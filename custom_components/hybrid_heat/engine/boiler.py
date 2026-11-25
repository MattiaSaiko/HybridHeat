"""Boiler controller: call rules, delays, minimum times and deficit override."""

from __future__ import annotations

from datetime import datetime, timedelta

from .actuator import ActuatorChoice, ZoneCommands
from .models import Tunables, ZoneInputs


class BoilerController:
    """Decide the boiler relay state from a demand signal, with timing guards."""

    def __init__(self, tun: Tunables, initial_on: bool = False) -> None:
        self._tun = tun
        self._on = initial_on
        self._last_change: datetime | None = None
        self._pending_since: datetime | None = None

    def seed(self, is_on: bool) -> None:
        """Set the relay state the controller starts from.

        For a relay whose real state was unknown when the controller was
        created; the timing guards apply from here as after `initial_on`.
        """
        self._on = is_on

    def set_tunables(self, tun: Tunables) -> None:
        """Use new tunables from the next decision on, keeping all timing."""
        self._tun = tun

    def _clamp(self, now: datetime) -> None:
        """Pull stored timestamps back to `now` if the clock went backwards."""
        if self._pending_since is not None and self._pending_since > now:
            self._pending_since = now
        if self._last_change is not None and self._last_change > now:
            self._last_change = now

    def decide(self, demand: bool, now: datetime) -> bool:
        """Return the commanded boiler state after delays and minimum times."""
        self._clamp(now)
        if demand == self._on:
            # The demand agrees with the current state: nothing is pending.
            self._pending_since = None
            return self._on
        if self._pending_since is None:
            self._pending_since = now
        if self._allowed_at(demand) <= now:
            self._on = demand
            self._last_change = now
            self._pending_since = None
        return self._on

    def _allowed_at(self, demand: bool) -> datetime:
        """Return when a pending switch to `demand` is allowed."""
        assert self._pending_since is not None
        delay_s = (
            self._tun.boiler_on_delay_s if demand else self._tun.boiler_off_delay_s
        )
        min_s = self._tun.boiler_min_off_s if demand else self._tun.boiler_min_on_s
        allowed = self._pending_since + timedelta(seconds=delay_s)
        if self._last_change is not None:
            allowed = max(allowed, self._last_change + timedelta(seconds=min_s))
        return allowed

    def next_transition_at(self, now: datetime) -> datetime | None:
        """Return when the pending switch becomes allowed, None if none pends."""
        self._clamp(now)
        if self._pending_since is None:
            return None
        return self._allowed_at(not self._on)


class DeficitTracker:
    """Detect zones that stayed too far below target for too long."""

    def __init__(self, tun: Tunables) -> None:
        self._tun = tun
        self._since: dict[str, datetime] = {}

    def set_tunables(self, tun: Tunables) -> None:
        """Use new tunables from the next update on, keeping the timers."""
        self._tun = tun

    def update(self, zone_id: str, deficit_c: float, now: datetime) -> bool:
        """Return True once the deficit has lasted `deficit_min` minutes."""
        if deficit_c < self._tun.deficit_c:
            self._since.pop(zone_id, None)
            return False
        since = self._since.setdefault(zone_id, now)
        return (now - since).total_seconds() >= self._tun.deficit_min * 60

    def forget(self, zone_id: str) -> None:
        """Drop the tracking state of a zone."""
        self._since.pop(zone_id, None)


def valves_need_heat(
    zone: ZoneInputs,
    commands: ZoneCommands,
    tun: Tunables,
) -> bool:
    """Return whether the valves of a zone ask for heat, whatever the actuator.

    This covers frost protection (valves at antifreeze) and the safety net
    of a zone heated by the climate.
    """
    if not zone.has_valves:
        return False
    if zone.valves_calling_heat:
        return True
    return (
        zone.temperature_c is not None
        and commands.valve_setpoint_c is not None
        and zone.temperature_c < commands.valve_setpoint_c - tun.boiler_call_margin_c
    )


def zone_calls_boiler(
    zone: ZoneInputs,
    choice: ActuatorChoice,
    commands: ZoneCommands,
    deficit_active: bool,
    tun: Tunables,
) -> bool:
    """Return whether a zone asks the boiler to run."""
    if not valves_need_heat(zone, commands, tun):
        return False
    return choice.reason != "solar_thermal" or (
        deficit_active and not tun.solar_never_boiler
    )
