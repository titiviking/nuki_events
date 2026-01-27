"""Constants for the Nuki Events integration."""

DOMAIN = "nuki_events"

CONF_WEBHOOK_ID = "webhook_id"
CONF_NUKI_WEBHOOK_ID = "nuki_webhook_id"
DATA_API = "api"
DATA_LAST_EVENT = "last_event"
DATA_WEBHOOKS = "webhooks"

SIGNAL_EVENT_RECEIVED = "nuki_events_event_received_{}"

DEFAULT_OAUTH_NAME = "Nuki"

NUKI_BASE_URL = "https://api.nuki.io"
NUKI_OAUTH_AUTHORIZE = "https://web.nuki.io/oauth/authorize"
NUKI_OAUTH_TOKEN = "https://web.nuki.io/oauth/token"

ATTR_TIMESTAMP = "timestamp"
ATTR_SMARTLOCK_NAME = "smartlock_name"
ATTR_SOURCE = "source"
