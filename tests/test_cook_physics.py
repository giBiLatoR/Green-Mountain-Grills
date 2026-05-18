"""Tests for the cook physics module (pure-Python diffusion model port)."""
from __future__ import annotations

import math

import pytest

from custom_components.gmg.cook_physics import (
    CP_MEATS,
    CookProjection,
    compute_at,
    expected_probe_at,
    find_exact_temp,
    phase_at,
    phase_hours,
    wet_bulb_f,
)


def test_meats_table_size() -> None:
    """All 21 canonical meats from app.js CP_MEATS must be present."""
    assert len(CP_MEATS) == 21
    for key, meat in CP_MEATS.items():
        assert meat.key == key
        assert meat.label
        assert meat.pull_f > 0
        assert meat.max_hours > 0


def test_wet_bulb_below_dry_bulb() -> None:
    """Wet-bulb is always <= dry-bulb at non-100% RH."""
    for tdb in (150, 200, 225, 250, 300):
        twb = wet_bulb_f(tdb, 12)
        assert twb < tdb
        assert twb > 0


def test_phase_returns_inf_when_unreachable() -> None:
    """Drive temp below final temp → infinite time."""
    assert math.isinf(phase_hours(1.85, 1.5, t_drive_f=100, t_init_f=38, t_final_f=200))


def test_compute_at_brisket_low_and_slow() -> None:
    """10lb brisket @ 225°F should land in 12–24h ballpark (smoking_formula_research)."""
    res = compute_at("beef_brisket_packer", 10.0, 225.0)
    assert res is not None
    assert isinstance(res, CookProjection)
    assert 10 <= res.total_hours <= 30
    # Brisket has foil → 2 phases (Smoke & Bark, Foil Wrap — Render).
    names = [p.name for p in res.phases]
    assert "Smoke & Bark" in names
    assert "Foil Wrap — Render" in names


def test_compute_at_chicken_no_stall() -> None:
    """Chicken doesn't stall — single Smoke phase."""
    res = compute_at("whole_chicken", 2.0, 350.0)
    assert res is not None
    assert len(res.phases) == 1
    assert res.phases[0].name == "Smoke"
    assert res.total_hours < 3.0


def test_compute_at_unwrapped_stall_has_three_phases() -> None:
    """Stalling meat without foil → Smoke/Bark + Stall + Render."""
    res = compute_at("beef_ribs_dino", 4.0, 250.0)
    assert res is not None
    phase_names = [p.name for p in res.phases]
    assert "Smoke & Bark" in phase_names
    assert "Stall Plateau" in phase_names
    assert "Collagen Render" in phase_names


def test_compute_at_returns_none_when_pit_too_cool() -> None:
    """Pit at or below wet-bulb cannot drive cook."""
    # 100°F pit can't cook a brisket at all.
    assert compute_at("beef_brisket_packer", 10.0, 100.0) is None


def test_find_exact_temp_inversely_monotonic() -> None:
    """Longer target cook → cooler pit temp."""
    fast = find_exact_temp("pork_butt_pulled", 8.0, 8.0)
    slow = find_exact_temp("pork_butt_pulled", 8.0, 16.0)
    assert fast > slow
    # Binary search should land within the valid GMG range.
    assert 150 <= slow <= 450
    assert 150 <= fast <= 450


def test_expected_probe_monotonic_in_elapsed() -> None:
    """expected_probe should increase over elapsed time."""
    res = compute_at("pork_butt_pulled", 8.0, 250.0)
    assert res is not None
    samples = [expected_probe_at(res, h) for h in (0.5, 2.0, 5.0, 9.0, 15.0)]
    for prev, nxt in zip(samples, samples[1:]):
        assert nxt >= prev


def test_phase_at_classifies_probe_temps() -> None:
    """phase_at returns expected labels at boundary probe temps."""
    res = compute_at("beef_brisket_packer", 10.0, 225.0)
    assert res is not None
    pull = CP_MEATS["beef_brisket_packer"].pull_f
    assert phase_at(res, 100, pull) == "pre_stall"
    assert phase_at(res, 162, pull) == "stall"
    assert phase_at(res, 180, pull) == "post_stall"
    assert phase_at(res, pull - 5, pull) == "approaching"
    assert phase_at(res, pull, pull) == "pull_reached"


def test_chicken_phase_at_is_single_phase() -> None:
    """Non-stall meats always classify mid-cook as single_phase."""
    res = compute_at("whole_chicken", 2.0, 325.0)
    assert res is not None
    pull = CP_MEATS["whole_chicken"].pull_f
    assert phase_at(res, 120, pull) == "single_phase"


@pytest.mark.parametrize("meat_key", list(CP_MEATS.keys()))
def test_all_meats_compute_at_default_pit(meat_key: str) -> None:
    """Every meat must yield a finite projection at its likely pit temp."""
    weight = 4.0 if not CP_MEATS[meat_key].stall else 8.0
    res = compute_at(meat_key, weight, 275.0)
    assert res is not None
    assert math.isfinite(res.total_hours)
    assert res.total_hours > 0
