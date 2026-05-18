"""Select platform: meat type, cook mode, probe selection."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import LOGGER
from .cook_manager import CookMode
from .cook_physics import CP_MEATS
from .coordinator import GMGConfigEntry, GMGCoordinator
from .entity import GMGBaseEntity

PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class GMGSelectDescription(SelectEntityDescription):
    """Describe a GMG select with its option list and initial value."""

    options_fn: Callable[[], list[str]]
    default: str


SELECTS: tuple[GMGSelectDescription, ...] = (
    GMGSelectDescription(
        key="cook_meat_type",
        translation_key="cook_meat_type",
        options_fn=lambda: list(CP_MEATS.keys()),
        default="beef_brisket_packer",
    ),
    GMGSelectDescription(
        key="cook_mode",
        translation_key="cook_mode",
        options_fn=lambda: [m.value for m in CookMode],
        default=CookMode.AUTONOMOUS.value,
    ),
    GMGSelectDescription(
        key="cook_probe",
        translation_key="cook_probe",
        options_fn=lambda: ["1", "2"],
        default="1",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GMGConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up GMG select entities from a config entry."""
    coordinator = entry.runtime_data
    async_add_entities(
        GMGSelect(coordinator, description) for description in SELECTS
    )


class GMGSelect(GMGBaseEntity, SelectEntity, RestoreEntity):
    """A persistent select used by the auto-cook helpers."""

    entity_description: GMGSelectDescription

    def __init__(
        self,
        coordinator: GMGCoordinator,
        description: GMGSelectDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.info.serial}_{description.key}"
        self._attr_options = description.options_fn()
        self._attr_current_option = description.default

    async def async_added_to_hass(self) -> None:
        """Restore prior value if HA has one."""
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state in (self._attr_options or []):
            self._attr_current_option = last.state

    async def async_select_option(self, option: str) -> None:
        if option not in self._attr_options:
            LOGGER.warning("select %s rejected option %s", self.entity_description.key, option)
            return
        self._attr_current_option = option
        self.async_write_ha_state()
