"""The Green Mountain Grills integration."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.const import CONF_HOST, CONF_PORT, UnitOfTemperature
from homeassistant.helpers import entity_registry as er

from .api import GMGClient
from .const import DEFAULT_PORT, DOMAIN, LOGGER, PLATFORMS
from .coordinator import GMGConfigEntry, GMGCoordinator
from .services import async_setup_services, async_unload_services
from .units import TEMP_UNIT_CELSIUS, TEMP_UNIT_FAHRENHEIT

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.typing import ConfigType

# Bundled dashboard assets (generic overlay + Lovelace auto-strategy).
STATIC_URL_PATH = "/gmg_static"
_FRONTEND_REGISTERED = f"{DOMAIN}_frontend_registered"

# Temperature entities whose display unit follows the integration's unit toggle.
_TEMP_SENSOR_KEYS = (
    "grill_temperature",
    "probe_1_temperature",
    "probe_2_temperature",
    "cook_expected_probe_temp",
    "cook_pit_target",
    "cook_pull_temp",
)
_TEMP_NUMBER_KEYS = ("grill_setpoint", "probe_1_target", "probe_2_target")


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:  # noqa: ARG001
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
    # Entities now exist in the registry — apply the chosen temperature unit.
    _async_apply_temperature_unit(hass, coordinator)
    return True


def _async_apply_temperature_unit(hass: HomeAssistant, coordinator: GMGCoordinator) -> None:
    """Force the display unit of the GMG temperature entities to the user's choice.

    Uses the supported entity-registry unit override (the same mechanism the HA
    UI's per-entity unit picker writes). ``auto`` clears the override so the
    entities follow the global HA unit system. Re-applied on every reload, so a
    change in the options flow (which reloads the entry) takes effect at once.
    """
    pref = coordinator.temperature_unit_pref
    if pref == TEMP_UNIT_CELSIUS:
        unit: str | None = UnitOfTemperature.CELSIUS
    elif pref == TEMP_UNIT_FAHRENHEIT:
        unit = UnitOfTemperature.FAHRENHEIT
    else:
        unit = None  # auto → defer to the HA unit system

    registry = er.async_get(hass)
    serial = coordinator.info.serial
    for domain, keys in (("sensor", _TEMP_SENSOR_KEYS), ("number", _TEMP_NUMBER_KEYS)):
        for key in keys:
            entity_id = registry.async_get_entity_id(domain, DOMAIN, f"{serial}_{key}")
            if entity_id is None:
                continue
            entry = registry.async_get(entity_id)
            options = dict(entry.options.get(domain, {})) if entry else {}
            if unit is None:
                options.pop("unit_of_measurement", None)
            else:
                options["unit_of_measurement"] = unit
            registry.async_update_entity_options(entity_id, domain, options)


async def async_unload_entry(hass: HomeAssistant, entry: GMGConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.client.async_close()
    if not hass.config_entries.async_loaded_entries(entry.domain):
        async_unload_services(hass)
    return unloaded


async def async_migrate_entry(hass: HomeAssistant, entry: GMGConfigEntry) -> bool:  # noqa: ARG001
    """Migrate an old config entry to the current schema."""
    return True
