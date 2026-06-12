"""Service handlers for the Green Mountain Grills integration.

Register these from custom_components.gmg.__init__.async_setup() by calling
``async_setup_services(hass)``. ``async_unload_services(hass)`` is provided for
symmetry but is not normally required since HA tears services down on reload.
"""
from __future__ import annotations

import voluptuous as vol

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import ATTR_TEMPERATURE
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er

from .api import GMGInvalidValueError
from .const import (
    DOMAIN,
    LOGGER,
    MAX_COOK_WEIGHT_KG,
    MAX_FINISH_IN_HOURS,
    MAX_PROBE_TARGET_F,
    MIN_COOK_WEIGHT_KG,
    MIN_FINISH_IN_HOURS,
    MIN_PROBE_TARGET_F,
)
from .cook_manager import CookManagerError, CookMode
from .cook_physics import CP_MEATS
from .coordinator import GMGConfigEntry, GMGCoordinator

ATTR_CONFIG_ENTRY_ID = "config_entry_id"
ATTR_PROBE = "probe"
ATTR_MEAT_KEY = "meat_key"
ATTR_WEIGHT_KG = "weight_kg"
ATTR_MODE = "mode"
ATTR_FINISH_IN_HOURS = "finish_in_hours"

SERVICE_SET_PROBE_TARGET = "set_probe_target"
SERVICE_REFRESH = "refresh"
SERVICE_START_COOK = "start_cook"
SERVICE_ABORT_COOK = "abort_cook"

_SET_PROBE_TARGET_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Required(ATTR_PROBE): vol.All(vol.Coerce(int), vol.Range(min=1, max=2)),
        vol.Required(ATTR_TEMPERATURE): vol.All(
            vol.Coerce(int),
            vol.Range(min=MIN_PROBE_TARGET_F, max=MAX_PROBE_TARGET_F),
        ),
    }
)

_REFRESH_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_CONFIG_ENTRY_ID): cv.string,
    }
)

_START_COOK_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Required(ATTR_MEAT_KEY): vol.In(list(CP_MEATS.keys())),
        vol.Required(ATTR_WEIGHT_KG): vol.All(
            vol.Coerce(float), vol.Range(min=MIN_COOK_WEIGHT_KG, max=MAX_COOK_WEIGHT_KG)
        ),
        vol.Required(ATTR_PROBE): vol.All(vol.Coerce(int), vol.Range(min=1, max=2)),
        vol.Optional(ATTR_MODE, default=CookMode.AUTONOMOUS.value): vol.In(
            [m.value for m in CookMode]
        ),
        vol.Required(ATTR_FINISH_IN_HOURS): vol.All(
            vol.Coerce(float),
            vol.Range(min=MIN_FINISH_IN_HOURS, max=MAX_FINISH_IN_HOURS),
        ),
    }
)

_ABORT_COOK_SCHEMA = vol.Schema(
    {vol.Required(ATTR_CONFIG_ENTRY_ID): cv.string}
)


