"""Browser-input API contracts, with no workbook/CSV fixtures or file access."""
import hashlib
import math
from pathlib import Path
import unittest
from unittest.mock import patch

from app import create_app
from browser_inputs import InputError, LAB_COLUMNS, parse_lab_data, pressure_range, validate_controls
from fit_engine import calibrate_curves
from pvt_engine import calculate_pvt_curve

CONTROLS = dict(OilAPI=35, GasGravity=.75, ReservoirTempF=180, BubblePointPsi=2500,
                PMin=500, PMax=5000, PStep=100)
HEADER = '\t'.join(LAB_COLUMNS)
LAB = HEADER + '\r\n500\t145\t1.125\t2.35\r\n2500\t650\t1.4\t.7\r\n5000\t650\t1.35\t.9\r\n'

class ExplorerTests(unittest.TestCase):
    def setUp(self):
        self.client = create_app().test_client()

    def calculate(self, **changes):
        return self.client.post('/api/calculate', json=dict(inputs=CONTROLS, lab_text=LAB, calibrate=False) | changes)

    def test_raw_results_match_existing_engine_and_no_fit_runs(self):
        with patch('app.calibrate_curves') as fit:
            response = self.calculate()
        self.assertEqual(response.status_code, 200)
        data = response.json
        self.assertEqual(data['inputs'], CONTROLS)
        self.assertEqual(data['pressures'], list(range(500, 5001, 100)))
        self.assertEqual(data['curves'], calculate_pvt_curve(data['pressures'], 180, 35, .75, 2500).to_dict('records'))
        self.assertEqual(data['calibration'], [])
        fit.assert_not_called()
        self.assertNotIn('path', data)
        self.assertEqual(response.headers['Cache-Control'], 'no-store')

    def test_delegation_to_both_unchanged_engines(self):
        with patch('browser_inputs.calculate_pvt_curve', wraps=calculate_pvt_curve) as engine, \
             patch('app.calibrate_curves', wraps=calibrate_curves) as fitter:
            response = self.calculate(calibrate=True)
        self.assertEqual(response.status_code, 200)
        data = response.json
        engine.assert_called_once_with(pressures=list(range(500,5001,100)), temperature_f=180,
                                       oil_api=35, gas_gravity=.75, bubble_point_psia=2500)
        fitter.assert_called_once_with(data['curves'], data['lab'])
        self.assertEqual(len(data['calibration']), 6)
        for fit in data['calibration']:
            self.assertEqual(fit['points_used'], 3)
            self.assertLessEqual(fit['error_after'], fit['error_before'])
        self.assertEqual(data['curves'], self.calculate().json['curves'])

    def test_engine_files_are_byte_identical(self):
        root = Path(__file__).resolve().parents[1]
        for filename, digest in [
            ('pvt_engine.py', 'c1ea6882499c3700d475f21a42a276d4d35bb07a4a2b99538599d44f50d81e5c'),
            ('fit_engine.py', '6cb00570218a5fb2cc60eda488fcfdd7b5b7f85ceb0dcf17210d9501423eb4e0')]:
            self.assertEqual(hashlib.sha256((root / filename).read_bytes()).hexdigest(), digest)

    def test_paste_crlf_blank_cells_rows_and_zero_rs(self):
        text = HEADER + '\r\n500\t0\t\t2.35\r\n\t\t\t\r\n700\t\t1.1\t\r\n800\t\t\t'
        data = self.calculate(lab_text=text, calibrate=True).json
        self.assertEqual(len(data['lab']), 3)
        self.assertEqual(data['lab'][0]['Rs_scf_stb'], 0)
        self.assertIsNone(data['lab'][0]['Bo_rb_stb'])
        self.assertIsNone(data['lab'][1]['Viscosity_cp'])
        self.assertEqual(data['missing_lab_values'], dict(Rs_scf_stb=2, Bo_rb_stb=2, Viscosity_cp=2))
        self.assertTrue(all(fit['points_used'] == 1 for fit in data['calibration']))

    def test_header_order_whitespace_quotes_and_extra_column(self):
        text = '\ufeff\n Viscosity_cp \tBo_rb_stb\tRs_scf_stb\tPressure_psia\tNotes\n"2.35"\t1.125\t145\t"1,000"\tnote'
        self.assertEqual(parse_lab_data(text), [dict(Pressure_psia=1000, Rs_scf_stb=145, Bo_rb_stb=1.125, Viscosity_cp=2.35)])

    def test_empty_input_can_calculate_without_lab_or_fit_points(self):
        for enabled in [False, True]:
            response = self.calculate(lab_text='', calibrate=enabled)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json['lab'], [])
            self.assertTrue(all(fit['status'] == 'unavailable' for fit in response.json['calibration']))
        self.assertEqual(self.client.post('/api/lab/validate', json={'lab_text': ''}).json['rows'], 0)

    def test_missing_duplicate_and_header_only(self):
        for text, error in [(HEADER.replace('Bo_rb_stb', 'Other'), 'Bo_rb_stb'),
                            (HEADER+'\tBo_rb_stb', 'Duplicate'), (HEADER, 'at least one'),
                            (HEADER.replace('\t', ',')+'\n500,1,1,1', 'tab-separated')]:
            with self.subTest(text=text):
                response = self.calculate(lab_text=text)
                self.assertEqual(response.status_code, 400)
                self.assertIn(error, response.json['error'])

    def test_invalid_numeric_cells_identify_row_and_column(self):
        for index, column in enumerate(LAB_COLUMNS):
            for invalid in ['bad', '#N/A', 'NaN', 'inf', '1e999', '=1+1', '1,2']:
                cells = ['500', '145', '1.125', '2.35']
                cells[index] = invalid
                response = self.calculate(lab_text=HEADER+'\n'+'\t'.join(cells))
                self.assertEqual(response.status_code, 400)
                self.assertIn('row 2', response.json['error'])
                self.assertIn(column, response.json['error'])
        response = self.calculate(lab_text=HEADER+'\n\t145\t1.125\t2.35')
        self.assertIn('Pressure_psia is required', response.json['error'])

    def test_invalid_lab_shape_and_physical_values(self):
        for text in [HEADER+'\n500\t1\t1\t1\textra', HEADER+'\n0\t1\t1\t1',
                     HEADER+'\n500\t-1\t1\t1', HEADER+'\n500\t1\t0\t1',
                     HEADER+'\n500\t1\t1\t0', HEADER+'\n"unterminated']:
            self.assertEqual(self.calculate(lab_text=text).status_code, 400)
        self.assertEqual(self.calculate(lab_text=[]).status_code, 400)

    def test_missing_measurement_property_does_not_block_other_fits(self):
        response = self.calculate(lab_text=HEADER+'\n500\t145\t1.125\t\n2500\t650\t1.4\t', calibrate=True)
        self.assertEqual(response.status_code, 200)
        for fit in response.json['calibration']:
            self.assertEqual(fit['status'], 'unavailable' if fit['property'] == 'Viscosity' else 'fitted')

    def test_outside_lab_range_excluded_by_existing_fitter(self):
        data = self.calculate(lab_text=LAB+'6000\t999\t1.5\t2', calibrate=True).json
        self.assertTrue(all(fit['outside_range'] == 1 and fit['points_used'] == 3 for fit in data['calibration']))

    def test_decimal_single_point_and_off_step_grids(self):
        for values, expected in [({'PMin': .1, 'PMax': .3, 'PStep': .1}, [.1,.2,.3]),
                                 ({'PMin': 500, 'PMax': 750, 'PStep': 100}, [500,600,700]),
                                 ({'PMin': 500, 'PMax': 500}, [500])]:
            self.assertEqual(pressure_range(validate_controls(CONTROLS | values)), expected)

    def test_invalid_controls_and_limits(self):
        for values in [dict(PStep=0), dict(PMin=6000), dict(OilAPI=-132), dict(GasGravity=0),
                       dict(ReservoirTempF=0), dict(BubblePointPsi=float('nan')), dict(PStep=1e-200),
                       dict(OilAPI=True), dict(PMax=[]), dict(GasGravity='oops'), dict(PMin=-1),
                       dict(PMin=1e20, PMax=1e20+32768, PStep=10)]:
            with self.subTest(values=values):
                self.assertEqual(self.calculate(inputs=CONTROLS | values).status_code, 400)
        missing = dict(CONTROLS); del missing['OilAPI']
        self.assertEqual(self.calculate(inputs=missing).status_code, 400)
        self.assertEqual(self.calculate(inputs=None).status_code, 400)
        self.assertEqual(self.calculate(calibrate='true').status_code, 400)
        with patch('browser_inputs.MAX_LAB_ROWS', 2):
            self.assertEqual(self.calculate().status_code, 400)
        self.assertEqual(self.calculate(lab_text=' ' * (2*1024*1024)).status_code, 413)

    def test_engine_failure_is_actionable(self):
        with patch('browser_inputs.calculate_pvt_curve', side_effect=OverflowError('overflow')):
            response = self.calculate()
        self.assertEqual(response.status_code, 400)
        self.assertIn('PVT calculation failed', response.json['error'])

    def test_new_requests_use_new_inputs_and_have_no_shared_data(self):
        first = self.calculate().json
        second = self.calculate(inputs=CONTROLS | dict(OilAPI=28, PStep=250), lab_text=HEADER+'\n900\t200\t1.1\t1.8').json
        self.assertEqual(second['inputs']['OilAPI'], 28)
        self.assertEqual(len(second['pressures']), 19)
        self.assertNotEqual(first['curves'], second['curves'])
        self.assertEqual(self.calculate().json['curves'], first['curves'])

    def test_automatic_paste_validation(self):
        response = self.client.post('/api/lab/validate', json={'lab_text': HEADER+'\n500\t\t1.1\t'})
        self.assertEqual(response.json, dict(rows=1, missing=2))
        self.assertEqual(self.client.post('/api/lab/validate', json={'lab_text': 'bad'}).status_code, 400)

    def test_browser_routes_requests_and_removed_file_access(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        for label in ('Paste Lab Data from Excel', 'Calculate PVT', 'Calibrate to Laboratory Data', 'Export results CSV'):
            self.assertIn(label, response.text)
        for name in CONTROLS:
            self.assertIn(f'id="{name}"', response.text)
        for forbidden in ('Excel Workbook Path', 'Refresh from Excel', 'type="file"'):
            self.assertNotIn(forbidden, response.text)
        for url in ('/static/app.js', '/static/style.css', '/assets/plotly.min.js', '/healthz'):
            with self.client.get(url) as asset:
                self.assertEqual(asset.status_code, 200)
        self.assertEqual(self.client.post('/api/workbook', json={'path':'C:/secret.xlsx'}).status_code, 404)
        for endpoint in ('/api/calculate', '/api/lab/validate'):
            self.assertEqual(self.client.post(endpoint, data='text').status_code, 400)
            self.assertEqual(self.client.post(endpoint, json=[]).status_code, 400)
            self.assertEqual(self.client.post(endpoint, data='{', content_type='application/json').status_code, 400)
        response = self.client.post('/api/calculate', base_url='https://pvt.example',
                                    headers={'Origin':'https://pvt.example'},
                                    json=dict(inputs=CONTROLS, lab_text=LAB))
        self.assertEqual(response.status_code, 200)

if __name__ == '__main__':
    unittest.main()
