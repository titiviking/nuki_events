"""The Nuki Events integration."""
from __future__ import annotations

from aiohttp import web

from homeassistant.components import webhook
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .api import NukiApi
from .const import (
    CONF_WEBHOOK_ID,
    CONF_NUKI_WEBHOOK_ID,
    DATA_API,
    DATA_LAST_EVENT,
    DATA_WEBHOOKS,
    DOMAIN,
    SIGNAL_EVENT_RECEIVED,
)

PLATFORMS: list[Platform] = [Platform.SENSOR]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the integration."""
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN].setdefault(DATA_WEBHOOKS, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Nuki Events from a config entry."""
    implementation = await config_entry_oauth2_flow.async_get_config_entry_implementation(
        hass, entry
    )
    session = config_entry_oauth2_flow.OAuth2Session(hass, entry, implementation)
    api = NukiApi(session)

    domain_data = hass.data.setdefault(DOMAIN, {})
    domain_data.setdefault(DATA_WEBHOOKS, {})
    domain_data[entry.entry_id] = {DATA_API: api, DATA_LAST_EVENT: None}

    webhook_id = entry.data.get(CONF_WEBHOOK_ID)
    if not webhook_id:
        webhook_id = webhook.async_generate_id()
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, CONF_WEBHOOK_ID: webhook_id}
        )

    domain_data[DATA_WEBHOOKS][webhook_id] = entry.entry_id

    webhook.async_register(
        hass,
        DOMAIN,
        "Nuki Events",
        webhook_id,
        _handle_webhook,
    )

    webhook_url = webhook.async_generate_url(hass, webhook_id)
    nuki_webhook_id = entry.data.get(CONF_NUKI_WEBHOOK_ID)
    if not nuki_webhook_id:
        nuki_webhook_id = await api.register_webhook(webhook_url)
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, CONF_NUKI_WEBHOOK_ID: nuki_webhook_id}
        )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    domain_data = hass.data.get(DOMAIN, {})
    webhook_id = entry.data.get(CONF_WEBHOOK_ID)
    nuki_webhook_id = entry.data.get(CONF_NUKI_WEBHOOK_ID)
    if webhook_id:
        webhook.async_unregister(hass, webhook_id)
        domain_data.get(DATA_WEBHOOKS, {}).pop(webhook_id, None)

    if nuki_webhook_id:
        api: NukiApi = domain_data[entry.entry_id][DATA_API]
        await api.unregister_webhook(nuki_webhook_id)

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        domain_data.pop(entry.entry_id, None)
    return unload_ok


async def _handle_webhook(
    hass: HomeAssistant, webhook_id: str, request: web.Request
) -> web.Response:
    """Handle webhook calls from Nuki."""
    payload = await request.json()
    domain_data = hass.data.get(DOMAIN, {})
    entry_id = domain_data.get(DATA_WEBHOOKS, {}).get(webhook_id)
    if not entry_id:
        return web.Response(status=404)

    api: NukiApi = domain_data[entry_id][DATA_API]
    event = await api.parse_event(payload)
    domain_data[entry_id][DATA_LAST_EVENT] = event
    async_dispatcher_send(hass, SIGNAL_EVENT_RECEIVED.format(entry_id))
    return web.Response(status=200)
