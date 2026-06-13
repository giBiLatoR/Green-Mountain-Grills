"""Button platform for the Green Mountain Grills integration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.exceptions import HomeAssistantError

from .const import LOGGER
from .entity import GMGBaseEntity

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from .coordinator import GMGConfigEntry, GMGCoordinator

PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class GMGButtonDescription(ButtonEntityDescription):
    """Describe a GMG button with a bound press callback."""

    press_fn: Callable[[GMGCoordinator], Awaitable[None]]


async def _start_cook(coordinator: GMGCoordinator) -> None:
    """Resolve helper-entity values and start a cook via the coordinator."""
    from .services import async_start_cook_from_helpers  # noqa: PLC0415

    await async_start_cook_from_helpers(coordinator.hass, coordinator)


async def _abort_cook(coordinator: GMGCoordinator) -> None:
    await coordinator.cook_manager.abort_cook()


BUTTONS: tuple[GMGButtonDescription, ...] = (
    GMGButtonDescription(
        key="power_on",
        translation_key="power_on",
        press_fn=lambda c: c.async_power_on(),
    ),
    GMGButtonDescription(
        key="power_off",
        translation_key="power_off",
        press_fn=lambda c: c.async_power_off(),
    ),
    GMGButtonDescription(
        key="cold_smoke",
        translation_key="cold_smoke",
        press_fn=lambda c: c.async_cold_smoke(),
    ),
    GMGButtonDescription(
        key="start_cook",
        translation_key="start_cook",
        press_fn=_start_cook,
    ),
    GMGButtonDescription(
        key="abort_cook",
        translation_key="abort_cook",
        press_fn=_abort_cook,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001
    entry: GMGConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up GMG buttons from a config entry."""
    coordinator = entry.runtime_data
    async_add_entities(GMGButton(coordinator, description) for description in BUTTONS)


class GMGButton(GMGBaseEntity, ButtonEntity):
    """A single GMG button backed by a description."""

    entity_description: GMGButtonDescription

    def __init__(
        self,
        coordinator: GMGCoordinator,
        description: GMGButtonDescription,
    ) -> None:
        """Initialize the button."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.info.serial}_{description.key}"

    async def async_press(self) -> None:
        """Invoke the description's press callback."""
        try:
            await self.entity_description.press_fn(self.coordinator)
        except HomeAssistantError:
            raise
        except Exception as err:
            LOGGER.exception("Unexpected error pressing %s", self.entity_description.key)
            raise HomeAssistantError(str(err)) from err
