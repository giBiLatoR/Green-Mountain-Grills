"""Auto-cook orchestration: state machine, SQLite persistence, control loop.

The CookManager owns one in-flight cook session per coordinator. It is driven
by GMGCoordinator post-poll. The state machine, guardrails, and control rules
follow CONTEXT.md (single source of truth).

Hard rules (never violated here):
  * Never auto-power-off the grill.
  * Pit setpoint clamped to [150°F, 375°F].
  * Auto power-on only on PLANNED→PREHEATING.
"""

from __future__ import annotations

import json

try:
    import sqlite3
except ModuleNotFoundError:  # Python build without the sqlite3 C extension
    sqlite3 = None  # type: ignore[assignment]
import time
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

from homeassistant.components import persistent_notification

from .api import GMGSnapshot, PowerState
from .const import LOGGER
from .cook_physics import (
    CP_MEATS,
    CookProjection,
    compute_at,
    expected_probe_at,
    find_exact_temp,
    phase_at,
)
from .units import TEMP_F, WEIGHT_KG, fmt_temp, fmt_weight

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .coordinator import GMGCoordinator

# Guardrails (CONTEXT.md) ----------------------------------------------------
PIT_CLAMP_MIN_F = 150
PIT_CLAMP_MAX_F = 375
COOK_START_DROP_F = 30  # Probe drop trigger for cook-start detection.
COOK_START_WINDOW_S = 60  # Within 1 minute.
PREHEAT_BAND_F = 10  # Pit within ±10°F of setpoint.
PREHEAT_HOLD_S = 180  # Sustained 3 min.
APPROACHING_BAND_F = 10  # Within 10°F of pull.
MAX_DELTA_PCT = 0.02  # ±2% of pit target per adjustment.
MIN_ADJ_INTERVAL_BASE_S = 60  # 60s at 0.5% scaling to 180s at 2.0%.
ADJ_INTERVAL_SPAN_S = 120
PIT_ERROR_TRIP_F = 200  # Was above this, dropped below 150 → fail.
PROBE_UNPLUGGED_SENTINEL_F = 89  # Probe pulled from meat.
DB_FILENAME = "gmg_cooks.db"
COACH_ADVISE_BAND_F = 8  # Coach mode advises when off-schedule by this much.
COACH_ADVISE_INTERVAL_S = 900  # …at most once every 15 min.


class CookState(StrEnum):
    """State-machine states (CONTEXT.md)."""

    IDLE = "idle"
    PLANNED = "planned"
    PREHEATING = "preheating"
    WAITING_MEAT = "waiting_meat"
    COOKING = "cooking"
    APPROACHING = "approaching"
    PULL_REACHED = "pull_reached"
    COMPLETE = "complete"
    ABORTED = "aborted"


class CookMode(StrEnum):
    """User-selectable behavior modes."""

    SET_AND_FORGET = "set_and_forget"
    AUTONOMOUS = "autonomous"
    COACH = "coach"


@dataclass(slots=True)
class _ProbeSample:
    ts: float
    probe_f: float


@dataclass(slots=True)
class CookSession:
    """In-memory state of one cook session."""

    state: CookState
    meat_key: str
    weight_kg: float
    probe_index: int
    mode: CookMode
    pit_target_f: int
    projection: CookProjection
    created_at: float
    preheat_started_at: float | None = None
    preheat_ready_since: float | None = None
    cook_started_at: float | None = None
    last_adj_at: float = 0.0
    last_pit_set_f: int = 0
    pull_reached_at: float | None = None
    last_pull_notify_at: float = 0.0
    probe_history: list[_ProbeSample] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass(slots=True)
class PreFlightResult:
    """Outcome of the pre-flight validation pass."""

    ok: bool
    pit_target_f: int
    projection: CookProjection
    warnings: tuple[str, ...]


class CookManagerError(Exception):
    """Base class for cook-manager errors."""


