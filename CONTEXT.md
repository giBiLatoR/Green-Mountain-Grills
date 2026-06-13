# GMG Auto-Cook

Domain context for the Green Mountain Grills Home Assistant integration auto-cook feature — automated cook orchestration using physics-based heat diffusion modeling, probe feedback control, and SQLite session management.

## Language

### Cook Session
A single tracked cooking event from planning through completion. Has one meat type, one weight, one primary probe, and progresses through a state machine.
_Avoid_: Cook plan, recipe, job

### Pull Temp
The target internal meat temperature at which the cook is considered done (e.g., 203°F for pulled pork). Defined per meat type in the reference database.
_Avoid_: Target temp, done temp, finish temp — those are ambiguous with pit temp

### Pit Temp
The actual grill chamber temperature (`snapshot.grill_temp`). Distinct from pit setpoint.
_Avoid_: Grill temp (ambiguous with probe), smoker temp

### Pit Setpoint
The target temperature the grill is commanded to maintain (`snapshot.grill_set_temp` or via `UT###!` command).
_Avoid_: Target temp, desired temp — ambiguous with pull temp

### Projection Curve
The expected probe temperature trajectory over time, calculated from the physics-based heat diffusion model. Used to compare actual vs expected during cooking.
_Avoid_: Expected curve, cook timeline, schedule

### Phase
A distinct segment of the cook trajectory: `pre_stall`, `stall`, `post_stall`, or `single_phase` (for non-stall meats). Each phase has its own driving temperature and tolerance band for control adjustments.
_Avoid_: Stage, step — those imply user action rather than thermal behavior

### Stall
The evaporative cooling plateau where probe temperature stalls between **158°F–170°F** for an extended period. Detected when rate_of_change < 2°F per 30 minutes within this range for > 60 minutes.
_Avoid_: Plateau (too generic), the wall (community slang)

### Pre-Flight Check
Validation run before a cook session starts: grill reachability, probe plugged in, calculated bounds [150°F–375°F], max cook time guardrails, hopper level warning.
_Avoid_: Validation (too generic), safety check

### Cook Start Detection
The moment cooking begins, detected by a rapid **drop** in probe temperature (> 30°F within 1 minute) as the probe transitions from ambient chamber heat into cold meat.
_Avoid_: Meat insertion, cook begin — those are user actions we can't directly observe

### Pull Reached
State where probe temperature >= pull temp. Triggers notification to user. System does NOT change grill settings.
_Avoid_: Cook done (implies system action), complete

### Rate-Limited Adjustment
Pit setpoint changes governed by a proportional cooldown curve: smaller adjustments allowed more frequently, larger adjustments require longer wait times. Formula: `min_interval = 60 + ((adj_pct - 0.5) / 1.5) * 120` seconds, clamped between 0.5%–2.0% of target pit temp.
_Avoid_: Throttled control, PID adjustment

### Dev Mode
Optional development mode that logs every coordinator poll to SQLite during active cooks, enabling post-cook analysis and model calibration.
_Avoid_: Debug mode, logging mode — dev mode implies intentional data collection, not error debugging

## Relationships

- A **Cook Session** references exactly one meat type from the reference database and one HA config entry (grill).
- A **Cook Session** produces zero or more **Rate-Limited Adjustments** during its COOKING state.
- The **Projection Curve** is computed once at session creation from meat type + weight + calculated pit temp, then queried continuously during cooking.
- A **Phase** transition is detected from probe temperature behavior (stall entry/exit), not from elapsed time.
- The coordinator polls at the user-configured interval (default 15s) — this does NOT change during active cooks.
- One cook session per grill config entry at a time.

## Guardrails

| Rule | Value | Rationale |
|------|-------|-----------|
| Max pit setpoint | **375°F** | Safety clamp for unattended auto-cook. GMG hardware can go to 550°F but sustained high heat is dangerous. |
| Min pit setpoint | **150°F** | GMG hardware minimum and food safety (below this, meat sits in danger zone too long). |
| Pit error detection | Drop below **150°F** after being above **200°F** | Indicates grill failure (not lid opening — those recover within minutes). Triggers critical notification. |
| Max adjustment delta | **2%** of target pit temp | At 250°F = ±5°F. Prevents hunting and dangerous rapid temperature changes on live fire. |
| Min adjustment interval | **60s** at 0.5%, scaling to **180s** at 2.0% | Proportional cooldown prevents oscillation. |
| Absolute max cook hours | Per meat type (see below) | Pre-flight hard warning if calculated schedule exceeds these. User can override with confirmation. |

### Absolute Max Cook Hours by Meat Category

| Category | Max Hours | Rationale |
|----------|-----------|-----------|
| Chicken (all cuts) | 4h | Dries out, texture degradation |
| Turkey (whole/breast) | 8h | Quality drops past this |
| Pork chops / loin | 4h | Lean cuts dry out fast |
| Fish / salmon | 2h | Delicate protein |
| Sausage / brats | 3h | Already cooked, just warming |
| Ribs (all types) | 10h | Connective tissue over-breakdown |
| Beef brisket | 20h | Can go very long |
| Pork butt | 16h | Similar to brisket |
| Beef chuck / prime rib / tri-tip | 8h | Quality degradation |
| Lamb (shoulder/leg) | 10h | Shoulder like pork butt, leg leaner |

### Control Adjustment Rules

