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
    """Webhook-driven coordinator that stores 'last actor' per smartlock.

    On startup (first refresh), we also fetch the most recent logs per lock to avoid
    the sensor staying 'unknown' until the first webhook arrives.
    """

    def __init__(self, hass: HomeAssistant, api: NukiApi) -> None:
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=None)
        self.api = api

        self._data: dict[str, Any] = {
            "locks": [],
            "last_actor": {},
            "last_auth_id": {},
            "last_action": {},
            "last_trigger": {},
            "last_completion_state": {},  # mapped from log "state"
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

            # Prime last-actor info from latest logs so state isn't 'unknown' after restart
            await self._prime_from_latest_logs(locks)

            return dict(self._data)

        except ConfigEntryAuthFailed:
            _LOGGER.exception("Coordinator auth failed (reauth required)")
            raise
        except Exception as err:
            _LOGGER.exception("Coordinator update failed: %s", err)
            raise UpdateFailed(str(err)) from err
        finally:
            _LOGGER.debug("Coordinator update finished")

    async def _prime_from_latest_logs(self, locks: list[dict[str, Any]]) -> None:
        """Fetch and apply the most recent log entry for each lock (limit=1)."""
        for lock in locks:
            sl_id = self._safe_int(
                lock.get("smartlockId") or lock.get("smartlock_id") or lock.get("id")
            )
            if sl_id is None:
                continue

            try:
                raw = await self.api.list_smartlock_logs(sl_id, limit=1)
            except ConfigEntryAuthFailed:
                raise
            except Exception as err:
                _LOGGER.debug(
                    "Priming: failed to fetch latest log for smartlockId=%s: %s",
                    sl_id,
                    err,
                )
                continue

            latest = self._extract_latest_log(raw)
            if not latest:
                _LOGGER.debug("Priming: no logs returned for smartlockId=%s", sl_id)
                continue

            self._apply_log_event(sl_id, latest)

    @staticmethod
    def _extract_latest_log(raw: Any) -> dict[str, Any] | None:
        """Normalize possible log response shapes into a single latest log dict."""
        if raw is None:
            return None

        # Common case: list of logs
        if isinstance(raw, list):
            return raw[0] if raw else None

        # Wrapped dict cases
        if isinstance(raw, dict):
            for key in ("smartlockLogs", "logs", "items", "data", "results"):
                val = raw.get(key)
                if isinstance(val, list):
                    return val[0] if val else None

            # Sometimes it’s a single log entry already
            if any(k in raw for k in ("action", "date", "authId", "name", "state")):
                return raw

        return None

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

    def _apply_log_event(self, sl_id: int, event: dict[str, Any]) -> None:
        """Apply a log event to coordinator state (used by both webhook + priming)."""
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

        # DEVICE_LOGS include "state": completion state enum
        if "state" in event:
            self._data["last_completion_state"][sl_id] = self._label(NUKI_LOG_STATE, event["state"])

        if "date" in event:
            self._data["last_date"][sl_id] = event["date"]

        # Count as an event (consistent)
        self._data["event_counter"][sl_id] = self._data["event_counter"].get(sl_id, 0) + 1

    async def async_handle_webhook(self, entry_id: str, payload: dict[str, Any]) -> None:
        try:
            sl_id, event = self._normalize_webhook_payload(payload)
            if sl_id is None:
                _LOGGER.debug("Webhook payload missing smartlockId: %s", payload)
                return

            feature = event.get("feature")

            if feature == "DEVICE_STATUS":
                self._data["last_device_status"][sl_id] = event
                self._data["event_counter"][sl_id] = self._data["event_counter"].get(sl_id, 0) + 1

            if feature == "DEVICE_LOGS":
                self._apply_log_event(sl_id, event)

            self.async_set_updated_data(dict(self._data))
            _LOGGER.debug(
                "Processed webhook for smartlockId=%s (feature=%s)",
                sl_id,
                feature,
            )

        except Exception as err:
            _LOGGER.exception("Failed processing webhook payload: %s", err)
