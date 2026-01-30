from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.config_entry_oauth2_flow import OAuth2Session
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import API_BASE

_LOGGER = logging.getLogger(__name__)


class NukiApi:
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.session = async_get_clientsession(hass)
        self.oauth_session = OAuth2Session(hass, entry)

    async def _auth_headers(self) -> dict[str, str]:
        """Ensure token is valid and return auth headers."""
        try:
            await self.oauth_session.async_ensure_token_valid()
        except Exception as err:
            raise ConfigEntryAuthFailed("OAuth token invalid") from err

        token = self.entry.data.get("token")
        if not token or "access_token" not in token:
            raise ConfigEntryAuthFailed("Missing OAuth token (reauth required)")

        return {
            "Authorization": f"Bearer {token['access_token']}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
    ) -> Any:
        url = f"{API_BASE}{path}"
        headers = await self._auth_headers()

        async with self.session.request(
            method,
            url,
            headers=headers,
            json=json,
        ) as resp:
            if resp.status == 401:
                raise ConfigEntryAuthFailed("Unauthorized")

            if resp.status >= 400:
                text = await resp.text()
                raise RuntimeError(
                    f"Nuki API error {resp.status}: {text}"
                )

            if resp.content_type == "application/json":
                return await resp.json()

            return None

    # ---------------------------------------------------------------------
    # Core API
    # ---------------------------------------------------------------------

    async def list_smartlocks(self) -> list[dict[str, Any]]:
        return await self._request("GET", "/smartlock")

    # ---------------------------------------------------------------------
    # Decentral Webhooks (CORRECT per Nuki docs)
    # ---------------------------------------------------------------------

    async def register_decentral_webhook(
        self,
        webhook_url: str,
        features: list[str],
    ) -> dict[str, Any]:
        """
        Register decentral webhook.

        PUT /api/decentralWebhook
        {
          "webhookUrl": "...",
          "webhookFeatures": [...]
        }
        """
        payload = {
            "webhookUrl": webhook_url,
            "webhookFeatures": features,
        }

        _LOGGER.debug(
            "Registering Nuki decentral webhook: %s", payload
        )

        return await self._request(
            "PUT",
            "/api/decentralWebhook",
            json=payload,
        )

    async def list_decentral_webhooks(self) -> list[dict[str, Any]]:
        """GET /api/decentralWebhook"""
        return await self._request("GET", "/api/decentralWebhook")

    async def delete_decentral_webhook(self, webhook_id: str) -> None:
        """DELETE /api/decentralWebhook/{id}"""
        await self._request(
            "DELETE",
            f"/api/decentralWebhook/{webhook_id}",
        )
