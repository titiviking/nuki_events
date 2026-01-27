"""Sensor platform for Nuki Events."""
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import NukiEvent
from .const import (
    ATTR_SMARTLOCK_NAME,
    ATTR_SOURCE,
    ATTR_TIMESTAMP,
    DATA_LAST_EVENT,
    DOMAIN,
    SIGNAL_EVENT_RECEIVED,
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Nuki Event sensors."""
    async_add_entities([SmartlockLastActorSensor(hass, entry.entry_id)])


class SmartlockLastActorSensor(SensorEntity):
    """Show the last smartlock actor."""

    _attr_has_entity_name = True
    _attr_name = "Smartlock Last Actor"

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        """Initialize the sensor."""
        self._hass = hass
        self._entry_id = entry_id
        self._attr_unique_id = f"{entry_id}_smartlock_last_actor"
        self._event: NukiEvent | None = None
        self._unsub_dispatcher = None

    async def async_added_to_hass(self) -> None:
        """Register callbacks."""
        self._unsub_dispatcher = async_dispatcher_connect(
            self.hass,
            SIGNAL_EVENT_RECEIVED.format(self._entry_id),
            self._async_handle_event,
        )
        self._load_event()

    async def async_will_remove_from_hass(self) -> None:
        """Clean up callbacks."""
        if self._unsub_dispatcher:
            self._unsub_dispatcher()
            self._unsub_dispatcher = None

    @property
    def native_value(self) -> str | None:
        """Return the actor name."""
        return self._event.actor if self._event else None

    @property
    def extra_state_attributes(self) -> dict[str, str | None]:
        """Return the state attributes."""
        if not self._event:
            return {}
        return {
            ATTR_TIMESTAMP: self._event.timestamp,
            ATTR_SMARTLOCK_NAME: self._event.smartlock_name,
            ATTR_SOURCE: self._event.source,
        }

    def _load_event(self) -> None:
        domain_data = self.hass.data.get(DOMAIN, {})
        event = domain_data.get(self._entry_id, {}).get(DATA_LAST_EVENT)
        if event:
            self._event = event

    def _async_handle_event(self) -> None:
        self._load_event()
        self.async_write_ha_state()
