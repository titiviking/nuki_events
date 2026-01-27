from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import NukiApi
from .const import (
    WEBHOOK_FEATURE_DEVICE_STATUS,
    WEBHOOK_FEATURE_DEVICE_LOGS,
    WEBHOOK_FEATURE_DEVICE_AUTHS,
    EVENT_NUKI_WEBHOOK,
    EVENT_NUKI_LOCK_EVENT,
)

_LOGGER = logging.getLogger(__name__)

TRIGGER_LABEL = {
    0: "System (Bluetooth)",
    1: "Manual",
    2: "Button",
    3: "Automatic",
    4: "Web",
    5: "App",
    6: "Auto lock",
    7: "Accessory",
    255: "Keypad",
}

ACTION_LABEL = {
    1: "unlock",
    2: "lock",
    3: "unlatch",
    4: "lock_n_go",
    5: "lock_n_go_unlatch",
    208: "door_sensor_jammed",
    209: "door_sensor_error",
    224: "keypad_battery_critical",
    225: "keypad_battery_low",
    226: "keypad_battery_ok",
    240: "door_opened",
    241: "door_closed",
    243: "firmware_update",
    252: "initialization",
    253: "calibration",
    254: "log_enabled",
    255: "log_disabled"
}

COMPLETION_STATE_LABEL = {
    0: "success",
    1: "motor_blocked",
    2: "canceled",
    3: "too_recent",
    4: "busy",
    5: "low_motor_voltage",
    6: "clutch_failure",
    7: "motor_power_failure",
    8: "incomplete",
    9: "other_error",
    10: "rejected_night_mode",
    254: "other_error",
    255: "unknown_error",
}

SOURCE_LABEL = {0: "default", 1: "keypad_code", 2: "fingerprint"}


class NukiDataCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    def __init__(self, hass, api: NukiApi) -> None:
        self.api = api
        super().__init__(hass, _LOGGER, name="Nuki Events", update_interval=timedelta(hours=6))

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            locks = await self.api.list_smartlocks()
            prior = self.data or {}
            auth_map: dict[str, str] = prior.get("auth_map", {})

            try:
                for a in await self.api.get_all_auths() or []:
                    auth_id = a.get("authId")
                    name = a.get("name")
                    if auth_id is not None and name:
                        auth_map[str(auth_id)] = str(name)
            except Exception as err:
                _LOGGER.debug("Auth list refresh skipped/failed: %s", err)

            return {
                "locks": locks,
                "auth_map": auth_map,
                "last_actor": prior.get("last_actor", {}),
                "last_auth_id": prior.get("last_auth_id", {}),
                "last_action": prior.get("last_action", {}),
                "last_trigger": prior.get("last_trigger", {}),
                "last_date": prior.get("last_date", {}),
                "last_completion_state": prior.get("last_completion_state", {}),
                "last_source": prior.get("last_source", {}),
                "last_device_type": prior.get("last_device_type", {}),
                "event_counter": prior.get("event_counter", {}),
            }
        except Exception as err:
            raise UpdateFailed(str(err)) from err

    def _bump_counter(self, current: dict[str, Any], smartlock_id: int) -> int:
        counter = int(current.get("event_counter", {}).get(smartlock_id, 0)) + 1
        current.setdefault("event_counter", {})[smartlock_id] = counter
        return counter

    async def async_handle_webhook(self, entry_id: str, payload: dict[str, Any]) -> None:
        _LOGGER.debug("Handling Nuki webhook payload (entry=%s): %s", entry_id, payload)
        self.hass.bus.async_fire(EVENT_NUKI_WEBHOOK, {"entry_id": entry_id, "payload": payload})

        current = self.data or {
            "locks": [],
            "auth_map": {},
            "last_actor": {},
            "last_auth_id": {},
            "last_action": {},
            "last_trigger": {},
            "last_date": {},
            "last_completion_state": {},
            "last_source": {},
            "last_device_type": {},
            "event_counter": {},
        }

        feature = payload.get("feature")
        log = payload.get("smartlockLog") or {}
        auth_map: dict[str, str] = current.get("auth_map", {})

        if feature == WEBHOOK_FEATURE_DEVICE_AUTHS:
            auth = payload.get("smartlockAuth") or {}
            deleted = bool(payload.get("deleted", False))
            auth_id = auth.get("authId")
            name = auth.get("name")

            if auth_id is not None:
                aid = str(auth_id)
                if deleted:
                    auth_map.pop(aid, None)
                elif name:
                    auth_map[aid] = str(name)
            current["auth_map"] = auth_map

            self.hass.bus.async_fire(
                EVENT_NUKI_LOCK_EVENT,
                {
                    "entry_id": entry_id,
                    "feature": feature,
                    "smartlockId": auth.get("smartlockId") or payload.get("smartlockId"),
                    "authId": str(auth_id) if auth_id is not None else None,
                    "username": auth_map.get(str(auth_id)) if auth_id is not None else None,
                    "deleted": deleted,
                },
            )
            self.async_set_updated_data(current)
            return

        if feature == WEBHOOK_FEATURE_DEVICE_STATUS:
            state_obj = payload.get("state") or {}
            self.hass.bus.async_fire(
                EVENT_NUKI_LOCK_EVENT,
                {
                    "entry_id": entry_id,
                    "feature": feature,
                    "smartlockId": state_obj.get("smartlockId") or payload.get("smartlockId"),
                    "state": state_obj,
                },
            )
            self.async_set_updated_data(current)
            return

        if feature == WEBHOOK_FEATURE_DEVICE_LOGS:
            smartlock_id_val = log.get("smartlockId") or payload.get("smartlockId")
            if smartlock_id_val is None:
                await self.async_request_refresh()
                return
            smartlock_id = int(smartlock_id_val)

            auth_id = log.get("authId")
            auth_id_str = str(auth_id) if auth_id is not None else None

            name = log.get("name")
            if name:
                actor = str(name)
            elif auth_id_str and auth_id_str in auth_map:
                actor = auth_map[auth_id_str]
            else:
                trig = log.get("trigger")
                try:
                    trig_i = int(trig) if trig is not None else None
                except Exception:
                    trig_i = None
                actor = TRIGGER_LABEL.get(trig_i, "Unknown") if trig_i is not None else "Unknown"

            def to_int(v):
                try:
                    return int(v) if v is not None else None
                except Exception:
                    return None

            action_i = to_int(log.get("action"))
            trigger_i = to_int(log.get("trigger"))
            completion_i = to_int(log.get("state"))
            source_i = to_int(log.get("source"))

            action = ACTION_LABEL.get(action_i, log.get("action"))
            trigger = TRIGGER_LABEL.get(trigger_i, log.get("trigger"))
            completion_state = COMPLETION_STATE_LABEL.get(completion_i, log.get("state"))
            source = SOURCE_LABEL.get(source_i, log.get("source"))

            device_type = log.get("deviceType")
            date = log.get("date")
            auto_unlock = log.get("autoUnlock")

            current["last_actor"][smartlock_id] = actor
            current["last_auth_id"][smartlock_id] = auth_id_str
            current["last_action"][smartlock_id] = action
            current["last_trigger"][smartlock_id] = trigger
            current["last_completion_state"][smartlock_id] = completion_state
            current["last_source"][smartlock_id] = source
            current["last_device_type"][smartlock_id] = device_type
            current["last_date"][smartlock_id] = date

            counter = self._bump_counter(current, smartlock_id)

            self.hass.bus.async_fire(
                EVENT_NUKI_LOCK_EVENT,
                {
                    "entry_id": entry_id,
                    "feature": feature,
                    "smartlockId": smartlock_id,
                    "actor": actor,
                    "authId": auth_id_str,
                    "username": auth_map.get(auth_id_str) if auth_id_str else None,
                    "action": action,
                    "trigger": trigger,
                    "completion_state": completion_state,
                    "source": source,
                    "deviceType": device_type,
                    "autoUnlock": auto_unlock,
                    "date": date,
                    "event_counter": counter,
                },
            )

            self.async_set_updated_data(current)
            return

        await self.async_request_refresh()
