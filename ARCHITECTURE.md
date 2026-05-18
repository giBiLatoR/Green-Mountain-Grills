# Green Mountain Grills Home Assistant Integration — Architecture Deep Dive

## Overview

The **Green Mountain Grills (GMG)** integration is a Home Assistant custom component that provides local, cloud-free control and monitoring of WiFi-enabled GMG pellet smokers over the LAN. It communicates via a proprietary UDP protocol on port `8080` with no TLS or authentication — purely local broadcast/unicast datagrams.

- **Domain:** `gmg`
- **Version:** 1.0.0
- **Target HA version:** 2026.1+
- **Quality Scale Target:** Platinum
- **IoT Class:** `local_polling`
- **License:** MIT

---

## High-Level Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                        Home Assistant                            │
│                                                                  │
│  ┌─────────────┐    ┌──────────────────┐                        │
│  │  Config Flow │───▶│   GMGCoordinator  │                       │
│  │  (scan/      │    │                  │                        │
│  │   manual/    │    │  DataUpdateCoord.│◀── Poll every N sec   │
│  │   dhcp)      │    │  (timed polling) │     via GMGClient     │
│  └─────────────┘    └────────┬─────────┘                        │
│                              │                                   │
│              ┌───────────────┼───────────────┐                   │
│              ▼               ▼               ▼                   │
│    ┌─────────────┐ ┌──────────┐ ┌────────┐  │ ...other platforms │
│    │   Climate   │ │  Sensor  │ │ Binary │  │                    │
│    │   Entity    │ │ Entities │ │Sensor  │  │                    │
│    │ (grill ctrl)│ │(temps,   │ │Entities│  │                    │
│    └─────────────┘ │ states)  │ │(faults)│  │                    │
│                    └──────────┘ └────────┘                     │
│                                                                  │
│  ┌─────────────┐    ┌──────────┐    ┌──────────┐                │
│  │   Number    │    │  Button  │    │ Services │                │
│  │  Entities   │    │ Entities │    │ (probe/  │                │
│  │(setpoints)  │    │(power on/off/cold smoke) │  refresh)      │
│  └─────────────┘    └──────────┘    └──────────┘                │
├──────────────────────────────────────────────────────────────────┤
│                         API Layer                                │
│                                                                  │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐             │
│  │ GMGClient   │  │ Protocol    │  │ Discovery   │             │
│  │ (UDP socket)│  │ Parser/Enc. │  │ (broadcast) │             │
│  └──────┬──────┘  └─────────────┘  └─────────────┘             │
│         │                                                        │
├─────────┼────────────────────────────────────────────────────────┤
│         │ UDP/8080 (raw datagrams, no TLS)                       │
│         ▼                                                        │
│  ┌─────────────────┐                                            │
│  │ GMG Grill WiFi  │                                            │
│  │ Controller      │                                            │
│  │ (Prime / Prime+ │                                            │
│  │  / Prime 2.0)   │                                            │
│  └─────────────────┘                                            │
└──────────────────────────────────────────────────────────────────┘
```

---

## Layer Breakdown

### 1. API Layer (`custom_components/gmg/api/`)

The lowest layer — pure protocol logic with no Home Assistant dependencies.

#### `client.py` — GMGClient

- **Role:** Async UDP client facade for a single grill at `(host, port)`.
- **Pattern:** Each request opens/closes its own `asyncio.DatagramEndpoint` (ephemeral sockets). No long-lived connections.
- **Concurrency:** Uses an internal `asyncio.Lock()` to serialize all commands — the controller is single-threaded and can't handle concurrent requests.
- **Retry Logic:** Up to 5 retries with 1-second timeout per attempt.
- **Key Methods:**

| Method | Command | Response | Purpose |
|--------|---------|----------|---------|
| `async_poll()` | `UR001!` | 36-byte binary frame | Full status snapshot |
| `async_probe()` | `UL!`, `UN!`, `UR001!` | ASCII + binary | Get serial, firmware, model |
| `async_set_grill_temp(f)` | `UT###!` | Status frame | Set grill setpoint (150-550°F) |
| `async_set_probe_target(p, f)` | `UF###!` / `Uf###!` | Status frame | Set probe target (32-257°F) |
| `async_power_on()` | `UK001!` | Status frame | Power on grill |
| `async_power_off()` | `UK004!` | Status frame | Power off grill |
| `async_cold_smoke()` | `UK002!` | Status frame | Cold smoke mode |

#### `protocol.py` — Frame Parsing & Encoding

- **Role:** Pure functions for parsing the 36-byte little-endian binary status frame and encoding ASCII commands.
- **Status Frame Layout:**

