# Changelog

## 2026-05-11 - Over-compression residue gate expansion

- 扩展 `clipped_word` / `romanized_name_residue` 规则，覆盖 `Chef Yifang`、`Ener Scie`、`Stru Expe`、`Pts impr esse`、`No sear resu`、`Shen Armo`、`Orde Thun` 等新发现坏例。
- AI 审核 prompt 增加职业名、资源名、装备名、搜索结果文案不得截断缩写的约束。
- 新增回归样例，确保 `Divine Edge Armor`、`Thunder Order`、`No beds available` 这类自然译法不会被误杀。
- 重跑战机语言表和 UI 表：语言表修复 175 处典型过度压缩/拼音残留，UI 表无同类命中。

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
