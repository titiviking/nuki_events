from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import API_BASE

_LOGGER = logging.getLogger(__name__)


class NukiApi:
    """Nuki Web API client using HA OAuth2Session for token management."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, oauth_session: Any) -> None:
        self.hass = hass
        self.entry = entry
        self.oauth_session = oauth_session

    async def _auth_headers(self) -> dict[str, str]:
        """Return Authorization headers.

        Fix 1: async_ensure_token_valid() can return None; never call .get() on None.
        Raise ConfigEntryAuthFailed so HA can trigger reauth instead of crashing.
        """
        token = await self.oauth_session.async_ensure_token_valid()

        if not token or not isinstance(token, dict):
            raise ConfigEntryAuthFailed("Missing OAuth token (reauth required)")

        access_token = token.get("access_token")
        if not access_token:
            raise ConfigEntryAuthFailed("OAuth token missing access_token (reauth required)")

        return {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        }

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        """Make an authenticated request to Nuki."""
        session = async_get_clientsession(self.hass)
        url = f"{API_BASE}{path}"

        headers = kwargs.pop("headers", {})
        headers.update(await self._auth_headers())

        async with session.request(method, url, headers=headers, **kwargs) as resp:
            # Fix 2: 401/403 should be treated as auth failure -> reauth
            if resp.status in (401, 403):
                body = await resp.text()
                _LOGGER.warning(
                    "Nuki API auth failed (HTTP %s) for %s %s. Body: %s",
                    resp.status,
                    method,
                    path,
                    body,
                )
                raise ConfigEntryAuthFailed(f"Nuki API auth failed (HTTP {resp.status})")

            resp.raise_for_status()

            if resp.content_type == "application/json":
                return await resp.json()

            text = await resp.text()
            return text if text else None

    async def list_smartlocks(self) -> Any:
        """Return list of smartlocks."""
        return await self._request("GET", "/smartlock")

    async def register_decentral_webhook(self, webhook_url: str, features: list[str]) -> Any:
        """Register a decentral webhook."""
        payload = {"url": webhook_url, "features": features}
        return await self._request("POST", "/webhook/decentral", json=payload)

    async def delete_decentral_webhook(self, webhook_id: int) -> Any:
        """Delete a decentral webhook."""
        return await self._request("DELETE", f"/webhook/decentral/{int(webhook_id)}")
