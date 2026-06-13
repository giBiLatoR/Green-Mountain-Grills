/*
 * GMG Smoker — Lovelace auto-strategy
 * Ships with the Green Mountain Grills integration (served at /gmg_static/).
 *
 * Builds a smoker overlay + controls view automatically from the GMG device,
 * resolving entities by their registry translation_key so it survives renames
 * and is independent of any user-created helpers. Temperatures are shown in
 * Home Assistant's own unit system (no hard-coded °F conversion).
 *
 * Add a view with:
 *   strategy:
 *     type: custom:gmg-smoker
 *     serial: GMG12137138   # optional; auto-detects the only GMG device
 *     show_graph: true      # optional; needs the apexcharts-card HACS card
 *
 * Optional HACS cards for the full look: card-mod (glow/fan animation),
 * apexcharts-card (progress graph). The view still works without them.
 */

const STATIC = "/gmg_static";

const GENERIC_IMAGE = `${STATIC}/smoker-generic.svg`;

// Optional explicit overrides: model_id -> image url. Usually unnecessary —
// prefer the filename convention below.
const MODEL_IMAGES = {};

// Auto-discovery convention: drop a transparent PNG named "<model_id>.png" into
// custom_components/gmg/static/models/ and it is used automatically — no code
// edit needed. model_id values come from the integration's MODEL_NAMES table:
//   0 Davy Crockett   1 Trek              2 Daniel Boone        3 Jim Bowie
//   4 Ledge           5 Peak              6 Ledge Prime+        7 Peak Prime+
//   8 Trek Prime 2.0  9 Ledge Prime 2.0  10 Peak Prime 2.0     11 Daniel Boone Prime+
//   12 Jim Bowie Prime+  13 Daniel Boone Prime 2.0  14 Jim Bowie Prime 2.0  15 Trek Prime+
async function resolveImage(device) {
  const id = device && device.model_id;
  if (id != null && MODEL_IMAGES[id]) return MODEL_IMAGES[id];
  if (id != null) {
    const url = `${STATIC}/models/${id}.png`;
    try {
      const r = await fetch(url, { method: "HEAD" });
      if (r.ok) return url;
    } catch (err) {
      /* fall through to the generic silhouette */
    }
  }
  return GENERIC_IMAGE;
}

function findDevice(hass, serial) {
  const devices = Object.values(hass.devices || {});
  for (const d of devices) {
    const ids = d.identifiers || [];
    const isGmg = ids.some((pair) => pair[0] === "gmg");
    if (!isGmg) continue;
    if (!serial) return d;
    if (ids.some((pair) => String(pair[1]).includes(serial))) return d;
  }
  return null;
}

function deviceEntities(hass, deviceId) {
  return Object.values(hass.entities || {}).filter(
    (e) => e.device_id === deviceId
  );
}

// Resolve by registry translation_key (stable), falling back to an entity_id
// substring match for older cores that don't expose translation_key.
function byKey(entities, domain, key) {
  let m = entities.find(
    (e) => e.entity_id.startsWith(domain + ".") && e.translation_key === key
  );
  if (m) return m.entity_id;
  m = entities.find(
    (e) => e.entity_id.startsWith(domain + ".") && e.entity_id.includes(key)
  );
  return m ? m.entity_id : null;
}

function onlyDomain(entities, domain) {
  const m = entities.find((e) => e.entity_id.startsWith(domain + "."));
  return m ? m.entity_id : null;
}

// Drop null/undefined entries from a list (used to skip missing entities).
const compact = (arr) => arr.filter((x) => x);

