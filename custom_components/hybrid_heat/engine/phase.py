"""Phase resolution: which stage of the heating cycle a zone is in."""

from __future__ import annotations

from .models import Phase, Tunables, ZoneInputs
from .target import TargetDecision

_OFF_REASONS = frozenset({"disabled", "mode_off"})


def resolve_phase(
    target: TargetDecision,
    zone: ZoneInputs,
    prev: Phase | None,
    tun: Tunables,
) -> Phase:
    """Return the phase of a zone, with hysteresis between preheating and maintenance."""
    if target.reason in _OFF_REASONS:
        return Phase.OFF
    if target.reason == "mode_antifreeze":
        return Phase.ANTIFREEZE
    if target.reason == "window_open":
        return Phase.WINDOW_OPEN
    if not target.is_comfort:
        return Phase.ECO
    if zone.temperature_c is None:
        return Phase.MAINTENANCE
    gap = target.target_c - zone.temperature_c
    threshold = tun.preheat_exit_c if prev == Phase.PREHEATING else tun.preheat_enter_c
    return Phase.PREHEATING if gap > threshold else Phase.MAINTENANCE
