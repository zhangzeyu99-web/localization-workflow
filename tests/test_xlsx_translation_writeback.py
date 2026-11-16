from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from unittest.mock import patch
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import PatternFill

from utils.xlsx_translation_writeback import _patch_row, _patch_sheet, verify_translation_cache, write_translation_workbooks


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )


class XlsxTranslationWritebackTests(unittest.TestCase):
    def test_self_closed_blank_row_does_not_consume_next_row(self) -> None:
        for prefix in ('', 'x:'):
            with self.subTest(prefix=prefix):
                empty = f'<{prefix}row r="1" />'
                xml = (f'<{prefix}worksheet xmlns:x="urn:test"><{prefix}sheetData>'
                       f'{empty}<{prefix}row r="2"><{prefix}c r="A2"><{prefix}v>7</{prefix}v>'
                       f'</{prefix}c></{prefix}row></{prefix}sheetData></{prefix}worksheet>').encode()
                result = _patch_sheet(xml, [(2, 2, 'accepted')])
                self.assertIn(empty.encode(), result)
                self.assertIn(b'r="B2"', result)
                self.assertIn(b'>accepted<', result)
                with self.assertRaisesRegex(ValueError, 'row is missing: 1'):
                    _patch_sheet(xml, [(1, 2, 'refuse unsupported empty row')])

    def test_patch_groups_rows_preserves_namespace_order_and_carriage_return(self) -> None:
        xml = (b'<x:worksheet xmlns:x="urn:test"><x:sheetData>'
               b'<x:row r="2"><x:c r="A2" s="2" t="n"><x:v>4</x:v></x:c>'
               b'<x:c r="D2" t="inlineStr"><x:is><x:t>keep</x:t></x:is></x:c></x:row>'
               b'<x:row r="3"><x:c r="A3"><x:v>5</x:v></x:c></x:row>'
               b'</x:sheetData><x:extLst/></x:worksheet>')
        with patch('utils.xlsx_translation_writeback._patch_row', wraps=_patch_row) as worker:
            result = _patch_sheet(xml, [(2, 3, 'first'), (2, 2, ' B\r\n '), (2, 3, 'last')])
        self.assertEqual(worker.call_count, 1)
        self.assertIn(b' B&#13;\n ', result)
        self.assertIn(b'xml:space="preserve"', result)
        self.assertLess(result.index(b'r="B2"'), result.index(b'r="C2"'))
        self.assertLess(result.index(b'r="C2"'), result.index(b'r="D2"'))
        self.assertIn(b'<x:c r="A2" s="2" t="n"><x:v>4</x:v></x:c>', result)
        self.assertIn(b'<x:row r="3"><x:c r="A3"><x:v>5</x:v></x:c></x:row>', result)
        self.assertIn(b'>last<', result)
        self.assertNotIn(b'>first<', result)
        with self.assertRaisesRegex(ValueError, 'row is missing: 4'):
            _patch_sheet(xml, [(4, 2, 'value')])

    def test_writeback_preserves_approved_boundary_whitespace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'source.xlsx'
            workbook = Workbook()
            workbook.active.append(['ID', 'CN', 'EN', 'DE'])
            workbook.active.append([1, 'Reward', None, None])
            workbook.save(source)
            workbook.close()
            cache = root / 'cache.jsonl'
            row = {'key': 'source.xlsx::Sheet::1::2', 'id': '1', 'source_file': source.name,
                   'sheet': 'Sheet', 'row': 2, 'cn': 'Reward',
                   'translations': {'EN': '\r\n  Reward  \r', 'DE': '\t  Belohnung \t'}}
            write_jsonl(cache, [row])
            output = root / 'delivery'
            write_translation_workbooks(inputs=[source], cache_jsonl=cache,
                                        target_langs=['EN', 'DE'], output_dir=output)
            result = verify_translation_cache(cache_jsonl=cache, delivery_dir=output,
                                              target_langs=['EN', 'DE'])
            self.assertEqual(result['hard_blockers'], 0)
            saved = load_workbook(output / source.name)
            try:
                self.assertEqual(saved.active['C2'].value, row['translations']['EN'])
                self.assertEqual(saved.active['D2'].value, row['translations']['DE'])
            finally:
                saved.close()
            row['translations']['DE'] = ' \t\n'
            write_jsonl(cache, [row])
            with self.assertRaisesRegex(ValueError, 'blank target translation'):
                write_translation_workbooks(inputs=[source], cache_jsonl=cache,
                                            target_langs=['EN', 'DE'], output_dir=output)

    def test_writeback_handles_underreported_worksheet_dimension(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.xlsx"
            workbook = Workbook()
            sheet = workbook.active
            sheet.append(["ID", "CN", "EN"])
            sheet.append([1, "Attack", None])
            workbook.save(source)
            workbook.close()
            with zipfile.ZipFile(source, "r") as archive:
                entries = {name: archive.read(name) for name in archive.namelist()}
                infos = archive.infolist()
            xml = entries["xl/worksheets/sheet1.xml"].decode("utf-8")
            xml = xml.replace('<dimension ref="A1:C2"/>', '<dimension ref="A1"/>')
            entries["xl/worksheets/sheet1.xml"] = xml.encode("utf-8")
            with zipfile.ZipFile(source, "w") as archive:
                for info in infos:
                    archive.writestr(info, entries[info.filename])
            cache = root / "cache.jsonl"
            write_jsonl(
                cache,
                [
                    {
                        "key": "source.xlsx::Sheet::1::2",
                        "id": "1",
                        "source_file": "source.xlsx",
                        "sheet": "Sheet",
                        "row": 2,
                        "cn": "Attack",
                        "translations": {"EN": "Attack"},
                    }
                ],
            )

            write_translation_workbooks(
                inputs=[source],
                cache_jsonl=cache,
                target_langs=["EN"],
                output_dir=root / "delivery",
            )

            saved = load_workbook(root / "delivery" / "source.xlsx", read_only=True)
            try:
                self.assertEqual(saved["Sheet"]["C2"].value, "Attack")
            finally:
                saved.close()

    def test_writeback_preserves_worksheet_namespace_extensions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.xlsx"
            workbook = Workbook()
            sheet = workbook.active
            sheet.append(["ID", "CN", "EN"])
            sheet.append([1, "Attack", None])
            workbook.save(source)
            workbook.close()
            with zipfile.ZipFile(source, "r") as archive:
                entries = {name: archive.read(name) for name in archive.namelist()}
                infos = archive.infolist()
            xml = entries["xl/worksheets/sheet1.xml"].decode("utf-8")
            xml = xml.replace(
                "<worksheet ",
                '<worksheet xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" '
                'xmlns:x14="http://schemas.microsoft.com/office/spreadsheetml/2009/9/main" '
                'mc:Ignorable="x14" ',
                1,
            ).replace(
                "</worksheet>",
                '<extLst><ext uri="test"><x14:test/></ext></extLst></worksheet>',
            )
            entries["xl/worksheets/sheet1.xml"] = xml.encode("utf-8")
            with zipfile.ZipFile(source, "w") as archive:
                for info in infos:
                    archive.writestr(info, entries[info.filename])
            cache = root / "cache.jsonl"
            write_jsonl(
                cache,
                [{"key": "source.xlsx::Sheet::1::2", "id": "1", "source_file": "source.xlsx", "sheet": "Sheet", "row": 2, "cn": "Attack", "translations": {"EN": "Attack"}}],
            )

            write_translation_workbooks(
                inputs=[source],
                cache_jsonl=cache,
                target_langs=["EN"],
                output_dir=root / "delivery",
            )

            with zipfile.ZipFile(root / "delivery" / "source.xlsx", "r") as archive:
                saved_xml = archive.read("xl/worksheets/sheet1.xml").decode("utf-8")
            self.assertIn("xmlns:x14=", saved_xml)
            self.assertIn('mc:Ignorable="x14"', saved_xml)
            self.assertIn("<x14:test", saved_xml)

    def test_writeback_only_changes_requested_target_cells_and_opens_normally(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.xlsx"
            workbook = Workbook()
            sheet = workbook.active
            sheet.title = "Language"
            sheet.append(["ID", "CN", "Note", "EN", "DE"])
            sheet.append([1001, "Attack", "keep", None, None])
            sheet["C2"].fill = PatternFill("solid", fgColor="00FF00")
            sheet["D2"].fill = PatternFill("solid", fgColor="FFFF00")
            workbook.save(source)
            workbook.close()

            cache = root / "cache.jsonl"
            write_jsonl(
                cache,
                [
                    {
                        "key": "source.xlsx::Language::1001::2",
                        "id": "1001",
                        "source_file": "source.xlsx",
                        "sheet": "Language",
                        "row": 2,
                        "cn": "Attack",
                        "translations": {"EN": "Attack", "DE": "Angriff"},
                    }
                ],
            )

            result = write_translation_workbooks(
                inputs=[source],
                cache_jsonl=cache,
                target_langs=["EN", "DE"],
                output_dir=root / "delivery",
            )

            self.assertEqual(result.written_cells, 2)
            self.assertEqual(result.invalid_style_refs, 0)
            self.assertEqual(result.output_files, 1)
            output = root / "delivery" / "source.xlsx"
            saved = load_workbook(output)
            try:
                sheet = saved["Language"]
                self.assertEqual(sheet["A2"].value, 1001)
                self.assertEqual(sheet["B2"].value, "Attack")
                self.assertEqual(sheet["C2"].value, "keep")
                self.assertEqual(sheet["D2"].value, "Attack")
                self.assertEqual(sheet["E2"].value, "Angriff")
                self.assertEqual(sheet["C2"].fill.fgColor.rgb, "0000FF00")
                self.assertEqual(sheet["D2"].fill.fgColor.rgb, "00FFFF00")
            finally:
                saved.close()

    def test_writeback_rejects_source_text_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.xlsx"
            workbook = Workbook()
            sheet = workbook.active
            sheet.append(["ID", "CN", "EN"])
            sheet.append([1, "Attack", None])
            workbook.save(source)
            workbook.close()
            cache = root / "cache.jsonl"
            write_jsonl(
                cache,
                [
                    {
                        "key": "source.xlsx::Sheet::1::2",
                        "id": "1",
                        "source_file": "source.xlsx",
                        "sheet": "Sheet",
                        "row": 2,
                        "cn": "Changed source",
                        "translations": {"EN": "Attack"},
                    }
                ],
            )

            with self.assertRaisesRegex(ValueError, "source text drift"):
                write_translation_workbooks(
                    inputs=[source],
                    cache_jsonl=cache,
                    target_langs=["EN"],
                    output_dir=root / "delivery",
                )

    def test_writeback_preserves_numeric_zero_source_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.xlsx"
            workbook = Workbook()
            sheet = workbook.active
            sheet.append(["ID", "CN", "EN"])
            sheet.append([1, 0, None])
            workbook.save(source)
            workbook.close()
            cache = root / "cache.jsonl"
            write_jsonl(
                cache,
                [
                    {
                        "key": "source.xlsx::Sheet::1::2",
                        "id": "1",
                        "source_file": "source.xlsx",
                        "sheet": "Sheet",
                        "row": 2,
                        "cn": "0",
                        "translations": {"EN": "0"},
                    }
                ],
            )

            write_translation_workbooks(
                inputs=[source],
                cache_jsonl=cache,
                target_langs=["EN"],
                output_dir=root / "delivery",
            )

            saved = load_workbook(root / "delivery" / "source.xlsx", read_only=True)
            try:
                self.assertEqual(saved["Sheet"]["C2"].value, "0")
            finally:
                saved.close()
            verification = verify_translation_cache(root / "delivery", cache, ["EN"])
            self.assertEqual(verification["hard_blockers"], 0)

    def test_writeback_rejects_repeated_source_row_with_wrong_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.xlsx"
            workbook = Workbook()
            sheet = workbook.active
            sheet.append(["ID", "CN", "EN"])
            sheet.append([1, "Attack", None])
            sheet.append([2, "Attack", None])
            workbook.save(source)
            workbook.close()
            cache = root / "cache.jsonl"
            write_jsonl(
                cache,
                [{"key": "source.xlsx::Sheet::1::2", "id": "1", "source_file": "source.xlsx", "sheet": "Sheet", "row": 3, "cn": "Attack", "translations": {"EN": "First"}}],
            )

            with self.assertRaisesRegex(ValueError, "source row id drift"):
                write_translation_workbooks(
                    inputs=[source],
                    cache_jsonl=cache,
                    target_langs=["EN"],
                    output_dir=root / "delivery",
                )

    def test_cache_readback_detects_nonblank_but_wrong_translation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            delivery = root / "delivery"
            delivery.mkdir()
            workbook = Workbook()
            sheet = workbook.active
            sheet.append(["ID", "CN", "EN"])
            sheet.append([1, "Attack", "Wrong but nonblank"])
            workbook.save(delivery / "source.xlsx")
            workbook.close()
            cache = root / "cache.jsonl"
            write_jsonl(
                cache,
                [{"key": "source.xlsx::Sheet::1::2", "id": "1", "source_file": "source.xlsx", "sheet": "Sheet", "row": 2, "cn": "Attack", "translations": {"EN": "Attack"}}],
            )

            result = verify_translation_cache(delivery, cache, ["EN"])

            self.assertEqual(result["hard_blockers"], 1)
            self.assertEqual(result["issues"][0]["type"], "translation_value_mismatch")


if __name__ == "__main__":
    unittest.main()
