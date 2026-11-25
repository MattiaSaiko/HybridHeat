"""Sensors: phase and target of each zone, active free source of the house."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import HybridHeatConfigEntry
from .coordinator import HybridHeatCoordinator
from .engine.models import Phase
from .entity import HybridHeatEntity
from .inputs import ZoneConfig

PARALLEL_UPDATES = 0

# Values of EngineResult.active_source (engine/sources.py).
ACTIVE_SOURCES = ["solar_thermal", "photovoltaic", "none"]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HybridHeatConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the house sensor and the sensors of every zone."""
    coordinator = entry.runtime_data
    async_add_entities([ActiveSourceSensor(coordinator)])
    for zone in coordinator.zones:
        async_add_entities(
            [PhaseSensor(coordinator, zone), TargetSensor(coordinator, zone)],
            config_subentry_id=zone.zone_id,
        )


class ActiveSourceSensor(HybridHeatEntity, SensorEntity):
    """Free source in use: solar thermal, photovoltaic or none."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ACTIVE_SOURCES

    def __init__(self, coordinator: HybridHeatCoordinator) -> None:
        super().__init__(coordinator, "active_source")

    @property
    def native_value(self) -> str | None:
        data = self.coordinator.data
        return data.active_source if data is not None else None


class PhaseSensor(HybridHeatEntity, SensorEntity):
    """Phase of a zone, with the stable keys of why it was chosen.

    `reason`, `actuator` and `actuator_reason` hold stable keys; their
    translations live under `state_attributes` of this entity.
    """

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = [phase.value for phase in Phase]

    def __init__(self, coordinator: HybridHeatCoordinator, zone: ZoneConfig) -> None:
        super().__init__(coordinator, "phase", zone)

    @property
    def native_value(self) -> str | None:
        result = self.zone_result
        return result.phase.value if result is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        result = self.zone_result
        if result is None:
            return None
        return {
            "reason": result.reason,
            "actuator": result.actuator.value,
            "actuator_reason": result.actuator_reason,
        }


class TargetSensor(HybridHeatEntity, SensorEntity):
    """Target temperature of a zone."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 1

    def __init__(self, coordinator: HybridHeatCoordinator, zone: ZoneConfig) -> None:
        super().__init__(coordinator, "target", zone)

    @property
    def native_value(self) -> float | None:
        result = self.zone_result
        return result.target_c if result is not None else None
