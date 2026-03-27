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
) -> list[dict]:
    """Validate the cached webhook registration and reuse it when still valid.

    Returns the live endpoint list fetched from Nuki so the caller can pass it
    directly to the diagnostic sensor, avoiding a redundant second API call.

    Decision flow:
      1. Fetch all live decentral webhooks from GET /api/decentralWebhook.
      2. If the cached webhook_id AND the cached URL are both found in the live
         list → registration is valid, retain credentials unchanged.
      3. Otherwise → the cached registration is stale or missing:
           a. Attempt to delete the cached webhook from Nuki (best-effort).
           b. Clear cached credentials from entry.data and hass.data.
           c. Register a fresh webhook, persist new id + secret.
      4. Re-fetch the live list after any new registration so the returned
         snapshot always reflects the final server state.

    All failures are non-fatal: errors are logged and setup continues.
    """
    existing_webhook_id = entry.data.get(CONF_WEBHOOK_ID)
    existing_secret = entry.data.get(CONF_WEBHOOK_SECRET)

    # Build the URL we expect to be registered.
    try:
        base = get_url(hass, prefer_external=True)
        webhook_url = f"{base}{WEBHOOK_PATH}/{entry.entry_id}"
    except Exception as err:  # noqa: BLE001
        _LOGGER.error("Could not determine external URL for webhook: %s", err)
        return []

    # ------------------------------------------------------------------ #
    # Step 1 — Fetch all live endpoints                                   #
    # ------------------------------------------------------------------ #
    try:
        live_endpoints = await api.list_decentral_webhooks()
        if not isinstance(live_endpoints, list):
            _LOGGER.warning(
                "Unexpected response from GET /api/decentralWebhook: %r. "
                "Will attempt fresh registration.",
                live_endpoints,
            )
            live_endpoints = []
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning(
            "Could not fetch live webhooks (will keep existing credentials): %s", err
        )
        return []

    # ------------------------------------------------------------------ #
    # Step 2 — Check if cached registration is still valid               #
    # A valid registration requires both:                                 #
    #   • the cached webhook_id is present in the live list, AND          #
    #   • the live endpoint's URL matches our expected URL                 #
    #   (Nuki does not expose secrets via GET, so URL+ID is the best      #
    #    available proxy for "the secret we stored is still correct")      #
    # ------------------------------------------------------------------ #
    if existing_webhook_id and existing_secret:
        matching = next(
            (
                w for w in live_endpoints
                if isinstance(w, dict)
                and w.get("id") is not None
                and int(w["id"]) == int(existing_webhook_id)
                and w.get("webhookUrl") == webhook_url
            ),
            None,
        )
        if matching is not None:
            _LOGGER.debug(
                "Nuki webhook id=%s is still active and URL matches; "
                "reusing existing registration.",
                existing_webhook_id,
            )
            return live_endpoints  # ← reuse: no changes needed

        _LOGGER.warning(
            "Cached webhook id=%s is stale or URL mismatch (expected %s). "
            "Will deregister and re-register.",
            existing_webhook_id,
            webhook_url,
        )

    # ------------------------------------------------------------------ #
    # Step 3a — Best-effort deregister stale webhook                     #
    # ------------------------------------------------------------------ #
    if existing_webhook_id:
        try:
            await api.delete_decentral_webhook(existing_webhook_id)
            _LOGGER.debug(
                "Deregistered stale webhook id=%s before re-registration.",
                existing_webhook_id,
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning(
                "Could not deregister stale webhook id=%s (continuing anyway): %s",
                existing_webhook_id,
                err,
            )

    # ------------------------------------------------------------------ #
    # Step 3b — Clear stale credentials                                  #
    # ------------------------------------------------------------------ #
    new_data = {
        k: v for k, v in entry.data.items()
        if k not in (CONF_WEBHOOK_ID, CONF_WEBHOOK_SECRET)
    }
    hass.config_entries.async_update_entry(entry, data=new_data)
    hass.data[DOMAIN][entry.entry_id]["webhook_id"] = None
    hass.data[DOMAIN][entry.entry_id]["webhook_secret"] = None

    # ------------------------------------------------------------------ #
    # Step 3c — Register fresh webhook                                   #
    # ------------------------------------------------------------------ #
    try:
        resp = await api.register_decentral_webhook(
            webhook_url=webhook_url, features=DEFAULT_WEBHOOK_FEATURES
        )

        if isinstance(resp, dict):
            new_id = resp.get("id")
            new_secret = resp.get("secret")

            fresh_data = dict(entry.data)
            if new_id is not None:
                fresh_data[CONF_WEBHOOK_ID] = int(new_id)
                hass.data[DOMAIN][entry.entry_id]["webhook_id"] = int(new_id)
            if new_secret:
                fresh_data[CONF_WEBHOOK_SECRET] = new_secret
                hass.data[DOMAIN][entry.entry_id]["webhook_secret"] = new_secret

            hass.config_entries.async_update_entry(entry, data=fresh_data)
            _LOGGER.debug(
                "Nuki decentral webhook registered successfully (id=%s).", new_id
            )
        else:
            _LOGGER.error(
                "Webhook registration returned unexpected response: %r", resp
            )
            return live_endpoints

    except Exception as err:  # noqa: BLE001
        _LOGGER.error("Failed to register Nuki decentral webhook: %s", err)
        return live_endpoints

    # ------------------------------------------------------------------ #
    # Step 4 — Re-fetch live endpoints to reflect the new registration   #
    # ------------------------------------------------------------------ #
    try:
        live_endpoints = await api.list_decentral_webhooks()
        if not isinstance(live_endpoints, list):
            live_endpoints = []
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("Could not re-fetch webhooks after registration: %s", err)

    return live_endpoints


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

    coordinator = NukiDataCoordinator(hass, api, entry_id=entry.entry_id, entry_data=dict(entry.data))
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = {
        "coordinator": coordinator,
        "webhook_secret": entry.data.get(CONF_WEBHOOK_SECRET),
        "webhook_id": entry.data.get(CONF_WEBHOOK_ID),
        "api": api,
        "oauth_session": oauth_session,
    }

    # Validate the cached webhook registration; reuse if still valid, otherwise
    # deregister and re-register.  Returns the current live endpoint list from
    # Nuki so we can feed it directly to the diagnostic sensor without an extra
    # API call.
    live_endpoints = await _ensure_webhook_registered(hass, entry, api)

    # Re-sync hass.data from entry.data after _ensure_webhook_registered, which
    # may have persisted a brand-new webhook_id/secret via async_update_entry.
    hass.data[DOMAIN][entry.entry_id]["webhook_id"] = entry.data.get(CONF_WEBHOOK_ID)
    hass.data[DOMAIN][entry.entry_id]["webhook_secret"] = entry.data.get(CONF_WEBHOOK_SECRET)
    # Keep coordinator's cached entry_data in sync so the diagnostic sensor
    # always works against the freshly persisted credentials.
    coordinator._entry_data = dict(entry.data)

    # Run diagnostic with the live endpoint list already in hand — no extra API
    # call needed.  This populates the diagnostic sensor before the first render.
    await coordinator.async_run_webhook_diagnostic(live_endpoints=live_endpoints)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry.

    The Nuki webhook registration is intentionally kept alive across reloads and
    restarts.  On the next load _ensure_webhook_registered will verify the cached
    credentials are still valid and reuse them, avoiding an unnecessary delete +
    re-register cycle (and the associated Nuki API calls and new secret churn).

    The webhook is only deregistered when _ensure_webhook_registered detects that
    the cached registration is no longer valid (wrong URL, missing id, etc.), or
    when the integration is fully removed by the user.
    """
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
        # If no entry data keys remain (ignoring the _view_registered sentinel),
        # clear the flag so the webhook view is re-registered on a fresh setup
        # without requiring a full HA restart.
        remaining = [k for k in hass.data.get(DOMAIN, {}) if k != "_view_registered"]
        if not remaining:
            hass.data.get(DOMAIN, {}).pop("_view_registered", None)
        _LOGGER.debug(
            "Nuki webhook id=%s retained on Nuki server (will be validated on next load).",
            entry.data.get(CONF_WEBHOOK_ID),
        )

    return unload_ok