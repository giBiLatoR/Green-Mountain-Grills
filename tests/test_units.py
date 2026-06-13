"""Unit tests for the pure unit-conversion/formatting helpers."""

from __future__ import annotations

import pytest

from custom_components.gmg.units import (
    TEMP_C,
    TEMP_F,
    TEMP_UNIT_AUTO,
    TEMP_UNIT_CELSIUS,
    TEMP_UNIT_FAHRENHEIT,
    WEIGHT_KG,
    WEIGHT_LB,
    WEIGHT_UNIT_AUTO,
    WEIGHT_UNIT_KILOGRAMS,
    WEIGHT_UNIT_POUNDS,
    c_to_f,
    f_to_c,
    fmt_temp,
    fmt_weight,
    kg_to_lb,
    lb_to_kg,
    resolve_temp_unit,
    resolve_weight_unit,
)


def test_temperature_round_trip() -> None:
    for f in (32.0, 212.0, 225.0, 375.0):
        assert c_to_f(f_to_c(f)) == pytest.approx(f)


def test_known_temperature_points() -> None:
    assert f_to_c(32.0) == pytest.approx(0.0)
    assert f_to_c(212.0) == pytest.approx(100.0)
    assert c_to_f(100.0) == pytest.approx(212.0)


def test_weight_round_trip() -> None:
    for kg in (0.2, 1.0, 5.0, 12.0):
        assert lb_to_kg(kg_to_lb(kg)) == pytest.approx(kg)


def test_known_weight_point() -> None:
    assert kg_to_lb(1.0) == pytest.approx(2.20462, rel=1e-4)


def test_resolve_temp_unit_explicit_wins_over_system() -> None:
    assert resolve_temp_unit(TEMP_UNIT_CELSIUS, metric=False) == TEMP_C
    assert resolve_temp_unit(TEMP_UNIT_FAHRENHEIT, metric=True) == TEMP_F


def test_resolve_temp_unit_auto_follows_system() -> None:
    assert resolve_temp_unit(TEMP_UNIT_AUTO, metric=True) == TEMP_C
    assert resolve_temp_unit(TEMP_UNIT_AUTO, metric=False) == TEMP_F


def test_resolve_weight_unit() -> None:
    assert resolve_weight_unit(WEIGHT_UNIT_KILOGRAMS, metric=False) == WEIGHT_KG
    assert resolve_weight_unit(WEIGHT_UNIT_POUNDS, metric=True) == WEIGHT_LB
    assert resolve_weight_unit(WEIGHT_UNIT_AUTO, metric=True) == WEIGHT_KG
    assert resolve_weight_unit(WEIGHT_UNIT_AUTO, metric=False) == WEIGHT_LB


def test_fmt_temp() -> None:
    assert fmt_temp(212.0, TEMP_F) == "212°F"
    assert fmt_temp(212.0, TEMP_C) == "100°C"
    assert fmt_temp(None, TEMP_C) == "—"


def test_fmt_weight() -> None:
    assert fmt_weight(1.0, WEIGHT_KG) == "1.0 kg"
    assert fmt_weight(1.0, WEIGHT_LB) == "2.2 lb"
    assert fmt_weight(None, WEIGHT_LB) == "—"
