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
    url = "/api/nuki_events/webhook/{token}"

    def __init__(self, hass) -> None:
        # HomeAssistantView injects self.hass at registration time, but that
        # injection is not guaranteed to have occurred before the first request
        # arrives (observed on Python 3.14 / HA 2026.x: AttributeError on
        # self.hass).  Storing hass explicitly in __init__ is the safe pattern.
        self._hass = hass

    async def post(self, request: web.Request, token: str) -> web.Response:
        # The token is a random per-registration suffix stored in entry.data.
        # hass.data[DOMAIN]["_token_map"] maps token -> entry_id so we can
        # look up the right coordinator without exposing the fixed entry_id
        # in the webhook URL.
        domain_data = self._hass.data.get(DOMAIN, {})
        token_map: dict[str, str] = domain_data.get("_token_map", {})
        entry_id = token_map.get(token)

        if not entry_id:
            _LOGGER.debug("Webhook received for unknown token=%s", token)
            return web.Response(status=404, text="Unknown token")

        data = domain_data.get(entry_id)
        if not data:
            _LOGGER.debug("Webhook received for token=%s but entry_id=%s has no data", token, entry_id)
            return web.Response(status=404, text="Unknown entry")

        secret = data.get("webhook_secret")
        if not secret:
            _LOGGER.warning("Webhook received but no secret stored for entry_id=%s", entry_id)
            return web.Response(status=401, text="No secret")

        body = await request.read()
        signature = request.headers.get("X-Nuki-Signature-SHA256", "")

        _LOGGER.debug(
            "Nuki webhook received (entry=%s), headers=%s",
            entry_id,
            {k: v for k, v in request.headers.items() if k.lower().startswith("x-nuki")},
        )
        _LOGGER.debug("Nuki webhook raw body (entry=%s): %s", entry_id, body.decode("utf-8", errors="replace"))

        expected = _hmac_sha256_hex(secret, body)
        if not signature or not hmac.compare_digest(signature.lower(), expected.lower()):
            _LOGGER.warning(
                "Invalid Nuki webhook signature (entry=%s). "
                "Received: %.8s… Expected: %.8s… Secret length: %d chars. "
                "If this persists after updating to v2.8.0+, reload the integration "
                "to force fresh webhook re-registration.",
                entry_id,
                signature,
                expected,
                len(secret),
            )
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