# 大文本多语言工作流加速与可靠性修复实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把上一批依赖临时脚本的十语言任务固化为可恢复、可计时、可验证的一键工作流，将同规模任务的用户感知耗时从约 59 分钟压缩到 12-18 分钟，同时保持完整逐行审校和 0 hard blocker。

**Architecture:** 在现有 `large_text_multilingual_runner/gate/retro` 之上补齐四个缺口：高性能工作簿抽取、OpenAI-compatible API 执行器、独立审校与二次纠偏控制器、精确 XLSX XML 写回。所有阶段统一更新 manifest，最终由 cache-lint、语言专项 QA、普通模式打开验证和 readback-gate 共同放行。

**Tech Stack:** Python 3.14、`openpyxl`、标准库 `urllib.request`、`zipfile`、JSONL、`unittest`。

## Global Constraints

- 固定源仓库：`D:\project\localization-workflow-project`；不直接修改 `D:\codex\localization-workflow-studio`。
- 保留当前工作区已有修改；执行前按文件审阅 diff，不重置或覆盖无关改动。
- 翻译模型使用本地私有配置中的 OpenAI-compatible API；manifest、日志、测试 fixture 不得写入 API key。
- 不使用 Google Translate、`googletrans`、`deep_translator` 或浏览器机翻。
- 全量逐行审校必须是独立阶段；建议只输出建议，主控制器负责应用、二次纠偏和写回。
- 最终交付目录只保留成品工作簿和 `QA摘要.xlsx`。
- 所有生产代码改动遵循 TDD：先写失败测试并确认失败，再做最小实现。
- 性能验收以 2 个工作簿、267 行、145 条唯一中文、10 种语言、2670 个目标单元格为基准 fixture。

---

### Task 1: 收口现有 QA 误报和报告误识别

**Files:**
- Modify: `utils/readability_checker.py`
- Modify: `utils/quality_harness_terms.py`
- Modify: `utils/large_text_multilingual_gate.py`
- Modify: `tests/test_readability_checker.py`
- Modify: `tests/test_quality_harness.py`
- Modify: `tests/test_large_text_multilingual_gate.py`

**Interfaces:**
- Consumes: `check_readability(row_id, original, translation, lang)`、`_detect_columns(ws, lang)`、`readback_gate(delivery_dir, target_langs)`。
- Produces: 只对英语执行英语裁词词典；`ID` 主键不再抢占 `IDN` 列；`QA摘要.xlsx` 不再被当成翻译工作簿。

- [ ] **Step 1: 保留并复核当前两个失败用例**

```python
def test_does_not_apply_english_clipped_word_dictionary_to_spanish():
    issues = check_readability(1, "我是玩家名字", "Soy el nombre del jugador de capa alta", lang="es")
    assert "clipped_word" not in {issue.check_type for issue in issues}

def test_scan_workbook_uses_idn_column_instead_of_id_primary_key():
    # Workbook headers: ID, CN, IDN; scanner must read IDN, not numeric ID.
    assert result.rows_scanned == 1
    assert result.passed
```

- [ ] **Step 2: 新增 QA 摘要误识别失败用例并确认 RED**

```python
def test_readback_gate_skips_qa_summary_support_sheets():
    # QA摘要.xlsx contains Summary, LineReview, Changes and Issues sheets.
    result = readback_gate(delivery, target_langs=["EN", "IDN"])
    assert result.hard_blockers == 0
```

Run:

```powershell
python -m unittest tests.test_readability_checker tests.test_quality_harness tests.test_large_text_multilingual_gate -v
```

Expected before implementation: QA 摘要用例因 `target_column_missing` 失败。

- [ ] **Step 3: 实现最小修复**

```python
SUPPORT_WORKBOOK_NAMES = {"qa摘要.xlsx", "qa_summary.xlsx"}
SUPPORT_SHEET_NAMES = {"summary", "linereview", "changes", "issues", "filestats"}

def _is_delivery_support_sheet(path: Path, sheet_title: str) -> bool:
    return path.name.lower() in SUPPORT_WORKBOOK_NAMES or sheet_title.lower() in SUPPORT_SHEET_NAMES
```

