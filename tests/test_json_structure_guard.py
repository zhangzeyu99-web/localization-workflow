from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from openpyxl import Workbook

from utils import structured_text_template as templates
from utils.large_text_multilingual_gate import cache_lint, pair_integrity_issues, readback_gate
from utils.large_text_multilingual_executor import _validate_response
from utils.large_text_multilingual_proofread import _validate_audit, _validate_suggestions
from utils.quality_harness import DEFAULT_HARD_ISSUES, check_row, scan_workbook
from utils.structured_text_template import technical_tokens


JSON_HARD_ISSUES = {
    "target_json_invalid",
    "source_json_invalid",
    "json_structure_mismatch",
    "json_value_changed",
    "json_string_missing",
    "json_token_mismatch",
}


def _json(value: object, *, indent: int | None = None) -> str:
    return json.dumps(value, ensure_ascii=False, indent=indent)


def _issue_types(source: str, target: str) -> set[str]:
    return {kind for kind, _ in templates.json_structure_issues(source, target)}


def _four_section_payload() -> tuple[str, str]:
    """Anonymous counterpart of the escaped four-section localization cell."""
    sections = ["领取奖励" for _ in range(4)]
    for index in range(139):
        sections[index % 4] += f"<color=#ffffff><@{index}>领取奖励</color>"
    for index in range(139, 318):
        sections[index % 4] += f"<@{index}>领取奖励"
    source = json.dumps(sections, ensure_ascii=False)
    target = source.replace("领取奖励", "Claim reward")
    return source, target


def test_extra_closing_brace_is_blocked_even_when_every_runtime_token_matches() -> None:
    source, target = _four_section_payload()
    broken = target + "}"
    assert len(json.loads(source)) == 4
    assert len(re.findall(r"<@\d+>", source)) == 318
    assert len([token for token in technical_tokens(source) if not token.startswith("<@")]) == 278
    assert technical_tokens(source) == technical_tokens(broken)

    issue_types = {kind for kind, _ in pair_integrity_issues({"cn": source}, "EN", broken)}

    assert "target_json_invalid" in issue_types


@pytest.mark.parametrize(
    "target",
    [
        '["Claim reward"]}',
        '["Claim reward"] trailing prose',
        '["Claim reward"] ["Done"]',
        '["Claim reward"',
        '["Claim "reward""]',
        "[NaN]",
        "[Infinity]",
    ],
    ids=["extra-closer", "trailing-prose", "second-root", "truncated", "unescaped-quote", "nan", "infinity"],
)
def test_strict_target_json_consumes_the_entire_cell(target: str) -> None:
    assert "target_json_invalid" in _issue_types('["领取奖励"]', target)


@pytest.mark.parametrize(
    ("source", "target"),
    [
        (["奖励", "完成"], ["Reward"]),
        ({"text": "奖励"}, {"body": "Reward"}),
        ({"nested": ["奖励"]}, {"nested": {"text": "Reward"}}),
        ({"nested": [{"text": "奖励"}]}, {"nested": [{"text": "Reward"}, {"text": "Done"}]}),
        ({"text": "奖励", "count": 3}, {"text": "Reward", "count": "3"}),
        ({"text": "奖励", "enabled": True}, {"text": "Reward", "enabled": 1}),
        (["奖励"], "Reward"),
    ],
    ids=["array-length", "object-keys", "nested-container", "nested-array-length", "number-type", "boolean-type", "root-type"],
)
def test_container_shape_and_scalar_types_cannot_change(source: object, target: object) -> None:
    assert "json_structure_mismatch" in _issue_types(_json(source), _json(target))


