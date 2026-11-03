"use strict";

const form = document.getElementById("pvt-form");
const labInput = document.getElementById("lab-data");
const inputFields = document.getElementById("input-fields");
const results = document.getElementById("results");
const emptyState = document.getElementById("empty-state");
const statusBox = document.getElementById("status");
const calibrateToggle = document.getElementById("calibrate");
const inputNames = ["OilAPI", "GasGravity", "ReservoirTempF", "BubblePointPsi", "PMin", "PMax", "PStep"];
let loadedData = null;
let labValidationTimer;
let labValidationVersion = 0;

function number(value, digits = 4) {
  return new Intl.NumberFormat("en", { maximumFractionDigits: digits }).format(value);
}

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function status(text, kind) {
  statusBox.textContent = text;
  statusBox.className = `status ${kind}`;
  statusBox.setAttribute("role", kind === "error" ? "alert" : "status");
}

function renderControls(data) {
  const controls = document.getElementById("controls");
  controls.replaceChildren();
  for (const [name, label, unit] of [
    ["OilAPI", "Oil gravity · OilAPI", "°API"],
    ["GasGravity", "Gas specific gravity · GasGravity", ""],
    ["ReservoirTempF", "Reservoir temperature · ReservoirTempF", "°F"],
    ["BubblePointPsi", "Bubble point · BubblePointPsi", "psia"],
  ]) {
    const group = element("div");
    const value = element("dd", number(data.inputs[name]));
    if (unit) value.append(element("small", unit));
    group.append(element("dt", label), value);
    controls.append(group);
  }
  const summary = document.getElementById("range-summary");
  summary.replaceChildren();
  for (const [name, label] of [["PMin", "PMin"], ["PMax", "PMax"], ["PStep", "PStep"]]) {
    const item = element("span", `${label}  `);
    item.append(element("strong", `${number(data.inputs[name])} ${name === "PStep" ? "psi" : "psia"}`));
    summary.append(item);
  }
  summary.append(element("span", `${number(data.pressures.length, 0)} calculated pressures · ${number(data.lab.length, 0)} lab rows`));
  if (data.pressures.at(-1) !== data.inputs.PMax) {
    summary.append(element("span", `Last grid pressure: ${number(data.pressures.at(-1))} psia (PMax is off-step)`));
  }
}

async function renderCharts(data) {
  const definitions = [
    ["rs-chart", "Rs", "Rs_scf_stb", "Rs (scf/STB)"],
    ["bo-chart", "Bo", "Bo_rb_stb", "Bo (rb/STB)"],
    ["viscosity-chart", "Viscosity", "Viscosity_cp", "Viscosity (cP)"],
  ];
  await Promise.all(definitions.map(([id, key, labKey, unit]) => {
    const traces = ["Standing", "Vasquez-Beggs"].flatMap((name, i) => {
      const rows = data.curves.filter(row => row.Correlation === name);
      const fit = data.calibration.find(item => item.property === key && item.correlation === name);
      const enabled = data.calibration_enabled;
      const rawName = enabled ? `${name} (original)` : name;
      const raw = {
        name: rawName, x: rows.map(row => row.Pressure), y: rows.map(row => row[key]),
        type: "scatter", mode: rows.length === 1 ? "markers" : "lines",
        line: { color: ["#087e83", "#ca7034"][i], width: 1.8, dash: "dash" },
        opacity: enabled ? 0.45 : 0.8,
        marker: { color: ["#087e83", "#ca7034"][i] },
        hovertemplate: `%{x:,.2f} psia<br>${unit}: %{y:.5g}<extra>${rawName}</extra>`,
      };
      if (!enabled || !fit?.calibrated_curve) return [raw];
      const calibratedName = `${name} (calibrated)`;
      return [raw, {
        ...raw, name: calibratedName, y: fit.calibrated_curve, opacity: 1,
        line: { color: ["#087e83", "#ca7034"][i], width: 2.5, dash: "solid" },
        hovertemplate: `%{x:,.2f} psia<br>${unit}: %{y:.5g}<extra>${calibratedName}</extra>`,
      }];
    });
    const measured = data.lab.filter(row => row[labKey] !== null);
    traces.push({
      name: "Laboratory", x: measured.map(row => row.Pressure_psia), y: measured.map(row => row[labKey]),
      type: "scatter", mode: "markers", marker: { color: "#172f3d", size: 7, line: { color: "white", width: 1 } },
      hovertemplate: `%{x:,.2f} psia<br>${unit}: %{y:.5g}<extra>Laboratory</extra>`,
    });
    return Plotly.react(id, traces, {
      margin: { l: 63, r: 18, t: 24, b: 53 }, showlegend: false,
      font: { family: "Segoe UI, Arial, sans-serif", size: 11, color: "#607280" },
      paper_bgcolor: "white", plot_bgcolor: "white", hovermode: "closest",
      xaxis: { title: { text: "Pressure (psia)", standoff: 12 }, gridcolor: "#edf1f2", zeroline: false, automargin: true },
      yaxis: { title: { text: unit, standoff: 10 }, gridcolor: "#edf1f2", zeroline: false, automargin: true },
      shapes: [{ type: "line", xref: "x", yref: "paper", x0: data.inputs.BubblePointPsi, x1: data.inputs.BubblePointPsi,
        y0: 0, y1: 1, line: { color: "#9daab3", dash: "dot", width: 1 }, layer: "below" }],
    }, { responsive: true, displaylogo: false, modeBarButtonsToRemove: ["select2d", "lasso2d"] });
  }));
}

