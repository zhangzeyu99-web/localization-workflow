# 本地化工作流执行线程 Handoff

## 既有语言包诊断新增入口（本地维护源）

评估任务先按 `docs/INDEPENDENT_TRANSLATION_QUALITY_EVALUATION.md` 固定抽样范围，再运行 `scripts/run_quality_diagnostics.py`。它只校验实际覆盖、未决项及资源 ID 冲突，不输出整体质量分或发布通过。中英版本冲突不默认按英语自由重译。此本地入口未同步 Studio 时不得声称产品端已生效。

## 新线程必读顺序

1. 先读本文件，确认仓库边界、任务路由和交付规则。
2. 再读 `docs/WORKFLOW_OPTIMIZATION_LOG.md`，只采用当前分支已经包含的最新 `validated` 优化。
3. 命中专项任务后读取对应规范；大文本多语言任务读取 `docs/LARGE_TEXT_MULTILINGUAL_WORKFLOW_V2.md`。
4. 检查优化档案记录的 commit 是否存在于当前分支；不存在时不得仅凭旧线程描述使用新流程。

工作流优化不得只留在线程上下文。通过测试和真实任务验收后，必须追加优化档案，并同步本 handoff、`AGENTS.md` 和相关专项文档，使新线程可以仅凭仓库文件恢复执行规则。

本文档用于新 Codex 线程接手本地化工作流任务，目标是把“执行翻译/校对任务”和“持续优化 workflow 源仓库”固定在正确边界内，避免再次把工作流源代码、术语提取仓库和工作台仓库混用。

## 线程定位

- 线程职责：本地化翻译/校对任务执行，以及本仓库内 workflow 能力的持续迭代优化。
- 主工作目录：`D:\project\localization-workflow-project`
- 主远端：`https://github.com/zhangzeyu99-web/localization-workflow`
- 默认语言：简体中文。
- 默认工作方式：能执行就执行，不停留在泛泛计划；只有用户明确要求“先给计划”时才先输出计划。

## 仓库边界

| 类型 | 路径 | 远端 | 本线程职责 |
| --- | --- | --- | --- |
| 本地化 workflow 源仓库 | `D:\project\localization-workflow-project` | `https://github.com/zhangzeyu99-web/localization-workflow` | 默认工作目录，负责翻译校对、大文本、多语言、公告 DOCX、本地 QA |
| 术语提取源仓库 | `D:\codex\glossary-extraction-workflow` | `https://github.com/zhangzeyu99-web/glossary-extraction-workflow` | 仅在用户明确要求 brief/术语提取逻辑时进入 |
| 工作台/studio 仓库 | `D:\codex\localization-workflow-studio` | `https://github.com/zhangzeyu99-web/localization-workflow-studio` | 本线程禁止直接修改；只把需要工作台处理的事项报告给工作台线程 |

硬边界：

- 不直接修改 `D:\codex\localization-workflow-studio`。
- 不直接修改 `D:\codex\localization-workflow-studio\workflow\localization`，它只是本仓库的同步产物。
- 不修改 studio backend/frontend/工作台 UI。
- 如任务需要工作台产品更新、UI/backend 更新、studio 同步，只报告“超出本线程范围，需要交给工作台线程”，不要自己改。
- 如果需要改术语提取源逻辑，必须先确认用户要求的是 brief/术语提取，而不是翻译执行任务。

## 新任务启动自检

每个新任务先进入源仓库并确认状态：

```powershell
Set-Location D:\project\localization-workflow-project
git status --short --branch
git remote -v
git log -1 --date=iso --pretty=format:"%h %ad %s"
```

如果工作区不干净：

- 先区分用户/其他线程改动和本次任务需要改动。
- 不覆盖、不回滚、不重排无关改动。
- 如有冲突，先停下汇报冲突点。

## 用户常见任务给法

用户通常会用以下形式发任务：

- `跑新任务：<目录>`
- `只做英语`、`只要英语`
- `中印+8语言`、`英语泰语越南语印尼语`、`西葡`
- `术语表在目录里`、`源目录有术语表和 pb/brief`
- `做深校`、`逐句校对`、`逐行校对`、`完整校对`、`LQA`
- `回填飞书：<wiki/sheet 链接>`
- 直接附 `xlsx`、`docx`、`csv` 文件路径

