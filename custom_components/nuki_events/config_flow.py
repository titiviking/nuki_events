from __future__ import annotations

import logging
from typing import Any

from homeassistant import config_entries
from homeassistant.helpers import config_entry_oauth2_flow

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


class OAuth2FlowHandler(config_entry_oauth2_flow.AbstractOAuth2FlowHandler, domain=DOMAIN):
    """Handle the OAuth2 configuration flow for Nuki."""

    DOMAIN = DOMAIN
    VERSION = 1

    @property
    def logger(self) -> logging.Logger:
        return _LOGGER

    async def async_oauth_create_entry(self, data: dict[str, Any]) -> config_entries.FlowResult:
        """Create or update a config entry after OAuth2 has completed."""
        # For reauth flows, HA will set `self.source` and `self.context["entry_id"]`
        if self.source == config_entries.SOURCE_REAUTH:
            entry_id = self.context.get("entry_id")
            if entry_id:
                entry = self.hass.config_entries.async_get_entry(entry_id)
                if entry:
                    new_data = {**entry.data, **data}
                    self.hass.config_entries.async_update_entry(entry, data=new_data)
                    return self.async_abort(reason="reauth_successful")

        # Prevent duplicates (single account typical)
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        return self.async_create_entry(title="Nuki Events", data=data)

    async def async_step_reauth(self, user_input: dict[str, Any] | None = None) -> config_entries.FlowResult:
        """Perform re-authentication."""
        # Standard pattern: show confirm step, then start OAuth again
        return await self.async_step_reauth_confirm(user_input)

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Confirm reauth."""
        if user_input is None:
            entry_id = self.context.get("entry_id")
            entry = self.hass.config_entries.async_get_entry(entry_id) if entry_id else None
            placeholders = {"name": entry.title} if entry else {}
            return self.async_show_form(
                step_id="reauth_confirm",
                description_placeholders=placeholders,
            )

        return await self.async_step_user()
