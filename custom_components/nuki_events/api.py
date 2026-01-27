"""API client for Nuki Web."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from aiohttp import ClientResponseError

from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.config_entry_oauth2_flow import OAuth2Session

from .const import NUKI_BASE_URL


@dataclass
class NukiEvent:
    """Parsed Nuki event."""

    actor: str | None
    timestamp: str | None
    smartlock_name: str | None
    source: str | None


class NukiApi:
    """Nuki Web API client."""

    def __init__(self, session: OAuth2Session) -> None:
        """Initialize the API client."""
        self._session = session
        self._http = async_get_clientsession(session.hass)

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        """Make an authenticated request."""
        url = f"{NUKI_BASE_URL}{path}"
        token = await self._session.async_get_access_token()
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {token}"
        async with self._http.request(method, url, headers=headers, **kwargs) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def list_webhooks(self) -> list[dict[str, Any]]:
        """Return configured webhooks from Nuki Web."""
        data = await self._request("GET", "/webhooks")
        return data if isinstance(data, list) else data.get("webhooks", [])

    async def register_webhook(self, webhook_url: str) -> str:
        """Register the webhook endpoint with Nuki Web."""
        existing = await self.list_webhooks()
        for hook in existing:
            if hook.get("url") == webhook_url:
                return str(hook.get("id"))
        payload = {"url": webhook_url, "eventTypes": ["device_log"]}
        try:
            data = await self._request("POST", "/webhooks", json=payload)
        except ClientResponseError as err:
            if err.status != 409:
                raise
            existing = await self.list_webhooks()
            for hook in existing:
                if hook.get("url") == webhook_url:
                    return str(hook.get("id"))
            raise
        return str(data.get("id"))

    async def unregister_webhook(self, webhook_id: str) -> None:
        """Remove a webhook registration on Nuki Web."""
        await self._request("DELETE", f"/webhooks/{webhook_id}")

    async def get_smartlock_name(self, smartlock_id: int | None) -> str | None:
        """Fetch the smartlock name for a lock id."""
        if smartlock_id is None:
            return None
        data = await self._request("GET", f"/smartlocks/{smartlock_id}")
        return data.get("name")

    async def get_actor_name(self, actor_id: int | None) -> str | None:
        """Fetch the actor name for a user id."""
        if actor_id is None:
            return None
        data = await self._request("GET", f"/users/{actor_id}")
        return data.get("name")

    async def parse_event(self, payload: dict[str, Any]) -> NukiEvent:
        """Parse webhook payload into a structured event."""
        data = payload.get("data", payload)
        log = data.get("deviceLog", data.get("device_log", {}))
        actor_id = log.get("userId") or log.get("user_id")
        smartlock_id = log.get("smartlockId") or log.get("smartlock_id")
        actor_name = log.get("name") or await self.get_actor_name(actor_id)
        smartlock_name = log.get("smartlockName") or await self.get_smartlock_name(
            smartlock_id
        )
        return NukiEvent(
            actor=actor_name,
            timestamp=log.get("timestamp") or log.get("time"),
            smartlock_name=smartlock_name,
            source=log.get("source"),
        )