function renderCalibration(data) {
  const enabled = data.calibration_enabled;
  document.getElementById("calibration-summary").hidden = !enabled;
  document.getElementById("calibration-legend").hidden = !enabled;
  if (!enabled) return;
  const rows = data.calibration.map(fit => ({
    Property: `${fit.property} (${fit.unit})`,
    Correlation: fit.property === "Viscosity" ? `Beggs-Robinson / ${fit.correlation} Rs` : fit.correlation,
    multiplier: fit.multiplier, shift: fit.shift,
    error_before: fit.error_before, error_after: fit.error_after,
  }));
  renderTable("calibration-table", rows, [["Property", "Property"], ["Correlation", "Correlation"],
    ["multiplier", "Multiplier"], ["shift", "Shift"], ["error_before", "Error Before"],
    ["error_after", "Error After"]], "Calibration coefficients and RMSE");
  const notes = data.calibration.flatMap(fit => {
    const details = [];
    if (fit.message) details.push(fit.message);
    if (fit.outside_range) details.push(`${fit.outside_range} measured point(s) outside the curve range excluded.`);
    return details.length ? [`${fit.property} / ${fit.correlation}: ${details.join(" ")} Points used: ${fit.points_used}.`] : [];
  });
  const note = document.getElementById("calibration-notes");
  note.textContent = notes.join("\n");
  note.style.whiteSpace = "pre-line";
  note.hidden = notes.length === 0;
}

function renderTable(target, rows, columns, caption) {
  const table = element("table");
  table.setAttribute("aria-label", caption);
  const header = element("tr");
  for (const [key, label] of columns) {
    const cell = element("th", label, ["Correlation", "Property"].includes(key) ? "text-cell" : "");
    cell.scope = "col";
    header.append(cell);
  }
  const head = element("thead"); head.append(header);
  const body = element("tbody");
  for (const row of rows) {
    const tr = element("tr");
    for (const [key] of columns) {
      const text = row[key] === null ? "—" : typeof row[key] === "number" ? number(row[key], 6) : row[key];
      tr.append(element("td", text, ["Correlation", "Property"].includes(key) ? "text-cell" : ""));
    }
    body.append(tr);
  }
  table.append(head, body);
  document.getElementById(target).replaceChildren(table);
}

function invalidateResults() {
  loadedData = null;
  results.hidden = true;
  emptyState.hidden = false;
}

async function postJSON(url, payload) {
  let response;
  try {
    response = await fetch(url, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload), cache: "no-store",
    });
  } catch {
    throw new Error("Could not reach the server. Check your connection and try again.");
  }
  let data;
  try { data = await response.json(); }
  catch { throw new Error("The server returned an unexpected response. Please retry."); }
  if (!response.ok) throw new Error(data.error || "Unable to process these inputs.");
  return data;
}

async function validatePaste(version) {
  const note = document.getElementById("paste-status");
  try {
    const data = await postJSON(form.dataset.validateUrl, { lab_text: labInput.value });
    if (version !== labValidationVersion) return;
    labInput.setAttribute("aria-invalid", "false");
    note.textContent = data.rows
      ? `${number(data.rows, 0)} lab rows parsed. ${number(data.missing, 0)} blank measurements will remain missing.`
      : "No laboratory data pasted. Raw curves can still be calculated.";
  } catch (error) {
    if (version !== labValidationVersion) return;
    labInput.setAttribute("aria-invalid", "true");
    note.textContent = error.message;
  }
}

