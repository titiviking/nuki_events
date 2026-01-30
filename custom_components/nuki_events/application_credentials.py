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
    """OAuth2 implementation for Nuki.

    Nuki expects *client_secret_post* for token exchange/refresh:
    - client_id and client_secret must be sent in the x-www-form-urlencoded body
    - not using HTTP Basic auth

    Docs: Nuki Web API Documentation (OAuth2 Code Flow).
    """

    @property
    def extra_authorize_data(self) -> dict[str, str]:
        # Nuki expects scopes as a space-separated string.
        return {"scope": " ".join(DEFAULT_SCOPES)}

    async def async_exchange_code(self, code: str) -> dict[str, Any]:
        """Exchange authorization code for an access token."""
        session = async_get_clientsession(self.hass)

        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.redirect_uri,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        }

        _LOGGER.debug("Exchanging authorization code for token (client_secret_post)")
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
        """Refresh an access token."""
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

        _LOGGER.debug("Refreshing token (client_secret_post)")
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
    """Return the OAuth2 implementation for Nuki."""
    return NukiOAuth2Implementation(
        hass=hass,
        domain=auth_domain,
        client_id=credential.client_id,
        authorize_url=OAUTH2_AUTHORIZE,
        token_url=OAUTH2_TOKEN,
        client_secret=credential.client_secret,
    )


async def async_get_description_placeholders(hass: HomeAssistant) -> dict[str, str]:
    """Return description placeholders for the Application Credentials UI."""
    return {"docs_url": "https://web.nuki.io/"}
