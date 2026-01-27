from __future__ import annotations

import secrets
import urllib.parse
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DOMAIN, OAUTH2_AUTHORIZE, OAUTH2_TOKEN, DEFAULT_SCOPES


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for Nuki Events using a dedicated OAuth2 implementation.

    Nuki requires client_id/client_secret in the POST body (client_secret_post).
    Home Assistant's built-in OAuth helpers use HTTP Basic Auth, so we implement
    the token exchange ourselves.
    """

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        if user_input is None:
            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema(
                    {
                        vol.Required("client_id"): str,
                        vol.Required("client_secret"): str,
                    }
                ),
            )

        self._client_id = user_input["client_id"].strip()
        self._client_secret = user_input["client_secret"].strip()
        redirect_uri = f"{self.hass.config.external_url}/auth/external/callback"

        # Generate a CSRF protection state and store it for validation on callback
        state = secrets.token_urlsafe(32)
        self.context["oauth_state"] = state

        params = {
            "response_type": "code",
            "client_id": self._client_id,
            "redirect_uri": redirect_uri,
            "scope": DEFAULT_SCOPES,
            "state": state,
        }

        auth_url = f"{OAUTH2_AUTHORIZE}?{urllib.parse.urlencode(params)}"

        return self.async_external_step(step_id="authorize", url=auth_url)

    async def async_step_authorize(self, user_input: dict[str, Any]):
        expected_state = self.context.get("oauth_state")
        if not expected_state or user_input.get("state") != expected_state:
            return self.async_abort(reason="invalid_state")

        code = user_input.get("code")
        if not code:
            return self.async_abort(reason="invalid_state")

        session = async_get_clientsession(self.hass)

        redirect_uri = f"{self.hass.config.external_url}/auth/external/callback"
        payload = {
            "grant_type": "authorization_code",
            "client_id": self._client_id,
            "client_secret": self._client_secret,
            "code": code,
            "redirect_uri": redirect_uri,
        }

        async with session.post(
            OAUTH2_TOKEN,
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        ) as resp:
            if resp.status != 200:
                body = await resp.text()
                raise config_entries.ConfigEntryAuthFailed(
                    f"Nuki token exchange failed ({resp.status}): {body}"
                )
            token = await resp.json()

        # Add expires_at (monotonic) for refresh checks
        expires_in = int(token.get("expires_in", 3600))
        token["expires_at"] = int(self.hass.loop.time()) + expires_in - 60

        # If this is a reauth flow, update the existing entry in place
        entry_id = getattr(self, "_reauth_entry_id", None)
        if entry_id:
            entry = self.hass.config_entries.async_get_entry(entry_id)
            if entry:
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={
                        "client_id": self._client_id,
                        "client_secret": self._client_secret,
                        "token": token,
                    },
                )

        return self.async_create_entry(
            title="Nuki Events",
            data={
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "token": token,
            },
        )

    async def async_step_reauth(self, user_input: dict[str, Any] | None = None):
        """Handle re-authentication when refresh fails."""
        # Home Assistant passes the existing config entry data in context
        self._reauth_entry_id = self.context.get("entry_id")
        return await self.async_step_user(user_input)
