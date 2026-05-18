# Handoff — GMG Auto Cook Implementation

**Date:** 2026-05-18  
**From:** Planning session agent  
**To:** Implementation agent  
**Repo:** `giBiLatoR/Green-Mountain-Grills` (fork of `HallyAus/Green-Mountain-Grills`)  
**Branch:** `claude/modernize-home-assistant-r61NC`  

---

## What has been done

The planning phase is complete. All design decisions have been grilled, resolved, and documented. **No integration code has been written yet.** The next agent should begin implementing the Auto Cook feature from scratch using the specifications below.

### Files committed (on branch)

| File | Purpose |
|------|---------|
| `CONTEXT.md` | Domain glossary, guardrails, state machine — **read this first** |
| `CLAUDE.md` | Behavioral guidelines for working on this codebase |
| `ARCHITECTURE.md` | Full upstream integration architecture deep dive (existing HA component) |
| `cook-database.json` | 97 reference cooks across 21 meat types with full phase data |
| `README.md` | Updated with fork notice, auto-cook feature description, new entity/service tables |
| `.gitignore` | Includes `.pi/`, local dev files (app.js, architecture.html, etc.) |

### Files in working tree but NOT committed (local reference only)

| File | Purpose |
|------|---------|
| `app.js` | Physics-based cook planner calculator — contains the heat diffusion model (`cpComputeAt`, `cpFindExactTemp`) and `CP_MEATS` lookup table. **This is the formula you need to port to Python.** |
| `smoking_formula_research.md` | Full analysis of the physics model, empirical fallback engine, and validation against published data. References every function in app.js with line numbers. |
| `architecture.html` | Interactive architecture viewer — includes an "Auto Cook Proposal" tab rendering the full design spec visually. |

### Upstream codebase (from fork)

The upstream integration (`custom_components/gmg/`) is fully functional and tested. Key files you'll interact with:

- `coordinator.py` — **extend this** to hook in cook management on each poll
- `config_flow.py` — add options flow toggle for enabling/disabling auto-cook + dev mode
- `sensor.py`, `binary_sensor.py`, `button.py`, `number.py` — extend with new entities
- `api/models.py` — data models and enums you'll reference (GMGSnapshot, PowerState, etc.)

---

## What needs to be built

### New Python modules

1. **`cook_manager.py`** — Core engine. Owns:
   - SQLite database lifecycle (init at setup, import meats from `cook-database.json`)
   - State machine transitions per the spec in CONTEXT.md
   - Projection curve calculation (port physics model from `app.js` to Python)
   - Control loop called post-poll on GMGCoordinator
   - Rate-limited pit setpoint adjustments
   - Notification dispatch

2. **SQLite schema** at `/config/gmg_cooks.db`:
   - `meats` — 21 canonical types from physics model + 97 reference entries
   - `cook_sessions` — active/recent cook state and calculated plans
   - `cook_log` — dev mode polling data (only when enabled)

### New entity platforms

3. **`select.py`** — Dropdown entities:
   - Cook meat type (populated from meats table)
   - Cook mode (set_and_forget / autonomous / coach)
   - Cook probe selection (probe 1 or probe 2)

4. Extend existing platforms with new entities (see README.md entity tables for full list):
   - `sensor.py` — cook state, phase, elapsed time, remaining time, expected probe temp
   - `binary_sensor.py` — on_schedule flag
   - `button.py` — start_cook, abort_cook
   - `number.py` — cook_weight_kg

### Coordinator integration

5. **Extend `coordinator.py`**:
   - Add `cook_manager` attribute (initialized in `async_setup_entry`)
   - Call `cook_manager.update(snapshot)` after each successful poll
   - Cook manager is disabled by default, enabled via options flow

### Options flow

6. **Update `config_flow.py`** — OptionsFlow:
   - Toggle: Enable/disable Auto Cook (default OFF)
   - Toggle: Dev mode logging (default OFF)
   - Toggle: Push notifications (default OFF)

### Services

7. **Extend `services.py`**:
   - `gmg.start_cook` — reads helper entities, runs pre-flight checks, creates session
   - `gmg.abort_cook` — cancels active cook

---

## Critical design decisions (all resolved, do not re-debate)

### Hard rules (non-negotiable)

- **NEVER auto-power-off the grill.** Period. System only adjusts pit setpoint and notifies.
- **Pit temp clamp: 150°F–375°F** for safety on unattended cooks.
- **Auto power-on IS allowed** if grill is OFF when transitioning PLANNED → PREHEATING.
- **Cook start detection = probe DROP > 15°F in 3 minutes** (not a rise — probe sits in hot ambient during preheat, drops into cold meat).

### Control algorithm

- Rate-limited adjustments: `min_interval = 60 + ((adj_pct - 0.5) / 1.5) * 120` seconds
- Max delta: ±2% of target pit temp (at 250°F = ±5°F)
- Asymmetric bias: raise when behind, don't aggressively reduce when ahead
- Phase tolerances: pre-stall ±7-8°F, stall ±3°F or no adjust, post-stall ±2-3°F

### Stall detection

- Range: **158°F–170°F** (not 150-165 from the physics model)
- Criteria: rate_of_change < 2°F per 30 minutes for > 60 minutes sustained

### Pre-flight warnings

- Two-layer validation: physics-derived max at 150°F AND absolute hard caps per meat type
- Warnings are overridable with user confirmation (never block the cook)

### Notifications

- Persistent notifications always on
- Push via options toggle, discovers mobile_app_* targets at startup
- Pull-reached repeats every 5 min for up to 30 min max

### Polling

- Coordinator keeps user-configured interval (default 30s). **DO NOT change it during active cooks.**

---

## Suggested skills for next session

1. **`tdd`** — Use test-driven development for the cook_manager module (physics model port, state machine transitions, control loop)
2. **`to-issues`** — Break implementation into tracer-bullet vertical slices if creating issues
3. **`diagnose`** — If anything doesn't work during integration testing

---

## First steps recommended

1. Read `CONTEXT.md` completely — it's the source of truth for all terminology and guardrails
2. Read `app.js` (the `CP_MEATS`, `cpComputeAt`, `cpPhase`, `cpFindExactTemp` functions) to understand the physics model you're porting
3. Start with `cook_manager.py` — get the SQLite schema working, import meats from JSON, implement the projection curve calculation in Python
4. Write tests for the physics calculations first (compare against known values from `smoking_formula_research.md`)
5. Wire into coordinator as a post-poll callback
6. Build entities one platform at a time
