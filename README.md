# Green Mountain Grills for Home Assistant — Auto Cook Fork

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![HA min version](https://img.shields.io/badge/Home%20Assistant-2026.1%2B-41BDF5.svg)](https://www.home-assistant.io/)

> ## ⚠️ WARNING — HIGHLY EXPERIMENTAL
>
> **This fork is experimental and under active development.** The Auto Cook feature automatically controls your pellet grill's temperature based on sensor readings. While safety guardrails are in place (maximum pit temperature clamp, rate-limited adjustments), this software can make real-world changes to a device involving live fire and high heat.
>
> **Use at your own risk.** Always monitor your grill during use. Do not leave your home while an automated cook is running until you have thoroughly tested and verified the system in your environment. The authors accept no liability for property damage, injury, or food loss resulting from the use of this integration.

> ## Fork Notice — Auto Cook Feature
>
> This is a **feature fork** of [hallyaus/Green-Mountain-Grills](https://github.com/hallyaus/Green-Mountain-Grills), the original upstream integration. All core grill control, monitoring, and protocol logic is credited to and maintained by **[hallyaus](https://github.com/hallyaus)**.
>
> This fork adds an **Auto Cook** subsystem — automated cook orchestration using physics-based heat diffusion modeling, probe feedback control, and SQLite session management. The feature is designed as a self-contained extension that does not modify the upstream core integration.
>
> ### What Auto Cook Does
>
> - **Three modes**: Set &amp; Forget (monitor + notify), Autonomous (active pit temp adjustment with rate limiting), Coach (human-in-the-loop guidance at phase boundaries)
> - **Physics-based scheduling**: Calculates optimal smoker temperature from meat type, weight, and desired finish time using transient heat conduction — no hardcoded per-pound estimates. Works backward from your dinner time to tell you exactly when to start.
> - **Probe feedback control**: Compares actual probe temperature against a projected trajectory curve in real time. Makes small, rate-limited pit setpoint adjustments (max ±2% of target, cooldown 60–180s) to keep the cook on schedule. Never powers off the grill.
> - **Cook start detection**: Detects when meat hits the grill by monitoring for a rapid probe temperature drop during preheat — no manual "start" button needed after initial setup.
> - **Stall awareness**: Recognizes the evaporative cooling plateau (158–170°F) and switches to appropriate tolerance bands automatically.
> - **Safety guardrails**: Hard pit temp clamp at 375°F, asymmetric adjustment bias (raise when behind, don't aggressively reduce when ahead), pre-flight warnings for out-of-range cook times with per-meat-type maximums.
> - **Development mode logging**: Optional SQLite logging of every poll cycle during active cooks for post-cook analysis and model calibration.
>
> ### Quick Start
>
> 1. Install this fork via HACS (or manual install from `custom_components/gmg/`)
> 2. Set up your grill as normal through the integration config flow
> 3. Enable Auto Cook in the integration options (disabled by default)
> 4. Use the Auto Cook entities (meat type selector, weight input, finish time picker) and press **Start Cook**
> 5. The system handles preheat, cook start detection, phase monitoring, and pull notifications automatically
>
> See [CONTEXT.md](CONTEXT.md) for full domain terminology, guardrails, state machine, and resolved design decisions.
>
> ---

Control and monitor Green Mountain Grills WiFi-enabled pellet smokers
directly from Home Assistant - locally, over your own LAN, with no cloud
dependency.

**Fork maintained by [giBiLatoR](https://github.com/giBiLatoR). Original integration by [hallyaus](https://github.com/hallyaus).**

![GMG auto-cook overlay](docs/preview-overlay.png)

*The auto-cook overlay: phase, live grill/probe temperatures, and a heating glow.
A neutral silhouette ships by default — your model's artwork loads automatically.*

## What this fork adds — the interface

The upstream integration by **[hallyaus](https://github.com/hallyaus)** gives you
rock-solid **local control**: a climate entity, temperature / probe / fault
sensors, power and cold-smoke buttons, LAN + DHCP discovery, and diagnostics —
all over your own network, no cloud. This fork keeps every bit of that and adds
a **cooking interface** on top:

- **Auto-Cook controller** — tell it the meat, the weight, and when you want to
  eat; a heat-diffusion model picks the pit temperature and keeps the cook on
  schedule with small, rate-limited nudges. It never powers the grill off by
  itself.
- **One-line dashboard** — a bundled Lovelace strategy (`custom:gmg-smoker`)
  auto-builds the smoker view from your device: the picture overlay above,
  context-aware controls, **Pace** (ahead/behind), an **ETA clock**, and a
  *Cook Progress vs Plan* graph. No entity IDs to wire.
- **Per-model artwork** — the overlay shows your grill's silhouette, auto-picked
  by model.
- **Safety & polish** — a configurable **maximum grill temperature** and
  natural-language meat names ("Pork Butt — Pulled Pork", not `pork_butt_pulled`).

## Setup

1. **Install the integration.**
   - *HACS:* HACS → ⋮ → *Custom repositories* → add
     `https://github.com/giBiLatoR/Green-Mountain-Grills` (category
     *Integration*) → install **Green Mountain Grills** → **restart Home
     Assistant**.
   - *Manual:* copy `custom_components/gmg/` into your HA `config/custom_components/`
     folder and **restart Home Assistant**.
2. **Add your grill.** Settings → Devices & Services → **Add Integration** →
   *Green Mountain Grills*. It scans the LAN (UDP `8080`) and lists any grills
   found; or enter the IP manually. The grill must be on local WiFi, **not
   Server Mode** (toggle that in the GMG app).
3. **Set a temperature ceiling** *(optional, recommended).* On the integration
   tile → **Configure** → **Maximum grill temperature**. Caps the manual setpoint
   *and* Auto-Cook so the grill is never told to run hotter than your unit can.
4. **Enable Auto-Cook** *(optional).* Same **Configure** dialog → tick **Enable
   Auto Cook**. (Off by default; the cook phase stays *idle* until it's on.)
5. **Add the dashboard.** Make a new view in YAML mode and paste:
   ```yaml
   strategy:
     type: custom:gmg-smoker
     # serial: GMG12137138   # only if you have more than one grill
     # show_graph: false     # set if you don't run apexcharts-card
   ```
   For the heating glow and the progress graph, install the HACS cards
   [`card-mod`](https://github.com/thomasloven/lovelace-card-mod) and
   [`apexcharts-card`](https://github.com/RomRider/apexcharts-card).
6. **Add your model's photo** *(optional).* Drop a transparent PNG named
   `<model_id>.png` into `custom_components/gmg/static/models/` — picked up
   automatically (see [the model table](#prebuilt-dashboard-auto-strategy)).
7. **Restart once** after first install so the dashboard assets register.

A full walkthrough of an actual cook is in
[Using Auto Cook, start to finish](#using-auto-cook-start-to-finish).

## How it works (the simple version)

Think of your pellet grill as an oven that burns little wood pellets to make heat and smoke. This add-on talks to the grill over your home WiFi (no internet or cloud needed) and does two jobs:

1. **Watch.** Every few seconds it asks the grill how things are going: how hot the fire box is, how hot the meat is (that's the *probe* — a thermometer you stick in the food), how many pellets are left, and whether anything is wrong. Those readings become the tiles and the glowing smoker picture you see on your dashboard.

2. **Drive — "Auto Cook" (a.k.a. Cruise Control).** You tell it three things: *what* meat, *how heavy*, and *what time you want to eat*. A physics model — the same kind of maths that describes how heat slowly soaks into food — figures out how hot to run the grill and when dinner will actually be ready. While it cooks, it keeps checking the meat's real temperature against where it *should* be by now, and nudges the grill a little hotter or cooler to stay on schedule. It does this gently, and it will **never shut the fire off by itself**.

### Cook modes (what they're *meant* to do)

| Mode | Idea |
|------|------|
| **Set & Forget** | Just watch and tell you what's happening — send notifications at each stage, but let *you* turn the dials. |
| **Autonomous** | Drive the grill itself — make small, rate-limited setpoint nudges to keep the food on its schedule. |
| **Coach** | Meet in the middle — pause at the big moments (preheat done, stall, almost-there) and suggest what to do, you decide. |

> **Heads-up (current code):** the mode you pick is saved with the cook, but the
> control loop doesn't branch on it yet — right now every mode runs the same
> active-adjustment + notify logic. Wiring the three behaviours apart is a
> planned change; until then, treat the selector as a label.

### Reading the cook on your dashboard

- **Auto Start Temp** — the grill temperature the physics model chose for this
  cook (`cook_pit_target`). This is the "estimated start temperature."
- **Pace** — are we ahead or behind? It compares the food's real temperature to
  where the projection says it *should* be: 🟢 on track, 🔵 ahead, 🔴 behind,
  with the gap in °F.
- **Cook Progress vs Plan** — an [apexcharts](https://github.com/RomRider/apexcharts-card)
  graph of **Food Actual vs Food Expected** (plus grill and pit setpoint), so
  you can see the real curve tracking the planned curve in real time.

The cook moves through stages, like steps in a recipe:

**Preheat** (get hot) → **Waiting for meat** (it notices the temperature dip when you put cold food on) → **Cooking** → **Approaching** (almost done) → **Pull!** (it tells you to take the meat off).

The stage it's on right now is the **"phase"** shown on your dashboard. If the phase says *idle*, no auto-cook is running yet — you start one with the **Start Auto-Cook** button after turning Cruise Control on.

## Features

### Core Integration (upstream)

- Full **climate** entity for the grill with setpoint, current temperature,
  HVAC mode, preset for Cold Smoke, and on/off control.
- **Sensor** entities for grill temperature, probe 1, probe 2, profile time
  remaining, firmware version, signal warnings, and the last-warn code.
- **Binary sensor** entities for flame-on, low-pellet, fan / auger / ignitor
  faults, and Cold Smoke active.
- **Number** entities for probe 1 and probe 2 targets, with the correct
  150-550 degF / 32-257 degF ranges.
- **Button** entities for Power On, Power Off, and Cold Smoke.
- **Services** for setting setpoints, targeting probes, and starting Cold
  Smoke, all exposed in the Developer Tools service picker.
- Built-in **diagnostics** download for issue reporting.
- **Repair issues** for the most common failure modes - notably the
  Server Mode interlock - with clickable fix-flows.
- Full **translations** scaffolding (English ships in-box; others are
  populated as community translations land).
- Targets the **Platinum** Home Assistant integration quality scale: strict
  typing, async-only, full config flow, options flow, reconfigure flow,
  DHCP discovery, and comprehensive test coverage.

### Auto Cook (this fork)

- **Select** entities for meat type (21 cuts from physics model), cook mode, and probe selection
- **Sensor** entities for cook state machine, current phase, elapsed/remaining time, expected vs actual probe temp
- **Binary sensor** for on-schedule tracking
- **Button** entities for Start Cook and Abort Cook
- **Number** entity for cook weight input (kg)
- SQLite session management at `/config/gmg_cooks.db` with reference meat database imported from [cook-database.json](cook-database.json)

## Supported models

See [docs/MODELS.md](docs/MODELS.md) for the full controller matrix.

## Installation

See [docs/INSTALL.md](docs/INSTALL.md) for step-by-step instructions,
including how to disable Server Mode in the GMG mobile app.

## Configuration

The integration has no YAML configuration; everything is set up through the
UI.

- **Auto-discovery** broadcasts on UDP `8080` and lists every grill that
  responds.
- **DHCP discovery** offers a one-click setup when Home Assistant sees a
  matching MAC prefix on the network.
- **Manual entry** is available for routed networks where broadcast
  discovery is not viable.
- **Options**: scan interval slider (default `15` seconds; UI warns below `5`),
  a **Maximum grill temperature** slider (see below), plus Auto Cook
  enable/disable, dev mode, and push-notification toggles.

## Entities

### Core Integration

| Platform        | Entity                                | Notes                                                   |
|-----------------|---------------------------------------|---------------------------------------------------------|
| `climate`       | Grill                                 | Setpoint 150-550 degF, Cold Smoke preset.               |
| `sensor`        | Grill temperature                     | degF / degC (HA unit system).                           |
| `sensor`        | Probe 1 / Probe 2                     | `None` when unplugged (89 degF sentinel).               |
| `sensor`        | Probe 1 target / Probe 2 target       | Echoes setpoint.                                        |
| `sensor`        | Profile time remaining                | Seconds.                                                |
| `sensor`        | Hopper percent (diagnostic)           | Only reported by some firmwares.                        |
| `sensor`        | Firmware version (diagnostic)         |                                                         |
| `sensor`        | Last warn code (diagnostic)           |                                                         |
| `binary_sensor` | Flame on                              |                                                         |
| `binary_sensor` | Low pellets                           |                                                         |
| `binary_sensor` | Fan / auger / ignitor fault           | One per fault class.                                    |
| `binary_sensor` | Cold Smoke active                     |                                                         |
| `number`        | Probe 1 target / Probe 2 target       | 32-257 degF.                                            |
| `number`        | Grill setpoint                        | 150-550 degF.                                           |
| `button`        | Power On                              |                                                         |
| `button`        | Power Off                             |                                                         |
| `button`        | Cold Smoke                            |                                                         |

### Auto Cook (this fork)

| Platform        | Entity                                | Notes                                                   |
|-----------------|---------------------------------------|---------------------------------------------------------|
| `select`        | Cook meat type                        | 21 cuts from physics model.                             |
| `select`        | Cook mode                             | Set &amp; Forget / Autonomous / Coach.                  |
| `select`        | Cook probe                            | Probe 1 (default) or Probe 2.                           |
| `number`        | Cook weight                           | Weight in kg.                                           |
| `sensor`        | Cook state                            | State machine value (PLANNED, PREHEATING, COOKING...).  |
| `sensor`        | Cook phase                            | pre_stall / stall / post_stall / single_phase.          |
| `sensor`        | Cook elapsed time                     | Duration since cook start detection.                    |
| `sensor`        | Cook remaining time                   | Estimated minutes to pull temp.                         |
| `sensor`        | Cook expected probe temp              | From physics projection curve at current elapsed time.  |
| `binary_sensor` | Cook on schedule                      | Within phase tolerance band or not.                     |
| `button`        | Start cook                            | Runs pre-flight checks, creates session.                |
| `button`        | Abort cook                            | Cancels active cook session.                            |

## Services

### Core Integration

| Service                  | Fields                                | Notes                                  |
|--------------------------|---------------------------------------|----------------------------------------|
| `gmg.set_grill_temp`     | `entity_id`, `temperature`            | 150-550 degF.                          |
| `gmg.set_probe_target`   | `entity_id`, `probe` (1 or 2), `temperature` | 32-257 degF.                    |
| `gmg.power_on`           | `entity_id`                           |                                        |
| `gmg.power_off`          | `entity_id`                           |                                        |
| `gmg.cold_smoke`         | `entity_id`                           | Equivalent to power-on with profile.   |

### Auto Cook (this fork)

| Service                  | Fields                                | Notes                                  |
|--------------------------|---------------------------------------|----------------------------------------|
| `gmg.start_cook`         | Reads from cook helper entities       | Runs pre-flight, creates session.      |
| `gmg.abort_cook`         | `entity_id`                           | Cancels active cook.                   |

## Automation examples

### Notify when the grill reaches its setpoint

```yaml
automation:
  - alias: "Grill reached setpoint"
    triggers:
      - trigger: numeric_state
        entity_id: sensor.gmg_grill_temperature
        above: 224
    conditions:
      - condition: state
        entity_id: binary_sensor.gmg_flame_on
        state: "on"
    actions:
      - action: notify.mobile_app
        data:
          message: "Grill is up to temp - load the meat."
```

### Alert on low pellets

```yaml
automation:
  - alias: "GMG low pellets"
    triggers:
      - trigger: state
        entity_id: binary_sensor.gmg_low_pellets
        to: "on"
        for: "00:01:00"
    actions:
      - action: notify.mobile_app
        data:
          message: "GMG hopper is low - top it up before the next session."
```

### Auto-off when meat probe hits its target

```yaml
automation:
  - alias: "GMG auto-off on probe done"
    triggers:
      - trigger: numeric_state
        entity_id: sensor.gmg_probe_1
        above: 164
    actions:
      - action: button.press
        target:
          entity_id: button.gmg_power_off
      - action: notify.mobile_app
        data:
          message: "Probe 1 hit target. Grill is shutting down."
```

### Pre-heat on a schedule

```yaml
automation:
  - alias: "GMG pre-heat at 17:00"
    triggers:
      - trigger: time
        at: "17:00:00"
    actions:
      - action: button.press
        target:
          entity_id: button.gmg_power_on
      - delay: "00:00:30"
      - action: climate.set_temperature
        target:
          entity_id: climate.gmg_grill
        data:
          temperature: 225
```

## Prebuilt dashboard (auto-strategy)

The integration ships a **Lovelace auto-strategy** that builds a full smoker
view for you — a picture-overlay of the grill, the auto-cook controls, and a
progress graph — with **no entity IDs to wire up**. It finds your GMG device
automatically and resolves every entity by its registry key, so it keeps
working even if you rename things, and it shows temperatures in *your* unit
system (°C or °F) without any conversion hacks.

**Add it as a view.** Edit a dashboard → ⋮ → *Edit in YAML* (or add a new view
in YAML mode) and use:

```yaml
strategy:
  type: custom:gmg-smoker
  # serial: GMG12137138   # optional — only needed if you have >1 grill
  # show_graph: false     # optional — set false if you don't run apexcharts-card
```

Or make a whole dashboard out of it (Settings → Dashboards → Add → *Take
control* is not needed; in YAML):

```yaml
strategy:
  type: custom:gmg-smoker
```

**How it loads.** The integration serves its assets at `/gmg_static/` and
registers the strategy automatically on startup — no manual “Resources” entry.
A one-time **restart** is needed after first install so the new frontend asset
is registered.

**Optional HACS cards** for the full look (the view still renders without them):
- [`card-mod`](https://github.com/thomasloven/lovelace-card-mod) — the heating glow
- [`apexcharts-card`](https://github.com/RomRider/apexcharts-card) — the
  *Cook Progress vs Plan* graph (omit it with `show_graph: false`)

**Overlay images.** A neutral smoker silhouette ships as the default. To use a
real picture of your model, drop a **transparent PNG named `<model_id>.png`**
into `custom_components/gmg/static/models/` — it is then picked up
**automatically**, no code edit needed. The `model_id` values:

| id | model | id | model | id | model |
|----|-------|----|-------|----|-------|
| 0 | Davy Crockett | 6 | Ledge Prime+ | 12 | Jim Bowie Prime+ |
| 1 | Trek | 7 | Peak Prime+ | 13 | Daniel Boone Prime 2.0 |
| 2 | Daniel Boone | 8 | Trek Prime 2.0 | 14 | Jim Bowie Prime 2.0 |
| 3 | Jim Bowie | 9 | Ledge Prime 2.0 | 15 | Trek Prime+ |
| 4 | Ledge | 10 | Peak Prime 2.0 | | |
| 5 | Peak | 11 | Daniel Boone Prime+ | | |

So a Jim Bowie owner saves their cut-out PNG as `static/models/3.png`. These
are the WiFi-capable models the local protocol supports. (The integration does
not ship product photos — they're copyright GMG; supply your own transparent
PNGs.)

> This strategy is **experimental**. It does not depend on any personal helper
> entities — contrast with the hand-built popup below, which uses extra HACS
> cards and a couple of custom `input_boolean` / template-sensor helpers.

## Dashboard & phone popup

The companion dashboards drive everything from a single **`#smoker` popup**
(a [bubble-card](https://github.com/Clooos/Bubble-Card) pop-up) that appears on
both the **PHONES** and **Primary** dashboards. Inside the popup:

- **Smoker picture** — a `picture-elements` card overlaid on a photo of the
  grill. It shows the **phase**, live **grill** and **probe** temperatures (in
  °F), a power button, a spinning fan when it's running, and warning/low-pellet
  badges. The whole card glows red while heating.
- **Smoker Controls** — one `entities` card that changes with context:
  - **Cruise Control off** → manual targets (grill setpoint, probe targets).
  - **Cruise Control on + idle** → the Auto Cook setup (meat, mode, primary
    probe, weight, finish-in-hours) and a **▶ Start Auto-Cook** button.
  - **Cruise Control on + cooking** → a live read-out (phase, meat, on-schedule,
    elapsed, time remaining, estimated ready-at clock, pit target, probe
    now/expected, pull target) and a **■ Abort Cook** button.

Temperatures from the integration are reported in your Home Assistant unit
system (°C here in metric land), so the dashboards convert to °F with
`× 1.8 + 32`. Two template helpers, `sensor.gmg_grill_temp_f` and
`sensor.gmg_probe_1_temp_f`, do this for the picture overlay.

> **Tip — "Est. Ready At" should be a clock, not a countdown that creeps.**
> Build it from the integration's `cook_remaining_minutes` sensor
> (`now() + remaining`), **not** from the finish-in-hours *input*. The input is
> a fixed number, so `now() + finish_in_hours` slides forward by a minute every
> minute. Using the remaining-minutes sensor keeps the clock steady.

### Using Auto Cook, start to finish

A full cook, step by step:

1. **Turn Auto Cook on once.** Settings → Devices & Services → Green Mountain
   Grills → **Configure** → tick **Enable Auto Cook**, then Submit. (The
   per-poll control loop does nothing while this is off, so the cook phase never
   leaves *idle*. You only need to do this once.)
2. **Set your inputs.** On the dashboard turn **Cruise Control** on, then pick:
   - **Meat type** (21 cuts), **Cook mode**, **Primary probe** (1 or 2)
   - **Meat weight** (kg) and **Finish in** (hours from now you want to eat)
3. **Press ▶ Start Auto-Cook.** The integration runs a pre-flight check, picks
   the **start temperature** (shown as *Auto Start Temp*), powers the grill on,
   and begins **preheating**.
4. **Load the meat once the grill is hot.** When you push the cold probe into
   the meat, its reading craters — that ~30°F-in-a-minute **drop** is how the
   system knows the cook has started. (If the probe is already buried in the
   meat and only rising, it can't see a drop and will sit in *waiting for meat*.
   Briefly lift the probe into the open grill, then re-seat it in the meat to
   create the drop.)
5. **Watch it track.** The dashboard now shows **Pace** (🟢/🔵/🔴 ahead or
   behind), **Time Remaining**, **Est. Ready At**, and the **Cook Progress vs
   Plan** graph (food actual vs. the projected curve). The controller makes
   small, rate-limited grill nudges to stay on schedule — it never powers the
   grill off on its own.
6. **Pull when it says so.** At the target temperature you get a notification to
   take the meat off. Done.

### Setting a maximum grill temperature

Different grills top out at different temperatures, and you may simply not want
yours run hot. The **Maximum grill temperature** option (Configure → slider, in
°F) is a single ceiling that applies everywhere:

- the **manual** temperature control (climate card + grill-setpoint number) won't
  let you set higher than it, and
- the **Auto Cook** controller is clamped to it too (bounded by a hard 375°F
  safety cap), so the physics model can never ask for more than your grill can
  give.

Example: if your grill realistically maxes out around 300°F, set the slider to
**300**. Nothing — manual or automatic — will command it past that. The default
is 375°F.

> **Heads-up:** changing options **reloads the integration**, which clears any
> in-progress Auto Cook session (the session lives in memory only). Set your
> ceiling **between cooks**, not in the middle of one.

### Recent fixes (2026-06)

- Synced `translations/en.json` with `strings.json`. The stale copy left the
  Auto Cook entities unnamed, so Home Assistant fell back to collision IDs like
  `select.gmg_gmg12137138_2`. Entities now get their proper IDs
  (`select.gmg_gmg12137138_cook_meat_type`, `button.gmg_gmg12137138_start_cook`,
  `sensor.gmg_gmg12137138_cook_state`, …).
- Hardened `async_start_cook_from_helpers` to resolve helper entities by
  registry **unique_id** instead of hard-coded entity IDs, so a future rename
  can't break the Start Cook button.
- Fixed the dashboard "Est. Finish Time" so it no longer creeps forward (now
  uses `cook_remaining_minutes`).
- Added a **Maximum grill temperature** option that caps both the manual
  setpoint and the Auto Cook controller (see above).

## Troubleshooting

See the troubleshooting tree in [docs/INSTALL.md](docs/INSTALL.md). The
single most common cause of "no devices found" is the grill being in Server
Mode; the second is a VLAN that does not forward UDP broadcasts.

To collect a debug bundle:

1. Enable debug logging for the integration (`logger:` block in
   `configuration.yaml`).
2. Reproduce the issue.
3. Download diagnostics from the integration's device page.
4. Open an issue with both.

## Development / contributing

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.test.txt
ruff check .
ruff format --check .
mypy custom_components/gmg
pytest
```

CI runs the same commands on every push and pull request. Pull requests
should add or update tests for any behavioural change.

## License

[MIT](LICENSE). Core integration copyright 2026 hallyaus. Auto Cook extension copyright 2026 giBiLatoR.
