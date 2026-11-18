"""Declared time units and conversion to a field's canonical unit."""
from __future__ import annotations

_SECONDS = {
    "second": 1, "seconds": 1, "sec": 1, "secs": 1, "s": 1,
    "minute": 60, "minutes": 60, "min": 60, "mins": 60, "m": 60,
    "hour": 3600, "hours": 3600, "hr": 3600, "hrs": 3600, "h": 3600,
    "day": 86400, "days": 86400, "d": 86400,
}


class UnitError(ValueError):
    pass


def is_unit(word: str) -> bool:
    return word.lower() in _SECONDS


def canonical(unit: str) -> str:
    u = unit.lower()
    if u not in _SECONDS:
        raise UnitError(f"unknown time unit {unit!r}")
    factor = _SECONDS[u]
    return {1: "seconds", 60: "minutes", 3600: "hours", 86400: "days"}[factor]


def convert(value: float, from_unit: str | None, to_unit: str | None) -> float:
    """Convert `value` from `from_unit` to `to_unit`.

    A missing `from_unit` means the value is already in the field's unit. A unit on a
    field that has no declared unit is an error, never silently ignored.
    """
    if from_unit is None:
        return float(value)
    if to_unit is None:
        raise UnitError(f"value given in {from_unit!r} but the field declares no unit")
    f, t = from_unit.lower(), to_unit.lower()
    if f not in _SECONDS:
        raise UnitError(f"unknown time unit {from_unit!r}")
    if t not in _SECONDS:
        raise UnitError(f"unknown time unit {to_unit!r}")
    return float(value) * _SECONDS[f] / _SECONDS[t]
