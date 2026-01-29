from __future__ import annotations

import logging
from typing import Any

from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DEFAULT_SCOPES, OAUTH2_AUTHORIZE, OAUTH2_TOKEN

_LOGGER = logging.getLogger(__name__)


class NukiOAuth2Implementation(config_entry_oauth2_flow.LocalOAuth2Implementation):
    """Nuki OAuth2 implementation compatible with HA 2026.x.

    Key points:
    - Do NOT pass scopes into __init__ (HA no longer accepts that kwarg).
    - Provide scopes via extra_authorize_data -> 'scope' query parameter.
    - Exchange/refresh tokens using client_secret_post (id/secret in POST body).
    """

    @property
    def extra_authorize_data(self) -> dict[str, str]:
        # Nuki expects a space-separated scope string
        return {"scope": " ".join(DEFAULT_SCOPES)}

    async def async_exchange_code(self, code: str) -> dict[str, Any]:
        """Exchange authorization code for token (client_secret_post)."""
        session = async_get_clientsession(self.hass)

        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.redirect_uri,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        }

        _LOGGER.debug("Exchanging OAuth code for token at %s", self.token_url)
        async with session.post(
            self.token_url,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        ) as resp:
            text = await resp.text()
            if resp.status != 200:
                raise config_entry_oauth2_flow.OAuth2RequestException(
                    f"Token exchange failed ({resp.status}): {text}"
                )
            return await resp.json()

    async def async_refresh_token(self, token: dict[str, Any]) -> dict[str, Any]:
        """Refresh access token (client_secret_post)."""
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

        _LOGGER.debug("Refreshing OAuth token at %s", self.token_url)
        async with session.post(
            self.token_url,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        ) as resp:
            text = await resp.text()
            if resp.status != 200:
                raise config_entry_oauth2_flow.OAuth2RequestException(
                    f"Token refresh failed ({resp.status}): {text}"
                )
            return await resp.json()


def async_get_authorization_server() -> dict[str, str]:
    """Return the OAuth endpoints.

    This mirrors the information used by Application Credentials / OAuth flows.
    """
    return {"authorize_url": OAUTH2_AUTHORIZE, "token_url": OAUTH2_TOKEN}
