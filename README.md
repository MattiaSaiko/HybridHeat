<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="custom_components/hybrid_heat/brand/dark_logo.png">
    <img src="custom_components/hybrid_heat/brand/logo.png" alt="Hybrid Heat, smart room-by-room heating for Home Assistant" width="420">
  </picture>
</p>

# Hybrid Heat: smart zone heating for Home Assistant (TRV, heat pump, solar thermal, PV surplus)

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2026.2.0%2B-blue.svg)](https://www.home-assistant.io/)
[![Release](https://img.shields.io/github/v/release/MattiaSaiko/HybridHeat)](https://github.com/MattiaSaiko/HybridHeat/releases)
[![Validate](https://github.com/MattiaSaiko/HybridHeat/actions/workflows/validate.yml/badge.svg)](https://github.com/MattiaSaiko/HybridHeat/actions/workflows/validate.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![PayPal](https://img.shields.io/badge/Donate-PayPal-00457C.svg?logo=paypal&logoColor=white)](https://paypal.me/Saikoadv)

🇬🇧 English · 🇮🇹 [Italiano](README.it.md)

**Hybrid Heat** is a custom integration for [Home Assistant](https://www.home-assistant.io/) (install it with [HACS](https://hacs.xyz/)) that heats each room with the right device at the right time, to cut your heating bill. It is a smart multi-zone thermostat that coordinates **radiator thermostatic valves (TRV)**, **air conditioners and heat pumps** in heat mode and, optionally, a **gas boiler**. It uses free energy first: **solar thermal** and **photovoltaic (PV) surplus**, with home battery support.

Everything is set up from the Home Assistant UI, with no YAML. You create **zones** (a room or a group of rooms) and Hybrid Heat decides which device heats each zone, and to what temperature.

> 🇮🇹 **In breve:** integrazione per Home Assistant che coordina, stanza per stanza, valvole termostatiche, condizionatori e caldaia, usando prima l'energia gratuita (solare termico e surplus fotovoltaico). Guida in italiano: [README.it.md](README.it.md).

[![Open your Home Assistant instance and open this repository in HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=MattiaSaiko&repository=HybridHeat&category=integration)

## What you get

- **Heating by zone.** Each zone has its own schedule and its own comfort, eco and antifreeze temperatures.
- **The right device for the job.** Air conditioners bring a room up to temperature quickly; radiator valves keep it there efficiently.
- **Free energy first.** A hot solar thermal tank feeds the radiators and keeps the boiler off. A PV surplus (a home battery's charging counts too) runs the air conditioners.
- **Optional boiler control.** The boiler turns on only when a zone's valves call for heat.
- **Smart schedules.** Weekday and weekend comfort periods, or any Home Assistant `schedule` or calendar. Preheating learns how fast each room warms up.
- **Presence and windows.** Eco when nobody is home, antifreeze when a window is open.
- **Decisions you can read.** Every zone shows its current phase and why.
- **A standard thermostat per zone**, for the normal thermostat card, voice assistants and automations.
- **No prices, no cloud.** It only uses your own sensors. English and Italian included.

## How it decides

| Situation | What Hybrid Heat does |
|---|---|
| Room well below the comfort temperature | Air conditioner climbs (*preheating*) |
| Room close to the comfort temperature | Valves maintain it (*maintenance*) |
| Solar thermal tank hot | Radiators run on the sun, the boiler stays off |
| PV surplus | Air conditioners run on the surplus |
| Very cold outside | Valves instead of air conditioners |
| Window open for more than 2 minutes | Antifreeze |
| Nobody home (zone in Auto) | Eco temperature |

When both free sources are available, solar thermal wins if it is hot enough for what the room needs.

## Requirements

- Home Assistant **2026.2.0** or newer, set to **degrees Celsius**.
- For each zone, at least one thermostatic valve or one air conditioner (with a `heat` mode), exposed as a `climate` entity (Zigbee2MQTT, ZHA, Tado, Daikin, a manufacturer's integration, …).
- Everything else is optional: room temperature and window sensors, outdoor temperature, solar tank temperature, grid power for the PV surplus, a home battery, a boiler switch, `person` entities.

## Installation

**With HACS:** open HACS, menu (⋮) → **Custom repositories**, add `https://github.com/MattiaSaiko/HybridHeat` as **Integration**, download **Hybrid Heat** and restart Home Assistant.

**Manually:** copy `custom_components/hybrid_heat` into your `config/custom_components` folder and restart.

Then go to **Settings → Devices & services → Add integration** and choose **Hybrid Heat**.

## Setup

1. **House-wide sources** (all optional): outdoor temperature, solar tank temperature, grid power (one signed sensor, or two separate sensors for export and import), home battery, boiler switch, people.
2. **Zones**: from the integration page choose **Add zone**, then pick the zone's air conditioners, valves, temperature sensors, window sensors and schedule. The schedule can be the built-in comfort periods (weekdays and weekend, up to 3 each), an external `schedule` or calendar, or none.
3. **Turn it on.** Hybrid Heat starts disabled and does not touch your devices. Check the temperatures and modes, then switch on **Enabled**.

You can change sources and zones later from the integration page (⋮ → **Reconfigure**).

## Entities

For a zone called *Living room* (IDs are the English defaults):

| Entity | What it is |
|---|---|
| `climate.living_room` | The zone's thermostat: on/off, presets Auto, Comfort, Eco and Antifreeze, current temperature, heating state. Its attributes `phase` and `reason` explain the decision. |
| `select.living_room_mode` | `auto`, `comfort`, `eco`, `antifreeze` (holds the antifreeze temperature) or `off` (keeps the zone's devices off) |
| `number.living_room_comfort_temperature` (and the same for `eco` and `antifreeze`) | The zone's temperatures, 20 / 17 / 7 °C by default |
| `sensor.living_room_phase` | `off`, `antifreeze`, `window_open`, `eco`, `preheating` or `maintenance`, with attributes `reason`, `actuator` and `actuator_reason` |
| `binary_sensor.living_room_heat_request` | On when the zone asks for heat |

For the whole house: `switch.hybrid_heat_enabled` (off by default) and `sensor.hybrid_heat_active_source` (`solar_thermal`, `photovoltaic` or `none`). Thresholds, delays and the other settings are `number` entities in the integration's device page.

## Good to know

- **Disabled means hands off.** With **Enabled** off, Hybrid Heat sends no commands at all, not even antifreeze, so you control your devices yourself. When you switch it off, it turns your valves, heating air conditioners and boiler off once. For frost protection, keep **Enabled** on and set the zone to **Antifreeze**.
- **Boiler.** If you give Hybrid Heat a boiler switch, let it be the only thing that controls it. While enabled, it also switches the boiler on to protect zones in Antifreeze (or with an open window) from frost.
- **Removing it.** Your devices stay exactly as they are.
- **Heating only.** Air conditioners that are cooling, or in any other mode, are never touched. Temperatures are in °C, and there is one instance per Home Assistant.
- **Sensors can fail.** If a sensor is unavailable, Hybrid Heat keeps working with what it has.

## Support

If Hybrid Heat saves you some heating bills and you'd like to say thanks, you can buy me a coffee:

<div align="center">

[![PayPal](https://img.shields.io/badge/Donate-PayPal-00457C.svg?style=for-the-badge&logo=paypal&logoColor=white)](https://paypal.me/Saikoadv)

</div>

A ⭐ on the repository helps other people find it. Bug reports and ideas are welcome in the [issues](https://github.com/MattiaSaiko/HybridHeat/issues), in English or Italian. To add a language, copy `custom_components/hybrid_heat/translations/en.json` to `<language>.json`, translate the values and open a pull request.

## License

Released under the [MIT License](LICENSE).

## 🇮🇹 Italiano

**Hybrid Heat** è un'integrazione personalizzata per Home Assistant (installabile con HACS) che scalda ogni stanza con il dispositivo giusto al momento giusto. Coordina **valvole termostatiche**, **condizionatori / pompe di calore** in riscaldamento e, se presente, la **caldaia a gas**, usando prima l'energia gratuita: **solare termico** e **surplus fotovoltaico**. Si configura dall'interfaccia, senza YAML, e non usa prezzi o tariffe. Guida completa in italiano: **[README.it.md](README.it.md)**.
