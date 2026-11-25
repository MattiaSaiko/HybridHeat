"""Switches of Hybrid Heat: the main switch and the boolean settings."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import HybridHeatConfigEntry
from .coordinator import HybridHeatCoordinator
from .entity import HybridHeatEntity

PARALLEL_UPDATES = 0

# Boolean Tunables exposed as configuration switches; the key is the field.
#   solar_never_boiler: disable the boiler deficit override while solar
#     thermal is active.
#   battery_surplus_enabled: count battery charging as photovoltaic surplus.
TUNABLE_SWITCHES = ("solar_never_boiler", "battery_surplus_enabled")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HybridHeatConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the house switches."""
    coordinator = entry.runtime_data
    async_add_entities(
        [
            EnabledSwitch(coordinator),
            *(TunableSwitch(coordinator, key) for key in TUNABLE_SWITCHES),
        ]
    )


class EnabledSwitch(HybridHeatEntity, SwitchEntity):
    """Main switch: off switches the devices off once, then commands nothing."""

    def __init__(self, coordinator: HybridHeatCoordinator) -> None:
        super().__init__(coordinator, "enabled")

    @property
    def is_on(self) -> bool:
        return self.coordinator.settings.enabled

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_enabled(True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_enabled(False)
        self.async_write_ha_state()


class TunableSwitch(HybridHeatEntity, SwitchEntity):
    """A boolean setting of the whole house."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: HybridHeatCoordinator, key: str) -> None:
        super().__init__(coordinator, key)
        self._key = key

    @property
    def is_on(self) -> bool:
        return getattr(self.coordinator.settings.tunables, self._key)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_tunable(self._key, True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_tunable(self._key, False)
        self.async_write_ha_state()
