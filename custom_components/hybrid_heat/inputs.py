"""Read Home Assistant states into the engine's input dataclasses.

Every reader is defensive: a missing entity, an `unavailable`/`unknown`
state or a non-numeric value becomes `None` (or 0 W for power) and never
raises. Power sensors are converted to W from their unit of measurement.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, fields
from datetime import datetime, time
from typing import Any

from homeassistant.components.climate import (
    ATTR_CURRENT_TEMPERATURE,
    ATTR_HVAC_ACTION,
    HVACAction,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_UNIT_OF_MEASUREMENT,
    PERCENTAGE,
    STATE_HOME,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    UnitOfPower,
)
from homeassistant.core import HomeAssistant, State
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_conversion import PowerConverter

from .const import (
    CONF_BATTERY_CHARGE,
    CONF_BATTERY_DISCHARGE,
    CONF_BATTERY_INVERT,
    CONF_BATTERY_SOC,
    CONF_BOILER,
    CONF_CLIMATE_POWER,
    CONF_CLIMATES,
    CONF_NAME,
    CONF_OUTDOOR_TEMP,
    CONF_PRESENCE,
    CONF_PROGRAM,
    CONF_PV_EXPORT,
    CONF_PV_IMPORT,
    CONF_PV_INVERT,
    CONF_SCHEDULE_ENTITY,
    CONF_SCHEDULE_SOURCE,
    CONF_SOLAR_TEMP,
    CONF_TEMPERATURE_SENSORS,
    CONF_VALVES,
    CONF_WINDOWS,
    DEFAULT_ANTIFREEZE_C,
    DEFAULT_COMFORT_C,
    DEFAULT_ECO_C,
    SCHEDULE_EXTERNAL,
    SCHEDULE_INTERNAL,
    SCHEDULE_NONE,
    SUBENTRY_ZONE,
)
from .engine.models import HouseInputs, Mode, Tunables, ZoneInputs, ZoneSettings
from .engine.preheat import PreheatModel
from .engine.schedule import (
    MAX_BANDS,
    Band,
    Program,
    is_comfort_time,
    minutes_to_next_comfort,
)

_UNUSABLE = frozenset({STATE_UNAVAILABLE, STATE_UNKNOWN})
_ATTR_NEXT_EVENT = "next_event"

DEFAULT_ZONE_SETTINGS = ZoneSettings(
    mode=Mode.AUTO,
    comfort_c=DEFAULT_COMFORT_C,
    eco_c=DEFAULT_ECO_C,
    antifreeze_c=DEFAULT_ANTIFREEZE_C,
)
ZONE_VALUE_KEYS = ("comfort_c", "eco_c", "antifreeze_c")
_TUNABLE_DEFAULTS = {f.name: f.default for f in fields(Tunables)}


# --- configuration ---------------------------------------------------------


def _as_tuple(value: Any) -> tuple[str, ...]:
    """Normalise an entity selector value (None, str or list) to a tuple."""
    if not value:
        return ()
    if isinstance(value, str):
        return (value,)
    return tuple(str(item) for item in value if item)


def _parse_bands(raw: Any) -> tuple[Band, ...]:
    """Parse `[{"start": "HH:MM[:SS]", "end": ...}, ...]`; skip invalid bands."""
    bands: list[Band] = []
    for item in raw if isinstance(raw, list | tuple) else ():
        if not isinstance(item, Mapping):
            continue
        start = _parse_time(item.get("start"))
        end = _parse_time(item.get("end"))
        if start is not None and end is not None:
            bands.append(Band(start, end))
    return tuple(bands[:MAX_BANDS])


def _parse_time(value: Any) -> time | None:
    if isinstance(value, time):
        return value
    if isinstance(value, str):
        return dt_util.parse_time(value)
    return None


def parse_program(raw: Any) -> Program:
    """Build the internal Program from its JSON form."""
    if not isinstance(raw, Mapping):
        return Program()
    return Program(
        weekday=_parse_bands(raw.get("weekday")),
        weekend=_parse_bands(raw.get("weekend")),
    )


@dataclass(frozen=True)
class ZoneConfig:
    """Entities and schedule of a zone, read from its subentry."""

    zone_id: str
    name: str
    climates: tuple[str, ...] = ()
    climate_power: tuple[str, ...] = ()
    valves: tuple[str, ...] = ()
    temperature_sensors: tuple[str, ...] = ()
    windows: tuple[str, ...] = ()
    schedule_source: str = SCHEDULE_NONE
    schedule_entity: str | None = None
    program: Program = Program()

    @classmethod
    def from_subentry(cls, zone_id: str, data: Mapping[str, Any]) -> ZoneConfig:
        """Build a zone from the data of a `zone` subentry."""
        source = data.get(CONF_SCHEDULE_SOURCE) or SCHEDULE_NONE
        return cls(
            zone_id=zone_id,
            name=str(data.get(CONF_NAME) or zone_id),
            climates=_as_tuple(data.get(CONF_CLIMATES)),
            climate_power=_as_tuple(data.get(CONF_CLIMATE_POWER)),
            valves=_as_tuple(data.get(CONF_VALVES)),
            temperature_sensors=_as_tuple(data.get(CONF_TEMPERATURE_SENSORS)),
            windows=_as_tuple(data.get(CONF_WINDOWS)),
            schedule_source=source,
            schedule_entity=data.get(CONF_SCHEDULE_ENTITY) or None,
            program=parse_program(data.get(CONF_PROGRAM)),
        )

    @property
    def entity_ids(self) -> tuple[str, ...]:
        """Every entity whose state the zone reads."""
        ids = (
            *self.climates,
            *self.climate_power,
            *self.valves,
            *self.temperature_sensors,
            *self.windows,
        )
        if self.schedule_source == SCHEDULE_EXTERNAL and self.schedule_entity:
            ids = (*ids, self.schedule_entity)
        return ids


def zone_configs(entry: ConfigEntry) -> list[ZoneConfig]:
    """Return the zones of an entry; the zone id is the subentry id."""
    return [
        ZoneConfig.from_subentry(subentry_id, subentry.data)
        for subentry_id, subentry in entry.subentries.items()
        if subentry.subentry_type == SUBENTRY_ZONE
    ]


def watched_entity_ids(entry: ConfigEntry, zones: Iterable[ZoneConfig]) -> list[str]:
    """Return every configured entity, without duplicates."""
    data = entry.data
    ids: list[str] = [
        data[key]
        for key in (
            CONF_OUTDOOR_TEMP,
            CONF_SOLAR_TEMP,
            CONF_PV_EXPORT,
            CONF_PV_IMPORT,
            CONF_BATTERY_CHARGE,
            CONF_BATTERY_DISCHARGE,
            CONF_BATTERY_SOC,
            CONF_BOILER,
        )
        if data.get(key)
    ]
    ids.extend(_as_tuple(data.get(CONF_PRESENCE)))
    for zone in zones:
        ids.extend(zone.entity_ids)
    return list(dict.fromkeys(ids))


# --- user settings ---------------------------------------------------------


def coerce_tunable(name: str, value: Any) -> float | bool:
    """Return `value` converted to the type of tunable `name`."""
    if name not in _TUNABLE_DEFAULTS:
        raise ValueError(f"Unknown tunable: {name}")
    if isinstance(_TUNABLE_DEFAULTS[name], bool):
        return bool(value)
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"Invalid value for {name}: {value}")
    return number


def _zone_settings_from_dict(raw: Any) -> ZoneSettings:
    if not isinstance(raw, Mapping):
        return DEFAULT_ZONE_SETTINGS
    try:
        mode = Mode(raw.get("mode"))
    except ValueError:
        mode = DEFAULT_ZONE_SETTINGS.mode
    values = {
        key: _to_float(raw.get(key), getattr(DEFAULT_ZONE_SETTINGS, key))
        for key in ZONE_VALUE_KEYS
    }
    return ZoneSettings(mode=mode, **values)


@dataclass
class RuntimeSettings:
    """User settings and learned values, persisted by the coordinator."""

    enabled: bool = False
    zones: dict[str, ZoneSettings] = field(default_factory=dict)
    tunables: Tunables = field(default_factory=Tunables)
    minutes_per_c: dict[str, float] = field(default_factory=dict)

    def zone(self, zone_id: str) -> ZoneSettings:
        """Return the settings of a zone, defaults for a new zone."""
        return self.zones.get(zone_id, DEFAULT_ZONE_SETTINGS)

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable copy for the Store."""
        return {
            "enabled": self.enabled,
            "zones": {
                zone_id: {
                    "mode": s.mode.value,
                    "comfort_c": s.comfort_c,
                    "eco_c": s.eco_c,
                    "antifreeze_c": s.antifreeze_c,
                }
                for zone_id, s in self.zones.items()
            },
            "tunables": {
                f.name: getattr(self.tunables, f.name) for f in fields(Tunables)
            },
            "minutes_per_c": dict(self.minutes_per_c),
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any] | None) -> RuntimeSettings:
        """Rebuild the settings from the Store, ignoring invalid values."""
        raw = raw or {}
        zones_raw = raw.get("zones")
        zones = (
            {
                str(zone_id): _zone_settings_from_dict(value)
                for zone_id, value in zones_raw.items()
            }
            if isinstance(zones_raw, Mapping)
            else {}
        )
        tunables: dict[str, float | bool] = {}
        tun_raw = raw.get("tunables")
        for name, value in (tun_raw.items() if isinstance(tun_raw, Mapping) else ()):
            try:
                tunables[name] = coerce_tunable(name, value)
            except (TypeError, ValueError, OverflowError):
                continue
        learned_raw = raw.get("minutes_per_c")
        learned = {
            str(zone_id): number
            for zone_id, value in (
                learned_raw.items() if isinstance(learned_raw, Mapping) else ()
            )
            if (number := _to_float(value)) is not None
        }
        return cls(
            enabled=raw.get("enabled") is True,
            zones=zones,
            tunables=Tunables(**tunables),
            minutes_per_c=learned,
        )


