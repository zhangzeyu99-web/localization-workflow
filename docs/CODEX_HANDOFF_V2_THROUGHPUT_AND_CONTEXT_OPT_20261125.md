# Codex 交接文档：V2 大文本多语吞吐、无损上下文减负与分层二审优化（2026-11-25）

> **交接对象**：Codex CLI / 后续维护与执行线程
> **目标仓库**：`D:\project\localization-workflow-project`，发布基线 `bbc6a26`
> **记录范围**：下方参数已按 2026-11-26 发布审查修正。2026-11-25 的工作区和 API 数据是开发实验记录，不作为当前生产并发授权。
> **质量底线**：默认仍为全量独立二审。分层策略会减少低风险独立审计覆盖，只能显式选用，不能用于要求全量二审的批次。
>
> **分线程审查修正（2026-11-26）**：下表为历史实验记录。传输保留术语的 `required`、`enforcement` 和与目标同值的 `reference_en`；含字面 `[fN]` 的请求不生成片段引用，译文新增内部引用会被拦截。动作、否定、长文、公告、对白及重译行的 `KEEP` 也进入独立二审；自动接受不计入 `audited_cells`，逐格结果分别记为 `independent` 或 `auto_keep_low_risk`。

---

## 1. 四批优化落地总览

| 批次 | 目标 | 核心改动 | 质量与兼容性保障 |
| --- | --- | --- | --- |
| **第 1 批** | 解除碎包、放开并发上限、清理 3 类高频假硬阻断 | 1. 一审先按 `_language_review_row` 裁成单语再分包，一/二审 `max_chars` 由 `24000` 提至 `48000`，默认 `--proofread-batch-size` 由 `30` 提至 `50`。<br>2. `MAX_API_CONCURRENCY` 保持 `5`（默认 `4`），沿用既有 AIMD 遇 429/连错减半退避机制。<br>3. 泛称 NPC 多语言豁免（`GENERIC_ROLE_TARGETS` + `GENERIC_ROLE_SOURCES`）；德语人名标准 `-s` 所有格与 `s/ß/x/z` 撇号放行；`scan_cache_surface` 支持 `context.text_type` 及前一行续接标点后的合法跨行续句小写豁免。 | 具名角色严格保持 `'person'`；英语裸 `-s`、德语 `Maxs` 与错拼严格拦截；独立单句与句号后句首小写严格硬阻断。 |
| **第 1.5 批** | **100% 无损上下文减负**（全链路 `translate`/`review`/`blind`/`audit` 生效） | 1. `_prune_wire_payload`：仅在 HTTP 传输副本上裁除空字段、默认值、镜像 `translation_source`（`source_mode=="cn"` 且与 `cn` 相同）、内部键（`owner`/`cache_key`/`enforcement`/`required`）及单语重复 `reference_en`。<br>2. `_compact_shared_context` 共享阈值由 `256` 降至 `64` 字符（保持 `$context_ref` 100% 可逆）。<br>3. `_compact_context_fragments`：按自然句界（`｜`/`|`/`\n`/`；`/`。`）提取批内出现 `>=3` 次、长度 `>=24` 的高频重复上下文整句到 `shared_context_fragments`，含 `[fN]` 字面冲突保护与 `>=120` 字节净节省门槛。<br>4. 紧凑 JSON 序列化（`separators=(",",":")`），并与 `_partition_requests` 估算对齐。 | **绝不修改调用方原始 `user_payload`**（`RelayRuntime` 断点键 100% 稳定）；对 `glossary_exact` 行显式保留 `glossary_seed_locked: false`；逐字逆向还原 100% 等价。 |
| **第 2 批** | 风险分层二审（避免纯低风险 `KEEP` 重复全量审计） | 新增 `--audit-policy {all,risk_tiered}`（默认 `all` 100% 向下兼容），透传至 `run_pipeline`、`resume_pipeline`、`run_deep_proofread` 与 `run_config.json` 绑定检查。<br>在 `risk_tiered` 下：全部 11 类高风险格（`FIX`、`unresolved_issues`、语义/名称检查、`glossary_exact`、`en`/`cn+en` 双源、`risk_flags`、`term_hits`、`protected_tokens`、结构化分槽、对话轮次、数字/占位/标签）**100% 强制进独立二审**；纯低风险 `KEEP` 默认按 **10% 确定性哈希抽检**进二审，其余自动 `ACCEPT` 并标记 `audit_tier="auto_keep_low_risk"`。 | 默认 `all` 不改变既有行为与契约；`proofread_apply_summary.json` 与 manifest 完整披露 `audit_policy`、`audit_api_cells`、`audit_auto_accepted_low_risk_cells`、`audit_sampled_low_risk_cells`、`audit_tier_breakdown`。 |
| **第 3–4 批** | 翻译批上限对齐、盲读去重、可观测性闭环与文档回归收口 | 1. `translate_manifest` 默认 `max_batch_chars` 由 `24000` 提至 `48000`。<br>2. `_read_target_texts` 按 `(lang, text)` 批内去重 + 跨批文本级缓存复用（同时兼容读取历史旧键）。<br>3. `RelayRuntime.progress()` 输出 `stage_requests` 与 `context_compression`（`wire_chars_before`/`wire_chars_after`/`wire_chars_saved`/`saved_ratio`）。<br>4. 补全匿名正反测试、正式 `quality_regression.json` 用例、优化档案及本交接文档。 | 盲读本身不依赖源文或行号，按 `(lang, text)` 去重零质量损失，并按各原 `review_key` 精准回填。 |
| **第 5 批（追加 1–5 项全落地 + 真机 API 实测）** | 压缩模型输出 Token、深化邻句去重、Keep-Alive + 流式按语种流水线、显式中文修改重译分流、真机端到端试跑 | 1. **精简 `reason` 输出**：修复 `review` prompt 残句；一审 `KEEP` 统一返回 `'ok'`、`FIX` 理由 `<=20` 词；二审 `reason <=15` 词、`semantic_check` 精炼，直砍慢速 Completion Token。<br>2. **邻句标签与高频重复邻句去重**：`_CONTEXT_FRAGMENT_SPLIT` 升级为 `(?<=[；。：！？\n])|(?=[｜|])|(?<=[｜|])`，片段门槛放宽至 `len>=12`、`count>=3`，按净节省取前 `40` 条，自动把 `同场景±1/±2行` 固定标签与重复邻句纳入无损 `shared_context_fragments`。<br>3A. **线程本地 HTTP/HTTPS Keep-Alive**：`_post_json_bytes` 直连场景按 `(scheme, host, port)` 复用 `http.client` 长连接、断连清理连接并由中转运行时按预算重试；检测到代理环境变量或单测 monkeypatch `urllib.request.urlopen` 时自动无感回退原路径。<br>3B. **按语种流式流水线**：多语且 `workers>1` 时，共享有界线程池在某语种一审刚跑完的瞬间立即投递该语种二审，不再等最慢语种全部一审结束，并记录 `streaming_language_pipeline: true`。<br>4. **显式重译分流 `--retranslate-marked`**：`prepare_pack` 识别修改状态列（`中文修改`/`中文大改`/`新增` 等）及 `text_type` 显式标记为 `retranslate_marked=True`；`review` 模式仅在显式开启 `--retranslate-marked` 时清空标记行错位旧译走干净重译，再合并进深校；未标记行仍严格禁止空单元格。<br>5. **真实中转 API 端到端验收**：构造 24 行匿名 EN+DE 测试表完成真机实测，`hard_blockers: 0`、0 标记泄露。 | 全项均有匿名单元测试 + 真实中转 API 端到端实测验证；未开启 `--retranslate-marked` 时严格保持既有“review 模式禁止隐式重译”红线。 |

---

## 2. 精确改动文件清单（务必与工作区既有未提交改动区分！）

> **重要提醒**：在本次优化开始前，`D:\project\localization-workflow-project` 工作区已存在 20+ 个其他未提交文件（例如 `docs/NATIVE_REVIEW_BASELINE_WORKFLOW.md`、`tests/test_native_baseline_quality.py`、`process_language.py`、`utils/quantity_guard.py`、`utils/semantic_constraints.py`、`utils/language_config.py` 等）。**请勿将无关既有改动误回滚，也不要在未确认前混入同一 commit。**

### 2.1 本轮新增文件（4 个）
- `tests/test_batch1_throughput_and_false_positives.py` — 第 1 批 + 第 1.5 批（并发上限保留、单语分包、泛称 NPC、德语所有格、跨行续句、嵌套标题类型、无损裁剪、片段共享与端到端 HTTP 传输测试）
- `tests/test_batch2_batch3_tiered_audit_and_observability.py` — 第 2 批 + 第 3 批（11 类高风险强制二审、`risk_tiered` 抽检与摘要、CLI 透传、盲读 `(lang, text)` 去重、`RelayRuntime` 压缩观测与 `max_batch_chars=48000` 测试）
- `tests/test_batch4_followup_optimizations.py` — 第 5 批追加 1–4 项（精简 `reason` 提示、邻句标签与高频重复邻句 100% 可逆去重、真实本地 HTTP/1.1 Keep-Alive 同端口复用与断连预算、多语流式流水线快语种抢跑二审、`--retranslate-marked` 正反边界测试）
- `docs/CODEX_HANDOFF_V2_THROUGHPUT_AND_CONTEXT_OPT_20261125.md` — 本交接文档

