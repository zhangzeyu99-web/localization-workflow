# AGENTS.md

## 新任务必读与优化落档

- 每个新线程进入本仓库后必须先读 `docs/workflow-execution-thread-handoff.md` 和 `docs/WORKFLOW_OPTIMIZATION_LOG.md`，不得只依赖线程 handoff、聊天上下文或旧提示词。
- 命中专项任务时再读对应规范；大文本多语言任务必须额外读 `docs/LARGE_TEXT_MULTILINGUAL_WORKFLOW_V2.md`。
- 工作流优化只有在回归测试和真实任务/等价端到端证据都通过后，才允许标记为有效并追加到 `docs/WORKFLOW_OPTIMIZATION_LOG.md`。
- 每条有效优化必须记录触发问题、实施改动、验收证据、生效范围、回滚边界、剩余风险和代码版本；不得只在当前线程口头总结。
- 优化改变默认入口、任务路由、质量门禁或 subagent/API 边界时，必须同步更新 `AGENTS.md`、`docs/workflow-execution-thread-handoff.md` 和对应专项文档，确保其他线程按仓库文件即可执行。
- 新线程执行任务前必须检查优化档案最新 `validated` 条目是否已进入当前分支；未进入时不得假定新流程可用。

## 大文本多语言 V2

- 独立质量评估或深校复盘执行 `docs/INDEPENDENT_TRANSLATION_QUALITY_EVALUATION.md`：先提取同批已批准角色名基线；对白提供话轮和人物证据；二次审计输入必须含主控补齐的源文、原译及上下文。修改数和结构 QA 不能代替语言质量评估。
- 同表批准姓名在清空工作副本前用 `scripts/run_approved_name_snapshot.py` 的显式姓名行生成私有 JSON；后续 pack/cache-lint 共用该 `--term-base`。不得从普通对白猜姓名定义。对白深校按显式场景补齐当前目标话轮，审计接受须有语义证据；已知语义回归由确定性门禁兜底，不能因模型 ACCEPT 放行。

- 大文本、多 workbook 或 5 个以上目标语言优先使用 `scripts/run_large_text_multilingual_runner.py run`，详细契约见 `docs/LARGE_TEXT_MULTILINGUAL_WORKFLOW_V2.md`。
- 先按历史交付和精确术语复用，再对唯一文本调用中转 API；禁止把 API 返回直接写进 workbook。
- API 批次必须落 checkpoint 并支持续跑；manifest 和日志不得保存 API key。
- 深校默认按单一目标语言分批，翻译与深校分别使用 `--batch-size/--workers` 和 `--proofread-batch-size/--proofread-workers`；深校 checkpoint 按 `review_key + lang` 复用，改变批大小不得重审已完成单元。
- reviewer 返回 `KEEP` 但省略 `suggested` 时，使用当前译文补齐审校记录；`FIX` 的 `suggested` 为空仍是 hard failure，不得当作通过。
- 同一任务目录同时只允许一个深校主进程；命中 `proofread.lock` 时必须停止重复启动，不得让多个进程共享 checkpoint。
- 深校建议必须经过主控二次审计，最终缓存 `cache-lint` hard blocker 为 0 后才允许精确写回。
- `sampled` 深校只审全部高风险唯一文本和稳定抽取的 10% 低风险唯一文本；`full` 才是全部唯一文本，不得把两种模式混同。
- API 阶段失败后若通过缓存补齐继续完成，必须运行 runner 的 `reconcile`，且只在 final cache-lint、深校摘要、apply-dry-run、交付目录和 readback 全部验证后把 manifest 收口为 `complete`。
- JSON 或含 3 个以上技术标签的中文结构化长文本必须由程序拆出纯文本槽；翻译、reviewer 和 auditor 均不得接收或返回整段 JSON、`<@n>` 或标签结构，最终由程序按原路径和标签序列回填。
- 结构 QA 已通过的译文不得因其他行失败而重译。初译后仅允许本地修复命中术语残留和章节序号残留；其余中文残留继续作为 hard blocker，不得用整条模型重译掩盖。
- 写回必须核对源文件、sheet、行号和源文，并在交付后普通打开、校验样式索引、执行 `readback-gate`。
- 飞书长表任务必须先整表导出到本地任务目录，记录在线 revision 和源文件哈希后再翻译/深校；本地 hard blocker 为 0 后核对 revision，最后分块回填并在线读回，不得边翻译边写飞书。

## 语言

- 始终使用简体中文回复。

## 本仓库定位

- 本目录是游戏本地化处理的主工作流根目录。
- 优先使用 `workspace_runner.py`、`cli.py`、`process_language.py`。
- 旧版 Tkinter GUI（`gui.py`）已于 2026-07-09 移除；不要重建 GUI 或人工复制粘贴流程。
- 新线程接手执行任务时，先读 `docs/workflow-execution-thread-handoff.md`，其中记录仓库边界、用户常见任务给法、任务路由、QA/深校/飞书回填和交付规则。

## 下游同步关系（Localization Workflow Studio）

- 本仓库是本地化工作流（翻译校对/大文本多语言/公告 DOCX/本地 QA）的**单一维护源**；`D:\codex\localization-workflow-studio\workflow\localization` 是它的只读同步产物，禁止在那边直接改。
- 本仓库改动提交后，到 studio 仓库根执行：`python scripts/sync_workflow_sources.py localization`（自动镜像 + 哈希读回校验）。
- 同步后必须在 studio 跑 `python -m pytest workflow/localization/tests -q` 和 `python -m pytest backend/tests -q`：`process_language.py`、`scripts/run_quality_harness.py`、`scripts/run_translation_harness.py` 是 studio 工作台 backend 的 subprocess 运行时依赖（各文件 docstring 有 `Boundary:` 标注），backend 测试不全绿不得声明同步完成。
- studio backend 的 `app/workflow/large_text.py` 是从本仓库 `utils/large_text_multilingual_gate.py` port 的受控复制；改 gate 规则后要求 studio 侧 `backend/tests/test_large_text_productization.py` parity 测试通过。
- 同步范围只含代码与测试（`cli.py`、`process_language.py`、`workspace_runner.py`、`scripts/`、`utils/`、`tests/`、`templates/`、`fixtures/`、`requirements.txt`、`CHANGELOG.md`）；`docs/`、`tools/`、根目录中文文档、样例文件是本仓库私有资产，不同步。

## 默认执行方式

- 当用户给出语言表文件或项目目录时，不要停在机审阶段。
- 除非用户明确要求只跑部分步骤，否则默认执行完整闭环：
  1. 预检
  2. 机审
  3. 自动修复
  4. AI 审核或人工收口
  5. 严格回填
  6. 复检
  7. 导出最终版

## Subagent 规则

- 基础 QA 默认由主 agent 直接执行，不为了并行而启用 `subagent`。
- 用户明确说“深校、逐句校对、逐行校对、完整校对、全量审校、LQA”时，视为已授权按目标语言启用 reviewer subagent，无需再次要求“使用 subagent”。
- 主 agent 负责总控、`prepare / merge`、最终回填和最终导出。
- 不要为了并行而拆分同一语言表的严格批次映射。
- 不允许多个 agent 同时写同一个输出文件。
- reviewer subagent 只输出审校建议，不直接写 workbook/docx；主 agent 必须逐项二次纠偏后再回填。
- 剧情、对白、角色语音或配音文本必须同时执行 `docs/DIALOGUE_TRANSLATION_REQUIREMENTS.md`；先按文本类型分流，人工修订只作为风格证据，不能跳过语义、技术结构和清洁度复检。
- subagent 只允许按“语言”或“项目”拆分，不允许按同一语言表的批次拆分。
- 深校结果必须记录建议数、纠偏回退数、最终保留修改数和各语言修改数。

## 稳定性优先

- 首跑优先稳定性，不优先吞吐量。
- 默认使用小批次，建议 `batch-size=80~100`。
- `prepare` 和 `merge` 之间不要替换、重排或改写输入语言表。
- 如果发现输入漂移、批次错配、词条漏回、响应格式错误，优先保证链路正确，不要强行合并。
- 如果需要批量翻译，必须持续输出进度，不要长时间无反馈。

## 输入假设

- 当前主支持场景是：中文原文 -> 目标语言列。
- 非英语任务需要参考已校对英语时，按 `docs/BILINGUAL_SOURCE_REFERENCE_WORKFLOW.md` 显式选择 `--source-mode cn+en`；中文仍是语义主源，英语只辅助术语、专名、语气和歧义判断。
- 只有用户明确要求按英语翻译、且英语逐行完整可靠时才使用 `--source-mode en`；该模式仍用中文回查漏译、玩法条件、数字、占位符和术语。
- `cn+en` 允许个别英语缺失并逐行回退中文；`en` 要求英语覆盖率 100%，否则 prepare 必须中止。目标语言为英语时只允许 `cn`。
- 不允许自动检测到英语列后静默切换语义主源；源模式必须进入 workpack/manifest、AI 审校指纹和缓存键。
- 当前支持的目标语言以 `utils/language_config.py` 的 `SUPPORTED_TRANSLATION_LANGUAGES` 为准：
  `en`、`ko`、`ja`、`th`、`vi`、`idn`、`fr`、`de`、`ru`、`it`、`es`、`pt`、`tr`、`ar`
- 该清单覆盖历史交付需求过的全部语言（土拨鼠 8 语、明日2 全语种、勇者西葡、公告阿语等）；新增语言时只改 `language_config.py` 的注册表（SUPPORTED/NAMES/ALIASES/FILE_HINTS/OUTPUT_SUFFIX/TARGET_HEADERS 六处齐全），列检测、术语查找、工作区自动发现会自动生效。
- 如果同目录或工作区里存在术语表，默认一起使用。
- 如果没有术语表，则按无术语模式继续处理，不要因此停住。
- 最终交付判定以 `scripts/run_quality_harness.py fixtures\quality_regression.json --workbook <最终版.xlsx>` 为准；`process_language.py` 负责机审和自动修复，但不能作为唯一放行依据。

## 目标列状态规则

- 如果目标语言列已有有效文本，直接进入主工作流收口，不要重建翻译管线。
- 如果目标语言列为空，或接近全空，则允许直接启动备用翻译管线。
- 如果目标语言列全空，而用户又希望更稳的处理，可先把中文原文整列复制到目标语言列，再进入主工作流；这通常比“纯空列从零生成”更稳。

## 备用翻译管线

- 备用翻译管线只在“目标语言列为空或近乎全空”时使用。
- 只处理当前任务目录，不扫描整个工作区，不做工作区级翻译记忆库扫描，除非用户明确要求。
- 输入物料只使用当前目录中的：
  - 语言表
  - 术语表
  - 当前任务相关输出目录
- 翻译前必须保护：
  - 变量
  - 占位符
  - BBCode / 标签
  - 换行
  - 术语表里的术语
- 批量翻译时必须给每一行加唯一行号 token，再按 token 回填，避免批次错位、串行和漏行。
- 不允许用仅靠行顺序猜测的拼接方式回填。
- 备用翻译管线的输出必须立刻回写到目标语言列，再进入主工作流继续做机审和收口。

## 小批量历史译文定向检索

- 当前任务唯一中文不超过 200 条时，先加载同目录最新术语表并提取命中项，再决定是否检索历史已验收语言表。
- 历史检索只允许使用 `scripts/run_history_lookup.py` 做中文原文精确匹配；只读取中文列和用户要求的目标语言列，使用 `read_only=True`，不导入、渲染、翻译、校对或另存整份历史语言表。
- 标准命令：`python scripts/run_history_lookup.py --input <当前任务.xlsx> --history <已验收历史.xlsx> --lang en --output <lookup.json>`；多语言重复传 `--lang`，多个历史文件重复传 `--history`。
- 精确完整句命中后可以复用，但必须再检查用户当前要求和最新术语表；发生冲突时以“用户当前要求 > 项目 profile/prompt > 最新术语表 > 历史译文”为准，不得原样继承旧口径。
- 没有精确命中时立即结束历史查询并进入模型翻译，不自动扩大为相似句、模糊匹配或整本历史表处理。
- 只有用户明确要求全量历史审计，或任务达到大文本 V2 路由条件时，才允许进入相应完整历史处理流程；不得因目录里存在完整语言表就自动整本加载。

## 英语全量翻译 Harness

- 当英语目标列为空、近乎全空，或大面积中文回填时，优先使用 `scripts/run_translation_harness.py`，不要手工拼 Excel。
- 准备阶段运行：`python scripts\run_translation_harness.py --input <excel_file> --term-base <terms.xlsx> --lang en --output-dir <output_dir> --style-hint "<项目级短提示词>"`。
- `--style-hint` 用于项目风格约束，例如“面向美国移动端用户；SLG；简短地道表达”；也可用 `--style-hint-file <txt>` 从 UTF-8 文本读取。
- 主 agent 读取 `translation_workpack.jsonl`，只写 `translation_response.jsonl`，每行格式为 `{"id": 1001, "translation": "Claim Reward"}`。
- 翻译非英语语言时可加 `--source-mode cn+en` 或 `--source-mode en`；workpack 会提供 `translation_source`、`reference_en` 和逐行参考状态。
- 应用阶段运行：`python scripts\run_translation_harness.py --input <excel_file> --term-base <terms.xlsx> --lang en --output-dir <output_dir> --response <output_dir>\translation_response.jsonl --run-qa`。
- 该 harness 不调用 API、不自动操作 ChatGPT 网页、不启用 subagent；模型翻译由主 agent 直接完成。
- 回填严格按 ID 和 manifest 校验，漏 ID、重复 ID、额外 ID、乱序、输入漂移、占位符/标签/换行漂移都必须拒绝写回。
- 同项目翻译记忆只允许写入输入目录下的 `.translation_cache\en.jsonl`，不要扫描其他项目缓存；提示词不同的缓存不能混用。

## 质量要求

- 变量、占位符、BBCode、换行必须严格保留。
- 不要为了缩短文案破坏占位符、标签、变量顺序或结构。
- 短文本长度规则默认启用：
  - 中文原文可见长度 `<= 10` 先入池
  - `mode=hard`：紧凑 UI / 按钮 / 标签
  - `mode=soft`：普通短文本软提示
  - `mode=exempt`：编号专名、复杂富文本等豁免
- 英语 UI hard 预算：`min(32, max(10, 中文可见长度 * 2 + 14))`。
- 印尼语 UI hard 预算：`min(34, max(12, 中文可见长度 * 2 + 15))`。
- 自然可懂优先，长度第二。
- 不允许为了长度生成不可读缩写或内部代码式文案，例如 `PERR`、`DTT`、`IDNE`、`IJA`、`CL##1##2`、`TPRM#P`。
- 不允许截断英文单词或删除元音来压长度，例如 `rewa`、`obta`、`coll imme`、`tmrw`。
- 不允许把职业、资源、装备、技能名、商店名、搜索结果、消息/邮件、容量、积分、内容/敏感词提示、摆放提示等常规词压成片段，例如 `Ener Scie`、`Stru Expe`、`Smel Expe`、`Pts impr esse`、`No sear resu`、`Shen Armo`、`Orde Thun`、`Fast Trac Bull`、`Fina ATK SPD`、`Repl This mess expi`、`No unre mess`、`Hara swip spam mess`、`Troo capa`、`Conf spen ##1 diam`、`Figh modi leve ##1`、`Offline Rwds`、`Glor Cont`、`Cont cann empt`、`Your cont ##1`、`Loca cann plac`、`Wear equi cann rese`、`No wear equi`、`Stro equi Pack`。
- 不允许保留不该上线的中文拼音残留，例如 `Chef Yifang`；应改为自然本地化姓名，例如 `Chef Yvonne`。
- 允许稳定游戏缩写：`HP`、`ATK`、`DEF`、`DMG`、`DPS`、`PVP`、`PVE`、`VIP`、`FPS`、`SFX`、`UI`、`Lv`。
- 如果长度预算和可读性冲突，以自然可懂为准，宁可略长，不用坏缩写。
- 英文错误、状态、提示类文案默认使用 sentence case，例如 `Too many roles`、`System error`；不要无理由写成 `Too Many Roles`、`System Error`。
- Title Case 只用于合理范围：专名、功能名、标题、商店项、术语表明确要求的名称。
- 术语表 `分类/category/type` 明确为技能名时，按移动端 UI 专名处理：英语优先不超过 2 个可读词 / 24 字符；明确为地名、地点名、地图名、区域名或场景名时，英语优先不超过 2 个核心词 / 28 字符，冠词和介词不计核心词；明确为建筑名或设施名时，英语正式名优先不超过 2 个核心词 / 18 字符，产品支持独立地图标签时目标不超过 14 字符。详细规则见 `docs/UI_NAME_TRANSLATION_STANDARD.md`。
- 技能名/地名/建筑名压缩只由术语表显式分类触发，不根据中文长度猜测；`技能描述`、`技能效果`、`地图说明`、`地点描述`、`建筑说明`、`建筑效果` 不得套用。
- 建筑名用于地图或主城 UI 时，优先保留功能中心词和关键区分词；`Lv.`、`I-V` 等等级/阶级信息在产品支持时拆成 UI 徽标。正式名与地图短标签分开管理，禁止用坏缩写或机械截词压长度。
- 两词/字符预算是软约束：核心含义、自然度、既有专名和名称唯一性优先；禁止机械截断、坏缩写或把不同中文专名压成同一译名。
- `skill_name_word_count_watch`、`location_name_compactness_watch`、`building_name_compactness_watch`、`name_translation_collision_watch` 必须进入 AI/人工复核，但不作为无条件自动改写或 hard blocker。
- 颜色标签必须翻译前后保持一致，`[color=#...]` 和 `<color=#...>` 的数量、开闭和色值都不能漂移。
- 不允许非问句中把分隔符污染成 `?`，例如源文 `重装·普攻I` 不能译成 `Tank ? Basic Attack I`；真实问号键提示如 `Press ? for help` 不按分隔符污染处理。
- 人名/角色名一致性是所有项目的硬门槛：术语表中 `分类` 含 `人名`、`角色`、`person`、`character`、`name` 的条目，正文命中中文名时必须使用术语表英文名，不能把 `Aria` 写成 `Arya`、`Leon` 写成 `Lyon` 这类近似名。
- 术语表默认是强约束；只有 `分类/category/type` 显式含 `soft`、`generic`、`common`、`参考`、`泛词`、`通用词` 时才作为软提示，不阻断最终交付。
- 引号或结构化名称段不能只因“包含主译”就判定通过；主译周围若残留额外修饰词，必须作为 `term_superstring_drift_candidate` 送入 AI 语境复核，不做机械删除。
- 连续编号词条必须临时沉淀批内术语：同一中文词根反复出现为 `词根-数字` 时，目标译文前缀、大小写和连字符格式必须一致，例如 `消灭怪物-74` 到 `消灭怪物-238` 不能混用 `Kill Monsters` / `Destroy monsters` / `Kill monsters`。
- 新增任何质量规则时，必须同步补 `fixtures/quality_regression.json`：坏例要被拦住，好例不能被误杀。

## 公开仓库边界

- 公开仓库只提交通用代码、通用测试、通用 fixture、通用文档和不含客户信息的模板。
- 不要提交客户 workbook、截图、参考表、本地交付路径、单项目 harness、项目专用术语规则或可识别客户/项目名称的文件。
- 单项目规则可以留在本地私有文件或私有配置中，但必须通过 `.git/info/exclude` 或仓库外目录防止误提交。

## 最终版交付管线

- 最终交付不是只跑机审，而是必须按下面顺序执行：
  1. 识别当前目录中的语言表和术语表
  2. 判断目标语言列是否为空
  3. 若为空则先走备用翻译管线；若不为空则直接进入主工作流
  4. 跑预检、机审、自动修复
  5. 优先清掉硬错误：
     - `term_missing`
     - `term_partial_hit`
     - `term_capitalization`
     - `chinese_residue`
     - `variable_missing`
     - `ui_length_overflow`
     - `opaque_abbreviation`
     - `clipped_word`
     - `title_case_overuse`
     - 其他结构性错误
  6. 反复复检，直到不再有硬错误
  7. 跑质量回归 harness：`python scripts\run_quality_harness.py fixtures\quality_regression.json --workbook <最终版.xlsx> --lang <语言>`；用户指定最新版术语表时必须显式传 `--term-base <术语表.xlsx>`，避免自动发现旧版。既有内容修改且有历史语言包时，加 `--history <历史语言包.xlsx>`，只读检索当前译文，不导入或重译完整历史表。
  8. 允许保留 `short_text_length_watch` 这类软提示作为说明项，除非用户明确要求清到 0
  9. 在任务目录落一个明确命名的最终版文件，例如 `原文件名_最终版.xlsx`
  10. 同时输出 `result_{lang}.xlsx` 和 `report_{lang}.xlsx`

## 交付要求

- 结果直接输出回原目录或项目目录。
- 默认同时生成：
  - 最终版语言表
  - `result_{lang}.xlsx`
  - `report_{lang}.xlsx`
- 回复用户时优先给出最终版文件的准确路径。
- 除非用户明确要求，否则不要把中间目录、临时术语表、批次文件当成交付物。
- 如无明确要求，不要额外产出无关的过程文件。
- 如果当前交付仍有剩余问题，必须明确区分：
  - 硬错误是否已清零
  - 剩余的是软提示还是结构性问题
- 最终复检必须确认 `opaque_abbreviation`、`clipped_word`、明显的 `title_case_overuse` 为 0；否则不能说是可上线最终版。

## 文档优先级

- 处理前优先参考这些文件：
  - `README.md`
  - `CHANGELOG.md`
  - `工作流说明.md`
  - `docs/使用说明书.md`

## 交付目录清理规则

- 最终交付目录根部只保留源表、术语表和 `_最终版.xlsx`。
- `result_<lang>.xlsx` 和 `report_<lang>.xlsx` 必须统一放入 `qa_<lang>/`，不要散落在根目录。
- `.translation_cache/` 只属于过程缓存，不是交付物；除非正在连续返修同一批内容或用户明确要求保留，否则最终交付前删除。
- 删除缓存只会损失同目录重跑时的复用速度和少量一致性辅助，不影响最终 workbook、QA 报告或上线使用。

## 公告 DOCX 检索式翻译流程

