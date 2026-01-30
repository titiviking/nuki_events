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

    We fetch the locks list initially (and when HA explicitly refreshes),
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
            # Optional, but useful for future attributes/debugging
            "last_device_status": {},  # smartlockId -> DEVICE_STATUS payload
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

    def _normalize_webhook_payload(self, payload: dict[str, Any]) -> tuple[int | None, dict[str, Any]]:
        """Normalize Nuki webhook payloads into a flat event dict + smartlockId.

        Nuki sends different shapes:
        - DEVICE_STATUS: smartlockId at top-level, state nested under "state"
        - DEVICE_LOGS: smartlockId nested under "smartlockLog.smartlockId"
        """
        feature = payload.get("feature")

        # DEVICE_LOGS: unwrap smartlockLog
        if feature == "DEVICE_LOGS":
            smartlock_log = payload.get("smartlockLog")
            if isinstance(smartlock_log, dict):
                smartlock_id = smartlock_log.get("smartlockId")
                event = dict(smartlock_log)
                event["feature"] = feature
                return self._safe_int(smartlock_id), event

        # DEVICE_STATUS (and other potential future features): top-level smartlockId
        smartlock_id = payload.get("smartlockId") or payload.get("smartlock_id")
        return self._safe_int(smartlock_id), payload

    @staticmethod
    def _safe_int(value: Any) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    async def async_handle_webhook(self, entry_id: str, payload: dict[str, Any]) -> None:
        """Handle a verified webhook payload and update coordinator state."""
        try:
            sl_id, event = self._normalize_webhook_payload(payload)
            if sl_id is None:
                _LOGGER.debug("Webhook payload missing smartlockId: %s", payload)
                return

            feature = event.get("feature")

            # Store status payloads (useful, and keeps the log clean)
            if feature == "DEVICE_STATUS":
                # Keep the full payload so we can expose battery/door state later if desired
                self._data["last_device_status"][sl_id] = event

            # Update "last actor" and log-derived fields when we get a log event
            # DEVICE_LOGS are the ones that include name/authId/action/date.
            if feature == "DEVICE_LOGS":
                auth_id = event.get("authId") or event.get("auth_id")
                name = (
                    event.get("name")
                    or event.get("authName")
                    or event.get("accountUserName")
                    or event.get("userName")
                )
                actor = name or (str(auth_id) if auth_id is not None else "unknown")

                self._data["last_actor"][sl_id] = actor
                if auth_id is not None:
                    self._data["last_auth_id"][sl_id] = auth_id

                # Copy over common fields when present (from the unwrapped smartlockLog dict)
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
                    if key in event:
                        self._data[target][sl_id] = event.get(key)

            # Count every event per lock (status + logs)
            self._data["event_counter"][sl_id] = int(self._data["event_counter"].get(sl_id, 0)) + 1

            # Push update to entities
            self.async_set_updated_data(dict(self._data))
            _LOGGER.debug("Processed webhook for smartlockId=%s (feature=%s)", sl_id, feature)

        except Exception as err:
            _LOGGER.exception("Failed processing webhook payload: %s", err)
