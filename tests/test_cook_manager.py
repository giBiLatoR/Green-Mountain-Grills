"""Smoke tests for CookManager pre-flight and rejection paths.

The full state machine requires a live coordinator + snapshots and is exercised
in HA integration tests separately. Here we only verify the synchronous parts.
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.gmg.api import PowerState
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
from custom_components.gmg.units import TEMP_C


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


def _preheating_session(manager: CookManager, mode: CookMode) -> CookSession:
    """Build a PREHEATING session for control-loop tests."""
    pf = manager.pre_flight(meat_key="whole_chicken", weight_kg=2.0, finish_in_hours=3.0)
    return CookSession(
        state=CookState.PREHEATING,
        meat_key="whole_chicken",
        weight_kg=2.0,
        probe_index=1,
        mode=mode,
        pit_target_f=pf.pit_target_f,
        projection=pf.projection,
        created_at=time.time(),
    )


async def test_coach_mode_makes_no_grill_writes_on_start(
    manager: CookManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Coach start neither powers on nor sets the pit; it only advises."""
    manager.configure(auto_cook=True, dev_mode=False, push=False, temp_unit=TEMP_C)
    monkeypatch.setattr(manager, "_notify", lambda **_kwargs: None)
    manager.hass.async_add_executor_job = AsyncMock()
    manager.coordinator.async_power_on = AsyncMock()
    manager.coordinator.async_set_grill_temp = AsyncMock()

    snapshot = MagicMock()
    snapshot.power_state = PowerState.OFF
    snapshot.grill_set_temp = 180

    session = await manager.start_cook(
        meat_key="whole_chicken",
        weight_kg=2.0,
        probe_index=1,
        mode=CookMode.COACH,
        finish_in_hours=3.0,
        snapshot=snapshot,
    )

    manager.coordinator.async_power_on.assert_not_called()
    manager.coordinator.async_set_grill_temp.assert_not_called()
    assert session.state is CookState.PREHEATING


async def test_set_and_forget_does_not_adjust_pit(
    manager: CookManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Set-and-forget never adjusts the pit during cooking."""
    manager.configure(auto_cook=True, dev_mode=False, push=False)
    monkeypatch.setattr(manager, "_notify", lambda **_kwargs: None)
    manager.coordinator.async_set_grill_temp = AsyncMock()

    session = _preheating_session(manager, CookMode.SET_AND_FORGET)
    now = time.time()
    session.state = CookState.COOKING
    session.cook_started_at = now - 3600  # an hour in, behind schedule
    manager.session = session

    snapshot = MagicMock()
    snapshot.power_state = PowerState.ON
    snapshot.grill_temp = 225
    snapshot.grill_set_temp = 225
    snapshot.probe_1_temp = 80.0  # far behind expected
    snapshot.probe_2_temp = None

    await manager.update(snapshot)

    manager.coordinator.async_set_grill_temp.assert_not_called()


def test_mark_meat_on_starts_cook(manager: CookManager, monkeypatch: pytest.MonkeyPatch) -> None:
    """The meat-on override jumps a preheating session straight to COOKING."""
    monkeypatch.setattr(manager, "_notify", lambda **_kwargs: None)
    manager.session = _preheating_session(manager, CookMode.COACH)

    manager.mark_meat_on()

    assert manager.session.state is CookState.COOKING
    assert manager.session.cook_started_at is not None


def test_notifications_format_in_celsius(manager: CookManager) -> None:
    """_ftemp honors the configured temperature unit."""
    manager.configure(auto_cook=True, dev_mode=False, push=False, temp_unit=TEMP_C)
    assert manager._ftemp(212) == "100°C"
    manager.configure(auto_cook=True, dev_mode=False, push=False)  # default F
    assert manager._ftemp(212) == "212°F"
