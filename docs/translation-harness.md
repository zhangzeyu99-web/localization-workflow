# 英语全量翻译 Harness v1

## 目标

把“目标列为空、近乎全空、或目标列大面积中文回填”的英语全量翻译变成可验证流程。该 harness 不调用 API，也不自动操作 ChatGPT 网页；它由主 agent 操作模型生成译文，脚本负责打包、校验、按 ID 回填和缓存。

## 使用方式

准备 workpack：

```powershell
python scripts\run_translation_harness.py `
  --input "C:\path\lang.xlsx" `
  --term-base "C:\path\terms.xlsx" `
  --lang en `
  --output-dir "C:\path\translation_harness" `
  --style-hint "面向美国移动端用户；SLG；简短、地道、自然"
```

主 agent 读取 `translation_workpack.jsonl`，写入 `translation_response.jsonl`。每行必须是：

```json
{"id": 1001, "translation": "Claim Reward"}
```

也支持简写：

```text
1001 | Claim Reward
```

应用译文：

```powershell
python scripts\run_translation_harness.py `
  --input "C:\path\lang.xlsx" `
  --term-base "C:\path\terms.xlsx" `
  --lang en `
  --output-dir "C:\path\translation_harness" `
  --response "C:\path\translation_harness\translation_response.jsonl"
```

如需立刻进入现有机审：

```powershell
python scripts\run_translation_harness.py `
  --input "C:\path\lang.xlsx" `
  --term-base "C:\path\terms.xlsx" `
  --lang en `
  --output-dir "C:\path\translation_harness" `
  --response "C:\path\translation_harness\translation_response.jsonl" `
  --run-qa
```

## 文件

- `translation_workpack.jsonl`：主 agent 需要翻译的行级输入。
- `translation_manifest.json`：输入指纹、ID 列表、语言、文本类型抽样和协议。
- `translation_response.jsonl`：主 agent 写入的译文。
- `.translation_cache/en.jsonl`：同项目隐藏翻译记忆，位于输入语言表所在目录。
- `<原文件名>_最终版.xlsx`：按 ID 回填后的最终 workbook。

## 项目提示词

全量翻译可以传入简短项目提示词，用于约束译文风格。例如：

```powershell
python scripts\run_translation_harness.py `
  --input "C:\path\lang.xlsx" `
  --term-base "C:\path\terms.xlsx" `
  --lang en `
  --output-dir "C:\path\translation_harness" `
  --style-hint "面向美国移动端用户" `
  --style-hint "SLG 游戏；简短地道表达"
```

也可以从 UTF-8 文本文件读取：

```powershell
python scripts\run_translation_harness.py `
  --input "C:\path\lang.xlsx" `
  --term-base "C:\path\terms.xlsx" `
  --lang en `
  --output-dir "C:\path\translation_harness" `
  --style-hint-file "C:\path\style-hint.txt"
```

提示词会写入 `translation_manifest.json` 的 `style_profile.project_hint`，并复制到 `translation_workpack.jsonl` 的每条 `style_hint`。主 agent 翻译时必须按它调整风格，但不能突破变量、标签、换行、术语和 QA hard gate。

缓存按提示词隔离：同一目录下，提示词不同的旧译文不会作为当前任务的 `cache_hit`，避免“美国移动端 SLG”和其他项目风格互相污染。

## 质量约束

- 只支持英语全量翻译 v1。多语言 QA 可以由 `quality_harness` 扫描，但本 harness 不负责生成印尼语、法语、德语、土耳其语、西班牙语、葡萄牙语或俄语译文。
- 回填严格按 ID，不按行顺序猜。
- response 必须覆盖全部 ID，不能漏 ID、重复 ID、额外 ID、乱序。
- 占位符、变量、BBCode、富文本标签和换行结构必须与原文一致，否则拒绝写回。
- 术语默认强约束；只有术语表显式标记 `soft/generic/common/参考/泛词/通用词` 的条目才作为软参考。
- 后半 QA 不变，最终仍需跑 `scripts/run_quality_harness.py`。

## 主 agent 翻译原则

- 目标是上线可懂，不要求逐字直译。
- UI 短词按长度预算控制，但不能生成不可读缩写或截断词。
- 英文状态、错误、提示默认 sentence case；专名、功能名、标题才用 Title Case。
- 不保留中文残留、拼音残留或内部代码式文案。