- **Never auto-power-off the grill.** Period. The system only adjusts pit setpoint and notifies.
- **Auto power-on is allowed** if grill is OFF when transitioning from PLANNED to PREHEATING.
- Asymmetric bias: adjust UP when behind schedule, but don't aggressively adjust DOWN when ahead (only reduce back to original calculated target).
- During stall phase: wider tolerance, minimal pit adjustments (evaporative cooling dominates regardless of setpoint).

## Cook Modes

`cook_mode` (select entity / `mode` service arg) selects how much control the
system takes. All three share the same state machine, projection curve, and
milestone notifications (grill-ready, approaching, pull-reached); they differ
only in whether the integration **writes to the grill**.

| Mode | Auto power-on | Sets pit at start | Ongoing pit adjustment | Off-schedule behavior |
|------|---------------|-------------------|------------------------|-----------------------|
| **autonomous** (default) | Yes | Yes | Yes — rate-limited proportional control | Adjusts the pit setpoint |
| **set_and_forget** | Yes | Yes | **No** | Leaves the grill alone after preheat |
| **coach** | **No** | **No** | **No** | Notifies the user to nudge the pit manually |

- **autonomous** is the full closed-loop controller (the original behavior).
- **set_and_forget** preheats and sets the calculated pit once, then only tracks
  and notifies — no further setpoint writes.
- **coach** never touches the grill at all. At start it tells the user what pit
  to dial in; during the cook, when the probe drifts more than
  `COACH_ADVISE_BAND_F` (8°F) from the projection it advises raising/lowering the
  pit, at most once every `COACH_ADVISE_INTERVAL_S` (15 min).

The hard guardrails (never auto-power-off, pit clamp, asymmetric bias) apply to
the modes that write; coach simply never writes.

## Meat-On Override

Cook Start Detection relies on a probe **drop** as the probe moves from hot
chamber air into cold meat. If the probe is already buried in cold meat before
the cook starts, no drop ever occurs. The **Meat is on** button
(`button.…_meat_on` → `CookManager.mark_meat_on`) is the manual override: pressed
during PLANNED / PREHEATING / WAITING_MEAT it forces the transition to COOKING
and stamps `cook_started_at` now.

## Display Units

Two options-flow preferences control how temperatures and weights are shown.
Both default to **auto** (follow the Home Assistant unit system).

- **temperature_unit** (`auto` / `celsius` / `fahrenheit`): the grill protocol is
  natively °F. When set to °C or °F, the integration forces that display unit on
  every GMG temperature entity (grill, probes, setpoints, cook-plan sensors) via
  the entity-registry unit override, and formats all notifications in that unit.
  `auto` clears the override so the entities follow the HA unit system. (The
  `climate` thermostat card always follows HA's global unit system — HA has no
  per-entity climate unit override; the sensor/number temperatures honor the
  toggle.)
- **weight_unit** (`auto` / `kilograms` / `pounds`): switches the cook-weight
  number entity's unit, bounds, and step, and the weight shown in notifications.
  Weight is always stored and computed canonically in kilograms; the
  `start_cook` helper normalizes the displayed value back to kg.

## State Machine

```
IDLE → PLANNED → PREHEATING → WAITING_MEAT → COOKING ↔ IN_STALL → APPROACHING → PULL_REACHED → COMPLETE
```

| Transition | Trigger | System Action |
|------------|---------|---------------|
| IDLE → PLANNED | User presses START COOK + confirms pre-flight | Create SQLite session, calculate projection curve |
| PLANNED → PREHEATING | Session created | Power on grill (if off), set pit setpoint to calculated target |
| PREHEATING → WAITING_MEAT | Pit temp reaches setpoint ±10°F sustained 3 min | Notify: "Grill ready, insert probe into meat" |
| WAITING_MEAT → COOKING | Probe drops >30°F in 1 minute (cook start detection) | Record cook_start_time, begin projection curve comparison |
| COOKING ↔ IN_STALL | Probe enters/exits 158°F–170°F with rate <2°F/30min for 60+ min | Adjust tolerance band; notify user stall status |
| COOKING → APPROACHING | Probe within 10°F of pull temp | Stop pit adjustments, notify "approaching pull" |
| APPROACHING → PULL_REACHED | Probe >= pull temp | Critical notification. No grill changes. |
| PULL_REACHED → COMPLETE | Probe removed (89°F sentinel) OR rapid probe drop OR grill turned off | Mark session complete, log summary if dev mode |

## Example dialogue

> **Dev:** "When do we stop adjusting the pit setpoint?"
> **Domain expert:** "Once **Pull Reached** fires — the probe hit target. We never touch the grill after that. Before that, during APPROACHING (within 10°F of pull), we also stop adjusting and just notify."

> **Dev:** "What if the chicken has been cooking for 5 hours?"
> **Domain expert:** "The **Pre-Flight Check** would have flagged it before starting — chicken max is 4h. If they overrode the warning, we keep monitoring. We don't enforce runtime limits because the meat might actually be fine."

> **Dev:** "How do we know the cook started?"
> **Domain expert:** "**Cook Start Detection** — the probe was sitting in hot ambient air during preheat (~250°F). When it drops into cold meat, temperature plunges >30°F in 1 minute. That drop is our trigger."

## Flagged ambiguities

- "open lid mode" was initially discussed as a feature but resolved to be **rate-limited adjustment guardrails** — preventing the system from overreacting to transient pit temp drops when the user opens the lid. The system uses the probe as primary comparison (thermal mass smooths out brief lid openings) and rate-limits all setpoint changes.
- "cook database" initially ambiguous between reference data only vs active session tracking. Resolved: SQLite stores both — reference meats table imported from `cook-database.json` AND active cook sessions with optional dev mode logging.
