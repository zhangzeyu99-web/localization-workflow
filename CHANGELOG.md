# Changelog

## 2026-05-12 - Project style hints for full translation

- 英语全量翻译 harness 新增 `--style-hint` 和 `--style-hint-file`，用于传入项目级短提示词，例如“面向美国移动端用户、SLG、简短地道表达”。
- `translation_manifest.json` 现在记录 `style_profile.project_hint`，`translation_workpack.jsonl` 每行也包含 `style_hint`，方便主 agent 翻译时按同一项目风格执行。
- `.translation_cache/en.jsonl` 增加提示词隔离：提示词不同的旧译文不会作为当前任务缓存命中，避免不同项目风格互相污染。
- 保持回填协议和 QA hard gate 不变：项目提示词只能优化表达风格，不能突破变量、标签、换行、术语和可读性门槛。

## 2026-05-12 - Full translation harness real-task validation

- 使用英语全量翻译 harness 重跑一份目标列为中文回填的真实语言表，完成 `prepare -> agent response -> apply -> --run-qa -> quality_harness` 闭环。
- 本轮验证覆盖 63 条语言表记录：`translation_response.jsonl` 按 ID 全量覆盖，回填阶段通过变量、标签、换行和 manifest 指纹校验。
- 最终机审结果为 `需人工确认: 0`，`quality_harness` 扫描真实 workbook 返回 `passed: True`。
- 剩余 `term_partial_hit: 3` 被确认为术语表机械匹配造成的软提示，不作为 hard gate 阻断；README 同步补充该判断口径。
- 交付目录策略验证通过：最终只保留 `_最终版.xlsx`、`output_en_final/result_en.xlsx`、`output_en_final/report_en.xlsx` 和隐藏 `.translation_cache`，临时 harness/probe 目录不作为交付物。

## 2026-05-12 - English full translation harness v1

- 新增 `scripts/run_translation_harness.py`，支持英语目标列为空、近乎全空或大面积中文回填时，先生成 `translation_workpack.jsonl`、`translation_manifest.json` 和 `translation_response.jsonl`。
- 新增 `utils/translation_harness.py`，负责列识别后的行级打包、文本类型分类、术语命中、占位符/标签/换行结构提取、response 协议校验、按 ID 回填和同项目隐藏缓存。
- 回填阶段会拒绝漏 ID、重复 ID、额外 ID、乱序、输入漂移、空译文、占位符漂移、标签漂移和换行漂移，避免全量翻译时串行或漏行。
- 新增 `.translation_cache/<lang>.jsonl` 同项目缓存策略，只复用当前任务目录译文，避免跨项目污染和目录杂乱。
- 新增 `docs/translation-harness.md` 和单元测试，明确该 harness 不调用 API，也不启用 subagent，由主 agent 直接生成译文后再由脚本校验回填。

## 2026-05-11 - Over-compression residue gate expansion

- 修复 `ID/CN/EN` 三列表头识别，避免把 `CN` 误当目标语言列导致全表中文残留误报。
- 扩展 hard gate，拦截 `TPRM#P` 这类内部代码加 `#` 的泄漏、`?R5` 这类项目符号损坏，以及 `Fina ATK SPD` 这类新截断残留。
- 补充消息/邮件场景截断规则，覆盖 `Repl This mess expi`、`No unre mess`、`Hara swip spam mess` 等四字母片段。
- 扩展四字符截断扫描，覆盖容量、钻石、奖励、修改、伤害、离线等场景的 `Capa`、`Diam`、`Rwds`、`Modi`、`Dama`、`Offl` 等片段。
- 扩展 `clipped_word` / `romanized_name_residue` 规则，覆盖 `Chef Yifang`、`Ener Scie`、`Stru Expe`、`Pts impr esse`、`No sear resu`、`Shen Armo`、`Orde Thun` 等新发现坏例。
- AI 审核 prompt 增加职业名、资源名、装备名、搜索结果文案不得截断缩写的约束。
- 新增回归样例，确保 `Divine Edge Armor`、`Thunder Order`、`No beds available` 这类自然译法不会被误杀。
- 重跑战机语言表和 UI 表：语言表修复 175 处典型过度压缩/拼音残留，UI 表无同类命中。
- 补充技能名/商店名/提示文案重灾区规则，覆盖 `Fast Trac Bull`、`Pene bull`、`Mult sanc`、`Inte guid`、`Glor Cont`、`Dese Cara`、`Cont cann empt`、`Your cont ##1`、`Loca cann plac`、`Wear equi cann rese`、`No wear equi`、`Stro equi Pack` 等整段截断。

## 2026-05-11 - UI length budget relaxation

- 放宽 UI hard 长度预算，英语从 `min(20, max(6, source*2+4))` 调整为 `min(26, max(8, source*2+8))`。
- 印尼语同步放宽到 `min(28, max(9, source*2+9))`。
- AI 审核 prompt 明确：hard 预算是显示保护线，不是机械压缩目标，不能为了进预算产生拼音、截断词或代码式缩写。
- 新增回归测试：`Divine Edge Armor`、`10 Improvement Essence` 这类自然短词不应被迫继续压缩。

## 2026-05-09 - Quality Harness

本次更新把会话中反复暴露的本地化质量问题沉淀成可执行 harness，目标是防止“越跑越差”。

### GitHub 项目管理

- 建立里程碑 `Quality Harness v1`
- 建立标签：`type:harness`、`type:workflow`、`type:docs`、`priority:p0`、`priority:p1`、`status:ready`、`status:backlog`
- 建立 issues `#2` 到 `#7`，覆盖最终交付 gate、CI、私有回归快照、delta report、多语言扩展和备份发布流程
- 新增 `docs/project-management.md`

