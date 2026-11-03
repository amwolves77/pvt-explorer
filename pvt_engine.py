"""PVT correlation calculation engine.

Engineering equations are taken from the accompanying correlation reference PDF.
Units used throughout:
- pressure: psia
- temperature: degF
- oil gravity: degAPI
- gas gravity: dimensionless
- Rs: scf/STB
- Bo: rb/STB
- Co: psi^-1
- oil viscosity: cP
"""

import math
import pandas as pd


def oil_specific_gravity(oil_api):
    """Convert oil gravity in degAPI to dimensionless oil specific gravity."""
    return 141.5 / (oil_api + 131.5)


def standing_rs(pressure_psia, temperature_f, oil_api, gas_gravity):
    """Standing solution GOR for saturated oil. Returns Rs in scf/STB."""
    return (
        (pressure_psia / 18.2 + 1.4)
        * (10 ** (0.0125 * oil_api))
        / (10 ** (0.00091 * temperature_f))
    ) ** (1.0 / 0.83) * gas_gravity


def standing_bo(rs_scf_stb, temperature_f, oil_api, gas_gravity):
    """Standing saturated oil FVF. Returns Bo in rb/STB."""
    gamma_o = oil_specific_gravity(oil_api)
    term = rs_scf_stb * (gas_gravity / gamma_o) ** 0.5 + 1.25 * temperature_f
    return 0.972 + 1.47e-4 * term ** 1.175


def _vasquez_beggs_rs_coefficients(oil_api):
    """Return Vasquez-Beggs Rs coefficients for the applicable API range."""
    if oil_api <= 30.0:
        return 0.0362, 1.0937, 25.7240
    return 0.0178, 1.1870, 23.9310


def _vasquez_beggs_bo_coefficients(oil_api):
    """Return Vasquez-Beggs Bo coefficients for the applicable API range."""
    if oil_api <= 30.0:
        return 4.677e-4, 1.751e-5, -1.811e-8
    return 4.670e-4, 1.100e-5, 1.377e-9


def vasquez_beggs_rs(pressure_psia, temperature_f, oil_api, gas_gravity):
    """Vasquez-Beggs solution GOR for saturated oil. Returns Rs in scf/STB."""
    c1, c2, c3 = _vasquez_beggs_rs_coefficients(oil_api)
    return (
        c1
        * gas_gravity
        * pressure_psia ** c2
        * math.exp(c3 * oil_api / (temperature_f + 460.0))
    )


def vasquez_beggs_bo(rs_scf_stb, temperature_f, oil_api, gas_gravity):
    """Vasquez-Beggs saturated oil FVF. Returns Bo in rb/STB."""
    c1, c2, c3 = _vasquez_beggs_bo_coefficients(oil_api)
    gravity_term = oil_api / gas_gravity
    return (
        1.0
        + c1 * rs_scf_stb
        + c2 * (temperature_f - 60.0) * gravity_term
        + c3 * rs_scf_stb * (temperature_f - 60.0) * gravity_term
    )


def vasquez_beggs_co(
    pressure_psia,
    temperature_f,
    oil_api,
    gas_gravity,
    rs_bubblepoint_scf_stb,
):
    """Vasquez-Beggs undersaturated oil compressibility. Returns Co in psi^-1."""
    numerator = (
        -1433.0
        + 5.0 * rs_bubblepoint_scf_stb
        + 17.2 * temperature_f
        - 1180.0 * gas_gravity
        + 12.61 * oil_api
    )
    return numerator / (1.0e5 * pressure_psia)


def undersaturated_bo(pressure_psia, bubble_point_psia, bo_bubblepoint, co_psi_inv):
    """Calculate undersaturated Bo above bubble point using Bob and Co."""
    return bo_bubblepoint * math.exp(co_psi_inv * (bubble_point_psia - pressure_psia))


def beggs_robinson_dead_oil_viscosity(temperature_f, oil_api):
    """Beggs-Robinson dead-oil viscosity. Returns viscosity in cP."""
    z = 3.0324 - 0.02023 * oil_api
    y = 10.0 ** z
    x = y * temperature_f ** (-1.163)
    return 10.0 ** x - 1.0


