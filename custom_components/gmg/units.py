"""Unit conversion and formatting helpers for the GMG integration.

Pure functions with no Home Assistant imports — safe to unit-test in isolation.

The grill protocol is natively Fahrenheit and the cook physics works in pounds
internally. These helpers convert the canonical values (Fahrenheit, kilograms)
to the user's chosen display unit for the notifications and dashboard the
integration renders itself. The standard temperature entities are switched via
the entity registry; see ``__init__._async_apply_temperature_unit``.
"""

from __future__ import annotations

# Options-flow preference values (stored in the config entry options).
TEMP_UNIT_AUTO = "auto"
TEMP_UNIT_CELSIUS = "celsius"
TEMP_UNIT_FAHRENHEIT = "fahrenheit"

WEIGHT_UNIT_AUTO = "auto"
WEIGHT_UNIT_KILOGRAMS = "kilograms"
WEIGHT_UNIT_POUNDS = "pounds"

# Resolved, concrete unit tokens used internally and by the cook manager.
TEMP_C = "C"
TEMP_F = "F"
WEIGHT_KG = "kg"
WEIGHT_LB = "lb"

LB_PER_KG = 1.0 / 0.453592


def f_to_c(value_f: float) -> float:
    """Convert a Fahrenheit value to Celsius."""
    return (value_f - 32.0) * 5.0 / 9.0


def c_to_f(value_c: float) -> float:
    """Convert a Celsius value to Fahrenheit."""
    return value_c * 9.0 / 5.0 + 32.0


def kg_to_lb(value_kg: float) -> float:
    """Convert a kilogram value to pounds."""
    return value_kg * LB_PER_KG


def lb_to_kg(value_lb: float) -> float:
    """Convert a pound value to kilograms."""
    return value_lb / LB_PER_KG


def resolve_temp_unit(pref: str, *, metric: bool) -> str:
    """Resolve a temperature preference to a concrete ``"C"`` or ``"F"``.

    ``auto`` follows the Home Assistant unit system (``metric`` flag).
    """
    if pref == TEMP_UNIT_CELSIUS:
        return TEMP_C
    if pref == TEMP_UNIT_FAHRENHEIT:
        return TEMP_F
    return TEMP_C if metric else TEMP_F


def resolve_weight_unit(pref: str, *, metric: bool) -> str:
    """Resolve a weight preference to a concrete ``"kg"`` or ``"lb"``.

    ``auto`` follows the Home Assistant unit system (``metric`` flag).
    """
    if pref == WEIGHT_UNIT_KILOGRAMS:
        return WEIGHT_KG
    if pref == WEIGHT_UNIT_POUNDS:
        return WEIGHT_LB
    return WEIGHT_KG if metric else WEIGHT_LB


def fmt_temp(value_f: float | None, unit: str) -> str:
    """Format a canonical Fahrenheit value as a display string in ``unit``."""
    if value_f is None:
        return "—"
    if unit == TEMP_C:
        return f"{round(f_to_c(value_f))}°C"
    return f"{round(value_f)}°F"


def fmt_weight(value_kg: float | None, unit: str) -> str:
    """Format a canonical kilogram value as a display string in ``unit``."""
    if value_kg is None:
        return "—"
    if unit == WEIGHT_LB:
        return f"{kg_to_lb(value_kg):.1f} lb"
    return f"{value_kg:.1f} kg"
