"""Affine least-squares calibration of existing curves; no PVT equations.

Only finite lab measurements within the calculated pressure range are used.
Calculated values are linearly interpolated to those pressures before fitting.
Raw inputs are never changed. RMSE before/after uses the same measured points.
"""

from bisect import bisect_left
import math


def fit_curve(pressures, calculated, lab_pressures, measurements):
    """Return multiplier, shift, RMSEs and calibrated values on the input grid.

    Missing/non-finite measurements are ignored. Out-of-range lab pressures are
    counted and excluded (no extrapolation). For one point or constant calculated
    values, A and B are not uniquely identifiable: choose A=1 and fit only B.
    With no usable measurements, coefficients/errors/curve are None.
    """
    pressures, calculated = list(pressures), list(calculated)
    lab_pressures, measurements = list(lab_pressures), list(measurements)
    if not pressures or len(pressures) != len(calculated):
        raise ValueError("A nonempty calculated curve with matching pressures is required.")
    if len(lab_pressures) != len(measurements):
        raise ValueError("Laboratory pressures and measurements must have matching lengths.")
    if not all(math.isfinite(v) for v in pressures + calculated):
        raise ValueError("Calculated pressures and values must be finite.")
    grid = sorted(zip(pressures, calculated))
    xp, yp = zip(*grid)
    if any(a == b for a, b in zip(xp, xp[1:])):
        raise ValueError("Calculated pressures must be unique.")

    x, y = [], []
    outside = 0
    for pressure, measured in zip(lab_pressures, measurements):
        if measured is None or not math.isfinite(measured):
            continue
        if pressure is None or not math.isfinite(pressure):
            continue
        if pressure < xp[0] or pressure > xp[-1]:
            outside += 1
            continue
        index = bisect_left(xp, pressure)
        if xp[index] == pressure:
            interpolated = yp[index]
        else:
            fraction = (pressure - xp[index - 1]) / (xp[index] - xp[index - 1])
            interpolated = yp[index - 1] + fraction * (yp[index] - yp[index - 1])
        x.append(interpolated)
        y.append(measured)

    result = dict(multiplier=None, shift=None, error_before=None, error_after=None,
                  calibrated_curve=None, metric="RMSE", points_used=len(x),
                  outside_range=outside, status="unavailable", message="")
    if not x:
        result["message"] = "No measured points within the calculated pressure range."
        return result

    # Centering and scaling avoids the ill-conditioning of uncentered normal
    # equations, especially for Bo curves whose values are close together.
    mean_x, mean_y = math.fsum(x) / len(x), math.fsum(y) / len(y)
    dx = [value - mean_x for value in x]
    scale = max(abs(value) for value in dx)
    if max(x) == min(x):
        multiplier = 1.0
        result.update(status="shift_only", message=
                      "Shift-only fit (A = 1): measured points do not span distinct calculated values.")
    else:
        normalized = [value / scale for value in dx]
        multiplier = (math.fsum(value * (target - mean_y) for value, target in zip(normalized, y))
                      / math.fsum(value * value for value in normalized) / scale)
        result["status"] = "fitted"
    shift = mean_y - multiplier * mean_x
    calibrated = [multiplier * value + shift for value in calculated]
    before = math.hypot(*(value - target for value, target in zip(x, y))) / math.sqrt(len(x))
    after = math.hypot(*(multiplier * value + shift - target for value, target in zip(x, y))) / math.sqrt(len(x))
    if not all(math.isfinite(v) for v in [multiplier, shift, before, after] + calibrated):
        result.update(status="unavailable", message="Fit exceeds the supported numeric range.")
        return result
    result.update(multiplier=multiplier, shift=shift, error_before=before,
                  error_after=after, calibrated_curve=calibrated)
    return result


def calibrate_curves(curves, lab):
    """Fit each existing property/correlation independently from record lists.

    Viscosity is fitted separately for both existing Rs-based viscosity curves.
    Calibrated Rs is never fed back into Bo or viscosity engineering equations.
    """
    fits = []
    for property_name, lab_key, unit in (
        ("Rs", "Rs_scf_stb", "scf/STB"),
        ("Bo", "Bo_rb_stb", "rb/STB"),
        ("Viscosity", "Viscosity_cp", "cP"),
    ):
        for correlation in ("Standing", "Vasquez-Beggs"):
            rows = [row for row in curves if row["Correlation"] == correlation]
            fit = fit_curve([row["Pressure"] for row in rows],
                            [row[property_name] for row in rows],
                            [row["Pressure_psia"] for row in lab],
                            [row.get(lab_key) for row in lab])
            fits.append(dict(property=property_name, correlation=correlation, unit=unit, **fit))
    return fits
