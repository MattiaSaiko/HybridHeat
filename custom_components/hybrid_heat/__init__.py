"""Hybrid Heat: picks valves, climates and boiler per zone using free energy."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError

from .const import DOMAIN, PLATFORMS
from .coordinator import HybridHeatCoordinator
from .entity import async_register_house_device

type HybridHeatConfigEntry = ConfigEntry[HybridHeatCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: HybridHeatConfigEntry) -> bool:
    """Set up Hybrid Heat from a config entry."""
    if hass.config.units.temperature_unit != UnitOfTemperature.CELSIUS:
        # The engine works in °C, but climate attributes and set_temperature
        # use the system unit: refuse to run rather than misread them.
        raise ConfigEntryError(
            translation_domain=DOMAIN, translation_key="unit_not_celsius"
        )
    coordinator = HybridHeatCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    coordinator.async_start()
    entry.runtime_data = coordinator
    # Sources changed or a zone subentry added/changed/removed: start over.
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    async_register_house_device(hass, entry)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: HybridHeatConfigEntry) -> bool:
    """Unload a config entry.

    No command is sent: valves keep their last setpoint. The coordinator's
    listeners and timers are stopped by its shutdown, which Home Assistant
    runs on unload.
    """
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload_entry(
    hass: HomeAssistant, entry: HybridHeatConfigEntry
) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
