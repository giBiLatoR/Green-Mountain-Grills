"""Smoke tests for CookManager pre-flight and rejection paths.

The full state machine requires a live coordinator + snapshots and is exercised
in HA integration tests separately. Here we only verify the synchronous parts.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from custom_components.gmg.cook_manager import (
    PIT_CLAMP_MAX_F,
    PIT_CLAMP_MIN_F,
    CookManager,
    CookManagerError,
    CookMode,
    CookSession,
    CookState,
    _ProbeSample,
)


@pytest.fixture
def manager() -> CookManager:
    """Build a CookManager without touching HA — only pre_flight is exercised."""
    hass = MagicMock()
    hass.config.path.return_value = "/tmp/test_gmg_cooks.db"  # noqa: S108
    coordinator = MagicMock()
    return CookManager(hass, coordinator)


def test_pre_flight_clamps_pit_target(manager: CookManager) -> None:
    """pit_target_f always lands in [150, 375]."""
    pf = manager.pre_flight(meat_key="beef_brisket_packer", weight_kg=5.0, finish_in_hours=20.0)
    assert PIT_CLAMP_MIN_F <= pf.pit_target_f <= PIT_CLAMP_MAX_F


def test_pre_flight_unknown_meat_raises(manager: CookManager) -> None:
    with pytest.raises(CookManagerError):
        manager.pre_flight(meat_key="bigfoot_jerky", weight_kg=2.0, finish_in_hours=5.0)


def test_pre_flight_zero_weight_raises(manager: CookManager) -> None:
    with pytest.raises(CookManagerError):
        manager.pre_flight(meat_key="whole_chicken", weight_kg=0.0, finish_in_hours=3.0)


def test_pre_flight_too_soon_raises(manager: CookManager) -> None:
    with pytest.raises(CookManagerError):
        manager.pre_flight(meat_key="whole_chicken", weight_kg=2.0, finish_in_hours=0.25)


def test_pre_flight_emits_max_hours_warning(manager: CookManager) -> None:
    """Chicken has max 4h; ask for an absurdly long projection."""
    pf = manager.pre_flight(meat_key="whole_chicken", weight_kg=3.0, finish_in_hours=10.0)
    # finish=10h forces a very low pit, projection will exceed chicken's 4h cap.
    assert any("max" in w for w in pf.warnings)


async def test_probe_drop_during_preheat_starts_cook(
    manager: CookManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Inserting the probe while still preheating should jump straight to COOKING."""
    manager.configure(auto_cook=True, dev_mode=False, push=False)
    monkeypatch.setattr(manager, "_notify", lambda **_kwargs: None)

    pf = manager.pre_flight(meat_key="whole_chicken", weight_kg=2.0, finish_in_hours=3.0)
    now = time.time()
    session = CookSession(
        state=CookState.PREHEATING,
        meat_key="whole_chicken",
        weight_kg=2.0,
        probe_index=1,
        mode=CookMode.AUTONOMOUS,
        pit_target_f=pf.pit_target_f,
        projection=pf.projection,
        created_at=now,
    )
    # Probe was reading hot grill air, then dropped on insertion into cold meat.
    session.probe_history = [_ProbeSample(now - 30, 200.0), _ProbeSample(now - 1, 55.0)]
    manager.session = session

    snapshot = MagicMock()
    snapshot.probe_1_temp = 55.0
    snapshot.probe_2_temp = None
    snapshot.grill_temp = 180.0  # still mid-preheat, below target

    await manager.update(snapshot)

    assert manager.session.state is CookState.COOKING
    assert manager.session.cook_started_at is not None
