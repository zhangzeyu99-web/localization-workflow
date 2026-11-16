"""Publication checks for the real entry documents, not wording snapshots."""

import json
from pathlib import Path
import re
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
ENTRY_DOCUMENTS = (
    "AGENTS.md",
    "docs/workflow-execution-thread-handoff.md",
    "docs/LARGE_TEXT_MULTILINGUAL_WORKFLOW_V2.md",
    "docs/RELAY_STABLE_EXECUTION.md",
    "docs/TERM_CHANGE_DELIVERY_SYNC.md",
    "templates/translation_prompt_template.txt",
)


def inspect_document(text):
    """Return structural issues and fenced PowerShell, without running examples."""
    issues, blocks = [], []
    if "diff --git a/" in text:
        issues.append("embedded patch header")
    language, body = None, []
    for line in text.splitlines():
        fence = re.fullmatch(r"```([\w-]*)\s*", line)
        if fence:
            if language is None:
                language, body = fence[1], []
            elif fence[1]:
                issues.append("nested or unclosed code fence")
            else:
                if language == "powershell":
                    block = "\n".join(body)
                    blocks.append(block)
                    # Chinese paths/arguments/comments are valid. Narrative at
                    # the start of a command line is the actual publication bug.
                    if re.search(r"(?m)^\s*[\u3400-\u9fff]", block):
                        issues.append("prose inside PowerShell example")
                language = None
        elif language is not None:
            body.append(line)
    if language is not None:
        issues.append("unclosed code fence")
    return issues, blocks


@pytest.mark.parametrize("relative", ENTRY_DOCUMENTS)
def test_entry_documents_have_clean_patch_and_fence_boundaries(relative):
    issues, _ = inspect_document((ROOT / relative).read_text(encoding="utf-8-sig"))
    assert not issues, f"{relative}: {issues}"


@pytest.mark.parametrize(
    "bad_text",
    (
        "A rule.diff --git a/docs/next.md b/docs/next.md\n",
        "```powershell\n项目说明应放在代码块外。\npython cli.py\n```\n",
        "```powershell\npython cli.py\n",
    ),
)
def test_document_check_rejects_the_published_failure_shapes(bad_text):
    assert inspect_document(bad_text)[0]


def test_document_check_keeps_chinese_paths_and_comments():
    text = '```powershell\n# 项目内执行\npython cli.py --input "<语言表.xlsx>"\n```\n'
    assert not inspect_document(text)[0]


def test_powershell_examples_parse_without_execution():
    shell = shutil.which("pwsh") or shutil.which("powershell")
    if not shell:
        pytest.skip("PowerShell parser is unavailable on this platform")
    blocks = []
    for relative in ENTRY_DOCUMENTS:
        _, examples = inspect_document((ROOT / relative).read_text(encoding="utf-8-sig"))
        blocks.extend({"source": relative, "text": example} for example in examples)
    assert blocks, "Entry documents must expose executable command examples"
    script = r"""
$ErrorActionPreference = 'Stop'
$blocks = [Console]::In.ReadToEnd() | ConvertFrom-Json
$failures = @(foreach ($block in $blocks) {
    $tokens = $null
    $parseErrors = $null
    $null = [System.Management.Automation.Language.Parser]::ParseInput(
        $block.text, [ref]$tokens, [ref]$parseErrors)
    foreach ($problem in $parseErrors) {
        [PSCustomObject]@{source=$block.source; error=$problem.ErrorId}
    }
})
if ($failures.Count) { $failures | ConvertTo-Json -Compress; exit 1 }
"""
    result = subprocess.run(
        [shell, "-NoProfile", "-NonInteractive", "-Command", script],
        input=json.dumps(blocks, ensure_ascii=True),
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
