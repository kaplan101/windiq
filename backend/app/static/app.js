// Lädt Ergebnis, 7-Tage-Verlauf und Betriebsstatus aus dem Backend und zeigt sie an. Kein Build-Schritt, kein Framework.
//
// Beide Reiter haben dieselben Diagrammarten in anderer Auflösung:
//   Energie-Balken (gemessen + aufgefüllt):  12 Monate → pro Monat   · 7 Tage → pro Tag
//   Wind- und Leistungs-Verlauf:             12 Monate → Tagesmittel · 7 Tage → stündlich

const REFRESH_MS = 60 * 1000;
const TIME_ZONE = "Europe/Berlin";
const Y_AXIS_WIDTH = 48; // gleich breit in übereinanderliegenden Diagrammen, damit die Zeitachsen exakt passen
const hourFormat = new Intl.DateTimeFormat("de-DE", { timeZone: TIME_ZONE, hour: "numeric", hourCycle: "h23" });

const fmt = {
  mwh: (v) => v.toLocaleString("de-DE", { maximumFractionDigits: 0 }),
  mwh1: (v) => v.toLocaleString("de-DE", { minimumFractionDigits: 1, maximumFractionDigits: 1 }),
  int: (v) => Math.round(v).toLocaleString("de-DE"),
  pct: (v, digits = 1) => v.toLocaleString("de-DE", { style: "percent", minimumFractionDigits: digits, maximumFractionDigits: digits }),
  num: (v, digits) => v.toLocaleString("de-DE", { minimumFractionDigits: digits, maximumFractionDigits: digits }),
  date: (iso) => new Date(iso).toLocaleDateString("de-DE", { timeZone: TIME_ZONE, day: "2-digit", month: "2-digit", year: "numeric" }),
  dateTime: (iso) => new Date(iso).toLocaleString("de-DE", { timeZone: TIME_ZONE, day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" }),
  time: (iso) => new Date(iso).toLocaleTimeString("de-DE", { timeZone: TIME_ZONE, hour: "2-digit", minute: "2-digit" }),
  weekday: (iso) => new Date(iso).toLocaleDateString("de-DE", { timeZone: TIME_ZONE, weekday: "short" }),
  weekdayDate: (iso) => new Date(iso).toLocaleDateString("de-DE", { timeZone: TIME_ZONE, weekday: "short", day: "2-digit", month: "2-digit" }),
  hourOfDay: (iso) => Number(hourFormat.formatToParts(new Date(iso)).find((part) => part.type === "hour").value),
  month: (ym) => new Date(`${ym}-01T00:00:00Z`).toLocaleDateString("de-DE", { timeZone: "UTC", month: "short", year: "2-digit" }),
  // Kalendertage kommen als "2026-02-18" (deutsche Zeit) – ohne Zeitzonen-Umrechnung anzeigen
  day: (d) => new Date(`${d}T12:00:00Z`).toLocaleDateString("de-DE", { timeZone: "UTC", weekday: "short", day: "2-digit", month: "2-digit", year: "numeric" }),
  dayShort: (d) => new Date(`${d}T12:00:00Z`).toLocaleDateString("de-DE", { timeZone: "UTC", weekday: "short", day: "2-digit", month: "2-digit" }),
  monthOfDay: (d) => new Date(`${d}T12:00:00Z`).toLocaleDateString("de-DE", { timeZone: "UTC", month: "short" }),
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

const VERSION_TIP =
  "Die Stammdaten kommen versioniert aus der WindIQ-API. Ändert WindIQ sie, zum Beispiel die Verluste, " +
  "steigt die Version und das Ergebnis wird automatisch mit den neuen Werten berechnet.";

const charts = {};
let lastYield = null;
let lastRecent = null;

const $ = (id) => document.getElementById(id);
const cssVar = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const isVisible = (panelId) => !$(panelId).hidden;

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
      if (term instanceof Node) dt.append(term); else dt.textContent = term;
      if (value instanceof Node) dd.append(value); else dd.textContent = value;
      return [dt, dd];
    }),
  );
}

