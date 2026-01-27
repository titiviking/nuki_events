from __future__ import annotations

import hashlib
import hmac
import json
import logging

from aiohttp import web
from homeassistant.components.http import HomeAssistantView

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


def _hmac_sha256_hex(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


class NukiWebhookView(HomeAssistantView):
    requires_auth = False
    name = "api:nuki_events_webhook"
    url = "/api/nuki_events/webhook/{entry_id}"

    def __init__(self, hass) -> None:
        self.hass = hass

    async def post(self, request: web.Request, entry_id: str) -> web.Response:
        data = self.hass.data.get(DOMAIN, {}).get(entry_id)
        if not data:
            _LOGGER.debug("Webhook received for unknown entry_id=%s", entry_id)
            return web.Response(status=404, text="Unknown entry")

        secret = data.get("webhook_secret")
        if not secret:
            _LOGGER.warning("Webhook received but no secret stored for entry_id=%s", entry_id)
            return web.Response(status=401, text="No secret")

        body = await request.read()
        signature = request.headers.get("X-Nuki-Signature-SHA256", "")

        # Debug logging (payloads can be big; this is requested)
        _LOGGER.debug(
            "Nuki webhook received (entry=%s), headers=%s",
            entry_id,
            {k: v for k, v in request.headers.items() if k.lower().startswith("x-nuki")},
        )
        _LOGGER.debug("Nuki webhook raw body (entry=%s): %s", entry_id, body.decode("utf-8", errors="replace"))

        expected = _hmac_sha256_hex(secret, body)
        if not signature or not hmac.compare_digest(signature.lower(), expected.lower()):
            _LOGGER.warning("Invalid Nuki webhook signature (entry=%s).", entry_id)
            return web.Response(status=401, text="Bad signature")

        try:
            payload = json.loads(body.decode("utf-8"))
        except Exception as err:
            _LOGGER.warning("Invalid JSON payload from Nuki (entry=%s): %s", entry_id, err)
            return web.Response(status=400, text="Bad JSON")

        _LOGGER.debug("Nuki webhook payload (entry=%s): %s", entry_id, payload)

        coordinator = data["coordinator"]
        await coordinator.async_handle_webhook(entry_id, payload)
        return web.Response(status=200, text="OK")
