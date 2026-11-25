"""Binary sensors: heat request of each zone, boiler request of the house."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import HybridHeatConfigEntry
from .const import CONF_BOILER
from .coordinator import HybridHeatCoordinator
from .entity import HybridHeatEntity
from .inputs import ZoneConfig

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HybridHeatConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the boiler request (only with a boiler) and the zone heat requests."""
    coordinator = entry.runtime_data
    if entry.data.get(CONF_BOILER):
        async_add_entities([BoilerRequestedSensor(coordinator)])
    for zone in coordinator.zones:
        async_add_entities(
            [HeatRequestSensor(coordinator, zone)], config_subentry_id=zone.zone_id
        )


class BoilerRequestedSensor(HybridHeatEntity, BinarySensorEntity):
    """Whether the engine wants the boiler on."""

    def __init__(self, coordinator: HybridHeatCoordinator) -> None:
        super().__init__(coordinator, "boiler_requested")

    @property
    def is_on(self) -> bool | None:
        data = self.coordinator.data
        return data.boiler_on if data is not None else None


class HeatRequestSensor(HybridHeatEntity, BinarySensorEntity):
    """Whether a zone is asking for heat from its valves or climates."""

    def __init__(self, coordinator: HybridHeatCoordinator, zone: ZoneConfig) -> None:
        super().__init__(coordinator, "heat_request", zone)

    @property
    def is_on(self) -> bool | None:
        result = self.zone_result
        return result.heat_request if result is not None else None
