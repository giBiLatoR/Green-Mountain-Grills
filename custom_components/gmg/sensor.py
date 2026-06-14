"""Sensor platform for the Green Mountain Grills integration."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfTemperature, UnitOfTime

from .api import FireState, PowerState, WarnCode
from .cook_manager import CookState
from .cook_physics import CP_MEATS, elapsed_at_probe, expected_probe_at
from .entity import GMGBaseEntity

if TYPE_CHECKING:
    from collections.abc import Callable

    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
    from homeassistant.helpers.typing import StateType

    from .coordinator import GMGConfigEntry, GMGCoordinator

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class GMGSensorDescription(SensorEntityDescription):
    """Describe a GMG sensor with a coordinator-bound value function."""

    value_fn: Callable[[GMGCoordinator], StateType]


SENSORS: tuple[GMGSensorDescription, ...] = (
    GMGSensorDescription(
        key="grill_temperature",
        translation_key="grill_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.FAHRENHEIT,
        suggested_display_precision=0,
        value_fn=lambda c: c.data.grill_temp,
    ),
    GMGSensorDescription(
        key="probe_1_temperature",
        translation_key="probe_1_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.FAHRENHEIT,
        suggested_display_precision=0,
        entity_registry_enabled_default=True,
        value_fn=lambda c: c.data.probe_1_temp,
    ),
    GMGSensorDescription(
        key="probe_2_temperature",
        translation_key="probe_2_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.FAHRENHEIT,
        suggested_display_precision=0,
        entity_registry_enabled_default=True,
        value_fn=lambda c: c.data.probe_2_temp,
    ),
    GMGSensorDescription(
        key="power_state",
        translation_key="power_state",
        device_class=SensorDeviceClass.ENUM,
        options=[member.name.lower() for member in PowerState],
        value_fn=lambda c: c.data.power_state.name.lower(),
    ),
    GMGSensorDescription(
        key="fire_state",
        translation_key="fire_state",
        device_class=SensorDeviceClass.ENUM,
        options=[member.name.lower() for member in FireState],
        value_fn=lambda c: c.data.fire_state.name.lower(),
    ),
    GMGSensorDescription(
        key="warning",
        translation_key="warning",
        device_class=SensorDeviceClass.ENUM,
        entity_category=EntityCategory.DIAGNOSTIC,
        options=[member.name.lower() for member in WarnCode],
        value_fn=lambda c: c.data.warn_code.name.lower(),
    ),
    GMGSensorDescription(
        key="hopper",
        translation_key="hopper",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        entity_category=EntityCategory.DIAGNOSTIC,
        # Hopper level is a heuristic derived from auger runtime; disabled by default.
        entity_registry_enabled_default=False,
        value_fn=lambda c: c.data.hopper_pct,
    ),
    GMGSensorDescription(
        key="firmware_version",
        translation_key="firmware_version",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: c.info.firmware,
    ),
    GMGSensorDescription(
        key="model",
        translation_key="model",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda c: c.info.model,
    ),
)


def _cook_elapsed_minutes(c: GMGCoordinator) -> StateType:
    s = c.cook_manager.session
    if s is None or s.cook_started_at is None:
        return None
    return round((time.time() - s.cook_started_at) / 60, 1)


def _cook_remaining_minutes(c: GMGCoordinator) -> StateType:
    s = c.cook_manager.session
    if s is None or s.cook_started_at is None:
        return None
    probe = c.data.probe_1_temp if s.probe_index == 1 else c.data.probe_2_temp
    if probe is not None:
        # Live forecast: anchor remaining time to where the probe actually is on
        # the projection curve rather than wall-clock elapsed.
        elapsed_h = elapsed_at_probe(s.projection, float(probe))
        return round(max(0.0, (s.projection.total_hours - elapsed_h) * 60), 1)
    # No probe reading: fall back to a static wall-clock countdown.
    total_min = s.projection.total_hours * 60
    return round(max(0.0, total_min - (time.time() - s.cook_started_at) / 60), 1)


def _cook_expected_probe(c: GMGCoordinator) -> StateType:
    s = c.cook_manager.session
    if s is None or s.cook_started_at is None:
        return None
    elapsed_h = (time.time() - s.cook_started_at) / 3600
    return round(expected_probe_at(s.projection, elapsed_h), 1)


def _cook_pit_target(c: GMGCoordinator) -> StateType:
    s = c.cook_manager.session
    return s.pit_target_f if s is not None else None


def _cook_pull_temp(c: GMGCoordinator) -> StateType:
    s = c.cook_manager.session
    return CP_MEATS[s.meat_key].pull_f if s is not None else None


def _cook_state(c: GMGCoordinator) -> StateType:
    s = c.cook_manager.session
    return s.state.value if s is not None else CookState.IDLE.value


def _cook_meat_label(c: GMGCoordinator) -> StateType:
    s = c.cook_manager.session
    return CP_MEATS[s.meat_key].label if s is not None else None


COOK_SENSORS: tuple[GMGSensorDescription, ...] = (
    GMGSensorDescription(
        key="cook_state",
        translation_key="cook_state",
        device_class=SensorDeviceClass.ENUM,
        options=[s.value for s in CookState],
        value_fn=_cook_state,
    ),
    GMGSensorDescription(
        key="cook_meat",
        translation_key="cook_meat",
        value_fn=_cook_meat_label,
    ),
    GMGSensorDescription(
        key="cook_elapsed_minutes",
        translation_key="cook_elapsed_minutes",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_cook_elapsed_minutes,
    ),
    GMGSensorDescription(
        key="cook_remaining_minutes",
        translation_key="cook_remaining_minutes",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_cook_remaining_minutes,
    ),
    GMGSensorDescription(
        key="cook_expected_probe_temp",
        translation_key="cook_expected_probe_temp",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.FAHRENHEIT,
        value_fn=_cook_expected_probe,
    ),
    GMGSensorDescription(
        key="cook_pit_target",
        translation_key="cook_pit_target",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.FAHRENHEIT,
        value_fn=_cook_pit_target,
    ),
    GMGSensorDescription(
        key="cook_pull_temp",
        translation_key="cook_pull_temp",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.FAHRENHEIT,
        value_fn=_cook_pull_temp,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001
    entry: GMGConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up GMG sensors from a config entry."""
    coordinator = entry.runtime_data
    async_add_entities(
        GMGSensor(coordinator, description) for description in (*SENSORS, *COOK_SENSORS)
    )


class GMGSensor(GMGBaseEntity, SensorEntity):
    """A single GMG sensor backed by a description."""

    entity_description: GMGSensorDescription

    def __init__(
        self,
        coordinator: GMGCoordinator,
        description: GMGSensorDescription,
    ) -> None:
        """Initialize the sensor entity."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.info.serial}_{description.key}"

    @property
    def native_value(self) -> StateType:
        """Return the value from the description's value function."""
        return self.entity_description.value_fn(self.coordinator)
