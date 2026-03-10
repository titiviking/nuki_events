from __future__ import annotations

import logging
import time
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.helpers.network import get_url

from .api import NukiApi
from .coordinator import NukiDataCoordinator
from .const import (
    CONF_WEBHOOK_ID,
    CONF_WEBHOOK_SECRET,
    DEFAULT_WEBHOOK_FEATURES,
    DOMAIN,
    PLATFORMS,
    WEBHOOK_PATH,
)
from .webhook import NukiWebhookView

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the integration via YAML (not used, but required by HA loader)."""
    return True


def _normalize_and_enrich_token(entry: ConfigEntry) -> dict[str, Any] | None:
    """Normalize OAuth token shape and ensure expires_at is available.

    Older versions may store token fields at the top-level of entry.data.
    Convert that shape into the expected ``{"token": {...}}`` layout and add
    ``expires_at`` when possible.
    """
    token_data = entry.data.get("token")
    if isinstance(token_data, dict):
        token: dict[str, Any] = dict(token_data)
    elif "access_token" in entry.data:
        token = {
            key: entry.data[key]
            for key in (
                "access_token",
                "token_type",
                "refresh_token",
                "expires_in",
                "scope",
                "expires_at",
            )
            if key in entry.data
        }
    else:
        token = {}

    if not token:
        return None

    changed = token_data != token

    if "expires_at" in token:
        return token if changed else None

    expires_in = token.get("expires_in")
    if expires_in is None:
        return None

    try:
        expires_in_int = int(expires_in)
    except (TypeError, ValueError):
        return token if changed else None

    # Use wall clock here; HA's OAuth2Session expects epoch seconds for expires_at
    token["expires_at"] = time.time() + expires_in_int - 60
    return token


async def _ensure_webhook_registered(
    hass: HomeAssistant,
    entry: ConfigEntry,
    api: NukiApi,
) -> None:
    """Ensure a valid decentral webhook is registered with Nuki.

    On every entry load we verify the stored webhook_id still exists on the
    Nuki server side.  If the webhook is gone (e.g. the user reset their Nuki
    account, revoked the token, or the webhook was deleted externally) we clear
    the stale id/secret and re-register so push events are not silently lost.

    All failures are treated as non-fatal: a warning is logged and entity setup
    continues.  The integration can still poll for state on the next coordinator
    refresh — it just won't receive real-time push events until the next
    successful HA reload or until the webhook is restored manually.
    """
    existing_webhook_id = entry.data.get(CONF_WEBHOOK_ID)
    existing_secret = entry.data.get(CONF_WEBHOOK_SECRET)

    needs_registration = True  # default: register unless we confirm it's live

    if existing_webhook_id and existing_secret:
        # Verify the stored webhook still exists on the Nuki server.
        try:
            registered = await api.list_decentral_webhooks()
            if isinstance(registered, list):
                live_ids = {
                    int(w["id"])
                    for w in registered
                    if isinstance(w, dict) and w.get("id") is not None
                }
                if int(existing_webhook_id) in live_ids:
                    _LOGGER.debug(
                        "Nuki webhook id=%s is still active; skipping re-registration.",
                        existing_webhook_id,
                    )
                    needs_registration = False
                else:
                    _LOGGER.warning(
                        "Stored Nuki webhook id=%s no longer exists on the server "
                        "(found ids: %s). Clearing stale credentials and re-registering.",
                        existing_webhook_id,
                        live_ids,
                    )
                    # Clear stale data so we fall through to re-registration below.
                    new_data = dict(entry.data)
                    new_data.pop(CONF_WEBHOOK_ID, None)
                    new_data.pop(CONF_WEBHOOK_SECRET, None)
                    hass.config_entries.async_update_entry(entry, data=new_data)
                    hass.data[DOMAIN][entry.entry_id]["webhook_id"] = None
                    hass.data[DOMAIN][entry.entry_id]["webhook_secret"] = None
            else:
                # Unexpected response shape — log and attempt re-registration to be safe.
                _LOGGER.warning(
                    "Unexpected response from GET /api/decentralWebhook: %r. "
                    "Will attempt re-registration.",
                    registered,
                )
        except Exception as err:  # noqa: BLE001
            # Network error, auth failure, etc.  Do not block setup — keep the
            # existing credentials in place and skip re-registration this cycle.
            _LOGGER.warning(
                "Could not verify Nuki webhook liveness (will keep existing "
                "credentials): %s",
                err,
            )
            needs_registration = False

    if not needs_registration:
        return

    # Register a fresh webhook.
    try:
        base = get_url(hass, prefer_external=True)
        webhook_url = f"{base}{WEBHOOK_PATH}/{entry.entry_id}"

        resp = await api.register_decentral_webhook(
            webhook_url=webhook_url, features=DEFAULT_WEBHOOK_FEATURES
        )

        if isinstance(resp, dict):
            webhook_id = resp.get("id")
            secret = resp.get("secret")

            new_data = dict(entry.data)
            if webhook_id is not None:
                new_data[CONF_WEBHOOK_ID] = int(webhook_id)
                hass.data[DOMAIN][entry.entry_id]["webhook_id"] = int(webhook_id)
            if secret:
                new_data[CONF_WEBHOOK_SECRET] = secret
                hass.data[DOMAIN][entry.entry_id]["webhook_secret"] = secret

            hass.config_entries.async_update_entry(entry, data=new_data)
            _LOGGER.debug(
                "Nuki decentral webhook registered successfully (id=%s).", webhook_id
            )
        else:
            _LOGGER.error(
                "Webhook registration returned unexpected response: %r", resp
            )

    except Exception as err:  # noqa: BLE001
        _LOGGER.error("Failed to register Nuki decentral webhook: %s", err)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the integration from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    # Register webhook view once
    if not hass.data[DOMAIN].get("_view_registered"):
        hass.http.register_view(NukiWebhookView(hass))
        hass.data[DOMAIN]["_view_registered"] = True

    # Create HA OAuth session (standard pattern)
    try:
        implementation = await config_entry_oauth2_flow.async_get_config_entry_implementation(
            hass, entry
        )
    except config_entry_oauth2_flow.ImplementationUnavailableError as err:
        # HA recommends treating this as retryable (e.g., no internet/DNS at startup)
        raise ConfigEntryNotReady(
            "OAuth2 implementation temporarily unavailable, will retry"
        ) from err

    oauth_session = config_entry_oauth2_flow.OAuth2Session(hass, entry, implementation)

    # Normalize legacy token storage and ensure expires_at for HA refresh logic.
    new_token = _normalize_and_enrich_token(entry)
    if new_token is not None:
        new_data = dict(entry.data)
        new_data["token"] = new_token
        for key in (
            "access_token",
            "token_type",
            "refresh_token",
            "expires_in",
            "scope",
            "expires_at",
        ):
            new_data.pop(key, None)
        hass.config_entries.async_update_entry(entry, data=new_data)

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

    # Verify the stored webhook is still live on the Nuki server and re-register
    # if it has gone missing.  This is intentionally non-blocking: failures are
    # logged as warnings and entity setup continues regardless.
    await _ensure_webhook_registered(hass, entry, api)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    return unload_ok