class CookManager:
    """Owns SQLite, the in-memory cook session, and control loop bookkeeping.

    All SQLite IO is wrapped in hass.async_add_executor_job so the event loop
    is never blocked.
    """

    def __init__(self, hass: HomeAssistant, coordinator: GMGCoordinator) -> None:
        """Initialize the cook manager."""
        self.hass = hass
        self.coordinator = coordinator
        self.session: CookSession | None = None
        self._db_path: Path = Path(hass.config.path(DB_FILENAME))
        self._auto_cook_enabled = False
        self._dev_mode = False
        self._push_enabled = False
        # Upper pit clamp; overridden from options. Never exceeds PIT_CLAMP_MAX_F.
        self._max_pit_f = PIT_CLAMP_MAX_F
        # Resolved display units for notifications ("C"/"F", "kg"/"lb").
        self._temp_unit = TEMP_F
        self._weight_unit = WEIGHT_KG

    # --- lifecycle ----------------------------------------------------------

    def configure(
        self,
        *,
        auto_cook: bool,
        dev_mode: bool,
        push: bool,
        max_pit_f: int = PIT_CLAMP_MAX_F,
        temp_unit: str = TEMP_F,
        weight_unit: str = WEIGHT_KG,
    ) -> None:
        """Refresh option-flow flags (called by coordinator on options update)."""
        self._auto_cook_enabled = auto_cook
        self._dev_mode = dev_mode
        self._push_enabled = push
        # Honor the user's ceiling, but never above the hard safety cap.
        self._max_pit_f = max(PIT_CLAMP_MIN_F, min(PIT_CLAMP_MAX_F, int(max_pit_f)))
        self._temp_unit = temp_unit
        self._weight_unit = weight_unit

    def _ftemp(self, value_f: float | None) -> str:
        """Format a Fahrenheit value for notifications in the chosen unit."""
        return fmt_temp(value_f, self._temp_unit)

    def _fweight(self, value_kg: float | None) -> str:
        """Format a kilogram value for notifications in the chosen unit."""
        return fmt_weight(value_kg, self._weight_unit)

    async def async_init_db(self) -> None:
        """Create schema and import meat reference data if missing."""
        if sqlite3 is None:
            LOGGER.warning(
                "sqlite3 is unavailable on this Python build; "
                "Auto Cook history and sessions are disabled"
            )
            return
        await self.hass.async_add_executor_job(self._init_db_sync)

    def _init_db_sync(self) -> None:
        conn = sqlite3.connect(self._db_path)
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS meats (
                    key TEXT PRIMARY KEY,
                    label TEXT NOT NULL,
                    pull_f INTEGER NOT NULL,
                    stall INTEGER NOT NULL,
                    foil INTEGER NOT NULL,
                    rest_min INTEGER NOT NULL,
                    max_hours REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS cook_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    serial TEXT NOT NULL,
                    meat_key TEXT NOT NULL,
                    weight_kg REAL NOT NULL,
                    probe_index INTEGER NOT NULL,
                    mode TEXT NOT NULL,
                    pit_target_f INTEGER NOT NULL,
                    projection_json TEXT NOT NULL,
                    state TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    cook_started_at REAL,
                    pull_reached_at REAL,
                    completed_at REAL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS cook_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id INTEGER NOT NULL,
                    ts REAL NOT NULL,
                    pit_f INTEGER,
                    pit_set_f INTEGER,
                    probe_f INTEGER,
                    state TEXT,
                    FOREIGN KEY(session_id) REFERENCES cook_sessions(id)
                )
                """
            )
            # Always upsert canonical meats from the in-process model so any
            # add/remove ships with the integration.
            for m in CP_MEATS.values():
                conn.execute(
                    """
                    INSERT INTO meats(key,label,pull_f,stall,foil,rest_min,max_hours)
                    VALUES(?,?,?,?,?,?,?)
                    ON CONFLICT(key) DO UPDATE SET
                        label=excluded.label,
                        pull_f=excluded.pull_f,
                        stall=excluded.stall,
                        foil=excluded.foil,
                        rest_min=excluded.rest_min,
                        max_hours=excluded.max_hours
                    """,
                    (m.key, m.label, m.pull_f, int(m.stall), int(m.foil), m.rest_min, m.max_hours),
                )
            conn.commit()
        finally:
            conn.close()

    # --- planning -----------------------------------------------------------

    def pre_flight(
        self,
        *,
        meat_key: str,
        weight_kg: float,
        finish_in_hours: float,
    ) -> PreFlightResult:
        """Validate parameters and compute a pit target + projection.

        Warnings are advisory (cook may proceed). Errors raise CookManagerError.
        """
        meat = CP_MEATS.get(meat_key)
        if meat is None:
            raise CookManagerError(f"unknown meat key: {meat_key}")
        if weight_kg <= 0:
            raise CookManagerError("weight must be > 0 kg")
        if finish_in_hours <= 0.5:
            raise CookManagerError("finish time too soon (>0.5h required)")
        weight_lbs = weight_kg * 2.20462
        cook_hrs = finish_in_hours - (meat.rest_min / 60) - 0.5
        if cook_hrs <= 0.25:
            raise CookManagerError("not enough cook time after rest + preheat budget")
        pit_target = find_exact_temp(meat_key, weight_lbs, cook_hrs)
        pit_target = max(PIT_CLAMP_MIN_F, min(self._max_pit_f, round(pit_target)))
        projection = compute_at(meat_key, weight_lbs, pit_target)
        if projection is None:
            raise CookManagerError("physics model failed to converge")

        warnings: list[str] = []
        if projection.total_hours > meat.max_hours:
            warnings.append(
                f"projected {projection.total_hours:.1f}h exceeds {meat.label} "
                f"max {meat.max_hours:.1f}h"
            )
        # Two-layer guardrail per HANDOFF: also check physics-derived max at 150°F.
        slow = compute_at(meat_key, weight_lbs, PIT_CLAMP_MIN_F)
        if slow is not None and slow.total_hours < projection.total_hours:
            warnings.append(
                f"computed pit target slower than the {self._ftemp(PIT_CLAMP_MIN_F)} "
                "floor — review inputs"
            )

        return PreFlightResult(
            ok=True,
            pit_target_f=int(pit_target),
            projection=projection,
            warnings=tuple(warnings),
        )

    async def start_cook(
        self,
        *,
        meat_key: str,
        weight_kg: float,
        probe_index: int,
        mode: CookMode,
        finish_in_hours: float,
        snapshot: GMGSnapshot,
    ) -> CookSession:
        """Create a session and transition PLANNED → PREHEATING."""
        if sqlite3 is None:
            raise CookManagerError(
                "Auto Cook requires the sqlite3 module, which is unavailable on this Python build"
            )
        if self.session is not None and self.session.state not in (
            CookState.COMPLETE,
            CookState.ABORTED,
            CookState.IDLE,
        ):
            raise CookManagerError("a cook is already in progress")
        if probe_index not in (1, 2):
            raise CookManagerError("probe_index must be 1 or 2")

        pf = self.pre_flight(
            meat_key=meat_key,
            weight_kg=weight_kg,
            finish_in_hours=finish_in_hours,
        )
        now = time.time()
        session = CookSession(
            state=CookState.PLANNED,
            meat_key=meat_key,
            weight_kg=weight_kg,
            probe_index=probe_index,
            mode=mode,
            pit_target_f=pf.pit_target_f,
            projection=pf.projection,
            created_at=now,
            last_pit_set_f=snapshot.grill_set_temp,
        )
        self.session = session
        await self.hass.async_add_executor_job(self._insert_session_sync, session)

        label = CP_MEATS[meat_key].label
        target = pf.pit_target_f
        proj_h = pf.projection.total_hours
        if mode is CookMode.COACH:
            # Coach never touches the grill — it only advises the user.
            session.state = CookState.PREHEATING
            session.preheat_started_at = now
            self._notify(
                title="Auto-Cook (coach) started",
                message=(
                    f"{label} ({self._fweight(weight_kg)}) — power on the grill and set the "
                    f"pit to {self._ftemp(target)}. Projected {proj_h:.1f}h. I'll track "
                    f"progress and advise, but I won't change the grill."
                ),
            )
        else:
            # PLANNED → PREHEATING: auto power-on permitted here only.
            if snapshot.power_state is PowerState.OFF:
                try:
                    await self.coordinator.async_power_on()
                except Exception:  # noqa: BLE001 — broad to never break user start
                    LOGGER.exception("auto power-on failed at PLANNED→PREHEATING")
            await self._set_pit_target(target, reason="preheat")
            session.state = CookState.PREHEATING
            session.preheat_started_at = now
            self._notify(
                title="Auto-Cook started",
                message=(
                    f"{label} ({self._fweight(weight_kg)}) — preheating to "
                    f"{self._ftemp(target)}. Projected {proj_h:.1f}h."
                ),
            )
        if pf.warnings:
            self._notify(
                title="Auto-Cook pre-flight warnings",
                message="; ".join(pf.warnings),
            )
        return session

    async def abort_cook(self) -> None:
        """Cancel any active session. Does NOT power off the grill."""
        if self.session is None:
            return
        self.session.state = CookState.ABORTED
        await self.hass.async_add_executor_job(self._complete_session_sync, self.session, "aborted")
        self._notify(title="Auto-Cook aborted", message="Session cancelled.")
        self.session = None

    # --- per-poll loop ------------------------------------------------------

    async def update(self, snapshot: GMGSnapshot) -> None:  # noqa: C901, PLR0912, PLR0915
        """Run the control loop once after a successful poll."""
        if not self._auto_cook_enabled or self.session is None:
            return
        session = self.session
        now = time.time()
        probe_f = snapshot.probe_1_temp if session.probe_index == 1 else snapshot.probe_2_temp
        if probe_f is not None:
            session.probe_history.append(_ProbeSample(now, float(probe_f)))
            # Bound history to recent samples to keep memory + scan cheap.
            if len(session.probe_history) > 240:
                session.probe_history = session.probe_history[-240:]

        if self._dev_mode:
            await self.hass.async_add_executor_job(
                self._log_sample_sync, session, snapshot, probe_f
            )

        # Grill failure trip — pit dropped from hot to below safe floor.
        if (
            session.state
            in (
                CookState.PREHEATING,
                CookState.WAITING_MEAT,
                CookState.COOKING,
                CookState.APPROACHING,
            )
            and snapshot.grill_temp < PIT_CLAMP_MIN_F
            and self._was_above(session, PIT_ERROR_TRIP_F)
        ):
            self._notify(
                title="Auto-Cook: grill failure suspected",
                message=f"Pit dropped to {self._ftemp(snapshot.grill_temp)}. Check grill.",
                critical=True,
            )

        # State transitions ------------------------------------------------
        if session.state is CookState.PREHEATING:
            # Short-on-time path: a sharp probe drop during preheat means the
            # meat went on before the grill settled — start cooking right away
            # instead of waiting for the "grill ready" prompt.
            if self._detect_cook_start(session):
                session.state = CookState.COOKING
                session.cook_started_at = now
                self._notify(
                    title="Cook started",
                    message="Meat detected during preheat — tracking now.",
                )
                return
            if abs(snapshot.grill_temp - session.pit_target_f) <= PREHEAT_BAND_F:
                if session.preheat_ready_since is None:
                    session.preheat_ready_since = now
                elif now - session.preheat_ready_since >= PREHEAT_HOLD_S:
                    session.state = CookState.WAITING_MEAT
                    self._notify(
                        title="Grill ready",
                        message=f"At {self._ftemp(snapshot.grill_temp)} — insert probe into meat.",
                    )
            else:
                session.preheat_ready_since = None
            return

        if session.state is CookState.WAITING_MEAT:
            if self._detect_cook_start(session):
                session.state = CookState.COOKING
                session.cook_started_at = now
                self._notify(
                    title="Cook started",
                    message="Probe drop detected. Tracking projection.",
                )
            return

        if session.state in (CookState.COOKING, CookState.APPROACHING):
            pull_f = CP_MEATS[session.meat_key].pull_f
            if probe_f is not None:
                if probe_f >= pull_f:
                    session.state = CookState.PULL_REACHED
                    session.pull_reached_at = now
                    self._notify(
                        title="Pull temp reached",
                        message=(
                            f"Probe at {self._ftemp(probe_f)} (target {self._ftemp(pull_f)})."
                        ),
                        critical=True,
                    )
                    return
                if probe_f >= pull_f - APPROACHING_BAND_F and session.state is CookState.COOKING:
                    session.state = CookState.APPROACHING
                    self._notify(
                        title="Approaching pull",
                        message=(
                            f"Approaching the {self._ftemp(pull_f)} pull target. "
                            "No further pit adjustments."
                        ),
                    )
            # Control only during COOKING (not APPROACHING), and only in the
            # modes that permit it: autonomous adjusts the grill; coach advises
            # the user; set-and-forget leaves the grill alone after preheat.
            if session.state is CookState.COOKING and probe_f is not None:
                if session.mode is CookMode.AUTONOMOUS:
                    await self._maybe_adjust_pit(session, snapshot, probe_f, now)
                elif session.mode is CookMode.COACH:
                    self._maybe_advise_pit(session, probe_f, now)
            return

        if session.state is CookState.PULL_REACHED:
            # Notify repeatedly (up to 30 min) — every 5 min.
            elapsed_since_pull = now - (session.pull_reached_at or now)
            if elapsed_since_pull <= 1800 and now - session.last_pull_notify_at >= 300:
                session.last_pull_notify_at = now
                self._notify(
                    title="Pull temp reached",
                    message=f"Probe {self._ftemp(probe_f)} — pull the meat.",
                )
            # Completion: probe sentinel or rapid drop or grill off.
            if (
                snapshot.power_state is PowerState.OFF
                or probe_f is None
                or probe_f <= PROBE_UNPLUGGED_SENTINEL_F
            ):
                session.state = CookState.COMPLETE
                await self.hass.async_add_executor_job(
                    self._complete_session_sync, session, "complete"
                )
                self._notify(title="Cook complete", message="Session closed.")
                self.session = None

    # --- control helpers ----------------------------------------------------

    def _detect_cook_start(self, session: CookSession) -> bool:
        """Probe DROP > 30°F within 1 min."""
        hist = session.probe_history
        if len(hist) < 2:
            return False
        cutoff = hist[-1].ts - COOK_START_WINDOW_S
        recent = [s for s in hist if s.ts >= cutoff]
        if len(recent) < 2:
            return False
        return (recent[0].probe_f - recent[-1].probe_f) >= COOK_START_DROP_F

    def _was_above(self, session: CookSession, threshold_f: float) -> bool:
        # Cheap heuristic: was pit at any point near projected target?
        return session.last_pit_set_f >= threshold_f

    async def _maybe_adjust_pit(
        self,
        session: CookSession,
        snapshot: GMGSnapshot,
        probe_f: float,
        now: float,
    ) -> None:
        """Asymmetric, rate-limited proportional pit-setpoint adjustment."""
        if session.cook_started_at is None:
            return
        elapsed_h = (now - session.cook_started_at) / 3600
        expected = expected_probe_at(session.projection, elapsed_h)
        delta = expected - probe_f  # > 0 = behind schedule
        phase = phase_at(session.projection, probe_f, CP_MEATS[session.meat_key].pull_f)
        # Tolerance per phase
        tol = 7.0
        if phase == "stall":
            tol = 3.0
            # During stall, suppress most adjustments.
            if abs(delta) < 5:
                return
        elif phase in ("post_stall", "single_phase"):
            tol = 3.0
        if abs(delta) < tol:
            return

        # Asymmetric: when ahead (delta < 0), only relax back toward original target.
        target = session.pit_target_f
        max_delta = max(1.0, MAX_DELTA_PCT * target)
        if delta > 0:
            adjust = min(max_delta, delta * 0.5)
            new_set = min(self._max_pit_f, snapshot.grill_set_temp + round(adjust))
        else:
            # Ahead: only step down toward original target.
            if snapshot.grill_set_temp <= target:
                return
            adjust = min(max_delta, snapshot.grill_set_temp - target)
            new_set = max(target, snapshot.grill_set_temp - round(adjust))

        adj_pct = abs(new_set - snapshot.grill_set_temp) / max(target, 1)
        min_interval = MIN_ADJ_INTERVAL_BASE_S + ((adj_pct - 0.005) / 0.015) * ADJ_INTERVAL_SPAN_S
        min_interval = max(
            MIN_ADJ_INTERVAL_BASE_S,
            min(min_interval, MIN_ADJ_INTERVAL_BASE_S + ADJ_INTERVAL_SPAN_S),
        )
        if now - session.last_adj_at < min_interval:
            return
        if new_set == snapshot.grill_set_temp:
            return
        await self._set_pit_target(int(new_set), reason=f"adjust ({phase})")
        session.last_adj_at = now

    def _maybe_advise_pit(self, session: CookSession, probe_f: float, now: float) -> None:
        """Coach mode: notify the user to nudge the pit, but never write to it."""
        if session.cook_started_at is None:
            return
        elapsed_h = (now - session.cook_started_at) / 3600
        expected = expected_probe_at(session.projection, elapsed_h)
        delta = expected - probe_f  # > 0 = behind schedule
        if abs(delta) < COACH_ADVISE_BAND_F:
            return
        if now - session.last_adj_at < COACH_ADVISE_INTERVAL_S:
            return
        session.last_adj_at = now
        if delta > 0:
            self._notify(
                title="Coach: running behind",
                message=(
                    f"Probe {self._ftemp(probe_f)} vs expected {self._ftemp(expected)}. "
                    "Consider raising the pit setpoint."
                ),
            )
        else:
            self._notify(
                title="Coach: ahead of schedule",
                message=(
                    f"Probe {self._ftemp(probe_f)} vs expected {self._ftemp(expected)}. "
                    f"Consider lowering the pit toward {self._ftemp(session.pit_target_f)}."
                ),
            )

    def mark_meat_on(self) -> None:
        """User override: the probe is in the meat — begin tracking now.

        Covers the case where the probe was already buried in cold meat before
        the cook started, so no probe-drop event ever fires (see HANDOFF).
        """
        session = self.session
        if session is None:
            self._notify(
                title="Meat-on ignored",
                message="No active cook session to apply 'meat is on' to.",
            )
            return
        if session.state not in (
            CookState.PLANNED,
            CookState.PREHEATING,
            CookState.WAITING_MEAT,
        ):
            return
        session.state = CookState.COOKING
        session.cook_started_at = time.time()
        session.preheat_ready_since = None
        self._notify(
            title="Cook started",
            message="Meat-on override — tracking the cook now.",
        )

    async def _set_pit_target(self, pit_f: int, *, reason: str) -> None:
        clamped = max(PIT_CLAMP_MIN_F, min(self._max_pit_f, pit_f))
        try:
            await self.coordinator.async_set_grill_temp(clamped)
        except Exception:  # noqa: BLE001 — control loop must not crash poll
            LOGGER.exception("pit setpoint write failed (%s)", reason)
            return
        if self.session is not None:
            self.session.last_pit_set_f = clamped
            self.session.notes.append(f"{reason}: {clamped}°F")

    # --- SQLite helpers (executor-bound) ------------------------------------

    def _insert_session_sync(self, session: CookSession) -> int:
        conn = sqlite3.connect(self._db_path)
        try:
            cur = conn.execute(
                """
                INSERT INTO cook_sessions(
                    serial, meat_key, weight_kg, probe_index, mode,
                    pit_target_f, projection_json, state, created_at
                ) VALUES (?,?,?,?,?,?,?,?,?)
                """,
                (
                    self.coordinator.info.serial,
                    session.meat_key,
                    session.weight_kg,
                    session.probe_index,
                    str(session.mode),
                    session.pit_target_f,
                    json.dumps(
                        {
                            "total_hours": session.projection.total_hours,
                            "phases": [
                                {
                                    "name": p.name,
                                    "start_f": p.start_internal_f,
                                    "end_f": p.end_internal_f,
                                    "hours": p.hours,
                                }
                                for p in session.projection.phases
                            ],
                        }
                    ),
                    str(session.state),
                    session.created_at,
                ),
            )
            conn.commit()
            return cur.lastrowid or 0
        finally:
            conn.close()

    def _complete_session_sync(self, session: CookSession, final_state: str) -> None:
        conn = sqlite3.connect(self._db_path)
        try:
            conn.execute(
                """
                UPDATE cook_sessions SET state=?, completed_at=?, pull_reached_at=?
                WHERE id=(SELECT MAX(id) FROM cook_sessions WHERE serial=?)
                """,
                (final_state, time.time(), session.pull_reached_at, self.coordinator.info.serial),
            )
            conn.commit()
        finally:
            conn.close()

    def _log_sample_sync(
        self,
        session: CookSession,
        snapshot: GMGSnapshot,
        probe_f: float | None,
    ) -> None:
        conn = sqlite3.connect(self._db_path)
        try:
            row = conn.execute(
                "SELECT MAX(id) FROM cook_sessions WHERE serial=?",
                (self.coordinator.info.serial,),
            ).fetchone()
            session_id = row[0] if row and row[0] else 0
            conn.execute(
                """
                INSERT INTO cook_log(session_id, ts, pit_f, pit_set_f, probe_f, state)
                VALUES (?,?,?,?,?,?)
                """,
                (
                    session_id,
                    time.time(),
                    snapshot.grill_temp,
                    snapshot.grill_set_temp,
                    int(probe_f) if probe_f is not None else None,
                    str(session.state),
                ),
            )
            conn.commit()
        finally:
            conn.close()

    # --- notifications ------------------------------------------------------

    def _notify(self, *, title: str, message: str, critical: bool = False) -> None:
        nid = f"gmg_cook_{self.coordinator.info.serial}"
        persistent_notification.async_create(
            self.hass,
            message=message,
            title=title,
            notification_id=nid,
        )
        LOGGER.info("[auto-cook] %s — %s", title, message)
        if self._push_enabled:
            self._dispatch_push(title=title, message=message, critical=critical)

    def _dispatch_push(self, *, title: str, message: str, critical: bool) -> None:
        # Discover mobile_app_* notify services at fire-time; safe if none exist.
        services = self.hass.services.async_services().get("notify", {})
        for svc in services:
            if not svc.startswith("mobile_app_"):
                continue
            data = {"title": title, "message": message}
            if critical:
                data["data"] = {"push": {"sound": "default"}}
            self.hass.async_create_task(
                self.hass.services.async_call("notify", svc, data, blocking=False)
            )
