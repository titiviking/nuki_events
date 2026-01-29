from __future__ import annotations

import logging
import time
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.network import get_url
from homeassistant.helpers import config_entry_oauth2_flow

from .api import NukiApi
from .coordinator import NukiDataCoordinator
from .const import (
    DOMAIN,
    PLATFORMS,
    WEBHOOK_PATH,
    DEFAULT_WEBHOOK_FEATURES,
    CONF_WEBHOOK_ID,
    CONF_WEBHOOK_SECRET,
)
from .webhook import NukiWebhookView

_LOGGER = logging.getLogger("custom_components.nuki_events")


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    return True


def _ensure_expires_at(entry: ConfigEntry) -> dict[str, Any] | None:
    """Ensure OAuth token has expires_at (HA requires it).

    Some token stores only persist expires_in. Home Assistant's OAuth2Session
    expects expires_at to be present and will raise KeyError otherwise.
    """
    token: dict[str, Any] = dict(entry.data.get("token") or {})
    if not token:
        return None

    if "expires_at" in token:
        return None

    expires_in = token.get("expires_in")
    if expires_in is None:
        return None

    try:
        expires_in_int = int(expires_in)
    except (TypeError, ValueError):
        return None

    # now + expires_in minus a small safety margin
    token["expires_at"] = time.time() + expires_in_int - 60
    return token


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})

    # Register webhook view once
    if not hass.data[DOMAIN].get("_view_registered"):
        hass.http.register_view(NukiWebhookView(hass))
        hass.data[DOMAIN]["_view_registered"] = True

    # --- HA-native OAuth session ---
    implementation = await config_entry_oauth2_flow.async_get_config_entry_implementation(
        hass, entry
    )
    oauth_session = config_entry_oauth2_flow.OAuth2Session(hass, entry, implementation)

    # Fix KeyError: 'expires_at' by normalizing stored token
    new_token = _ensure_expires_at(entry)
    if new_token is not None:
        _LOGGER.debug(
            "OAuth token missing expires_at; normalizing and updating config entry (entry_id=%s)",
            entry.entry_id,
        )
        new_data = dict(entry.data)
        new_data["token"] = new_token
        hass.config_entries.async_update_entry(entry, data=new_data)

    # API client using HA-managed OAuth session
    api = NukiApi(hass, entry, oauth_session=oauth_session)

    coordinator = NukiDataCoordinator(hass, api)
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = {
        "coordinator": coordinator,
        "webhook_secret": entry.data.get(CONF_WEBHOOK_SECRET),
        "webhook_id": entry.data.get(CONF_WEBHOOK_ID),
        "api": api,
        "oauth_session": oauth_session,
    }

    # Webhook registration (best-effort; do not block entity setup)
    existing_webhook_id = entry.data.get(CONF_WEBHOOK_ID)
    existing_secret = entry.data.get(CONF_WEBHOOK_SECRET)

    if existing_webhook_id and existing_secret:
        _LOGGER.debug(
            "Using existing Nuki webhook configuration (entry=%s, id=%s)",
            entry.entry_id,
            existing_webhook_id,
        )
    else:
        try:
            base = get_url(hass, prefer_external=True)
        except Exception:
            _LOGGER.exception(
                "Cannot compute external URL for Nuki webhook registration (entry=%s)",
                entry.entry_id,
            )
        else:
            webhook_url = f"{base}{WEBHOOK_PATH}/{entry.entry_id}"
            _LOGGER.debug("Computed external webhook URL for Nuki: %s", webhook_url)

            try:
                resp: Any = await api.register_decentral_webhook(
                    webhook_url=webhook_url, features=DEFAULT_WEBHOOK_FEATURES
                )

                if not isinstance(resp, dict):
                    _LOGGER.error(
                        "Webhook registration returned non-dict response (type=%s): %r",
                        type(resp).__name__,
                        resp,
                    )
                else:
                    webhook_id = resp.get("id")
                    secret = resp.get("secret")

                    _LOGGER.info(
                        "Registered Nuki decentral webhook (entry=%s, id=%s)",
                        entry.entry_id,
                        webhook_id,
                    )

                    new_data = dict(entry.data)
                    if webhook_id is not None:
                        new_data[CONF_WEBHOOK_ID] = int(webhook_id)
                        hass.data[DOMAIN][entry.entry_id]["webhook_id"] = int(webhook_id)
                    if secret:
                        new_data[CONF_WEBHOOK_SECRET] = secret
                        hass.data[DOMAIN][entry.entry_id]["webhook_secret"] = secret

                    hass.config_entries.async_update_entry(entry, data=new_data)

            except Exception:
                _LOGGER.exception(
                    "Failed to register Nuki decentral webhook (entry=%s)",
                    entry.entry_id,
                )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    data = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
    api: NukiApi | None = data.get("api")
    webhook_id = data.get("webhook_id") or entry.data.get(CONF_WEBHOOK_ID)

    if api and webhook_id:
        try:
            await api.delete_decentral_webhook(int(webhook_id))
            _LOGGER.info(
                "Deleted Nuki decentral webhook id=%s (entry=%s)",
                webhook_id,
                entry.entry_id,
            )
        except Exception:
            _LOGGER.exception(
                "Could not delete Nuki decentral webhook id=%s (entry=%s)",
                webhook_id,
                entry.entry_id,
            )

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok
