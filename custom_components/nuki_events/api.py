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

        Important: HA's OAuth2Session.async_ensure_token_valid() updates the stored token
        but does not return it. Use oauth_session.token after ensuring validity.
        """
        await self.oauth_session.async_ensure_token_valid()
        token = getattr(self.oauth_session, "token", None)

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

        headers: dict[str, str] = dict(kwargs.pop("headers", {}) or {})
        headers.update(await self._auth_headers())

        # If we're sending json, ensure content-type is present (Nuki endpoints expect JSON)
        if "json" in kwargs and "Content-Type" not in headers:
            headers["Content-Type"] = "application/json"

        async with session.request(method, url, headers=headers, **kwargs) as resp:
            # Treat auth errors as reauth triggers (HA will handle it)
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

    async def list_smartlock_logs(self, smartlock_id: int, limit: int = 1) -> Any:
        """Return recent log entries for a smartlock."""
        # Nuki Web API commonly supports /smartlock/{id}/log or /smartlock/log
        # depending on version. Use the one your docs specify.
        return await self._request(
            "GET",
            f"/smartlock/{int(smartlock_id)}/log",
            params={"limit": int(limit)},
        )

    # ---------------------------------------------------------------------
    # Decentral webhooks (FIXED)
    # ---------------------------------------------------------------------
    async def register_decentral_webhook(self, webhook_url: str, features: list[str]) -> Any:
        """Register a decentral webhook.

        Correct endpoint/method/payload:
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
        return await self._request("PUT", "/api/decentralWebhook", json=payload)

    async def list_decentral_webhooks(self) -> Any:
        """List decentral webhooks (useful for debugging).

        GET /api/decentralWebhook
        """
        return await self._request("GET", "/api/decentralWebhook")

    async def delete_decentral_webhook(self, webhook_id: int) -> Any:
        """Delete a decentral webhook.

        Correct endpoint:
          DELETE /api/decentralWebhook/{id}
        """
        return await self._request("DELETE", f"/api/decentralWebhook/{int(webhook_id)}")
