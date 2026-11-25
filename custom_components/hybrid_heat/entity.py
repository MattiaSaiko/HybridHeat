"""Base entity and devices of Hybrid Heat.

One device for the house, one per zone (attached to its config subentry,
`via_device` the house). Entities read the coordinator: user settings from
`coordinator.settings`, decisions from `coordinator.data`. They never write a
setting on their own: the coordinator's Store is the single source of truth.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import HybridHeatCoordinator
from .engine.controller import ZoneResult
from .inputs import ZoneConfig

HOUSE = "house"


def _identifier(entry: ConfigEntry, scope: str) -> tuple[str, str]:
    return (DOMAIN, f"{entry.entry_id}_{scope}")


def house_device_info(entry: ConfigEntry) -> DeviceInfo:
    """Return the device of the house-wide entities."""
    return DeviceInfo(
        identifiers={_identifier(entry, HOUSE)},
        name=entry.title,
        entry_type=DeviceEntryType.SERVICE,
    )


def zone_device_info(entry: ConfigEntry, zone: ZoneConfig) -> DeviceInfo:
    """Return the device of a zone, linked to the house device."""
    return DeviceInfo(
        identifiers={_identifier(entry, zone.zone_id)},
        name=zone.name,
        entry_type=DeviceEntryType.SERVICE,
        via_device=_identifier(entry, HOUSE),
    )


@callback
def async_register_house_device(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Create the house device before the platforms add the zone devices.

    The platforms are set up concurrently, so a zone device could otherwise
    reference a `via_device` that does not exist yet.
    """
    dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, **house_device_info(entry)
    )


class HybridHeatEntity(CoordinatorEntity[HybridHeatCoordinator]):
    """An entity of the house (`zone` None) or of one zone."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: HybridHeatCoordinator,
        key: str,
        zone: ZoneConfig | None = None,
    ) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._zone_id = zone.zone_id if zone is not None else None
        scope = self._zone_id or HOUSE
        self._attr_unique_id = f"{entry.entry_id}_{scope}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = (
            zone_device_info(entry, zone)
            if zone is not None
            else house_device_info(entry)
        )

    @property
    def available(self) -> bool:
        """Unavailable without data or once the zone is no longer evaluated."""
        data = self.coordinator.data
        if not super().available or data is None:
            return False
        return self._zone_id is None or self._zone_id in data.zones

    @property
    def zone_id(self) -> str:
        """Return the zone id; only valid for zone entities."""
        assert self._zone_id is not None
        return self._zone_id

    @property
    def zone_result(self) -> ZoneResult | None:
        """Return the last decision for the zone, None when missing."""
        data = self.coordinator.data
        if data is None or self._zone_id is None:
            return None
        return data.zones.get(self._zone_id)
