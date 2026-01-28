from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.application_credentials import (
    AuthorizationServer,
    ClientCredential,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DEFAULT_SCOPES, OAUTH2_AUTHORIZE, OAUTH2_TOKEN

_LOGGER = logging.getLogger(__name__)


class NukiOAuth2Implementation(config_entry_oauth2_flow.LocalOAuth2Implementation):
    """OAuth2 implementation for Nuki using client_secret_post for token requests."""

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

        _LOGGER.debug("Exchanging code for token via POST body at %s", self.token_url)

        async with session.post(
            self.token_url,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        ) as resp:
            body = await resp.text()
            if resp.status != 200:
                raise config_entry_oauth2_flow.OAuth2RequestException(
                    f"Token exchange failed ({resp.status}): {body}"
                )
            return await resp.json()

    async def async_refresh_token(self, token: dict[str, Any]) -> dict[str, Any]:
        """Refresh token using client_secret_post."""
        refresh_token = token.get("refresh_token")
        if not refresh_token:
            raise config_entry_oauth2_flow.OAuth2RequestException("Missing refresh_token")

        session = async_get_clientsession(self.hass)

        data = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        }

        _LOGGER.debug("Refreshing token via POST body at %s", self.token_url)

        async with session.post(
            self.token_url,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        ) as resp:
            body = await resp.text()
            if resp.status != 200:
                raise config_entry_oauth2_flow.OAuth2RequestException(
                    f"Token refresh failed ({resp.status}): {body}"
                )
            return await resp.json()


async def async_get_authorization_server(hass: HomeAssistant) -> AuthorizationServer:
    """Return the authorization server for Nuki."""
    return AuthorizationServer(
        authorize_url=OAUTH2_AUTHORIZE,
        token_url=OAUTH2_TOKEN,
    )


async def async_get_auth_implementation(
    hass: HomeAssistant,
    auth_domain: str,
    credential: ClientCredential,
) -> config_entry_oauth2_flow.AbstractOAuth2Implementation:
    """Return the auth implementation for Nuki (client_secret_post)."""
    # AbstractOAuth2FlowHandler will request scopes via its own mechanism; we keep DEFAULT_SCOPES
    # on the implementation so the session knows what it requested.
    return NukiOAuth2Implementation(
        hass=hass,
        domain=auth_domain,
        client_id=credential.client_id,
        authorize_url=OAUTH2_AUTHORIZE,
        token_url=OAUTH2_TOKEN,
        client_secret=credential.client_secret,
        scope=DEFAULT_SCOPES,
    )


async def async_get_description_placeholders(hass: HomeAssistant) -> dict[str, str]:
    """Placeholders shown in the Application Credentials UI (optional)."""
    return {
        "docs_url": "https://api.nuki.io/",
    }
