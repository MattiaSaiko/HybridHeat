"""Plain data models for the heating engine (no Home Assistant imports)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Phase(StrEnum):
    """Phase a zone is in."""

    OFF = "off"
    ANTIFREEZE = "antifreeze"
    WINDOW_OPEN = "window_open"
    ECO = "eco"
    PREHEATING = "preheating"
    MAINTENANCE = "maintenance"


class Mode(StrEnum):
    """Manual mode of a zone."""

    AUTO = "auto"
    COMFORT = "comfort"
    ECO = "eco"
    ANTIFREEZE = "antifreeze"
    OFF = "off"


class Actuator(StrEnum):
    """Actuator chosen to heat a zone."""

    VALVES = "valves"
    CLIMATE = "climate"
    NONE = "none"


@dataclass(frozen=True)
class ZoneSettings:
    """User settings of a zone."""

    mode: Mode
    comfort_c: float
    eco_c: float
    antifreeze_c: float


@dataclass(frozen=True)
class ZoneInputs:
    """Measured state of a zone for one evaluation cycle."""

    zone_id: str
    has_climate: bool
    has_valves: bool
    temperature_c: float | None
    window_open_s: float | None
    schedule_on: bool
    minutes_to_next_comfort: float | None
    preheat_lead_min: float
    valves_calling_heat: bool
    climate_power_w: float
    settings: ZoneSettings


@dataclass(frozen=True)
class HouseInputs:
    """Measured state shared by the whole house."""

    enabled: bool
    anyone_home: bool | None
    outdoor_c: float | None
    solar_c: float | None
    # Net power available for heating before the climates' own consumption:
    # grid export minus import, plus the battery charging power when it counts.
    grid_export_w: float | None
    boiler_configured: bool


@dataclass(frozen=True)
class Tunables:
    """Adjustable thresholds and delays."""

    solar_on_c: float = 40.0
    solar_hyst_c: float = 3.0
    solar_high_c: float = 50.0
    min_outdoor_c: float = -5.0
    outdoor_hyst_c: float = 1.0
    climate_hyst_c: float = 0.5
    pv_threshold_w: float = 500.0
    pv_hold_ratio: float = 0.5
    climate_nominal_w: float = 1000.0
    valve_deadband_c: float = 0.4
    valve_safety_offset_c: float = 1.5
    preheat_enter_c: float = 1.0
    preheat_exit_c: float = 0.3
    preheat_default_min_per_c: float = 30.0
    preheat_max_min: float = 180.0
    window_delay_s: float = 120.0
    boiler_on_delay_s: float = 60.0
    boiler_off_delay_s: float = 180.0
    boiler_min_on_s: float = 300.0
    boiler_min_off_s: float = 300.0
    boiler_call_margin_c: float = 0.3
    deficit_c: float = 1.0
    deficit_min: float = 30.0
    solar_never_boiler: bool = False
    # Read by the Home Assistant layer only, when it builds `grid_export_w`.
    battery_surplus_enabled: bool = True
    battery_soc_min_pct: float = 0.0