@pytest.mark.parametrize(
    ("source", "target"),
    [
        ([{"text": "奖励", "count": 3}], [{"text": "Reward", "count": 4}]),
        ({"text": "奖励", "x": 3, "y": 4}, {"text": "Reward", "x": 4, "y": 3}),
        ({"text": "奖励", "enabled": True}, {"text": "Reward", "enabled": False}),
        ({"text": "奖励", "color": "#ff0000"}, {"text": "Reward", "color": "#00ff00"}),
        ({"text": "奖励", "url": "https://example.invalid/reward"}, {"text": "Reward", "url": "https://example.invalid/other"}),
        (["HTTP://example.invalid/reward"], ["HTTP://example.invalid/other"]),
        (["<@1>"], ["<@1> appended prose"]),
    ],
    ids=["array-number", "numeric-swap", "boolean", "fixed-color", "runtime-url", "uppercase-runtime-url", "pure-protected-string"],
)
def test_fixed_values_are_compared_at_the_original_path(source: object, target: object) -> None:
    assert "json_value_changed" in _issue_types(_json(source), _json(target))


def test_nonempty_localizable_string_cannot_disappear() -> None:
    assert "json_string_missing" in _issue_types('["领取奖励"]', '[""]')


@pytest.mark.parametrize(
    ("source", "target"),
    [
        (["<@1>奖励", "<@2>完成"], ["<@2>Reward", "<@1>Done"]),
        (["<color=#ff0000><@1>奖励</color><@2>"], ["<color=#ff0000><@2>Reward</color><@1>"]),
        (["<c>奖励</c><@1>"], ["<c><@1>Reward</c>"]),
        (["<color=#ff0000>奖励</color>"], ["<color=#00ff00>Reward</color>"]),
        (["<@1>奖励<@1>"], ["<@1>Reward"]),
        (
            ["<color=#ff0000><@1>奖励</color><color=#ff0000><@2>完成</color>"],
            ["<color=#ff0000><@2>Reward</color><color=#ff0000><@1>Done</color>"],
        ),
    ],
    ids=["cross-path-placeholder-swap", "cross-color-placeholder-binding", "cross-real-c-scope", "tag-color-parameter", "placeholder-count", "same-color-distinct-groups"],
)
def test_technical_tokens_must_keep_their_json_path_formatting_scope_and_count(source: object, target: object) -> None:
    assert "json_token_mismatch" in _issue_types(_json(source), _json(target))


@pytest.mark.parametrize(
    ("source", "target"),
    [
        (["每<@1>小时回复<@2>次"], ["Restore <@2> times every <@1> hours"]),
        (["<@1>日<color=#ffffff>活动</color>"], ["<color=#ffffff>Event</color> on day <@1>"]),
    ],
    ids=["natural-order-in-same-segment", "root-placeholder-moves-across-complete-color-group"],
)
def test_plain_json_guard_allows_placeholder_reordering_within_the_same_formatting_scope(source: object, target: object) -> None:
    assert _issue_types(_json(source), _json(target)) == set()


def test_program_owned_review_and_render_still_require_the_original_exact_token_order() -> None:
    source = '["<@1><@2>领取奖励"]'
    target = '["<@2><@1>Claim reward"]'
    assert _issue_types(source, target) == set()

    with pytest.raises(ValueError):
        templates.aligned_review_slots(source, target)

    template = templates.parse_template(source)
    with pytest.raises(ValueError):
        templates.render_template(template, {((0,), 1): "<@2>", ((0,), 3): "<@1>"})


@pytest.mark.parametrize("source", ['[["领取奖励"]', '{"text": "领取奖励"'])
def test_obviously_broken_source_is_reported_as_source_not_target(source: str) -> None:
    issues = _issue_types(source, '["Claim reward"]')
    assert "source_json_invalid" in issues
    assert "target_json_invalid" not in issues


@pytest.mark.parametrize(
    ("source", "target"),
    [
        ("[领取]", "[Claim]"),
        ("[color=red]领取奖励[/color]", "[color=red]Claim reward[/color]"),
        ("{count}", "{count}"),
        ("[{0}]\n{2}", "[{0}]\n{2}"),
        ("获得{count}奖励", "Get {count} rewards"),
        ("普通文案 [选项一/选项二]", "Prose [option one/option two]"),
        ('"奖励"', "Reward"),
    ],
    ids=["literal-list", "bbcode", "runtime-placeholder", "bracketed-numeric-placeholders", "placeholder-prose", "bracket-prose", "json-scalar-out-of-scope"],
)
def test_non_json_text_is_not_promoted_to_a_structured_payload(source: str, target: str) -> None:
    assert _issue_types(source, target) == set()


