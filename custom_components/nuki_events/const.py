from __future__ import annotations

DOMAIN = "nuki_events"
PLATFORMS = ["sensor"]

API_BASE = "https://api.nuki.io"
OAUTH2_AUTHORIZE = "https://api.nuki.io/oauth/authorize"
OAUTH2_TOKEN = "https://api.nuki.io/oauth/token"

WEBHOOK_PATH = "/api/nuki_events/webhook"

CONF_WEBHOOK_ID = "webhook_id"
CONF_WEBHOOK_SECRET = "webhook_secret"

WEBHOOK_FEATURE_DEVICE_STATUS = "DEVICE_STATUS"
WEBHOOK_FEATURE_DEVICE_LOGS = "DEVICE_LOGS"
WEBHOOK_FEATURE_DEVICE_AUTHS = "DEVICE_AUTHS"

DEFAULT_WEBHOOK_FEATURES = [
    WEBHOOK_FEATURE_DEVICE_STATUS,
    WEBHOOK_FEATURE_DEVICE_LOGS,
    WEBHOOK_FEATURE_DEVICE_AUTHS,
]

DEFAULT_SCOPES = [
    "account",
    "notification",
    "smartlock.readOnly",
    "smartlock.log",
    "smartlock.auth",
    "webhook.decentral",
    "offline_access",
]

EVENT_NUKI_WEBHOOK = f"{DOMAIN}_webhook"
EVENT_NUKI_LOCK_EVENT = f"{DOMAIN}_lock_event"

# Optional: simple feature set for quick checks
WEBHOOK_FEATURES = {
    WEBHOOK_FEATURE_DEVICE_STATUS,
    WEBHOOK_FEATURE_DEVICE_LOGS,
    WEBHOOK_FEATURE_DEVICE_AUTHS,
}

# ---------------------------------------------------------------------
# Nuki enum translations (from Nuki Web API documentation)
# ---------------------------------------------------------------------

NUKI_ACTION = {
    0: "none",
    1: "unlock",
    2: "lock",
    3: "unlatch",
    4: "lock_n_go",
    5: "lock_n_go_with_unlatch",
}

NUKI_TRIGGER = {
    0: "system",
    1: "manual",
    2: "button",
    3: "automatic",
    4: "app",
    5: "auto_lock",
    6: "keypad",
    7: "fingerprint",
}

NUKI_SOURCE = {
    0: "nuki_app",
    1: "web",
    2: "button",
    3: "bridge",
    4: "keypad",
    5: "fingerprint",
    6: "fob",
    7: "key",
}

NUKI_DEVICE_TYPE = {
    0: "smart_lock",
    2: "opener",
    3: "smart_door",
    4: "smart_lock_3",
    5: "smart_lock_4",
}

NUKI_COMPLETION_STATE = {
    0: "success",
    1: "motor_blocked",
    2: "canceled",
    3: "too_recent",
    4: "busy",
    5: "low_battery",
}