| Offset | Length | Field | Type |
|--------|--------|-------|------|
| 0 | 2 | Header (`UR`) | bytes |
| 2 | 2 | Grill temperature (°F) | uint16 LE |
| 4 | 2 | Probe 1 temp (89 = unplugged) | uint16 LE |
| 6 | 2 | Grill setpoint (°F) | uint16 LE |
| 8 | 1 | API version | uint8 |
| 9 | 3 | Build info | bytes |
| 12 | 2 | Probe 2 temp | uint16 LE |
| 14 | 2 | Probe 2 setpoint | uint16 LE |
| 16 | 4 | Profile time remaining (s) | uint32 LE |
| 20 | 4 | Warn code | uint32 LE |
| 24 | 2 | Probe 1 setpoint | uint16 LE |
| 26 | 1 | Power state | uint8 |
| 27 | 1 | Grill mode | uint8 |
| 28 | 1 | Fire state | uint8 |
| 29 | 1 | Hopper % | uint8 |
| 30 | 1 | Profile end byte | uint8 |
| 31 | 1 | Grill type (model ID) | uint8 |
| 32 | 4 | Reserved | bytes |

- **Model Mapping:** 16 known grill types mapped by `grill_type` byte → human-readable names (Davy Crockett, Trek Prime 2.0, etc.)

#### `discovery.py` — UDP Broadcast Discovery

- Sends `UL!` to `255.255.255.255:8080` with `SO_BROADCAST`.
- Listens for 1-2 seconds; any reply starting with `GMG` is a grill.
- Deduplicates by source IP.

#### `models.py` — Data Classes & Enums

| Type | Values | Purpose |
|------|--------|---------|
| `PowerState` (IntEnum) | OFF(0), ON(1), FAN(2), COLD_SMOKE(3) | Power byte at offset 26 |
| `FireState` (IntEnum) | DEFAULT-OFF-STARTUP-RUNNING-COOL_DOWN-FAIL, COLD_SMOKE(198) | Fire byte at offset 28 |
| `WarnCode` (IntEnum) | NONE through LOW_PELLET(8); 128 is alias | Warning byte at offset 20 |
| `GMGSnapshot` (dataclass) | 23 fields | Parsed view of one status frame |
| `GMGGrillInfo` (dataclass) | host, serial, firmware, model, snapshot | Identity from probe |
| `DiscoveredGrill` (dataclass) | host, serial | From broadcast discovery |

#### `exceptions.py` — Exception Hierarchy

```
GMGError (base)
├── GMGConnectionError
│   ├── GMGTimeoutError
│   └── GMGServerModeError  ← grill in cloud mode, not reachable locally
├── GMGProtocolError        ← malformed frame / wrong header
└── GMGInvalidValueError    ← out-of-range setpoint (also ValueError)
```

#### `const.py` — Protocol Constants

Command bytes (`UR001!`, `UL!`, `UN!`, `UK001!`, etc.), port defaults, timeouts, temperature ranges.

---

### 2. Integration Core Layer

#### `__init__.py` — Entry Point

- **`async_setup()`** → Registers domain-wide services (`gmg.set_probe_target`, `gmg.refresh`).
- **`async_setup_entry()`** → Creates `GMGClient` + `GMGCoordinator`, does first refresh, then forwards to all 5 platforms.
- **`async_unload_entry()`** → Unloads platforms, closes client, removes services if no entries remain.
- **`async_migrate_entry()`** → Stub for future config entry migrations.

#### `coordinator.py` — GMGCoordinator (DataUpdateCoordinator)

- Extends HA's `DataUpdateCoordinator[GMGSnapshot]`.
- **Polling Interval:** Configurable via options flow (default 15s, range 5-600s).
- **`_async_setup()`:** Probes the grill once; raises `ConfigEntryNotReady` if Server Mode detected.
- **`_async_update_data()`:** Polls with 10-second timeout; creates repair issues for persistent Server Mode errors.
- **Command Methods:** `async_set_grill_temp`, `async_set_probe_target`, `async_power_on/off`, `async_cold_smoke` — all go through `_call()` which maps API exceptions to HA exceptions and triggers a refresh after success.

#### `config_flow.py` — Configuration & Options Flows

| Flow | Steps | Purpose |
|------|-------|---------|
| **ConfigFlow** | `user` → menu (scan/manual) | Initial setup |
| | `scan` → UDP discovery → select grill | LAN auto-discovery |
| | `manual` → host/port form | Manual IP entry |
| | `dhcp` → probe → confirm | DHCP-based auto-discovery |
| | `reconfigure` → new host/port | Update after IP change |
| **OptionsFlow** | `init` → scan interval slider | Change polling frequency |