### 2.2 本轮修改文件（14 个）
- `utils/relay_runtime.py` — 共享硬上限 5、`stage_requests`、`note_wire_compression` 与 `context_compression`
- `utils/large_text_multilingual_executor.py` — `_prune_wire_payload`、`_compact_shared_context`（64 字符阈值）、`_compact_context_fragments`（含邻句标签与重复邻句 `len>=12` / `top 40`）、`_prepare_wire_payload`、紧凑 JSON、`_partition_requests` 对齐、`_read_target_texts` 语义去重、`translate_manifest(max_batch_chars=48000)`、精简 `review`/`audit` reason 输出约束、线程本地 HTTP/HTTPS Keep-Alive `_post_json_bytes`
- `utils/large_text_multilingual_proofread.py` — 先单语投影再分包、一/二审 `max_chars=48000`、`_requires_independent_audit`、`audit_policy` / `low_risk_audit_sample_rate` 与分层统计、多语共享池按语种流式流水线（`streaming_language_pipeline`）
- `utils/large_text_multilingual_pack.py` — 检测显式修改状态列（`修改状态`/`变更状态`/`更新状态`/`revision_status` 等）与 `text_type` 中显式标记，写入行级 `retranslate_marked` 布尔标记
- `utils/large_text_multilingual_pipeline.py` — worker 上限改为 `MAX_API_CONCURRENCY`、`audit_policy` 透传与 `run_config.json` 漂移检查、显式 `retranslate_marked` 重译分流合并逻辑及 `phase_metrics.api_translate.retranslated_marked_rows` 统计
- `utils/large_text_multilingual_runner.py` — `--api-concurrency` 保持 `1..5`、默认 `--proofread-batch-size 50`、新增 `--audit-policy` 与 `--retranslate-marked`
- `utils/quality_harness_terms.py` — 扩充 `GENERIC_ROLE_TARGETS`、新增 `GENERIC_ROLE_SOURCES`、`term_enforcement_kind` 全语种泛称判定
- `utils/quality_harness_rules.py` — `_check_person_name_terms` / `_contains_expected_person_name` 增加 `lang` 参数支持德语 `-s` 所有格与弯撇号
- `utils/large_text_multilingual_gate.py` — 向 `_check_person_name_terms` 传入 `lang=lang.lower()`
- `utils/quality_harness.py` — 向 `_check_person_name_terms` 传入 `lang=lang`；`scan_cache_surface` 兼容 `context.text_type` 与合法跨行续句小写豁免
- `utils/readability_checker.py` — 兼容带说明文字的中文标题 `text_type` 识别
- `tests/test_relay_runtime.py` — 验证所有角色共享上限，实测 `limit=5`
- `fixtures/quality_regression.json` — 新增 2 条匿名通用标题 `text_type` 正反用例（总计 222 例）
- `docs/WORKFLOW_OPTIMIZATION_LOG.md` — 追加 `2026-11-25` 优化档案条目

