from __future__ import annotations

import logging
import time
import urllib.parse

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

        if "code" in qs:
            qs["code"] = ["<masked>"]
        if "client_secret" in qs:
            qs["client_secret"] = ["<masked>"]

        flat = {k: v[0] if v else "" for k, v in qs.items()}
        new_query = urllib.parse.urlencode(flat, quote_via=urllib.parse.quote)

        return urllib.parse.urlunsplit(
            (parts.scheme, parts.netloc, parts.path, new_query, parts.fragment)
        )
    except Exception:  # noqa: BLE001
        return "<unparseable url>"


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for Nuki Events with custom OAuth2 token exchange.

    - Uses state=self.flow_id so HA can resume the external step.
    - Encodes query using %20 for spaces (quote_via=urllib.parse.quote).
    - Persists credentials in flow context so resume after redirect is robust.
    """

    VERSION = 1

    @callback
    def _log_context(self, prefix: str) -> None:
        _LOGGER.debug(
            "%s: flow_id=%s unique_id=%s context(source=%s entry_id=%s)",
            prefix,
            getattr(self, "flow_id", None),
            getattr(self, "unique_id", None),
            self.context.get("source"),
            self.context.get("entry_id"),
        )

    async def async_step_user(self, user_input=None):
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

        client_id = (user_input.get("client_id") or "").strip()
        client_secret = (user_input.get("client_secret") or "").strip()

        # Persist in context so they survive the external redirect resume
        self.context["client_id"] = client_id
        self.context["client_secret"] = client_secret

        _LOGGER.debug(
            "User submitted credentials client_id=%s client_secret=%s",
            _mask(client_id),
            _mask(client_secret),
        )

        external_url = self.hass.config.external_url
        internal_url = self.hass.config.internal_url
        _LOGGER.debug(
            "HA URLs external_url=%s internal_url=%s",
            external_url,
            internal_url,
        )

        if not external_url:
            _LOGGER.error(
                "Home Assistant external_url is not set. "
                "OAuth redirect_uri cannot be constructed reliably."
            )
            return self.async_abort(reason="no_external_url")

        redirect_uri = f"{external_url.rstrip('/')}/auth/external/callback"

        # IMPORTANT: HA uses state to route the callback back to this flow.
        state = self.flow_id

        self.context["oauth_created_at"] = int(time.time())
        self.context["oauth_redirect_uri"] = redirect_uri

        _LOGGER.debug(
            "Prepared OAuth redirect_uri=%s state(flow_id)=%s",
            redirect_uri,
            state,
        )

        params = {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            # space-delimited; will become %20 with quote_via=quote
            "scope": DEFAULT_SCOPES,
            "state": state,
        }

        # Force %20 encoding for spaces (instead of '+')
        query = urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
        auth_url = f"{OAUTH2_AUTHORIZE}?{query}"

        _LOGGER.debug("Starting external auth step, auth_url=%s", _safe_url(auth_url))

        self._log_context("async_step_user(end->external_step)")
        return self.async_external_step(step_id="authorize", url=auth_url)

    async def async_step_authorize(self, user_input):
        self._log_context("async_step_authorize(start)")

        returned_state = user_input.get("state")
        returned_code = user_input.get("code")
        returned_error = user_input.get("error")
        returned_error_desc = user_input.get("error_description")

        _LOGGER.debug(
            "OAuth callback received: state=%s code=%s error=%s error_description=%s keys=%s",
            returned_state or "<none>",
            _mask(returned_code, keep=6),
            returned_error or "<none>",
            returned_error_desc or "<none>",
            list(user_input.keys()),
        )

        if returned_error:
            _LOGGER.error(
                "OAuth provider returned error=%s error_description=%s",
                returned_error,
                returned_error_desc,
            )
            return self.async_abort(reason="oauth_error")

        # Sanity check (HA already routed by state)
        if returned_state != self.flow_id:
            _LOGGER.error(
                "Unexpected state mismatch after routing. returned_state=%s flow_id=%s",
                returned_state,
                self.flow_id,
            )
            return self.async_abort(reason="invalid_state")

        if not returned_code:
            _LOGGER.error("No authorization code received in callback.")
            return self.async_abort(reason="invalid_state")

        # Pull credentials from context (robust across external redirect resume)
        client_id = self.context.get("client_id")
        client_secret = self.context.get("client_secret")
        if not client_id or not client_secret:
            _LOGGER.error(
                "Missing client credentials in flow context after redirect. "
                "client_id_present=%s client_secret_present=%s",
                bool(client_id),
                bool(client_secret),
            )
            return self.async_abort(reason="missing_credentials")

        session = async_get_clientsession(self.hass)

        redirect_uri = self.context.get("oauth_redirect_uri")
        if not redirect_uri:
            _LOGGER.error("redirect_uri missing from context; cannot exchange token.")
            return self.async_abort(reason="no_external_url")

        payload = {
            "grant_type": "authorization_code",
            "client_id": client_id,
            "client_secret": client_secret,
            "code": returned_code,
            "redirect_uri": redirect_uri,
        }

        _LOGGER.debug(
            "Exchanging code for token at %s with redirect_uri=%s client_id=%s code=%s",
            OAUTH2_TOKEN,
            redirect_uri,
            _mask(client_id),
            _mask(returned_code, keep=6),
        )

        async with session.post(
            OAUTH2_TOKEN,
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        ) as resp:
            text = await resp.text()
            _LOGGER.debug(
                "Token endpoint responded status=%s headers=%s body=%s",
                resp.status,
                dict(resp.headers),
                text[:2000],
            )

            if resp.status != 200:
                raise config_entries.ConfigEntryAuthFailed(
                    f"Nuki token exchange failed ({resp.status}): {text}"
                )

            token = await resp.json()

        expires_in = int(token.get("expires_in", 3600))
        token["expires_at"] = int(time.time()) + max(0, expires_in - 60)

        _LOGGER.debug(
            "Token exchange success: token_keys=%s expires_in=%s expires_at=%s access_token=%s refresh_token=%s",
            list(token.keys()),
            expires_in,
            token.get("expires_at"),
            _mask(token.get("access_token"), keep=6),
            _mask(token.get("refresh_token"), keep=6),
        )

        entry_id = getattr(self, "_reauth_entry_id", None)
        if entry_id:
            entry = self.hass.config_entries.async_get_entry(entry_id)
            if entry:
                _LOGGER.debug("Reauth: updating entry_id=%s and reloading", entry_id)
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={
                        "client_id": client_id,
                        "client_secret": client_secret,
                        "token": token,
                    },
                )

        _LOGGER.debug("Creating new config entry for %s", DOMAIN)
        return self.async_create_entry(
            title="Nuki Events",
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "token": token,
            },
        )

    async def async_step_reauth(self, user_input=None):
        self._log_context("async_step_reauth(start)")
        self._reauth_entry_id = self.context.get("entry_id")
        _LOGGER.debug("Reauth requested for entry_id=%s", self._reauth_entry_id)
        return await self.async_step_user(user_input)