同时保持：`clipped_word` 仅在 `lang == "en"` 时执行；当 `tgt_col == id_col` 时移除冲突的 `id` 候选并重新查找 `IDN`。

- [ ] **Step 4: 跑相关测试并提交独立修复**

```powershell
python -m unittest tests.test_readability_checker tests.test_quality_harness tests.test_large_text_multilingual_gate -v
git add utils/readability_checker.py utils/quality_harness_terms.py utils/large_text_multilingual_gate.py tests/test_readability_checker.py tests/test_quality_harness.py tests/test_large_text_multilingual_gate.py
git commit -m "fix(qa): avoid multilingual false positives"
```

Expected: 相关测试全部通过；西语 `del/capa`、`ID/IDN`、QA 摘要误识别均有回归覆盖。

---

### Task 2: 增加高性能多工作簿抽取与去重准备层

**Files:**
- Create: `utils/large_text_multilingual_pack.py`
- Create: `scripts/prepare_large_text_multilingual_pack.py`
- Create: `tests/test_large_text_multilingual_pack.py`
- Modify: `utils/large_text_multilingual_runner.py`

**Interfaces:**
- Produces: `prepare_pack(inputs, term_base, history_dirs, target_langs, work_dir) -> PackArtifacts`。
- Artifacts: `items.jsonl`、`source_rows.jsonl`、`seed_memory.json`、`prepare_stats.json`。
- Row contract: `key,id,source_file,sheet,row,context,cn,tokens,term_hits,seed_origin`。

- [ ] **Step 1: 写入 267 行、10 语言 fixture 的失败测试**

```python
def test_prepare_pack_uses_iter_rows_and_deduplicates_api_items():
    result = prepare_pack(inputs, terms, history_dirs=[], target_langs=LANGS, work_dir=work)
    assert result.source_rows == 267
    assert result.unique_items == 145
    assert result.estimated_target_cells == 2670
    assert result.elapsed_seconds < 5
```

- [ ] **Step 2: 确认测试因入口不存在而失败**

```powershell
python -m unittest tests.test_large_text_multilingual_pack -v
```

- [ ] **Step 3: 实现线性读取和稳定 key**

```python
@dataclass(frozen=True)
class PackArtifacts:
    items_jsonl: Path
    source_rows_jsonl: Path
    prepare_stats: Path
    source_rows: int
    unique_items: int
    estimated_target_cells: int
    elapsed_seconds: float

def stable_row_key(source_file: str, sheet: str, row: int, row_id: object) -> str:
    return f"{source_file}::{sheet}::{row_id}::{row}"
```

读取必须使用一次 `iter_rows(values_only=True)`；禁止在 `read_only=True` 工作簿中循环调用 `sheet.cell()`。术语检索按最长词优先，历史译文只做整句精确匹配。

- [ ] **Step 4: 把 prepare 接入 runner**

新增 CLI：

```powershell
python scripts\run_large_text_multilingual_runner.py prepare-pack `
  --input a.xlsx --input b.xlsx `
  --term-base terms.xlsx `
  --target-langs EN,IDN,DE,FR,ES,PT,RU,IT,TR,TH `
  --work-dir <work_dir> --proofread-mode full
```

- [ ] **Step 5: 验证性能和断言源列不漂移**

```powershell
python -m unittest tests.test_large_text_multilingual_pack tests.test_large_text_multilingual_runner -v
git add utils/large_text_multilingual_pack.py scripts/prepare_large_text_multilingual_pack.py utils/large_text_multilingual_runner.py tests/test_large_text_multilingual_pack.py
git commit -m "feat(pack): add fast multilingual workbook preparation"
```

Expected: 本地准备阶段不超过 5 秒；无临时项目专用脚本。

---

### Task 3: 固化可恢复的 API 初译执行器

**Files:**
- Create: `utils/large_text_multilingual_executor.py`
- Create: `scripts/run_large_text_multilingual_executor.py`
- Create: `tests/test_large_text_multilingual_executor.py`
- Modify: `utils/large_text_multilingual_runner.py`

**Interfaces:**
- Produces: `RelayClient.call_json(system, user) -> dict`。
- Produces: `translate_manifest(manifest_path, relay_config, workers=4) -> ExecutionSummary`。
- Artifacts: `translation_batches/batch_NNNN.json`、`initial_cache.jsonl`、`translation_metrics.json`。

