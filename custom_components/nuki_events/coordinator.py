from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import NukiApi
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


class NukiDataCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Webhook-driven coordinator that stores 'last actor' per smartlock.

    We only fetch the locks list initially (and when HA explicitly refreshes),
    then update entity state when a verified webhook arrives.
    """

    def __init__(self, hass: HomeAssistant, api: NukiApi) -> None:
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=None)
        self.api = api

        # Data shape expected by sensor.py
        self._data: dict[str, Any] = {
            "locks": [],
            "last_actor": {},
            "last_auth_id": {},
            "last_action": {},
            "last_trigger": {},
            "last_completion_state": {},
            "last_source": {},
            "last_device_type": {},
            "last_date": {},
            "event_counter": {},
        }

    async def _async_update_data(self) -> dict[str, Any]:
        """Initial fetch of locks list."""
        _LOGGER.debug("Coordinator update started")
        try:
            locks = await self.api.list_smartlocks()
            if locks is None:
                locks = []
            if not isinstance(locks, list):
                _LOGGER.debug("Unexpected smartlock list response: %r", locks)
                locks = []

            self._data["locks"] = locks
            return dict(self._data)

        except ConfigEntryAuthFailed:
            _LOGGER.exception("Coordinator auth failed (reauth required)")
            raise
        except Exception as err:
            _LOGGER.exception("Coordinator update failed: %s", err)
            raise UpdateFailed(str(err)) from err
        finally:
            _LOGGER.debug("Coordinator update finished")

    async def async_handle_webhook(self, entry_id: str, payload: dict[str, Any]) -> None:
        """Handle a verified webhook payload and update coordinator state."""
        try:
            smartlock_id = payload.get("smartlockId") or payload.get("smartlock_id")
            if smartlock_id is None:
                _LOGGER.debug("Webhook payload missing smartlockId: %s", payload)
                return

            try:
                sl_id = int(smartlock_id)
            except (TypeError, ValueError):
                _LOGGER.debug("Webhook smartlockId not an int: %r", smartlock_id)
                return

            auth_id = payload.get("authId") or payload.get("auth_id")
            name = (
                payload.get("name")
                or payload.get("authName")
                or payload.get("accountUserName")
                or payload.get("userName")
            )

            actor = name or (str(auth_id) if auth_id is not None else "unknown")

            self._data["last_actor"][sl_id] = actor
            if auth_id is not None:
                self._data["last_auth_id"][sl_id] = auth_id

            # Copy over common fields when present
            for key, target in (
                ("action", "last_action"),
                ("trigger", "last_trigger"),
                ("completionState", "last_completion_state"),
                ("completion_state", "last_completion_state"),
                ("source", "last_source"),
                ("deviceType", "last_device_type"),
                ("device_type", "last_device_type"),
                ("date", "last_date"),
                ("timestamp", "last_date"),
            ):
                if key in payload:
                    self._data[target][sl_id] = payload.get(key)

            self._data["event_counter"][sl_id] = int(self._data["event_counter"].get(sl_id, 0)) + 1

            # Push update to entities
            self.async_set_updated_data(dict(self._data))
            _LOGGER.debug("Processed webhook for smartlockId=%s (actor=%s)", sl_id, actor)

        except Exception as err:
            _LOGGER.exception("Failed processing webhook payload: %s", err)
