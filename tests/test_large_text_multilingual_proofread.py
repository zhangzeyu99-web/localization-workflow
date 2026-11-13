from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path

from utils.large_text_multilingual_proofread import run_deep_proofread
from utils.large_text_multilingual_runner import build_manifest
from utils.structured_text_template import technical_tokens


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )


class Reviewer:
    checkpoint_identity = "reviewer-v1"

    def review_batch(self, rows, target_langs):  # type: ignore[no-untyped-def]
        suggestions = []
        for row in rows:
            for lang in target_langs:
                if row["cn"] == "Attack" and lang in {"EN", "DE"}:
                    suggestions.append(
                        {
                            "review_key": row["review_key"],
                            "lang": lang,
                            "status": "FIX",
                            "suggested": "Attack now" if lang == "EN" else "Bad German",
                            "reason": "clarity",
                        }
                    )
                else:
                    suggestions.append(
                        {
                            "review_key": row["review_key"],
                            "lang": lang,
                            "status": "KEEP",
                            "suggested": row["translations"][lang],
                            "reason": "ok",
                        }
                    )
        return suggestions


class Auditor:
    checkpoint_identity = "auditor-v1"

    def audit_batch(self, suggestions):  # type: ignore[no-untyped-def]
        return [
            {
                "review_key": row["review_key"],
                "lang": row["lang"],
                "decision": "ACCEPT" if row["lang"] == "EN" or row['status'] == 'KEEP' else "REVERT",
                "final": row["suggested"],
                "reason": "meaning preserved" if row["lang"] == "EN" else "meaning narrowed",
            }
            for row in suggestions
        ]


class FailingReviewer:
    checkpoint_identity = "reviewer-v1"

    def review_batch(self, rows, target_langs):  # type: ignore[no-untyped-def]
        raise AssertionError("review checkpoints must be reused")


class FailingAuditor:
    checkpoint_identity = "auditor-v1"

    def audit_batch(self, suggestions):  # type: ignore[no-untyped-def]
        raise AssertionError("audit checkpoints must be reused")