- [ ] **Step 1: 写失败测试覆盖去重、重试、断点恢复和密钥隔离**

```python
def test_translate_manifest_calls_unique_rows_only_and_resumes():
    first = translate_manifest(manifest, config, client=fake_client)
    second = translate_manifest(manifest, config, client=failing_client)
    assert first.unique_api_rows == 145
    assert second.reused_batches == first.batch_count
    assert "api_key" not in manifest.read_text(encoding="utf-8")
```

- [ ] **Step 2: 确认 RED 后实现最小客户端和批次协议**

```python
@dataclass(frozen=True)
class ExecutionSummary:
    model: str
    source_rows: int
    unique_api_rows: int
    batch_count: int
    reused_batches: int
    wall_seconds: float

def partition_rows(rows, max_rows=14, char_budget=1200):
    """Keep output size bounded; never split one source row across batches."""
```

每批输出必须验证：key 集合完全一致、每个目标语言非空、无额外语言。失败策略为 3 次重试；持续失败时二分批次，不丢弃已成功 checkpoint。

- [ ] **Step 3: 每个阶段原子更新 manifest**

```python
def update_phase(manifest_path: Path, phase: str, status: str, payload: dict) -> None:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["phase_status"][phase] = status
    manifest.setdefault("phase_events", {})[phase] = payload
    temp = manifest_path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, manifest_path)

def start_phase(manifest_path: Path, phase: str) -> None:
    update_phase(manifest_path, phase, "running", {"started_at": datetime.now().isoformat()})

def complete_phase(manifest_path: Path, phase: str, metrics: dict) -> None:
    update_phase(manifest_path, phase, "done", {"finished_at": datetime.now().isoformat(), **metrics})

def fail_phase(manifest_path: Path, phase: str, error: str) -> None:
    update_phase(manifest_path, phase, "failed", {"finished_at": datetime.now().isoformat(), "error": error})
```

写 manifest 时使用临时文件加 `os.replace`，记录 `started_at`、`finished_at`、`wall_seconds`、`status` 和 artifact 路径。

- [ ] **Step 4: 验证 API smoke、翻译和恢复路径**

```powershell
python -m unittest tests.test_large_text_multilingual_executor tests.test_large_text_multilingual_runner -v
git add utils/large_text_multilingual_executor.py scripts/run_large_text_multilingual_executor.py utils/large_text_multilingual_runner.py tests/test_large_text_multilingual_executor.py
git commit -m "feat(executor): add resumable relay translation"
```

Expected: 267 行只请求 145 条唯一内容；中断后重跑只处理未完成批次；API key 不出现在任何 artifact。

---

### Task 4: 固化逐行审校、二次纠偏和真实修改统计

**Files:**
- Create: `utils/large_text_multilingual_proofread.py`
- Create: `tests/test_large_text_multilingual_proofread.py`
- Modify: `utils/large_text_multilingual_executor.py`
- Modify: `utils/large_text_multilingual_runner.py`

**Interfaces:**
- Produces: `review_cache(initial_cache, provider, workers) -> proofread_suggestions.jsonl`。
- Produces: `audit_suggestions(initial_cache, suggestions, provider) -> final_cache.jsonl`。
- Produces: `proofread_apply_summary.json`，字段固定为 `reviewed_rows,reviewed_unique_texts,reviewed_cells,suggested_cells,reverted_cells,revised_cells,final_changed_rows,final_changed_cells,changes_by_language`。

- [ ] **Step 1: 写失败测试覆盖逐语言 KEEP/FIX 和纠偏回退**

```python
def test_controller_reverts_narrower_term_overwrite():
    suggestion = {"status": "FIX", "after": "FAQ"}
    audit = {"decision": "REVERT"}
    result = apply_audit(initial="Help", suggestion=suggestion, audit=audit)
    assert result == "Help"
```

- [ ] **Step 2: 定义审校 owner，避免伪称 subagent**

```python
ProofreadOwner = Literal["api", "subagent_import"]

@dataclass(frozen=True)
class ProofreadConfig:
    mode: Literal["sampled", "full"]
    owner: ProofreadOwner
    workers: int = 4
```

