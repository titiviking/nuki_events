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
import secrets

from .const import (
    CONF_WEBHOOK_ID,
    CONF_WEBHOOK_SECRET,
    CONF_WEBHOOK_TOKEN,
    CONF_WEBHOOK_URL,
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
) -> tuple[list[dict], bool]:
    """Validate cached webhook registration; reuse if valid, else deregister and re-register.

    Validation requires all three cached values to match:
      - webhook_id   present in the live endpoint list
      - webhook_url  matches the live endpoint's URL exactly
      - webhook_secret  present in entry.data (cannot be verified via GET — used as
                        proof that HA performed the registration and stored the secret)

    When all three match the registration is reused unchanged.

    When anything is stale or missing:
      1. Best-effort DELETE the old registration from Nuki.
      2. Clear all cached webhook credentials from entry.data.
      3. Generate a fresh random token → build a new URL → PUT to Nuki.
      4. Cache the new id, secret, url, and token in entry.data.
      5. Re-fetch the live endpoint list.

    Returns (live_endpoints, secret_valid) where secret_valid=True means the
    cached credentials are confirmed correct for this load.
    """
    existing_id = entry.data.get(CONF_WEBHOOK_ID)
    existing_secret = entry.data.get(CONF_WEBHOOK_SECRET)
    existing_url = entry.data.get(CONF_WEBHOOK_URL)
    existing_token = entry.data.get(CONF_WEBHOOK_TOKEN)

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
        return [], False

    # ------------------------------------------------------------------ #
    # Step 2 — Validate: id + url + secret must all be cached and match  #
    # ------------------------------------------------------------------ #
    if existing_id and existing_secret and existing_url and existing_token:
        matching = next(
            (
                w for w in live_endpoints
                if isinstance(w, dict)
                and w.get("id") is not None
                and int(w["id"]) == int(existing_id)
                and w.get("webhookUrl") == existing_url
            ),
            None,
        )
        if matching is not None:
            _LOGGER.debug(
                "Nuki webhook id=%s is still active, URL and secret match; "
                "reusing existing registration.",
                existing_id,
            )
            return live_endpoints, True  # ← all three validated, reuse

        _LOGGER.warning(
            "Cached webhook id=%s is stale or URL mismatch (cached=%s). "
            "Will deregister and re-register with a new random token.",
            existing_id,
            existing_url,
        )
    else:
        _LOGGER.debug(
            "No complete webhook credentials cached "
            "(id=%s url=%s secret=%s token=%s) — registering fresh.",
            existing_id is not None,
            existing_url is not None,
            existing_secret is not None,
            existing_token is not None,
        )

    # ------------------------------------------------------------------ #
    # Step 3a — Best-effort deregister stale webhook                     #
    # ------------------------------------------------------------------ #
    if existing_id:
        try:
            await api.delete_decentral_webhook(existing_id)
            _LOGGER.debug(
                "Deregistered stale webhook id=%s before re-registration.",
                existing_id,
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning(
                "Could not deregister stale webhook id=%s (continuing anyway): %s",
                existing_id,
                err,
            )

    # ------------------------------------------------------------------ #
    # Step 3b — Clear all stale credentials                              #
    # ------------------------------------------------------------------ #
    cleared_data = {
        k: v for k, v in entry.data.items()
        if k not in (CONF_WEBHOOK_ID, CONF_WEBHOOK_SECRET, CONF_WEBHOOK_URL, CONF_WEBHOOK_TOKEN)
    }
    hass.config_entries.async_update_entry(entry, data=cleared_data)
    hass.data[DOMAIN][entry.entry_id]["webhook_id"] = None
    hass.data[DOMAIN][entry.entry_id]["webhook_secret"] = None

    # ------------------------------------------------------------------ #
    # Step 3c — Generate fresh random token + register                   #
    # A new token on every registration means the URL is unpredictable   #
    # and rotates automatically, unlike the fixed entry_id suffix.       #
    # ------------------------------------------------------------------ #
    try:
        base = get_url(hass, prefer_external=True)
    except Exception as err:  # noqa: BLE001
        _LOGGER.error("Could not determine external URL for webhook: %s", err)
        return live_endpoints, False

    new_token = secrets.token_urlsafe(32)
    new_webhook_url = f"{base}{WEBHOOK_PATH}/{new_token}"

    try:
        resp = await api.register_decentral_webhook(
            webhook_url=new_webhook_url, features=DEFAULT_WEBHOOK_FEATURES
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
            fresh_data[CONF_WEBHOOK_URL] = new_webhook_url
            fresh_data[CONF_WEBHOOK_TOKEN] = new_token

            hass.config_entries.async_update_entry(entry, data=fresh_data)
            _LOGGER.debug(
                "Nuki decentral webhook registered (id=%s, token=%.8s…).",
                new_id,
                new_token,
            )
        else:
            _LOGGER.error(
                "Webhook registration returned unexpected response: %r", resp
            )
            return live_endpoints, False

    except Exception as err:  # noqa: BLE001
        _LOGGER.error("Failed to register Nuki decentral webhook: %s", err)
        return live_endpoints, False

    # ------------------------------------------------------------------ #
    # Step 4 — Re-fetch live endpoints to reflect the new registration   #
    # ------------------------------------------------------------------ #
    try:
        live_endpoints = await api.list_decentral_webhooks()
        if not isinstance(live_endpoints, list):
            live_endpoints = []
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("Could not re-fetch webhooks after registration: %s", err)

    return live_endpoints, True  # fresh registration confirmed



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

    # Normalize legacy token storage and ensure expires_at BEFORE creating the
    # OAuth session.  OAuth2Session reads entry.data at construction time; if
    # expires_at is missing the session's internal token dict will lack it and
    # async_ensure_token_valid() raises KeyError: 'expires_at' on the first API
    # call (observed as the "Could not fetch live webhooks: 'expires_at'" warning).
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

    # Create OAuth session after normalisation so it picks up the enriched token.
    oauth_session = config_entry_oauth2_flow.OAuth2Session(hass, entry, implementation)

    # Force a token refresh on every startup.  The stored access_token may have
    # been invalidated server-side by Nuki (e.g. after a previous reauth issued a
    # new one) even though expires_at still looks valid.  Backdating expires_at by
    # 1 second guarantees async_ensure_token_valid() triggers a refresh and we
    # always hit the API with a live access_token rather than a stale one.
    _LOGGER.debug("Forcing proactive token refresh on startup")
    try:
        stale_data = dict(entry.data)
        if "token" in stale_data and isinstance(stale_data["token"], dict):
            stale_data["token"] = {**stale_data["token"], "expires_at": time.time() - 1}
            hass.config_entries.async_update_entry(entry, data=stale_data)
        await oauth_session.async_ensure_token_valid()
    except config_entry_oauth2_flow.OAuth2TokenRequestReauthError as err:
        raise ConfigEntryNotReady("Token refresh requires reauth — will retry") from err
    except Exception as err:  # noqa: BLE001
        raise ConfigEntryNotReady(f"Could not refresh OAuth token on startup: {err}") from err

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

    # Validate the cached webhook registration (id + url + secret); reuse if
    # still valid, otherwise deregister, generate a new random token, and
    # re-register.  Returns the live endpoint list and a secret_valid flag so
    # the diagnostic sensor is populated without an extra API call.
    live_endpoints, secret_valid = await _ensure_webhook_registered(hass, entry, api)

    # Re-sync hass.data from entry.data — _ensure_webhook_registered may have
    # persisted a brand-new token, url, id, and secret via async_update_entry.
    hass.data[DOMAIN][entry.entry_id]["webhook_id"] = entry.data.get(CONF_WEBHOOK_ID)
    hass.data[DOMAIN][entry.entry_id]["webhook_secret"] = entry.data.get(CONF_WEBHOOK_SECRET)

    # Register the current token in the domain-level token map so webhook.py
    # can route incoming requests to the right entry without exposing entry_id
    # in the URL.  Old tokens from previous loads are evicted automatically
    # since they are no longer valid on the Nuki server.
    current_token = entry.data.get(CONF_WEBHOOK_TOKEN)
    if current_token:
        token_map: dict[str, str] = hass.data[DOMAIN].setdefault("_token_map", {})
        # Remove any stale token that previously pointed to this entry.
        stale = [t for t, eid in token_map.items() if eid == entry.entry_id]
        for t in stale:
            token_map.pop(t, None)
        token_map[current_token] = entry.entry_id
        _LOGGER.debug(
            "Registered webhook token %.8s… → entry_id=%s",
            current_token,
            entry.entry_id,
        )
    else:
        _LOGGER.error(
            "No webhook token found after registration — webhook delivery will fail."
        )

    # Keep coordinator's cached entry_data in sync so the diagnostic sensor
    # always works against the freshly persisted credentials.
    coordinator._entry_data = dict(entry.data)

    # Run diagnostic with the live endpoint list already in hand — no extra API
    # call needed.  This populates the diagnostic sensor before the first render.
    await coordinator.async_run_webhook_diagnostic(live_endpoints=live_endpoints, secret_valid=secret_valid)

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
        # Remove the token from the domain-level map so stale tokens don't
        # accumulate and cannot be used to route requests to an unloaded entry.
        token = entry.data.get(CONF_WEBHOOK_TOKEN)
        if token:
            hass.data.get(DOMAIN, {}).get("_token_map", {}).pop(token, None)
        _LOGGER.debug(
            "Nuki webhook id=%s retained on Nuki server (will be validated on next load).",
            entry.data.get(CONF_WEBHOOK_ID),
        )

    return unload_ok