class LargeTextMultilingualProofreadTests(unittest.TestCase):
    def test_review_and_audit_retry_only_failed_cells_with_feedback(self) -> None:
        class PartialReviewer(Reviewer):
            checkpoint_identity = 'partial-review'

            def __init__(self):
                self.requests = []

            def review_batch(self, rows, target_langs):
                self.requests.append(rows)
                result = super().review_batch(rows, target_langs)
                if len(self.requests) == 1:
                    result[1]['suggested'] = {'invalid': 'not text'}
                return result

        class PartialAuditor(Auditor):
            checkpoint_identity = 'partial-audit'

            def __init__(self):
                self.requests = []

            def audit_batch(self, rows):
                self.requests.append(rows)
                result = super().audit_batch(rows)
                if len(self.requests) == 1:
                    result[1]['final'] = {'invalid': 'not text'}
                return result

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = [dict(key=str(i), cn=f'Text {i}', context='ui',
                         translations={'EN': f'Text {i}'}) for i in range(30)]
            write_jsonl(root / 'items.jsonl', rows)
            manifest = build_manifest(work_dir=root / 'work', items_jsonl=root / 'items.jsonl',
                                      source_rows_jsonl=None, target_langs=['EN'], workbook_count=1,
                                      relay_config=None, proofread_mode='full')
            reviewer, auditor = PartialReviewer(), PartialAuditor()
            summary = run_deep_proofread(Path(manifest['manifest_path']),
                                        initial_cache=root / 'items.jsonl', reviewer=reviewer, auditor=auditor)
            for requests in (reviewer.requests, auditor.requests):
                self.assertEqual([len(batch) for batch in requests], [30, 1])
                self.assertEqual(requests[1][0]['cn'], 'Text 1')
                self.assertIn('must be text', requests[1][0]['validation_feedback'])
            self.assertEqual(summary.changed_cells, 0)

    def test_partial_checkpoint_survives_exhausted_review_or_audit(self) -> None:
        from utils.large_text_multilingual_proofread import _retry_validated_cells

        for phase in ('review', 'audit'):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as tmp:
                rows = [dict(review_key=str(i), lang='EN') for i in range(3)]
                calls = []

                def request(pending):
                    calls.append(pending)
                    return [{**row, 'valid': row['review_key'] != '1'} for row in pending]

                def validate(trusted, response):
                    if not response['valid']:
                        raise ValueError('unresolved semantic evidence')
                    return {**trusted, 'valid': True}

                checkpoint = Path(tmp) / 'batch.jsonl'
                with self.assertRaisesRegex(ValueError, 'unresolved semantic evidence'):
                    _retry_validated_cells(rows, request, validate, checkpoint,
                                           {(str(i), 'EN'): f'cache-{i}' for i in range(3)}, phase=phase)
                self.assertEqual([len(batch) for batch in calls], [3, 1])
                saved = [json.loads(line) for line in checkpoint.read_text(encoding='utf-8').splitlines()]
                self.assertEqual([row['review_key'] for row in saved], ['0', '2'])
                self.assertTrue(all('validation_feedback' not in row for row in saved))
                self.assertEqual([row['cache_key'] for row in saved], ['cache-0', 'cache-2'])

    def test_failed_deep_review_resumes_from_partial_success_checkpoints(self) -> None:
        for phase in ('review', 'audit'):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as tmp:
                class PartialReviewer(Reviewer):
                    checkpoint_identity = 'resume-partial-review'

                    def __init__(self, fail):
                        self.fail, self.sources = fail, []

                    def review_batch(self, rows, target_langs):
                        self.sources.extend(row['cn'] for row in rows)
                        output = super().review_batch(rows, target_langs)
                        if self.fail:
                            for trusted, response in zip(rows, output):
                                if trusted['cn'] == 'Text 1':
                                    response['suggested'] = {'invalid': True}
                        return output

                class PartialAuditor(Auditor):
                    checkpoint_identity = 'resume-partial-audit'

                    def __init__(self, fail):
                        self.fail, self.sources = fail, []

                    def audit_batch(self, rows):
                        self.sources.extend(row['cn'] for row in rows)
                        output = super().audit_batch(rows)
                        if self.fail:
                            for trusted, response in zip(rows, output):
                                if trusted['cn'] == 'Text 1':
                                    response['final'] = {'invalid': True}
                        return output

                root = Path(tmp)
                rows = [dict(key=str(i), cn=f'Text {i}', context='ui',
                             translations={'EN': f'Text {i}'}) for i in range(3)]
                write_jsonl(root / 'items.jsonl', rows)
                manifest = build_manifest(work_dir=root / 'work', items_jsonl=root / 'items.jsonl',
                                          source_rows_jsonl=None, target_langs=['EN'], workbook_count=1,
                                          relay_config=None, proofread_mode='full')
                with self.assertRaisesRegex(ValueError, 'must be text'):
                    run_deep_proofread(Path(manifest['manifest_path']), initial_cache=root / 'items.jsonl',
                                       reviewer=PartialReviewer(phase == 'review'),
                                       auditor=PartialAuditor(phase == 'audit'))
                reviewer, auditor = PartialReviewer(False), PartialAuditor(False)
                summary = run_deep_proofread(Path(manifest['manifest_path']), initial_cache=root / 'items.jsonl',
                                            reviewer=reviewer, auditor=auditor, batch_size=2)
                if phase == 'review':
                    self.assertEqual(reviewer.sources, ['Text 1'])
                    self.assertCountEqual(auditor.sources, ['Text 0', 'Text 1', 'Text 2'])
                else:
                    self.assertEqual(reviewer.sources, [])
                    self.assertEqual(auditor.sources, ['Text 1'])
                self.assertEqual(summary.changed_cells, 0)

    def test_retry_does_not_silently_accept_duplicate_or_unknown_response_keys(self) -> None:
        from utils.large_text_multilingual_proofread import _retry_validated_cells

        for problem in ('duplicate', 'extra', 'non-object'):
            with self.subTest(problem=problem), tempfile.TemporaryDirectory() as tmp:
                row = dict(review_key='1', lang='EN')

                def request(pending):
                    if problem == 'duplicate':
                        return [row, row]
                    if problem == 'extra':
                        return [row, dict(review_key='unknown', lang='EN')]
                    return [row, 'not an object']

                checkpoint = Path(tmp) / 'batch.jsonl'
                with self.assertRaisesRegex(ValueError, 'coverage mismatch'):
                    _retry_validated_cells([row], request, lambda trusted, response: response,
                                           checkpoint, {('1', 'EN'): 'cache-1'})
                self.assertFalse(checkpoint.exists())

    def test_auditor_receives_trusted_source_current_and_dialogue_context(self) -> None:
        testcase = self
        class GenderReviewer:
            checkpoint_identity = 'gender-reviewer'
            def review_batch(self, rows, target_langs):
                return [{'review_key': row['review_key'], 'lang': 'RU', 'status': 'FIX',
                         'suggested': 'Я выбирала.', 'reason': 'likely female speaker',
                         'context': 'untrusted replacement context', 'current': 'not the original'}
                        for row in rows]

        class EvidenceAuditor:
            checkpoint_identity = 'evidence-auditor'
            def audit_batch(self, suggestions):
                for row in suggestions:
                    testcase.assertEqual(row['current'], 'Я выбирал.')
                    testcase.assertEqual(row['translation_source'], 'I made the choice.')
                    testcase.assertEqual(row['source_mode'], 'en')
                    testcase.assertEqual(row['cn'], '我做出了选择。')
                    testcase.assertEqual(row['context'], 'Speaker: Adrian, male. Addressee: Ella, female.')
                    testcase.assertEqual(row['protected_tokens'], [])
                    testcase.assertEqual(row['risk_flags'], ['dialogue'])
                return [{'review_key': row['review_key'], 'lang': row['lang'],
                         'decision': 'REVERT', 'final': row['current'], 'reason': 'speaker evidence contradicts suggestion'}
                        for row in suggestions]

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            items, initial = root/'items.jsonl', root/'initial.jsonl'
            rows = [{'key':'1','cn':'我做出了选择。','translation_source':'I made the choice.',
                     'reference_en':'I made the choice.','source_mode':'en',
                     'context':'Speaker: Adrian, male. Addressee: Ella, female.',
                     'tokens':[], 'risk_flags':['dialogue'], 'translations':{'RU':'Я выбирал.'}}]
            write_jsonl(items, rows)
            write_jsonl(initial, rows)
            manifest=build_manifest(work_dir=root/'work',items_jsonl=items,source_rows_jsonl=None,
                target_langs=['RU'],workbook_count=1,relay_config=None,proofread_mode='full',source_mode='en')
            summary=run_deep_proofread(Path(manifest['manifest_path']),initial_cache=initial,
                reviewer=GenderReviewer(),auditor=EvidenceAuditor())
            self.assertEqual(summary.changed_cells,0)
            self.assertEqual(summary.reverted_changes,1)
            self.assertEqual(json.loads(summary.final_cache.read_text(encoding='utf-8'))['translations']['RU'],'Я выбирал.')

    def test_controller_reverts_suggestion_that_changes_literal_newline_token(self) -> None:
        class NewlineReviewer:
            checkpoint_identity = "newline-reviewer"

            def review_batch(self, rows, target_langs):  # type: ignore[no-untyped-def]
                return [
                    {
                        "review_key": row["review_key"],
                        "lang": target_langs[0],
                        "status": "FIX",
                        "suggested": "First line\nSecond line",
                        "reason": "style",
                    }
                    for row in rows
                ]

        class AcceptingAuditor:
            checkpoint_identity = "newline-auditor"

            def audit_batch(self, suggestions):  # type: ignore[no-untyped-def]
                return [
                    {
                        "review_key": row["review_key"],
                        "lang": row["lang"],
                        "decision": "ACCEPT",
                        "final": row["suggested"],
                        "reason": "accepted",
                    }
                    for row in suggestions
                ]

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            items = root / "items.jsonl"
            initial = root / "initial.jsonl"
            rows = [
                {
                    "key": "1",
                    "cn": r"第一行\n第二行",
                    "context": "ui",
                    "tokens": [r"\n"],
                    "translations": {"EN": r"Line one\nLine two"},
                }
            ]
            write_jsonl(items, rows)
            write_jsonl(initial, rows)
            manifest = build_manifest(
                work_dir=root / "work",
                items_jsonl=items,
                source_rows_jsonl=None,
                target_langs=["EN"],
                workbook_count=1,
                relay_config=None,
                proofread_mode="full",
            )

            summary = run_deep_proofread(
                Path(manifest["manifest_path"]),
                initial_cache=initial,
                reviewer=NewlineReviewer(),
                auditor=AcceptingAuditor(),
            )

            output = json.loads(summary.final_cache.read_text(encoding="utf-8"))
            self.assertEqual(output["translations"]["EN"], r"Line one\nLine two")
            self.assertEqual(summary.changed_cells, 0)

    def test_controller_keeps_exact_glossary_seed_locked(self) -> None:
        class GlossaryReviewer:
            checkpoint_identity = "glossary-reviewer"

            def review_batch(self, rows, target_langs):  # type: ignore[no-untyped-def]
                return [
                    {
                        "review_key": row["review_key"],
                        "lang": target_langs[0],
                        "status": "FIX",
                        "suggested": "Titan's Warblade",
                        "reason": "style",
                    }
                    for row in rows
                ]

        class AcceptingAuditor:
            checkpoint_identity = "glossary-auditor"

            def audit_batch(self, suggestions):  # type: ignore[no-untyped-def]
                return [
                    {
                        "review_key": row["review_key"],
                        "lang": row["lang"],
                        "decision": "ACCEPT",
                        "final": row["suggested"],
                        "reason": "accepted",
                    }
                    for row in suggestions
                ]

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            items = root / "items.jsonl"
            initial = root / "initial.jsonl"
            rows = [
                {
                    "key": "1",
                    "cn": "泰坦战刃",
                    "context": "ui",
                    "seed_origin": "glossary_exact",
                    "translations": {"EN": "Titan Warblade"},
                }
            ]
            write_jsonl(items, rows)
            write_jsonl(initial, rows)
            manifest = build_manifest(
                work_dir=root / "work",
                items_jsonl=items,
                source_rows_jsonl=None,
                target_langs=["EN"],
                workbook_count=1,
                relay_config=None,
                proofread_mode="full",
            )

            summary = run_deep_proofread(
                Path(manifest["manifest_path"]),
                initial_cache=initial,
                reviewer=GlossaryReviewer(),
                auditor=AcceptingAuditor(),
            )

            output = json.loads(summary.final_cache.read_text(encoding="utf-8"))
            self.assertEqual(output["translations"]["EN"], "Titan Warblade")
            self.assertEqual(summary.changed_cells, 0)

    def test_structured_deep_review_never_exposes_or_rebuilds_code(self) -> None:
        class PlainReviewer:
            checkpoint_identity = "plain-structured-reviewer"

            def review_batch(self, rows, target_langs):  # type: ignore[no-untyped-def]
                suggestions = []
                for row in rows:
                    for field in ("cn", "translation_source", "context"):
                        value = str(row.get(field) or "")
                        if any(token in value for token in ("<", "{", "[")):
                            raise AssertionError(f"reviewer received structure: {value}")
                    current = row["translations"][target_langs[0]]
                    fix = row["cn"] == "今日打包"
                    suggestions.append(
                        {
                            "review_key": row["review_key"],
                            "lang": target_langs[0],
                            "status": "FIX" if fix else "KEEP",
                            "suggested": "Daily Bundle" if fix else current,
                            "reason": "terminology" if fix else "ok",
                        }
                    )
                return suggestions

        class PlainAuditor:
            checkpoint_identity = "plain-structured-auditor"

            def audit_batch(self, suggestions):  # type: ignore[no-untyped-def]
                for row in suggestions:
                    if any(token in str(row.get("suggested") or "") for token in ("<", "{", "[")):
                        raise AssertionError("auditor received structure")
                return [
                    {
                        "review_key": row["review_key"],
                        "lang": row["lang"],
                        "decision": "ACCEPT",
                        "final": row["suggested"],
                        "reason": "clear improvement",
                    }
                    for row in suggestions
                ]

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            items = root / "items.jsonl"
            initial = root / "initial.jsonl"
            source = json.dumps(
                ["<color=#<@1>><@2>今日打包</color>", "章节一"],
                ensure_ascii=False,
            )
            target = json.dumps(
                ["<color=#<@1>><@2>Daily Pack</color>", "Chapter I"],
                ensure_ascii=False,
            )
            rows = [
                {
                    "key": "1",
                    "cn": source,
                    "context": "ui",
                    "term_hits": [],
                    "translations": {"EN": target},
                }
            ]
            write_jsonl(items, rows)
            write_jsonl(initial, rows)
            manifest = build_manifest(
                work_dir=root / "work",
                items_jsonl=items,
                source_rows_jsonl=None,
                target_langs=["EN"],
                workbook_count=1,
                relay_config=None,
                proofread_mode="full",
            )

            summary = run_deep_proofread(
                Path(manifest["manifest_path"]),
                initial_cache=initial,
                reviewer=PlainReviewer(),
                auditor=PlainAuditor(),
            )

            output = json.loads(summary.final_cache.read_text(encoding="utf-8"))
            final_text = output["translations"]["EN"]
            self.assertEqual(technical_tokens(final_text), technical_tokens(source))
            self.assertEqual(json.loads(final_text)[0], "<color=#<@1>><@2>Daily Bundle</color>")
            self.assertEqual(summary.changed_cells, 1)

    def test_sampled_mode_reviews_high_risk_rows_and_ten_percent_of_low_risk_rows(self) -> None:
        class RecordingReviewer(Reviewer):
            checkpoint_identity = "sampled-reviewer"

            def __init__(self) -> None:
                self.sources: list[str] = []

            def review_batch(self, rows, target_langs):  # type: ignore[no-untyped-def]
                self.sources.extend(str(row["cn"]) for row in rows)
                return super().review_batch(rows, target_langs)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            items = root / "items.jsonl"
            initial = root / "initial.jsonl"
            rows = [
                {
                    "key": str(index),
                    "cn": "高风险" * 151 if index == 0 else f"低风险 {index}",
                    "context": "ui",
                    "risk_flags": ["qa_failed_once"] if index == 1 else [],
                    "translations": {"EN": f"Text {index}"},
                }
                for index in range(21)
            ]
            write_jsonl(items, rows)
            write_jsonl(initial, rows)
            manifest = build_manifest(
                work_dir=root / "work",
                items_jsonl=items,
                source_rows_jsonl=None,
                target_langs=["EN"],
                workbook_count=1,
                relay_config=None,
                proofread_mode="sampled",
            )
            reviewer = RecordingReviewer()

            summary = run_deep_proofread(
                Path(manifest["manifest_path"]),
                initial_cache=initial,
                reviewer=reviewer,
                auditor=Auditor(),
                batch_size=10,
            )

            self.assertEqual(summary.reviewed_rows, 4)
            self.assertEqual(len(reviewer.sources), 4)
            self.assertIn("高风险" * 151, reviewer.sources)
            self.assertIn("低风险 1", reviewer.sources)

    def test_review_retries_transient_coverage_mismatch(self) -> None:
        class FlakyReviewer(Reviewer):
            checkpoint_identity = "flaky-reviewer-v1"

            def __init__(self) -> None:
                self.calls = 0

            def review_batch(self, rows, target_langs):  # type: ignore[no-untyped-def]
                self.calls += 1
                suggestions = super().review_batch(rows, target_langs)
                if self.calls == 1:
                    suggestions[0]["review_key"] += "bad"
                return suggestions

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            items = root / "items.jsonl"
            initial = root / "initial.jsonl"
            rows = [{"key": "1", "cn": "Attack", "context": "ui", "translations": {"EN": "Attack"}}]
            write_jsonl(items, rows)
            write_jsonl(initial, rows)
            manifest = build_manifest(
                work_dir=root / "work",
                items_jsonl=items,
                source_rows_jsonl=None,
                target_langs=["EN"],
                workbook_count=1,
                relay_config=None,
                proofread_mode="full",
            )
            reviewer = FlakyReviewer()

            summary = run_deep_proofread(
                Path(manifest["manifest_path"]),
                initial_cache=initial,
                reviewer=reviewer,
                auditor=Auditor(),
            )

            self.assertEqual(reviewer.calls, 2)
            self.assertEqual(summary.changed_cells, 1)

    def test_blank_keep_suggestion_reuses_current_translation(self) -> None:
        class BlankKeepReviewer:
            checkpoint_identity = "blank-keep-reviewer-v1"

            def review_batch(self, rows, target_langs):  # type: ignore[no-untyped-def]
                return [
                    {
                        "review_key": row["review_key"],
                        "lang": lang,
                        "status": "KEEP",
                        "suggested": "",
                        "reason": "no change needed",
                    }
                    for row in rows
                    for lang in target_langs
                ]

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            items = root / "items.jsonl"
            initial = root / "initial.jsonl"
            rows = [
                {
                    "key": "1",
                    "cn": "载具维修",
                    "context": "ui",
                    "translations": {"EN": "Vehicle Repair"},
                }
            ]
            write_jsonl(items, rows)
            write_jsonl(initial, rows)
            manifest = build_manifest(
                work_dir=root / "work",
                items_jsonl=items,
                source_rows_jsonl=None,
                target_langs=["EN"],
                workbook_count=1,
                relay_config=None,
                proofread_mode="full",
            )

            summary = run_deep_proofread(
                Path(manifest["manifest_path"]),
                initial_cache=initial,
                reviewer=BlankKeepReviewer(),
                auditor=Auditor(),
            )

            suggestions = [
                json.loads(line)
                for line in summary.suggestions_jsonl.read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(suggestions[0]["suggested"], "Vehicle Repair")
            self.assertEqual(summary.changed_cells, 0)

    def test_audit_batches_use_configured_workers(self) -> None:
        class FixAllReviewer:
            checkpoint_identity = "fix-all-reviewer-v1"

            def review_batch(self, rows, target_langs):  # type: ignore[no-untyped-def]
                return [
                    {
                        "review_key": row["review_key"],
                        "lang": lang,
                        "status": "FIX",
                        "suggested": f"{row['translations'][lang]} fixed",
                        "reason": "clarity",
                    }
                    for row in rows
                    for lang in target_langs
                ]

        class ConcurrentAuditor:
            checkpoint_identity = "concurrent-auditor-v1"

            def __init__(self) -> None:
                self.active = 0
                self.max_active = 0
                self.lock = threading.Lock()

            def audit_batch(self, suggestions):  # type: ignore[no-untyped-def]
                with self.lock:
                    self.active += 1
                    self.max_active = max(self.max_active, self.active)
                time.sleep(0.05)
                with self.lock:
                    self.active -= 1
                return [
                    {
                        "review_key": row["review_key"],
                        "lang": row["lang"],
                        "decision": "ACCEPT",
                        "final": row["suggested"],
                        "reason": "meaning preserved",
                    }
                    for row in suggestions
                ]

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            items = root / "items.jsonl"
            initial = root / "initial.jsonl"
            rows = [
                {
                    "key": str(index),
                    "cn": f"Text {index}",
                    "context": "ui",
                    "translations": {"EN": f"Text {index}"},
                }
                for index in range(4)
            ]
            write_jsonl(items, rows)
            write_jsonl(initial, rows)
            manifest = build_manifest(
                work_dir=root / "work",
                items_jsonl=items,
                source_rows_jsonl=None,
                target_langs=["EN"],
                workbook_count=1,
                relay_config=None,
                proofread_mode="full",
            )
            auditor = ConcurrentAuditor()

            run_deep_proofread(
                Path(manifest["manifest_path"]),
                initial_cache=initial,
                reviewer=FixAllReviewer(),
                auditor=auditor,
                batch_size=1,
                workers=2,
            )

            self.assertGreaterEqual(auditor.max_active, 2)

    def test_concurrent_proofread_owner_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            items = root / "items.jsonl"
            initial = root / "initial.jsonl"
            rows = [
                {
                    "key": "1",
                    "cn": "Attack",
                    "context": "ui",
                    "translations": {"EN": "Attack"},
                }
            ]
            write_jsonl(items, rows)
            write_jsonl(initial, rows)
            manifest = build_manifest(
                work_dir=root / "work",
                items_jsonl=items,
                source_rows_jsonl=None,
                target_langs=["EN"],
                workbook_count=1,
                relay_config=None,
                proofread_mode="full",
            )
            proof_dir = root / "work" / "deep_proofread"
            proof_dir.mkdir(parents=True)
            (proof_dir / "proofread.lock").write_text(
                json.dumps({"pid": os.getpid()}),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(RuntimeError, "already running"):
                run_deep_proofread(
                    Path(manifest["manifest_path"]),
                    initial_cache=initial,
                    reviewer=Reviewer(),
                    auditor=Auditor(),
                )

    def test_review_batches_are_isolated_by_language(self) -> None:
        class TrackingReviewer(Reviewer):
            checkpoint_identity = "tracking-reviewer-v1"

            def __init__(self) -> None:
                self.target_lang_batches: list[list[str]] = []

            def review_batch(self, rows, target_langs):  # type: ignore[no-untyped-def]
                self.target_lang_batches.append(list(target_langs))
                return super().review_batch(rows, target_langs)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            items = root / "items.jsonl"
            initial = root / "initial.jsonl"
            rows = [
                {
                    "key": str(index),
                    "cn": f"Text {index}",
                    "context": "ui",
                    "translations": {"EN": f"Text {index}", "DE": f"Text {index}"},
                }
                for index in range(3)
            ]
            write_jsonl(items, rows)
            write_jsonl(initial, rows)
            manifest = build_manifest(
                work_dir=root / "work",
                items_jsonl=items,
                source_rows_jsonl=None,
                target_langs=["EN", "DE"],
                workbook_count=1,
                relay_config=None,
                proofread_mode="full",
            )
            reviewer = TrackingReviewer()

            run_deep_proofread(
                Path(manifest["manifest_path"]),
                initial_cache=initial,
                reviewer=reviewer,
                auditor=Auditor(),
                batch_size=2,
                workers=2,
            )

            self.assertEqual(len(reviewer.target_lang_batches), 4)
            self.assertTrue(all(len(langs) == 1 for langs in reviewer.target_lang_batches))
            self.assertEqual(
                sorted(lang for batch in reviewer.target_lang_batches for lang in batch),
                ["DE", "DE", "EN", "EN"],
            )

    def test_review_item_checkpoints_survive_batch_size_change(self) -> None:
        class CountingReviewer(Reviewer):
            checkpoint_identity = "item-resume-reviewer-v1"

            def __init__(self) -> None:
                self.calls = 0

            def review_batch(self, rows, target_langs):  # type: ignore[no-untyped-def]
                self.calls += 1
                return super().review_batch(rows, target_langs)

        class MustReuseReviewer(Reviewer):
            checkpoint_identity = "item-resume-reviewer-v1"

            def review_batch(self, rows, target_langs):  # type: ignore[no-untyped-def]
                raise AssertionError("completed review items must be reused")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            items = root / "items.jsonl"
            initial = root / "initial.jsonl"
            rows = [
                {
                    "key": str(index),
                    "cn": f"Text {index}",
                    "context": "ui",
                    "translations": {"EN": f"Text {index}", "DE": f"Text {index}"},
                }
                for index in range(3)
            ]
            write_jsonl(items, rows)
            write_jsonl(initial, rows)
            manifest = build_manifest(
                work_dir=root / "work",
                items_jsonl=items,
                source_rows_jsonl=None,
                target_langs=["EN", "DE"],
                workbook_count=1,
                relay_config=None,
                proofread_mode="full",
            )
            manifest_path = Path(manifest["manifest_path"])
            first = CountingReviewer()

            run_deep_proofread(
                manifest_path,
                initial_cache=initial,
                reviewer=first,
                auditor=Auditor(),
                batch_size=2,
                workers=2,
            )
            self.assertGreater(first.calls, 0)

            run_deep_proofread(
                manifest_path,
                initial_cache=initial,
                reviewer=MustReuseReviewer(),
                auditor=FailingAuditor(),
                batch_size=1,
                workers=2,
            )

    def test_language_edit_only_rechecks_that_languages_related_scene(self) -> None:
        class KeepReviewer:
            checkpoint_identity = "language-isolated-reviewer"

            def __init__(self):
                self.cells = []

            def review_batch(self, rows, target_langs):
                self.cells.extend((row['cn'], lang) for row in rows for lang in target_langs)
                return [{'review_key': row['review_key'], 'lang': lang, 'status': 'KEEP',
                         'suggested': row['translations'][lang], 'reason': 'meaning preserved'}
                        for row in rows for lang in target_langs]

        class KeepAuditor:
            checkpoint_identity = "language-isolated-auditor"

            def __init__(self):
                self.cells = []

            def audit_batch(self, rows):
                self.cells.extend((row['cn'], row['lang']) for row in rows)
                return [{'review_key': row['review_key'], 'lang': row['lang'], 'decision': 'ACCEPT',
                         'final': row['current'], 'reason': 'meaning preserved',
                         'semantic_check': {'source_meaning': row['cn'], 'final_meaning': row['cn'],
                                            'meaning_preserved': True, 'roles_preserved': True, 'tone_preserved': True}}
                        for row in rows]

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            initial = root / 'initial.jsonl'
            rows = [{'key': str(i), 'row': i + 2, 'cn': f'Line {i}',
                     'context': {'type': 'dialogue', 'scene': 'a' if i < 2 else 'b'},
                     'translations': {'EN': f'Line {i}', 'FR': f'Ligne {i}'}}
                    for i in range(3)]
            write_jsonl(initial, rows)
            manifest = build_manifest(work_dir=root / 'work', items_jsonl=initial, source_rows_jsonl=None,
                                      target_langs=['EN', 'FR'], workbook_count=1, relay_config=None,
                                      proofread_mode='full')
            path = Path(manifest['manifest_path'])
            first = run_deep_proofread(path, initial_cache=initial, reviewer=KeepReviewer(),
                                       auditor=KeepAuditor(), batch_size=2)
            self.assertEqual(first.reviewed_cells, 6)
            rows[0]['translations']['FR'] = 'Première ligne'
            write_jsonl(initial, rows)
            reviewer, auditor = KeepReviewer(), KeepAuditor()
            result = run_deep_proofread(path, initial_cache=initial, reviewer=reviewer,
                                        auditor=auditor, batch_size=1)
            expected = [('Line 0', 'FR'), ('Line 1', 'FR')]
            self.assertEqual(sorted(reviewer.cells), expected)
            self.assertEqual(sorted(auditor.cells), expected)
            self.assertEqual(result.reviewed_cells, 6)
            final = [json.loads(line) for line in result.final_cache.read_text(encoding='utf-8').splitlines()]
            self.assertEqual(final[0]['translations']['EN'], 'Line 0')
            self.assertEqual(final[0]['translations']['FR'], 'Première ligne')

    def test_changing_reviewer_identity_does_not_reuse_old_suggestions(self) -> None:
        class OtherReviewer(Reviewer):
            checkpoint_identity = "reviewer-v2"

            def __init__(self) -> None:
                self.calls = 0

            def review_batch(self, rows, target_langs):  # type: ignore[no-untyped-def]
                self.calls += 1
                return super().review_batch(rows, target_langs)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            items = root / "items.jsonl"
            initial = root / "initial.jsonl"
            rows = [
                {"key": "1", "cn": "Attack", "context": "ui", "translations": {"EN": "Attack"}}
            ]
            write_jsonl(items, rows)
            write_jsonl(initial, rows)
            manifest = build_manifest(
                work_dir=root / "work",
                items_jsonl=items,
                source_rows_jsonl=None,
                target_langs=["EN"],
                workbook_count=1,
                relay_config=None,
                proofread_mode="full",
            )
            manifest_path = Path(manifest["manifest_path"])
            run_deep_proofread(
                manifest_path,
                initial_cache=initial,
                reviewer=Reviewer(),
                auditor=Auditor(),
            )
            other = OtherReviewer()

            run_deep_proofread(
                manifest_path,
                initial_cache=initial,
                reviewer=other,
                auditor=Auditor(),
            )

            self.assertEqual(other.calls, 1)

    def test_review_suggestions_require_controller_audit_before_apply(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            items = root / "items.jsonl"
            initial = root / "initial_cache.jsonl"
            rows = [
                {
                    "key": "1",
                    "cn": "Attack",
                    "context": "ui",
                    "tokens": [],
                    "term_hits": [],
                    "translations": {"EN": "Attack", "DE": "Angriff"},
                },
                {
                    "key": "2",
                    "cn": "Defend",
                    "context": "ui",
                    "tokens": [],
                    "term_hits": [],
                    "translations": {"EN": "Defend", "DE": "Verteidigen"},
                },
            ]
            write_jsonl(items, rows)
            write_jsonl(initial, rows)
            manifest = build_manifest(
                work_dir=root / "work",
                items_jsonl=items,
                source_rows_jsonl=None,
                target_langs=["EN", "DE"],
                workbook_count=1,
                relay_config=None,
                proofread_mode="full",
            )
            manifest_path = Path(manifest["manifest_path"])

            summary = run_deep_proofread(
                manifest_path,
                initial_cache=initial,
                reviewer=Reviewer(),
                auditor=Auditor(),
                batch_size=20,
            )

            final_rows = [
                json.loads(line)
                for line in summary.final_cache.read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(final_rows[0]["translations"]["EN"], "Attack now")
            self.assertEqual(final_rows[0]["translations"]["DE"], "Angriff")
            self.assertEqual(summary.suggested_changes, 2)
            self.assertEqual(summary.reverted_changes, 1)
            self.assertEqual(summary.changed_cells, 1)
            self.assertEqual(summary.changed_rows, 1)
            saved_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(saved_manifest["phase_status"]["subagent_review"], "done")
            self.assertEqual(saved_manifest["phase_status"]["controller_merge"], "done")

            # Legacy batches have no cell cache key; exact input batches remain reusable.
            for phase in ('review_batches', 'audit_batches'):
                for checkpoint in (root / 'work' / 'deep_proofread' / phase).rglob('*.jsonl'):
                    records = [json.loads(line) for line in checkpoint.read_text(encoding='utf-8').splitlines()]
                    for record in records:
                        record.pop('cache_key', None)
                    write_jsonl(checkpoint, records)
            resumed = run_deep_proofread(
                manifest_path,
                initial_cache=initial,
                reviewer=FailingReviewer(),
                auditor=FailingAuditor(),
                batch_size=20,
            )
            self.assertEqual(resumed.changed_cells, 1)
            promoted = run_deep_proofread(
                manifest_path, initial_cache=initial, reviewer=FailingReviewer(), auditor=FailingAuditor(), batch_size=1,
            )
            self.assertEqual(promoted.changed_cells, 1)

    def test_invalid_audit_item_is_reaudited_instead_of_silently_accepted(self) -> None:
        class CountingAuditor(Auditor):
            def __init__(self):
                self.calls = 0

            def audit_batch(self, rows):
                self.calls += 1
                return super().audit_batch(rows)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            initial = root / 'initial.jsonl'
            write_jsonl(initial, [{'key': '1', 'cn': 'Attack', 'context': 'ui', 'translations': {'EN': 'Attack'}}])
            manifest = build_manifest(work_dir=root / 'work', items_jsonl=initial, source_rows_jsonl=None,
                                      target_langs=['EN'], workbook_count=1, relay_config=None, proofread_mode='full')
            path = Path(manifest['manifest_path'])
            run_deep_proofread(path, initial_cache=initial, reviewer=Reviewer(), auditor=Auditor())
            for checkpoint in (root / 'work' / 'deep_proofread' / 'audit_batches').rglob('*.jsonl'):
                records = [json.loads(line) for line in checkpoint.read_text(encoding='utf-8').splitlines()]
                records[0].update(final='Incorrect cached text', unresolved_issues=['unresolved omission'])
                write_jsonl(checkpoint, records)
            auditor = CountingAuditor()
            result = run_deep_proofread(path, initial_cache=initial, reviewer=FailingReviewer(), auditor=auditor)
            self.assertEqual(auditor.calls, 1)
            self.assertEqual(json.loads(result.final_cache.read_text(encoding='utf-8'))['translations']['EN'], 'Attack now')

    def test_review_rejects_incomplete_suggestion_contract(self) -> None:
        class BadReviewer:
            def review_batch(self, rows, target_langs):  # type: ignore[no-untyped-def]
                return []

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            items = root / "items.jsonl"
            initial = root / "initial.jsonl"
            rows = [
                {"key": "1", "cn": "Attack", "context": "ui", "translations": {"EN": "Attack"}}
            ]
            write_jsonl(items, rows)
            write_jsonl(initial, rows)
            manifest = build_manifest(
                work_dir=root / "work",
                items_jsonl=items,
                source_rows_jsonl=None,
                target_langs=["EN"],
                workbook_count=1,
                relay_config=None,
                proofread_mode="full",
            )

            with self.assertRaisesRegex(ValueError, "review coverage"):
                run_deep_proofread(
                    Path(manifest["manifest_path"]),
                    initial_cache=initial,
                    reviewer=BadReviewer(),
                    auditor=Auditor(),
                )


if __name__ == "__main__":
    unittest.main()
