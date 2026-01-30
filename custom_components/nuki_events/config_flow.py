from __future__ import annotations

import logging
import time
from typing import Any

from homeassistant import config_entries
from homeassistant.helpers import config_entry_oauth2_flow

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


class OAuth2FlowHandler(config_entry_oauth2_flow.AbstractOAuth2FlowHandler, domain=DOMAIN):
    """Config flow to handle OAuth2 authentication."""

    DOMAIN = DOMAIN
    VERSION = 1

    def __init__(self) -> None:
        super().__init__()
        self._reauth_entry: config_entries.ConfigEntry | None = None

    @property
    def logger(self) -> logging.Logger:
        """Return logger for AbstractOAuth2FlowHandler."""
        return _LOGGER

    async def async_step_reauth(self, user_input: dict[str, Any] | None = None) -> config_entries.FlowResult:
        """Handle re-auth initiated by ConfigEntryAuthFailed (HA 2026.1 expects this step)."""
        entry_id = self.context.get("entry_id")
        if entry_id:
            self._reauth_entry = self.hass.config_entries.async_get_entry(entry_id)

        # show a confirmation first (standard HA pattern)
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Confirm reauth then restart OAuth."""
        if user_input is None:
            placeholders = {}
            if self._reauth_entry:
                placeholders["name"] = self._reauth_entry.title
            return self.async_show_form(
                step_id="reauth_confirm",
                description_placeholders=placeholders,
            )

        # Continue with normal OAuth flow
        return await self.async_step_user()

    def _normalize_token(self, data: dict[str, Any]) -> dict[str, Any]:
        """Validate and normalize token coming from OAuth completion.

        Fix:
        - Ensure token is present and has access_token.
        - Ensure expires_at exists (HA OAuth2Session expects it).
        """
        token = data.get("token")

        # Token must exist and be a dict with an access_token
        if not isinstance(token, dict) or not token.get("access_token"):
            _LOGGER.error("OAuth completed but token is missing/invalid: %r", token)
            raise config_entries.AbortFlow("oauth_token_missing")

        # Ensure expires_at exists if expires_in is present
        if "expires_at" not in token:
            expires_in = token.get("expires_in")
            if expires_in is not None:
                try:
                    token["expires_at"] = time.time() + int(expires_in) - 60
                except (TypeError, ValueError):
                    # If expires_in is garbage, leave expires_at absent (HA may still refresh)
                    pass

        data["token"] = token
        return data

    async def async_oauth_create_entry(self, data: dict[str, Any]) -> config_entries.FlowResult:
        """Create (or update) the config entry after OAuth is complete."""
        _LOGGER.debug("OAuth completed; creating config entry (keys=%s)", list(data.keys()))

        data = self._normalize_token(data)

        # If this is reauth, update the existing entry instead of creating a new one
        if self.source == config_entries.SOURCE_REAUTH and self._reauth_entry:
            _LOGGER.info("Reauth successful; updating existing config entry")
            new_data = dict(self._reauth_entry.data)
            new_data.update(data)
            self.hass.config_entries.async_update_entry(self._reauth_entry, data=new_data)
            return self.async_abort(reason="reauth_successful")

        return self.async_create_entry(title="Nuki Events", data=data)
