# 本地化工作流与 Harness 上下文

本文用于把旧线程中可复用的本地化工作流压缩成新会话可读取的上下文包。只保留通用流程、项目 harness、质量门禁和交付规则；不记录历史任务、客户文件、具体交付路径或单项目私有内容。

## 默认执行原则

- 本仓库是游戏本地化处理主工作流，优先使用 `workspace_runner.py`、`cli.py`、`process_language.py`，不退回旧 GUI 人工复制粘贴流。
- 用户给出语言表或项目目录时，默认跑到可交付闭环，不停在机审或待确认。
- 默认由主 agent 直接执行完整链路；只有用户明确要求时才启用 subagent，并且只按语言或项目拆分，不按同一语言表批次拆分。
- 术语表同目录优先；有术语表就自动使用，没有术语表就按无术语模式继续。
- 质量优先于吞吐量。首跑建议小批次，`batch-size=80~100`。

## 主工作流

适用于目标语言列已有译文、需要质检收口的语言表。

1. 发现输入：识别语言表、目标语言列、术语表、项目目录结构。
2. 预检：确认源列/目标列、语言代码、术语表列、可处理 sheet。
3. 机审：检查变量、占位符、BBCode/HTML 标签、换行、中文残留、术语、句式一致性、UI 文本、短文本长度。
4. 自动修复：只修高置信问题，不破坏变量、标签、换行和结构。
5. AI 或人工收口：只针对仍需判断的行做语义修订。
6. 严格回填：按 ID、manifest 和指纹回填，禁止靠行顺序猜。
7. 复检：反复清掉 hard error。
8. 最终门禁：运行 `quality_harness` 扫最终 workbook。
9. 导出：根目录保留 `_最终版.xlsx`，QA 文件进入 `qa_<lang>/`。

## 严格 AI 审核协议

`prepare / merge` 链路由 `utils/ai_checker.py` 管控。

- `prepare` 生成 `ai_review/batch_N.txt`、`batch_N.json`、`batch_N_response.txt`。
- `batch_N.json` 保存 ID、输入指纹和批次 manifest；`merge` 只认 manifest，不从 prompt 文本反解析 ID。
- 回复文件必须逐条覆盖该批所有 ID，只允许：
  - `ID | KEEP`
  - `ID | FIX | corrected translation`
- 禁止缺行、重复 ID、额外 ID、解释、标题、总结、代码块。
- 任一批次 ID 覆盖、顺序、输入指纹不一致，必须拒绝 merge。
- 主批次外可以生成 `batch_recheck_N.*` 做术语二次复查。

## 多语言全量翻译 Harness

适用于目标列为空、近乎全空，或大量中文回填的情况。当前支持 `en`、`th`、`vi`、`idn`。入口是 `scripts/run_translation_harness.py`，实现是 `utils/translation_harness.py`。

准备工作包：

```powershell
python scripts\run_translation_harness.py --input <language.xlsx> --term-base <terms.xlsx> --lang en --output-dir <work_dir> --style-hint-file <translation_prompt.txt>
```

输出：

- `translation_workpack.jsonl`：逐行翻译输入，包含 ID、源文、占位符、标签、换行形态、术语命中、文本类型、UI 长度信息和项目风格提示。
- `translation_manifest.json`：输入指纹、ID 列表、语言、目标列状态和协议。
- `translation_response.jsonl`：主 agent 写译文的响应文件。

响应可用 JSONL：

```json
{"id": 1001, "translation": "Claim Reward"}
```

也可用简写：

```text
1001 | Claim Reward
```

应用译文：

```powershell
python scripts\run_translation_harness.py --input <language.xlsx> --term-base <terms.xlsx> --lang en --output-dir <work_dir> --response <work_dir>\translation_response.jsonl --run-qa
```

硬规则：

- v1 支持 `en`、`th`、`vi`、`idn`；只处理任务目录/术语表实际给出的语言，不凭空补未提供语言。
- response 必须覆盖全部 ID，不能漏、重、乱序或额外 ID。
- 输入漂移、占位符漂移、标签漂移、换行形态漂移必须拒绝写回。
- `.translation_cache/<lang>.jsonl` 只在同项目目录内使用，并按项目提示词隔离；最终交付默认清理缓存。

## 项目定制 Harness

项目定制 harness 是通用 `quality_harness` 之外的项目级增强层，用于沉淀某个游戏的术语、风格、结构和历史高频问题。公开仓库只保留通用模板，不提交任何私有项目内容。

项目开始前先建立私有资料包：