收到任务后先简短汇报：

- 当前任务目录或文件。
- 识别到的任务类型。
- 目标语言。
- 找到的术语表、brief、历史交付证据。
- 准备使用的 workflow 入口。

除非用户明确要求先给计划，否则汇报后直接执行。

## 任务目录扫描规则

每次新任务必须重新扫描当前任务目录，不沿用旧任务流水。

扫描目标：

- 语言表、UI 表、系统提示表、邮件表、问卷表。
- 公告 `.docx` 或公告原文 `.txt`。
- 术语表、术语交付表、`project brief`、`pb`。
- 历史已验收交付文件，仅限当前任务目录或用户明确指定目录。

语言识别规则：

- 只处理用户要求或文件明确给到的语言。
- 如果术语表只给了部分语言，只使用已给语言。
- 缺失语言不要凭空补，除非任务明确要求“补译术语”或“翻译这些语言”。
- 未请求语言列不得写入或修改。

## 工作流入口选择

| 任务类型 | 默认入口 | 说明 |
| --- | --- | --- |
| 普通 `xlsx/csv` 语言表 | `workspace_runner.py`、`process_language.py`、`scripts/run_translation_harness.py`、`scripts/run_quality_harness.py` | 用于语言表、UI 表、系统提示表、邮件表、问卷表 |
| 目标列为空或近乎全空 | `scripts/run_translation_harness.py` | 先生成 workpack，主 agent 用 AI 模型能力填 response，再严格回填和 QA |
| 公告 DOCX | `scripts/run_announcement_docx_harness.py` | 固定走 `inspect/stage/prepare/import-ai/apply/deliver` 检索式中转表流程 |
| 大文本多语言包 V2 | `scripts/run_large_text_multilingual_runner.py run` | 一键执行只读分包、历史复用、唯一文本 API 翻译、缓存 QA、可选深校审计、精确写回、读回和 retro |
| 术语表翻译/校对 | 本仓库术语 QA 规则和质量 harness | 只保留主译，不写 `A / B`；正文允许按语境用自然变体 |
| 飞书回填 | `lark-cli` | 先解析真实 sheet token，写入后必须 readback |

## 翻译原则

- 默认使用 AI 模型能力，结合项目 brief、术语表、历史已验收交付翻译。
- 大批量任务可使用本仓库本地私有配置 `.local\api\relay-api-config.json`；该目录被 `.gitignore` 忽略，不得提交或在回复中泄露密钥内容。
- 除非用户明确要求，不使用 Google Translate、`googletrans`、`deep_translator` 或浏览器机翻做初译。
- 游戏 UI 要简洁、自然、适合手机竖屏；能短则短，但不能漏译。
- 术语表是约束输入，不做机械替换；必须按句子语境判断词性和自然表达。
- 术语表交付列只保留一个主译，不写 `A / B`。
- 术语表明确分类为技能名或地名时，执行 `docs/UI_NAME_TRANSLATION_STANDARD.md`：英语技能名两词优先，地名两个核心词优先；含义、自然度和唯一性高于长度，不对描述句或未分类短文本猜类型。
- 非英语任务若已有逐句校对英语，默认推荐 `--source-mode cn+en`：中文主源、英语参考；只有用户明确要求且英语完整可靠时才用 `--source-mode en`。详细规则见 `docs/BILINGUAL_SOURCE_REFERENCE_WORKFLOW.md`。
- 正文翻译遇到动词/名词变体时，由模型按语境处理，不新增补充变体列。

### 小批量历史译文检索

当前任务唯一中文不超过 200 条时，历史语言表只作为精确复用证据，不进入完整处理：

1. 先加载最新术语表和项目 brief，提取当前源文命中的术语及用户覆盖规则。
2. 使用当前任务中文原文建立精确查询，不生成模糊词或相似句查询。
3. 运行 `scripts/run_history_lookup.py`，以 `openpyxl read_only=True` 流式读取历史表，只返回中文列和本次请求语言列。
4. 精确完整句命中后按用户当前要求和最新术语复核；没有命中则停止历史查询，直接进入模型补译。
5. 禁止为小批量任务导入 Artifact Tool、渲染、翻译、校对或另存整份历史语言表；禁止把只读检索描述为“跑完整语言表”。