def _resolve_coordinator(
    hass: HomeAssistant, entry_id: str
) -> GMGCoordinator:
    """Resolve a loaded GMG coordinator by config entry id."""
    entry: GMGConfigEntry | None = hass.config_entries.async_get_entry(entry_id)
    if entry is None or entry.domain != DOMAIN:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="entry_not_found",
            translation_placeholders={"entry_id": entry_id},
        )
    if entry.state is not ConfigEntryState.LOADED:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="entry_not_loaded",
            translation_placeholders={"entry_id": entry_id},
        )
    return entry.runtime_data


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the GMG domain services."""

    async def _async_set_probe_target(call: ServiceCall) -> None:
        """Handle gmg.set_probe_target."""
        coordinator = _resolve_coordinator(hass, call.data[ATTR_CONFIG_ENTRY_ID])
        probe = call.data[ATTR_PROBE]
        temperature = call.data[ATTR_TEMPERATURE]
        try:
            await coordinator.async_set_probe_target(probe, temperature)
        except ServiceValidationError:
            raise
        except GMGInvalidValueError as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_value",
            ) from err
        except HomeAssistantError:
            raise
        except Exception as err:  # noqa: BLE001 - defensive service boundary
            LOGGER.exception("set_probe_target service failed")
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="service_call_failed",
            ) from err

    async def _async_refresh(call: ServiceCall) -> None:
        """Handle gmg.refresh."""
        coordinator = _resolve_coordinator(hass, call.data[ATTR_CONFIG_ENTRY_ID])
        await coordinator.async_request_refresh()

    async def _async_start_cook(call: ServiceCall) -> None:
        coordinator = _resolve_coordinator(hass, call.data[ATTR_CONFIG_ENTRY_ID])
        if coordinator.data is None:
            raise ServiceValidationError("no snapshot available yet")
        try:
            await coordinator.cook_manager.start_cook(
                meat_key=call.data[ATTR_MEAT_KEY],
                weight_kg=call.data[ATTR_WEIGHT_KG],
                probe_index=call.data[ATTR_PROBE],
                mode=CookMode(call.data[ATTR_MODE]),
                finish_in_hours=call.data[ATTR_FINISH_IN_HOURS],
                snapshot=coordinator.data,
            )
        except CookManagerError as err:
            raise ServiceValidationError(str(err)) from err

    async def _async_abort_cook(call: ServiceCall) -> None:
        coordinator = _resolve_coordinator(hass, call.data[ATTR_CONFIG_ENTRY_ID])
        await coordinator.cook_manager.abort_cook()

    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_PROBE_TARGET,
        _async_set_probe_target,
        schema=_SET_PROBE_TARGET_SCHEMA,
        supports_response=SupportsResponse.NONE,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_REFRESH,
        _async_refresh,
        schema=_REFRESH_SCHEMA,
        supports_response=SupportsResponse.NONE,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_START_COOK,
        _async_start_cook,
        schema=_START_COOK_SCHEMA,
        supports_response=SupportsResponse.NONE,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_ABORT_COOK,
        _async_abort_cook,
        schema=_ABORT_COOK_SCHEMA,
        supports_response=SupportsResponse.NONE,
    )


async def async_start_cook_from_helpers(
    hass: HomeAssistant, coordinator: GMGCoordinator
) -> None:
    """Resolve helper-entity values for this grill and start a cook.

    Used by the button.start_cook entity. Pulls meat/mode/probe from the
    select entities and weight/finish-in-hours from the number entities.
    """
    serial = coordinator.info.serial
    registry = er.async_get(hass)
    # Resolve by registry unique_id ({serial}_{key}) so renamed or
    # collision-suffixed entity_ids still resolve correctly.
    slot_to_domain = {
        "cook_meat_type": "select",
        "cook_mode": "select",
        "cook_probe": "select",
        "cook_weight_kg": "number",
        "cook_finish_in_hours": "number",
    }
    values: dict[str, str | None] = {}
    for slot, domain in slot_to_domain.items():
        entity_id = registry.async_get_entity_id(domain, DOMAIN, f"{serial}_{slot}")
        st = hass.states.get(entity_id) if entity_id is not None else None
        values[slot] = st.state if st is not None else None
    missing = [k for k, v in values.items() if v in (None, "unknown", "unavailable")]
    if missing:
        raise ServiceValidationError(
            f"missing auto-cook helper values: {', '.join(missing)}"
        )
    if coordinator.data is None:
        raise ServiceValidationError("no snapshot available yet")
    try:
        await coordinator.cook_manager.start_cook(
            meat_key=values["cook_meat_type"],
            weight_kg=float(values["cook_weight_kg"]),
            probe_index=int(values["cook_probe"]),
            mode=CookMode(values["cook_mode"]),
            finish_in_hours=float(values["cook_finish_in_hours"]),
            snapshot=coordinator.data,
        )
    except CookManagerError as err:
        raise ServiceValidationError(str(err)) from err


@callback
def async_unload_services(hass: HomeAssistant) -> None:
    """Remove the GMG domain services."""
    for service in (
        SERVICE_SET_PROBE_TARGET,
        SERVICE_REFRESH,
        SERVICE_START_COOK,
        SERVICE_ABORT_COOK,
    ):
        if hass.services.has_service(DOMAIN, service):
            hass.services.async_remove(DOMAIN, service)
