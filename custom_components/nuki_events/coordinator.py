from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import NukiApi
from .const import DOMAIN, UPDATE_INTERVAL_SECONDS

_LOGGER = logging.getLogger("custom_components.nuki_events.coordinator")


class NukiDataCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Fetch data from Nuki and expose it to platforms."""

    def __init__(self, hass: HomeAssistant, api: NukiApi) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=None,  # we control interval below for clarity
        )
        self.api = api

        # If your const.py already defines an interval, use it. Otherwise you can
        # set update_interval in DataUpdateCoordinator directly.
        if UPDATE_INTERVAL_SECONDS:
            from datetime import timedelta
            self.update_interval = timedelta(seconds=UPDATE_INTERVAL_SECONDS)

    async def _async_update_data(self) -> dict[str, Any]:
        _LOGGER.debug("Coordinator update started")
        try:
            locks = await self.api.list_smartlocks()
            # You can add other API calls here later if needed
            data = {"locks": locks}
            return data

        except ConfigEntryAuthFailed:
            # Let HA handle reauth; do NOT wrap in UpdateFailed
            _LOGGER.exception("Coordinator auth failed (reauth required)")
            raise

        except Exception as err:
            # This makes HA log "success: False" and keeps retrying
            _LOGGER.exception("Coordinator update failed: %s", err)
            raise UpdateFailed(str(err)) from err
        finally:
            _LOGGER.debug("Coordinator update finished")