示例：

```powershell
python scripts/run_history_lookup.py `
  --input "<当前任务.xlsx>" `
  --history "<已验收历史.xlsx>" `
  --lang en `
  --lang fr `
  --output "<任务目录>\history_exact_lookup.json"
```

该入口不修改任何 workbook。完整历史审计仍只在用户明确要求，或任务进入大文本 V2 时执行。

## 基础 QA 必做

所有翻译/本地化任务默认必须完成基础 QA：

- 源行和 ID 对齐。
- 目标列和目标文件完整。
- 未请求语言列不被改。
- 占位符、变量、BBCode、HTML、换行保留。
- 数字、日期、时间、单位、范围保留。
- 目标文本无中文残留。
- 无非预期全角符号或非 ASCII 残留。
- 术语命中检查。
- 成品文件读回验证。

未完成基础 QA 不得声明交付完成。

## 深度逐句校对触发条件

独立质量评估、深校净效果和对白证据契约见 `INDEPENDENT_TRANSLATION_QUALITY_EVALUATION.md`。先提取需求表内已批准名称，再准备工作副本；auditor 接收主控提供的原译、源文与上下文，不以 reviewer 理由代替证据。

同批姓名提取入口为 `scripts/run_approved_name_snapshot.py`（显式行号、来源哈希、冲突阻断）；其 JSON 输出可直接作为大文本 `--term-base`。深校自动补充显式场景中的源文及当前目标话轮；对白接受修改必须附语义复述与主客体/语气检查。模型仍可能误判，`utils/semantic_regression.py` 的窄范围已知误译规则同时约束审计和 cache-lint；新规则必须带反例与正确对照。

默认不启用深度逐句校对；只有用户明确说以下表达时才启用：

- `深校`
- `逐句校对`
- `逐行校对`
- `完整校对`
- `全量审校`
- `LQA`

深校规则：

- 深校必须检查漏译、误译、术语漂移、游戏/UI 语境、自然度、数字/日期/单位/范围保留和同类句式一致性。
- 用户明确触发深校后，默认按目标语言分配 reviewer subagent；无需用户再次单独说明“使用 subagent”。
- subagent 只能输出审校建议，不直接写最终 workbook/docx，不得多个 agent 同时写同一交付文件。
- 主 agent 负责合并建议、二次纠偏、回填、复跑结构 QA，并记录建议数、纠偏回退数和最终保留修改数。
- 有实质修改时，最终汇报修改数量；必要时输出修改清单或 QA 备注表。
- 未做深校时，最终回复只能说完成基础 QA，不能声称“逐句校对完成”。

### 检索优先与唯一文本审校契约

无论任务最终走普通 translation harness 还是大文本 V2，翻译和深校都遵循以下顺序：

1. 先加载当前项目最新术语表和用户覆盖规则，再定向检索已验收历史交付；精确历史完整句可优先复用，但与当前用户要求或最新术语冲突时必须调整，精确术语优先于模型补译。
2. 历史译文和术语主译只是初始约束，深校时仍要检查语义、语境和自然度，不得因“已有译文”跳过审校。
3. 按 `源文 + 参考文本 + 必要语境` 生成唯一文本；重复行只审校一次，主线程按稳定键扩展回全部源行，并检查重复项最终译文一致。
4. reviewer subagent 按语言输出建议；主线程逐项接受、调整或回退，禁止把模型建议未经审计直接写入 workbook。
5. `QA摘要.xlsx` 至少记录源行数、唯一文本数、填入单元格数、各语言审校数、模型建议数、纠偏回退数、最终修改数、各语言修改数和 hard blocker 数。
6. 最终读回不仅检查非空，还要检查源列未改、品牌/数字/占位符保留、中文残留、重复项冲突和交付目录内容；可用 Excel 原生只读打开再做一次客户端可用性验证。

真实匿名任务验收：单 workbook、2 个目标语言、257 个源行、104 条唯一文本、514 个目标单元格；49 条由精确术语/历史复用，55 条由模型补译；逐语言审校提出 40 项建议，主控回退 3 项并补充 3 项纠偏，最终保留 40 项修改。空译文、中文残留、重复冲突和 hard blocker 均为 0，Excel 原生只读打开成功。

该验收只证明上述执行契约有效，不把任务目录中的临时脚本当作仓库公共入口，也不改变大文本 V2 的现有路由条件。

## 公告 DOCX 执行流程

对公告类 `.docx` 或公告原文任务，默认使用检索式中转表流程：

```powershell
python scripts\run_announcement_docx_harness.py inspect --input-dir <raw_task_dir>
python scripts\run_announcement_docx_harness.py stage --input-dir <raw_task_dir>
python scripts\run_announcement_docx_harness.py prepare --input-dir <task_dir>
python scripts\run_announcement_docx_harness.py import-ai --input-dir <task_dir> --response-dir <response_dir>
python scripts\run_announcement_docx_harness.py apply --input-dir <task_dir> --translation-workbook <task_dir>\_work\announcement_docx\announcement_translation_workbook.xlsx
python scripts\run_announcement_docx_harness.py deliver --input-dir <task_dir>
```

交付规则：

- 过程文件只放在 `<task_dir>\_work\announcement_docx\`。
- 最终交付目录只保留最终 DOCX 和 `QA摘要.xlsx`。
- 不逐个 DOCX 自由翻译后手工覆盖。

新版公告术语表规则：

1. `Glossary` 是词级主译；可选的 `SentenceTemplates` 是句子级术语适配，不是可直接复制的历史句库。
2. `official_exact` 优先级最高，先匹配 `AnnouncementCN`，再用 `OfficialCNTemplate` 中的 `<@数字>` 作为动态占位符匹配；覆盖范围内允许采用官方整句里的自然词形，不做词级机械误报。
3. `official_similar` 只提供当前句命中的官方表达和术语用法，模型必须按当前原文重写，不得带入示例中的无关语义、数字或玩法信息。
4. `workpack_<code>.jsonl` 的 `sentence_adaptations` 已按优先级排序；模型输出协议仍只允许 `para_id, translation`，不改变 import/apply/deliver 主链路。
5. `QA摘要.xlsx` 必须读回核对 `sentence_adaptation_hit_rows`、`official_exact_sentence_hits`、`official_similar_sentence_hits` 和 hard blocker；全半角括号、月份名称本地化及术语连字符差异按等价形式检查。
6. `import-ai` 失败时直接读取错误信息中的 `qa_report` 路径并按明细修复，不再临时编写诊断脚本；报告只留在 `_work`，不进入交付目录。

## 大文本多语言包 V2 执行流程

命中任一条件即使用 V2：

- 目标语言超过 4 个。
- 多 workbook 交付。
- 唯一文本超过 5,000 条。
- 用户明确要求全量逐句校对、深度校对或完整多语言审校。

执行前必须读取 `docs/LARGE_TEXT_MULTILINGUAL_WORKFLOW_V2.md`，并确认当前分支包含 `docs/WORKFLOW_OPTIMIZATION_LOG.md` 中对应的 `validated` 版本。

### 一键执行入口

```powershell
python scripts\run_large_text_multilingual_runner.py run `
  --input "<语言表.xlsx>" `
  --input "<UI表.xlsx>" `
  --term-base "<术语表.xlsx>" `
  --history-dir "<历史已验收交付目录>" `
  --target-langs "EN,IDN,DE,FR,ES,PT,RU,IT,TR,TH" `
  --task-dir "<任务目录>" `
  --relay-config "<relay-api-config.json>" `
  --proofread-mode full
