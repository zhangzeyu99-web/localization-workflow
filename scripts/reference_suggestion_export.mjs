import fs from "node:fs/promises";
import path from "node:path";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const specPath = process.argv[2];
if (!specPath) throw new Error("usage: node reference_suggestion_export.mjs <export_spec.json>");
const spec = JSON.parse(await fs.readFile(specPath, "utf8"));
const manifest = spec.manifest;
const records = spec.review.records;
const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(manifest.source.path));

function columnName(index) {
  let value = index;
  let name = "";
  while (value > 0) {
    value -= 1;
    name = String.fromCharCode(65 + (value % 26)) + name;
    value = Math.floor(value / 26);
  }
  return name;
}

function reviewNote(item) {
  const relation = { corresponding: "对应", similar: "近似", no_match: "无可靠命中" }[item.reference_relation];
  const evidence = item.evidence_ids.length ? item.evidence_ids.join(",") : "无可靠竞品对应";
  const basis = item.basis === "reference" ? "参考竞品" : "项目判断";
  const decision = item.decision === "KEEP" ? "保持原样" : "建议修改";
  return `${item.lang} ${decision} ${item.original_length}→${item.final_length}：${item.reason}；${relation}；${basis}；${evidence}`;
}

const recordsBySheet = new Map();
for (const item of records) {
  if (!recordsBySheet.has(item.sheet)) recordsBySheet.set(item.sheet, []);
  recordsBySheet.get(item.sheet).push(item);
}

for (const sheetSpec of manifest.sheets) {
  const sheet = workbook.worksheets.getItem(sheetSpec.name);
  const rows = Number(sheetSpec.physical_rows);
  const originalColumns = Number(sheetSpec.physical_columns);
  const targetColumns = Object.fromEntries(Object.entries(sheetSpec.columns.targets).map(([lang, col]) => [lang, Number(col)]));
  const targets = Object.values(targetColumns).sort((a, b) => a - b);
  const shiftBefore = (column) => targets.filter((target) => target < column).length;
  const originalWidths = new Map();
  for (let column = 1; column <= originalColumns; column += 1) {
    originalWidths.set(column, sheet.getRange(`${columnName(column)}1:${columnName(column)}${rows}`).format.columnWidth);
  }

  for (let column = originalColumns; column >= 1; column -= 1) {
    const destination = column + shiftBefore(column);
    if (destination !== column) {
      sheet.getRange(`${columnName(destination)}1:${columnName(destination)}${rows}`).copyFrom(
        sheet.getRange(`${columnName(column)}1:${columnName(column)}${rows}`),
        "all",
      );
    }
    const width = originalWidths.get(column);
    if (width !== undefined && width !== null) {
      sheet.getRange(`${columnName(destination)}1:${columnName(destination)}${rows}`).format.columnWidth = width;
    }
  }

  for (const style of sheetSpec.styles || []) {
    const destination = Number(style.column) + shiftBefore(Number(style.column));
    const cell = sheet.getRange(`${columnName(destination)}${style.row}`);
    if (style.number_format) cell.format.numberFormat = style.number_format;
    const font = Object.fromEntries(Object.entries(style.font || {}).filter(([, value]) => value !== null && value !== undefined));
    if (Object.keys(font).length) cell.format.font = font;
    const alignment = style.alignment || {};
    if (alignment.horizontal) cell.format.horizontalAlignment = alignment.horizontal;
    if (alignment.vertical) cell.format.verticalAlignment = alignment.vertical;
    if (alignment.wrap_text !== null && alignment.wrap_text !== undefined) cell.format.wrapText = alignment.wrap_text;
  }

  const suggestionColumns = {};
  for (const [lang, oldColumn] of Object.entries(targetColumns)) {
    const originalColumn = oldColumn + shiftBefore(oldColumn);
    const suggestionColumn = originalColumn + 1;
    suggestionColumns[lang] = suggestionColumn;
    const originalRange = sheet.getRange(`${columnName(originalColumn)}1:${columnName(originalColumn)}${rows}`);
    const suggestionRange = sheet.getRange(`${columnName(suggestionColumn)}1:${columnName(suggestionColumn)}${rows}`);
    suggestionRange.copyFrom(originalRange, "all");
    suggestionRange.clear({ applyTo: "contents" });
    suggestionRange.format.columnWidth = originalRange.format.columnWidth;
    suggestionRange.format.wrapText = true;
    suggestionRange.format.verticalAlignment = "center";
    if (sheetSpec.has_header) suggestionRange.getCell(0, 0).values = [[`${lang}建议`]];
  }

  let noteColumn;
  if (sheetSpec.columns.note) {
    const oldNote = Number(sheetSpec.columns.note);
    noteColumn = oldNote + shiftBefore(oldNote);
  } else {
    noteColumn = originalColumns + targets.length + 1;
  }
  const noteRange = sheet.getRange(`${columnName(noteColumn)}1:${columnName(noteColumn)}${rows}`);
  noteRange.format.wrapText = true;
  noteRange.format.verticalAlignment = "top";
  const priorNoteWidth = Number(noteRange.format.columnWidth || 0);
  noteRange.format.columnWidth = Math.max(priorNoteWidth, 70);

  const byRow = new Map();
  for (const item of recordsBySheet.get(sheetSpec.name) || []) {
    const row = Number(item.row);
    if (!byRow.has(row)) byRow.set(row, []);
    byRow.get(row).push(item);
    const originalColumn = targetColumns[item.lang] + shiftBefore(targetColumns[item.lang]);
    const suggestionColumn = suggestionColumns[item.lang];
    const originalCell = sheet.getRange(`${columnName(originalColumn)}${row}`);
    const suggestionCell = sheet.getRange(`${columnName(suggestionColumn)}${row}`);
    originalCell.format.wrapText = true;
    if (item.decision === "FIX") {
      suggestionCell.values = [[item.suggested]];
      originalCell.format.fill = "#FFF2CC";
      suggestionCell.format.fill = "#DDEBF7";
    } else if (item.green_eligible) {
      originalCell.format.fill = "#E2F0D9";
    }
  }

  const sourceColumn = Number(sheetSpec.columns.source) + shiftBefore(Number(sheetSpec.columns.source));
  sheet.getRange(`${columnName(sourceColumn)}1:${columnName(sourceColumn)}${rows}`).format.wrapText = true;
  for (const [row, items] of byRow.entries()) {
    items.sort((left, right) => Object.keys(targetColumns).indexOf(left.lang) - Object.keys(targetColumns).indexOf(right.lang));
    const noteCell = sheet.getRange(`${columnName(noteColumn)}${row}`);
    const prior = String(noteCell.values?.[0]?.[0] ?? "");
    noteCell.values = [[prior ? `${prior}\n${items.map(reviewNote).join("\n")}` : items.map(reviewNote).join("\n")]];
    sheet.getRange(`A${row}:${columnName(noteColumn)}${row}`).format.autofitRows();
  }
}

