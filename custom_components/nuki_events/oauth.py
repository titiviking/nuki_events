from __future__ import annotations

import logging
from typing import Any

from aiohttp import ClientResponseError

from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import OAUTH2_AUTHORIZE, OAUTH2_TOKEN, DEFAULT_SCOPES

_LOGGER = logging.getLogger(__name__)


class NukiOAuth2Implementation(config_entry_oauth2_flow.LocalOAuth2Implementation):
    """OAuth2 implementation for Nuki with client_secret_post token requests."""

    async def async_exchange_code(self, code: str) -> dict[str, Any]:
        """Exchange authorization code for token using client_secret_post."""
        session = async_get_clientsession(self.hass)

        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.redirect_uri,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        }

        _LOGGER.debug("Exchanging code for token (client_secret_post) at %s", self.token_url)

        async with session.post(
            self.token_url,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        ) as resp:
            text = await resp.text()
            if resp.status >= 400:
                _LOGGER.error("Token exchange failed (%s): %s", resp.status, text)
                raise ClientResponseError(
                    request_info=resp.request_info,
                    history=resp.history,
                    status=resp.status,
                    message=text,
                    headers=resp.headers,
                )
            return await resp.json()

    async def async_refresh_token(self, token: dict[str, Any]) -> dict[str, Any]:
        """Refresh token using client_secret_post."""
        session = async_get_clientsession(self.hass)

        refresh_token = token.get("refresh_token")
        if not refresh_token:
            raise config_entry_oauth2_flow.OAuth2RequestException("Missing refresh_token")

        data = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        }

        _LOGGER.debug("Refreshing token (client_secret_post) at %s", self.token_url)

        async with session.post(
            self.token_url,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        ) as resp:
            text = await resp.text()
            if resp.status >= 400:
                _LOGGER.error("Token refresh failed (%s): %s", resp.status, text)
                raise ClientResponseError(
                    request_info=resp.request_info,
                    history=resp.history,
                    status=resp.status,
                    message=text,
                    headers=resp.headers,
                )
            return await resp.json()


async def async_get_config_entry_implementation(
    hass: HomeAssistant,
) -> config_entry_oauth2_flow.AbstractOAuth2Implementation:
    """Return the OAuth2 implementation for this integration.

    This is used by the OAuth2FlowHandler and OAuth2Session.
    """
    # Pull client_id/secret from Application Credentials, if you enable it in manifest.
    # If you are not using application_credentials, you can instantiate with fixed values
    # or load from somewhere else, but Application Credentials is the HA-native approach.
    return config_entry_oauth2_flow.LocalOAuth2Implementation(
        hass=hass,
        domain="nuki_events",
        client_id=None,         # filled by HA when using application_credentials
        client_secret=None,     # filled by HA when using application_credentials
        authorize_url=OAUTH2_AUTHORIZE,
        token_url=OAUTH2_TOKEN,
        scopes=DEFAULT_SCOPES,
    )
