from __future__ import annotations

import logging

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

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    return True


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

    # Pass the OAuth session to the API client (so requests always have a valid token).
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

    existing_webhook_id = entry.data.get(CONF_WEBHOOK_ID)
    existing_secret = entry.data.get(CONF_WEBHOOK_SECRET)
    if existing_webhook_id and existing_secret:
        _LOGGER.debug(
            "Using existing Nuki webhook configuration (entry=%s, id=%s)",
            entry.entry_id,
            existing_webhook_id,
        )
    else:
        # Webhook registration is useful, but should never block the integration
        # from setting up entities. If registration fails, we log and proceed.
        try:
            base = get_url(hass, prefer_external=True)
        except Exception as err:
            _LOGGER.error(
                "Cannot compute external URL for Nuki webhook registration (entry=%s): %s",
                entry.entry_id,
                err,
            )
        else:
            webhook_url = f"{base}{WEBHOOK_PATH}/{entry.entry_id}"
            _LOGGER.debug("Computed external webhook URL for Nuki: %s", webhook_url)

            try:
                resp = await api.register_decentral_webhook(
                    webhook_url=webhook_url, features=DEFAULT_WEBHOOK_FEATURES
                )

                if not isinstance(resp, dict):
                    _LOGGER.error(
                        "Unexpected response while registering Nuki decentral webhook "
                        "(expected dict, got %s): %r",
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
                        try:
                            webhook_id_int = int(webhook_id)
                        except (TypeError, ValueError):
                            _LOGGER.error(
                                "Nuki returned non-integer webhook id %r (entry=%s)",
                                webhook_id,
                                entry.entry_id,
                            )
                        else:
                            new_data[CONF_WEBHOOK_ID] = webhook_id_int
                            hass.data[DOMAIN][entry.entry_id]["webhook_id"] = webhook_id_int

                    if secret:
                        new_data[CONF_WEBHOOK_SECRET] = secret
                        hass.data[DOMAIN][entry.entry_id]["webhook_secret"] = secret

                    if new_data != entry.data:
                        hass.config_entries.async_update_entry(entry, data=new_data)

            except Exception as err:
                _LOGGER.error(
                    "Failed to register Nuki decentral webhook (entry=%s): %s",
                    entry.entry_id,
                    err,
                    exc_info=True,
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
        except Exception as err:
            _LOGGER.warning(
                "Could not delete Nuki decentral webhook id=%s: %s",
                webhook_id,
                err,
            )

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok
