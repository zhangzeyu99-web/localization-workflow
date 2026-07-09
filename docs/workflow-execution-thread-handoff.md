# 本地化工作流执行线程 Handoff

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
| 大文本多语言包 | `scripts/run_large_text_multilingual_runner.py`、`scripts/run_large_text_multilingual_gate.py`、`scripts/run_large_text_multilingual_retro.py` | 先 manifest，再 `cache-lint`、`apply-dry-run`、`readback-gate`，最后 retro |
| 术语表翻译/校对 | 本仓库术语 QA 规则和质量 harness | 只保留主译，不写 `A / B`；正文允许按语境用自然变体 |
| 飞书回填 | `lark-cli` | 先解析真实 sheet token，写入后必须 readback |

## 翻译原则

- 默认使用 AI 模型能力，结合项目 brief、术语表、历史已验收交付翻译。
- 大批量任务可使用本仓库本地私有配置 `.local\api\relay-api-config.json`；该目录被 `.gitignore` 忽略，不得提交或在回复中泄露密钥内容。
- 除非用户明确要求，不使用 Google Translate、`googletrans`、`deep_translator` 或浏览器机翻做初译。
- 游戏 UI 要简洁、自然、适合手机竖屏；能短则短，但不能漏译。
- 术语表是约束输入，不做机械替换；必须按句子语境判断词性和自然表达。
- 术语表交付列只保留一个主译，不写 `A / B`。
- 正文翻译遇到动词/名词变体时，由模型按语境处理，不新增补充变体列。

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

默认不启用深度逐句校对；只有用户明确说以下表达时才启用：

- `深校`
- `逐句校对`
- `逐行校对`
- `完整校对`
- `全量审校`
- `LQA`

深校规则：

- 深校必须检查漏译、误译、术语漂移、游戏/UI 语境、自然度、数字/日期/单位/范围保留和同类句式一致性。
- 如启用 subagent，subagent 只能输出审校建议，不直接写最终 workbook/docx。
- 主 agent 负责合并建议、二次纠偏、回填、复跑结构 QA。
- 有实质修改时，最终汇报修改数量；必要时输出修改清单或 QA 备注表。
- 未做深校时，最终回复只能说完成基础 QA，不能声称“逐句校对完成”。

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

## 大文本多语言包执行流程

触发条件：

- 唯一文本超过 5,000 条。
- 目标语言超过 4 个。
- 用户要求全量逐句校对。
- 多 workbook 交付。

默认流程：

```powershell
python scripts\run_large_text_multilingual_runner.py prepare <args>
python scripts\run_large_text_multilingual_gate.py preflight <args>
python scripts\run_large_text_multilingual_gate.py cache-lint <args>
python scripts\run_large_text_multilingual_gate.py apply-dry-run <args>
python scripts\run_large_text_multilingual_gate.py readback-gate <args>
python scripts\run_large_text_multilingual_retro.py <args>
```

执行要求：

- 先创建 runner manifest，再按 manifest 的 critical path 执行。
- `cache-lint` 和 `apply-dry-run` 通过后才写回大文件。
- 交付后必须跑 `readback-gate`。
- 大 JSON、issue 明细、模型建议写入日志或报告文件，终端只汇报 hard/warn、修改量、文件数、耗时和交付路径。

## 飞书回填规则

- 飞书相关任务默认使用 `lark-cli`。
- 个人可见文档/表格优先使用用户身份：`--as user`。
- 不默认重新登录，先复用 `C:\Users\Administrator\.lark-cli\`。
- 先解析 wiki/sheet 链接到真实 token。
- 写入指定 sheet 和指定列。
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
