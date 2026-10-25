// Lädt Ergebnis und Betriebsstatus aus dem Backend und zeigt sie an. Kein Build-Schritt, kein Framework.

const REFRESH_MS = 5 * 60 * 1000;
const TIME_ZONE = "Europe/Berlin";

const fmt = {
  mwh: (v) => v.toLocaleString("de-DE", { maximumFractionDigits: 0 }),
  mwh1: (v) => v.toLocaleString("de-DE", { minimumFractionDigits: 1, maximumFractionDigits: 1 }),
  int: (v) => v.toLocaleString("de-DE"),
  pct: (v, digits = 1) => v.toLocaleString("de-DE", { style: "percent", minimumFractionDigits: digits, maximumFractionDigits: digits }),
  num: (v, digits) => v.toLocaleString("de-DE", { minimumFractionDigits: digits, maximumFractionDigits: digits }),
  dateTime: (iso) => new Date(iso).toLocaleString("de-DE", { timeZone: TIME_ZONE, day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" }),
  time: (iso) => new Date(iso).toLocaleTimeString("de-DE", { timeZone: TIME_ZONE, hour: "2-digit", minute: "2-digit" }),
  month: (ym) => new Date(`${ym}-01T00:00:00Z`).toLocaleDateString("de-DE", { timeZone: "UTC", month: "short", year: "2-digit" }),
};

const QUALITY_LABELS = {
  valid: "Gültig",
  frozen: "Eingefroren (Wiederholung)",
  sensor_error: "Sensorfehler (−999)",
  missing: "Kein Wert (null)",
  outlier: "Unplausibel (< 0 oder > 40 m/s)",
  invalid: "Kein Zahlenwert",
  unknown_unit: "Unbekannte Einheit",
  no_record: "Kein Datensatz",
};

let chart = null;
let lastYield = null;

const $ = (id) => document.getElementById(id);
const cssVar = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

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

function renderYield(y) {
  const inp = y.inputs;
  $("subtitle").textContent = `${inp.mast_name} · ${inp.turbine_name} · ${inp.site_name}`;
  $("p50").textContent = fmt.mwh(y.p50_mwh);
  $("p90").textContent = fmt.mwh(y.p90_mwh);
  $("gross").textContent = fmt.mwh(y.aep_gross_mwh);
  $("coverage").textContent = fmt.pct(y.coverage);
  $("coverage-bar").style.width = `${(y.coverage * 100).toFixed(1)}%`;
  $("measured").textContent = `${fmt.int(y.hours_valid)} von ${fmt.int(y.hours_total)} Stunden gemessen`;
  $("window").textContent = `Letzte 12 Monate: ${fmt.dateTime(y.window_start)} – ${fmt.dateTime(y.window_end)}`;

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
      .map(([key, count]) => [QUALITY_LABELS[key] ?? key, `${fmt.int(count)} (${fmt.pct(count / y.hours_total)})`]),
  );

  $("monthly-table").replaceChildren(
    ...y.monthly.map((m) => {
      const tr = document.createElement("tr");
      const cells = [fmt.month(m.month), fmt.mwh1(m.measured_mwh), fmt.mwh1(m.filled_mwh), fmt.mwh1(m.measured_mwh + m.filled_mwh), `${fmt.int(m.valid_hours)} / ${fmt.int(m.hours)}`];
      tr.replaceChildren(...cells.map((text) => Object.assign(document.createElement("td"), { textContent: text })));
      return tr;
    }),
  );

  renderChart(y.monthly);
}

function renderChart(monthly) {
  const surface = cssVar("--surface");
  const muted = cssVar("--text-muted");
  const grid = cssVar("--grid");
  const axis = cssVar("--axis");
  const isTopSegment = (ctx) => ctx.datasetIndex === 1 || monthly[ctx.dataIndex].filled_mwh === 0;

  const data = {
    labels: monthly.map((m) => fmt.month(m.month)),
    datasets: [
      { label: "Gemessen", data: monthly.map((m) => m.measured_mwh), backgroundColor: cssVar("--series-1") },
      {
        label: "Aufgefüllt (geschätzt)",
        data: monthly.map((m) => m.filled_mwh),
        backgroundColor: cssVar("--series-2"),
        // 2 px Abstand in Flächenfarbe zum Segment darunter
        borderColor: surface,
        borderWidth: (ctx) => (monthly[ctx.dataIndex].filled_mwh > 0 ? { top: 0, right: 0, left: 0, bottom: 2 } : 0),
        borderSkipped: false,
      },
    ].map((ds) => ({
      ...ds,
      stack: "energy",
      maxBarThickness: 24,
      borderRadius: (ctx) => (isTopSegment(ctx) ? { topLeft: 4, topRight: 4 } : 0),
    })),
  };

  const options = {
    responsive: true,
    maintainAspectRatio: false,
    animation: false,
    interaction: { mode: "index", intersect: false },
    plugins: {
      legend: { display: false },
      tooltip: {
        callbacks: {
          title: (items) => {
            const m = monthly[items[0].dataIndex];
            return m.hours < 672 ? `${items[0].label} (Teilmonat, ${fmt.int(m.hours)} h)` : items[0].label;
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
      x: { stacked: true, grid: { display: false }, border: { color: axis }, ticks: { color: muted } },
      y: {
        stacked: true,
        beginAtZero: true,
        grid: { color: grid },
        border: { display: false },
        ticks: { color: muted, callback: (v) => fmt.int(v) },
      },
    },
  };

  if (chart) chart.destroy();
  chart = new Chart($("monthly-chart"), { type: "bar", data, options });
}

function renderStatus(status, freshness) {
  const sync = status.last_sync;
  const fresh = freshness.status === "ok";
  const level = !sync ? "" : !sync.ok ? "critical" : fresh ? "good" : "warning";
  const text = !sync ? "Sync startet …" : !sync.ok ? "Letzter Sync fehlgeschlagen" : fresh ? "Live · Daten aktuell" : "Daten veraltet";
  $("sync-badge").querySelector(".dot").className = `dot ${level}`;
  $("sync-label").textContent = text;

  const rows = [
    ["Letzter Sync", sync ? statusLabel(sync.ok ? "good" : "critical", `${fmt.time(sync.finished_at)} · ${sync.ok ? "OK" : "Fehler"}`) : "–"],
    ["Abgerufen / gespeichert", sync?.ok ? `${fmt.int(sync.fetched)} / ${fmt.int(sync.written)}` : "–"],
    ["Neuester Messwert", freshness.latest_measurement_at ? statusLabel(fresh ? "good" : "warning", `${fmt.time(freshness.latest_measurement_at)} (vor ${freshness.age_minutes} min)`) : "–"],
    ["Sync-Intervall", status.sync_interval_minutes ? `alle ${status.sync_interval_minutes} min` : "–"],
    ["Gespeicherte Stunden", fmt.int(status.measurements_total)],
  ];
  if (sync && !sync.ok) rows.splice(1, 0, ["Fehler", sync.error]);
  setFacts("ops", rows);
}

async function fetchJson(url) {
  const response = await fetch(url, { cache: "no-store" });
  const body = await response.json();
  return { ok: response.ok, body };
}

async function load() {
  try {
    const [yieldRes, statusRes, freshRes] = await Promise.all([fetchJson("/api/yield"), fetchJson("/api/status"), fetchJson("/health/data")]);
    if (yieldRes.ok) {
      lastYield = yieldRes.body;
      renderYield(lastYield);
      $("notice").hidden = true;
    } else {
      $("notice").textContent = yieldRes.body.detail ?? "Ergebnis gerade nicht verfügbar.";
      $("notice").hidden = false;
    }
    renderStatus(statusRes.body, freshRes.body);
    $("refreshed").textContent = `zuletzt ${fmt.time(new Date().toISOString())}`;
  } catch (error) {
    $("notice").textContent = "Backend nicht erreichbar – neuer Versuch in 5 Minuten.";
    $("notice").hidden = false;
  }
}

// Hell/Dunkel gewechselt → Diagramm mit den neuen Farben neu zeichnen
window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => lastYield && renderChart(lastYield.monthly));

load();
setInterval(load, REFRESH_MS);
