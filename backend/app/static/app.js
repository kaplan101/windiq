// Lädt Ergebnis, 7-Tage-Verlauf und Betriebsstatus aus dem Backend und zeigt sie an. Kein Build-Schritt, kein Framework.

const REFRESH_MS = 5 * 60 * 1000;
const TIME_ZONE = "Europe/Berlin";
const Y_AXIS_WIDTH = 48; // gleich breit in beiden 7-Tage-Diagrammen, damit die Zeitachsen exakt übereinander liegen
const hourFormat = new Intl.DateTimeFormat("de-DE", { timeZone: TIME_ZONE, hour: "numeric", hourCycle: "h23" });

const fmt = {
  mwh: (v) => v.toLocaleString("de-DE", { maximumFractionDigits: 0 }),
  mwh1: (v) => v.toLocaleString("de-DE", { minimumFractionDigits: 1, maximumFractionDigits: 1 }),
  int: (v) => Math.round(v).toLocaleString("de-DE"),
  pct: (v, digits = 1) => v.toLocaleString("de-DE", { style: "percent", minimumFractionDigits: digits, maximumFractionDigits: digits }),
  num: (v, digits) => v.toLocaleString("de-DE", { minimumFractionDigits: digits, maximumFractionDigits: digits }),
  dateTime: (iso) => new Date(iso).toLocaleString("de-DE", { timeZone: TIME_ZONE, day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" }),
  time: (iso) => new Date(iso).toLocaleTimeString("de-DE", { timeZone: TIME_ZONE, hour: "2-digit", minute: "2-digit" }),
  weekday: (iso) => new Date(iso).toLocaleDateString("de-DE", { timeZone: TIME_ZONE, weekday: "short" }),
  weekdayDate: (iso) => new Date(iso).toLocaleDateString("de-DE", { timeZone: TIME_ZONE, weekday: "short", day: "2-digit", month: "2-digit" }),
  hourOfDay: (iso) => Number(hourFormat.formatToParts(new Date(iso)).find((part) => part.type === "hour").value),
  month: (ym) => new Date(`${ym}-01T00:00:00Z`).toLocaleDateString("de-DE", { timeZone: "UTC", month: "short", year: "2-digit" }),
};

const STATUS_LABELS = {
  valid: "Gültig",
  frozen: "Eingefroren (Wiederholung)",
  sensor_error: "Sensorfehler (−999)",
  missing: "Kein Wert (null)",
  outlier: "Unplausibel (< 0 oder > 40 m/s)",
  invalid: "Kein Zahlenwert",
  unknown_unit: "Unbekannte Einheit",
  no_record: "Kein Datensatz",
};

const charts = {};
let lastYield = null;
let lastRecent = null;

const $ = (id) => document.getElementById(id);
const cssVar = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

function withAlpha(hex, alpha) {
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${n >> 16}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`;
}

function drawChart(id, config) {
  charts[id]?.destroy();
  charts[id] = new Chart($(id), config);
}

function setFacts(id, rows) {
  $(id).replaceChildren(
    ...rows.flatMap(([term, value]) => {
      const dt = document.createElement("dt");
      const dd = document.createElement("dd");
      dt.textContent = term;
      if (value instanceof Node) dd.append(value); else dd.textContent = value;
      return [dt, dd];
    }),
  );
}

function statusLabel(level, text) {
  const wrap = document.createElement("span");
  wrap.className = "status";
  const dot = document.createElement("span");
  dot.className = `dot ${level}`;
  dot.setAttribute("aria-hidden", "true");
  wrap.append(dot, text);
  return wrap;
}

// ---------- 12 Monate ----------

function isPartialMonth(m) {
  const [year, month] = m.month.split("-").map(Number);
  return m.hours < new Date(Date.UTC(year, month, 0)).getUTCDate() * 24;
}

function renderYield(y) {
  const inp = y.inputs;
  $("subtitle").textContent = `${inp.mast_name} · ${inp.turbine_name} · ${inp.site_name}`;
  $("p50").textContent = fmt.mwh(y.p50_mwh);
  $("p90").textContent = fmt.mwh(y.p90_mwh);
  $("gross").textContent = fmt.mwh(y.aep_gross_mwh);
  $("coverage").textContent = fmt.pct(y.coverage);
  $("coverage-bar").style.width = `${(y.coverage * 100).toFixed(1)}%`;
  $("range-fill").style.width = `${((y.p90_mwh / y.p50_mwh) * 100).toFixed(1)}%`;
  $("range-text").textContent = `P90 liegt ${fmt.pct(1 - y.p90_mwh / y.p50_mwh)} unter P50 (Unsicherheit ${fmt.pct(inp.uncertainty, 0)})`;
  $("measured").textContent = `${fmt.int(y.hours_valid)} von ${fmt.int(y.hours_total)} Stunden gemessen`;
  $("window").textContent = `Letzte 12 Monate: ${fmt.dateTime(y.window_start)} – ${fmt.dateTime(y.window_end)} Uhr`;

  setFacts("inputs", [
    ["Messhöhe", `${fmt.num(inp.measurement_height_m, 0)} m`],
    ["Nabenhöhe", `${fmt.num(inp.hub_height_m, 0)} m`],
    ["Höhenexponent α", fmt.num(inp.shear_exponent, 2)],
    ["Faktor Nabenhöhe", fmt.num(inp.hub_height_factor, 4)],
    ["Nennleistung", `${fmt.int(inp.rated_power_kw)} kW`],
    ["Cut-in / Cut-out", `${fmt.num(inp.cut_in_wind_speed_ms, 0)} / ${fmt.num(inp.cut_out_wind_speed_ms, 0)} m/s`],
    ["Verlust Verfügbarkeit", fmt.pct(inp.loss_availability, 0)],
    ["Verlust elektrisch", fmt.pct(inp.loss_electrical, 0)],
    ["Verlust Abschattung", fmt.pct(inp.loss_wake, 0)],
    ["Netto-Faktor", fmt.num(inp.net_factor, 4)],
    ["Unsicherheit U", fmt.pct(inp.uncertainty, 0)],
    ["P90-Faktor", fmt.num(inp.p90_factor, 4)],
    ["Version Anlage / Standort", `v${inp.turbine_version} / v${inp.site_version}`],
  ]);

  setFacts(
    "quality",
    Object.entries(y.data_quality)
      .filter(([key, count]) => key === "valid" || count > 0)
      .map(([key, count]) => [STATUS_LABELS[key] ?? key, `${fmt.int(count)} (${fmt.pct(count / y.hours_total)})`]),
  );

  const monthLabel = (m) => (isPartialMonth(m) ? `${fmt.month(m.month)}*` : fmt.month(m.month));
  $("monthly-table").replaceChildren(
    ...y.monthly.map((m) => {
      const tr = document.createElement("tr");
      const cells = [monthLabel(m), fmt.mwh1(m.measured_mwh), fmt.mwh1(m.filled_mwh), fmt.mwh1(m.measured_mwh + m.filled_mwh), `${fmt.int(m.valid_hours)} / ${fmt.int(m.hours)}`];
      tr.replaceChildren(...cells.map((text) => Object.assign(document.createElement("td"), { textContent: text })));
      return tr;
    }),
  );

  renderMonthlyChart(y.monthly, monthLabel);
}

function renderMonthlyChart(monthly, monthLabel) {
  const isTopSegment = (ctx) => ctx.datasetIndex === 1 || monthly[ctx.dataIndex].filled_mwh === 0;
  const datasets = [
    { label: "Gemessen", data: monthly.map((m) => m.measured_mwh), backgroundColor: cssVar("--series-1") },
    {
      label: "Aufgefüllt (geschätzt)",
      data: monthly.map((m) => m.filled_mwh),
      backgroundColor: cssVar("--series-2"),
      // 2 px Abstand in Flächenfarbe zum Segment darunter
      borderColor: cssVar("--surface"),
      borderWidth: (ctx) => (monthly[ctx.dataIndex].filled_mwh > 0 ? { top: 0, right: 0, left: 0, bottom: 2 } : 0),
      borderSkipped: false,
    },
  ].map((ds) => ({
    ...ds,
    stack: "energy",
    maxBarThickness: 24,
    borderRadius: (ctx) => (isTopSegment(ctx) ? { topLeft: 4, topRight: 4 } : 0),
  }));

  drawChart("monthly-chart", {
    type: "bar",
    data: { labels: monthly.map(monthLabel), datasets },
    options: {
      ...baseOptions(),
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            title: (items) => {
              const m = monthly[items[0].dataIndex];
              return isPartialMonth(m) ? `${fmt.month(m.month)} (Teilmonat, ${fmt.int(m.hours)} h)` : fmt.month(m.month);
            },
            label: (item) => ` ${item.dataset.label}: ${fmt.mwh1(item.parsed.y)} MWh`,
            footer: (items) => {
              const m = monthly[items[0].dataIndex];
              return `Gesamt: ${fmt.mwh1(m.measured_mwh + m.filled_mwh)} MWh · ${fmt.int(m.valid_hours)} / ${fmt.int(m.hours)} h gültig`;
            },
          },
        },
      },
      scales: {
        x: { stacked: true, grid: { display: false }, border: { color: cssVar("--axis") }, ticks: { color: cssVar("--text-muted") } },
        y: { stacked: true, beginAtZero: true, grid: { color: cssVar("--grid") }, border: { display: false }, ticks: { color: cssVar("--text-muted"), callback: (v) => fmt.int(v) } },
      },
    },
  });
}

function baseOptions() {
  return { responsive: true, maintainAspectRatio: false, animation: false };
}

// ---------- 7 Tage ----------

// Graue Bänder hinter Stunden ohne gültige Messung
const gapBands = {
  id: "gapBands",
  beforeDatasetsDraw(chart, _args, opts) {
    const { ctx, chartArea, scales: { x } } = chart;
    const width = x.getPixelForValue(1) - x.getPixelForValue(0);
    ctx.save();
    ctx.fillStyle = opts.color;
    for (const i of opts.indices) {
      ctx.fillRect(x.getPixelForValue(i) - width / 2, chartArea.top, width, chartArea.bottom - chartArea.top);
    }
    ctx.restore();
  },
};

// Dünne Bezugslinie, z. B. für die Nennleistung
const referenceLine = {
  id: "referenceLine",
  afterDatasetsDraw(chart, _args, opts) {
    if (opts.value == null) return;
    const { ctx, chartArea, scales: { y } } = chart;
    const py = y.getPixelForValue(opts.value);
    ctx.save();
    ctx.strokeStyle = opts.color;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(chartArea.left, py);
    ctx.lineTo(chartArea.right, py);
    ctx.stroke();
    ctx.fillStyle = opts.textColor;
    ctx.font = "12px system-ui, -apple-system, 'Segoe UI', sans-serif";
    ctx.textAlign = "right";
    ctx.fillText(opts.label, chartArea.right, py - 6);
    ctx.restore();
  },
};

function renderRecent(r) {
  $("week-energy").textContent = `${fmt.mwh1(r.energy_mwh)} MWh`;
  $("week-wind").textContent = r.mean_wind_ms == null ? "–" : `${fmt.num(r.mean_wind_ms, 1)} m/s`;
  $("week-coverage").textContent = fmt.pct(r.coverage);
  if (!$("panel-week").hidden) renderRecentCharts(r);
}

function renderRecentCharts(r) {
  const hours = r.hours;
  const invalid = hours.flatMap((h, i) => (h.status === "valid" ? [] : [i]));
  const series = cssVar("--series-1");
  const muted = cssVar("--text-muted");

  const xAxis = {
    grid: { display: false },
    border: { color: cssVar("--axis") },
    ticks: {
      color: muted,
      autoSkip: false,
      maxRotation: 0,
      // nur um Mitternacht beschriften: „Mo., 26.10.“ – auf schmalen Bildschirmen nur „Mo.“
      callback(_v, i) {
        if (fmt.hourOfDay(hours[i].timestamp) !== 0) return "";
        return this.chart.width < 600 ? fmt.weekday(hours[i].timestamp) : fmt.weekdayDate(hours[i].timestamp);
      },
    },
  };
  const tooltip = {
    callbacks: {
      title: (items) => `${fmt.weekdayDate(hours[items[0].dataIndex].timestamp)}, ${fmt.time(hours[items[0].dataIndex].timestamp)} Uhr`,
      label: (item) => {
        const h = hours[item.dataIndex];
        if (h.status !== "valid") return ` Keine gültige Messung: ${STATUS_LABELS[h.status] ?? h.status}`;
        return item.dataset.id === "wind"
          ? ` Wind: ${fmt.num(h.wind_speed_ms, 2)} m/s (Nabe ${fmt.num(h.hub_wind_ms, 2)} m/s)`
          : ` Leistung: ${fmt.int(h.power_kw)} kW`;
      },
    },
  };
  const lineDataset = (id, label, values, fill) => ({
    id,
    label,
    data: values,
    borderColor: series,
    backgroundColor: fill ? withAlpha(series, 0.1) : series,
    fill: fill ? "origin" : false,
    borderWidth: 2,
    pointRadius: 0,
    pointHoverRadius: 4,
    spanGaps: false,
  });
  const options = (datasetId, { yExtra = {}, extraPlugins = {} } = {}) => ({
    ...baseOptions(),
    interaction: { mode: "index", intersect: false },
    plugins: {
      legend: { display: false },
      gapBands: { indices: invalid, color: cssVar("--gap") },
      // gültige Stunde → Messwert zeigen; ungültige Stunde → einmal den Grund (über die Hilfsreihe)
      tooltip: { ...tooltip, filter: (item) => (hours[item.dataIndex].status === "valid" ? item.dataset.id === datasetId : item.dataset.id === "helper") },
      ...extraPlugins,
    },
    scales: {
      x: xAxis,
      y: {
        beginAtZero: true,
        grid: { color: cssVar("--grid") },
        border: { display: false },
        ticks: { color: muted, maxTicksLimit: 5, callback: (v) => fmt.int(v) },
        afterFit: (scale) => { scale.width = Y_AXIS_WIDTH; },
        ...yExtra,
      },
    },
  });
  const labels = hours.map((h) => h.timestamp);
  // Unsichtbare Hilfsreihe (überall 0), damit der Tooltip auch über ungültigen Stunden erscheint
  const helper = { id: "helper", data: hours.map(() => 0), pointRadius: 0, pointHoverRadius: 0, borderWidth: 0, showLine: false };

  drawChart("wind-chart", {
    type: "line",
    data: { labels, datasets: [lineDataset("wind", "Wind", hours.map((h) => h.wind_speed_ms), false), helper] },
    options: options("wind"),
    plugins: [gapBands],
  });

  const rated = lastYield?.inputs.rated_power_kw ?? null;
  drawChart("power-chart", {
    type: "line",
    data: { labels, datasets: [lineDataset("power", "Leistung", hours.map((h) => h.power_kw), true), { ...helper }] },
    options: options("power", {
      yExtra: rated ? { suggestedMax: rated * 1.1 } : {},
      extraPlugins: { referenceLine: { value: rated, label: rated ? `Nennleistung ${fmt.int(rated)} kW` : "", color: cssVar("--axis"), textColor: muted } },
    }),
    plugins: [gapBands, referenceLine],
  });
}

// ---------- Betrieb ----------

function renderStatus(status, freshness) {
  const sync = status.last_sync;
  const fresh = freshness.status === "ok";
  const level = !sync ? "" : !sync.ok ? "critical" : fresh ? "good" : "warning";
  const text = !sync ? "Sync startet …" : !sync.ok ? "Letzter Sync fehlgeschlagen" : fresh ? "Live · Daten aktuell" : "Daten veraltet";
  $("sync-badge").querySelector(".dot").className = `dot ${level}`;
  $("sync-label").textContent = text;

  const rows = [
    ["Letzter Sync", sync ? statusLabel(sync.ok ? "good" : "critical", `${fmt.time(sync.finished_at)} Uhr · ${sync.ok ? "OK" : "Fehler"}`) : "–"],
    ["Letzter Abruf", sync?.ok ? `${fmt.int(sync.fetched)} Werte · ${fmt.int(sync.written)} neu` : "–"],
    ["Neuester Messwert", freshness.latest_measurement_at ? statusLabel(fresh ? "good" : "warning", `${fmt.time(freshness.latest_measurement_at)} Uhr (vor ${freshness.age_minutes} min)`) : "–"],
    ["Sync-Intervall", status.sync_interval_minutes ? `alle ${status.sync_interval_minutes} min` : "–"],
    ["Gespeicherte Stunden", fmt.int(status.measurements_total)],
  ];
  if (sync && !sync.ok) rows.splice(1, 0, ["Fehler", sync.error]);
  setFacts("ops", rows);
}

// ---------- Reiter ----------

const TAB_HASHES = { year: "#12-monate", week: "#7-tage" };

function selectTab(name) {
  history.replaceState(null, "", TAB_HASHES[name]);
  for (const tab of ["year", "week"]) {
    const selected = tab === name;
    $(`tab-${tab}`).setAttribute("aria-selected", String(selected));
    $(`tab-${tab}`).tabIndex = selected ? 0 : -1;
    $(`panel-${tab}`).hidden = !selected;
  }
  // Diagramme erst zeichnen, wenn der Bereich sichtbar ist (sonst kennt Chart.js die Breite nicht)
  if (name === "week" && lastRecent) renderRecentCharts(lastRecent);
}

$("tab-year").addEventListener("click", () => selectTab("year"));
$("tab-week").addEventListener("click", () => selectTab("week"));
document.querySelector(".tabs").addEventListener("keydown", (e) => {
  if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
  const next = $("tab-year").getAttribute("aria-selected") === "true" ? "week" : "year";
  selectTab(next);
  $(`tab-${next}`).focus();
});

// ---------- Laden ----------

async function fetchJson(url) {
  const response = await fetch(url, { cache: "no-store" });
  return { ok: response.ok, body: await response.json() };
}

async function load() {
  try {
    const [yieldRes, recentRes, statusRes, freshRes] = await Promise.all(
      ["/api/yield", "/api/recent?days=7", "/api/status", "/health/data"].map(fetchJson),
    );
    if (yieldRes.ok) {
      lastYield = yieldRes.body;
      renderYield(lastYield);
      document.body.classList.remove("loading");
      $("notice").hidden = true;
    } else {
      $("notice").textContent = yieldRes.body.detail ?? "Ergebnis gerade nicht verfügbar.";
      $("notice").hidden = false;
    }
    if (recentRes.ok) {
      lastRecent = recentRes.body;
      renderRecent(lastRecent);
    }
    renderStatus(statusRes.body, freshRes.body);
    $("refreshed").textContent = `zuletzt ${fmt.time(new Date().toISOString())} Uhr`;
  } catch {
    $("notice").textContent = "Backend nicht erreichbar – neuer Versuch in 5 Minuten.";
    $("notice").hidden = false;
  }
}

// Hell/Dunkel gewechselt → Diagramme mit den neuen Farben neu zeichnen
window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
  if (lastYield) renderYield(lastYield);
  if (lastRecent && !$("panel-week").hidden) renderRecentCharts(lastRecent);
});

// Direkt verlinkbare Ansicht: /#7-tage öffnet den 7-Tage-Reiter
if (location.hash === TAB_HASHES.week) selectTab("week");

load();
setInterval(load, REFRESH_MS);
