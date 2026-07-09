# 本地化质量回归 Harness

## 目标

这个 harness 用来防止“越跑越差”。它不替代翻译流程，而是在最终交付前固定检查两件事：

- 旧问题不能回来。
- 新规则不能误伤已确认可用的好译文。

最终交付以本 harness 为统一 gate。`process_language.py` 可以继续负责机审、自动修复和报告生成，但不能单独作为最终放行依据。

## 当前回归问题库

用于固定以下质量回归类型：

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
- 非问句分隔符被编码污染成问号：`Tank ? Basic Attack I`。
- 字面量 `\n` 被写成真实换行。
- 人名/角色名近似但不一致：术语表是 `Aria`，译文写成 `Arya`。
- 通用术语未命中：术语表是 `战机 -> Warplane`，译文写成 `Fighter upgrade`。
- UI 短文案超预算：`领取奖励 -> Claim all rewards now immediately`。
- 连续编号词条混译：同一中文词根如 `消灭怪物-#` 不能混用 `Kill Monsters-#`、`Destroy monsters-#` 和 `Kill monsters -#`。

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
  --workbook "C:\path\to\final-ui.xlsx" `
  --workbook "C:\path\to\final-language.xlsx"
```

Workbook 扫描必须真实命中语言表行。`rows_scanned=0` 会被视为失败，不能把空扫描当作 QA 通过。扫描使用非只读方式打开 workbook，以便更接近交付前真实 Excel 状态。通用扫描会跳过 `术语表` / glossary sheet 和审计/裁决类辅助 sheet，避免把词典里的 Title Case 术语或返修记录当正文错误误杀。

QA 会自动读取 workbook 内置术语表、同目录术语表，以及常见输出目录上一级的术语表；只有自动发现失败或需要覆盖时才补 `--term-base "C:\path\to\terms.xlsx"`。

术语默认是强约束。术语表里未显式标记为软参考的条目，正文命中中文术语时必须使用标准译法；例如 `战机 -> Warplane` 不能输出为 `Fighter`。`分类/category/type` 显式含 `soft`、`generic`、`common`、`参考`、`泛词`、`通用词` 的条目会降为软提示；当术语表没有分类列时，`获得`、`需要`、`成功` 这类明显泛词也会自动降为软提示，统计但不阻断。

如果自动发现或 `--term-base` 指定的术语表里存在 `分类` 含 `人名`、`角色`、`person`、`character`、`name` 的条目，harness 会把这些条目作为人名强约束。正文命中中文人名时，目标译文必须使用术语表里的英文名；例如 `艾莉娅 -> Aria` 不能输出为 `Arya`。

短 UI 长度也在 workbook 扫描中执行。`ui_length_overflow` 是 hard gate，`short_text_length_watch` 是软提示。当前 hard 预算：英语/泰语 `min(32, max(10, source*2+14))`，越南语/印尼语 `min(34, max(12, source*2+15))`。支持的 QA 语言代码包括 `en`、`th`、`vi`、`idn`、`fr`、`de`、`tr`、`es`、`pt`、`ru`；全量翻译 harness v1 支持 `en`、`th`、`vi`、`idn`。

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
- `term_missing`
- `term_partial_hit`
- `term_capitalization`
- `ui_length_overflow`
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
- `person_name_term_mismatch`
- `numbered_term_inconsistency`

以下问题会统计但默认不阻断：

- `short_text_length_watch`
- `term_soft_missing`
- `term_soft_partial_hit`
- `term_soft_capitalization`

## 维护规则

每次发现新的质量问题，必须补两类用例：

- 坏例：这个问题必须被拦住。
- 好例：相似但合理的译文不能被误杀。

例如新增“标题式大小写滥用”时，同时加入：

- 坏例：`Too Many Roles`。
- 好例：`7-Day Login`、`Battle Pass`。

## 当前回归结果

验证命令：

```powershell
python scripts\run_quality_harness.py fixtures\quality_regression.json
```

结果：

- fixture cases：61
- passed：True

说明：`issue_counts` 里仍会统计 fixture 里的故意坏例；只要 `passed=True` 且没有 `workbook_issues`，就表示 workbook 通过当前 harness。Workbook 扫描的空扫描失败和 glossary sheet 跳过逻辑由 `tests/test_quality_harness.py` 覆盖。