- `project_profile.md`
- `project_profile.json` 或 `project_profile.yaml`
- `translation_prompt.txt`
- 术语表、合格参考、截图或 UI 上下文

公开模板：

- `templates/project_profile_template.md`
- `templates/project_profile_template.json`
- `templates/project_profile_template.yaml`
- `templates/translation_prompt_template.txt`

规则：

- 如果当前项目存在 profile，项目 harness 必须读取并执行，不能忽略。
- profile/prompt 只在单项目私有环境中使用，不跨项目复用，不提交公开仓库。
- 项目 harness 先跑通用 `quality_harness`，再跑项目定制 gate。
- 项目规则只拦截明确、可复现、可解释的问题；每新增规则都要补坏例和好例。

## 通用质量门禁

入口：

```powershell
python scripts\run_quality_harness.py fixtures\quality_regression.json --workbook <final.xlsx>
```

只跑回归集：

```powershell
python scripts\run_quality_harness.py fixtures\quality_regression.json
```

核心 hard gate：

- 变量缺失、变量多余、变量顺序错误。
- BBCode/HTML/颜色标签缺失、错配、未闭合。
- 换行形态不一致。
- 中文残留。
- 强术语缺失、部分命中、大小写错误；无分类术语表中的明显泛词（如 `获得`、`需要`、`成功`）降为 soft warning。
- 人名/角色名近似但不一致。
- 连续编号词条混译。
- UI 短文案硬超长。
- 不可读缩写、截断词、内部 token、井号代码泄漏。
- Title Case 滥用、句首小写异常、全角符号残留、标点污染。

软提示默认不阻断：

- `short_text_length_watch`
- `term_soft_missing`
- `term_soft_partial_hit`
- `term_soft_capitalization`

`rows_scanned=0` 视为失败，不能把空扫描当 QA 通过。

## 交付目录规则

- 最终交付目录根部只保留源表、术语表、`_最终版.xlsx`。
- `result_<lang>.xlsx` 和 `report_<lang>.xlsx` 放入 `qa_<lang>/`。
- 中间 workpack、批次文件、临时术语、cache 默认不作为交付物。
- 最终回复只汇报最终文件路径、处理范围、通用 QA 结果、项目 harness 结果和剩余 soft warning。

## 公开仓库边界

允许提交：

- 通用代码、通用测试、通用 fixture、通用文档、空模板。

禁止提交：

- 客户 workbook、截图、参考样本、本地交付路径、单项目 harness、项目专用术语规则、可识别客户或项目名称的配置。

## 关键文件

- `AGENTS.md`：仓库级执行规则。
- `docs/translation-harness.md`：多语言全量翻译 harness 文档。
- `docs/quality-harness.md`：质量回归 harness 文档。
- `docs/project-custom-harness.md`：项目定制 harness 流程。
- `scripts/run_translation_harness.py`：翻译 workpack/回填入口。
- `scripts/run_quality_harness.py`：质量门禁入口。
- `utils/translation_harness.py`：翻译 harness 实现。
- `utils/quality_harness.py`：质量扫描与 fixture runner。
- `utils/readability_checker.py`：可读性、坏缩写、截断词等检查。
- `fixtures/quality_regression.json`：回归用例。
- `templates/project_profile_template.*`：项目资料模板。
- `templates/translation_prompt_template.txt`：项目提示词模板。

## 验证命令

```powershell
python scripts\run_quality_harness.py fixtures\quality_regression.json
python -m unittest tests.test_quality_harness tests.test_translation_harness tests.test_readability_checker tests.test_excel_reader
```

## 公告 DOCX 检索式翻译 Harness

适用场景：同一任务目录内存在公告 `.docx` 和对应 `*_announcement_terms_*.xlsx` 术语表。该流程是通用工作流，不绑定具体项目名。

固定链路：

```text
docx 段落抽取 -> 术语表检索命中 -> 中转翻译表 -> 二次翻译填表 -> QA -> 回填同格式 docx -> 干净交付目录
```

入口：

```powershell
python scripts\run_announcement_docx_harness.py inspect --input-dir <raw_task_dir>
python scripts\run_announcement_docx_harness.py stage --input-dir <raw_task_dir>
python scripts\run_announcement_docx_harness.py prepare --input-dir <task_dir>
python scripts\run_announcement_docx_harness.py import-ai --input-dir <task_dir> --response-dir <response_dir>
python scripts\run_announcement_docx_harness.py apply --input-dir <task_dir> --translation-workbook <task_dir>\_work\announcement_docx\announcement_translation_workbook.xlsx
python scripts\run_announcement_docx_harness.py deliver --input-dir <task_dir>
```

