from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import NukiApi
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


class NukiDataCoordinator(DataUpdateCoordinator[Any]):
    def __init__(self, hass: HomeAssistant, api: NukiApi) -> None:
        # Keep webhook-driven behavior: no polling interval.
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=None)
        self.api = api

    async def _async_update_data(self) -> Any:
        _LOGGER.debug("Coordinator update started")
        try:
            locks = await self.api.list_smartlocks()
            return locks
        except ConfigEntryAuthFailed:
            # Let HA handle reauth for the config entry
            _LOGGER.exception("Coordinator update auth failed (reauth required)")
            raise
        except Exception as err:
            _LOGGER.exception("Coordinator update failed: %s", err)
            raise UpdateFailed(str(err)) from err
        finally:
            _LOGGER.debug("Coordinator update finished")
