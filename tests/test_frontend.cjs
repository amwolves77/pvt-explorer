// Exercise UI handlers and exports without a browser; Plotly and DOM are test doubles.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

class Element {
  constructor() {
    this.children = []; this.handlers = {}; this.attrs = {};
    this.style = {}; this.hidden = false; this.checked = false;
    this.classList = { toggle() {} };
  }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children; }
  setAttribute(key, value) { this.attrs[key] = value; }
  getAttribute(key) { return this.attrs[key]; }
  removeAttribute(key) { delete this.attrs[key]; }
  addEventListener(event, handler) { this.handlers[event] = handler; }
  click() { if (this.download) downloads.push(this.download); }
  remove() {}
  focus() {}
}
const elements = new Map();
const get = id => {
  if (!elements.has(id)) elements.set(id, new Element());
  return elements.get(id);
};
const controls = { OilAPI: 35, GasGravity: .75, ReservoirTempF: 180, BubblePointPsi: 2500, PMin: 500, PMax: 1500, PStep: 1000 };
for (const [key, value] of Object.entries(controls)) get(key).value = String(value);
get('lab-data').value = 'clipboard test';
get('pvt-form').dataset = { calculateUrl: '/api/calculate', validateUrl: '/api/lab/validate' };
get('calculated-tab').attrs['aria-controls'] = 'calculated-table';
get('lab-tab').attrs['aria-controls'] = 'lab-table';
get('pvt-form').requestSubmit = () => { pending = context.calculate(); };

const curves = ['Standing', 'Vasquez-Beggs'].flatMap(Correlation =>
  [500, 1500].map((Pressure, i) => ({ Correlation, Pressure, Rs: 100 + i, Bo: 1 + i, Viscosity: 2 + i })));
const calibration = ['Rs', 'Bo', 'Viscosity'].flatMap(property => ['Standing', 'Vasquez-Beggs'].map(correlation => ({
  property, correlation, unit: 'test', calibrated_curve: [7, 8], multiplier: 2, shift: 3,
  error_before: 1, error_after: 0, points_used: 2, outside_range: 0, message: '', status: 'fitted', metric: 'RMSE',
})));
const snapshot = {
  inputs: controls, pressures: [500, 1500], curves,
  lab: [{ Pressure_psia: 500, Rs_scf_stb: 0, Bo_rb_stb: null, Viscosity_cp: 2 },
        { Pressure_psia: 1500, Rs_scf_stb: 200, Bo_rb_stb: 1.2, Viscosity_cp: null }],
  missing_lab_values: { Rs_scf_stb: 0, Bo_rb_stb: 1, Viscosity_cp: 1 }, calculated_at: '2026-11-03T00:00:00Z',
};
const charts = new Map();
const blobs = []; const downloads = []; const requests = [];
let fail = false; let pending;
const context = vm.createContext({
  document: { getElementById: get, createElement: () => new Element(), body: new Element() },
  Intl, Date, Blob, setTimeout: () => 0, clearTimeout() {},
  URL: { createObjectURL(blob) { blobs.push(blob); return 'blob:test'; }, revokeObjectURL() {} },
  Plotly: { async react(id, traces) { charts.set(id, traces); } },
  async fetch(url, options) {
    const payload = JSON.parse(options.body); requests.push({ url, payload });
    return { ok: !fail, async json() {
      if (fail) return { error: 'Invalid pasted measurement' };
      return { ...snapshot, calibration_enabled: payload.calibrate, calibration: payload.calibrate ? calibration : [] };
    } };
  },
});
vm.runInContext(fs.readFileSync('static/app.js', 'utf8'), context);

(async () => {
  await context.calculate();
  assert.equal(get('results').hidden, false);
  assert.equal(get('input-fields').disabled, false);
  assert.equal(charts.size, 3);
  for (const traces of charts.values()) {
    assert.equal(traces.length, 3);
    assert.equal(traces[0].line.dash, 'dash');
    assert.equal(traces[2].mode, 'markers');
  }
  assert.equal(charts.get('bo-chart')[2].x.length, 1);
  assert.equal(charts.get('rs-chart')[2].y[0], 0);
  assert.equal(get('calibration-summary').hidden, true);

  get('calibrate').checked = true;
  get('calibrate').handlers.change();
  await pending;
  assert.equal(requests.at(-1).payload.calibrate, true);
  assert.equal(get('calibration-summary').hidden, false);
  for (const traces of charts.values()) {
    assert.equal(traces.length, 5);
    assert.equal(traces[0].line.dash, 'dash');
    assert.equal(traces[1].line.dash, 'solid');
    assert.equal(traces[1].y[0], 7);
  }
  get('export-results').handlers.click();
  const csv = await blobs.at(-1).text();
  assert.ok(csv.includes('"Rs_calibrated","Bo_calibrated","Viscosity_calibrated"'));
  assert.ok(csv.includes('"500","Standing","100","1","2","7","7","7"'));
  get('export-calibration').handlers.click();
  assert.ok((await blobs.at(-1).text()).includes('"points_used","outside_range","status","message"'));
  get('export-json').handlers.click();
  const exported = JSON.parse(await blobs.at(-1).text());
  assert.equal(exported.lab[0].Bo_rb_stb, null);
  assert.equal(exported.calibration.length, 6);
  assert.deepEqual(downloads, ['pvt-results.csv', 'pvt-calibration.csv', 'pvt-results.json']);

  get('pvt-form').handlers.input({ target: get('OilAPI') });
  assert.equal(get('results').hidden, true);
  get('export-results').handlers.click();
  assert.equal(downloads.length, 3);
  fail = true;
  await context.calculate();
  assert.equal(get('results').hidden, true);
  assert.equal(get('status').textContent, 'Invalid pasted measurement');
  assert.equal(get('input-fields').disabled, false);
  console.log('Frontend handlers, chart traces, missing values, calibration, exports and stale-result checks: PASS');
})().catch(error => { console.error(error); process.exitCode = 1; });