- All flows probe the grill before creating/updating entries.
- Unique ID is the grill serial number — survives IP changes.
- Server Mode errors abort with actionable messages.

---

### 3. Entity Layer (5 Platforms)

All entities extend `GMGBaseEntity` which provides:
- Device info binding (serial, model, firmware, manufacturer)
- Availability check (coordinator has data)

#### `climate.py` — GMGGrillClimate

| Property | Source |
|----------|--------|
| `hvac_mode` | OFF → power OFF; HEAT → power ON; FAN_ONLY → cold smoke |
| `hvac_action` | HEATING → fire RUNNING; IDLE → fan/startup/cool-down; OFF → rest |
| `current_temperature` | `snapshot.grill_temp` |
| `target_temperature` | `snapshot.grill_set_temp` |

- Supports: TARGET_TEMPERATURE, TURN_ON, TURN_OFF
- Temperature snapped to 5°F grid on set.

#### `sensor.py` — 9 Sensors

| Sensor | Device Class | Category | Notes |
|--------|-------------|----------|-------|
| Grill temperature | TEMPERATURE | Default | Always enabled |
| Probe 1/2 temp | TEMPERATURE | Default | None when unplugged (89°F sentinel) |
| Power state | ENUM | Default | off/on/fan/cold_smoke |
| Fire state | ENUM | Default | default/off/startup/running/cool_down/fail/cold_smoke |
| Warning code | ENUM | DIAGNOSTIC | All WarnCode values |
| Hopper % | MEASUREMENT (%) | DIAGNOSTIC | Disabled by default — unreliable on many firmwares |
| Firmware version | None | DIAGNOSTIC | From probe info |
| Model | None | DIAGNOSTIC | Disabled by default |

Uses `GMGSensorDescription` pattern with `value_fn` lambdas.

#### `binary_sensor.py` — 10 Binary Sensors

| Sensor | Device Class | Category | Notes |
|--------|-------------|----------|-------|
| Low pellet | PROBLEM | Default | WarnCode 8 or 128 |
| Fan/auger/ignitor overload | PROBLEM | DIAGNOSTIC | From warn code |
| Low voltage | BATTERY | DIAGNOSTIC | From warn code |
| Fan/auger/ignitor disconnect | PROBLEM | DIAGNOSTIC | Disabled by default |
| Flame on | HEAT | Default | fire_state == RUNNING |
| Cooking | RUNNING | Default | power_state != OFF |

#### `number.py` — 3 Number Entities

| Entity | Range | Step | Purpose |
|--------|-------|------|---------|
| Grill setpoint | 150-550°F | 5 | Set grill target temperature |
| Probe 1 target | 32-257°F | 1 | Meat probe 1 doneness target |
| Probe 2 target | 32-257°F | 1 | Meat probe 2 doneness target |

All use `BOX` mode. Write goes through coordinator → API client.

#### `button.py` — 3 Buttons

| Button | Command | Purpose |
|--------|---------|---------|
| Power On | `UK001!` | Start the grill |
| Power Off | `UK004!` | Shut down the grill |
| Cold Smoke | `UK002!` | Engage cold smoke mode (fan only, no heat) |

---

### 4. Services Layer (`services.py`)

Two domain services registered at integration startup:

| Service | Parameters | Purpose |
|---------|-----------|---------|
| `gmg.set_probe_target` | config_entry_id, probe (1/2), temperature (32-257°F) | Set meat probe target via Developer Tools |
| `gmg.refresh` | config_entry_id | Force immediate state poll |

Resolved by config entry ID — works across all grills.

---

### 5. Supporting Infrastructure

#### `entity.py` — GMGBaseEntity

Common base for all platform entities. Sets up `DeviceInfo` with identifiers, manufacturer, model, firmware version, and configuration URL.

#### `diagnostics.py`

Redacted diagnostics dump: config entry data/options, grill identity, full snapshot (minus raw bytes). Used for issue reporting.

#### `strings.json` / `translations/en.json`

Full translation scaffolding for all UI strings: config flow steps, entity names/states, exceptions, issues, and service descriptions.

#### `icons.json`

Material Design Icons for every entity with state-aware icon switching (e.g., fire icon changes based on fire state).

#### `services.yaml`

Service picker definitions for the Developer Tools panel.

#### `manifest.json`

- Domain: `gmg`, Name: "Green Mountain Grills"
- DHCP discovery via hostname pattern `gmg-*`
- After dependencies: `dhcp`, `network`
- Quality scale: platinum target

---

### 6. Testing & CI/CD

#### Test Suite (`tests/`)

