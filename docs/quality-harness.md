# 本地化质量回归 Harness

## 目标

这个 harness 用来防止“越跑越差”。它不替代翻译流程，而是在最终交付前固定检查两件事：

- 旧问题不能回来。
- 新规则不能误伤已确认可用的好译文。

## 当前沉淀的问题库

来自本轮和前序交付中反复出现的问题：

- 占位符损坏：`[v0]` 被改成 `0`。
- HTML 实体泄漏：`Rare&#39;s`。
- 内部 token 泄漏：`ZXN37Q`、`AM4HUITL`、`SAAI##1DIT`。
- 井号代码缩写：`#BRUL`、`#FRUL`、`#DA##1##2`。
- 字母和占位符硬粘连：`S##1##2`、`L##1##2##3`、`##1Employed##2`。
- 不可读缩写：`PERR`、`DTT`、`IJA`。
- 截断词：`Logi time`、`Plea ente corr char`。
- 错误提示滥用 Title Case：`Too Many Roles`、`System Error`。
- 孤立英文所有格：`’s poisonous tongue...`。
- 句首小写异常：`double red liquid.`。
- 全角符号残留：`System error！`。
- 问号被破坏成多余引号：`What's wrong, Nora"`。
- 字面量 `\n` 被写成真实换行。

同时保留反例，避免误杀：

- `7-Day Login` 属于功能名，可以 Title Case。
- `Battle Pass` 属于功能名，可以 Title Case。
- `HP`、`ATK`、`PVP` 等稳定游戏缩写允许保留。
- `##1 and ##2 others were reassigned` 这类占位符开头句子不按普通句首小写拦截。

## 使用方式

只跑固定回归集：

```powershell
python scripts\run_quality_harness.py fixtures\quality_regression.json
```

扫描一个或多个 workbook：

```powershell
python scripts\run_quality_harness.py fixtures\quality_regression.json `
  --workbook "C:\Users\Administrator\Desktop\本地化处理\飞机语言表翻译\战机英语UI表翻译_最终版.xlsx" `
  --workbook "C:\Users\Administrator\Desktop\本地化处理\飞机语言表翻译\战机英语语言表翻译_最终版.xlsx"
```

输出 JSON：

```powershell
python scripts\run_quality_harness.py fixtures\quality_regression.json --json
```

## 判定规则

固定 fixture 要求实际问题类型和 `expected_issues` 完全一致。这样既能防漏检，也能防误报。

Workbook 扫描默认把以下问题当阻断项：

- `variable_missing`
- `variable_extra`
- `variable_order`
- `bbcode_open_mismatch`
- `bbcode_close_mismatch`
- `bbcode_unclosed`
- `bbcode_color_mismatch`
- `newline_mismatch`
- `chinese_residue`
- `opaque_abbreviation`
- `clipped_word`
- `title_case_overuse`
- `internal_token_leak`
- `hash_code_abbreviation`
- `placeholder_compaction`
- `placeholder_word_glue`
- `html_entity_leak`
- `orphan_leading_clitic`
- `leading_lowercase`
- `punctuation_corruption`
- `fullwidth_punctuation`

## 维护规则

每次发现新的质量问题，必须补两类用例：

- 坏例：这个问题必须被拦住。
- 好例：相似但合理的译文不能被误杀。

例如新增“标题式大小写滥用”时，同时加入：

- 坏例：`Too Many Roles`。
- 好例：`7-Day Login`、`Battle Pass`。

## 当前战机回归结果

最近一次验证命令：

```powershell
python scripts\run_quality_harness.py fixtures\quality_regression.json `
  --workbook "C:\Users\Administrator\Desktop\本地化处理\飞机语言表翻译\战机英语UI表翻译_最终版.xlsx" `
  --workbook "C:\Users\Administrator\Desktop\本地化处理\飞机语言表翻译\战机英语语言表翻译_最终版.xlsx"
```

结果：

- fixture cases：18
- workbook rows：2648
- passed：True

说明：`issue_counts` 里仍会统计 fixture 里的故意坏例；只要 `passed=True` 且没有 `workbook_issues`，就表示 workbook 通过当前 harness。