def test_multiline_nested_json_accepts_escaped_quotes_and_literal_brackets() -> None:
    source = _json(
        {"text": '他说"领取"，显示 [选项] 和 } 字符\\路径', "nested": [3, True, None, {"text": "完成\n继续"}]},
        indent=2,
    )
    target = _json(
        {"nested": [3, True, None, {"text": "Done\nContinue"}], "text": 'He says "Claim", with [options] and } characters\\path'},
        indent=2,
    )

    assert _issue_types(source, target) == set()
    assert _issue_types('["Claim reward"]', '["Collect reward"]') == set()


def test_json_errors_are_hard_blockers_in_the_formal_workbook_harness() -> None:
    assert JSON_HARD_ISSUES <= DEFAULT_HARD_ISSUES
    source, target = _four_section_payload()
    issues = check_row("anonymous-four-sections", source, target + "}", lang="en")
    assert "target_json_invalid" in {issue.check_type for issue in issues}


def test_cache_and_actual_workbook_readback_block_then_accept_the_repaired_cell(tmp_path: Path) -> None:
    source, target = _four_section_payload()
    cache = tmp_path / "cache.jsonl"
    delivery = tmp_path / "delivery"
    delivery.mkdir()
    workbook_path = delivery / "localized.xlsx"

    for actual_target, valid in [(target + "}", False), (target, True)]:
        cache.write_text(
            _json({"key": "anonymous-four-sections", "cn": source, "translations": {"EN": actual_target}}) + "\n",
            encoding="utf-8",
        )
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Content"
        sheet.append(["ID", "CN", "EN"])
        sheet.append(["anonymous-four-sections", source, actual_target])
        workbook.save(workbook_path)
        workbook.close()

        cached = cache_lint(cache, target_langs=["EN"])
        readback = readback_gate(delivery, target_langs=["EN"])
        formal = scan_workbook(workbook_path, lang="en", auto_discover_terms=False)

        assert cached["ok_to_apply"] is valid, cached
        assert readback["readback_verified"] is valid, readback
        assert formal.passed is valid, formal.to_dict()
        if not valid:
            assert "target_json_invalid" in cached["hard_by_type"]
            assert "target_json_invalid" in readback["hard_by_type"]
            assert "target_json_invalid" in formal.issue_counts


@pytest.mark.parametrize(
    "target",
    [
        {"text": "Claim reward", "count": 4, "url": "https://example.invalid/reward"},
        {"text": "Claim reward", "count": 3, "url": "https://example.invalid/other"},
    ],
    ids=["changed-program-number", "changed-runtime-url"],
)
def test_review_refuses_to_adopt_an_already_damaged_target_as_its_template(target: object) -> None:
    source = _json({"text": "领取奖励", "count": 3, "url": "https://example.invalid/reward"})

    with pytest.raises(ValueError):
        templates.aligned_review_slots(source, _json(target))


def test_reviewed_fix_and_controller_rollback_preserve_the_complete_json() -> None:
    source = _json({"text": '<color=#ffffff><@1>领取奖励</color>', "count": 3})
    initial = _json({"text": '<color=#ffffff><@1>Claim reward</color>', "count": 3})
    target_template, slots = templates.aligned_review_slots(source, initial)
    assert len(slots) == 1

    fixed = templates.render_reviewed_target(target_template, slots, {slots[0].slot_key: 'Collect "reward" [now] }'})
    reverted = templates.render_reviewed_target(target_template, slots, {slot.slot_key: slot.target for slot in slots})

    assert json.loads(fixed)["text"] == '<color=#ffffff><@1>Collect "reward" [now] }</color>'
    assert json.loads(fixed)["count"] == 3
    assert technical_tokens(fixed) == technical_tokens(source)
    assert json.loads(reverted) == json.loads(initial)