中转表固定基础列：`source_file, para_id, para_index, style, CN, protected_tokens, term_hits_json, sentence_adaptations_json`。旧版已准备的中转表没有 `sentence_adaptations_json` 时仍可读取。目标语言列默认从匹配术语交付表中识别，只生成术语表实际提供的目标列；例如 `ID/CN/EN/FR` 只生成 EN/FR，`ID/CN/KR` 只生成 KR/ko。只有显式传 `--lang` 时才覆盖该推断。

规则：

- 术语表按列位置识别语言；第 1 列 `ID` 是词条 ID，第 11 列 `ID` 才是印尼语，内部码为 `idn`。
- 术语表优先读取 `Glossary`；若存在 `SentenceTemplates`，必须包含 `Priority, MatchType, ID, AnnouncementCN, OfficialCNTemplate` 和 `Glossary` 中全部目标语言列。`MatchType` 只允许 `official_exact`、`official_similar`，缺列、空目标译文或非法类型直接中止 prepare。
- `official_exact` 同时支持 `AnnouncementCN` 规范化精确片段匹配和 `OfficialCNTemplate` 的 `<@数字>` 动态占位符匹配；`official_similar` 只按 `AnnouncementCN` 线索检索。命中结果按优先级、精确优先、线索长度排序后写入 workpack。
- 模型使用顺序固定为：精确句子适配 > 词级术语主译 > 相似句子参考 > 自然翻译。精确适配覆盖的词允许使用官方整句中的自然词形；相似适配不得复制与当前原文无关的历史内容。
- 不为术语交付表未提供的目标语种生成 workpack、ai_response 或最终 DOCX，避免凭空扩展任务范围。
- 原始目录里的中文命名 `术语译文交付表`、`.txt` 公告原文和参考语言包先由 `inspect`/`stage` 标准化；`inspect` 只读表头，不扫描大型语言包全表。
- `prepare` 只生成 `_work/announcement_docx/announcement_translation_workbook.xlsx`、manifest、workpack 和日志类过程文件。
- 二次翻译必须由 Codex/ChatGPT/明确的大模型通道读取 `workpack_<code>.jsonl` 后写 `ai_response_<code>.jsonl`；禁止用 Google Translate、`deep_translator`、浏览器翻译、在线机翻聚合器或其他外部机器翻译服务产出初译。
- `ai_response_<code>.jsonl` 固定为 JSONL，每行只允许 `para_id` 和 `translation` 两个字段，行数、顺序和 `para_id` 必须与对应 workpack 完全一致。
- `import-ai` 负责把 AI response 回填到中转表目标语言列；回填前会校验漏行、重行、额外行、乱序、中文残留、受保护 token、括号形态和术语目标命中。全半角括号、Unicode 等价形式和术语中的空格/连字符差异按等价形式比较；中文月份数字可本地化为月份名称。
- `import-ai` 的译文 QA 失败时会写 `_work/announcement_docx/ai_response_qa_<code>.json`，包含逐项类型、原文、译文和位置；同语言重新导入前会删除旧报告，避免把历史问题当作当前问题。
- 不直接手工改 `source_file`、`para_id`、`CN`、`protected_tokens`、`term_hits_json` 和 `sentence_adaptations_json`。
- `apply` 必须先通过 QA，拦截空译文、中文残留、受保护数字/日期/时间范围/括号 token 漂移、强命中术语缺失、缺段落、重复段落、额外段落和源 DOCX hash 漂移。
- `QA摘要.xlsx` 记录词级命中行、句子级适配命中行、`official_exact` 命中数和 `official_similar` 命中数，便于复盘检索覆盖率。
- `deliver` 只复制通过 QA 的最终 DOCX 和 `QA摘要.xlsx`，不把 `_work/`、jsonl、manifest 或日志放进交付目录。
- v1 只替换段落文本并保留段落样式；表格、图片、文本框等复杂结构不重建，只记录 unsupported warning。

推荐 Codex 批处理命令：

```powershell
Get-Content <prompt_file> | "C:\Users\Administrator\AppData\Local\Programs\OpenAI\CodexDesktop\resources\codex.exe" -a never exec --ephemeral --sandbox workspace-write -C <repo_root> -
```

要求：使用 `--ephemeral`，避免把每个语言批处理会话持久化成长期任务流水；批处理日志和 response 只作为过程文件，不进入交付目录。
