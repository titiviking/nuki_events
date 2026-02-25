from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import NukiDataCoordinator
from .const import DOMAIN


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    coordinator: NukiDataCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    entities = []
    for sl in coordinator.data.get("locks", []):
        sl_id = int(sl["smartlockId"])
        name = sl.get("name") or f"Nuki {sl_id}"
        entities.append(NukiLastActorSensor(coordinator, sl_id, name))
        entities.append(NukiLastActionSensor(coordinator, sl_id, name))
    async_add_entities(entities)


class NukiLastActorSensor(CoordinatorEntity[NukiDataCoordinator], SensorEntity):
    _attr_icon = "mdi:account-key"
    _attr_has_entity_name = True

    def __init__(self, coordinator: NukiDataCoordinator, smartlock_id: int, lock_name: str) -> None:
        super().__init__(coordinator)
        self._id = smartlock_id
        self._attr_unique_id = f"nuki_events_{smartlock_id}_last_actor"
        self._attr_name = f"{lock_name} last actor"

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


class NukiLastActionSensor(CoordinatorEntity[NukiDataCoordinator], SensorEntity):
    _attr_icon = "mdi:lock-alert"
    _attr_has_entity_name = True

    def __init__(self, coordinator: NukiDataCoordinator, smartlock_id: int, lock_name: str) -> None:
        super().__init__(coordinator)
        self._id = smartlock_id
        self._attr_unique_id = f"nuki_events_{smartlock_id}_last_action"
        self._attr_name = f"{lock_name} last action"

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
