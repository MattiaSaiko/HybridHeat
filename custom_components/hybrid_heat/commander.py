"""Turn the engine commands into Home Assistant service calls.

Commands are sent only when they change something, so Zigbee valves and
climates are not flooded every cycle. Setpoints are rounded to each device's
own step, and a command the device does not reflect is not repeated until
the device's state changes or 10 minutes have passed. Missing, `unavailable`
or `unknown` entities are skipped.

The calls are first planned for every zone and the boiler, then sent one by
one. Each call has its own timeout and its own error handling, so a device
that fails or hangs never stops the commands to the other zones or to the
boiler.
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from collections.abc import Callable
from typing import Any

from homeassistant.components.climate import (
    ATTR_HVAC_MODE,
    ATTR_MAX_TEMP,
    ATTR_MIN_TEMP,
    ATTR_TARGET_TEMP_STEP,
    SERVICE_SET_HVAC_MODE,
    SERVICE_SET_TEMPERATURE,
    HVACMode,
)
from homeassistant.components.climate import DOMAIN as CLIMATE_DOMAIN
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_TEMPERATURE,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import HomeAssistant, State

from .engine.actuator import ZoneCommands
from .engine.controller import EngineResult, ZoneResult
from .engine.models import Tunables
from .inputs import ZoneConfig

_LOGGER = logging.getLogger(__name__)

# Upper bound for one service call; a hung device must not stall the cycle.
SERVICE_TIMEOUT_S = 30.0

_HA_DOMAIN = "homeassistant"
_UNUSABLE = frozenset({STATE_UNAVAILABLE, STATE_UNKNOWN})
_SAME_SETPOINT_C = 0.01
_DEFAULT_STEP_C = 0.5
# An identical command the device did not reflect is repeated after this.
REPEAT_AFTER_S = 600.0

type ServiceCallSpec = tuple[str, str, dict[str, Any]]
type _CallKey = tuple[str, str]


class CommandMemory:
    """What the commander sent and warned about, kept between cycles."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        # (entity, service) -> (data sent, observed state then, when).
        self._sent: dict[_CallKey, tuple[dict[str, Any], tuple[Any, ...], float]] = {}
        self._failing: set[_CallKey] = set()
        self._valves_off_warned: set[str] = set()
        self._relay_warned = False

    def recently_sent(self, hass: HomeAssistant, spec: ServiceCallSpec) -> bool:
        """Return whether this exact climate command was sent and not reflected.

        True while the entity's observed state has not changed since and
        less than `REPEAT_AFTER_S` has passed.
        """
        domain, service, data = spec
        if domain != CLIMATE_DOMAIN:
            return False
        record = self._sent.get((data[ATTR_ENTITY_ID], service))
        if record is None:
            return False
        sent_data, observed, at = record
        return (
            sent_data == data
            and observed == _observed(hass, data[ATTR_ENTITY_ID])
            and self._clock() - at < REPEAT_AFTER_S
        )

    def record_sent(self, spec: ServiceCallSpec, observed: tuple[Any, ...]) -> None:
        domain, service, data = spec
        if domain == CLIMATE_DOMAIN:
            self._sent[(data[ATTR_ENTITY_ID], service)] = (
                dict(data),
                observed,
                self._clock(),
            )

    def call_failed(self, spec: ServiceCallSpec) -> bool:
        """Record a failure; return True if it is the first since a success."""
        _, service, data = spec
        key = (str(data.get(ATTR_ENTITY_ID)), service)
        first = key not in self._failing
        self._failing.add(key)
        return first

    def call_succeeded(self, spec: ServiceCallSpec) -> None:
        _, service, data = spec
        self._failing.discard((str(data.get(ATTR_ENTITY_ID)), service))

    def warn_valve_off(self, entity_id: str) -> None:
        """Warn once that a valve is switched from off to heat."""
        if entity_id in self._valves_off_warned:
            return
        self._valves_off_warned.add(entity_id)
        _LOGGER.warning(
            "Valve %s is in HVAC mode off: switching it to heat so it can "
            "reach its setpoint",
            entity_id,
        )

    def valve_not_off(self, entity_id: str) -> None:
        self._valves_off_warned.discard(entity_id)

    def relay_unavailable(self, entity_id: str, needed: bool) -> None:
        """Warn once that the boiler relay can't be switched on while needed."""
        if not needed:
            return
        if self._relay_warned:
            _LOGGER.debug("Boiler relay %s still unavailable", entity_id)
            return
        self._relay_warned = True
        _LOGGER.warning(
            "Boiler relay %s is unavailable while heat is needed: the boiler "
            "cannot be switched on",
            entity_id,
        )

    def relay_available(self) -> None:
        self._relay_warned = False


def _observed(hass: HomeAssistant, entity_id: str) -> tuple[Any, ...]:
    """The state of a climate that a command can change: mode and setpoint."""
    state = hass.states.get(entity_id)
    if state is None:
        return (None, None)
    return (state.state, state.attributes.get(ATTR_TEMPERATURE))


