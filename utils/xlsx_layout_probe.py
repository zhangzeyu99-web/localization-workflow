"""Measure actual Microsoft Excel row-height risk without modifying the workbook."""
from pathlib import Path
from tempfile import TemporaryDirectory
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from utils.xlsx_translation_writeback import _sheet_xml_paths


def _height_profiles(path: Path) -> dict:
    with ZipFile(path) as archive:
        sheets = _sheet_xml_paths({
            name: archive.read(name)
            for name in ('xl/workbook.xml', 'xl/_rels/workbook.xml.rels')
        })
        profiles = {}
        for sheet, part in sheets.items():
            root = ET.fromstring(archive.read(part))
            fmt = root.find('{*}sheetFormatPr')
            default = float(fmt.get('defaultRowHeight', 15)) if fmt is not None else 15
            rows = {
                int(row.attrib['r']): float(row.get('ht', default))
                for row in root.findall('{*}sheetData/{*}row')
                if row.get('hidden') not in {'1', 'true'}
            }
            profiles[sheet] = (default, rows, root.find('{*}mergeCells') is not None)
        return profiles


def check_excel_layout(path: Path) -> dict:
    path = path.resolve(strict=True)
    if path.suffix.lower() != '.xlsx' or not path.is_file():
        raise ValueError('layout probe requires a local .xlsx workbook')
    import pythoncom
    from win32com.client import DispatchEx

    original = _height_profiles(path)
    with TemporaryDirectory() as directory:
        fitted = Path(directory) / 'fitted.xlsx'
        pythoncom.CoInitialize()
        app = book = None
        try:
            app = DispatchEx('Excel.Application')
            app.Visible = False
            app.DisplayAlerts = False
            app.AutomationSecurity = 3
            book = app.Workbooks.Open(str(path), UpdateLinks=0, ReadOnly=True, AddToMru=False, CorruptLoad=0)
            for sheet in book.Worksheets:
                sheet.UsedRange.Rows.AutoFit()
            book.SaveCopyAs(str(fitted))
        finally:
            try:
                if book is not None:
                    book.Close(False)
            finally:
                try:
                    if app is not None:
                        app.Quit()
                finally:
                    pythoncom.CoUninitialize()
        measured = _height_profiles(fitted)
    if original.keys() != measured.keys():
        raise ValueError('Excel layout probe changed the sheet set')
    sheets = {}
    for sheet, (default, before, has_merges) in original.items():
        fitted_default, after, _ = measured[sheet]
        saturated = [row for row in before if after.get(row, fitted_default) >= 409]
        too_short = [row for row, height in before.items()
                     if height + 1 < after.get(row, fitted_default)]
        sheets[sheet] = {
            'visible_rows_measured': len(before), 'saturated_rows': saturated,
            'underfit_rows': too_short, 'merged_cells_need_manual_check': has_merges,
        }
    return {
        'workbook': str(path), 'engine': 'Microsoft Excel', 'sheets': sheets,
        'no_height_risk': not any(s['saturated_rows'] or s['underfit_rows'] for s in sheets.values()),
        'formal_visual_acceptance': False,
    }
