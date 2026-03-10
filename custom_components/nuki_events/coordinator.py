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
    NUKI_LOG_STATE,
    NUKI_SOURCE,
    NUKI_TRIGGER,
)

_LOGGER = logging.getLogger(__name__)


class NukiDataCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Webhook-driven coordinator that stores 'last actor' per smartlock.

    On startup (first refresh), we fetch the most recent log entry per lock
    and resolve the actor name from the lock's auth list, so sensors show a
    meaningful value immediately rather than staying 'unknown' until the first
    webhook arrives.
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

        # Per-lock auth name cache: {sl_id: {auth_id: name}}.
        # Built during startup priming, invalidated when a DEVICE_AUTHS webhook
        # arrives so the next priming cycle picks up renames/additions.
        self._auth_name_cache: dict[int, dict[int, str]] = {}

    async def _async_update_data(self) -> dict[str, Any]:
        _LOGGER.debug("Coordinator update started")
        try:
            locks = await self.api.list_smartlocks()
            if not isinstance(locks, list):
                locks = []

            self._data["locks"] = locks

            # Prime last-actor info from latest logs so state isn't 'unknown' after restart.
            await self._prime_from_latest_logs(locks)

            return {k: dict(v) if isinstance(v, dict) else v for k, v in self._data.items()}

        except ConfigEntryAuthFailed:
            _LOGGER.exception("Coordinator auth failed (reauth required)")
            raise
        except Exception as err:
            _LOGGER.exception("Coordinator update failed: %s", err)
            raise UpdateFailed(str(err)) from err
        finally:
            _LOGGER.debug("Coordinator update finished")

    # ------------------------------------------------------------------
    # Auth name resolution
    # ------------------------------------------------------------------

    async def _fetch_auth_name_map(self, sl_id: int) -> dict[int, str]:
        """Return a mapping of {authId: name} for a given smartlock.

        Results are cached per lock for the lifetime of this coordinator instance.
        The cache is invalidated when a DEVICE_AUTHS webhook is received so that
        renames or new authorizations are reflected after the next HA reload or
        coordinator refresh.

        Returns an empty dict on any failure so callers degrade gracefully.
        """
        if sl_id in self._auth_name_cache:
            return self._auth_name_cache[sl_id]

        try:
            auths = await self.api.list_smartlock_auths(sl_id)
        except ConfigEntryAuthFailed:
            raise
        except Exception as err:
            _LOGGER.debug(
                "Priming: could not fetch auth list for smartlockId=%s: %s",
                sl_id,
                err,
            )
            return {}

        if not isinstance(auths, list):
            return {}

        name_map: dict[int, str] = {}
        for auth in auths:
            if not isinstance(auth, dict):
                continue
            auth_id = self._safe_int(auth.get("id") or auth.get("authId"))
            name = (
                auth.get("name")
                or auth.get("accountUserName")
                or auth.get("userName")
            )
            if auth_id is not None and name:
                name_map[auth_id] = name

        self._auth_name_cache[sl_id] = name_map
        return name_map

    # ------------------------------------------------------------------
    # Startup priming
    # ------------------------------------------------------------------

    async def _prime_from_latest_logs(self, locks: list[dict[str, Any]]) -> None:
        """Fetch the most recent log entry and resolve actor name for each lock."""
        for lock in locks:
            sl_id = self._safe_int(
                lock.get("smartlockId") or lock.get("smartlock_id") or lock.get("id")
            )
            if sl_id is None:
                continue

            # --- 1. Fetch the latest log entry ---
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

            # --- 2. Resolve actor name from auth list if log lacks a name ---
            # The /smartlock/{id}/log endpoint returns authId but frequently
            # omits the human-readable name.  We resolve it separately so the
            # sensor shows a real name rather than a raw numeric ID or "unknown".
            if not (
                latest.get("name")
                or latest.get("authName")
                or latest.get("accountUserName")
                or latest.get("userName")
            ):
                auth_id = self._safe_int(
                    latest.get("authId") or latest.get("auth_id")
                )
                if auth_id is not None:
                    auth_name_map = await self._fetch_auth_name_map(sl_id)
                    resolved_name = auth_name_map.get(auth_id)
                    if resolved_name:
                        # Inject the resolved name so _apply_log_event picks it up.
                        latest = dict(latest)
                        latest["name"] = resolved_name
                        _LOGGER.debug(
                            "Priming: resolved authId=%s → %r for smartlockId=%s",
                            auth_id,
                            resolved_name,
                            sl_id,
                        )
                    else:
                        _LOGGER.debug(
                            "Priming: authId=%s not found in auth list for smartlockId=%s",
                            auth_id,
                            sl_id,
                        )

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

            # Sometimes it's a single log entry already
            if any(k in raw for k in ("action", "date", "authId", "name", "state")):
                return raw

        return None

    # ------------------------------------------------------------------
    # Webhook handling
    # ------------------------------------------------------------------

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

            elif feature == "DEVICE_LOGS":
                # Webhook DEVICE_LOGS payloads include the actor name directly
                # in the smartlockLog object, so no auth lookup is needed here.
                self._apply_log_event(sl_id, event)

            elif feature == "DEVICE_AUTHS":
                # An authorization was added, removed, or renamed.  Invalidate
                # the cached name map for this lock so the next priming cycle
                # (on HA reload) fetches fresh data from the API.
                self._auth_name_cache.pop(sl_id, None)
                _LOGGER.debug(
                    "DEVICE_AUTHS webhook received for smartlockId=%s — auth name cache invalidated.",
                    sl_id,
                )

            else:
                # Feature is subscribed but not yet handled (e.g. DEVICE_MASTERDATA,
                # DEVICE_CONFIG).  Skip the state push to avoid spurious entity
                # re-renders when nothing actually changed.
                _LOGGER.debug(
                    "Unhandled webhook feature=%s for smartlockId=%s — ignoring.",
                    feature,
                    sl_id,
                )
                return

            self.async_set_updated_data({k: dict(v) if isinstance(v, dict) else v for k, v in self._data.items()})
            _LOGGER.debug(
                "Processed webhook for smartlockId=%s (feature=%s)",
                sl_id,
                feature,
            )

        except Exception as err:
            _LOGGER.exception("Failed processing webhook payload: %s", err)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

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