def _state(hass: HomeAssistant, entity_id: str) -> State | None:
    state = hass.states.get(entity_id)
    if state is None or state.state in _UNUSABLE:
        _LOGGER.debug("Skipping %s: not available", entity_id)
        return None
    return state


def _attr_float(state: State, attr: str) -> float | None:
    try:
        value = float(state.attributes.get(attr))
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _within_limits(state: State, setpoint: float) -> float:
    """Clamp to the entity's own min/max so the call is not rejected."""
    low = _attr_float(state, ATTR_MIN_TEMP)
    high = _attr_float(state, ATTR_MAX_TEMP)
    if low is not None:
        setpoint = max(setpoint, low)
    if high is not None:
        setpoint = min(setpoint, high)
    return setpoint


def _round_to_step(state: State, value: float) -> float:
    """Round to the entity's own setpoint step (0.5 by default), halves up."""
    step = _attr_float(state, ATTR_TARGET_TEMP_STEP)
    if step is None or step <= 0:
        step = _DEFAULT_STEP_C
    return round(math.floor(value / step + 0.5) * step, 3)


def _device_setpoint(state: State, value: float) -> float:
    """Return the setpoint the device can take: its step, then its limits."""
    return _within_limits(state, _round_to_step(state, value))


def _set_temperature(entity_id: str, setpoint: float) -> ServiceCallSpec:
    return (
        CLIMATE_DOMAIN,
        SERVICE_SET_TEMPERATURE,
        {ATTR_ENTITY_ID: entity_id, ATTR_TEMPERATURE: setpoint},
    )


def _set_hvac_mode(entity_id: str, mode: HVACMode) -> ServiceCallSpec:
    return (
        CLIMATE_DOMAIN,
        SERVICE_SET_HVAC_MODE,
        {ATTR_ENTITY_ID: entity_id, ATTR_HVAC_MODE: mode},
    )


def _valve_calls(
    hass: HomeAssistant,
    entity_id: str,
    setpoint: float,
    deadband_c: float,
    is_antifreeze: bool,
    memory: CommandMemory,
) -> list[ServiceCallSpec]:
    state = _state(hass, entity_id)
    if state is None:
        return []
    calls: list[ServiceCallSpec] = []
    if state.state == HVACMode.OFF:
        # A valve switched off does not heat. Leave it alone at antifreeze;
        # otherwise switch it to heat first.
        if is_antifreeze:
            return []
        memory.warn_valve_off(entity_id)
        calls.append(_set_hvac_mode(entity_id, HVACMode.HEAT))
    else:
        memory.valve_not_off(entity_id)
    setpoint = _device_setpoint(state, setpoint)
    current = _attr_float(state, ATTR_TEMPERATURE)
    if current is None or abs(current - setpoint) > deadband_c:
        calls.append(_set_temperature(entity_id, setpoint))
    return calls


def _climate_calls(
    hass: HomeAssistant, entity_id: str, commands: ZoneCommands
) -> list[ServiceCallSpec]:
    state = _state(hass, entity_id)
    if state is None:
        return []
    if not commands.climate_on:
        # Only the mode: some integrations power the unit on when they
        # receive a temperature, so no set_temperature is ever sent here.
        # Only `heat` (the one mode set here) is switched off: a unit
        # cooling or in any other mode belongs to someone else.
        if state.state == HVACMode.HEAT:
            return [_set_hvac_mode(entity_id, HVACMode.OFF)]
        return []
    calls: list[ServiceCallSpec] = []
    if state.state != HVACMode.HEAT:
        calls.append(_set_hvac_mode(entity_id, HVACMode.HEAT))
    if commands.climate_setpoint_c is not None:
        setpoint = _device_setpoint(state, commands.climate_setpoint_c)
        current = _attr_float(state, ATTR_TEMPERATURE)
        if current is None or abs(current - setpoint) >= _SAME_SETPOINT_C:
            calls.append(_set_temperature(entity_id, setpoint))
    return calls


def _zone_off_calls(hass: HomeAssistant, zone: ZoneConfig) -> list[ServiceCallSpec]:
    """Return the calls that switch the devices of a zone off.

    Valves are switched off whatever their mode; a climate only when it
    heats (a unit cooling or in another mode belongs to someone else).
    Unavailable entities are skipped.
    """
    calls: list[ServiceCallSpec] = []
    for entity_id in zone.valves:
        state = _state(hass, entity_id)
        if state is not None and state.state != HVACMode.OFF:
            calls.append(_set_hvac_mode(entity_id, HVACMode.OFF))
    for entity_id in zone.climates:
        state = _state(hass, entity_id)
        if state is not None and state.state == HVACMode.HEAT:
            calls.append(_set_hvac_mode(entity_id, HVACMode.OFF))
    return calls


def _zone_calls(
    hass: HomeAssistant,
    zone: ZoneConfig,
    zone_result: ZoneResult,
    deadband_c: float,
    memory: CommandMemory,
) -> list[ServiceCallSpec]:
    commands = zone_result.commands
    if commands.devices_off:
        return _zone_off_calls(hass, zone)
    calls: list[ServiceCallSpec] = []
    if (setpoint := commands.valve_setpoint_c) is not None:
        antifreeze = zone_result.antifreeze_c
        is_antifreeze = (
            antifreeze is not None and abs(setpoint - antifreeze) < _SAME_SETPOINT_C
        )
        for entity_id in zone.valves:
            calls += _valve_calls(
                hass, entity_id, setpoint, deadband_c, is_antifreeze, memory
            )
    for entity_id in zone.climates:
        calls += _climate_calls(hass, entity_id, commands)
    return calls


