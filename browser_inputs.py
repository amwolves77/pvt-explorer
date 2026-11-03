"""Validate browser controls and Excel clipboard text; delegate PVT calculations."""
import csv
from datetime import datetime, timezone
from decimal import Decimal
from io import StringIO
import math
import re

from pvt_engine import calculate_pvt_curve

INPUT_LABELS = {
    "OilAPI": "Oil API gravity", "GasGravity": "Gas Gravity",
    "ReservoirTempF": "Reservoir Temperature, °F",
    "BubblePointPsi": "Bubble Point Pressure, psia",
    "PMin": "Minimum Pressure, psia", "PMax": "Maximum Pressure, psia",
    "PStep": "Pressure Step, psi",
}
LAB_COLUMNS = ("Pressure_psia", "Rs_scf_stb", "Bo_rb_stb", "Viscosity_cp")
MAX_PRESSURES = 20000
MAX_LAB_ROWS = 20000
NUMERIC_TEXT = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?\Z")
GROUPED_TEXT = re.compile(r"[+-]?\d{1,3}(?:,\d{3})+(?:\.\d*)?(?:[eE][+-]?\d+)?\Z")


class InputError(ValueError):
    """Actionable validation error suitable for the browser."""


def number(value, label):
    if value is None or (isinstance(value, str) and not value.strip()):
        raise InputError(f"{label} is required.")
    if isinstance(value, str):
        value = value.strip()
        if GROUPED_TEXT.fullmatch(value):
            value = value.replace(",", "")
        if not NUMERIC_TEXT.fullmatch(value):
            raise InputError(f"{label} must be numeric (use a decimal point).")
    elif isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InputError(f"{label} must be numeric.")
    try:
        result = float(value)
    except (ValueError, OverflowError) as exc:
        raise InputError(f"{label} must be a finite number.") from exc
    if not math.isfinite(result):
        raise InputError(f"{label} must be a finite number.")
    return result


def parse_lab_data(text):
    """Parse TSV without touching files or filling missing measurements."""
    if not isinstance(text, str):
        raise InputError("Paste Lab Data from Excel must contain text.")
    if not text.strip():
        return []
    reader = csv.reader(StringIO(text.lstrip("\ufeff"), newline=""), delimiter="\t", strict=True)
    headers = None
    rows = []
    try:
        for cells in reader:
            line = reader.line_num
            if not any(cell.strip() for cell in cells):
                continue
            if headers is None:
                headers = [cell.strip() for cell in cells]
                missing = [name for name in LAB_COLUMNS if name not in headers]
                if missing:
                    raise InputError("Missing required column headers: " + ", ".join(missing)
                                     + ". Copy the header row and cells directly from Excel (tab-separated).")
                if any(headers.count(name) != 1 for name in LAB_COLUMNS):
                    raise InputError("Duplicate required column headers in pasted laboratory data.")
                positions = {name: headers.index(name) for name in LAB_COLUMNS}
                continue
            if len(cells) > len(headers):
                raise InputError(f"Lab row {line} has more cells than the header row.")
            cells += [""] * (len(headers) - len(cells))
            record = {}
            for name, position in positions.items():
                value = cells[position].strip()
                if not value and name != "Pressure_psia":
                    record[name] = None
                    continue
                record[name] = number(value, f"Lab row {line}, {name}")
                if record[name] < 0 or (name != "Rs_scf_stb" and record[name] == 0):
                    constraint = "nonnegative" if name == "Rs_scf_stb" else "greater than zero"
                    raise InputError(f"Lab row {line}, {name} must be {constraint}.")
            rows.append(record)
            if len(rows) > MAX_LAB_ROWS:
                raise InputError(f"Paste at most {MAX_LAB_ROWS:,} laboratory rows.")
    except csv.Error as exc:
        raise InputError(f"Invalid tab-separated data near row {reader.line_num}.") from exc
    if not rows:
        raise InputError("Paste at least one data row beneath the headers, or clear the field to view raw curves.")
    return rows


def validate_controls(values):
    if not isinstance(values, dict):
        raise InputError("Provide all seven calculation inputs.")
    controls = {name: number(values.get(name), label) for name, label in INPUT_LABELS.items()}
    for name, value in controls.items():
        if name == "OilAPI":
            if value <= -131.5:
                raise InputError("Oil API gravity must be greater than -131.5.")
        elif value <= 0:
            raise InputError(f"{INPUT_LABELS[name]} must be greater than zero.")
    if controls["PMax"] < controls["PMin"]:
        raise InputError("Maximum Pressure must be greater than or equal to Minimum Pressure.")
    return controls


def pressure_range(controls):
    start, stop, step = (Decimal(str(controls[name])) for name in ("PMin", "PMax", "PStep"))
    intervals = (stop - start) / step
    if intervals >= MAX_PRESSURES:
        raise InputError(f"The pressure range exceeds {MAX_PRESSURES:,} points; increase Pressure Step or narrow the range.")
    pressures = [float(start + i * step) for i in range(int(intervals) + 1)]
    if any(a >= b for a, b in zip(pressures, pressures[1:])):
        raise InputError("Pressure Step is too small for the numeric precision of this pressure range.")
    return pressures


def calculate_explorer(payload):
    controls = validate_controls(payload.get("inputs"))
    lab = parse_lab_data(payload.get("lab_text", ""))
    pressures = pressure_range(controls)
    try:
        curve = calculate_pvt_curve(
            pressures=pressures, temperature_f=controls["ReservoirTempF"],
            oil_api=controls["OilAPI"], gas_gravity=controls["GasGravity"],
            bubble_point_psia=controls["BubblePointPsi"],
        )
        if not all(math.isfinite(float(v)) for v in curve[["Pressure", "Rs", "Bo", "Viscosity"]].to_numpy().flat):
            raise ValueError("The engine returned a non-finite result.")
    except (ArithmeticError, ValueError, TypeError) as exc:
        raise InputError("PVT calculation failed for these inputs. Check the fluid properties and pressure range.") from exc
    return {
        "calculated_at": datetime.now(timezone.utc).isoformat(),
        "inputs": controls, "pressures": pressures,
        "curves": curve.to_dict(orient="records"), "lab": lab,
        "missing_lab_values": {name: sum(row[name] is None for row in lab) for name in LAB_COLUMNS[1:]},
    }