*(注：`utils/relay_runtime.py`、`utils/large_text_multilingual_pipeline.py`、`utils/large_text_multilingual_runner.py`、`utils/readability_checker.py`、`tests/test_relay_runtime.py`、`fixtures/quality_regression.json`、`docs/WORKFLOW_OPTIMIZATION_LOG.md` 在本轮之前已有既有未提交改动，如需独立拆分 commit，请用 `git add -p` 按 hunk 拣选本轮改动。)*

---

## 3. CLI 参数变更与推荐调用方式

### 新增/调整的 `large_text_multilingual_runner.py run` 参数
- `--api-concurrency`：范围保持 `1..5`（默认 `4`，遇 429 自动 AIMD 减半退避）
- `--proofread-batch-size`：默认值由 `30` 提升至 `50`
- `--audit-policy`：`all`（默认，全量独立二审）或 `risk_tiered`（高风险格强制二审，低风险 `KEEP` 默认抽检 10%）。
- `--retranslate-marked`：默认关闭，仅在 `--task-mode review` 下生效。识别明确的修改状态、校对状态和备注（如单独的“修改”）及显式文本类型标记；“无需重译”等否定优先，普通备注不触发。重译行只用新版 CN，保留源表旧 EN，合并后继续深校。未标记空译仍硬拦截。
- 葡语表头为 `PT` 时传 `PT`。如项目要求欧洲葡语，在 UTF-8 风格文件中明确 `欧洲葡语（pt-PT）` 并传 `--style-hint-file`；不要用地区标签代替原表列名。

> **质量底线**：默认仍为全量独立二审。分层策略会减少低风险独立审计覆盖，只能显式选用，不能用于要求全量二审的批次。
```powershell
# 1) 全量严格二审 + 高吞吐（适合高风险剧情/首版发布）
py -3 -X utf8 -m utils.large_text_multilingual_runner run `
  --input "<源表.xlsx>" `
  --term-base "<术语表.xlsx>" `
  --target-langs "EN,DE,FR,ES,PT" `
  --style-hint-file "<项目风格-欧洲葡语.txt>" `
  --task-dir "<任务目录>" `
  --relay-config "<relay.json>" `
  --proofread-mode full `
  --audit-policy all `
  --api-concurrency 5 `
  --workers 5 `
  --proofread-workers 5

# 2) 大批量高吞吐 + 风险分层二审 + 显式重译中文大改行（所有 FIX/术语/数字/对话/语义格仍 100% 二审）
py -3 -X utf8 -m utils.large_text_multilingual_runner run `
  --input "<源表.xlsx>" `
  --term-base "<术语表.xlsx>" `
  --target-langs "EN,DE,FR,ES,PT" `
  --style-hint-file "<项目风格-欧洲葡语.txt>" `
  --task-dir "<任务目录>" `
  --relay-config "<relay.json>" `
  --task-mode review `
  --proofread-mode full `
  --audit-policy risk_tiered `
  --retranslate-marked `
  --api-concurrency 5 `
  --workers 5 `
  --proofread-workers 5
```

---

## 4. 已完成的验收证据与基准数据

1. **全仓单元测试**：
   ```powershell
   py -3 -X utf8 -m pytest -q --basetemp "D:\project\localization-workflow-project\.pytest_tmp_run"
   ```
   结果：**758 passed, 0 failed, 2 skipped, 192 subtests passed**（含新增 `test_batch4_followup_optimizations.py` 5 项全过，临时目录已清理）。
2. **正式质量回归 CLI**：
   ```powershell
   py -3 -X utf8 scripts/run_quality_harness.py fixtures/quality_regression.json --json
   ```
   结果：**`passed: true`，222/222 全过，`failures: []`**。
3. **代码卫生**：`git diff --check` 退出码 `0`。
4. **离线只读基准回放**（557 条唯一待审行 × 5 语 `EN/DE/FR/ES/PT-PT`，未调 API、未改交付物）：
   - 一审请求总批数：**`130` → `60`（`-53.8%`）**，`shared_contexts` 与 `shared_context_fragments` 命中率 **60/60 批**（平均每批提取 `23.3` 个高频上下文/邻句片段）；
   - 5 语用户消息体总传输字符：原始未压缩 JSON **`5,665,132`** → 优化前 **`2,357,947`** → 第 1.5 批 **`1,339,442`** → 第 5 批邻句去重后 **`1,194,622`**（**较原始未压缩 JSON `-78.9%`，较旧传输层 `-49.3%`**），逐字可逆展开校验 100% 通过；
   - `scan_cache_surface` 复检：**`passed: True`, `hard_blockers: 0`**。
