"""The Green Mountain Grills integration."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant

from .api import GMGClient
from .const import DEFAULT_PORT, DOMAIN, LOGGER, PLATFORMS
from .coordinator import GMGConfigEntry, GMGCoordinator
from .services import async_setup_services, async_unload_services

if TYPE_CHECKING:
    from homeassistant.helpers.typing import ConfigType

# Bundled dashboard assets (generic overlay + Lovelace auto-strategy).
STATIC_URL_PATH = "/gmg_static"
_FRONTEND_REGISTERED = f"{DOMAIN}_frontend_registered"


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register integration-wide services and dashboard assets exactly once."""
    async_setup_services(hass)
    await _async_register_frontend(hass)
    return True


async def _async_register_frontend(hass: HomeAssistant) -> None:
    """Serve the bundled static assets and load the Lovelace strategy once."""
    if hass.data.get(_FRONTEND_REGISTERED):
        return
    static_dir = Path(__file__).parent / "static"
    try:
        await hass.http.async_register_static_paths(
            [StaticPathConfig(STATIC_URL_PATH, str(static_dir), cache_headers=False)]
        )
        add_extra_js_url(hass, f"{STATIC_URL_PATH}/gmg-smoker-strategy.js")
    except Exception:  # noqa: BLE001 — never block setup on a dashboard extra
        LOGGER.exception("failed to register GMG dashboard assets")
        return
    hass.data[_FRONTEND_REGISTERED] = True


async def async_setup_entry(hass: HomeAssistant, entry: GMGConfigEntry) -> bool:
    """Set up a GMG grill from a config entry."""
    client = GMGClient(
        host=entry.data[CONF_HOST],
        port=entry.data.get(CONF_PORT, DEFAULT_PORT),
    )
    coordinator = GMGCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: GMGConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.client.async_close()
    if not hass.config_entries.async_loaded_entries(entry.domain):
        async_unload_services(hass)
    return unloaded


async def async_migrate_entry(hass: HomeAssistant, entry: GMGConfigEntry) -> bool:
    """Migrate an old config entry to the current schema."""
    return True
