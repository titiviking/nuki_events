from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Mapping

from aiohttp import ClientResponseError

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers import config_entry_oauth2_flow

from .const import API_BASE

_LOGGER = logging.getLogger(__name__)


@dataclass
class NukiApi:
    hass: HomeAssistant
    entry: Any  # ConfigEntry, but keep loose to avoid circular typing issues
    oauth_session: config_entry_oauth2_flow.OAuth2Session

    async def _auth_headers(self) -> dict[str, str]:
        """Ensure token is valid and return Authorization header."""
        token = await self.oauth_session.async_ensure_token_valid()
        access_token = token.get("access_token")
        if not access_token:
            raise config_entry_oauth2_flow.OAuth2RequestException("Missing access_token in OAuth token")
        return {
            "accept": "application/json",
            "authorization": f"Bearer {access_token}",
        }

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict | None = None,
        params: Mapping[str, str] | None = None,
    ) -> Any:
        session = async_get_clientsession(self.hass)
        headers = await self._auth_headers()
        url = f"{API_BASE}{path}"

        _LOGGER.debug("Nuki API request: %s %s params=%s json=%s", method, url, params, json)
        async with session.request(method, url, headers=headers, json=json, params=params) as resp:
            _LOGGER.debug(
                "Nuki API response: %s %s -> status=%s content_type=%s",
                method,
                url,
                resp.status,
                resp.content_type,
            )

            # If auth fails even after ensure_token_valid, force reauth
            if resp.status in (401, 403):
                body = await resp.text()
                _LOGGER.error("Nuki API auth failed (%s): %s", resp.status, body)
                raise config_entry_oauth2_flow.OAuth2RequestException(
                    f"Authorization failed ({resp.status}): {body}"
                )

            # Raise for other errors
            try:
                resp.raise_for_status()
            except ClientResponseError:
                body = await resp.text()
                _LOGGER.error("Nuki API error response (%s): %s", resp.status, body)
                raise

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