### 新增

- 新增 `utils/quality_harness.py`
  - 统一运行变量/BBCode、中文残留、可读性、HTML 实体、内部 token、首字母小写、标点破坏、全角符号等检查
  - 增加 `hash_code_abbreviation`、`placeholder_compaction`、`placeholder_word_glue`，拦截 `#BRUL`、`S##1##2`、`##1Employed##2` 这类缩写残留
  - 支持固定字符串 fixture 和真实 workbook 扫描
- 新增 `scripts/run_quality_harness.py`
  - 可运行 `fixtures/quality_regression.json`
  - 可通过 `--workbook` 扫描最终版 Excel
  - 支持 `--json` 输出
- 新增 `fixtures/quality_regression.json`
  - 覆盖 `[v0]` 损坏、`ZXN37Q`、`Rare&#39;s`、`PERR`、`Logi time`、`Too Many Roles`、孤立 `’s`、句首小写、全角符号、问号变引号等回归用例
  - 同时保留 `7-Day Login`、`Battle Pass`、`HP`、占位符开头句子等好例，避免误杀
- 新增 `docs/quality-harness.md`

### 验证

- `python scripts\run_quality_harness.py fixtures\quality_regression.json`
- `python scripts\run_quality_harness.py fixtures\quality_regression.json --workbook <战机UI最终版> --workbook <战机语言表最终版>`
- `python -m unittest discover -s tests -p "test_*.py"`

## 2026-05-09

### 补充：英文大小写风格

- 新增 `title_case_overuse` 检查，拦截错误、状态、提示类文案里的无理由 Title Case，例如 `Too Many Roles`、`System Error`。
- `Logi time` 这类 `Login` 截断/拼错已纳入 `clipped_word` 检查。
- AI 审核 prompt 新增约束：英文错误、状态、提示类文案默认用 sentence case；Title Case 只用于专名、功能名、标题、商店项和术语表明确要求的名称。

### 可读性硬门槛

本次更新把“UI 过度压缩导致不可读缩写”的问题固化为流程硬门槛，避免最终版再次出现 `PERR`、`DTT`、`IJA`、`CL##1##2` 这类不可上线文案。

### 新增

- 新增 `utils/readability_checker.py`
  - 检测不可读缩写：`opaque_abbreviation`
  - 检测截断词 / 机械压缩词：`clipped_word`
  - 默认允许稳定游戏缩写：`HP`、`ATK`、`DEF`、`DMG`、`DPS`、`PVP`、`PVE`、`VIP`、`FPS`、`SFX`、`UI`、`Lv`
- 主流程在 UI 长度检查后增加“可读缩写 / 截断词检查”
- AI 审核 prompt 明确禁止为了长度预算发明不可读缩写或截断单词
- 新增规则文档：`docs/readability-abbreviation-gate.md`

### 规则变更

- `opaque_abbreviation` 和 `clipped_word` 现在属于最终版阻断错误，交付前必须清到 0。
- `Rwd`、`Req`、`Acct`、`Tmrw`、`OC`、`Mod` 不再默认视为安全缩写，除非项目术语表明确允许。
- 长度和可读性冲突时，以自然可懂为准，宁可略长。

### 验证

- `python -m unittest tests.test_readability_checker tests.test_process_language tests.test_ai_review_protocol`

## 2026-04-15

本次版本把近期已经验证过的工作流增强正式合入主线，重点是把“机审 -> AI 审核 -> 严格回填 -> 复核输出”这条链路补成稳定的闭环。

### 新增

- 严格 AI 审核协议
  - `prepare / merge` 使用 manifest 和 fingerprint 绑定批次
  - 模型回填必须逐条输出 `ID | KEEP` 或 `ID | FIX | corrected translation`
  - 缺行、乱序、输入漂移都会被直接拒绝合并
- 工作区批处理入口
  - 支持按目录自动发现语言表和术语表
  - 适合直接处理项目目录
- 拼音残留检测与自动修复
  - 支持识别 `Hongshangu`、`Jushizhen`、`Meiguihu`、`Xigu...`、`Lanshidi` 等专名残留
  - 对已知地图名和地点名可执行标准映射回写
- 短文本长度预算检查
  - 中文原文可见长度 `<= 10` 先进入候选池
  - `mode=hard`：紧凑 UI / 按钮 / 标签，作为硬约束
  - `mode=soft`：普通短文本，作为软提示
  - `mode=exempt`：编号专名、复杂富文本等直接豁免
  - AI prompt 会注入 `LEN:mode=...,source=...,target=...,budget<=...` 元数据

### 改进

- 强化占位符、BBCode、全角半角和富文本安全修复
- 支持在报告中识别 `romanized_name_residue`、`ui_length_overflow`、`short_text_length_watch`
- 同步更新 `README.md`、`工作流说明.md` 和 `docs/使用说明书.md`

### 使用注意事项

- 首跑建议 `batch-size=80~100`
- `prepare` 和 `merge` 之间不要替换或重排输入文件
- 短文本长度检查不是“全部 10 字以内都硬压”，而是先入池再分层
- 如果项目需要保留音译专名，建议显式维护到术语表或白名单

### 验证

- `python -m unittest discover -s tests -p 'test_*.py'`
- `python -m py_compile process_language.py utils\\ai_checker.py utils\\term_checker.py utils\\ui_length_checker.py tests\\test_ai_review_protocol.py tests\\test_ui_length_checker.py tests\\test_process_language.py`

结果：

- 单元测试通过
- 编译检查通过
