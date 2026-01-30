from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import NukiApi
from .const import (
    DOMAIN,
    NUKI_ACTION,
    NUKI_DEVICE_TYPE,
    NUKI_SOURCE,
    NUKI_TRIGGER,
    NUKI_LOG_STATE,
)

_LOGGER = logging.getLogger(__name__)


class NukiDataCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Webhook-driven coordinator that stores 'last actor' per smartlock."""

    def __init__(self, hass: HomeAssistant, api: NukiApi) -> None:
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=None)
        self.api = api

        self._data: dict[str, Any] = {
            "locks": [],
            "last_actor": {},
            "last_auth_id": {},
            "last_action": {},
            "last_trigger": {},
            "last_completion_state": {},  # kept for backwards compatibility: now mapped from log "state"
            "last_source": {},
            "last_device_type": {},
            "last_date": {},
            "event_counter": {},
            "last_device_status": {},
        }

    async def _async_update_data(self) -> dict[str, Any]:
        _LOGGER.debug("Coordinator update started")
        try:
            locks = await self.api.list_smartlocks()
            if not isinstance(locks, list):
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

    def _normalize_webhook_payload(
        self, payload: dict[str, Any]
    ) -> tuple[int | None, dict[str, Any]]:
        feature = payload.get("feature")

        if feature == "DEVICE_LOGS":
            smartlock_log = payload.get("smartlockLog")
            if isinstance(smartlock_log, dict):
                smartlock_id = smartlock_log.get("smartlockId")
                event = dict(smartlock_log)
                event["feature"] = feature
                return self._safe_int(smartlock_id), event

        smartlock_id = payload.get("smartlockId") or payload.get("smartlock_id")
        return self._safe_int(smartlock_id), payload

    @staticmethod
    def _safe_int(value: Any) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _label(mapping: dict[int, str], raw: Any) -> str:
        try:
            raw_int = int(raw)
        except (TypeError, ValueError):
            return "unknown"
        return mapping.get(raw_int, f"unknown({raw_int})")

    async def async_handle_webhook(self, entry_id: str, payload: dict[str, Any]) -> None:
        try:
            sl_id, event = self._normalize_webhook_payload(payload)
            if sl_id is None:
                _LOGGER.debug("Webhook payload missing smartlockId: %s", payload)
                return

            feature = event.get("feature")

            if feature == "DEVICE_STATUS":
                self._data["last_device_status"][sl_id] = event

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

                if "action" in event:
                    self._data["last_action"][sl_id] = self._label(NUKI_ACTION, event["action"])

                if "trigger" in event:
                    self._data["last_trigger"][sl_id] = self._label(NUKI_TRIGGER, event["trigger"])

                if "source" in event:
                    self._data["last_source"][sl_id] = self._label(NUKI_SOURCE, event["source"])

                if "deviceType" in event:
                    self._data["last_device_type"][sl_id] = self._label(NUKI_DEVICE_TYPE, event["deviceType"])

                # ✅ FIX: map log "state" (not completionState) into last_completion_state
                # Nuki DEVICE_LOGS include "state": numeric enum
                if "state" in event:
                    self._data["last_completion_state"][sl_id] = self._label(NUKI_LOG_STATE, event["state"])

                if "date" in event:
                    self._data["last_date"][sl_id] = event["date"]

            self._data["event_counter"][sl_id] = self._data["event_counter"].get(sl_id, 0) + 1

            self.async_set_updated_data(dict(self._data))
            _LOGGER.debug(
                "Processed webhook for smartlockId=%s (feature=%s)",
                sl_id,
                feature,
            )

        except Exception as err:
            _LOGGER.exception("Failed processing webhook payload: %s", err)
