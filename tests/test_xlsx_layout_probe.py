import contextlib
import io
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from openpyxl import Workbook
from openpyxl.styles import Alignment

from utils.large_text_multilingual_runner import main


@unittest.skipUnless(os.environ.get('LOCALIZATION_TEST_NATIVE_EXCEL') == '1',
                     'Microsoft Excel integration is opt-in')
class ExcelLayoutProbeTests(unittest.TestCase):
    def test_long_line_is_blocked_at_narrow_width_without_changing_workbook(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'candidate.xlsx'
            workbook = Workbook()
            sheet = workbook.active
            sheet['A1'] = 'ID'
            sheet['B1'] = 'target'
            sheet['A2'] = 'scene_description'
            sheet['B2'] = '\n'.join(['Scene introduction'] * 7 + [
                'The trainer stays outside the script and watches over the team. ' * 32])
            sheet['B2'].alignment = Alignment(wrap_text=True)
            sheet.row_dimensions[2].height = 390
            sheet['B3'] = 'reserved row'
            sheet.row_dimensions[3].hidden = True
            for width, code in ((40, 1), (105, 0)):
                sheet.column_dimensions['B'].width = width
                workbook.save(path)
                before = path.read_bytes()
                with contextlib.redirect_stdout(io.StringIO()) as output:
                    self.assertEqual(main(['check-excel-layout', '--workbook', str(path)]), code)
                report = json.loads(output.getvalue())
                self.assertEqual(report['sheets']['Sheet']['saturated_rows'], [2] if code else [])
                self.assertEqual(report['sheets']['Sheet']['visible_rows_measured'], 2)
                self.assertFalse(report['formal_visual_acceptance'])
                self.assertEqual(path.read_bytes(), before)