```

`--input` 和 `--history-dir` 可以重复传入。未明确要求逐句/深度校对时使用 `--proofread-mode basic`；明确要求时使用 `full`，不得把基础 QA 说成逐句审校。

只做只读抽取和规模预检、不调用 API：

```powershell
python scripts\run_large_text_multilingual_runner.py prepare-pack `
  --input "<语言表.xlsx>" `
  --input "<UI表.xlsx>" `
  --term-base "<术语表.xlsx>" `
  --target-langs "EN,IDN,DE,FR,ES,PT,RU,IT,TR,TH" `
  --work-dir "<任务目录>\_work\large_text_multilingual"
```

### V2 阶段契约

1. **只读分包**：顺序读取源 workbook，核对目标列为空，生成稳定 `file + sheet + ID + row` 键。
2. **复用与去重**：先复用当前项目历史已验收交付和精确术语，再按“源文、语境、术语约束”去重；API 只处理剩余唯一文本。
3. **API 初译**：只使用配置的 OpenAI-compatible 中转 API 或当前模型能力，不使用 Google/外部机翻；先小批 smoke，再按行数和字符预算并发。JSON 或含 3 个以上技术标签的中文行由程序拆成纯文本槽，模型不接触结构，程序原位重建；失败批次重试后自动拆分。
4. **断点续跑**：翻译 checkpoint 按模型、供应端、目标语言和 prompt 版本隔离；审校 checkpoint 按 reviewer/auditor 身份隔离，并按 `review_key + lang` 复用已完成单元。调整深校批大小后只补缺失项，不整包重译或重审。
5. **缓存级 QA**：写 workbook 前先仅对含中文残留的失败单元格做确定性修复（该行命中术语、章节序号），再执行 `cache-lint`；空译文、中文残留、未请求语言、占位符/标签/数字丢失和强术语遗漏的 hard blocker 必须为 0。已通过单元格不得重译。
6. **深校审计**：只有用户明确触发时执行。`sampled` 审全部高风险唯一文本和稳定抽取的 10% 低风险唯一文本，`full` 审全部唯一文本；API/subagent 只输出 `KEEP/FIX` 建议，不能直接写 workbook；结构化行只审纯文本槽，由主控按原结构回填；主控二次审计后生成最终缓存，并再次执行 `cache-lint`。
7. **精确写回**：`apply-dry-run` 通过后，只修改目标单元格；写回必须同时核对文件、sheet、ID/key、行号和源文，保留原 worksheet 命名空间和样式。
8. **交付读回**：普通模式打开成品、检查样式索引，再把每个目标单元格与最终缓存逐格比对；不能只检查“非空”。最后生成 retro 指标。

