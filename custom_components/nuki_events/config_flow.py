from __future__ import annotations

import logging
from typing import Any

from homeassistant import config_entries
from homeassistant.helpers import config_entry_oauth2_flow

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


class OAuth2FlowHandler(config_entry_oauth2_flow.AbstractOAuth2FlowHandler, domain=DOMAIN):
    """Config flow to handle OAuth2 authentication using HA's default handlers."""

    DOMAIN = DOMAIN
    VERSION = 1

    @property
    def logger(self) -> logging.Logger:
        """Return logger for AbstractOAuth2FlowHandler."""
        return _LOGGER

    async def async_oauth_create_entry(self, data: dict[str, Any]) -> config_entries.FlowResult:
        """Create the config entry after OAuth is complete."""
        _LOGGER.debug("OAuth completed; creating config entry (keys=%s)", list(data.keys()))
        return self.async_create_entry(title="Nuki Events", data=data)
