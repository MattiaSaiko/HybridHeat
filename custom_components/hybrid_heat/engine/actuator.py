"""Actuator selection and command planning for a zone."""

from __future__ import annotations

import math
from dataclasses import dataclass

from .models import Actuator, Phase, Tunables, ZoneInputs
from .sources import solar_effective


@dataclass(frozen=True)
class SourceState:
    """House-wide source state seen by every zone in one cycle."""

    outdoor_c: float | None
    solar_active: bool
    solar_c: float | None
    pv_surplus_w: float


@dataclass(frozen=True)
class ActuatorChoice:
    """Chosen actuator and the rule that chose it."""

    actuator: Actuator
    reason: str


@dataclass(frozen=True)
class ZoneCommands:
    """Commands to send to the devices of a zone."""

    valve_setpoint_c: float | None
    climate_on: bool
    climate_setpoint_c: float | None
    # The zone is off: switch its valves and climates off, and keep them off.
    devices_off: bool = False


def choose_actuator(
    zone: ZoneInputs,
    phase: Phase,
    src: SourceState,
    prev: Actuator | None,
    tun: Tunables,
) -> ActuatorChoice:
    """Choose the actuator of a zone, following the rule order of spec section 5.

    Whenever the valves are chosen while solar thermal is effective for the
    phase, the reason is "solar_thermal", whichever rule picked the valves.
    """
    if phase == Phase.OFF:
        return ActuatorChoice(Actuator.NONE, "zone_off")
    if phase == Phase.ANTIFREEZE or phase == Phase.WINDOW_OPEN:
        return ActuatorChoice(Actuator.NONE, "phase_idle")
    solar_ok = solar_effective(
        src.solar_active,
        src.solar_c,
        phase,
        tun,
        hold=prev == Actuator.VALVES,
    )

    def valves(reason: str) -> ActuatorChoice:
        return ActuatorChoice(Actuator.VALVES, "solar_thermal" if solar_ok else reason)

    if zone.temperature_c is None:
        if zone.has_valves:
            return valves("no_temperature")
        return ActuatorChoice(Actuator.NONE, "no_temperature")
    if not zone.has_climate:
        return valves("only_valves")
    if not zone.has_valves:
        return ActuatorChoice(Actuator.CLIMATE, "only_climate")
    min_outdoor_c = tun.min_outdoor_c
    if prev == Actuator.CLIMATE:
        min_outdoor_c -= tun.outdoor_hyst_c
    if src.outdoor_c is not None and src.outdoor_c < min_outdoor_c:
        return valves("outdoor_too_cold")
    if solar_ok:
        return valves("solar_thermal")
    threshold = tun.pv_threshold_w
    if prev == Actuator.CLIMATE:
        threshold *= tun.pv_hold_ratio
    if src.pv_surplus_w >= threshold:
        return ActuatorChoice(Actuator.CLIMATE, "pv_surplus")
    if phase == Phase.PREHEATING:
        return ActuatorChoice(Actuator.CLIMATE, "base_preheat_climate")
    return ActuatorChoice(Actuator.VALVES, "base_maintenance_valves")


def _round_half(value: float) -> float:
    """Round to the nearest 0.5, halves going up."""
    return math.floor(value * 2 + 0.5) / 2


def _climate_wanted(
    temperature_c: float | None,
    target_c: float,
    was_on: bool,
    tun: Tunables,
) -> bool:
    """Return whether the climate should run, with hysteresis."""
    if temperature_c is None:
        return was_on
    if was_on:
        return temperature_c <= target_c + tun.climate_hyst_c
    return temperature_c < target_c - tun.climate_hyst_c


def plan_commands(
    zone: ZoneInputs,
    target_c: float,
    choice: ActuatorChoice,
    climate_was_on: bool,
    tun: Tunables,
) -> ZoneCommands:
    """Return the valve and climate commands for a zone."""
    valve_setpoint: float | None = None
    climate_on = False
    climate_setpoint: float | None = None

    if choice.reason == "zone_off":
        return ZoneCommands(None, False, None, devices_off=True)
    if choice.actuator == Actuator.CLIMATE:
        if zone.has_valves:
            # The safety net never goes below the zone's antifreeze setpoint.
            valve_setpoint = max(
                target_c - tun.valve_safety_offset_c, zone.settings.antifreeze_c
            )
        if zone.has_climate:
            climate_on = _climate_wanted(
                zone.temperature_c, target_c, climate_was_on, tun
            )
            climate_setpoint = _round_half(target_c)
    elif choice.actuator == Actuator.VALVES:
        if zone.has_valves:
            valve_setpoint = target_c
    elif zone.has_valves:
        valve_setpoint = zone.settings.antifreeze_c
    elif zone.has_climate:
        # No valves to keep the antifreeze: the climate does it instead.
        antifreeze_c = zone.settings.antifreeze_c
        climate_on = _climate_wanted(
            zone.temperature_c, antifreeze_c, climate_was_on, tun
        )
        climate_setpoint = _round_half(antifreeze_c)

    return ZoneCommands(valve_setpoint, climate_on, climate_setpoint)
