"""Free-energy sources: solar thermal and photovoltaic surplus."""

from __future__ import annotations

from .models import Phase, Tunables


def pv_surplus_w(grid_export_w: float | None, climate_power_w: float) -> float:
    """Return the photovoltaic surplus, counting power already absorbed by climates.

    `grid_export_w` is the signed net power available for heating before the
    climates' own consumption: grid net power (export minus import) plus the
    battery term (see `HouseInputs` in `models.py`). Power imported from the
    grid or taken from the battery is not photovoltaic, so it is subtracted
    from the climate power before clamping at zero.
    """
    if grid_export_w is None:
        return 0.0
    return max(0.0, grid_export_w + climate_power_w)


def update_solar_active(prev: bool, solar_c: float | None, tun: Tunables) -> bool:
    """Return whether solar thermal is active, with hysteresis."""
    if solar_c is None:
        return False
    if solar_c >= tun.solar_on_c:
        return True
    return prev and solar_c >= tun.solar_on_c - tun.solar_hyst_c


def solar_effective(
    solar_active: bool,
    solar_c: float | None,
    phase: Phase,
    tun: Tunables,
    hold: bool = False,
) -> bool:
    """Return whether solar thermal can serve a zone in its current phase.

    `hold` is true when the zone is already served by its valves: the high
    threshold used in preheating then drops by the hysteresis, so it does not
    flap around it.
    """
    if not solar_active or solar_c is None:
        return False
    if phase != Phase.PREHEATING:
        return True
    threshold = tun.solar_high_c - (tun.solar_hyst_c if hold else 0.0)
    return solar_c >= threshold


def active_source(solar_effective_any: bool, pv_used_any: bool) -> str:
    """Return the free source in use, solar thermal winning over photovoltaic."""
    if solar_effective_any:
        return "solar_thermal"
    if pv_used_any:
        return "photovoltaic"
    return "none"
