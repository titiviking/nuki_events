from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import NukiDataCoordinator


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


class NukiBaseSensor(CoordinatorEntity[NukiDataCoordinator], SensorEntity):
    """Shared base for all Nuki event sensors.

    Stores the lock name so subclasses can reference it in device_info,
    and provides the device_info property that groups sensors under a
    single device card in the HA UI.
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

    def __init__(
        self,
        coordinator: NukiDataCoordinator,
        smartlock_id: int,
        lock_name: str,
    ) -> None:
        super().__init__(coordinator, smartlock_id, lock_name)
        self._attr_unique_id = f"nuki_events_{smartlock_id}_last_actor"
        self._attr_name = "Last Actor"

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

    def __init__(
        self,
        coordinator: NukiDataCoordinator,
        smartlock_id: int,
        lock_name: str,
    ) -> None:
        super().__init__(coordinator, smartlock_id, lock_name)
        self._attr_unique_id = f"nuki_events_{smartlock_id}_last_action"
        self._attr_name = "Last Action"

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