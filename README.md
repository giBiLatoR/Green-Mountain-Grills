# Green Mountain Grills for Home Assistant — Auto Cook Fork

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![HA min version](https://img.shields.io/badge/Home%20Assistant-2026.1%2B-41BDF5.svg)](https://www.home-assistant.io/)

> ## ⚠️ WARNING — EXPERIMENTAL
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
- **Options**: scan interval slider (default `30` seconds; UI warns below `5`), plus Auto Cook enable/disable and dev mode toggle.

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
