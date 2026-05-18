"""DataUpdateCoordinator for the GMG integration."""
from __future__ import annotations

import asyncio
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import (
    ConfigEntryNotReady,
    HomeAssistantError,
    ServiceValidationError,
)
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    GMGClient,
    GMGConnectionError,
    GMGGrillInfo,
    GMGInvalidValueError,
    GMGProtocolError,
    GMGServerModeError,
    GMGSnapshot,
    GMGTimeoutError,
)
from .api import GMGError
from .const import (
    CONF_AUTO_COOK_DEV_MODE,
    CONF_AUTO_COOK_ENABLED,
    CONF_AUTO_COOK_PUSH,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    LOGGER,
)
from .cook_manager import CookManager

type GMGConfigEntry = ConfigEntry[GMGCoordinator]

_SERVER_MODE_ISSUE = "server_mode_enabled"


class GMGCoordinator(DataUpdateCoordinator[GMGSnapshot]):
    """Coordinate polling against a single GMG grill."""

    config_entry: GMGConfigEntry
    info: GMGGrillInfo

    def __init__(
        self,
        hass: HomeAssistant,
        entry: GMGConfigEntry,
        client: GMGClient,
    ) -> None:
        """Initialize the coordinator."""
        self.client = client
        super().__init__(
            hass,
            LOGGER,
            config_entry=entry,
            name=f"GMG {entry.title}",
            update_interval=timedelta(
                seconds=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
            ),
            always_update=False,
        )
        self.cook_manager = CookManager(hass, self)
        self._refresh_cook_options(entry)

    def _refresh_cook_options(self, entry: GMGConfigEntry) -> None:
        """Push current options-flow values into the cook manager."""
        self.cook_manager.configure(
            auto_cook=bool(entry.options.get(CONF_AUTO_COOK_ENABLED, False)),
            dev_mode=bool(entry.options.get(CONF_AUTO_COOK_DEV_MODE, False)),
            push=bool(entry.options.get(CONF_AUTO_COOK_PUSH, False)),
        )

    async def _async_setup(self) -> None:
        """Probe the grill once before the first poll."""
        try:
            self.info = await self.client.async_probe()
        except GMGServerModeError as err:
            raise ConfigEntryNotReady(
                translation_domain=DOMAIN,
                translation_key=_SERVER_MODE_ISSUE,
                translation_placeholders={"host": self.client.host},
            ) from err
        except (GMGConnectionError, GMGTimeoutError) as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="cannot_connect",
                translation_placeholders={"host": self.client.host},
            ) from err
        except GMGProtocolError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="protocol_error",
            ) from err
        await self.cook_manager.async_init_db()

    async def _async_update_data(self) -> GMGSnapshot:
        """Fetch a snapshot from the grill."""
        try:
            async with asyncio.timeout(10):
                snapshot = await self.client.async_poll()
        except GMGServerModeError as err:
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                _SERVER_MODE_ISSUE,
                is_fixable=False,
                severity=ir.IssueSeverity.ERROR,
                translation_key=_SERVER_MODE_ISSUE,
                translation_placeholders={"host": self.client.host},
            )
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key=_SERVER_MODE_ISSUE,
                translation_placeholders={"host": self.client.host},
            ) from err
        except (GMGConnectionError, GMGTimeoutError, TimeoutError) as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="cannot_connect",
                translation_placeholders={"host": self.client.host},
            ) from err
        except GMGProtocolError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="protocol_error",
            ) from err

        ir.async_delete_issue(self.hass, DOMAIN, _SERVER_MODE_ISSUE)
        # Refresh options-flow values each poll cycle in case user toggled
        # auto-cook live, then let the cook manager run its control loop.
        self._refresh_cook_options(self.config_entry)
        try:
            await self.cook_manager.update(snapshot)
        except Exception:  # noqa: BLE001 — never let cook errors break polling
            LOGGER.exception("cook manager update raised")
        return snapshot

    async def async_set_grill_temp(self, f: int) -> None:
        """Set the grill setpoint temperature in Fahrenheit."""
        await self._call(self.client.async_set_grill_temp, f)

    async def async_set_probe_target(self, probe: int, f: int) -> None:
        """Set the target temperature for a meat probe."""
        await self._call(self.client.async_set_probe_target, probe, f)

    async def async_power_on(self) -> None:
        """Power on the grill."""
        await self._call(self.client.async_power_on)

    async def async_power_off(self) -> None:
        """Power off the grill."""
        await self._call(self.client.async_power_off)

    async def async_cold_smoke(self) -> None:
        """Engage cold smoke mode."""
        await self._call(self.client.async_cold_smoke)

    async def _call(self, func, /, *args) -> None:
        """Invoke a client command and refresh, mapping errors to HA exceptions."""
        try:
            await func(*args)
        except GMGInvalidValueError as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_value",
            ) from err
        except GMGServerModeError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key=_SERVER_MODE_ISSUE,
                translation_placeholders={"host": self.client.host},
            ) from err
        except (GMGConnectionError, GMGTimeoutError) as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="cannot_connect",
                translation_placeholders={"host": self.client.host},
            ) from err
        except GMGProtocolError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="protocol_error",
            ) from err
        except GMGError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="unknown_error",
            ) from err

        await self.async_request_refresh()
