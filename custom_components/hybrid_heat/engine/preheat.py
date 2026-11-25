"""Preheat lead-time model, learned from observed warm-up rates."""

from __future__ import annotations

_WEIGHT = 0.3
_MIN_DELTA_C = 0.3


class PreheatModel:
    """Estimates how many minutes a zone needs to gain one degree."""

    def __init__(self, minutes_per_c: float = 30.0, max_min: float = 180.0) -> None:
        self._minutes_per_c = minutes_per_c
        self._max_min = max_min

    @property
    def minutes_per_c(self) -> float:
        return self._minutes_per_c

    def lead_minutes(self, comfort_c: float, current_c: float) -> float:
        """Return how early to start heating, clamped to [0, max_min]."""
        lead = (comfort_c - current_c) * self._minutes_per_c
        return min(max(lead, 0.0), self._max_min)

    def observe(self, delta_c: float, minutes: float) -> None:
        """Blend a measured warm-up (delta_c gained in minutes) into the estimate."""
        if delta_c < _MIN_DELTA_C or minutes <= 0:
            return
        measured = minutes / delta_c
        self._minutes_per_c += _WEIGHT * (measured - self._minutes_per_c)
