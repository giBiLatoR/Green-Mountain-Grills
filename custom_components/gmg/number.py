"""Number platform for the Green Mountain Grills integration."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.const import UnitOfMass, UnitOfTemperature, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import (
    COOK_WEIGHT_STEP_KG,
    GRILL_TEMP_STEP_F,
    LOGGER,
    MAX_COOK_WEIGHT_KG,
    MAX_FINISH_IN_HOURS,
    MAX_GRILL_TEMP_F,
    MAX_PROBE_TARGET_F,
    MIN_COOK_WEIGHT_KG,
    MIN_FINISH_IN_HOURS,
    MIN_GRILL_TEMP_F,
    MIN_PROBE_TARGET_F,
)
from .coordinator import GMGConfigEntry, GMGCoordinator
from .entity import GMGBaseEntity

PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class GMGNumberDescription(NumberEntityDescription):
    """Describe a GMG number entity with bound read/write callbacks."""

    value_fn: Callable[[GMGCoordinator], int]
    set_fn: Callable[[GMGCoordinator, int], Awaitable[None]]


NUMBERS: tuple[GMGNumberDescription, ...] = (
    GMGNumberDescription(
        key="grill_setpoint",
        translation_key="grill_setpoint",
        device_class=NumberDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.FAHRENHEIT,
        native_min_value=MIN_GRILL_TEMP_F,
        native_max_value=MAX_GRILL_TEMP_F,
        native_step=GRILL_TEMP_STEP_F,
        mode=NumberMode.BOX,
        value_fn=lambda c: c.data.grill_set_temp,
        set_fn=lambda c, v: c.async_set_grill_temp(v),
    ),
    GMGNumberDescription(
        key="probe_1_target",
        translation_key="probe_1_target",
        device_class=NumberDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.FAHRENHEIT,
        native_min_value=MIN_PROBE_TARGET_F,
        native_max_value=MAX_PROBE_TARGET_F,
        native_step=1,
        mode=NumberMode.BOX,
        value_fn=lambda c: c.data.probe_1_target,
        set_fn=lambda c, v: c.async_set_probe_target(1, v),
    ),
    GMGNumberDescription(
        key="probe_2_target",
        translation_key="probe_2_target",
        device_class=NumberDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.FAHRENHEIT,
        native_min_value=MIN_PROBE_TARGET_F,
        native_max_value=MAX_PROBE_TARGET_F,
        native_step=1,
        mode=NumberMode.BOX,
        value_fn=lambda c: c.data.probe_2_target,
        set_fn=lambda c, v: c.async_set_probe_target(2, v),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GMGConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up GMG number entities from a config entry."""
    coordinator = entry.runtime_data
    async_add_entities(
        [
            *(GMGNumber(coordinator, d) for d in NUMBERS),
            GMGCookInputNumber(
                coordinator,
                key="cook_weight_kg",
                unit=UnitOfMass.KILOGRAMS,
                min_v=MIN_COOK_WEIGHT_KG,
                max_v=MAX_COOK_WEIGHT_KG,
                step=COOK_WEIGHT_STEP_KG,
                default=1.0,
            ),
            GMGCookInputNumber(
                coordinator,
                key="cook_finish_in_hours",
                unit=UnitOfTime.HOURS,
                min_v=MIN_FINISH_IN_HOURS,
                max_v=MAX_FINISH_IN_HOURS,
                step=0.25,
                default=12.0,
            ),
        ]
    )


class GMGNumber(GMGBaseEntity, NumberEntity):
    """A single GMG number entity backed by a description."""

    entity_description: GMGNumberDescription

    def __init__(
        self,
        coordinator: GMGCoordinator,
        description: GMGNumberDescription,
    ) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.info.serial}_{description.key}"

    @property
    def native_value(self) -> float | None:
        """Return the current value from the description."""
        return self.entity_description.value_fn(self.coordinator)

    async def async_set_native_value(self, value: float) -> None:
        """Push a new value to the grill via the description's set function."""
        try:
            await self.entity_description.set_fn(self.coordinator, int(value))
        except HomeAssistantError:
            raise
        except Exception as err:  # noqa: BLE001 - defensive boundary
            LOGGER.exception("Unexpected error setting %s", self.entity_description.key)
            raise HomeAssistantError(str(err)) from err


class GMGCookInputNumber(GMGBaseEntity, NumberEntity, RestoreEntity):
    """Local-only number used as a planning input for the auto-cook service."""

    _attr_mode = NumberMode.BOX

    def __init__(
        self,
        coordinator: GMGCoordinator,
        *,
        key: str,
        unit: str,
        min_v: float,
        max_v: float,
        step: float,
        default: float,
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.info.serial}_{key}"
        self._attr_translation_key = key
        self._attr_native_unit_of_measurement = unit
        self._attr_native_min_value = min_v
        self._attr_native_max_value = max_v
        self._attr_native_step = step
        self._attr_native_value = default
        self._key = key

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None:
            try:
                self._attr_native_value = float(last.state)
            except (TypeError, ValueError):
                pass

    async def async_set_native_value(self, value: float) -> None:
        self._attr_native_value = value
        self.async_write_ha_state()

    @property
    def available(self) -> bool:  # always available — purely local
        return True
