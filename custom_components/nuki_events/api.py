from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Mapping

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import API_BASE, OAUTH2_TOKEN

_LOGGER = logging.getLogger(__name__)


@dataclass
class NukiApi:
    hass: HomeAssistant
    entry: ConfigEntry

    def _now(self) -> int:
        # Monotonic time (seconds) for expires_at comparisons
        return int(self.hass.loop.time())

    async def _ensure_token_valid(self) -> dict[str, Any]:
        token: dict[str, Any] = dict(self.entry.data.get("token") or {})
        if not token:
            raise ConfigEntryAuthFailed("Missing OAuth token in config entry")


        expires_at = token.get("expires_at")
        if expires_at is None:
            expires_in = int(token.get("expires_in", 3600))
            token["expires_at"] = self._now() + expires_in - 60
            expires_at = token["expires_at"]

        if self._now() < int(expires_at):
            return token

        refresh = token.get("refresh_token")
        if not refresh:
            raise ConfigEntryAuthFailed("OAuth token expired and no refresh_token is available")


        client_id = self.entry.data.get("client_id")
        client_secret = self.entry.data.get("client_secret")
        if not client_id or not client_secret:
            raise ConfigEntryAuthFailed("Missing client_id/client_secret in config entry")


        session = async_get_clientsession(self.hass)
        payload = {
            "grant_type": "refresh_token",
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh,
        }

        _LOGGER.debug("Refreshing Nuki OAuth token")
        async with session.post(
            OAUTH2_TOKEN,
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        ) as resp:
            if resp.status != 200:
                body = await resp.text()
                raise ConfigEntryAuthFailed(f"Token refresh failed ({resp.status}): {body}")
            new_token = await resp.json()

        expires_in = int(new_token.get("expires_in", 3600))
        new_token["expires_at"] = self._now() + expires_in - 60

        # Preserve refresh_token if server doesn't return it
        if "refresh_token" not in new_token and refresh:
            new_token["refresh_token"] = refresh

        new_data = dict(self.entry.data)
        new_data["token"] = new_token
        self.hass.config_entries.async_update_entry(self.entry, data=new_data)

        # refresh local reference
        self.entry = self.hass.config_entries.async_get_entry(self.entry.entry_id) or self.entry
        return new_token

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict | None = None,
        params: Mapping[str, str] | None = None,
    ) -> Any:
        session = async_get_clientsession(self.hass)
        token = await self._ensure_token_valid()

        headers = {"accept": "application/json", "authorization": f"Bearer {token['access_token']}"}
        url = f"{API_BASE}{path}"

        _LOGGER.debug("Nuki API request: %s %s params=%s json=%s", method, url, params, json)
        resp = await session.request(method, url, headers=headers, json=json, params=params)
        _LOGGER.debug("Nuki API response: %s %s -> status=%s content_type=%s", method, url, resp.status, resp.content_type)

        resp.raise_for_status()
        if resp.status == 204:
            return None
        if resp.content_type == "application/json":
            return await resp.json()
        return await resp.text()

    async def list_smartlocks(self) -> list[dict]:
        return await self._request("GET", "/smartlock")  # type: ignore[return-value]

    async def get_all_auths(self) -> list[dict]:
        return await self._request("GET", "/smartlock/auth")  # type: ignore[return-value]

    async def register_decentral_webhook(self, webhook_url: str, features: list[str]) -> dict:
        return await self._request(
            "PUT",
            "/api/decentralWebhook",
            json={"webhookUrl": webhook_url, "webhookFeatures": features},
        )

    async def delete_decentral_webhook(self, webhook_id: int) -> None:
        await self._request("DELETE", f"/api/decentralWebhook/{webhook_id}")