def beggs_robinson_saturated_viscosity(rs_scf_stb, dead_oil_viscosity_cp):
    """Beggs-Robinson saturated/live-oil viscosity. Returns viscosity in cP."""
    a = 10.715 * (rs_scf_stb + 100.0) ** (-0.515)
    b = 5.44 * (rs_scf_stb + 150.0) ** (-0.338)
    return a * dead_oil_viscosity_cp ** b


def beggs_robinson_undersaturated_viscosity(
    pressure_psia,
    bubble_point_psia,
    bubble_point_viscosity_cp,
):
    """Pressure-corrected oil viscosity above bubble point. Returns viscosity in cP."""
    m = 2.6 * pressure_psia ** 1.187 * math.exp(
        -11.513 - 8.98e-5 * pressure_psia
    )
    return bubble_point_viscosity_cp * (pressure_psia / bubble_point_psia) ** m


def calculate_pvt_curve(
    pressures,
    temperature_f,
    oil_api,
    gas_gravity,
    bubble_point_psia,
):
    """Calculate Standing and Vasquez-Beggs PVT curves over a pressure array.

    Returns a structured results table with:
    Pressure, Correlation, Rs, Bo, Viscosity.
    """
    if bubble_point_psia <= 0:
        raise ValueError("Bubble-point pressure must be greater than zero.")
    if gas_gravity <= 0:
        raise ValueError("Gas gravity must be greater than zero.")
    if temperature_f <= 0:
        raise ValueError("Temperature must be greater than zero degF.")

    pressure_values = [float(p) for p in pressures]
    if any(p <= 0 for p in pressure_values):
        raise ValueError("All pressures must be greater than zero psia.")

    dead_oil_viscosity = beggs_robinson_dead_oil_viscosity(temperature_f, oil_api)

    correlations = [
        ("Standing", standing_rs, standing_bo),
        ("Vasquez-Beggs", vasquez_beggs_rs, vasquez_beggs_bo),
    ]

    results = []

    for correlation_name, rs_function, bo_function in correlations:
        rs_bubblepoint = rs_function(
            bubble_point_psia, temperature_f, oil_api, gas_gravity
        )
        bo_bubblepoint = bo_function(
            rs_bubblepoint, temperature_f, oil_api, gas_gravity
        )
        viscosity_bubblepoint = beggs_robinson_saturated_viscosity(
            rs_bubblepoint, dead_oil_viscosity
        )

        for pressure in pressure_values:
            if pressure <= bubble_point_psia:
                rs = rs_function(pressure, temperature_f, oil_api, gas_gravity)
                bo = bo_function(rs, temperature_f, oil_api, gas_gravity)
                viscosity = beggs_robinson_saturated_viscosity(
                    rs, dead_oil_viscosity
                )
            else:
                rs = rs_bubblepoint
                co = vasquez_beggs_co(
                    pressure,
                    temperature_f,
                    oil_api,
                    gas_gravity,
                    rs_bubblepoint,
                )
                bo = undersaturated_bo(
                    pressure,
                    bubble_point_psia,
                    bo_bubblepoint,
                    co,
                )
                viscosity = beggs_robinson_undersaturated_viscosity(
                    pressure,
                    bubble_point_psia,
                    viscosity_bubblepoint,
                )

            results.append(
                {
                    "Pressure": pressure,
                    "Correlation": correlation_name,
                    "Rs": rs,
                    "Bo": bo,
                    "Viscosity": viscosity,
                }
            )

    return pd.DataFrame(results)


if __name__ == "__main__":
    # Simple example using the Masterclass control-sheet assumptions.
    pressures = range(500, 5001, 100)

    table = calculate_pvt_curve(
        pressures=pressures,
        temperature_f=180.0,
        oil_api=35.0,
        gas_gravity=0.75,
        bubble_point_psia=2500.0,
    )

    print(table.head(10).to_string(index=False))
