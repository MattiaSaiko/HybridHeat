"""Zone mode select: auto, comfort, eco, antifreeze, off."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import HybridHeatConfigEntry
from .coordinator import HybridHeatCoordinator
from .engine.models import Mode
from .entity import HybridHeatEntity
from .inputs import ZoneConfig

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HybridHeatConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add one mode select per zone."""
    coordinator = entry.runtime_data
    for zone in coordinator.zones:
        async_add_entities(
            [ModeSelect(coordinator, zone)], config_subentry_id=zone.zone_id
        )


class ModeSelect(HybridHeatEntity, SelectEntity):
    """Manual mode of a zone."""

    _attr_options = [mode.value for mode in Mode]

    def __init__(self, coordinator: HybridHeatCoordinator, zone: ZoneConfig) -> None:
        super().__init__(coordinator, "mode", zone)

    @property
    def current_option(self) -> str:
        return self.coordinator.settings.zone(self.zone_id).mode.value

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.async_set_mode(self.zone_id, Mode(option))
        self.async_write_ha_state()
