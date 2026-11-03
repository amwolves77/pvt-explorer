# PVT Correlation Explorer - Web

A Flask dashboard driven entirely by browser controls and pasted Excel table text.
The server does not open Excel workbooks, read local CSV data, accept file uploads,
or access files on the visitor's computer. Both `pvt_engine.py` and `fit_engine.py`
are unchanged; all engineering calculations and calibration remain in those modules.

## Run locally

Requires Python 3.11 or newer.

```powershell
python -m pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:8050. Optional development arguments: `--port 8051` and
`--host 0.0.0.0`. Use the production server below for remote hosting.

## Browser workflow

1. Enter Oil API gravity, Gas Gravity, Reservoir Temperature (degrees F), Bubble
   Point Pressure (psia), Minimum Pressure (psia), Maximum Pressure (psia), and
   Pressure Step (psi). Initial values are editable example controls.
2. Copy the cleaned laboratory table **including its header row** from Excel.
3. Paste into **Paste Lab Data from Excel**. Parsing and validation run automatically.
4. Select **Calibrate to Laboratory Data** if desired, then **Calculate PVT**.
5. Inspect the three charts, calibration summary, and calculated/laboratory tables.
   Changing calibration after a successful calculation immediately recalculates.
   Editing other inputs hides the old results until **Calculate PVT** is clicked.
6. Download **Export results CSV**, **Export calibration CSV** (when enabled), or
   **Export full results JSON**. Downloads are generated in the browser; the server
   does not write export files. Full JSON includes controls, pressure grid, raw
   results, laboratory data, calibration coefficients, and calibrated curves.

An empty paste field permits raw correlation exploration. With calibration enabled
and no usable measurements, fits are reported as unavailable without solid traces.

## Pasted table format

Required headers, in any order:

| Header | Units | Blank allowed? |
| --- | --- | --- |
| `Pressure_psia` | psia | No |
| `Rs_scf_stb` | scf/STB | Yes |
| `Bo_rb_stb` | rb/STB | Yes |
| `Viscosity_cp` | cP | Yes |

Paste tab-separated cells, as Excel normally copies them. Header whitespace,
Windows or Unix newlines, quoted cells, scientific notation and comma thousands
separators (e.g. `1,000.5`) are supported. Use a decimal point. Extra columns are
ignored; duplicate required headers, missing headers, invalid numeric cells and
Excel error/formula text are rejected with actionable messages. All supplied
numbers must be finite. Pressure, Bo and viscosity must be positive; Rs may be zero.

Blank measurements become JSON `null`, are shown as dashes in the table, and are
omitted from that property's plot and fit. A pressure-only row is accepted.
Completely blank rows are ignored. No measurements are invented or interpolated.
A nonempty paste must contain headers and at least one data row.

## Calculation and calibration

The pressure grid is `PMin + n * PStep`, ending at or below `PMax`. An off-step
maximum does not create a short final step; the last actual pressure is displayed.
A single pressure is allowed when minimum equals maximum. The request limit is
2 MiB, with at most 20,000 pressures and 20,000 laboratory rows.

`browser_inputs.py` validates inputs and calls `pvt_engine.calculate_pvt_curve()`.
`app.py` calls `fit_engine.calibrate_curves()` only when calibration is enabled.
Neither Flask nor JavaScript contains engineering equations. Laboratory points,
dashed raw correlations and solid calibrated curves share the existing three charts.

Calibration fits `Y_calibrated = A * Y_calculated + B` independently for each
property and correlation. The existing fitter interpolates raw curves to measured
pressures, excludes measurements outside the calculated range, and reports RMSE
before/after over the same usable points. One point or constant predictions use a
flagged shift-only fit. No usable points produce an unavailable fit. Calibrated Rs
is not fed into Bo or viscosity. Raw results remain unchanged in the results table;
CSV exports add calibrated columns when enabled, with blank cells for unavailable
fits. Calibration CSV includes coefficients, errors, units, counts and status.

## Remote deployment

This application needs a Python server; it cannot run on static-only hosting.
No Excel installation, workbook, CSV input, user directory mount, database, or
writable data directory is required. Plotly and other assets are served by the app.

Install requirements and set the hosting service's start command to:

```text
python serve.py
```

`serve.py` uses Waitress, binds to `0.0.0.0`, and reads `PORT` (default `8050`) and
`HOST` from the environment. The WSGI application is also available as `app:app`.
Use the host's HTTPS endpoint or put an HTTPS reverse proxy in front of Waitress.
The frontend uses Flask-generated URLs, so API calls stay on the same origin.
A health endpoint is available at `/healthz`.

For a container host:

```text
docker build -t pvt-explorer .
docker run --rm -p 8050:8050 pvt-explorer
```

The Docker image runs as a non-root user and explicitly includes only the runtime
application files. Configure `PORT` and the container port mapping for your host.
The container can run with a read-only filesystem.

Deploy these files when not using Docker: `app.py`, `browser_inputs.py`,
`pvt_engine.py`, `fit_engine.py`, `serve.py`, `requirements.txt`, `templates/`,
and `static/`. Existing workbook samples, `Raw_Lab_PVT.csv`, and the legacy
`workbook_loader.py` are unused and are excluded from the container.
The former `/api/workbook` route has been removed.

Inputs are sent to the server for validation/calculation and held in memory only
for the request. The application does not persist lab data, use global result
caches, or share one visitor's results with another. API responses use `no-store`.
Hosting infrastructure should not be configured to log request bodies.

## API

`POST /api/calculate`, content type `application/json`:

```json
{
  "inputs": {
    "OilAPI": 35, "GasGravity": 0.75, "ReservoirTempF": 180,
    "BubblePointPsi": 2500, "PMin": 500, "PMax": 5000, "PStep": 100
  },
  "lab_text": "",
  "calibrate": false
}
```

Set `lab_text` to the clipboard TSV string. The response contains `inputs`,
`pressures`, `curves`, `lab`, `missing_lab_values`, `calibration_enabled`,
`calibration`, and `calculated_at`. `POST /api/lab/validate` accepts `lab_text`
and returns row and missing-measurement counts. Validation errors return JSON
`error` with HTTP 400; oversized requests return 413.

## Checks

```text
python -m unittest discover -s tests -v
python validation.py
node --check static/app.js
node tests/test_frontend.cjs
```

The tests cover clipboard parsing, missing measurements, input validation,
calibration on/off, engine delegation, independent requests, removed file access,
remote-origin requests, numeric limits, and byte-for-byte engine preservation.
The Node check exercises chart traces, calibration toggling, missing-value display,
CSV/JSON downloads and stale-result handling with DOM/Plotly test doubles. It does
not replace visual browser verification.
