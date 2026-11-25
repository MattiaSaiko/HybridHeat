"""Coordinator: runs the engine, applies its commands, keeps user settings."""

from __future__ import annotations

import asyncio
import logging
import math
from dataclasses import replace
from datetime import datetime, timedelta
from functools import partial
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import (
    CALLBACK_TYPE,
    Event,
    EventStateChangedData,
    HomeAssistant,
    State,
    callback,
)
from homeassistant.helpers.event import (
    async_track_point_in_utc_time,
    async_track_state_change_event,
)
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .commander import CommandMemory, async_apply_all_off, async_apply_commands
from .const import (
    CONF_BOILER,
    DOMAIN,
    MIN_PER_C_MAX,
    MIN_PER_C_MIN,
    STORAGE_KEY_PREFIX,
    STORAGE_VERSION,
    UPDATE_INTERVAL,
)
from .engine.controller import EngineResult, HybridHeatEngine
from .engine.models import Mode, Phase, ZoneInputs
from .engine.preheat import PreheatModel
from .inputs import (
    ZONE_VALUE_KEYS,
    RuntimeSettings,
    build_inputs,
    coerce_tunable,
    watched_entity_ids,
    zone_configs,
)

_LOGGER = logging.getLogger(__name__)

_BOILER_TIMER = "boiler"
_WINDOW_TIMER = "window"


