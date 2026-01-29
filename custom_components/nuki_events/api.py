from __future__ import annotations

import asyncio
import logging
from typing import Any

from aiohttp import ClientResponseError
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import API_BASE

_LOGGER = logging.getLogger("custom_components.nuki_events.api")


class NukiApi:
    """Thin Nuki Web API client using HA-managed OAuth2Session."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        oauth_session: Any,
        api_base: str | None = None,
        request_timeout: int = 30,
    ) -> None:
        self.hass = hass
        self.entry = entry
        self.oauth_session = oauth_session
        self.api_base = (api_base or API_BASE).rstrip("/")
        self.request_timeout = request_timeout

    async def _auth_headers(self) -> dict[str, str]:
    token = await self.oauth_session.async_ensure_token_valid()

    # async_ensure_token_valid() can return None if token storage is missing/invalid
    if not token or not isinstance(token, dict):
        raise ConfigEntryAuthFailed("Missing OAuth token (reauth required)")

    access_token = token.get("access_token")
    if not access_token:
        raise ConfigEntryAuthFailed("OAuth token missing access_token (reauth required)")

    return {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
    }

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any | None = None,
    ) -> Any:
        """Make an authenticated request to Nuki API.

        - Raises ConfigEntryAuthFailed on 401/403 so HA flags reauth.
        - Raises for other HTTP errors (caller/coordinator will turn into UpdateFailed).
        """
        session = async_get_clientsession(self.hass)
        url = f"{self.api_base}{path}"

        headers = await self._auth_headers()

        try:
            async with asyncio.timeout(self.request_timeout):
                async with session.request(
                    method,
                    url,
                    headers=headers,
                    params=params,
                    json=json,
                ) as resp:
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

                    # Some endpoints might return empty bodies
                    content_type = resp.headers.get("Content-Type", "")
                    if "application/json" in content_type.lower():
                        return await resp.json()

                    # Fallback: text (or empty)
                    text = await resp.text()
                    return text if text else None

        except ConfigEntryAuthFailed:
            raise
        except ClientResponseError as err:
            _LOGGER.error(
                "Nuki API HTTP error (%s) for %s %s: %s",
                getattr(err, "status", "?"),
                method,
                path,
                err,
            )
            raise
        except TimeoutError:
            _LOGGER.error("Nuki API timeout for %s %s", method, path)
            raise
        except Exception:
            _LOGGER.exception("Unexpected Nuki API error for %s %s", method, path)
            raise

    # ---------- Public API used by the integration ----------

    async def list_smartlocks(self) -> list[dict[str, Any]]:
        data = await self._request("GET", "/smartlock")
        # Nuki returns JSON list here
        if data is None:
            return []
        if isinstance(data, list):
            return data
        # If API ever changes shape, keep integration alive + log
        _LOGGER.error("Unexpected /smartlock response type=%s value=%r", type(data).__name__, data)
        return []

    async def register_decentral_webhook(self, webhook_url: str, features: list[str] | None = None) -> dict[str, Any] | None:
        payload: dict[str, Any] = {"url": webhook_url}
        if features is not None:
            payload["features"] = features

        data = await self._request("POST", "/webhook/decentral", json=payload)
        return data if isinstance(data, dict) else None

    async def delete_decentral_webhook(self, webhook_id: int) -> None:
        await self._request("DELETE", f"/webhook/decentral/{int(webhook_id)}")