workbook.recalculate();
const errorScan = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!",
  options: { useRegex: true, maxResults: 100 },
  summary: "reference suggestion export formula error scan",
});
const firstSpec = manifest.sheets[0];
const firstRecords = records.filter((item) => item.sheet === firstSpec.name);
const rowsForPreview = [...new Set(firstRecords.map((item) => item.row))].map((row) => {
  const items = firstRecords.filter((item) => item.row === row);
  return {
    row,
    primary: Math.max(...items.flatMap((item) => [item.original_length, item.final_length])),
    secondary: Math.max(...items.map((item) => reviewNote(item).length)),
  };
});
const compareRisk = (left, right) => left.primary - right.primary || left.secondary - right.secondary;
const shortRow = rowsForPreview.reduce((best, item) => compareRisk(item, best) < 0 ? item : best, rowsForPreview[0]);
const longRow = rowsForPreview.reduce((best, item) => compareRisk(item, best) > 0 ? item : best, rowsForPreview[0]);
const lastColumn = firstSpec.physical_columns + Object.keys(firstSpec.columns.targets).length + (firstSpec.columns.note ? 0 : 1);
for (const [item, output] of [[shortRow, spec.preview_short], [longRow, spec.preview_long]]) {
  const preview = await workbook.render({ sheetName: firstSpec.name, range: `A${item.row}:${columnName(lastColumn)}${item.row}`, scale: 1.2, format: "png" });
  await fs.mkdir(path.dirname(output), { recursive: true });
  await fs.writeFile(output, new Uint8Array(await preview.arrayBuffer()));
}
const inspect = await workbook.inspect({
  kind: "table",
  range: `${firstSpec.name}!A1:${columnName(lastColumn)}${firstSpec.physical_rows}`,
  include: "values,formulas",
  tableMaxRows: Math.min(30, firstSpec.physical_rows),
  tableMaxCols: Math.min(20, lastColumn),
  maxChars: 30000,
});
await fs.mkdir(path.dirname(spec.output), { recursive: true });
const blob = await SpreadsheetFile.exportXlsx(workbook);
await blob.save(spec.output);
await fs.writeFile(spec.verification, `${inspect.ndjson}\n${errorScan.ndjson}\n`, "utf8");
console.log(JSON.stringify({ output: spec.output, output_sha256: "deferred_to_verify", preview_short: spec.preview_short, preview_long: spec.preview_long, records: records.length }));
