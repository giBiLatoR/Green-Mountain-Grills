"""Binary sensor platform for the Green Mountain Grills integration."""
from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import GMGSnapshot, PowerState
from .cook_physics import expected_probe_at
from .coordinator import GMGConfigEntry, GMGCoordinator
from .entity import GMGBaseEntity

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class GMGBinarySensorDescription(BinarySensorEntityDescription):
    """Describe a GMG binary sensor with a snapshot-bound value function."""

    value_fn: Callable[[GMGSnapshot], bool]


BINARY_SENSORS: tuple[GMGBinarySensorDescription, ...] = (
    GMGBinarySensorDescription(
        key="low_pellet",
        translation_key="low_pellet",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda s: s.low_pellet,
    ),
    GMGBinarySensorDescription(
        key="fan_overload",
        translation_key="fan_overload",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.fan_overload,
    ),
    GMGBinarySensorDescription(
        key="auger_overload",
        translation_key="auger_overload",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.auger_overload,
    ),
    GMGBinarySensorDescription(
        key="ignitor_overload",
        translation_key="ignitor_overload",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.ignitor_overload,
    ),
    GMGBinarySensorDescription(
        key="low_voltage",
        translation_key="low_voltage",
        device_class=BinarySensorDeviceClass.BATTERY,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.low_voltage,
    ),
    GMGBinarySensorDescription(
        key="fan_disconnect",
        translation_key="fan_disconnect",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda s: s.fan_disconnect,
    ),
    GMGBinarySensorDescription(
        key="auger_disconnect",
        translation_key="auger_disconnect",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda s: s.auger_disconnect,
    ),
    GMGBinarySensorDescription(
        key="ignitor_disconnect",
        translation_key="ignitor_disconnect",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda s: s.ignitor_disconnect,
    ),
    GMGBinarySensorDescription(
        key="flame_on",
        translation_key="flame_on",
        device_class=BinarySensorDeviceClass.HEAT,
        value_fn=lambda s: s.flame_on,
    ),
    GMGBinarySensorDescription(
        key="cooking",
        translation_key="cooking",
        device_class=BinarySensorDeviceClass.RUNNING,
        value_fn=lambda s: s.power_state is not PowerState.OFF,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GMGConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up GMG binary sensors from a config entry."""
    coordinator = entry.runtime_data
    entities: list[BinarySensorEntity] = [
        GMGBinarySensor(coordinator, d) for d in BINARY_SENSORS
    ]
    entities.append(GMGCookOnScheduleSensor(coordinator))
    async_add_entities(entities)


class GMGBinarySensor(GMGBaseEntity, BinarySensorEntity):
    """A single GMG binary sensor backed by a description."""

    entity_description: GMGBinarySensorDescription

    def __init__(
        self,
        coordinator: GMGCoordinator,
        description: GMGBinarySensorDescription,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.info.serial}_{description.key}"

    @property
    def is_on(self) -> bool:
        """Return whether the underlying snapshot flag is set."""
        return self.entity_description.value_fn(self.coordinator.data)


class GMGCookOnScheduleSensor(GMGBaseEntity, BinarySensorEntity):
    """True when active cook probe is within tolerance of projected curve."""

    _attr_translation_key = "cook_on_schedule"

    def __init__(self, coordinator: GMGCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.info.serial}_cook_on_schedule"

    @property
    def is_on(self) -> bool | None:
        session = self.coordinator.cook_manager.session
        if session is None or session.cook_started_at is None:
            return None
        probe_f = (
            self.coordinator.data.probe_1_temp
            if session.probe_index == 1
            else self.coordinator.data.probe_2_temp
        )
        if probe_f is None:
            return None
        elapsed_h = (time.time() - session.cook_started_at) / 3600
        expected = expected_probe_at(session.projection, elapsed_h)
        return abs(expected - probe_f) <= 10.0
