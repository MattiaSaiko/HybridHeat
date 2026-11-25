"""Zone thermostat: a standard climate entity backed by the coordinator."""

from __future__ import annotations

from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
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
    """Add one thermostat per zone."""
    coordinator = entry.runtime_data
    for zone in coordinator.zones:
        async_add_entities(
            [ZoneClimate(coordinator, zone)], config_subentry_id=zone.zone_id
        )


class ZoneClimate(HybridHeatEntity, ClimateEntity):
    """Thermostat of a zone: reads the coordinator, writes through it."""

    _attr_name = None
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT]
    _attr_preset_modes = [mode.value for mode in Mode if mode is not Mode.OFF]
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.PRESET_MODE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )
    _attr_min_temp = 5.0
    _attr_max_temp = 30.0
    _attr_target_temperature_step = 0.5

    def __init__(self, coordinator: HybridHeatCoordinator, zone: ZoneConfig) -> None:
        super().__init__(coordinator, "zone", zone)

    @property
    def _mode(self) -> Mode:
        return self.coordinator.settings.zone(self.zone_id).mode

    @property
    def hvac_mode(self) -> HVACMode:
        return HVACMode.OFF if self._mode is Mode.OFF else HVACMode.HEAT

    @property
    def hvac_action(self) -> HVACAction | None:
        if self.hvac_mode is HVACMode.OFF:
            return HVACAction.OFF
        result = self.zone_result
        if result is None:
            return None
        return HVACAction.HEATING if result.heat_request else HVACAction.IDLE

    @property
    def preset_mode(self) -> str | None:
        mode = self._mode
        return None if mode is Mode.OFF else mode.value

    @property
    def current_temperature(self) -> float | None:
        result = self.zone_result
        return result.temperature_c if result is not None else None

    @property
    def target_temperature(self) -> float | None:
        result = self.zone_result
        if result is None or self._mode is Mode.OFF:
            return None
        return result.target_c

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        result = self.zone_result
        if result is None:
            return {}
        return {"phase": result.phase.value, "reason": result.reason}

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        if hvac_mode is HVACMode.OFF:
            await self.coordinator.async_set_mode(self.zone_id, Mode.OFF)
        elif self._mode is Mode.OFF:
            await self.coordinator.async_set_mode(self.zone_id, Mode.AUTO)
        self.async_write_ha_state()

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        await self.coordinator.async_set_mode(self.zone_id, Mode(preset_mode))
        self.async_write_ha_state()

    async def async_set_temperature(self, **kwargs: Any) -> None:
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return
        mode = self._mode
        result = self.zone_result
        if mode is Mode.COMFORT or mode is Mode.OFF:
            key = "comfort_c"
        elif mode is Mode.ANTIFREEZE:
            key = "antifreeze_c"
        elif mode is Mode.ECO:
            key = "eco_c"
        else:
            key = (
                "comfort_c"
                if result is not None and result.is_comfort
                else "eco_c"
            )
        await self.coordinator.async_set_zone_value(self.zone_id, key, temperature)
        self.async_write_ha_state()
