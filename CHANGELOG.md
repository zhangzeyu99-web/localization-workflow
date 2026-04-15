# Changelog

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
