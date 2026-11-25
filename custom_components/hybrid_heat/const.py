"""Constants for Hybrid Heat."""

from datetime import timedelta

from homeassistant.const import Platform

DOMAIN = "hybrid_heat"

PLATFORMS: list[Platform] = [
    Platform.SWITCH,
    Platform.SELECT,
    Platform.NUMBER,
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.CLIMATE,
]

DEFAULT_COMFORT_C = 20.0
DEFAULT_ECO_C = 17.0
DEFAULT_ANTIFREEZE_C = 7.0

UPDATE_INTERVAL = timedelta(minutes=10)

STORAGE_VERSION = 1
STORAGE_KEY_PREFIX = DOMAIN

# Bounds of the learned preheat speed, applied when it is persisted.
MIN_PER_C_MIN = 5.0
MIN_PER_C_MAX = 120.0

# Main entry data keys.
CONF_OUTDOOR_TEMP = "outdoor_temp"
CONF_SOLAR_TEMP = "solar_temp"
# Grid power: one signed net sensor (`pv_export`, positive = export), or two
# unsigned sensors when `pv_import` is set too.
CONF_PV_EXPORT = "pv_export"
CONF_PV_IMPORT = "pv_import"
CONF_PV_INVERT = "pv_invert"
# Battery power: one signed sensor (`battery_charge`, positive = charging), or
# two unsigned sensors when `battery_discharge` is set too.
CONF_BATTERY_CHARGE = "battery_charge"
CONF_BATTERY_DISCHARGE = "battery_discharge"
CONF_BATTERY_INVERT = "battery_invert"
CONF_BATTERY_SOC = "battery_soc"
CONF_BOILER = "boiler"
CONF_PRESENCE = "presence"

# Zone subentries.
SUBENTRY_ZONE = "zone"
CONF_NAME = "name"
CONF_CLIMATES = "climates"
CONF_CLIMATE_POWER = "climate_power"
CONF_VALVES = "valves"
CONF_TEMPERATURE_SENSORS = "temperature_sensors"
CONF_WINDOWS = "windows"
CONF_SCHEDULE_SOURCE = "schedule_source"
CONF_SCHEDULE_ENTITY = "schedule_entity"
CONF_PROGRAM = "program"

SCHEDULE_INTERNAL = "internal"
SCHEDULE_EXTERNAL = "external"
SCHEDULE_NONE = "none"
