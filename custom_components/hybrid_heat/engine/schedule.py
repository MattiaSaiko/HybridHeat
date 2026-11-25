"""Internal weekly schedule: comfort bands for weekdays and weekends."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

MAX_BANDS = 3
_LOOKAHEAD_DAYS = 8


@dataclass(frozen=True)
class Band:
    """A comfort time band; end <= start means it crosses midnight."""

    start: time
    end: time

    @property
    def crosses_midnight(self) -> bool:
        return self.end <= self.start


@dataclass(frozen=True)
class Program:
    """Comfort bands for Monday-Friday and for Saturday-Sunday."""

    weekday: tuple[Band, ...] = ()
    weekend: tuple[Band, ...] = ()


def _bands_for(program: Program, day: date) -> tuple[Band, ...]:
    return program.weekend if day.weekday() >= 5 else program.weekday


def is_comfort_time(program: Program, now: datetime) -> bool:
    """Return True if `now` falls inside a comfort band.

    A band belongs to the day it starts on, so a band crossing midnight is
    also checked against the previous day's profile.
    """
    t = now.time()
    for band in _bands_for(program, now.date()):
        if band.crosses_midnight:
            if t >= band.start:
                return True
        elif band.start <= t < band.end:
            return True
    yesterday = now.date() - timedelta(days=1)
    return any(
        band.crosses_midnight and t < band.end
        for band in _bands_for(program, yesterday)
    )


def minutes_to_next_comfort(program: Program, now: datetime) -> float | None:
    """Return minutes until the next band start strictly after `now`."""
    best: float | None = None
    for offset in range(_LOOKAHEAD_DAYS):
        day = now.date() + timedelta(days=offset)
        for band in _bands_for(program, day):
            start = datetime.combine(day, band.start, tzinfo=now.tzinfo)
            if start <= now:
                continue
            minutes = (start - now).total_seconds() / 60
            if best is None or minutes < best:
                best = minutes
    return best