function withInfo(text, tip) {
  const info = Object.assign(document.createElement("span"), { className: "info", tabIndex: 0, textContent: "i" });
  info.setAttribute("role", "button");
  info.setAttribute("aria-label", `Erklärung ${text}`);
  info.dataset.tip = tip;
  const wrap = document.createElement("span");
  wrap.append(text, info);
  return wrap;
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

// ---------- Diagramm-Bausteine ----------

const axisColors = () => ({ muted: cssVar("--text-muted"), grid: cssVar("--grid"), axis: cssVar("--axis") });

// Gestapelte Balken: gemessen (unten) + aufgefüllt (oben). rows: { label, title, measured, filled, footer }
function energyBarChart(id, rows) {
  const { muted, grid, axis } = axisColors();
  const isTopSegment = (ctx) => ctx.datasetIndex === 1 || rows[ctx.dataIndex].filled === 0;
  const datasets = [
    { label: "Gemessen", data: rows.map((r) => r.measured), backgroundColor: cssVar("--series-1") },
    {
      label: "Aufgefüllt (geschätzt)",
      data: rows.map((r) => r.filled),
      backgroundColor: cssVar("--series-2"),
      // 2 px Abstand in Flächenfarbe zum Segment darunter
      borderColor: cssVar("--surface"),
      borderWidth: (ctx) => (rows[ctx.dataIndex].filled > 0 ? { top: 0, right: 0, left: 0, bottom: 2 } : 0),
      borderSkipped: false,
    },
  ].map((ds) => ({ ...ds, stack: "energy", maxBarThickness: 24, borderRadius: (ctx) => (isTopSegment(ctx) ? { topLeft: 4, topRight: 4 } : 0) }));

  drawChart(id, {
    type: "bar",
    data: { labels: rows.map((r) => r.label), datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            title: (items) => rows[items[0].dataIndex].title,
            label: (item) => ` ${item.dataset.label}: ${fmt.mwh1(item.parsed.y)} MWh`,
            footer: (items) => rows[items[0].dataIndex].footer,
          },
        },
      },
      scales: {
        x: { stacked: true, grid: { display: false }, border: { color: axis }, ticks: { color: muted } },
        y: { stacked: true, beginAtZero: true, grid: { color: grid }, border: { display: false }, ticks: { color: muted, callback: (v) => fmt.int(v) } },
      },
    },
  });
}

