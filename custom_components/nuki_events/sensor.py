from __future__ import annotations

import logging

from homeassistant.components.sensor import RestoreSensor, SensorEntity
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import NukiDataCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    coordinator: NukiDataCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    entities = []
    for sl in coordinator.data.get("locks", []):
        sl_id = sl.get("smartlockId")
        if sl_id is None:
            continue
        sl_id = int(sl_id)
        name = sl.get("name") or f"Nuki {sl_id}"
        entities.append(NukiLastActorSensor(coordinator, sl_id, name))
        entities.append(NukiLastActionSensor(coordinator, sl_id, name))
    async_add_entities(entities)


class NukiBaseSensor(CoordinatorEntity[NukiDataCoordinator], RestoreSensor):
    """Shared base for all Nuki event sensors.

    Inherits RestoreSensor so that the last known state and attributes are
    persisted to HA storage before shutdown and restored on the next startup.
    This means sensors show their last value immediately after a reboot or
    integration update, even before the first webhook arrives or the Nuki API
    is reachable.

    Priority order on startup:
      1. Webhook received           -> coordinator updates, sensors re-render
      2. API priming succeeded      -> coordinator data populated (takes precedence)
      3. API priming failed / empty -> restored state fills the gap
      4. First ever boot            -> no prior state, sensors show 'unknown'
    """

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: NukiDataCoordinator,
        smartlock_id: int,
        lock_name: str,
    ) -> None:
        super().__init__(coordinator)
        self._id = smartlock_id
        self._lock_name = lock_name

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, str(self._id))},
            name=self._lock_name,
            manufacturer="Nuki",
            model="Smart Lock",
        )


class NukiLastActorSensor(NukiBaseSensor):
    _attr_icon = "mdi:account-key"
    # event_counter is a monotonically increasing integer - recording it would
    # write a new row on every lock event with no historical analytical value.
    # authId is a raw numeric key; the resolved name is already in native_value.
    _unrecorded_attributes = frozenset({"event_counter", "authId"})

    def __init__(
        self,
        coordinator: NukiDataCoordinator,
        smartlock_id: int,
        lock_name: str,
    ) -> None:
        super().__init__(coordinator, smartlock_id, lock_name)
        self._attr_unique_id = f"nuki_events_{smartlock_id}_last_actor"
        self._attr_translation_key = "last_actor"

    async def async_added_to_hass(self) -> None:
        """Restore last state when HA starts, then subscribe to coordinator updates."""
        await super().async_added_to_hass()

        # Only restore if the coordinator did not already prime a value from the API.
        if self.coordinator.data.get("last_actor", {}).get(self._id) is not None:
            return

        last_sensor_data = await self.async_get_last_sensor_data()
        if last_sensor_data is None:
            return

        restored_value = last_sensor_data.native_value
        if restored_value is None:
            return

        _LOGGER.debug(
            "Restoring last actor for smartlockId=%s: %r",
            self._id,
            restored_value,
        )

        # Seed the coordinator's in-memory state so that native_value reflects
        # the restored data immediately and all attribute reads are consistent.
        extra = (
            last_sensor_data.extra_data.as_dict()
            if last_sensor_data.extra_data
            else {}
        )
        self.coordinator.restore_state(self._id, actor=str(restored_value), extra=extra)

    @property
    def native_value(self):
        return self.coordinator.data.get("last_actor", {}).get(self._id)

    @property
    def extra_state_attributes(self):
        data = self.coordinator.data
        return {
            "authId": data.get("last_auth_id", {}).get(self._id),
            "action": data.get("last_action", {}).get(self._id),
            "trigger": data.get("last_trigger", {}).get(self._id),
            "completion_state": data.get("last_completion_state", {}).get(self._id),
            "source": data.get("last_source", {}).get(self._id),
            "deviceType": data.get("last_device_type", {}).get(self._id),
            "date": data.get("last_date", {}).get(self._id),
            "event_counter": data.get("event_counter", {}).get(self._id, 0),
        }


class NukiLastActionSensor(NukiBaseSensor):
    _attr_icon = "mdi:lock-alert"
    # event_counter changes on every lock event; no value in recording it in history.
    _unrecorded_attributes = frozenset({"event_counter"})

    def __init__(
        self,
        coordinator: NukiDataCoordinator,
        smartlock_id: int,
        lock_name: str,
    ) -> None:
        super().__init__(coordinator, smartlock_id, lock_name)
        self._attr_unique_id = f"nuki_events_{smartlock_id}_last_action"
        self._attr_translation_key = "last_action"

    async def async_added_to_hass(self) -> None:
        """Restore last state when HA starts, then subscribe to coordinator updates."""
        await super().async_added_to_hass()

        # Only restore if the coordinator did not already prime a value from the API.
        if self.coordinator.data.get("last_action", {}).get(self._id) is not None:
            return

        last_sensor_data = await self.async_get_last_sensor_data()
        if last_sensor_data is None:
            return

        restored_value = last_sensor_data.native_value
        if restored_value is None:
            return

        _LOGGER.debug(
            "Restoring last action for smartlockId=%s: %r",
            self._id,
            restored_value,
        )

        # Seed the coordinator so native_value and attributes are consistent
        # from the first render, before any webhook or API data arrives.
        extra = (
            last_sensor_data.extra_data.as_dict()
            if last_sensor_data.extra_data
            else {}
        )
        self.coordinator.restore_action_state(
            self._id, action=str(restored_value), extra=extra
        )

    @staticmethod
    def _format_action(action: str | None) -> str | None:
        if not action:
            return None

        # Keep unknown values intact to preserve debug visibility.
        if action.startswith("unknown("):
            return action

        return action.replace("_", " ").title()

    @property
    def native_value(self):
        action = self.coordinator.data.get("last_action", {}).get(self._id)
        return self._format_action(action)

    @property
    def extra_state_attributes(self):
        data = self.coordinator.data
        return {
            "actor": data.get("last_actor", {}).get(self._id),
            "trigger": data.get("last_trigger", {}).get(self._id),
            "source": data.get("last_source", {}).get(self._id),
            "completion_state": data.get("last_completion_state", {}).get(self._id),
            "date": data.get("last_date", {}).get(self._id),
            "event_counter": data.get("event_counter", {}).get(self._id, 0),
        }