function buildOverlay(image, e) {
  const elements = [];

  if (e.cookState) {
    elements.push({
      type: "state-label",
      entity: e.cookState,
      prefix: "Phase: ",
      style: {
        top: "12%",
        left: "50%",
        "font-size": "18px",
        "font-weight": "bold",
        color: "white",
      },
    });
  }
  if (e.grillTemp) {
    elements.push({
      type: "state-label",
      entity: e.grillTemp,
      suffix: "\nGrill",
      style: {
        top: "64%",
        left: "38%",
        color: "#ff6d00",
        "font-size": "24px",
        "font-weight": "bold",
        "text-align": "center",
        "white-space": "pre",
      },
    });
  }
  if (e.probe1) {
    elements.push({
      type: "state-label",
      entity: e.probe1,
      suffix: "\nProbe",
      style: {
        top: "64%",
        left: "68%",
        color: "#2196f3",
        "font-size": "24px",
        "font-weight": "bold",
        "text-align": "center",
        "white-space": "pre",
      },
    });
  }
  if (e.climate) {
    // Power toggle: tap to start heating when off, confirm-shutdown when on.
    elements.push({
      type: "conditional",
      conditions: [{ entity: e.climate, state: "off" }],
      elements: [
        {
          type: "state-icon",
          entity: e.climate,
          icon: "mdi:power",
          tap_action: {
            action: "perform-action",
            perform_action: "climate.set_hvac_mode",
            target: { entity_id: e.climate },
            data: { hvac_mode: "heat" },
          },
          style: {
            top: "62%",
            left: "12%",
            transform: "translate(-50%, -50%) scale(1.8)",
            color: "#808080",
          },
        },
      ],
    });
    elements.push({
      type: "conditional",
      conditions: [{ entity: e.climate, state_not: "off" }],
      elements: [
        {
          type: "state-icon",
          entity: e.climate,
          icon: "mdi:power",
          tap_action: {
            action: "perform-action",
            perform_action: "climate.set_hvac_mode",
            target: { entity_id: e.climate },
            data: { hvac_mode: "off" },
            confirmation: { text: "Shut the smoker down?" },
          },
          style: {
            top: "62%",
            left: "12%",
            transform: "translate(-50%, -50%) scale(1.8)",
            color: "#ff6d00",
          },
        },
      ],
    });
  }
  if (e.warning) {
    elements.push({
      type: "conditional",
      conditions: [{ entity: e.warning, state_not: "none" }],
      elements: [
        {
          type: "state-label",
          entity: e.warning,
          prefix: "⚠️ ",
          style: {
            top: "92%",
            left: "50%",
            color: "red",
            "font-size": "15px",
            "font-weight": "bold",
          },
        },
      ],
    });
  }
  if (e.hopper) {
    elements.push({
      type: "state-label",
      entity: e.hopper,
      prefix: "Hopper: ",
      style: { top: "92%", left: "13%", color: "#aaa", "font-size": "13px" },
    });
  }

  const card = { type: "picture-elements", image, elements };
  // Optional glow (needs card-mod; ignored if not installed).
  if (e.climate) {
    card.card_mod = {
      style: `ha-card {
  {% if is_state('${e.climate}', 'heat') %}
    box-shadow: 0 0 22px 6px rgba(255,109,0,0.55);
  {% endif %}
  border: none;
}`,
    };
  }
  return card;
}