// Graue Bänder hinter Punkten ohne gültige Messung
const gapBands = {
  id: "gapBands",
  beforeDatasetsDraw(chart, _args, opts) {
    const { ctx, chartArea, scales: { x } } = chart;
    const width = x.getPixelForValue(1) - x.getPixelForValue(0);
    ctx.save();
    ctx.fillStyle = opts.color;
    for (const i of opts.indices) {
      ctx.fillRect(x.getPixelForValue(i) - width / 2, chartArea.top, Math.max(width, 1), chartArea.bottom - chartArea.top);
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

// Zwei Verläufe übereinander mit gemeinsamer Zeitachse: Wind (oben) und Leistung (unten).
// points: { wind, power, valid } · tick(i, chart) → Achsenbeschriftung · title(i), windText(i), powerText(i), invalidText(i) → Tooltip
function windAndPowerCharts({ windId, powerId, points, tick, title, windText, powerText, invalidText, footer }) {
  const { muted, grid, axis } = axisColors();
  const series = cssVar("--series-1");
  const invalid = points.flatMap((p, i) => (p.valid ? [] : [i]));
  const rated = lastYield?.inputs.rated_power_kw ?? null;

  const lineDataset = (id, values, fill) => ({
    id,
    data: values,
    borderColor: series,
    backgroundColor: fill ? withAlpha(series, 0.1) : series,
    fill: fill ? "origin" : false,
    borderWidth: 2,
    pointRadius: 0,
    pointHoverRadius: 4,
    spanGaps: false,
  });
  // Unsichtbare Hilfsreihe (überall 0), damit der Tooltip auch über ungültigen Punkten erscheint
  const helper = () => ({ id: "helper", data: points.map(() => 0), pointRadius: 0, pointHoverRadius: 0, borderWidth: 0, showLine: false });

  const options = (datasetId, text, extra = {}) => ({
    responsive: true,
    maintainAspectRatio: false,
    animation: false,
    interaction: { mode: "index", intersect: false },
    plugins: {
      legend: { display: false },
      gapBands: { indices: invalid, color: cssVar("--gap") },
      tooltip: {
        // gültiger Punkt → Messwert; ungültiger Punkt → einmal den Grund (über die Hilfsreihe)
        filter: (item) => (points[item.dataIndex].valid ? item.dataset.id === datasetId : item.dataset.id === "helper"),
        callbacks: {
          title: (items) => title(items[0].dataIndex),
          label: (item) => ` ${points[item.dataIndex].valid ? text(item.dataIndex) : invalidText(item.dataIndex)}`,
          footer: (items) => (footer ? footer(items[0].dataIndex) : ""),
        },
      },
      ...extra.plugins,
    },
    scales: {
      x: { grid: { display: false }, border: { color: axis }, ticks: { color: muted, autoSkip: false, maxRotation: 0, callback(_v, i) { return tick(i, this.chart); } } },
      y: {
        beginAtZero: true,
        grid: { color: grid },
        border: { display: false },
        ticks: { color: muted, maxTicksLimit: 5, callback: (v) => fmt.int(v) },
        afterFit: (scale) => { scale.width = Y_AXIS_WIDTH; },
        ...extra.y,
      },
    },
  });

  const labels = points.map((_p, i) => i);
  drawChart(windId, {
    type: "line",
    data: { labels, datasets: [lineDataset("wind", points.map((p) => p.wind), false), helper()] },
    options: options("wind", windText),
    plugins: [gapBands],
  });
  drawChart(powerId, {
    type: "line",
    data: { labels, datasets: [lineDataset("power", points.map((p) => p.power), true), helper()] },
    options: options("power", powerText, {
      y: rated ? { suggestedMax: rated * 1.1 } : {},
      plugins: { referenceLine: { value: rated, label: rated ? `Nennleistung ${fmt.int(rated)} kW` : "", color: axis, textColor: muted } },
    }),
    plugins: [gapBands, referenceLine],
  });
}

// Tage werden nach deutscher Uhrzeit gebildet → am Tag der Zeitumstellung 23 bzw. 25 Stunden.
// Nur bei vollständigen Tagen prüfen (der erste Tag des Zeitraums und heute sind ohnehin unvollständig).
function dstNote(day, isEdgeOfRange) {
  if (isEdgeOfRange) return "";
  if (day.hours === 23) return "Beginn der Sommerzeit – dieser Tag hat 23 Stunden";
  if (day.hours === 25) return "Ende der Sommerzeit – dieser Tag hat 25 Stunden";
  return "";
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
    [withInfo("Anlagendaten", VERSION_TIP), `Version ${inp.turbine_version} vom ${fmt.date(inp.turbine_updated_at)}`],
    [withInfo("Standortdaten", VERSION_TIP), `Version ${inp.site_version} vom ${fmt.date(inp.site_updated_at)}`],
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

  $("weekly-table").replaceChildren(
    ...y.daily.slice(-7).map((d, i, days) => {
      const today = i === days.length - 1;
      const cells = [
        `${fmt.dayShort(d.day)}${today ? "*" : ""}`,
        fmt.mwh1(d.measured_mwh),
        fmt.mwh1(d.filled_mwh),
        fmt.mwh1(d.measured_mwh + d.filled_mwh),
        `${fmt.int(d.valid_hours)} / ${fmt.int(d.hours)}${dstNote(d, today) ? " (Zeitumstellung)" : ""}`,
        d.mean_wind_ms == null ? "–" : fmt.num(d.mean_wind_ms, 1),
        d.mean_power_kw == null ? "–" : fmt.int(d.mean_power_kw),
      ];
      const tr = document.createElement("tr");
      tr.replaceChildren(...cells.map((text) => Object.assign(document.createElement("td"), { textContent: text })));
      return tr;
    }),
  );

  if (isVisible("panel-year")) renderYearCharts(y);
  if (isVisible("panel-week") && lastRecent) renderWeekCharts(lastRecent, y);
}

function renderYearCharts(y) {
  energyBarChart(
    "year-energy",
    y.monthly.map((m) => ({
      label: isPartialMonth(m) ? `${fmt.month(m.month)}*` : fmt.month(m.month),
      title: isPartialMonth(m) ? `${fmt.month(m.month)} (Teilmonat, ${fmt.int(m.hours)} h)` : fmt.month(m.month),
      measured: m.measured_mwh,
      filled: m.filled_mwh,
      footer: `Gesamt: ${fmt.mwh1(m.measured_mwh + m.filled_mwh)} MWh · ${fmt.int(m.valid_hours)} / ${fmt.int(m.hours)} h gültig`,
    })),
  );

  const days = y.daily;
  windAndPowerCharts({
    windId: "year-wind",
    powerId: "year-power",
    points: days.map((d) => ({ wind: d.mean_wind_ms, power: d.mean_power_kw, valid: d.valid_hours > 0 })),
    // am Monatsersten den Monat anschreiben
    tick: (i) => (days[i].day.endsWith("-01") ? fmt.monthOfDay(days[i].day) : ""),
    title: (i) => fmt.day(days[i].day),
    windText: (i) => `Ø Wind: ${fmt.num(days[i].mean_wind_ms, 1)} m/s`,
    powerText: (i) => `Ø Leistung: ${fmt.int(days[i].mean_power_kw)} kW`,
    invalidText: () => "Keine gültige Messung an diesem Tag",
    footer: (i) => [
      `${fmt.int(days[i].valid_hours)} von ${fmt.int(days[i].hours)} Stunden gültig`,
      dstNote(days[i], i === 0 || i === days.length - 1),
    ].filter(Boolean),
  });
}

// ---------- 7 Tage ----------

function renderRecent(r) {
  $("week-stat-energy").textContent = `${fmt.mwh1(r.energy_mwh)} MWh`;
  $("week-stat-wind").textContent = r.mean_wind_ms == null ? "–" : `${fmt.num(r.mean_wind_ms, 1)} m/s`;
  $("week-stat-coverage").textContent = fmt.pct(r.coverage);
  if (isVisible("panel-week") && lastYield) renderWeekCharts(r, lastYield);
}

function renderWeekCharts(r, y) {
  const days = y.daily.slice(-7);
  energyBarChart(
    "week-energy-chart",
    days.map((d, i) => {
      const today = i === days.length - 1;
      return {
        label: `${fmt.dayShort(d.day)}${today ? "*" : ""}`,
        title: today ? `${fmt.day(d.day)} (heute, bis jetzt)` : fmt.day(d.day),
        measured: d.measured_mwh,
        filled: d.filled_mwh,
        footer: [
          `Gesamt: ${fmt.mwh1(d.measured_mwh + d.filled_mwh)} MWh · ${fmt.int(d.valid_hours)} / ${fmt.int(d.hours)} h gültig`,
          dstNote(d, today),
        ].filter(Boolean),
      };
    }),
  );

  const hours = r.hours;
  windAndPowerCharts({
    windId: "week-wind",
    powerId: "week-power",
    points: hours.map((h) => ({ wind: h.wind_speed_ms, power: h.power_kw, valid: h.status === "valid" })),
    // nur um Mitternacht beschriften: „Mo., 26.10.“ – auf schmalen Bildschirmen nur „Mo.“
    tick: (i, chart) => {
      if (fmt.hourOfDay(hours[i].timestamp) !== 0) return "";
      return chart.width < 600 ? fmt.weekday(hours[i].timestamp) : fmt.weekdayDate(hours[i].timestamp);
    },
    title: (i) => `${fmt.weekdayDate(hours[i].timestamp)}, ${fmt.time(hours[i].timestamp)} Uhr`,
    windText: (i) => `Wind: ${fmt.num(hours[i].wind_speed_ms, 2)} m/s (Nabe ${fmt.num(hours[i].hub_wind_ms, 2)} m/s)`,
    powerText: (i) => `Leistung: ${fmt.int(hours[i].power_kw)} kW`,
    invalidText: (i) => `Keine gültige Messung: ${STATUS_LABELS[hours[i].status] ?? hours[i].status}`,
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

  const latest = freshness.latest_measurement_at;
  const rows = [
    ["Letzter Sync", sync ? statusLabel(sync.ok ? "good" : "critical", `${fmt.time(sync.finished_at)} Uhr · ${sync.ok ? "OK" : "Fehler"}`) : "–"],
    ["Neueste Messstunde", latest ? statusLabel(fresh ? "good" : "warning", `${hourRange(latest)} Uhr`) : "–"],
    ["Nächster Sync", status.next_sync_at ? `${fmt.time(status.next_sync_at)} Uhr (alle ${status.sync_interval_minutes} min)` : "–"],
    ["Gespeicherte Stunden", fmt.int(status.measurements_total)],
  ];
  if (sync && !sync.ok) rows.splice(1, 0, ["Fehler", sync.error]);
  setFacts("ops", rows);

  const hints = [];
  const pending = pendingHour(latest);
  if (pending) hints.push(`Wert für ${hourRange(pending)} Uhr noch nicht von WindIQ geliefert – wird beim nächsten Sync nachgeholt.`);
  if (sync?.skipped) hints.push(`${fmt.int(sync.skipped)} unlesbare(r) Messwert(e) übersprungen – kommt eine Korrektur, wird sie automatisch übernommen.`);
  if (sync?.reference_error) hints.push(`Neue Stammdaten abgelehnt (${sync.reference_error}) – es wird mit dem letzten gültigen Stand gerechnet.`);
  $("ops-hint").hidden = hints.length === 0;
  $("ops-hint").replaceChildren(...hints.map((text) => statusLabel("warning", text)));
}

const HOUR_MS = 60 * 60 * 1000;

// „18–19“: ein Messwert gilt für die ganze Stunde ab seinem Zeitstempel
function hourRange(iso) {
  const start = new Date(iso);
  return `${fmt.hourOfDay(start.toISOString())}–${fmt.hourOfDay(new Date(start.getTime() + HOUR_MS).toISOString())}`;
}

// Fehlt der Wert der aktuellen Stunde, obwohl er normalerweise längst da wäre (WindIQ liefert ~6 min nach
// Stundenbeginn, unser Sync holt ihn spätestens zur nächsten Viertelstunde), liefert dies die fehlende Stunde.
function pendingHour(latestIso) {
  if (!latestIso) return null;
  const now = Date.now();
  const currentHourStart = Math.floor(now / HOUR_MS) * HOUR_MS;
  const expectedBy = currentHourStart + 20 * 60 * 1000;
  const nextExpected = new Date(latestIso).getTime() + HOUR_MS;
  return nextExpected <= currentHourStart && now >= expectedBy ? new Date(nextExpected).toISOString() : null;
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
  if (name === "year" && lastYield) renderYearCharts(lastYield);
  if (name === "week" && lastRecent && lastYield) renderWeekCharts(lastRecent, lastYield);
}

$("tab-year").addEventListener("click", () => selectTab("year"));
$("tab-week").addEventListener("click", () => selectTab("week"));
document.querySelector(".tabs").addEventListener("keydown", (e) => {
  if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
  const next = $("tab-year").getAttribute("aria-selected") === "true" ? "week" : "year";
  selectTab(next);
  $(`tab-${next}`).focus();
});

// ---------- Hell/Dunkel ----------

function redrawVisibleCharts() {
  if (!lastYield) return;
  if (isVisible("panel-year")) renderYearCharts(lastYield);
  if (isVisible("panel-week") && lastRecent) renderWeekCharts(lastRecent, lastYield);
}

$("theme-toggle").addEventListener("click", () => {
  const next = document.documentElement.dataset.theme === "light" ? "dark" : "light";
  document.documentElement.dataset.theme = next;
  try { localStorage.setItem("theme", next); } catch { /* ohne Speicher: gilt nur bis zum Neuladen */ }
  redrawVisibleCharts();
});

// ---------- Erklär-Symbole (i) ----------
// Maus: beim Darüberfahren · Touch: Antippen öffnet/schließt · Tastatur: Fokus · Box bleibt immer im Bildschirm

const tipBox = $("tip-box");
let openTip = null;

function showTip(el) {
  if (openTip && openTip !== el) openTip.setAttribute("aria-expanded", "false");
  openTip = el;
  el.setAttribute("aria-expanded", "true");
  tipBox.textContent = el.dataset.tip;
  tipBox.hidden = false;
  const width = Math.min(280, window.innerWidth - 16);
  tipBox.style.width = `${width}px`;
  const rect = el.getBoundingClientRect();
  const left = Math.max(8, Math.min(rect.left + rect.width / 2 - width / 2, window.innerWidth - width - 8));
  tipBox.style.left = `${left + window.scrollX}px`;
  tipBox.style.top = `${rect.bottom + 8 + window.scrollY}px`;
}

function hideTip() {
  openTip?.setAttribute("aria-expanded", "false");
  openTip = null;
  tipBox.hidden = true;
}

document.addEventListener("pointerover", (e) => {
  const el = e.target.closest?.(".info");
  if (el && e.pointerType === "mouse") showTip(el);
});
document.addEventListener("pointerout", (e) => {
  const el = e.target.closest?.(".info");
  if (el && e.pointerType === "mouse" && !el.contains(e.relatedTarget)) hideTip();
});
document.addEventListener("click", (e) => {
  const el = e.target.closest?.(".info");
  if (!el) return hideTip();
  // Bei Touch öffnet/schließt Antippen; bei der Maus ist die Box durch Hover schon offen
  if (e.pointerType !== "mouse" && openTip === el) hideTip(); else showTip(el);
});
document.addEventListener("focusin", (e) => {
  const el = e.target.closest?.(".info");
  if (el && el.matches(":focus-visible")) showTip(el);
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") hideTip();
  const el = e.target.closest?.(".info");
  if (el && (e.key === "Enter" || e.key === " ")) {
    e.preventDefault();
    openTip === el ? hideTip() : showTip(el);
  }
});
window.addEventListener("resize", hideTip);

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
    if (recentRes.ok) lastRecent = recentRes.body;
    if (yieldRes.ok) {
      lastYield = yieldRes.body;
      renderYield(lastYield);
      document.body.classList.remove("loading");
      $("notice").hidden = true;
    } else {
      $("notice").textContent = yieldRes.body.detail ?? "Ergebnis gerade nicht verfügbar.";
      $("notice").hidden = false;
    }
    if (lastRecent) renderRecent(lastRecent);
    renderStatus(statusRes.body, freshRes.body);
    $("refreshed").textContent = `zuletzt ${fmt.time(new Date().toISOString())} Uhr`;
  } catch {
    $("notice").textContent = "Backend nicht erreichbar – neuer Versuch in einer Minute.";
    $("notice").hidden = false;
  }
}

// Direkt verlinkbare Ansicht: /#7-tage öffnet den 7-Tage-Reiter
if (location.hash === TAB_HASHES.week) selectTab("week");

load();
setInterval(load, REFRESH_MS);
// Browser bremsen Zeitgeber in Hintergrund-Tabs aus → beim Zurückkehren sofort aktualisieren
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible") load();
});