def _boiler_calls(
    hass: HomeAssistant, entity_id: str, on: bool, memory: CommandMemory
) -> list[ServiceCallSpec]:
    state = _state(hass, entity_id)
    if state is None:
        memory.relay_unavailable(entity_id, needed=on)
        return []
    memory.relay_available()
    if (state.state == STATE_ON) == on:
        return []
    service = SERVICE_TURN_ON if on else SERVICE_TURN_OFF
    return [(_HA_DOMAIN, service, {ATTR_ENTITY_ID: entity_id})]


def plan_calls(
    hass: HomeAssistant,
    zones: list[ZoneConfig],
    result: EngineResult,
    boiler_entity: str | None = None,
    tun: Tunables | None = None,
    memory: CommandMemory | None = None,
) -> list[ServiceCallSpec]:
    """Return the service calls needed to apply `result`, zones first."""
    deadband_c = (tun or Tunables()).valve_deadband_c
    memory = memory or CommandMemory()
    calls: list[ServiceCallSpec] = []
    for zone in zones:
        zone_result = result.zones.get(zone.zone_id)
        if zone_result is None:
            continue
        try:
            calls += _zone_calls(hass, zone, zone_result, deadband_c, memory)
        except Exception:
            _LOGGER.warning(
                "Could not plan the commands of zone %s", zone.name, exc_info=True
            )
    if boiler_entity and result.boiler_on is not None:
        try:
            calls += _boiler_calls(hass, boiler_entity, result.boiler_on, memory)
        except Exception:
            _LOGGER.warning("Could not plan the boiler command", exc_info=True)
    return calls


async def _call(
    hass: HomeAssistant, spec: ServiceCallSpec, memory: CommandMemory
) -> bool:
    """Send one call; any failure or timeout is logged, never raised.

    The first failure of an (entity, service) is a warning; repeats are
    logged at debug level until the call succeeds again. `Exception`
    excludes `CancelledError`, so cancellation still propagates.
    """
    domain, service, data = spec
    try:
        async with asyncio.timeout(SERVICE_TIMEOUT_S):
            await hass.services.async_call(domain, service, data, blocking=True)
    except Exception:
        if memory.call_failed(spec):
            _LOGGER.warning(
                "%s.%s failed for %s (repeats are logged at debug level until "
                "it succeeds)",
                domain,
                service,
                data,
                exc_info=True,
            )
        else:
            _LOGGER.debug(
                "%s.%s failed again for %s", domain, service, data, exc_info=True
            )
        return False
    memory.call_succeeded(spec)
    return True


async def async_apply_commands(
    hass: HomeAssistant,
    zones: list[ZoneConfig],
    result: EngineResult,
    boiler_entity: str | None = None,
    tun: Tunables | None = None,
    *,
    stopped: Callable[[], bool] | None = None,
    memory: CommandMemory | None = None,
) -> None:
    """Send the commands of `result` to the valves, climates and boiler.

    `stopped` is checked before every call: once it returns True (the
    integration is being unloaded) nothing more is sent. `memory` keeps
    what was sent and logged between cycles; without it every call starts
    from scratch.
    """
    memory = memory or CommandMemory()
    for spec in plan_calls(hass, zones, result, boiler_entity, tun, memory):
        if stopped is not None and stopped():
            return
        if memory.recently_sent(hass, spec):
            _LOGGER.debug("Not repeating %s.%s for %s", *spec)
            continue
        observed = _observed(hass, spec[2][ATTR_ENTITY_ID])
        if await _call(hass, spec, memory):
            memory.record_sent(spec, observed)


def _all_off_calls(
    hass: HomeAssistant, zones: list[ZoneConfig], boiler_entity: str | None
) -> list[ServiceCallSpec]:
    """Return the calls that switch every heating device and the boiler off."""
    calls: list[ServiceCallSpec] = []
    for zone in zones:
        calls += _zone_off_calls(hass, zone)
    if boiler_entity:
        state = _state(hass, boiler_entity)
        if state is not None and state.state == STATE_ON:
            calls.append(
                (_HA_DOMAIN, SERVICE_TURN_OFF, {ATTR_ENTITY_ID: boiler_entity})
            )
    return calls


async def async_apply_all_off(
    hass: HomeAssistant,
    zones: list[ZoneConfig],
    boiler_entity: str | None = None,
    *,
    memory: CommandMemory | None = None,
) -> None:
    """Switch every valve, climate and the boiler off, once.

    Sent when the integration is switched off, so the user takes over from a
    known state. It is never repeated: a device that fails is only logged.
    """
    memory = memory or CommandMemory()
    for spec in _all_off_calls(hass, zones, boiler_entity):
        await _call(hass, spec, memory)
