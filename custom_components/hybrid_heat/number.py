"""Numbers: zone temperatures and the house-wide tunables."""

from __future__ import annotations

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfPower,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import HybridHeatConfigEntry
from .const import MIN_PER_C_MAX, MIN_PER_C_MIN
from .coordinator import HybridHeatCoordinator
from .entity import HybridHeatEntity
from .inputs import ZoneConfig

PARALLEL_UPDATES = 0

UNIT_MIN_PER_C = "min/°C"


def _temperature(key: str, low: float, high: float) -> NumberEntityDescription:
    return NumberEntityDescription(
        key=key,
        device_class=NumberDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        native_min_value=low,
        native_max_value=high,
        native_step=0.5,
    )


def _delay(key: str, high: float) -> NumberEntityDescription:
    return NumberEntityDescription(
        key=key,
        device_class=NumberDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        native_min_value=0,
        native_max_value=high,
        native_step=10,
    )


def _power(key: str, low: float, high: float) -> NumberEntityDescription:
    return NumberEntityDescription(
        key=key,
        device_class=NumberDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        native_min_value=low,
        native_max_value=high,
        native_step=50,
    )


# Entity key -> ZoneSettings field.
ZONE_NUMBERS: dict[str, NumberEntityDescription] = {
    "comfort_c": _temperature("comfort", 5, 30),
    "eco_c": _temperature("eco", 5, 30),
    "antifreeze_c": _temperature("antifreeze", 3, 15),
}

# The key is the Tunables field.
TUNABLE_NUMBERS: tuple[NumberEntityDescription, ...] = (
    _temperature("solar_on_c", 20, 90),
    _temperature("solar_high_c", 20, 95),
    # Not 0: without a grid sensor every zone would go to its climates.
    _power("pv_threshold_w", 50, 10000),
    _temperature("min_outdoor_c", -25, 15),
    # A temperature difference: no device class, so it is never converted
    # as an absolute temperature.
    NumberEntityDescription(
        key="climate_hyst_c",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        native_min_value=0.1,
        native_max_value=3,
        native_step=0.1,
    ),
    _power("climate_nominal_w", 100, 5000),
    # A temperature difference too: no device class.
    NumberEntityDescription(
        key="valve_safety_offset_c",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        native_min_value=0.5,
        native_max_value=5,
        native_step=0.5,
    ),
    NumberEntityDescription(
        key="preheat_default_min_per_c",
        native_unit_of_measurement=UNIT_MIN_PER_C,
        native_min_value=MIN_PER_C_MIN,
        native_max_value=MIN_PER_C_MAX,
        native_step=1,
    ),
    _delay("boiler_on_delay_s", 1800),
    _delay("boiler_off_delay_s", 1800),
    _delay("boiler_min_on_s", 3600),
    _delay("boiler_min_off_s", 3600),
    # A threshold, not a battery: no device class.
    NumberEntityDescription(
        key="battery_soc_min_pct",
        native_unit_of_measurement=PERCENTAGE,
        native_min_value=0,
        native_max_value=100,
        native_step=1,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HybridHeatConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the tunables and the temperatures of every zone."""
    coordinator = entry.runtime_data
    async_add_entities(
        TunableNumber(coordinator, description) for description in TUNABLE_NUMBERS
    )
    for zone in coordinator.zones:
        async_add_entities(
            (
                ZoneNumber(coordinator, zone, field, description)
                for field, description in ZONE_NUMBERS.items()
            ),
            config_subentry_id=zone.zone_id,
        )


class TunableNumber(HybridHeatEntity, NumberEntity):
    """A threshold or delay shared by the whole house."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = NumberMode.BOX

    def __init__(
        self,
        coordinator: HybridHeatCoordinator,
        description: NumberEntityDescription,
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> float:
        return getattr(self.coordinator.settings.tunables, self.entity_description.key)

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_set_tunable(self.entity_description.key, value)
        self.async_write_ha_state()


class ZoneNumber(HybridHeatEntity, NumberEntity):
    """Comfort, eco or antifreeze temperature of a zone."""

    def __init__(
        self,
        coordinator: HybridHeatCoordinator,
        zone: ZoneConfig,
        field: str,
        description: NumberEntityDescription,
    ) -> None:
        super().__init__(coordinator, description.key, zone)
        self.entity_description = description
        self._field = field

    @property
    def native_value(self) -> float:
        return getattr(self.coordinator.settings.zone(self.zone_id), self._field)

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_set_zone_value(self.zone_id, self._field, value)
        self.async_write_ha_state()