### 文件与安全边界

- 过程文件统一放在 `<task_dir>\_work\large_text_multilingual\`，包括 manifest、JSONL、checkpoint、门禁结果和 retro。
- API key 只在请求时从 relay 配置读取，不得写入 manifest、缓存、日志、QA 摘要或 Git。
- 最终交付目录只保留成品 workbook 和 `QA摘要.xlsx`；输入文件不得使用 `QA摘要.xlsx` / `qa_summary.xlsx` 保留名。
- 中断后优先使用相同 `task-dir`、输入、语言和 relay 配置重新执行，以复用 checkpoint；不得删除 `_work` 后声称是续跑。
- API 失败后若由有效缓存补齐继续完成，必须用 runner `reconcile` 核验 final cache-lint、深校摘要、apply-dry-run、交付目录和 readback，再收口 manifest 并生成 recovery retro；不得手工把失败状态改成完成。
- 终端保持安静输出，只汇报 source rows、unique items、API batches、修改量、hard/warn、文件数、总耗时和交付路径。

### 完成汇报

最终必须区分基础结构 QA 与深度逐句校对是否完成，并报告：源行数、唯一文本数、目标语言、模型/API 批次数、checkpoint 复用量、深校建议数、审计回退数、最终修改数、hard blocker、交付文件数和路径。

## 飞书回填规则

- 飞书相关任务默认使用 `lark-cli`。
- 个人可见文档/表格优先使用用户身份：`--as user`。
- 不默认重新登录，先复用 `C:\Users\Administrator\.lark-cli\`。
- 先解析 wiki/sheet 链接到真实 token。
- 长表先整表导出到本地 `_source` 留档，记录 revision、下载时间和 SHA256；翻译、深校和 QA 全部在本地完成，禁止边处理边回填。
- 本地 hard blocker 为 0 后重新核对在线 revision；发生漂移时停止写入并先比较，不覆盖他人改动。
- 只写指定 sheet、行和列，按块记录写入进度与 revision；写完在线读取源列和目标列，与最终缓存逐格比对。
- 写入成功和 readback 成功是两个独立验收点。
- 用户要求“发我消息”时，飞书消息发送也要单独确认。

## 输出和交付规则

- 最终交付目录只放最终 `xlsx/docx/csv` 和 `QA摘要`。
- 不把 `workpack`、`manifest`、`response`、`jsonl`、`log`、临时脚本放进交付目录。
- 最终回复只说交付路径、处理语言、行数/文件数、QA 结果、剩余风险。
- 如果没跑某项测试或校对，必须明说。

## 代码优化规则

当任务暴露流程问题时：

- 先记录问题和复现证据。
- 优先做最小化 workflow 源仓库改动。
- 能机器检查的失误优先写成测试或 gate。
- 不能机器检查的写进 AGENTS、文档或清单。
- 代码改动后跑相关测试；涉及核心流程时跑 `python -m pytest -q`。
- commit/push 前必须确认 `git status`，不能混入任务产物。

同步到工作台的边界：

- 本线程只改源仓库。
- 如用户要求同步工作台，先在源仓库完成测试和提交，再报告需要由工作台线程执行 studio 同步。
- 不在本线程直接修改 studio 目录。

## 新线程启动提示词

将下面内容复制给新线程即可：

```text
你是“本地化工作流执行线程”，只负责本地化翻译/校对任务执行和 workflow 源仓库持续优化。

