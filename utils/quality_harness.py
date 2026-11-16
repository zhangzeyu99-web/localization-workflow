"""Quality regression harness for localization outputs.

The harness is intentionally independent from one project workbook. It can run
small string fixtures and scan Excel language tables so quality regressions are
caught before final delivery.

Implementation detail: row-level rule checks live in
utils/quality_harness_rules.py and term-base/sheet detection lives in
utils/quality_harness_terms.py. This module re-exports those symbols so
existing `from utils.quality_harness import ...` imports keep working.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Sequence

from openpyxl import load_workbook

from utils.language_config import normalize_language_code
from utils.name_policy import evaluate_name_translation, find_name_collisions, resolve_name_type
from utils.punctuation_policy import punctuation_issues
from utils.readability_checker import TEXT_TYPE_HEADERS, check_readability
from utils.review_consistency import GROUP_HARD_ISSUES, group_issues, history_issues, load_history_rows, normalized
from utils.quality_harness_rules import (  # noqa: F401  (re-exported)
    BROKEN_BULLET_PATTERN,
    CJK_PATTERN,
    COLOR_TAG_PATTERN,
    DEFAULT_HARD_ISSUES,
    FULLWIDTH_PUNCTUATION_PATTERN,
    HASH_CODE_PATTERN,
    HASHED_INTERNAL_CODE_PATTERN,
    HTML_ENTITY_PATTERN,
    HarnessResult,
    INTERNAL_TOKEN_PATTERN,
    LETTER_PLACEHOLDER_COMPACTION_PATTERN,
    MIN_NUMBERED_TERM_GROUP_SIZE,
    NUMBERED_SOURCE_PATTERN,
    NUMBERED_TARGET_PATTERN,
    ORPHAN_LEADING_CLITIC_PATTERN,
    PLACEHOLDER_WORD_GLUE_PATTERN,
    SANDWICHED_QUESTION_PATTERN,
    SOURCE_SEPARATOR_PATTERN,
    WORD_START_PATTERN,
    _append_numbered_term_consistency_issues,
    _check_person_name_terms,
    _check_surface_regressions,
    _check_terms,
    _check_ui_length,
    _choose_numbered_canonical,
    _coerce_check_result,
    _contains_expected_person_name,
    _format_numbered_target_signature,
    _has_leading_lowercase,
    _has_punctuation_corruption,
    _issue,
    _looks_like_allowed_runtime_code,
    _matched_person_name_terms,
    _numbered_item_is_readable,
    _numbered_signature_from_term,
    _parse_numbered_source,
    _parse_numbered_target,
    _primary_term,
    _starts_with_runtime_payload,
    _visible_start,
    check_row,
)
from utils.quality_harness_terms import (  # noqa: F401  (re-exported)
    AUTO_SOFT_SOURCE_TERMS,
    AUTO_SOFT_TARGET_WORDS,
    GENERIC_ROLE_TARGETS,
    GLOSSARY_SHEET_NAMES,
    LANGUAGE_TARGET_HEADERS,
    LANGUAGE_VARIANT_HEADERS,
    LEGAL_TERM_CHECK_MIN_LENGTH,
    LEGAL_TERM_CHECK_SKIP_MARKERS,
    OUTPUT_DIR_NAME_HINTS,
    PERSON_NAME_CATEGORY_MARKERS,
    SOFT_TERM_CATEGORY_MARKERS,
    SUPPORT_SHEET_NAME_KEYWORDS,
    TERM_BASE_FILENAME_KEYWORDS,
    _add_term_lookup_entry,
    _all_target_header_candidates,
    _all_variant_header_candidates,
    _clean_term_cell,
    _collect_term_context,
    _collect_terms_from_json,
    _collect_terms_from_workbook,
    _detect_columns,
    _discover_term_base_paths,
    _fallback_index,
    _find_header,
    _has_explicit_language_header,
    _is_auto_soft_term,
    _is_generic_role_target,
    _is_glossary_sheet,
    _is_person_name_category,
    _is_soft_term_category,
    _is_support_sheet,
    _iter_term_base_paths,
    _looks_like_output_dir,
    _resolve_term_base_paths,
    _should_skip_term_checks,
    _split_term_variants,
    _target_header_candidates,
    _truthy_cell,
    _variant_header_candidates,
)


def load_fixture(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding='utf-8'))


def run_fixture(fixture: dict, lang: str = 'en') -> HarnessResult:
    cases = fixture.get('cases', [])
    result = HarnessResult(passed=True, total_cases=len(cases))
    from utils.semantic_constraints import semantic_constraint_issues
    for case in fixture.get('semantic_constraint_cases', []):
        actual = sorted({kind for kind, _ in semantic_constraint_issues(case['source'], case['target'], case['lang'])})
        result.total_cases += 1
        result.issue_counts.update(actual)
        if actual != sorted(case['expected']):
            result.passed = False
            result.failures.append({'id': case['name'], 'expected_issues': case['expected'], 'actual_issues': actual})
    from utils.quantity_guard import quantity_issues
    for case in fixture.get('quantity_guard_cases', []):
        actual = sorted({kind for kind, _ in quantity_issues(case['source'], case['target'], case['lang'])})
        result.total_cases += 1
        result.issue_counts.update(actual)
        if actual != sorted(case['expected']):
            result.passed = False
            result.failures.append({'id': case['name'], 'expected_issues': case['expected'], 'actual_issues': actual})
    for index, case in enumerate(fixture.get('punctuation_policy_cases', [])):
        actual = sorted(punctuation_issues(case['text'], case['lang'], case.get('mode')))
        result.total_cases += 1
        result.issue_counts.update(actual)
        if actual != sorted(case['expected']):
            result.passed = False
            result.failures.append({'id': f'punctuation-{index}', 'expected_issues': case['expected'], 'actual_issues': actual})
    collision_issues: dict[object, list] = {}
    name_rows = [
        {
            'id': case.get('id', ''),
            'source': case.get('source', ''),
            'translation': case.get('translation', ''),
            'name_type': case.get('name_type', ''),
        }
        for case in cases
        if case.get('name_type')
    ]
    for issue in find_name_collisions(name_rows, lang=lang):
        collision_issues.setdefault(issue.row_id, []).append(issue)

    for case in cases:
        row_id = case.get('id', '')
        case_lang = case.get('lang', lang)
        issues = check_row(
            row_id=row_id,
            source=case.get('source', ''),
            translation=case.get('translation', ''),
            lang=case_lang,
            text_type=case.get('text_type', ''),
        )
        name_type = str(case.get('name_type', ''))
        if name_type:
            issues.extend(
                evaluate_name_translation(
                    row_id=row_id,
                    source=case.get('source', ''),
                    translation=case.get('translation', ''),
                    name_type=name_type,
                    lang=case_lang,
                )
            )
            issues.extend(collision_issues.get(row_id, []))
        actual = sorted({issue.check_type for issue in issues})
        expected = sorted(case.get('expected_issues', []))

        for issue_type in actual:
            result.issue_counts[issue_type] += 1

        if actual != expected:
            result.passed = False
            result.failures.append({
                'id': row_id,
                'source': case.get('source', ''),
                'translation': case.get('translation', ''),
                'expected_issues': expected,
                'actual_issues': actual,
            })

    for case in fixture.get('review_consistency_cases', []):
        def as_rows(pairs):
            return [dict(file='fixture', sheet='UI', row=i + 2, id=i + 1,
                         source=source, translation=target)
                    for i, (source, target) in enumerate(pairs)]

        rows = as_rows(case['rows'])
        found = group_issues(rows) + history_issues(rows, as_rows(case.get('history', [])))
        actual = sorted({issue['check_type'] for issue in found})
        expected = sorted(case['expected'])
        result.total_cases += 1
        result.issue_counts.update(issue['check_type'] for issue in found)
        if actual != expected:
            result.passed = False
            result.failures.append(dict(id=case['name'], expected_issues=expected, actual_issues=actual))
    return result


def scan_workbook(
    path: str | Path,
    lang: str = 'en',
    fail_on: Iterable[str] | None = None,
    term_base: str | Path | Sequence[str | Path] | None = None,
    auto_discover_terms: bool = True,
    history: Sequence[str | Path] | None = None,
    punctuation_mode: str | None = None,
) -> HarnessResult:
    """Scan a workbook language table.

    The scanner expects either headers containing ID/CN/EN-like names or a
    simple first-three-column layout: ID, source, target.
    """
    lang = normalize_language_code(lang)
    fail_set = set(fail_on or (DEFAULT_HARD_ISSUES | GROUP_HARD_ISSUES))
    result = HarnessResult(passed=True)
    workbook_path = Path(path)
    wb = load_workbook(workbook_path, read_only=False, data_only=False)
    scanned_rows: list[dict] = []

    try:
        term_sources = _resolve_term_base_paths(workbook_path, term_base, auto_discover_terms)
        term_context = _collect_term_context(wb, term_sources, lang=lang)
        strong_term_lookup = term_context['strong']
        soft_term_lookup = term_context['soft']
        person_name_terms = term_context['person_names']
        name_type_lookup = term_context['name_types']
        for ws in wb.worksheets:
            if _is_glossary_sheet(ws) or _is_support_sheet(ws):
                continue
            id_col, src_col, tgt_col = _detect_columns(ws, lang=lang)
            if src_col is None or tgt_col is None:
                continue
            type_col = next((i for i, value in enumerate(ws[1])
                             if str(value.value or '').strip().lower() in TEXT_TYPE_HEADERS), None)
            max_col = max(c for c in (id_col, src_col, tgt_col, type_col) if c is not None) + 1
            numbered_rows: list[dict] = []
            name_rows: list[dict] = []
            for row_index, row in enumerate(
                ws.iter_rows(min_row=2, max_col=max_col, values_only=True),
                start=2,
            ):
                row_id = row[id_col] if id_col is not None else row_index
                source = row[src_col]
                target = row[tgt_col]
                if not isinstance(source, str) or not isinstance(target, str):
                    continue

                result.rows_scanned += 1
                numbered_rows.append({
                    'file': str(workbook_path),
                    'sheet': ws.title,
                    'row': row_index,
                    'id': row_id,
                    'source': source,
                    'translation': target,
                })
                name_type = resolve_name_type(source, name_type_lookup)
                text_type = str(row[type_col] or '') if type_col is not None else ''
                row_issues = check_row(row_id, source, target, lang=lang, punctuation_mode=punctuation_mode,
                                       text_type=text_type or name_type)
                row_issues.extend(_check_ui_length(row_id, source, target, lang=lang))
                if name_type:
                    row_issues.extend(
                        evaluate_name_translation(
                            row_id=row_id,
                            source=source,
                            translation=target,
                            name_type=name_type,
                            lang=lang,
                        )
                    )
                    name_rows.append(
                        {
                            'id': row_id,
                            'source': source,
                            'translation': target,
                            'name_type': name_type,
                            'row': row_index,
                        }
                    )
                if not _should_skip_term_checks(source):
                    row_issues.extend(_check_terms(row_id, source, target, strong_term_lookup, lang=lang))
                    row_issues.extend(_check_terms(row_id, source, target, soft_term_lookup, soft=True, lang=lang))
                    row_issues.extend(_check_person_name_terms(row_id, source, target, person_name_terms))
                for issue in row_issues:
                    result.issue_counts[issue.check_type] += 1
                    if issue.check_type in fail_set:
                        result.passed = False
                        result.issues.append({
                            'file': str(workbook_path),
                            'sheet': ws.title,
                            'row': row_index,
                            'id': row_id,
                            'check_type': issue.check_type,
                            'severity': issue.severity,
                            'message': issue.message,
                            'source': source,
                            'translation': target,
                            'auto_fix': issue.auto_fix,
                        })

            _append_numbered_term_consistency_issues(numbered_rows, result, fail_set, strong_term_lookup, lang=lang)
            scanned_rows.extend(numbered_rows)
            for issue in group_issues(numbered_rows):
                result.issue_counts[issue['check_type']] += 1
                if issue['check_type'] in fail_set:
                    result.passed = False
                    result.issues.append(issue)
            name_row_by_id = {row['id']: row for row in name_rows}
            for issue in find_name_collisions(name_rows, lang=lang):
                result.issue_counts[issue.check_type] += 1
                if issue.check_type not in fail_set:
                    continue
                result.passed = False
                row = name_row_by_id.get(issue.row_id, {})
                result.issues.append({
                    'file': str(workbook_path),
                    'sheet': ws.title,
                    'row': row.get('row', 0),
                    'id': issue.row_id,
                    'check_type': issue.check_type,
                    'severity': issue.severity,
                    'message': issue.message,
                    'source': row.get('source', ''),
                    'translation': row.get('translation', ''),
                    'auto_fix': issue.auto_fix,
                })

        if history:
            wanted = {normalized(row['translation']) for row in scanned_rows}
            historical_rows = load_history_rows(history, lang, wanted)
            for issue in history_issues(scanned_rows, historical_rows):
                result.issue_counts[issue['check_type']] += 1
                result.issues.append(issue)
                if issue['check_type'] in fail_set:
                    result.passed = False

        if result.rows_scanned == 0:
            result.passed = False
            result.issue_counts['workbook_scan_empty'] += 1
            result.issues.append({
                'file': str(workbook_path),
                'sheet': '',
                'row': 0,
                'id': '',
                'check_type': 'workbook_scan_empty',
                'severity': 'error',
                'message': 'No workbook rows were scanned; check sheet names and headers before treating QA as passed',
                'source': '',
                'translation': '',
                'auto_fix': '',
            })
    finally:
        wb.close()

    return result


def scan_cache_surface(rows: list[dict], target_langs: list[str]) -> dict:
    """Run existing surface/series rules before XLSX export, never replace final QA."""
    from collections import defaultdict
    from utils.large_text_multilingual_gate import row_translation, source_text

    result = HarnessResult(passed=True)
    fail_set = DEFAULT_HARD_ISSUES | GROUP_HARD_ISSUES
    for raw_lang in target_langs:
        lang = normalize_language_code(raw_lang)
        groups = defaultdict(list)
        for index, row in enumerate(rows, 1):
            source, target = source_text(row), row_translation(row, raw_lang.upper())
            if not source or not target:
                continue  # Coverage and source integrity remain mandatory in cache-lint.
            record = {'file': row.get('source_file', ''), 'sheet': row.get('sheet', ''),
                      'row': row.get('row', index), 'id': row.get('id', row.get('key', index)),
                      'source': source, 'translation': target, 'lang': raw_lang.upper()}
            groups[(record['file'], record['sheet'])].append(record)
            result.rows_scanned += 1
            issues = check_readability(record['id'], source, target, lang=lang,
                                       text_type=str(row.get('text_type') or ''))
            issues += _check_ui_length(record['id'], source, target, lang)
            issues += _check_surface_regressions(record['id'], source, target, lang)
            if any(issue.check_type == 'internal_token_leak' for issue in issues):
                issues = [issue for issue in issues if issue.check_type != 'opaque_abbreviation']
            for issue in issues:
                result.issue_counts[issue.check_type] += 1
                if issue.check_type in fail_set:
                    result.passed = False
                    result.issues.append({**record, 'check_type': issue.check_type,
                                          'severity': issue.severity, 'message': issue.message,
                                          'auto_fix': issue.auto_fix})
        for records in groups.values():
            first_issue = len(result.issues)
            _append_numbered_term_consistency_issues(records, result, fail_set, lang=lang)
            for issue in group_issues(records):
                result.issue_counts[issue['check_type']] += 1
                if issue['check_type'] in fail_set:
                    result.passed = False
                    result.issues.append(issue)
            for issue in result.issues[first_issue:]:
                issue['lang'] = raw_lang.upper()
    return {**result.to_dict(), 'scope': 'surface_and_same_sheet_series_precheck',
            'replaces_final_harness': False, 'hard_blockers': len(result.issues)}


def merge_results(results: list[HarnessResult]) -> HarnessResult:
    merged = HarnessResult(passed=all(r.passed for r in results))
    for result in results:
        merged.total_cases += result.total_cases
        merged.rows_scanned += result.rows_scanned
        merged.issue_counts.update(result.issue_counts)
        merged.issues.extend(result.issues)
        merged.failures.extend(result.failures)
    return merged