- 公告 `.docx` 长文本翻译默认走 `scripts/run_announcement_docx_harness.py`，不要逐个 DOCX 自由翻译后手工覆盖。
- 固定流程是 `inspect -> stage -> prepare -> 用 Codex/ChatGPT 生成 ai_response_<code>.jsonl -> import-ai -> apply -> deliver`。
- `prepare` 默认从同 stem 术语交付表识别目标语言列；术语表没给的语言不要生成，不要凭空扩展成全语种。
- 公告术语表支持旧版单 Sheet 和新版双 Sheet：`Glossary` 提供词级主译，选填的 `SentenceTemplates` 提供句子级术语适配；不得把后者当作普通词条或无条件整句复制。
- `SentenceTemplates` 仅接受 `official_exact` 和 `official_similar`：前者优先匹配 `AnnouncementCN`，并支持用 `OfficialCNTemplate` 的 `<@数字>` 占位符匹配动态值；后者只在当前句命中 `AnnouncementCN` 线索时提供官方表达参考。
- 句子级适配优先级高于词级机械命中：`official_exact` 覆盖范围内允许使用官方整句中的自然词形，不能因未逐字包含 `Glossary` 主译而误报；`official_similar` 仍需结合当前句重新翻译，禁止带入无关内容。
- `inspect` 只读表头识别原文、术语交付表、参考语言包和目标语言；不要为了识别语言扫描大型语言包全表。
- 公告 DOCX 初译禁止使用 Google Translate、`deep_translator`、浏览器翻译、在线机翻聚合器或其他外部机器翻译服务；如果本地没有可用模型通道，必须停下说明卡点，不能降级到机翻冒充 AI 译文。
- `ai_response_<code>.jsonl` 只能由 Codex/ChatGPT/明确的大模型通道生成，格式固定为每行 `{"para_id": "...", "translation": "..."}`，并且必须与 workpack 行数、顺序和 `para_id` 完全一致。
- `import-ai` 负责把 AI response 严格回填到 `announcement_translation_workbook.xlsx`，回填前会校验漏行、重行、额外行、乱序、中文残留、受保护 token 和术语目标。
- `import-ai` 的译文 QA 失败时必须读取 `_work/announcement_docx/ai_response_qa_<code>.json` 逐项修复，不要只根据 issue 数量猜测；该报告在同语言下次通过前会先清理旧版本。
- 受保护 token 比较必须兼容全角/半角括号和 Unicode 等价形式；中文日期中的月份数字允许按目标语言写成月份名称，但日期和服龄等其余关键数字仍须保留。
- 术语表必须是同目录内与 DOCX stem 匹配的 `*_announcement_terms_*.xlsx`，不要跨项目猜测术语表。
- 过程文件只允许放在 `<task_dir>/_work/announcement_docx/`；最终交付目录只保留最终 DOCX 和 `QA摘要.xlsx`。
- `apply` 的 hard blocker 必须为 0 才能执行 `deliver`。

## 项目定制 harness 启动规则

- 最终成品必须经过正式 `run_quality_harness.py`，项目临时脚本的结构 QA 不能替代它。短 UI 罗马编号系列及同条件等级阈值任务执行跨行一致性检查；不得多数表决自动覆盖译文。
- 无分类列时，术语加载器只将备注中完整的“英雄名、角色名”等明确分类值作为姓名分类，普通备注不升级。正文姓名缺失要复核；若术语分类与当前普通词语境冲突，记录原始问题及裁决，不改正确句子或默默关闭检测。
- `source_drift_tm_conflict` 仅是显式历史表中“异源同译”的复核候选，不能自动证明错译。源文改名时必须逐项核对新主体、名称、条件及相邻系列；短词、标点差异、自然同译均按语境裁决。机器 QA 通过不等于完成深度语义审校。

- 既有语言包质量诊断须执行 `scripts/run_quality_diagnostics.py`，将物理行覆盖、未决项、同文件同 sheet 资源 ID 冲突分开报告。抽样缺陷指数不得宣称整体质量分；完整覆盖也不代表语义正确或发布验收通过。具体契约见 `docs/INDEPENDENT_TRANSLATION_QUALITY_EVALUATION.md`。

- 新项目开始前，先用 `templates/project_profile_template.md` 和 `templates/project_profile_template.json` 收集项目资料：游戏信息、类型、目标市场、目标语言、核心玩法、术语、禁用译法、风格和技术约束。
- 项目资料确认后，必须输出单项目 `translation_prompt.txt`，并在全量翻译 harness 中通过 `--style-hint-file` 使用。
- 项目 profile 和 prompt 只能放在单项目私有环境中，不能跨项目复用，也不能提交公开仓库。
- 项目定制 harness 不强制依赖 profile；但如果当前项目存在 `project_profile.json`、`project_profile.yaml` 或等价 profile，则必须读取并执行，不能忽略。
- profile 规则优先级：用户当前明确要求 > 项目 profile/prompt > 项目术语表 > 通用 `quality_harness` 规则 > 历史经验。