class HybridHeatCoordinator(DataUpdateCoordinator[EngineResult]):
    """Evaluate the house every 10 minutes and on every relevant state change."""

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
        )
        self.zones = zone_configs(entry)
        self.settings = RuntimeSettings()
        self._boiler_entity: str | None = entry.data.get(CONF_BOILER) or None
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{STORAGE_KEY_PREFIX}.{entry.entry_id}"
        )
        self._engine: HybridHeatEngine | None = None
        # False until the engine knows the boiler relay's real state.
        self._boiler_seeded = True
        self._unsubs: list[CALLBACK_TYPE] = []
        self._timers: dict[str, CALLBACK_TYPE] = {}
        self._last_phase: dict[str, Phase] = {}
        self._preheat_start: dict[str, tuple[datetime, float]] = {}
        self._commands = CommandMemory()
        # Whether the last cycle ran enabled; None before the first cycle, so
        # that starting disabled never counts as switching off.
        self._was_enabled: bool | None = None
        self._cycle_lock = asyncio.Lock()

    # --- lifecycle ---------------------------------------------------------

    async def _async_setup(self) -> None:
        """Load the stored settings and create the engine (first refresh only)."""
        self.settings = RuntimeSettings.from_dict(await self._store.async_load())
        zone_ids = {zone.zone_id for zone in self.zones}
        self.settings.zones = {
            k: v for k, v in self.settings.zones.items() if k in zone_ids
        }
        self.settings.minutes_per_c = {
            k: v for k, v in self.settings.minutes_per_c.items() if k in zone_ids
        }
        self._engine = self._new_engine()

    @callback
    def async_start(self) -> None:
        """Start listening to the configured entities."""
        if entity_ids := watched_entity_ids(self.config_entry, self.zones):
            self._unsubs.append(
                async_track_state_change_event(
                    self.hass, entity_ids, self._async_on_state_change
                )
            )
        # A DataUpdateCoordinator only polls while it has listeners. This one
        # controls the house, so it keeps polling even with no entity at all.
        self._unsubs.append(self.async_add_listener(self._keep_polling))

    async def async_shutdown(self) -> None:
        """Stop listeners and timers.

        Deliberately sends no command: on unload the valves keep their last
        setpoint and the climates and the boiler stay as they are, relying on
        the devices' own protection.
        """
        # Set first (the base class sets it too): a refresh still in flight
        # checks it and neither sends more commands nor re-arms a timer.
        self._shutdown_requested = True
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        self._cancel_timers()
        await super().async_shutdown()

    @callback
    def _schedule_refresh(self) -> None:
        """Never re-arm the poll once shut down.

        A refresh still in flight at shutdown would otherwise schedule the
        next poll while the entities are still listening.
        """
        if not self._shutdown_requested:
            super()._schedule_refresh()

    @callback
    def _keep_polling(self) -> None:
        """No-op listener that keeps the 10-minute cycle alive."""

    @callback
    def _async_on_state_change(self, _event: Event[EventStateChangedData]) -> None:
        self.config_entry.async_create_task(
            self.hass, self.async_request_refresh(), f"{DOMAIN} state change"
        )

    # --- evaluation --------------------------------------------------------

    def _boiler_state(self) -> State | None:
        """Return the boiler relay's state, None if missing or unusable."""
        if not self._boiler_entity:
            return None
        state = self.hass.states.get(self._boiler_entity)
        if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return None
        return state

    def _new_engine(self) -> HybridHeatEngine:
        """Create the engine, seeding the boiler with the relay's real state.

        At Home Assistant start the relay often does not exist yet: it is
        then seeded at the first evaluation where its state is known.
        """
        state = self._boiler_state()
        self._boiler_seeded = not self._boiler_entity or state is not None
        return HybridHeatEngine(
            self.settings.tunables,
            boiler_initial_on=state is not None and state.state == STATE_ON,
        )

    def _seed_boiler_late(self) -> None:
        assert self._engine is not None
        if self._boiler_seeded or (state := self._boiler_state()) is None:
            return
        self._engine.seed_boiler(state.state == STATE_ON)
        self._boiler_seeded = True

    def _follow_boiler_relay(self) -> None:
        """Keep the engine's boiler memory equal to the real relay.

        While disabled the relay is under the user's control; enabling
        again must start from what it really is.
        """
        assert self._engine is not None
        if (state := self._boiler_state()) is not None:
            self._engine.seed_boiler(state.state == STATE_ON)

    async def _async_update_data(self) -> EngineResult:
        # The commands change states, which may request a refresh while this
        # one is still sending: the lock keeps evaluations and commands in order.
        async with self._cycle_lock:
            assert self._engine is not None
            now = dt_util.now()
            house, zones = build_inputs(
                self.hass, self.config_entry, self.settings, now
            )
            self._seed_boiler_late()
            result = self._engine.evaluate(house, zones, now)
            await self._async_learn_preheat(zones, result, now)
            if self._shutdown_requested:
                return result
            # Timers first: they must be armed whatever happens to the commands.
            self._set_timer(_BOILER_TIMER, result.next_boiler_transition)
            self._set_timer(_WINDOW_TIMER, self._window_deadline(zones, now))
            was_enabled, self._was_enabled = self._was_enabled, house.enabled
            if not house.enabled:
                # Hands off: only the switch-off itself sends commands, once.
                if was_enabled:
                    await async_apply_all_off(
                        self.hass,
                        self.zones,
                        self._boiler_entity,
                        memory=self._commands,
                    )
                self._follow_boiler_relay()
                return result
            await async_apply_commands(
                self.hass,
                self.zones,
                result,
                self._boiler_entity,
                self.settings.tunables,
                stopped=lambda: self._shutdown_requested,
                memory=self._commands,
            )
            return result

    def _window_deadline(
        self, zones: list[ZoneInputs], now: datetime
    ) -> datetime | None:
        """Return when the first window still inside its delay will count.

        The engine needs `window_open_s > window_delay_s`, hence the extra
        second. Without this timer antifreeze would wait for the next cycle.
        """
        delay_s = self.settings.tunables.window_delay_s
        waits = [
            delay_s - zone.window_open_s
            for zone in zones
            if zone.window_open_s is not None and zone.window_open_s <= delay_s
        ]
        if not waits:
            return None
        return now + timedelta(seconds=min(waits) + 1)

    @callback
    def _set_timer(self, key: str, when: datetime | None) -> None:
        """Replace the one-shot refresh `key`; None just cancels it.

        The boiler timer keeps the 60 s / 180 s delays exact; the window
        timer applies the 2-minute window delay on time.
        """
        if (unsub := self._timers.pop(key, None)) is not None:
            unsub()
        if when is not None and not self._shutdown_requested:
            self._timers[key] = async_track_point_in_utc_time(
                self.hass, partial(self._async_timer_due, key), when
            )

    @callback
    def _cancel_timers(self) -> None:
        for unsub in self._timers.values():
            unsub()
        self._timers.clear()

    async def _async_timer_due(self, key: str, _now: datetime) -> None:
        self._timers.pop(key, None)
        await self.async_refresh()

    async def _async_learn_preheat(
        self, zones: list[ZoneInputs], result: EngineResult, now: datetime
    ) -> None:
        """Learn the minutes per degree from each completed preheat."""
        tun = self.settings.tunables
        changed = False
        for zone in zones:
            zid = zone.zone_id
            phase = result.zones[zid].phase
            prev = self._last_phase.get(zid)
            self._last_phase[zid] = phase
            if phase is Phase.PREHEATING:
                if zid not in self._preheat_start and zone.temperature_c is not None:
                    self._preheat_start[zid] = (now, zone.temperature_c)
                continue
            start = self._preheat_start.pop(zid, None)
            if (
                start is None
                or prev is not Phase.PREHEATING
                or phase is not Phase.MAINTENANCE
                or zone.temperature_c is None
            ):
                continue
            started_at, start_c = start
            old = self.settings.minutes_per_c.get(zid, tun.preheat_default_min_per_c)
            model = PreheatModel(old, tun.preheat_max_min)
            model.observe(
                zone.temperature_c - start_c, (now - started_at).total_seconds() / 60
            )
            learned = min(max(model.minutes_per_c, MIN_PER_C_MIN), MIN_PER_C_MAX)
            if learned != old:
                self.settings.minutes_per_c[zid] = learned
                changed = True
        if changed:
            await self._async_save()

    # --- user settings -----------------------------------------------------

    async def _async_save(self) -> None:
        await self._store.async_save(self.settings.as_dict())

    async def _async_settings_changed(self) -> None:
        await self._async_save()
        await self.async_request_refresh()

    def _check_zone(self, zone_id: str) -> None:
        if all(zone.zone_id != zone_id for zone in self.zones):
            raise ValueError(f"Unknown zone: {zone_id}")

    async def async_set_enabled(self, enabled: bool) -> None:
        """Turn the whole integration on or off (off = hands off)."""
        self.settings.enabled = bool(enabled)
        await self._async_settings_changed()

    async def async_set_mode(self, zone_id: str, mode: Mode | str) -> None:
        """Set the manual mode of a zone."""
        self._check_zone(zone_id)
        self.settings.zones[zone_id] = replace(
            self.settings.zone(zone_id), mode=Mode(mode)
        )
        await self._async_settings_changed()

    async def async_set_zone_value(
        self, zone_id: str, key: str, value: float
    ) -> None:
        """Set `comfort_c`, `eco_c` or `antifreeze_c` of a zone."""
        self._check_zone(zone_id)
        if key not in ZONE_VALUE_KEYS:
            raise ValueError(f"Unknown zone value: {key}")
        number = float(value)
        if not math.isfinite(number):
            raise ValueError(f"Invalid value for {key}: {value}")
        self.settings.zones[zone_id] = replace(
            self.settings.zone(zone_id), **{key: number}
        )
        await self._async_settings_changed()

    async def async_set_tunable(self, key: str, value: float | bool) -> None:
        """Set one of the Tunables.

        The engine takes the new tunables and keeps all its memory: boiler
        timing, hysteresis, held actuators and deficit timers.
        """
        self.settings.tunables = replace(
            self.settings.tunables, **{key: coerce_tunable(key, value)}
        )
        if self._engine is not None:
            self._engine.set_tunables(self.settings.tunables)
        await self._async_settings_changed()
