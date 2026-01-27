from __future__ import annotations

import logging
import secrets
import time
import urllib.parse
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DOMAIN, OAUTH2_AUTHORIZE, OAUTH2_TOKEN, DEFAULT_SCOPES

_LOGGER = logging.getLogger(__name__)


def _mask(value: str | None, keep: int = 4) -> str:
    """Mask secrets for logs."""
    if not value:
        return "<none>"
    if len(value) <= keep * 2:
        return "*" * len(value)
    return f"{value[:keep]}...{value[-keep:]}"


def _safe_url(url: str) -> str:
    """Mask sensitive query params in a URL before logging."""
    try:
        parts = urllib.parse.urlsplit(url)
        qs = urllib.parse.parse_qs(parts.query, keep_blank_values=True)
        for key in ("client_secret", "code"):
            if key in qs:
                qs[key] = ["<masked>"]
        if "state" in qs:
            qs["state"] = [f"<masked:{len(qs['state'][0])}chars>"]
        new_query = urllib.parse.urlencode({k: v[0] for k, v in qs.items()})
        return urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path, new_query, parts.fragment))
    except Exception:  # noqa: BLE001
        return "<unparseable url>"


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for Nuki Events using a dedicated OAuth2 implementation.

    Nuki requires client_id/client_secret in the POST body (client_secret_post).
    Home Assistant's built-in OAuth helpers use HTTP Basic Auth, so we implement
    the token exchange ourselves.
    """

    VERSION = 1

    @callback
    def _log_context(self, prefix: str) -> None:
        # Helpful for troubleshooting cross-instance / flow-resume issues
        _LOGGER.debug(
            "%s: flow_id=%s unique_id=%s context=%s",
            prefix,
            getattr(self, "flow_id", None),
            getattr(self, "unique_id", None),
            {
                "source": self.context.get("source"),
                "entry_id": self.context.get("entry_id"),
                "oauth_state_set": "oauth_state" in self.context,
            },
        )

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        self._log_context("async_step_user(start)")

        if user_input is None:
            _LOGGER.debug("Showing user form for client_id/client_secret input")
            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema(
                    {
                        vol.Required("client_id"): str,
                        vol.Required("client_secret"): str,
                    }
                ),
            )

        # Store client credentials on the flow instance
        self._client_id = (user_input.get("client_id") or "").strip()
        self._client_secret = (user_input.get("client_secret") or "").strip()

        _LOGGER.debug(
            "User submitted credentials client_id=%s client_secret=%s",
            _mask(self._client_id),
            _mask(self._client_secret),
        )

        external_url = self.hass.config.external_url
        internal_url = self.hass.config.internal_url
        _LOGGER.debug("HA URLs external_url=%s internal_url=%s", external_url, internal_url)

        if not external_url:
            # This often causes redirect/callback to land on the wrong place
            _LOGGER.error(
                "Home Assistant external_url is not set. "
                "OAuth redirect_uri cannot be constructed reliably."
            )
            return self.async_abort(reason="no_external_url")

        redirect_uri = f"{external_url.rstrip('/')}/auth/external/callback"

        # Generate a CSRF protection state and store it for validation on callback
        state = secrets.token_urlsafe(32)
        self.context["oauth_state"] = state
        self.context["oauth_created_at"] = int(time.time())
        self.context["oauth_redirect_uri"] = redirect_uri

        _LOGGER.debug(
            "Prepared OAuth redirect_uri=%s state_len=%s state(masked)=%s",
            redirect_uri,
            len(state),
            _mask(state, keep=6),
        )

        params = {
            "response_type": "code",
            "client_id": self._client_id,
            "redirect_uri": redirect_uri,
            "scope": DEFAULT_SCOPES,
            "state": state,
        }

        auth_url = f"{OAUTH2_AUTHORIZE}?{urllib.parse.urlencode(params)}"
        _LOGGER.debug("Starting external auth step, auth_url=%s", _safe_url(auth_url))
        self._log_context("async_step_user(end->external_step)")

        # This tells HA to open the browser and later resume to async_step_authorize
        return self.async_external_step(step_id="authorize", url=auth_url)

    async def async_step_authorize(self, user_input: dict[str, An]()_