| File | Coverage | Key Tests |
|------|----------|-----------|
| `conftest.py` | Fixtures | Mock config entry, grill info, client with all methods mocked |
| `test_protocol.py` | API layer | Frame parsing (baseline, sentinel, low pellet, cold smoke), command encoding, validation boundaries |
| `test_init.py` | Integration lifecycle | Setup success, retry on connection error, unload cleanup |
| `test_config_flow.py` | Config flows | User flow (menu→manual, errors, server mode, already configured), DHCP discovery (create + update), reconfigure, options |

#### CI Workflows (`.github/workflows/`)

| Workflow | Tools | Triggers |
|----------|-------|----------|
| `lint.yml` | ruff check + format | push/PR to main |
| `test.yml` | pytest with coverage | push/PR to main |
| `validate.yml` | hassfest + HACS validation | push/PR/scheduled daily/manual |

---

### 7. Quality Scale Compliance

The integration targets **Platinum** quality:

- ✅ All Bronze rules (config flow, entity setup, unique IDs, runtime data, polling)
- ✅ All Silver rules (unloading, diagnostics, device info, parallel updates, test coverage)
- ✅ All Gold rules (discovery, reconfiguration flow, repair issues, icon/entity translations)
- ✅ Platinum: async-only dependency, strict typing via mypy

**Exemptions:**
- `brands` — PR to home-assistant/brands pending
- `reauthentication-flow` — No auth in local protocol; reconfigure handles address changes
- `inject-websession` — Protocol is raw UDP, no HTTP
- `dynamic-devices` / `stale-devices` — One grill per entry

---

## Data Flow: Setting Temperature End-to-End

```
User clicks climate.set_temperature in HA UI
    │
    ▼
GMGGrillClimate.async_set_temperature()
    │  (snaps to 5°F grid)
    ▼
GMGCoordinator.async_set_grill_temp(225)
    │  → _call(client.async_set_grill_temp, 225)
    ▼
GMGClient.async_set_grill_temp(225)
    │  → encode_set_grill_temp(225) → b"UT225!"
    │  → opens UDP endpoint to grill:8080
    │  → sends b"UT225!" via sendto()
    │  ← receives 36-byte status frame reply
    │  → closes endpoint
    ▼
coordinator.async_request_refresh()
    │  (schedules next poll cycle)
    ▼
All entities update from coordinator.data
```

## Error Handling Strategy

| Scenario | Detection | Response |
|----------|-----------|----------|
| Grill unreachable | Socket error after retries | `UpdateFailed` → HA marks unavailable, retries automatically |
| Server Mode active | No reply to reachable host | `ConfigEntryNotReady` on setup; repair issue on polling |
| Malformed frame | Header/length check fails | `GMGProtocolError` → logged as update failure |
| Out-of-range value | Client-side validation | `ServiceValidationError` → user sees error in UI |

---

## File Map Summary

```
custom_components/gmg/
├── __init__.py          # Entry point, service registration, setup/unload
├── api/                 # Protocol layer (no HA deps)
│   ├── __init__.py      # Public exports
│   ├── client.py        # GMGClient — UDP socket management
│   ├── const.py         # Command bytes, ports, ranges
│   ├── discovery.py     # UDP broadcast scanner
│   ├── exceptions.py    # Exception hierarchy
│   ├── models.py        # Dataclasses & enums (Snapshot, GrillInfo)
│   └── protocol.py      # Frame parser + command encoder
├── binary_sensor.py     # 10 fault/status binary sensors
├── button.py            # 3 action buttons (on/off/cold smoke)
├── climate.py           # Climate entity (main grill control)
├── config_flow.py       # Setup, DHCP discovery, options, reconfigure flows
├── const.py             # Integration constants & platform list
├── coordinator.py       # DataUpdateCoordinator + command dispatch
├── diagnostics.py       # Debug bundle generation
├── entity.py            # GMGBaseEntity with device info
├── icons.json           # MDI icon mappings (state-aware)
├── manifest.json        # HA integration metadata
├── number.py            # 3 setpoint controls
├── quality_scale.yaml   # Platinum compliance checklist
├── sensor.py            # 9 monitoring sensors
├── services.py          # Domain service handlers
├── services.yaml        # Service picker definitions
├── strings.json         # Full translation bundle
└── translations/en.json # English translation (source of truth)

tests/
├── conftest.py           # Shared fixtures
├── test_config_flow.py   # Config/options/reconfigure flow tests
├── test_init.py          # Setup/unload lifecycle tests
└── test_protocol.py      # Wire protocol parse/encode tests

docs/
├── INSTALL.md            # Installation guide + troubleshooting
├── MODELS.md             # Supported grill models matrix
└── PROTOCOL.md           # Full UDP protocol specification
```