def test_template_render_cannot_erase_a_nonempty_string_or_change_a_runtime_url() -> None:
    template = templates.parse_template(_json({"text": "领取奖励", "url": "https://example.invalid/reward"}))

    with pytest.raises(ValueError):
        templates.render_template(template, {(("text",), 0): ""})
    with pytest.raises(ValueError):
        templates.render_template(template, {(("url",), 0): "https://example.invalid/other"})


@pytest.mark.parametrize("include_suggested", [False, True], ids=["keep-current-fallback", "keep-explicit-current"])
def test_controller_keep_cannot_preserve_invalid_json(include_suggested: bool) -> None:
    source = '["领取奖励"]'
    broken = '["Claim reward"]}'
    request = {"review_key": "anonymous", "cn": source, "translations": {"EN": broken}}
    suggestion = {"review_key": "anonymous", "lang": "EN", "status": "KEEP", "reason": "unchanged"}
    if include_suggested:
        suggestion["suggested"] = broken

    with pytest.raises(ValueError, match="JSON integrity"):
        _validate_suggestions([request], [suggestion], ["EN"])


def test_controller_fix_can_repair_an_invalid_initial_json_cell() -> None:
    source = '["领取奖励"]'
    repaired = '["Claim reward"]'
    request = {"review_key": "anonymous", "cn": source, "translations": {"EN": repaired + "}"}}
    suggestion = {
        "review_key": "anonymous", "lang": "EN", "status": "FIX",
        "suggested": repaired, "reason": "Remove the invalid closing brace",
    }

    validated = _validate_suggestions([request], [suggestion], ["EN"])

    assert validated[0]["status"] == "FIX"
    assert validated[0]["suggested"] == repaired


@pytest.mark.parametrize("decision", ["ACCEPT", "REVISE"])
def test_controller_audit_cannot_add_a_closing_brace_to_valid_json(decision: str) -> None:
    fix = {
        "review_key": "anonymous", "lang": "EN", "status": "FIX", "cn": '["领取奖励"]',
        "current": '["Claim reward"]', "suggested": '["Collect reward"]',
    }
    audit = {"review_key": "anonymous", "lang": "EN", "decision": decision, "final": '["Collect reward"]}'}

    with pytest.raises(ValueError, match="JSON integrity"):
        _validate_audit([fix], [audit])


@pytest.mark.parametrize("decision_final", ["", '["Collect reward"]'], ids=["empty-final", "valid-final-decoy"])
def test_controller_revert_checks_actual_current_not_suggested_original_or_final(decision_final: str) -> None:
    fix = {
        "review_key": "anonymous", "lang": "EN", "status": "FIX", "cn": '["领取奖励"]',
        "current": '["Claim reward"]}',
        "original": '["Claim reward"]',
        "suggested": '["Collect reward"]',
    }
    audit = {"review_key": "anonymous", "lang": "EN", "decision": "REVERT", "final": decision_final}

    with pytest.raises(ValueError, match="JSON integrity"):
        _validate_audit([fix], [audit])


def test_controller_allows_a_legal_revert_to_the_actual_valid_current_cell() -> None:
    fix = {
        "review_key": "anonymous", "lang": "EN", "status": "FIX", "cn": '["领取奖励"]',
        "current": '["Claim reward"]',
        "original": '["Claim reward"]}',
        "suggested": '["Collect reward"]',
    }
    audit = {"review_key": "anonymous", "lang": "EN", "decision": "REVERT", "final": '["Ignored response"]}'}

    decisions = _validate_audit([fix], [audit])

    assert decisions[("anonymous", "EN")]["decision"] == "REVERT"


def test_non_slot_executor_response_rejects_the_same_bad_json_tail_then_accepts_repair() -> None:
    source, target = _four_section_payload()
    request = {"request_key": "anonymous-whole-cell", "cn": source, "translation_source": source}
    response = {"request_key": "anonymous-whole-cell", "translations": {"EN": target + "}"}}

    with pytest.raises(ValueError, match="JSON integrity"):
        _validate_response([request], [response], ["EN"])

    response["translations"] = {"EN": target}
    assert _validate_response([request], [response], ["EN"]) == {"anonymous-whole-cell": {"EN": target}}