当当前 CLI 无 subagent 调度能力时，manifest 必须写 `owner=api`；只有导入外部 subagent 建议文件时才能写 `owner=subagent_import`。

- [ ] **Step 3: 实现唯一文本审校并映射回全部源行**

去重签名固定为：`CN + context + term_hits + initial translations`。审校响应必须为十语言逐项 `KEEP/FIX`；二次纠偏响应必须为 `KEEP/REVERT/REVISE`。

- [ ] **Step 4: 产出 retro 可直接读取的标准摘要**

```powershell
python -m unittest tests.test_large_text_multilingual_proofread tests.test_large_text_multilingual_retro -v
git add utils/large_text_multilingual_proofread.py utils/large_text_multilingual_executor.py utils/large_text_multilingual_runner.py tests/test_large_text_multilingual_proofread.py
git commit -m "feat(proofread): standardize full line review and audit"
```

Expected: retro 能读取真实修改数，不再显示 `0 changed_cells`。

---

### Task 5: 精确 XLSX 写回和强化 dry-run/readback

**Files:**
- Create: `utils/xlsx_translation_writeback.py`
- Create: `tests/test_xlsx_translation_writeback.py`
- Modify: `utils/large_text_multilingual_gate.py`
- Modify: `tests/test_large_text_multilingual_gate.py`

**Interfaces:**
- Produces: `write_translation_cells(template, output, rows, language_columns) -> WritebackResult`。
- Produces: `verify_workbook_equivalence(template, output, target_cells) -> EquivalenceResult`。
- `apply-dry-run` 改为调用真实写回器，而不是只写入一个 `dry-run` 字符串。

- [ ] **Step 1: 写失败测试复现无效 style id 和非目标样式漂移**

```python
def test_writeback_preserves_non_target_xml_and_uses_valid_style_ids():
    result = write_translation_cells(template, output, rows, LANG_COLUMNS)
    load_workbook(output, read_only=False).close()
    assert result.invalid_style_refs == 0
    assert result.non_target_style_mismatches == 0
    assert result.source_alignment_mismatches == 0
```

- [ ] **Step 2: 实现 XLSX XML 定点写入**

```python
@dataclass(frozen=True)
class WritebackResult:
    written_cells: int
    invalid_style_refs: int
    non_target_style_mismatches: int
    source_alignment_mismatches: int

def default_style_id_for_missing_cell(sheet_xml: str, column: int) -> int:
    # Use explicit <col style> when present; otherwise use style 0.
    root = ElementTree.fromstring(sheet_xml)
    namespace = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    for item in root.findall("x:cols/x:col", namespace):
        if int(item.attrib["min"]) <= column <= int(item.attrib["max"]):
            return int(item.attrib.get("style", "0"))
    return 0
```

只修改目标 worksheet 的目标 `<c>` 节点；其他 ZIP 成员保持字节内容不变。新增单元格样式只能引用 `styles.xml/cellXfs` 中现有索引。

- [ ] **Step 3: 强化 apply-dry-run 和最终 readback**

门禁新增：普通模式 `load_workbook(read_only=False)`、最大 style id 合法、源 ID/CN hash 一致、非目标单元格样式一致、目标列完整、交付目录无过程文件。

- [ ] **Step 4: 回归两类源表并提交**

```powershell
python -m unittest tests.test_xlsx_translation_writeback tests.test_large_text_multilingual_gate -v
git add utils/xlsx_translation_writeback.py utils/large_text_multilingual_gate.py tests/test_xlsx_translation_writeback.py tests/test_large_text_multilingual_gate.py
git commit -m "fix(writeback): preserve xlsx structure and styles"
```

Expected: 不再出现“read-only gate 能过、普通打开失败”或样式索引重排问题。

---

### Task 6: 一键编排、准确 retro 和性能验收

**Files:**
- Modify: `utils/large_text_multilingual_runner.py`
- Modify: `utils/large_text_multilingual_retro.py`
- Modify: `scripts/run_large_text_multilingual_runner.py`
- Modify: `tests/test_large_text_multilingual_runner.py`
- Modify: `tests/test_large_text_multilingual_retro.py`
- Modify: `docs/workflow-execution-thread-handoff.md`

