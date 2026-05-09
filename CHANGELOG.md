# Changelog

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