固定工作流源仓库：
D:\project\localization-workflow-project
远端：
https://github.com/zhangzeyu99-web/localization-workflow

禁止范围：
- 不改 D:\codex\localization-workflow-studio
- 不改 studio backend/frontend/工作台 UI
- 不直接改 studio\workflow\localization，它只是同步产物
- 如需工作台更新，只汇报需要交给工作台线程

每次新任务启动：
1. Set-Location D:\project\localization-workflow-project
2. git status --short --branch
3. 扫描当前任务目录或文件，识别语言表、UI 表、系统提示表、邮件表、问卷、公告 DOCX、术语表、project brief/pb。
4. 识别用户要求的目标语言；只处理用户要求或明确给到的语言，不凭空增加语言。
5. 找到术语表/brief/历史交付后，选择合适入口执行。

常见入口：
- 普通 xlsx/csv：workspace_runner.py / process_language.py / scripts/run_translation_harness.py / scripts/run_quality_harness.py
- 公告 DOCX：scripts/run_announcement_docx_harness.py
- 大文本多语言包：scripts/run_large_text_multilingual_runner.py + run_large_text_multilingual_gate.py + run_large_text_multilingual_retro.py
- 飞书回填：lark-cli，写入后必须 readback

翻译原则：
- 使用 AI 模型能力结合项目 brief、术语表、历史已验收交付翻译。
- 不使用 Google Translate、googletrans、deep_translator 或浏览器机翻做初译，除非用户明确要求。
- 游戏 UI 要简洁、自然、适合手机竖屏。
- 术语表只保留主译，正文按语境处理词性和自然变体。

QA 规则：
- 所有任务默认做基础 QA：源行/ID 对齐、目标列完整、未请求语言列不改、占位符/变量/标签/换行/数字/日期/范围保留、无中文残留、术语命中检查、成品读回。
- 只有用户明确说“深校/逐句/逐行/完整校对/LQA”时，才做深度逐句校对。
- 未做深校时不能声称“逐句校对完成”。
- 深校有修改时汇报修改数量，必要时输出修改清单。

输出规则：
- 最终交付目录只放最终文件和 QA摘要。
- 不混入 manifest、workpack、response、jsonl、log、临时脚本。
- 最终回复只汇报交付路径、处理语言、行数/文件数、QA 结果、剩余风险。

开始任何任务时，先简短汇报：当前任务目录/文件、任务类型、目标语言、找到的术语表/brief、准备使用的 workflow 入口。然后直接执行，除非用户明确要求先给计划。
```