function buildControls(e) {
  const idle = (extra) =>
    e.cookState
      ? {
          conditions: [{ entity: e.cookState, state: "idle" }].concat(
            extra || []
          ),
        }
      : { conditions: [] };
  const active = e.cookState
    ? { conditions: [{ entity: e.cookState, state_not: "idle" }] }
    : { conditions: [] };

  const cond = (c, row) => (row.entity || row.type ? { type: "conditional", ...c, row } : null);

  const rows = compact([
    // --- Auto-cook setup (idle) ---
    e.cookState && { type: "section", label: "Auto-Cook Setup" },
    e.meatType &&
      cond(idle(), { entity: e.meatType, name: "Meat", icon: "mdi:silverware-fork-knife" }),
    e.cookMode && cond(idle(), { entity: e.cookMode, name: "Mode", icon: "mdi:cog" }),
    e.cookProbe &&
      cond(idle(), { entity: e.cookProbe, name: "Primary probe", icon: "mdi:thermometer-probe" }),
    // Weight is meaningless for by-the-piece items — hide for sausage/brats.
    e.weight &&
      cond(idle(e.meatType ? [{ entity: e.meatType, state_not: "sausage_brats" }] : []), {
        entity: e.weight,
        name: "Meat weight",
        icon: "mdi:weight-kilogram",
      }),
    e.finishIn &&
      cond(idle(), { entity: e.finishIn, name: "Finish in (h)", icon: "mdi:clock-outline" }),
    e.startCook &&
      cond(idle(), { entity: e.startCook, name: "▶  Start Auto-Cook", icon: "mdi:play-circle" }),

    // --- Live cook (not idle) ---
    e.cookState && { type: "section", label: "Cook In Progress" },
    e.cookState && cond(active, { entity: e.cookState, name: "Phase", icon: "mdi:chef-hat" }),
    e.cookMeat && cond(active, { entity: e.cookMeat, name: "Meat", icon: "mdi:food-steak" }),
    // Meat-on override: probe already in cold meat (no drop event to detect).
    e.meatOn &&
      cond(active, { entity: e.meatOn, name: "✔  Meat is on (start tracking)", icon: "mdi:food-steak" }),
    e.onSchedule &&
      cond(active, { entity: e.onSchedule, name: "On schedule", icon: "mdi:check-decagram" }),
    e.remaining &&
      cond(active, { entity: e.remaining, name: "Time remaining", icon: "mdi:timer-sand" }),
    e.pitTarget && cond(active, { entity: e.pitTarget, name: "Pit target", icon: "mdi:fire" }),
    e.expected &&
      cond(active, { entity: e.expected, name: "Expected probe", icon: "mdi:thermometer-probe" }),
    e.pullTemp && cond(active, { entity: e.pullTemp, name: "Pull target", icon: "mdi:target" }),
    e.abortCook &&
      cond(active, { entity: e.abortCook, name: "■  Abort Cook", icon: "mdi:stop-circle" }),

    // --- Manual controls (always) ---
    { type: "section", label: "Manual" },
    e.grillSet && { entity: e.grillSet, name: "Grill setpoint", icon: "mdi:fire" },
    e.probe1Target && { entity: e.probe1Target, name: "Probe 1 target", icon: "mdi:thermometer-probe" },
    e.probe2Target && { entity: e.probe2Target, name: "Probe 2 target", icon: "mdi:thermometer-probe" },
    e.coldSmoke && { entity: e.coldSmoke, name: "Cold smoke", icon: "mdi:snowflake" },
  ]);

  return { type: "entities", title: "Smoker Controls", show_header_toggle: false, state_color: true, entities: rows };
}

function buildGraph(e) {
  const series = compact([
    e.probe1 && { entity: e.probe1, name: "Food actual", color: "#2196f3", stroke_width: 3, curve: "smooth" },
    e.expected && { entity: e.expected, name: "Food expected", color: "#90caf9", stroke_width: 2, curve: "smooth" },
    e.grillTemp && { entity: e.grillTemp, name: "Grill", color: "#ff6d00", stroke_width: 2, curve: "smooth", opacity: 0.5 },
  ]);
  if (series.length < 2) return null;
  return {
    type: "custom:apexcharts-card",
    header: { show: true, title: "Cook Progress vs Plan", show_states: true },
    graph_span: "8h",
    series,
  };
}