**Interfaces:**
- Produces CLI: `run --input a.xlsx --input b.xlsx --term-base terms.xlsx --target-langs EN,IDN,DE,FR,ES,PT,RU,IT,TR,TH --proofread-mode full --relay-config relay-api-config.json --delivery-dir delivery`。
- Final manifest status: `complete`；每个 critical phase 有真实 wall time。
- Final retro reads: manifest timing、`proofread_apply_summary.json`、cache-lint、20-language QA summary、readback-gate。

- [ ] **Step 1: 写失败的端到端 fake-relay 测试**

```python
def test_full_run_completes_manifest_and_retro(tmp_path):
    result = run_pipeline(config=fake_config, inputs=[a, b], target_langs=LANGS)
    assert result.manifest["status"] == "complete"
    assert result.retro["runner_timing"]["total_seconds"] > 0
    assert result.retro["proofread"]["changed_cells"] > 0
    assert result.readback["hard_blockers"] == 0
```

- [ ] **Step 2: 增加统一 `run` 编排**

固定 critical path：

```text
prepare-pack -> api-smoke -> api-translate -> incremental-cache-lint
-> full-review -> controller-audit -> final-cache-lint
-> apply-dry-run -> write-outputs -> language-quality-gate
-> readback-gate -> retro -> complete
```

阶段失败时 manifest 写 `failed` 和可恢复的 `next_phase`；重跑从首个未完成阶段继续。

- [ ] **Step 3: 语言专项 QA 只在最终成品执行一次**

对 2 个成品和 10 种语言并行扫描，输出一个 `language_quality_summary.json`；soft watch 单独计数，不混入 hard blocker。

- [ ] **Step 4: 修正 retro 输入和报告字段**

```python
assert metrics["runner_status"]["status"] == "complete"
assert metrics["proofread"]["changed_cells"] == proofread_summary["final_changed_cells"]
assert metrics["runner_timing"]["total_seconds"] == sum(phase["wall_seconds"] for phase in phases)
```

- [ ] **Step 5: 跑完整回归和性能验收**

```powershell
python -m unittest tests.test_large_text_multilingual_pack `
  tests.test_large_text_multilingual_executor `
  tests.test_large_text_multilingual_proofread `
  tests.test_xlsx_translation_writeback `
  tests.test_large_text_multilingual_runner `
  tests.test_large_text_multilingual_gate `
  tests.test_large_text_multilingual_retro -v
python -m unittest discover -s tests -p 'test_*.py'
python -m py_compile utils\large_text_multilingual_pack.py utils\large_text_multilingual_executor.py utils\large_text_multilingual_proofread.py utils\xlsx_translation_writeback.py
```

Expected:

- 相关测试与全量测试全部通过。
- 基准 fixture：prepare 小于 5 秒，fake-relay 全链路小于 30 秒。
- 真实 267 行 × 10 语言任务：目标 12-18 分钟，且模型阶段之外的本地处理小于 3 分钟。
- API 请求只覆盖 145 条唯一文本；重复源行不重复生成。
- 20/20 语言专项 QA 通过，cache-lint 与 readback-gate 均为 0 hard blocker。
- manifest 为 `complete`，retro 有真实阶段耗时和最终修改数。
- 交付目录只有 2 个成品工作簿和 `QA摘要.xlsx`。

- [ ] **Step 6: 更新执行文档并提交收口**

```powershell
git add utils scripts tests docs\workflow-execution-thread-handoff.md
git commit -m "feat(workflow): complete resumable multilingual pipeline"
git status --short --branch
```

文档必须明确：API 初译、API 审校和 subagent 导入是不同 owner；没有真实 subagent 响应时不得标记为 subagent 审校。

## Self-Review

- 覆盖上一批暴露的七类问题：慢抽取、临时执行器、QA 误报、报告误识别、样式写回、manifest 状态、retro 统计。
- 没有引入工作台或 studio 修改；同步仍由独立工作台线程处理。
- 每个任务都有独立失败测试、最小实现、验证命令和提交边界。
- 性能目标区分真实 API 时间与本地处理时间，不用总 latency 冒充 wall time。
- 未要求把客户工作簿、API key、项目术语或任务路径提交到公开仓库。
