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

]

EVENT_NUKI_WEBHOOK = f"{DOMAIN}_webhook"
EVENT_NUKI_LOCK_EVENT = f"{DOMAIN}_lock_event"
