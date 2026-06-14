"""Heat diffusion physics model for the GMG auto-cook feature.

Pure Python port of the JavaScript cook planner (see app.js — cpComputeAt,
cpPhase, cpFindExactTemp). No Home Assistant or asyncio imports. Safe to
unit-test in isolation.

Reference: smoking_formula_research.md (heat-diffusion model derivation).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

# Physics constants ----------------------------------------------------------
CP_STALL_START_F = 150  # Lower bound of projection-curve stall region (°F).
CP_STALL_END_F = 165  # Upper bound of projection-curve stall region (°F).
CP_RH_PELLET = 12  # Approx RH (%) inside a pellet-smoker firebox.
CP_TI_F = 38  # Initial meat temp assumed at cook start (°F).
LBS_PER_KG = 1.0 / 0.453592

# Runtime stall-detection range (CONTEXT.md — distinct from projection range).
STALL_DETECT_LOW_F = 158
STALL_DETECT_HIGH_F = 170


@dataclass(frozen=True, slots=True)
class Meat:
    """One reference meat entry from the physics model."""

    key: str
    label: str
    km: float
    lfn: Callable[[float], float]
    pull_f: int
    stall: bool
    rest_min: int
    foil: bool
    max_hours: float
    by_the_piece: bool = False
    fixed_pit_f: int | None = None


def _l_linear(intercept: float, slope: float = 0.0) -> Callable[[float], float]:
    """Build a half-thickness function L(w) = intercept + slope * w_lbs."""
    return lambda w: intercept + slope * w


# CP_MEATS — 21 canonical meats, identical to app.js CP_MEATS table.
# max_hours from CONTEXT.md absolute-max-cook-hours guardrails.
CP_MEATS: dict[str, Meat] = {
    "beef_brisket_packer": Meat(
        "beef_brisket_packer",
        "Beef Brisket — Whole Packer",
        1.85,
        _l_linear(1.2, 0.05),
        203,
        stall=True,
        rest_min=90,
        foil=True,
        max_hours=20.0,
    ),
    "beef_brisket_flat": Meat(
        "beef_brisket_flat",
        "Beef Brisket — Flat Only",
        1.90,
        _l_linear(1.2, 0.05),
        198,
        stall=True,
        rest_min=30,
        foil=True,
        max_hours=20.0,
    ),
    "pork_butt_pulled": Meat(
        "pork_butt_pulled",
        "Pork Butt — Pulled Pork",
        1.80,
        _l_linear(1.9),
        203,
        stall=True,
        rest_min=60,
        foil=True,
        max_hours=16.0,
    ),
    "pork_butt_sliced": Meat(
        "pork_butt_sliced",
        "Pork Butt — Sliced",
        1.80,
        _l_linear(1.9),
        190,
        stall=True,
        rest_min=45,
        foil=True,
        max_hours=16.0,
    ),
    "beef_chuck_roast": Meat(
        "beef_chuck_roast",
        "Beef Chuck Roast",
        1.85,
        _l_linear(1.2, 0.05),
        195,
        stall=True,
        rest_min=45,
        foil=True,
        max_hours=8.0,
    ),
    "lamb_shoulder": Meat(
        "lamb_shoulder",
        "Lamb Shoulder",
        1.85,
        _l_linear(1.0, 0.07),
        190,
        stall=True,
        rest_min=45,
        foil=True,
        max_hours=10.0,
    ),
    "beef_ribs_dino": Meat(
        "beef_ribs_dino",
        "Beef Ribs — Short Plate",
        1.75,
        _l_linear(0.75),
        203,
        stall=True,
        rest_min=45,
        foil=False,
        max_hours=10.0,
    ),
    "whole_turkey": Meat(
        "whole_turkey",
        "Whole Turkey",
        1.55,
        _l_linear(1.5, 0.05),
        165,
        stall=False,
        rest_min=35,
        foil=False,
        max_hours=8.0,
    ),
    "turkey_breast": Meat(
        "turkey_breast",
        "Turkey Breast",
        1.60,
        _l_linear(1.0, 0.08),
        160,
        stall=False,
        rest_min=20,
        foil=False,
        max_hours=8.0,
    ),
    "whole_chicken": Meat(
        "whole_chicken",
        "Whole Chicken",
        1.55,
        _l_linear(1.0, 0.10),
        165,
        stall=False,
        rest_min=15,
        foil=False,
        max_hours=4.0,
    ),
    "chicken_thighs_legs": Meat(
        "chicken_thighs_legs",
        "Chicken Thighs / Legs",
        1.55,
        _l_linear(1.2),
        175,
        stall=False,
        rest_min=10,
        foil=False,
        max_hours=4.0,
    ),
    "chicken_breast": Meat(
        "chicken_breast",
        "Chicken Breasts",
        1.55,
        _l_linear(1.2),
        162,
        stall=False,
        rest_min=5,
        foil=False,
        max_hours=4.0,
        by_the_piece=True,
        fixed_pit_f=275,
    ),
    "pork_loin": Meat(
        "pork_loin",
        "Pork Loin Roast",
        1.60,
        _l_linear(1.0, 0.08),
        145,
        stall=False,
        rest_min=15,
        foil=False,
        max_hours=4.0,
    ),
    "lamb_leg": Meat(
        "lamb_leg",
        "Lamb Leg (Bone-In)",
        1.60,
        _l_linear(1.0, 0.08),
        135,
        stall=False,
        rest_min=15,
        foil=False,
        max_hours=10.0,
    ),
    "beef_tri_tip": Meat(
        "beef_tri_tip",
        "Beef Tri-Tip Roast",
        1.60,
        _l_linear(1.2),
        135,
        stall=False,
        rest_min=10,
        foil=False,
        max_hours=8.0,
    ),
    "beef_prime_rib": Meat(
        "beef_prime_rib",
        "Beef Prime Rib Roast",
        1.60,
        _l_linear(1.2, 0.05),
        130,
        stall=False,
        rest_min=25,
        foil=False,
        max_hours=8.0,
    ),
    "baby_back_ribs": Meat(
        "baby_back_ribs",
        "Baby Back Ribs",
        1.70,
        _l_linear(0.6),
        190,
        stall=False,
        rest_min=15,
        foil=False,
        max_hours=10.0,
    ),
    "spare_ribs_stlouis": Meat(
        "spare_ribs_stlouis",
        "Spare Ribs — St. Louis Style",
        1.72,
        _l_linear(0.65),
        195,
        stall=False,
        rest_min=15,
        foil=False,
        max_hours=10.0,
    ),
    "pork_chops": Meat(
        "pork_chops",
        "Pork Chops",
        1.60,
        _l_linear(0.8),
        145,
        stall=False,
        rest_min=5,
        foil=False,
        max_hours=4.0,
    ),
    "salmon_fillet": Meat(
        "salmon_fillet",
        "Salmon Fillet",
        1.50,
        _l_linear(0.3, 0.06),
        145,
        stall=False,
        rest_min=5,
        foil=True,
        max_hours=2.0,
    ),
    "sausage_brats": Meat(
        "sausage_brats",
        "Sausage / Bratwurst",
        1.55,
        _l_linear(0.7),
        160,
        stall=False,
        rest_min=5,
        foil=False,
        max_hours=3.0,
        by_the_piece=True,
        fixed_pit_f=250,
    ),
}


@dataclass(frozen=True, slots=True)
class Phase:
    """One segment of the projection curve."""

    name: str
    start_internal_f: float
    end_internal_f: float
    hours: float


@dataclass(frozen=True, slots=True)
class CookProjection:
    """Result of cpComputeAt — total hours plus per-phase breakdown."""

    total_hours: float
    half_thickness_in: float
    wet_bulb_f: float
    phases: tuple[Phase, ...]


def wet_bulb_f(tdb_f: float, rh_pct: float) -> float:
    """Rogers & Howarth wet-bulb approximation in Fahrenheit."""
    t_c = (tdb_f - 32) * 5 / 9
    tw_c = (
        t_c * math.atan(0.151977 * (rh_pct + 8.313659) ** 0.5)
        + math.atan(t_c + rh_pct)
        - math.atan(rh_pct - 1.676331)
        + 0.00391838 * (rh_pct**1.5) * math.atan(0.023101 * rh_pct)
        - 4.686035
    )
    return tw_c * 9 / 5 + 32


def phase_hours(
    km: float, l_in: float, t_drive_f: float, t_init_f: float, t_final_f: float
) -> float:
    """Single diffusion phase duration in hours. Returns inf for unreachable cases."""
    if t_drive_f <= t_final_f or not math.isfinite(t_drive_f):
        return math.inf
    ratio = (t_drive_f - t_init_f) / (t_drive_f - t_final_f)
    if ratio <= 0 or not math.isfinite(ratio):
        return math.inf
    return km * l_in * l_in * math.log(ratio)


def compute_at(meat_key: str, weight_lbs: float, pit_f: float) -> CookProjection | None:  # noqa: C901, PLR0911
    """Compute the projected cook for a meat at a given pit temp.

    Returns None when the pit is too cool (wet-bulb >= pit) or numeric failure.
    """
    meat = CP_MEATS.get(meat_key)
    if meat is None or not math.isfinite(pit_f):
        return None
    km = meat.km
    l_in = meat.lfn(weight_lbs)
    twb = wet_bulb_f(pit_f, CP_RH_PELLET)
    t_final = float(meat.pull_f)
    t_init = float(CP_TI_F)
    if twb >= pit_f:
        return None

    phases: list[Phase] = []

    if not meat.stall:
        t = phase_hours(km, l_in, pit_f, t_init, t_final)
        if t <= 0 or not math.isfinite(t):
            return None
        phases.append(Phase("Smoke", t_init, t_final, t))
        return CookProjection(t, l_in, twb, tuple(phases))

    if meat.foil:
        t1 = phase_hours(km, l_in, pit_f, t_init, CP_STALL_START_F)
        t3 = phase_hours(km, l_in, pit_f, CP_STALL_START_F, t_final)
        if not math.isfinite(t1) or not math.isfinite(t3) or (t1 + t3) <= 0:
            return None
        phases.append(Phase("Smoke & Bark", t_init, CP_STALL_START_F, t1))
        phases.append(Phase("Foil Wrap — Render", CP_STALL_START_F, t_final, t3))
        return CookProjection(t1 + t3, l_in, twb, tuple(phases))

    # Unwrapped stall — evaporative cooling reduces effective drive temp 40%.
    t_eff = pit_f - (pit_f - twb) * 0.40
    t1 = phase_hours(km, l_in, pit_f, t_init, CP_STALL_START_F)
    phases.append(Phase("Smoke & Bark", t_init, CP_STALL_START_F, t1))
    t2 = 0.0
    if t_eff > CP_STALL_END_F:
        t2_calc = phase_hours(km, l_in, t_eff, CP_STALL_START_F, CP_STALL_END_F)
        if math.isfinite(t2_calc) and t2_calc >= 0:
            t2 = t2_calc
    phases.append(Phase("Stall Plateau", CP_STALL_START_F, CP_STALL_END_F, t2))
    t3 = phase_hours(km, l_in, pit_f, CP_STALL_END_F, t_final)
    if not math.isfinite(t3):
        return None
    phases.append(Phase("Collagen Render", CP_STALL_END_F, t_final, t3))
    total = t1 + t2 + t3
    if total <= 0:
        return None
    return CookProjection(total, l_in, twb, tuple(phases))


def find_exact_temp(meat_key: str, weight_lbs: float, target_hours: float) -> float:
    """Binary search the pit temp that yields ~target_hours total cook time."""
    lo, hi = 150.0, 450.0
    for _ in range(80):
        mid = (lo + hi) / 2
        r = compute_at(meat_key, weight_lbs, mid)
        if r is None:
            lo = mid + 5
            continue
        if r.total_hours > target_hours:
            lo = mid
        elif r.total_hours < target_hours:
            hi = mid
        else:
            break
    return (lo + hi) / 2


def expected_probe_at(
    projection: CookProjection,
    elapsed_hours: float,
) -> float:
    """Interpolate expected probe temp from the projection at a given elapsed time.

    Linearly interpolates across each phase. Returns the final pull temp if
    elapsed exceeds total projected time.
    """
    if elapsed_hours <= 0:
        return projection.phases[0].start_internal_f
    cum = 0.0
    for ph in projection.phases:
        if elapsed_hours <= cum + ph.hours:
            if ph.hours <= 0:
                return ph.end_internal_f
            frac = (elapsed_hours - cum) / ph.hours
            return ph.start_internal_f + frac * (ph.end_internal_f - ph.start_internal_f)
        cum += ph.hours
    return projection.phases[-1].end_internal_f


def elapsed_at_probe(projection: CookProjection, probe_f: float) -> float:
    """Elapsed hours at which the projection expects the probe to read probe_f.
    Inverse of expected_probe_at; used for a live time-remaining that tracks the
    food's actual position on the curve."""
    first = projection.phases[0]
    if probe_f <= first.start_internal_f:
        return 0.0
    cum = 0.0
    for ph in projection.phases:
        if probe_f <= ph.end_internal_f:
            if ph.hours <= 0:
                return cum
            frac = (probe_f - ph.start_internal_f) / (ph.end_internal_f - ph.start_internal_f)
            return cum + max(0.0, min(1.0, frac)) * ph.hours
        cum += ph.hours
    return projection.total_hours


def phase_at(projection: CookProjection, probe_f: float, pull_f: int) -> str:
    """Classify the current cook phase from probe temp.

    Returns one of: 'pre_stall', 'stall', 'post_stall', 'single_phase',
    'approaching', 'pull_reached'.
    """
    if probe_f >= pull_f:
        return "pull_reached"
    if probe_f >= pull_f - 10:
        return "approaching"
    has_stall = any("Stall" in ph.name or "Render" in ph.name for ph in projection.phases)
    if not has_stall:
        return "single_phase"
    if probe_f < STALL_DETECT_LOW_F:
        return "pre_stall"
    if probe_f <= STALL_DETECT_HIGH_F:
        return "stall"
    return "post_stall"
