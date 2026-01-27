"""Config flow for Nuki Events."""
from __future__ import annotations

from homeassistant.helpers import config_entry_oauth2_flow

from .const import DEFAULT_OAUTH_NAME, DOMAIN


class ConfigFlow(config_entry_oauth2_flow.OAuth2FlowHandler, domain=DOMAIN):
    """Handle OAuth2 configuration flow for Nuki."""

    async def async_oauth_create_entry(self, data):
        """Create an entry for the flow."""
        return self.async_create_entry(title=DEFAULT_OAUTH_NAME, data=data)