# --- state readers ---------------------------------------------------------


def _to_float(value: Any, default: float | None = None) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return number if math.isfinite(number) else default


def _usable_state(hass: HomeAssistant, entity_id: str | None) -> State | None:
    """Return the state, or None if missing, unavailable or unknown."""
    if not entity_id:
        return None
    state = hass.states.get(entity_id)
    if state is None or state.state in _UNUSABLE:
        return None
    return state


def _float_state(hass: HomeAssistant, entity_id: str | None) -> float | None:
    state = _usable_state(hass, entity_id)
    return None if state is None else _to_float(state.state)


def _power_w(hass: HomeAssistant, entity_id: str | None) -> float | None:
    """Return a power state in W; None if unusable or not a power unit.

    A state without a unit is read as W.
    """
    state = _usable_state(hass, entity_id)
    if state is None or (value := _to_float(state.state)) is None:
        return None
    unit = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT)
    if not unit:
        return value
    if unit not in PowerConverter.VALID_UNITS:
        return None
    return PowerConverter.convert(value, unit, UnitOfPower.WATT)


def _net_power_w(
    hass: HomeAssistant,
    positive: str | None,
    negative: str | None,
    invert: bool,
) -> float | None:
    """Return a signed net power in W from one or two sensors.

    With `negative` set, both sensors are unsigned (a negative reading counts
    as 0), a missing `positive` counts as 0 W and `invert` is ignored.
    Otherwise `positive` alone is a signed sensor, its sign flipped by
    `invert`. None when no sensor is set or a set one is unusable.
    """
    if negative:
        plus = _power_w(hass, positive) if positive else 0.0
        minus = _power_w(hass, negative)
        if plus is None or minus is None:
            return None
        return max(0.0, plus) - max(0.0, minus)
    value = _power_w(hass, positive)
    if value is not None and invert:
        # Only the sign is flipped: the opposite flow must stay negative.
        value = -value
    return value


