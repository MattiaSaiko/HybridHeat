"""Engine controller: composes the pure engine modules into one evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .actuator import (
    ActuatorChoice,
    SourceState,
    ZoneCommands,
    choose_actuator,
    plan_commands,
)
from .boiler import (
    BoilerController,
    DeficitTracker,
    valves_need_heat,
    zone_calls_boiler,
)
from .models import Actuator, HouseInputs, Phase, Tunables, ZoneInputs
from .phase import resolve_phase
from .sources import active_source, pv_surplus_w, update_solar_active
from .target import resolve_target

# How much later the next comfort start may move before a preheat that has
# started is dropped (the schedule changed).
_PREHEAT_LATCH_TOLERANCE_MIN = 5.0


@dataclass(frozen=True)
class ZoneResult:
    """Everything decided for one zone in one evaluation."""

    target_c: float
    phase: Phase
    reason: str
    actuator: Actuator
    actuator_reason: str
    commands: ZoneCommands
    heat_request: bool
    # The zone's antifreeze setpoint: a valve switched off is left alone there.
    antifreeze_c: float | None = None
    temperature_c: float | None = None
    is_comfort: bool = False


@dataclass(frozen=True)
class EngineResult:
    """Everything decided for the house in one evaluation."""

    zones: dict[str, ZoneResult]
    boiler_on: bool | None
    active_source: str
    next_boiler_transition: datetime | None


class HybridHeatEngine:
    """Stateful engine: keeps the memory needed for hysteresis between cycles."""

    def __init__(
        self, tun: Tunables = Tunables(), boiler_initial_on: bool = False
    ) -> None:
        self._tun = tun
        self._boiler = BoilerController(tun, initial_on=boiler_initial_on)
        self._deficits = DeficitTracker(tun)
        self._solar_active = False
        self._phases: dict[str, Phase] = {}
        self._actuators: dict[str, Actuator] = {}
        self._climate_on: dict[str, bool] = {}
        # Zones whose preheat has started -> minutes to comfort last cycle.
        self._preheat_latch: dict[str, float] = {}

    def set_tunables(self, tun: Tunables) -> None:
        """Use new tunables from the next evaluation on, keeping all memory."""
        self._tun = tun
        self._boiler.set_tunables(tun)
        self._deficits.set_tunables(tun)

    def seed_boiler(self, is_on: bool) -> None:
        """Set the boiler relay's real state, once it is known."""
        self._boiler.seed(is_on)

    def evaluate(
        self, house: HouseInputs, zones: list[ZoneInputs], now: datetime
    ) -> EngineResult:
        """Evaluate the whole house and return the commands to apply."""
        tun = self._tun
        self._forget_removed(zones)
        if not house.enabled:
            return self._evaluate_disabled(house, zones)

        pv = pv_surplus_w(house.grid_export_w, sum(z.climate_power_w for z in zones))
        self._solar_active = update_solar_active(
            self._solar_active, house.solar_c, tun
        )
        src = SourceState(house.outdoor_c, self._solar_active, house.solar_c, pv)

        results: dict[str, ZoneResult] = {}
        boiler_demand = False
        solar_effective_any = False
        pv_used_any = False

        for zone in zones:
            zid = zone.zone_id
            target = resolve_target(
                zone, house, tun, preheat_latched=self._preheat_latched(zone)
            )
            if target.reason == "preheat":
                assert zone.minutes_to_next_comfort is not None
                self._preheat_latch[zid] = zone.minutes_to_next_comfort
            else:
                self._preheat_latch.pop(zid, None)
            phase = resolve_phase(target, zone, self._phases.get(zid), tun)
            choice = choose_actuator(
                zone, phase, src, self._actuators.get(zid), tun
            )
            commands = plan_commands(
                zone,
                target.target_c,
                choice,
                self._climate_on.get(zid, False),
                tun,
            )
            self._phases[zid] = phase
            self._actuators[zid] = choice.actuator
            self._climate_on[zid] = commands.climate_on

            # A climate switched on heats, also as frost protection of a
            # zone without valves.
            heat_request = (
                not commands.devices_off
                and (valves_need_heat(zone, commands, tun) or commands.climate_on)
            )
            results[zid] = ZoneResult(
                target_c=target.target_c,
                phase=phase,
                reason=target.reason,
                actuator=choice.actuator,
                actuator_reason=choice.reason,
                commands=commands,
                heat_request=heat_request,
                antifreeze_c=zone.settings.antifreeze_c,
                temperature_c=zone.temperature_c,
                is_comfort=target.is_comfort,
            )

            deficit_active = self._update_deficit(
                zone, target.target_c, choice, now
            )
            if not commands.devices_off and zone_calls_boiler(
                zone, choice, commands, deficit_active, tun
            ):
                boiler_demand = True
            solar_effective_any |= choice.reason == "solar_thermal"
            pv_used_any |= choice.reason == "pv_surplus"

        boiler_on: bool | None = None
        next_transition: datetime | None = None
        if house.boiler_configured:
            boiler_on = self._boiler.decide(boiler_demand, now)
            next_transition = self._boiler.next_transition_at(now)

        return EngineResult(
            zones=results,
            boiler_on=boiler_on,
            active_source=active_source(solar_effective_any, pv_used_any),
            next_boiler_transition=next_transition,
        )

    def _evaluate_disabled(
        self, house: HouseInputs, zones: list[ZoneInputs]
    ) -> EngineResult:
        """Return the result of a disabled house: it commands nothing.

        Disabled means hands off: no valve, climate or boiler command, not
        even frost protection. The zones still report their state, and the
        engine forgets what it remembered so that enabling it again starts
        from a clean state.
        """
        results: dict[str, ZoneResult] = {}
        for zone in zones:
            zid = zone.zone_id
            target = resolve_target(zone, house, self._tun)
            self._phases[zid] = Phase.OFF
            self._actuators.pop(zid, None)
            self._climate_on.pop(zid, None)
            self._preheat_latch.pop(zid, None)
            self._deficits.forget(zid)
            results[zid] = ZoneResult(
                target_c=target.target_c,
                phase=Phase.OFF,
                reason=target.reason,
                actuator=Actuator.NONE,
                actuator_reason="zone_off",
                commands=ZoneCommands(None, False, None),
                heat_request=False,
                antifreeze_c=zone.settings.antifreeze_c,
                temperature_c=zone.temperature_c,
                is_comfort=target.is_comfort,
            )
        self._solar_active = update_solar_active(
            self._solar_active, house.solar_c, self._tun
        )
        return EngineResult(
            zones=results,
            boiler_on=False if house.boiler_configured else None,
            active_source=active_source(False, False),
            next_boiler_transition=None,
        )

    def _preheat_latched(self, zone: ZoneInputs) -> bool:
        """Return whether a started preheat still holds for this cycle.

        It holds while the next comfort start stays where it was: a jump
        later by more than the tolerance means the schedule changed. Every
        other condition (Auto mode, house occupied, window closed, enabled,
        schedule off) is checked by `resolve_target` before the preheat rule.
        """
        previous = self._preheat_latch.get(zone.zone_id)
        minutes = zone.minutes_to_next_comfort
        return (
            previous is not None
            and minutes is not None
            and minutes <= previous + _PREHEAT_LATCH_TOLERANCE_MIN
        )

    def _update_deficit(
        self,
        zone: ZoneInputs,
        target_c: float,
        choice: ActuatorChoice,
        now: datetime,
    ) -> bool:
        """Track the deficit of a zone while solar serves it; return if active."""
        if zone.temperature_c is None or choice.reason != "solar_thermal":
            self._deficits.forget(zone.zone_id)
            return False
        return self._deficits.update(zone.zone_id, target_c - zone.temperature_c, now)

    def _forget_removed(self, zones: list[ZoneInputs]) -> None:
        """Drop the memory of zones that no longer appear in the input."""
        current = {z.zone_id for z in zones}
        for zid in set(self._phases) - current:
            self._phases.pop(zid, None)
            self._actuators.pop(zid, None)
            self._climate_on.pop(zid, None)
            self._preheat_latch.pop(zid, None)
            self._deficits.forget(zid)
