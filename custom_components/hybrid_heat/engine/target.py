"""Target temperature resolution: the first matching rule wins."""

from __future__ import annotations

from dataclasses import dataclass

from .models import HouseInputs, Mode, Tunables, ZoneInputs


@dataclass(frozen=True)
class TargetDecision:
    """Target temperature of a zone and why it was chosen."""

    target_c: float
    reason: str
    is_comfort: bool


def resolve_target(
    zone: ZoneInputs,
    house: HouseInputs,
    tun: Tunables,
    preheat_latched: bool = False,
) -> TargetDecision:
    """Return the target temperature of a zone.

    `preheat_latched` keeps a preheat that has started until the comfort
    period begins, even once the room is warm enough for the lead to drop
    below the minutes left.
    """
    s = zone.settings
    if not house.enabled:
        return TargetDecision(s.antifreeze_c, "disabled", False)
    if s.mode is Mode.OFF:
        # The zone's devices are switched off; the antifreeze value is only
        # what the zone reports as its target.
        return TargetDecision(s.antifreeze_c, "mode_off", False)
    if s.mode is Mode.ANTIFREEZE:
        return TargetDecision(s.antifreeze_c, "mode_antifreeze", False)
    if zone.window_open_s is not None and zone.window_open_s > tun.window_delay_s:
        return TargetDecision(s.antifreeze_c, "window_open", False)
    if s.mode is Mode.COMFORT:
        return TargetDecision(s.comfort_c, "mode_comfort", True)
    if s.mode is Mode.ECO:
        return TargetDecision(s.eco_c, "mode_eco", False)
    # From here on the mode is AUTO.
    if house.anyone_home is False:
        return TargetDecision(s.eco_c, "house_empty", False)
    if zone.schedule_on:
        return TargetDecision(s.comfort_c, "schedule", True)
    if zone.minutes_to_next_comfort is not None and (
        preheat_latched
        or (
            zone.preheat_lead_min > 0
            and zone.minutes_to_next_comfort <= zone.preheat_lead_min
        )
    ):
        return TargetDecision(s.comfort_c, "preheat", True)
    return TargetDecision(s.eco_c, "default_eco", False)