5. **真实中转 API 端到端小表试跑验收（24 行匿名 EN+DE 多语表，2026-11-25 历史实验；其 6 并发不在发布版范围内）**：
   - 运行模式：`--task-mode review --proofread-mode full --audit-policy risk_tiered --retranslate-marked --api-concurrency 6 --workers 6 --proofread-workers 6 --proofread-batch-size 50`（使用本地中转配置，结果全部脱敏，未泄露任何凭据或客户数据）；
   - 覆盖场景：连续 12 行剧情对白（带重复规则与上下文）、德语人名 `-s` 与 `s'` 所有格、泛称 NPC 称呼、含 `{0}`/数字/否定词反转故障的高风险任务句、带中文括号说明的建筑标题、4 条低风险短按钮、以及 2 条显式标记“中文大改/中文修改”的错位旧译/空译行；
   - **吞吐与压缩实测**：
     - 全流程端到端耗时 **`93.45s`**，总请求仅 **`5` 次**（`translate: 1`, `review: 2`, `audit: 2`），**`retries: 0`, `failed_requests: 0`**；
     - Token 实耗：`prompt_tokens=18,475`、`completion_tokens=6,589`、`total_tokens=25,064`；
     - 即使在 24 行小表上，`context_compression` 仍将线上传输字符从 `65,060` 压至 `30,055`（**`-53.8%`**）；
     - `streaming_language_pipeline: true` 成功激活；
   - **输出精简实测（改动 1）**：
     - 一审 42 条 `KEEP` 中 **42/42（100%）返回 `'ok'`（平均 `2.0` 字符）**；
     - 一审 6 条 `FIX` 理由平均仅 **`5.8` 词**（最长 `8` 词），二审 API 理由最长仅 **`9` 词**；
   - **质量与零退化验收**：
     - 成品交付表与 `readback_gate.json`：**`hard_blockers: 0`**，成品全表 **`[fN]` / `$context_ref` / `shared_context_fragments` 泄露数 = `0`**；
     - 故意植入的否定语义反转故障（`不要丢弃星辉石` 错译为 `Discard...` / `Wirf ... weg`）被 EN/DE 双语 **100% 精准检出并修正**，同时额外自动修复 3 处自然度/精确度瑕疵（`bridgehead` 军事词歧义、`广场边` 遗漏、术语统一）；
     - 德语所有格（`Ryans Rucksack`、`Marcus' Notizen`）与中文说明标题全部 **0 误报**；
     - `--retranslate-marked` 精准命中 `retranslated_marked_rows: 2, kept_existing_rows: 22`，2 条标记行干净重译并命中术语表；
     - `risk_tiered` 分层审计分布清晰透明：`auto_keep_low_risk=11`, `low_risk_sample=2`, `numeric_or_markup=2`, `protected_tokens=2`, `reviewer_fix=6`, `term_hits=25`。

---

## 5. 给 Codex 的后续接手建议

1. **独立代码审查（Code Review）**：重点核查 `utils/large_text_multilingual_executor.py` 中 `_prepare_wire_payload` / `_compact_context_fragments` / `_post_json_bytes`（Keep-Alive 代理回退与断连重连）/ `_read_target_texts` 的边界场景，以及 `utils/large_text_multilingual_proofread.py` 中多语流式线程池和 `_requires_independent_audit` 的异常收口。
2. **大批量真实生产表对比观察**：在授权范围内使用 4 并发（硬上限 5），比较实际总耗时、Token 消耗和审校覆盖；需要全量独立二审时保持 `--audit-policy all`。
3. **发布边界**：发布验收只看独立暂存快照；无关的母语基线、数值门禁及项目交付变更留原工作区。
4. **Studio 同步红线**：本线程与本交接均**未修改** `D:\codex\localization-workflow-studio`；若后续需同步到工作台，必须等本源仓库干净提交后，交由工作台线程按独立同步流程执行并另行验收。
