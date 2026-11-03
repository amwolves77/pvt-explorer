"""Numerical calibration contracts, independent of the engineering equations."""

import copy
import math
import unittest

from fit_engine import calibrate_curves, fit_curve


class FitTests(unittest.TestCase):
    def test_interpolates_before_fitting_and_preserves_original_grid(self):
        # Unsorted curve: interpolated values at 150/250/350 are 2/6/12.
        pressures, values = [400, 100, 200, 300], [15, 1, 3, 9]
        result = fit_curve(pressures, values, [150, 250, 350], [7, 15, 27])
        self.assertAlmostEqual(result['multiplier'], 2)
        self.assertAlmostEqual(result['shift'], 3)
        self.assertAlmostEqual(result['error_before'], math.sqrt((25 + 81 + 225) / 3))
        self.assertAlmostEqual(result['error_after'], 0)
        for actual, expected in zip(result['calibrated_curve'], [33, 5, 9, 21]):
            self.assertAlmostEqual(actual, expected)
        self.assertEqual(values, [15, 1, 3, 9])

    def test_noisy_least_squares_solution_and_consistent_rmse(self):
        result = fit_curve([100, 200, 300], [0, 1, 2], [100, 200, 300], [1, 4, 4])
        self.assertAlmostEqual(result['multiplier'], 1.5)
        self.assertAlmostEqual(result['shift'], 1.5)
        self.assertAlmostEqual(result['error_before'], math.sqrt(14 / 3))
        self.assertAlmostEqual(result['error_after'], math.sqrt(.5))
        self.assertEqual(result['metric'], 'RMSE')

    def test_missing_values_are_ignored_but_zero_is_used(self):
        result = fit_curve([100, 500], [0, 4], [100, 200, 300, 400, 500],
                           [0, None, float('nan'), float('inf'), 8])
        self.assertEqual(result['points_used'], 2)
        self.assertEqual(result['multiplier'], 2)
        self.assertEqual(result['shift'], 0)

    def test_excludes_outside_range_without_clamping_or_extrapolation(self):
        result = fit_curve([100, 200], [1, 2], [50, 100, 200, 250], [999, 3, 5, 999])
        self.assertEqual(result['outside_range'], 2)
        self.assertEqual(result['points_used'], 2)
        self.assertEqual(result['multiplier'], 2)
        self.assertEqual(result['shift'], 1)

    def test_no_usable_points_does_not_claim_calibration(self):
        for pressures, measurements in [([100, 200], [None, None]), ([50, 250], [1, 2]), ([], [])]:
            with self.subTest(measurements=measurements):
                result = fit_curve([100, 200], [1, 2], pressures, measurements)
                self.assertEqual(result['status'], 'unavailable')
                for key in ('multiplier', 'shift', 'error_before', 'error_after', 'calibrated_curve'):
                    self.assertIsNone(result[key])

    def test_single_point_and_constant_curves_use_documented_shift_only_fit(self):
        for grid, values, pressures, measured, shift, after in [
            ([100, 200], [1, 3], [150], [5], 3, 0),
            ([100, 200], [2, 2], [100, 200], [4, 6], 3, 1),
            ([100], [2], [100], [5], 3, 0),
        ]:
            with self.subTest(values=values):
                result = fit_curve(grid, values, pressures, measured)
                self.assertEqual(result['status'], 'shift_only')
                self.assertEqual(result['multiplier'], 1)
                self.assertEqual(result['shift'], shift)
                self.assertEqual(result['error_after'], after)

    def test_close_bo_values_are_fitted(self):
        values = [1.2, 1.200001, 1.200002]
        result = fit_curve([100, 200, 300], values, [100, 200, 300], [2*v - .8 for v in values])
        self.assertAlmostEqual(result['multiplier'], 2)
        self.assertAlmostEqual(result['shift'], -.8)
        self.assertLess(result['error_after'], 1e-12)

    def test_invalid_curve_inputs(self):
        for grid, values in [([], []), ([100], []), ([100, 100], [1, 2]), ([100], [float('nan')])]:
            with self.subTest(grid=grid), self.assertRaises(ValueError):
                fit_curve(grid, values, [100], [1])
        with self.assertRaises(ValueError):
            fit_curve([100], [1], [100], [])

    def test_each_property_and_correlation_is_independent_and_raw_is_unchanged(self):
        curves = [dict(Pressure=p, Correlation=name, Rs=value, Bo=value+1, Viscosity=10-value)
                  for name, scale in [('Standing', 1), ('Vasquez-Beggs', 2)]
                  for p, value in [(100, scale), (200, 3*scale), (300, 5*scale)]]
        lab = [dict(Pressure_psia=100, Rs_scf_stb=4, Bo_rb_stb=None, Viscosity_cp=3),
               dict(Pressure_psia=200, Rs_scf_stb=8, Bo_rb_stb=2, Viscosity_cp=None),
               dict(Pressure_psia=300, Rs_scf_stb=12, Bo_rb_stb=3, Viscosity_cp=1)]
        original_curves, original_lab = copy.deepcopy(curves), copy.deepcopy(lab)
        fits = calibrate_curves(curves, lab)
        self.assertEqual(len(fits), 6)
        self.assertEqual([fit['points_used'] for fit in fits], [3, 3, 2, 2, 2, 2])
        self.assertEqual([fit['multiplier'] for fit in fits[:2]], [2, 1])
        self.assertEqual([fit['shift'] for fit in fits[:2]], [2, 2])
        for fit in fits:
            self.assertLess(fit['error_after'], 1e-12)
            self.assertEqual(len(fit['calibrated_curve']), 3)
        self.assertEqual(curves, original_curves)
        self.assertEqual(lab, original_lab)


if __name__ == '__main__':
    unittest.main()