def _battery_level(hass: HomeAssistant, entity_id: str) -> float | None:
    """Return a battery level in %; None if unusable or not in %.

    A state without a unit is read as %.
    """
    state = _usable_state(hass, entity_id)
    if state is None or (value := _to_float(state.state)) is None:
        return None
    unit = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT)
    return value if not unit or unit == PERCENTAGE else None


def _battery_term_w(
    hass: HomeAssistant, data: Mapping[str, Any], tun: Tunables
) -> float:
    """Return the battery's contribution to the surplus, in W.

    Discharging always subtracts: power taken from the battery is never free,
    so a climate running on it must not count its own draw as surplus.
    Charging adds only when the battery counts: the setting is on and the
    level, if a level sensor is set, is usable and at least the minimum.
    0 when no battery power sensor is set or the power is unusable.
    """
    charge = data.get(CONF_BATTERY_CHARGE)
    discharge = data.get(CONF_BATTERY_DISCHARGE)
    if not (charge or discharge):
        return 0.0
    net = _net_power_w(hass, charge, discharge, bool(data.get(CONF_BATTERY_INVERT)))
    if net is None:
        return 0.0
    if net <= 0:
        return net
    if not tun.battery_surplus_enabled:
        return 0.0
    if soc_entity := data.get(CONF_BATTERY_SOC):
        level = _battery_level(hass, soc_entity)
        if level is None or level < tun.battery_soc_min_pct:
            return 0.0
    return net


