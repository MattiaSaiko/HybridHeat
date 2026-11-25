"""Config flow for Hybrid Heat: house sources, plus one subentry per zone.

The main entry holds the optional house-wide sources (outdoor temperature,
solar tank, grid power, battery, boiler, people). Each zone is a `zone` subentry; its
id is the zone id used everywhere else. The stored formats are the ones read
by `inputs.py`.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    SOURCE_RECONFIGURE,
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    SubentryFlowResult,
)
from homeassistant.const import Platform, UnitOfTemperature
from homeassistant.core import callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.selector import (
    BooleanSelector,
    EntitySelector,
    EntitySelectorConfig,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TimeSelector,
)

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
    DOMAIN,
    SCHEDULE_EXTERNAL,
    SCHEDULE_INTERNAL,
    SCHEDULE_NONE,
    SUBENTRY_ZONE,
)
from .engine.schedule import MAX_BANDS

ENTRY_TITLE = "Hybrid Heat"
PROFILES = ("weekday", "weekend")
_PLACEHOLDER_ENTITIES = "entities"


def _entities(domain: str | list[str], *, multiple: bool = False, **extra: Any):
    return EntitySelector(
        EntitySelectorConfig(domain=domain, multiple=multiple, **extra)
    )


MAIN_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_OUTDOOR_TEMP): _entities(Platform.SENSOR),
        vol.Optional(CONF_SOLAR_TEMP): _entities(Platform.SENSOR),
        vol.Optional(CONF_PV_EXPORT): _entities(Platform.SENSOR, device_class="power"),
        vol.Optional(CONF_PV_IMPORT): _entities(Platform.SENSOR, device_class="power"),
        vol.Optional(CONF_PV_INVERT, default=False): BooleanSelector(),
        vol.Optional(CONF_BATTERY_CHARGE): _entities(
            Platform.SENSOR, device_class="power"
        ),
        vol.Optional(CONF_BATTERY_DISCHARGE): _entities(
            Platform.SENSOR, device_class="power"
        ),
        vol.Optional(CONF_BATTERY_INVERT, default=False): BooleanSelector(),
        # Any sensor: the entity selector cannot filter by unit, and many
        # battery levels in % have no device class. A unit other than % makes
        # the level unusable at runtime.
        vol.Optional(CONF_BATTERY_SOC): _entities(Platform.SENSOR),
        vol.Optional(CONF_BOILER): _entities(Platform.SWITCH),
        vol.Optional(CONF_PRESENCE): _entities("person", multiple=True),
    }
)

ZONE_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_NAME): TextSelector(),
        vol.Optional(CONF_CLIMATES): _entities(Platform.CLIMATE, multiple=True),
        vol.Optional(CONF_VALVES): _entities(Platform.CLIMATE, multiple=True),
        vol.Optional(CONF_CLIMATE_POWER): _entities(
            Platform.SENSOR, multiple=True, device_class="power"
        ),
        vol.Optional(CONF_TEMPERATURE_SENSORS): _entities(
            Platform.SENSOR, multiple=True, device_class="temperature"
        ),
        vol.Optional(CONF_WINDOWS): _entities(Platform.BINARY_SENSOR, multiple=True),
        vol.Required(CONF_SCHEDULE_SOURCE, default=SCHEDULE_NONE): SelectSelector(
            SelectSelectorConfig(
                options=[SCHEDULE_INTERNAL, SCHEDULE_EXTERNAL, SCHEDULE_NONE],
                translation_key=CONF_SCHEDULE_SOURCE,
                mode=SelectSelectorMode.LIST,
            )
        ),
    }
)


def _band_key(profile: str, number: int, edge: str) -> str:
    return f"{profile}_{number}_{edge}"


SCHEDULE_INTERNAL_SCHEMA = vol.Schema(
    {
        vol.Optional(_band_key(profile, number, edge)): TimeSelector()
        for profile in PROFILES
        for number in range(1, MAX_BANDS + 1)
        for edge in ("start", "end")
    }
)

# Not `vol.Required`: a missing entity must come back as a form error.
SCHEDULE_EXTERNAL_SCHEMA = vol.Schema(
    {vol.Optional(CONF_SCHEDULE_ENTITY): _entities(["schedule", "calendar"])}
)


# --- main entry ------------------------------------------------------------


def _sources_from_form(user_input: Mapping[str, Any]) -> dict[str, Any]:
    """Keep only the chosen sources; the invert flags are always stored."""
    data = {
        key: value
        for key in (
            CONF_OUTDOOR_TEMP,
            CONF_SOLAR_TEMP,
            CONF_PV_EXPORT,
            CONF_PV_IMPORT,
            CONF_BATTERY_CHARGE,
            CONF_BATTERY_DISCHARGE,
            CONF_BATTERY_SOC,
            CONF_BOILER,
            CONF_PRESENCE,
        )
        if (value := user_input.get(key))
    }
    data[CONF_PV_INVERT] = bool(user_input.get(CONF_PV_INVERT, False))
    data[CONF_BATTERY_INVERT] = bool(user_input.get(CONF_BATTERY_INVERT, False))
    return data


class HybridHeatConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up the house-wide sources; zones are added as subentries."""

    VERSION = 1

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Return the subentry types: one per zone."""
        return {SUBENTRY_ZONE: ZoneSubentryFlow}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose the optional house-wide sources."""
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")
        if self.hass.config.units.temperature_unit != UnitOfTemperature.CELSIUS:
            # The engine works in °C; climates report the system unit.
            return self.async_abort(reason="unit_not_celsius")
        if user_input is not None:
            return self.async_create_entry(
                title=ENTRY_TITLE, data=_sources_from_form(user_input)
            )
        return self.async_show_form(step_id="user", data_schema=MAIN_SCHEMA)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the sources; a cleared field removes that source."""
        entry = self._get_reconfigure_entry()
        if user_input is not None:
            data = _sources_from_form(user_input)
            if entry.update_listeners:
                # Loaded: the entry's update listener reloads it on change.
                return self.async_update_and_abort(entry, data=data)
            return self.async_update_reload_and_abort(entry, data=data)
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(MAIN_SCHEMA, entry.data),
        )


# --- zone subentries -------------------------------------------------------


def _zone_from_form(user_input: Mapping[str, Any]) -> dict[str, Any]:
    """Return complete zone data; the schedule details are filled later."""
    return {
        CONF_NAME: str(user_input.get(CONF_NAME) or "").strip(),
        CONF_CLIMATES: list(user_input.get(CONF_CLIMATES) or []),
        CONF_CLIMATE_POWER: list(user_input.get(CONF_CLIMATE_POWER) or []),
        CONF_VALVES: list(user_input.get(CONF_VALVES) or []),
        CONF_TEMPERATURE_SENSORS: list(user_input.get(CONF_TEMPERATURE_SENSORS) or []),
        CONF_WINDOWS: list(user_input.get(CONF_WINDOWS) or []),
        CONF_SCHEDULE_SOURCE: user_input.get(CONF_SCHEDULE_SOURCE, SCHEDULE_NONE),
        CONF_SCHEDULE_ENTITY: None,
        CONF_PROGRAM: {profile: [] for profile in PROFILES},
    }


def _program_from_form(
    user_input: Mapping[str, Any],
) -> tuple[dict[str, list[dict[str, str]]], dict[str, str]]:
    """Return the program and the errors of bands missing start or end."""
    program: dict[str, list[dict[str, str]]] = {}
    errors: dict[str, str] = {}
    for profile in PROFILES:
        bands: list[dict[str, str]] = []
        for number in range(1, MAX_BANDS + 1):
            start_key = _band_key(profile, number, "start")
            end_key = _band_key(profile, number, "end")
            start, end = user_input.get(start_key), user_input.get(end_key)
            if start and end:
                bands.append({"start": start, "end": end})
            elif start:
                errors[end_key] = "band_incomplete"
            elif end:
                errors[start_key] = "band_incomplete"
        program[profile] = bands
    return program, errors


def _program_to_form(program: Any) -> dict[str, str]:
    """Return the form values of a stored program."""
    values: dict[str, str] = {}
    if not isinstance(program, Mapping):
        return values
    for profile in PROFILES:
        bands = program.get(profile) or []
        for number, band in enumerate(bands[:MAX_BANDS], start=1):
            for edge in ("start", "end"):
                if band.get(edge):
                    values[_band_key(profile, number, edge)] = band[edge]
    return values


class ZoneSubentryFlow(ConfigSubentryFlow):
    """Add or change a zone: entities, then its schedule."""

    def __init__(self) -> None:
        """Start with no zone data."""
        self._zone: dict[str, Any] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Add a zone."""
        return await self._async_zone_step("user", user_input)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Change a zone."""
        return await self._async_zone_step("reconfigure", user_input)

    async def async_step_schedule_internal(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Up to three comfort bands for weekdays and for weekends."""
        errors: dict[str, str] = {}
        if user_input is not None:
            program, errors = _program_from_form(user_input)
            if not errors:
                self._zone[CONF_PROGRAM] = program
                return self._async_finish()
            suggested: Mapping[str, Any] = user_input
        else:
            suggested = _program_to_form(self._previous_data().get(CONF_PROGRAM))
        return self.async_show_form(
            step_id="schedule_internal",
            data_schema=self.add_suggested_values_to_schema(
                SCHEDULE_INTERNAL_SCHEMA, suggested
            ),
            errors=errors,
        )

    async def async_step_schedule_external(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """A `schedule` or calendar entity: on means comfort."""
        errors: dict[str, str] = {}
        if user_input is not None:
            if entity_id := user_input.get(CONF_SCHEDULE_ENTITY):
                self._zone[CONF_SCHEDULE_ENTITY] = entity_id
                return self._async_finish()
            errors[CONF_SCHEDULE_ENTITY] = "schedule_entity_required"
            suggested: Mapping[str, Any] = user_input
        else:
            suggested = self._previous_data()
        return self.async_show_form(
            step_id="schedule_external",
            data_schema=self.add_suggested_values_to_schema(
                SCHEDULE_EXTERNAL_SCHEMA, suggested
            ),
            errors=errors,
        )

    async def _async_zone_step(
        self, step_id: str, user_input: dict[str, Any] | None
    ) -> SubentryFlowResult:
        errors: dict[str, str] = {}
        conflicts: list[str] = []
        if user_input is not None:
            zone = _zone_from_form(user_input)
            errors, conflicts = self._validate(zone)
            if not errors:
                self._zone = zone
                source = zone[CONF_SCHEDULE_SOURCE]
                if source == SCHEDULE_INTERNAL:
                    return await self.async_step_schedule_internal()
                if source == SCHEDULE_EXTERNAL:
                    return await self.async_step_schedule_external()
                return self._async_finish()
            suggested: Mapping[str, Any] = user_input
        else:
            suggested = self._previous_data()
        return self.async_show_form(
            step_id=step_id,
            data_schema=self.add_suggested_values_to_schema(ZONE_SCHEMA, suggested),
            errors=errors,
            description_placeholders={_PLACEHOLDER_ENTITIES: ", ".join(conflicts)},
        )

    def _validate(self, zone: Mapping[str, Any]) -> tuple[dict[str, str], list[str]]:
        """Return the form errors and the climate/valve entities in conflict."""
        if not zone[CONF_NAME]:
            return {CONF_NAME: "name_required"}, []
        climates, valves = zone[CONF_CLIMATES], zone[CONF_VALVES]
        if not climates and not valves:
            return {"base": "climate_or_valves_required"}, []
        registry = er.async_get(self.hass)
        own = sorted(
            entity_id
            for entity_id in set(climates) | set(valves)
            if (reg_entry := registry.async_get(entity_id)) is not None
            and reg_entry.platform == DOMAIN
        )
        if own:
            return {"base": "own_entity"}, own
        current = self._reconfigured_id()
        taken: set[str] = set()
        for subentry_id, subentry in self._get_entry().subentries.items():
            if subentry.subentry_type == SUBENTRY_ZONE and subentry_id != current:
                taken.update(subentry.data.get(CONF_CLIMATES) or ())
                taken.update(subentry.data.get(CONF_VALVES) or ())
        conflicts = sorted(
            (set(climates) & set(valves)) | ((set(climates) | set(valves)) & taken)
        )
        if conflicts:
            return {"base": "entity_in_other_zone"}, conflicts
        return {}, []

    def _reconfigured_id(self) -> str | None:
        if self.source != SOURCE_RECONFIGURE:
            return None
        return self._get_reconfigure_subentry().subentry_id

    def _previous_data(self) -> Mapping[str, Any]:
        """The stored data of the zone being changed, empty for a new one."""
        if self.source != SOURCE_RECONFIGURE:
            return {}
        return self._get_reconfigure_subentry().data

    @callback
    def _async_finish(self) -> SubentryFlowResult:
        title = self._zone[CONF_NAME]
        if self.source != SOURCE_RECONFIGURE:
            return self.async_create_entry(title=title, data=self._zone)
        entry = self._get_entry()
        subentry = self._get_reconfigure_subentry()
        if entry.update_listeners:
            # Loaded: the entry's update listener reloads it on change.
            return self.async_update_and_abort(
                entry, subentry, title=title, data=self._zone
            )
        return self.async_update_reload_and_abort(
            entry, subentry, title=title, data=self._zone
        )