async function calculate() {
  const payload = {
    inputs: Object.fromEntries(inputNames.map(name => [name, document.getElementById(name).value])),
    lab_text: labInput.value, calibrate: calibrateToggle.checked,
  };
  invalidateResults();
  emptyState.hidden = true;
  inputFields.disabled = true;
  form.setAttribute("aria-busy", "true");
  status("Calculating PVT curves" + (payload.calibrate ? " and calibrating to laboratory data..." : "..."), "neutral");
  try {
    const data = await postJSON(form.dataset.calculateUrl, payload);
    renderControls(data);
    const missing = Object.entries(data.missing_lab_values).filter(([, count]) => count > 0);
    const labNote = document.getElementById("lab-note");
    labNote.textContent = data.lab.length === 0 ? "No laboratory measurements supplied. Only raw correlations are shown."
      : `Missing laboratory measurements: ${missing.map(([key, count]) => `${key} (${count})`).join(", ")}. Shown as a dash in the table and omitted from the corresponding plot; no values are filled in.`;
    labNote.hidden = data.lab.length > 0 && missing.length === 0;
    renderTable("calculated-table", data.curves, [["Pressure", "Pressure (psia)"], ["Correlation", "Correlation"], ["Rs", "Rs (scf/STB)"], ["Bo", "Bo (rb/STB)"], ["Viscosity", "Viscosity (cP)"]], "Calculated PVT results");
    renderTable("lab-table", data.lab, [["Pressure_psia", "Pressure (psia)"], ["Rs_scf_stb", "Rs (scf/STB)"], ["Bo_rb_stb", "Bo (rb/STB)"], ["Viscosity_cp", "Viscosity (cP)"]], "Laboratory PVT measurements");
    document.getElementById("row-count").textContent = `${data.curves.length} calculated rows / ${data.lab.length} lab rows`;
    document.getElementById("export-calibration").hidden = !data.calibration_enabled;
    results.hidden = false;
    renderCalibration(data);
    await renderCharts(data);
    loadedData = data;
    const time = new Date(data.calculated_at).toLocaleTimeString();
    status(`Calculated at ${time}. ${data.pressures.length} pressure points and ${data.lab.length} laboratory rows.`, "success");
  } catch (error) {
    invalidateResults();
    status(error.message, "error");
  } finally {
    inputFields.disabled = false;
    form.removeAttribute("aria-busy");
  }
}

form.addEventListener("submit", event => { event.preventDefault(); calculate(); });
form.addEventListener("input", event => {
  if (event.target === calibrateToggle) return;
  invalidateResults();
  status("Inputs changed. Calculate PVT to update the results.", "neutral");
});
labInput.addEventListener("input", () => {
  clearTimeout(labValidationTimer);
  const version = ++labValidationVersion;
  labInput.removeAttribute("aria-invalid");
  document.getElementById("paste-status").textContent = "Checking pasted data...";
  labValidationTimer = setTimeout(() => validatePaste(version), 350);
});
calibrateToggle.addEventListener("change", () => {
  if (loadedData) form.requestSubmit();
});

function download(filename, content, mime) {
  const url = URL.createObjectURL(new Blob([content], { type: mime }));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function downloadCSV(filename, columns, rows) {
  const cell = value => value === null || value === undefined ? "" : `"${String(value).replaceAll('"', '""')}"`;
  const lines = [columns.map(cell).join(","), ...rows.map(row => columns.map(key => cell(row[key])).join(","))];
  download(filename, "\ufeff" + lines.join("\r\n"), "text/csv;charset=utf-8");
}

document.getElementById("export-results").addEventListener("click", () => {
  if (!loadedData) return;
  const columns = ["Pressure", "Correlation", "Rs", "Bo", "Viscosity"];
  const rows = loadedData.curves.map(row => ({ ...row }));
  if (loadedData.calibration_enabled) {
    for (const property of ["Rs", "Bo", "Viscosity"]) {
      const key = `${property}_calibrated`;
      columns.push(key);
      for (const correlation of ["Standing", "Vasquez-Beggs"]) {
        const fit = loadedData.calibration.find(item => item.property === property && item.correlation === correlation);
        rows.filter(row => row.Correlation === correlation).forEach((row, index) => {
          row[key] = fit?.calibrated_curve?.[index] ?? null;
        });
      }
    }
  }
  downloadCSV("pvt-results.csv", columns, rows);
});
document.getElementById("export-calibration").addEventListener("click", () => {
  if (!loadedData?.calibration_enabled) return;
  downloadCSV("pvt-calibration.csv", ["property", "correlation", "unit", "multiplier", "shift", "error_before", "error_after", "metric", "points_used", "outside_range", "status", "message"], loadedData.calibration);
});
document.getElementById("export-json").addEventListener("click", () => {
  if (loadedData) download("pvt-results.json", JSON.stringify(loadedData, null, 2), "application/json");
});

const tabs = [document.getElementById("calculated-tab"), document.getElementById("lab-tab")];
function selectTab(selected) {
  for (const tab of tabs) {
    const active = tab === selected;
    tab.classList.toggle("active", active);
    tab.setAttribute("aria-selected", String(active));
    tab.tabIndex = active ? 0 : -1;
    document.getElementById(tab.getAttribute("aria-controls")).hidden = !active;
  }
}
for (const tab of tabs) {
  tab.addEventListener("click", () => selectTab(tab));
  tab.addEventListener("keydown", event => {
    if (["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) {
      event.preventDefault();
      const next = event.key === "Home" ? tabs[0] : event.key === "End" ? tabs[1] : tabs[1 - tabs.indexOf(tab)];
      selectTab(next); next.focus();
    }
  });
}