def _grid_export_w(
    hass: HomeAssistant, data: Mapping[str, Any], tun: Tunables
) -> float | None:
    """Net power available for heating before the climates' own consumption.

    Grid export minus import, plus the battery term. None (no surplus at
    all) when the grid power is unknown, whatever the battery does.
    """
    grid = _net_power_w(
        hass,
        data.get(CONF_PV_EXPORT),
        data.get(CONF_PV_IMPORT),
        bool(data.get(CONF_PV_INVERT)),
    )
    if grid is None:
        return None
    return grid + _battery_term_w(hass, data, tun)


def _average(values: Iterable[float | None]) -> float | None:
    valid = [v for v in values if v is not None]
    return sum(valid) / len(valid) if valid else None


def _hvac_action(hass: HomeAssistant, entity_id: str) -> Any:
    state = _usable_state(hass, entity_id)
    return None if state is None else state.attributes.get(ATTR_HVAC_ACTION)


def _anyone_home(hass: HomeAssistant, persons: tuple[str, ...]) -> bool | None:
    """True if any person is home; None if unknown or not configured."""
    states = [s for p in persons if (s := _usable_state(hass, p)) is not None]
    if not states:
        return None
    return any(s.state == STATE_HOME for s in states)


def _zone_temperature(hass: HomeAssistant, zone: ZoneConfig) -> float | None:
    """Average of the zone sensors, else of the climates' current temperature.

    The valves' own temperature is never used: it is read on the radiator.
    """
    measured = _average(_float_state(hass, e) for e in zone.temperature_sensors)
    if measured is not None:
        return measured
    return _average(
        _to_float(state.attributes.get(ATTR_CURRENT_TEMPERATURE))
        for e in zone.climates
        if (state := _usable_state(hass, e)) is not None
    )


def _window_open_s(
    hass: HomeAssistant, windows: tuple[str, ...], now: datetime
) -> float | None:
    """Seconds since the longest-open window opened; None if all are closed."""
    open_for = [
        max((now - state.last_changed).total_seconds(), 0.0)
        for e in windows
        if (state := _usable_state(hass, e)) is not None and state.state == STATE_ON
    ]
    return max(open_for) if open_for else None


def _climate_heating(hass: HomeAssistant, entity_id: str) -> bool:
    """Return whether a climate counts as drawing its nominal power.

    It does when it reports `heating`, or when it reports no action at all
    (many air conditioners don't) and its mode is `heat`.
    """
    state = _usable_state(hass, entity_id)
    if state is None:
        return False
    action = state.attributes.get(ATTR_HVAC_ACTION)
    if action is None:
        return state.state == HVACMode.HEAT
    return action == HVACAction.HEATING


