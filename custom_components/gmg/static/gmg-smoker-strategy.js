/*
 * GMG Smoker — Lovelace card + auto-strategy
 * Ships with the Green Mountain Grills integration (served at /gmg_static/).
 *
 * Fully self-contained: builds a smoker overlay, controls and a live cook chart
 * with NO external HACS cards. The chart is a native inline-SVG element drawn
 * from the recorder history (no apexcharts-card); the heating glow is plain CSS
 * baked into the card (no card-mod). Only built-in Lovelace cards
 * (picture-elements, entities) are used for the overlay and controls.
 *
 * Add a view with:
 *   strategy:
 *     type: custom:gmg-smoker
 *     serial: GMG12137138   # optional; auto-detects the only GMG device
 *     show_graph: true      # optional
 *
 * Or just add the "GMG Smoker" card from Edit -> Add Card.
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

function escapeHtml(s) {
  return String(s).replace(
    /[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );
}

// Map every GMG entity we care about off the device, by registry translation_key.
function mapEntities(ents) {
  return {
    climate: onlyDomain(ents, "climate"),
    grillTemp: byKey(ents, "sensor", "grill_temperature"),
    probe1: byKey(ents, "sensor", "probe_1_temperature"),
    probe2: byKey(ents, "sensor", "probe_2_temperature"),
    cookState: byKey(ents, "sensor", "cook_state"),
    cookMeat: byKey(ents, "sensor", "cook_meat"),
    elapsed: byKey(ents, "sensor", "cook_elapsed_minutes"),
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
}

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
  // Grill + probe temps are rendered by GmgSmokerCard as a custom two-line
  // overlay (value over label). A built-in state-label can't do this: HA forces
  // white-space:nowrap on the label's inner div, collapsing a "\n" suffix to a
  // space — so "72°F" and "Grill" can never sit on separate lines.
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

  // Plain built-in picture-elements card. The heating glow is applied natively
  // by GmgSmokerCard (no card-mod dependency).
  return { type: "picture-elements", image, elements };
}

// Build a two-line temp readout (value over label) positioned over the smoker
// image. Returns the value <span> so the card can update it on each hass tick.
function addTempReadout(host, cls, label) {
  const wrap = document.createElement("div");
  wrap.className = "gmg-temp " + cls;
  const v = document.createElement("span");
  v.className = "v";
  const l = document.createElement("span");
  l.className = "l";
  l.textContent = label;
  wrap.appendChild(v);
  wrap.appendChild(l);
  host.appendChild(wrap);
  return v;
}

// Format a temperature into "72°F" (no space, matching the smoker display).
function setTempText(el, stateObj) {
  if (!el) return;
  const s = stateObj && stateObj.state;
  if (s == null || s === "" || s === "unknown" || s === "unavailable") {
    el.textContent = "—";
    return;
  }
  const n = Number(s);
  const unit = (stateObj.attributes && stateObj.attributes.unit_of_measurement) || "";
  el.textContent = (Number.isFinite(n) ? Math.round(n) : s) + unit;
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

  // By-the-piece meats (constant thickness): weight & finish-in are meaningless.
  // Row shows only when the meat is neither sausage/brats nor chicken breast.
  const byThePieceNot = e.meatType
    ? [
        { entity: e.meatType, state_not: "sausage_brats" },
        { entity: e.meatType, state_not: "chicken_breast" },
      ]
    : [];

  const rows = compact([
    // --- Auto-cook setup (idle) ---
    e.cookState && { type: "section", label: "Auto-Cook Setup" },
    e.meatType &&
      cond(idle(), { entity: e.meatType, name: "Meat", icon: "mdi:silverware-fork-knife" }),
    e.cookMode && cond(idle(), { entity: e.cookMode, name: "Mode", icon: "mdi:cog" }),
    e.cookProbe &&
      cond(idle(), { entity: e.cookProbe, name: "Primary probe", icon: "mdi:thermometer-probe" }),
    // Weight is meaningless for by-the-piece items — hide for sausage/brats
    // and chicken breast (constant-thickness "by the piece" meats).
    e.weight &&
      cond(idle(byThePieceNot), {
        entity: e.weight,
        name: "Meat weight",
        icon: "mdi:weight-kilogram",
      }),
    e.finishIn &&
      cond(idle(byThePieceNot), { entity: e.finishIn, name: "Finish in (h)", icon: "mdi:clock-outline" }),
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

// Window the chart to the live cook. The x-axis ends at "now"; a span of
// (elapsed + a little) starts it at the cook start with no pre-cook dead space
// and grows with the cook (long cooks are never truncated). cook_elapsed_minutes
// is None until COOKING — when no cook is running we fall back to a short window.
const IDLE_SPAN_MIN = 240;
function graphSpanMinutes(hass, elapsedEntity) {
  const st = elapsedEntity && hass && hass.states ? hass.states[elapsedEntity] : null;
  const min = st ? Number(st.state) : NaN;
  if (!Number.isFinite(min) || min <= 0) return IDLE_SPAN_MIN;
  return Math.max(10, Math.ceil(min) + 3);
}

function buildGraph(e, hass) {
  const series = compact([
    e.probe1 && { entity: e.probe1, name: "Food actual", color: "#2196f3", width: 3 },
    e.expected && { entity: e.expected, name: "Food expected", color: "#90caf9", width: 2, dashed: true },
    e.grillTemp && { entity: e.grillTemp, name: "Grill", color: "#ff6d00", width: 2, opacity: 0.6 },
  ]);
  if (series.length < 2) return null;
  return {
    type: "custom:gmg-cook-chart",
    title: "Cook Progress vs Plan",
    graph_span_minutes: graphSpanMinutes(hass, e.elapsed),
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

  const e = mapEntities(deviceEntities(hass, device.id));

  const cards = compact([
    buildOverlay(await resolveImage(device), e),
    buildControls(e),
    (config && config.show_graph === false) ? null : buildGraph(e, hass),
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

// ---- Native cook chart (inline SVG, no external charting card) ----
// A self-contained Lovelace card element that plots the recorder history of its
// series over [now - graph_span_minutes, now]. Used internally by the smoker
// card and strategy; also valid standalone as `type: custom:gmg-cook-chart`.
const GMG_CHART_CSS = `
  ha-card { padding: 12px 12px 8px; }
  .gmg-chart-body { width: 100%; }
  .gmg-svg { width: 100%; height: auto; display: block; }
  .gmg-grid { stroke: var(--divider-color, #4a4a4a); stroke-width: 1; opacity: 0.5; }
  .gmg-axis { fill: var(--secondary-text-color, #9aa0a6); font-size: 10px;
              font-family: var(--paper-font-body1_-_font-family, "Roboto", sans-serif); }
  .gmg-legend { display: flex; flex-wrap: wrap; gap: 14px; margin-top: 8px;
                font-size: 12px; color: var(--primary-text-color, #e8eaed); }
  .gmg-leg i { display: inline-block; width: 10px; height: 10px; border-radius: 2px;
               margin-right: 5px; vertical-align: middle; }
  .gmg-chart-msg { padding: 28px 8px; text-align: center;
                   color: var(--secondary-text-color, #9aa0a6); }
`;

class GmgCookChart extends HTMLElement {
  setConfig(config) {
    config = config || {};
    this._series = (config.series || []).filter((s) => s && s.entity);
    this._spanMin =
      Number(config.graph_span_minutes) > 0 ? Number(config.graph_span_minutes) : IDLE_SPAN_MIN;
    this._title = config.title || "";
    if (!this._shadow) {
      this._shadow = this.attachShadow({ mode: "open" });
      const style = document.createElement("style");
      style.textContent = GMG_CHART_CSS;
      this._card = document.createElement("ha-card");
      this._body = document.createElement("div");
      this._body.className = "gmg-chart-body";
      this._card.appendChild(this._body);
      this._shadow.append(style, this._card);
    }
    if (this._title) this._card.setAttribute("header", this._title);
    else this._card.removeAttribute("header");
    if (this._hass) this._update(true);
    else this._draw();
  }

  set hass(hass) {
    this._hass = hass;
    this._update(false);
  }

  getCardSize() {
    return 6;
  }

  static getStubConfig() {
    return { type: "custom:gmg-cook-chart", series: [] };
  }

  _update(force) {
    if (!this._hass || !this._series.length) {
      this._draw();
      return;
    }
    const now = Date.now();
    if (force || !this._data || now - (this._lastFetch || 0) > 30000) {
      this._fetch();
    } else {
      this._draw();
    }
  }

  async _fetch() {
    if (this._fetching || !this._hass) return;
    this._fetching = true;
    try {
      const end = new Date();
      const start = new Date(end.getTime() - this._spanMin * 60000);
      const res = await this._hass.callWS({
        type: "history/history_during_period",
        start_time: start.toISOString(),
        end_time: end.toISOString(),
        entity_ids: this._series.map((s) => s.entity),
        minimal_response: true,
        no_attributes: true,
        significant_changes_only: false,
      });
      this._data = res || {};
      this._error = null;
      this._lastFetch = Date.now();
    } catch (err) {
      this._error = err && err.message ? err.message : String(err);
    } finally {
      this._fetching = false;
      this._draw();
    }
  }

  _points(entityId) {
    const raw = (this._data && this._data[entityId]) || [];
    const pts = [];
    for (const r of raw) {
      const v = parseFloat(r.s != null ? r.s : r.state);
      let t = r.lu != null ? r.lu : r.lc != null ? r.lc : null;
      t = t != null ? t * 1000 : Date.parse(r.last_updated || r.last_changed || "");
      if (Number.isFinite(v) && Number.isFinite(t)) pts.push([t, v]);
    }
    // Pin a fresh point at "now" from the live state so the right edge tracks.
    const st = this._hass && this._hass.states[entityId];
    if (st) {
      const v = parseFloat(st.state);
      if (Number.isFinite(v)) pts.push([Date.now(), v]);
    }
    pts.sort((a, b) => a[0] - b[0]);
    return pts;
  }

  _draw() {
    if (!this._body) return;
    if (this._error) {
      this._body.innerHTML = `<div class="gmg-chart-msg">Chart unavailable: ${escapeHtml(this._error)}</div>`;
      return;
    }
    if (!this._series.length) {
      this._body.innerHTML = `<div class="gmg-chart-msg">No probe data configured.</div>`;
      return;
    }
    const series = this._series.map((s) => ({ ...s, pts: this._points(s.entity) }));
    if (!series.some((s) => s.pts.length)) {
      this._body.innerHTML = `<div class="gmg-chart-msg">Waiting for cook data…</div>`;
      return;
    }

    const W = 600;
    const H = 260;
    const mL = 38;
    const mR = 10;
    const mT = 8;
    const mB = 22;
    const xmax = Date.now();
    const xmin = xmax - this._spanMin * 60000;
    let ymin = Infinity;
    let ymax = -Infinity;
    for (const s of series) {
      for (const [t, v] of s.pts) {
        if (t < xmin - 1) continue;
        if (v < ymin) ymin = v;
        if (v > ymax) ymax = v;
      }
    }
    if (!Number.isFinite(ymin) || !Number.isFinite(ymax)) {
      ymin = 0;
      ymax = 1;
    }
    if (ymin === ymax) {
      ymin -= 1;
      ymax += 1;
    }
    const padY = (ymax - ymin) * 0.08;
    ymin -= padY;
    ymax += padY;
    const xpx = (t) => mL + ((t - xmin) / (xmax - xmin)) * (W - mL - mR);
    const ypx = (v) => mT + (1 - (v - ymin) / (ymax - ymin)) * (H - mT - mB);
    const first = this._hass.states[this._series[0].entity];
    const unit = (first && first.attributes && first.attributes.unit_of_measurement) || "";

    let grid = "";
    for (let i = 0; i <= 4; i++) {
      const v = ymin + (i / 4) * (ymax - ymin);
      const y = ypx(v).toFixed(1);
      grid += `<line class="gmg-grid" x1="${mL}" y1="${y}" x2="${W - mR}" y2="${y}"/>`;
      grid += `<text class="gmg-axis" x="${mL - 4}" y="${(Number(y) + 3).toFixed(1)}" text-anchor="end">${Math.round(v)}</text>`;
    }

    const spanH = this._spanMin / 60;
    const stepH = spanH <= 2 ? 0.5 : spanH <= 6 ? 1 : spanH <= 12 ? 2 : 4;
    let xticks = "";
    for (let h = 0; h <= spanH + 1e-6; h += stepH) {
      const t = xmax - h * 3600000;
      if (t < xmin - 1) break;
      const x = xpx(t).toFixed(1);
      const label = h === 0 ? "now" : `-${h % 1 ? h.toFixed(1) : h}h`;
      xticks += `<line class="gmg-grid" x1="${x}" y1="${mT}" x2="${x}" y2="${H - mB}"/>`;
      xticks += `<text class="gmg-axis" x="${x}" y="${H - mB + 14}" text-anchor="middle">${label}</text>`;
    }

    let paths = "";
    for (const s of series) {
      const inWin = s.pts.filter(([t]) => t >= xmin - 1);
      if (!inWin.length) continue;
      const d = inWin
        .map(([t, v], i) => `${i ? "L" : "M"}${xpx(t).toFixed(1)},${ypx(v).toFixed(1)}`)
        .join(" ");
      paths +=
        `<path d="${d}" fill="none" stroke="${s.color || "#888"}" stroke-width="${s.width || 2}" ` +
        `stroke-opacity="${s.opacity != null ? s.opacity : 1}" ${s.dashed ? 'stroke-dasharray="5 4"' : ""} ` +
        `stroke-linejoin="round" stroke-linecap="round"/>`;
    }

    const svg = `<svg viewBox="0 0 ${W} ${H}" class="gmg-svg">${grid}${xticks}${paths}</svg>`;
    const legend = series
      .map((s) => {
        const st = this._hass.states[s.entity];
        const num = st ? parseFloat(st.state) : NaN;
        const cur = Number.isFinite(num) ? `${Math.round(num)}${unit}` : "—";
        return `<span class="gmg-leg"><i style="background:${s.color || "#888"};opacity:${s.opacity != null ? s.opacity : 1}"></i>${escapeHtml(s.name || s.entity)}: <b>${cur}</b></span>`;
      })
      .join("");
    this._body.innerHTML = `${svg}<div class="gmg-legend">${legend}</div>`;
  }
}

// ---- Custom card ----
// In any dashboard: Edit -> Add Card -> "GMG Smoker" (or YAML
// `type: custom:gmg-smoker-card`). Builds the overlay + controls + native chart
// as ONE card, auto-resolved from your GMG device, with a native heating glow.
const GMG_CARD_CSS = `
  .gmg-col { display: flex; flex-direction: column; gap: 12px; }
  .gmg-glow { position: relative; border-radius: var(--ha-card-border-radius, 12px); transition: box-shadow 0.4s ease; }
  .gmg-glow.heating { box-shadow: 0 0 22px 6px rgba(255, 109, 0, 0.55); }
  .gmg-temp { position: absolute; transform: translate(-50%, -50%); z-index: 1;
              display: flex; flex-direction: column; align-items: center; line-height: 1.04;
              font-weight: bold; text-align: center; pointer-events: none; }
  .gmg-temp .v { font-size: 16px; }
  .gmg-temp .l { font-size: 10px; font-weight: 600; letter-spacing: 0.5px; opacity: 0.92; }
  .gmg-temp-grill { top: 64%; left: 38%; color: #ff6d00; }
  .gmg-temp-probe { top: 64%; left: 68%; color: #2196f3; }
`;

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
      return;
    }
    const inner = this._inner;
    if (!inner) return;
    inner.overlay.hass = hass;
    inner.controls.hass = hass;
    this._updateTemps(hass);
    if (inner.chart) {
      const span = graphSpanMinutes(hass, this._elapsed);
      if (span !== this._chartSpan) {
        this._chartSpan = span;
        inner.chart.setConfig({ ...this._chartCfg, graph_span_minutes: span });
      }
      inner.chart.hass = hass;
    }
    this._applyGlow(hass);
  }

  _applyGlow(hass) {
    if (!this._glowHost || !this._climate) return;
    const st = hass.states[this._climate];
    this._glowHost.classList.toggle("heating", !!(st && st.state === "heat"));
  }

  _updateTemps(hass) {
    if (!hass || !this._tempEls) return;
    if (this._tempEls.grill) setTempText(this._tempEls.grill, hass.states[this._grillId]);
    if (this._tempEls.probe) setTempText(this._tempEls.probe, hass.states[this._probe1Id]);
  }

  _msgCard(text) {
    const card = document.createElement("ha-card");
    const div = document.createElement("div");
    div.style.padding = "16px";
    div.textContent = text;
    card.appendChild(div);
    return card;
  }

  async _render(hass) {
    try {
      const helpers = await window.loadCardHelpers();
      const device = findDevice(hass, this._config && this._config.serial);
      if (!device) {
        this.replaceChildren(
          this._msgCard(
            "No Green Mountain Grills device found. Add the GMG integration, or set serial: in the card config."
          )
        );
        return;
      }
      const e = mapEntities(deviceEntities(hass, device.id));
      this._climate = e.climate;
      this._elapsed = e.elapsed;
      const image = await resolveImage(device);

      const overlay = helpers.createCardElement(buildOverlay(image, e));
      overlay.hass = hass;
      const controls = helpers.createCardElement(buildControls(e));
      controls.hass = hass;

      const col = document.createElement("div");
      col.className = "gmg-col";

      const glowHost = document.createElement("div");
      glowHost.className = "gmg-glow";
      glowHost.appendChild(overlay);
      this._grillId = e.grillTemp;
      this._probe1Id = e.probe1;
      this._tempEls = {};
      if (e.grillTemp) this._tempEls.grill = addTempReadout(glowHost, "gmg-temp-grill", "Grill");
      if (e.probe1) this._tempEls.probe = addTempReadout(glowHost, "gmg-temp-probe", "Probe");
      this._updateTemps(hass);
      this._glowHost = glowHost;
      col.appendChild(glowHost);
      col.appendChild(controls);

      let chart = null;
      if (!(this._config && this._config.show_graph === false)) {
        this._chartCfg = buildGraph(e, hass);
        if (this._chartCfg) {
          this._chartSpan = this._chartCfg.graph_span_minutes;
          chart = helpers.createCardElement(this._chartCfg);
          chart.hass = hass;
          col.appendChild(chart);
        }
      }

      const style = document.createElement("style");
      style.textContent = GMG_CARD_CSS;
      this.replaceChildren(style, col);
      this._inner = { overlay, controls, chart };
      this._applyGlow(hass);
    } catch (err) {
      this.replaceChildren(this._msgCard("GMG card error: " + (err && err.message ? err.message : err)));
    }
  }

  getCardSize() {
    return 12;
  }

  static getStubConfig() {
    return { type: "custom:gmg-smoker-card" };
  }
}

customElements.define("gmg-cook-chart", GmgCookChart);
customElements.define("gmg-smoker-card", GmgSmokerCard);

// Lovelace strategies (alternative: generate a whole view / dashboard).
customElements.define("ll-strategy-view-gmg-smoker", GmgSmokerViewStrategy);
customElements.define("ll-strategy-dashboard-gmg-smoker", GmgSmokerDashboardStrategy);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "gmg-smoker-card",
  name: "GMG Smoker",
  description:
    "Self-contained smoker overlay, controls and native cook chart for your Green Mountain Grill — no extra cards required.",
  preview: false,
});
console.info("%c GMG-SMOKER %c card + native chart loaded ", "background:#ff6d00;color:#fff", "");