async function buildView(hass, config) {
  const device = findDevice(hass, config && config.serial);
  if (!device) {
    return {
      type: "panel",
      cards: [
        {
          type: "markdown",
          content:
            "### No Green Mountain Grills device found\nAdd the GMG integration, or set `serial:` in the strategy config.",
        },
      ],
    };
  }

  const ents = deviceEntities(hass, device.id);
  const e = {
    climate: onlyDomain(ents, "climate"),
    grillTemp: byKey(ents, "sensor", "grill_temperature"),
    probe1: byKey(ents, "sensor", "probe_1_temperature"),
    probe2: byKey(ents, "sensor", "probe_2_temperature"),
    cookState: byKey(ents, "sensor", "cook_state"),
    cookMeat: byKey(ents, "sensor", "cook_meat"),
    remaining: byKey(ents, "sensor", "cook_remaining_minutes"),
    pitTarget: byKey(ents, "sensor", "cook_pit_target"),
    expected: byKey(ents, "sensor", "cook_expected_probe_temp"),
    pullTemp: byKey(ents, "sensor", "cook_pull_temp"),
    warning: byKey(ents, "sensor", "warning"),
    hopper: byKey(ents, "sensor", "hopper"),
    onSchedule: byKey(ents, "binary_sensor", "cook_on_schedule"),
    meatType: byKey(ents, "select", "cook_meat_type"),
    cookMode: byKey(ents, "select", "cook_mode"),
    cookProbe: byKey(ents, "select", "cook_probe"),
    weight: byKey(ents, "number", "cook_weight_kg"),
    finishIn: byKey(ents, "number", "cook_finish_in_hours"),
    grillSet: byKey(ents, "number", "grill_setpoint"),
    probe1Target: byKey(ents, "number", "probe_1_target"),
    probe2Target: byKey(ents, "number", "probe_2_target"),
    startCook: byKey(ents, "button", "start_cook"),
    abortCook: byKey(ents, "button", "abort_cook"),
    meatOn: byKey(ents, "button", "meat_on"),
    coldSmoke: byKey(ents, "button", "cold_smoke"),
  };

  const cards = compact([
    buildOverlay(await resolveImage(device), e),
    buildControls(e),
    (config && config.show_graph === false) ? null : buildGraph(e),
  ]);

  return { type: "panel", cards: [{ type: "vertical-stack", cards }] };
}

class GmgSmokerViewStrategy extends HTMLElement {
  static async generate(config, hass) {
    return await buildView(hass, config);
  }
}

class GmgSmokerDashboardStrategy extends HTMLElement {
  static async generate(config, hass) {
    const view = await buildView(hass, config);
    view.title = "Smoker";
    view.path = "smoker";
    view.icon = "mdi:grill";
    return { title: "GMG Smoker", views: [view] };
  }
}

// ---- Custom card ----
// The headline way to use this: in any dashboard, Edit -> Add Card -> "GMG
// Smoker" (or YAML `type: custom:gmg-smoker-card`). Builds the same overlay +
// controls (+ graph) as ONE card, auto-resolved from your GMG device.
class GmgSmokerCard extends HTMLElement {
  setConfig(config) {
    this._config = config || {};
    this._built = false;
    this._inner = null;
  }

  set hass(hass) {
    this._hass = hass;
    if (!hass) return;
    if (!this._built) {
      this._built = true;
      this._render(hass);
    } else if (this._inner) {
      this._inner.hass = hass;
    }
  }

  async _render(hass) {
    const helpers = await window.loadCardHelpers();
    const view = await buildView(hass, this._config);
    // buildView returns a panel wrapper; mount its single inner card.
    const inner = view.cards && view.cards.length ? view.cards[0] : view;
    const el = helpers.createCardElement(inner);
    el.hass = hass;
    this._inner = el;
    this.replaceChildren(el);
  }

  getCardSize() {
    return 12;
  }

  static getStubConfig() {
    return { type: "custom:gmg-smoker-card" };
  }
}

customElements.define("gmg-smoker-card", GmgSmokerCard);

// Lovelace strategies (alternative: generate a whole view / dashboard).
customElements.define("ll-strategy-view-gmg-smoker", GmgSmokerViewStrategy);
customElements.define("ll-strategy-dashboard-gmg-smoker", GmgSmokerDashboardStrategy);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "gmg-smoker-card",
  name: "GMG Smoker",
  description:
    "Auto-built smoker overlay, controls and progress graph for your Green Mountain Grill.",
  preview: false,
});
console.info("%c GMG-SMOKER %c card + strategy loaded ", "background:#ff6d00;color:#fff", "");