def _climate_power_w(hass: HomeAssistant, zone: ZoneConfig, tun: Tunables) -> float:
    """Power drawn by the zone's climates.

    The sum of the power sensors when they are all usable; otherwise (no
    sensor, or one unusable) the nominal power of each heating climate.
    """
    measured = [_power_w(hass, e) for e in zone.climate_power]
    if measured and all(value is not None for value in measured):
        return sum(value for value in measured if value is not None)
    heating = sum(1 for e in zone.climates if _climate_heating(hass, e))
    return heating * tun.climate_nominal_w


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, str):
        value = dt_util.parse_datetime(value)
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt_util.get_default_time_zone())
    return value


def _schedule(
    hass: HomeAssistant, zone: ZoneConfig, now: datetime
) -> tuple[bool, float | None]:
    """Return (schedule on, minutes to the next comfort start)."""
    if zone.schedule_source == SCHEDULE_INTERNAL:
        local = dt_util.as_local(now)
        return (
            is_comfort_time(zone.program, local),
            minutes_to_next_comfort(zone.program, local),
        )
    if zone.schedule_source != SCHEDULE_EXTERNAL:
        return False, None
    state = _usable_state(hass, zone.schedule_entity)
    if state is None:
        return False, None
    if state.state == STATE_ON:
        return True, None
    # While off, a `schedule` entity's next event is the next comfort start.
    # Calendars do not expose it, so preheat is not available with them.
    next_event = _parse_datetime(state.attributes.get(_ATTR_NEXT_EVENT))
    if next_event is None:
        return False, None
    minutes = (next_event - now).total_seconds() / 60
    return False, minutes if minutes > 0 else None


def _zone_inputs(
    hass: HomeAssistant, zone: ZoneConfig, settings: RuntimeSettings, now: datetime
) -> ZoneInputs:
    tun = settings.tunables
    zone_settings = settings.zone(zone.zone_id)
    temperature = _zone_temperature(hass, zone)
    schedule_on, minutes_to_comfort = _schedule(hass, zone, now)
    lead = 0.0
    if temperature is not None:
        model = PreheatModel(
            settings.minutes_per_c.get(zone.zone_id, tun.preheat_default_min_per_c),
            tun.preheat_max_min,
        )
        lead = model.lead_minutes(zone_settings.comfort_c, temperature)
    return ZoneInputs(
        zone_id=zone.zone_id,
        has_climate=bool(zone.climates),
        has_valves=bool(zone.valves),
        temperature_c=temperature,
        window_open_s=_window_open_s(hass, zone.windows, now),
        schedule_on=schedule_on,
        minutes_to_next_comfort=minutes_to_comfort,
        preheat_lead_min=lead,
        valves_calling_heat=any(
            _hvac_action(hass, e) == HVACAction.HEATING for e in zone.valves
        ),
        climate_power_w=_climate_power_w(hass, zone, tun),
        settings=zone_settings,
    )


def build_inputs(
    hass: HomeAssistant,
    entry: ConfigEntry,
    settings: RuntimeSettings,
    now: datetime,
) -> tuple[HouseInputs, list[ZoneInputs]]:
    """Read the current states into the engine inputs."""
    data = entry.data
    house = HouseInputs(
        enabled=settings.enabled,
        anyone_home=_anyone_home(hass, _as_tuple(data.get(CONF_PRESENCE))),
        outdoor_c=_float_state(hass, data.get(CONF_OUTDOOR_TEMP)),
        solar_c=_float_state(hass, data.get(CONF_SOLAR_TEMP)),
        grid_export_w=_grid_export_w(hass, data, settings.tunables),
        boiler_configured=bool(data.get(CONF_BOILER)),
    )
    zones = [_zone_inputs(hass, z, settings, now) for z in zone_configs(entry)]
    return house, zones
