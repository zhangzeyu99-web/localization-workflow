# 竞品查词与建议表工作流

## 适用范围

当任务要求先查询指定竞品资料，再给固定布局的 XLSX 增加多语言建议列时，使用：

```powershell
py -3 -X utf8 scripts/run_reference_suggestion_workflow.py --help
```

该入口只处理显式清单中的 XLSX/CSV 和显式配置的小表。它不扫描磁盘、不调用翻译 API，也不根据检索结果自动改译文。语言判断仍由审校模型完成，控制模型复核修改项和疑点。

V1 只支持普通单元格小表。`prepare` 会拒绝工作簿中的公式、合并单元格、结构化表、条件格式和数据验证；这些对象可能在插列后改变引用语义，当前导出器不迁移它们。

## 1. 建立持久竞品缓存

客户资料清单和缓存必须放在仓库外的稳定路径。清单示例：

```json
{
  "schema": "competitor-reference-catalog/v1",
  "sources": [
    {
      "id": "game-a-1.2.3",
      "version": "1.2.3",
      "path": "<absolute-path>/game-a.xlsx",
      "sheet": "Multilingual",
      "header_row": 1,
      "columns": {
        "module": "module",
        "key": "KEY",
        "languages": {"zh_cn": "zh_cn", "en": "en", "es": "es", "pt": "pt"}
      }
    }
  ]
}
```

CSV 使用相同的 `columns`，可选 `encoding`。构建或显式刷新：

```powershell
py -3 -X utf8 scripts/run_reference_suggestion_workflow.py cache-build `
  --config <catalog.json> `
  --output <stable-cache>/competitor_cache.json
```

缓存记录源路径、版本、SHA256、sheet、物理行、模块、KEY、真实语言代码和原始文本。后续批次直接复用同一 `--cache`；清单、缓存内容或任一竞品源漂移时，查询及所有后续阶段都会阻断，不能静默使用旧资料。

## 2. 统一查询

```powershell
py -3 -X utf8 scripts/run_reference_suggestion_workflow.py query `
  --cache <stable-cache>/competitor_cache.json `
  --text "<CN or EN text>" `
  --module "<optional scene hint>" `
  --top 3 `
  --output <work-dir>/reference_hits.json
```

查询先找 CN/EN 字面精确命中，再给有界相似候选，每项最多三条。输出保留竞品原文及来源定位。`exact_text` 只表示字面匹配；`similar_candidate` 只提供场景线索。两者都不能自动证明语义对应、自动套用译文或仅凭跨游戏 KEY 关联。没有可靠候选时记录 `no_reliable_match`。

## 3. 准备逐格审校记录

任务配置示例：

```json
{
  "input": "<absolute-path>/source.xlsx",
  "reference_cache": "<stable-cache>/competitor_cache.json",
  "glossary": ["<absolute-path>/glossary.xlsx"],
  "context": ["<absolute-path>/brief.md"],
  "sheets": [
    {
      "name": "Sheet1",
      "has_header": false,
      "columns": {
        "key": "A",
        "source": "B",
        "targets": {"EN": "C", "ES": "D", "PT": "E"},
        "note": "F"
      }
    }
  ]
}
```

`has_header` 必须显式填写；`false` 时第一行就是数据，不会丢失。KEY、源文、目标语言和备注列必须互不重叠，目标语言经大小写归一后也必须唯一。

```powershell
py -3 -X utf8 scripts/run_reference_suggestion_workflow.py prepare `
  --config <task.json> `
  --work-dir <work-dir>
```

`prepare` 记录源表/支持资料/竞品缓存的哈希、sheet、表头状态、物理行列、空行、原列映射及样式，并把任务配置、词表/上下文、竞品缓存和源表快照合成审校上下文指纹，写入每个目标格的 `batch_signature`。候选 ID 固定为 `sheet + physical row + language`。完全相同的权威输入可复用审校记录；任一权威输入变化后，旧记录会在 `import` 阶段因批次绑定不符而阻断。

## 4. 模型审校与验收导入

一个审校模型填写候选；控制模型复核修改项和疑点。每条记录必须原样带回绑定字段：

- `id`, `sheet`, `row`, `lang`, `key`, `source`, `original`, `batch_signature`
- `decision`: `KEEP` 或 `FIX`
- `suggested`: KEEP 必须为空；FIX 必须非空且不同于原译
- `reason`, `original_length` 由候选提供，最终长度由程序重算
- `reference_relation`: `corresponding`, `similar`, `no_match`
- `evidence_ids`: 仅填真实缓存记录 ID；`no_match` 必须为空
- `basis`: `reference` 或 `independent`
- `evaluation_model`, `controller_model`, `controller_status: "ACCEPTED"`

绿色资格必须同时满足：模型明确判为同场景 `corresponding`、KEEP、存在证据，并且该语言的竞品原始译文与项目原译严格相同。字面精确检索本身不会自动变绿。

```powershell
py -3 -X utf8 scripts/run_reference_suggestion_workflow.py import `
  --manifest <work-dir>/manifest.json `
  --review <work-dir>/review.json `
  --output <work-dir>/accepted_review.json `
  --report <work-dir>/import_report.json
```

漏格、多格、重复 ID、批次绑定不符、未知出处、KEEP 填新译、FIX 留空或未改、数字/占位符/富文本标签丢失都会阻断。候选必须先完整验收，才能导出。

## 5. 导出和读回验证

导出使用 bundled Artifact Tool 写 XLSX；Python/openpyxl 只做只读检查。

```powershell
py -3 -X utf8 scripts/run_reference_suggestion_workflow.py export `
  --manifest <work-dir>/manifest.json `
  --accepted-review <work-dir>/accepted_review.json `
  --output <delivery-dir>/suggestions.xlsx `
  --work-dir <work-dir>

py -3 -X utf8 scripts/run_reference_suggestion_workflow.py verify `
  --manifest <work-dir>/manifest.json `
  --accepted-review <work-dir>/accepted_review.json `
  --output <delivery-dir>/suggestions.xlsx `
  --report <work-dir>/verify_report.json
```

导出不改源文件；每种目标语言后插入建议列。KEEP 的建议格留空；FIX 的原译为黄色、建议为蓝色；经审校确认同场景且同译的 KEEP 原译为绿色。备注按语言分行，写入“保持原样/建议修改”、原因、原/新长度、对应关系、判断依据和证据 ID；已有备注原样保留后再追加。长文本和建议列自动换行，建议垂直居中，并生成短词与最长译文风险两张预览。

`verify` 会重新核对所有输入快照，检查原 sheet、物理行和空行、非目标值与样式、目标建议、备注内容、颜色及可读性。修正候选后，只需重跑 `import -> export -> verify`；源表、任务配置、支持资料或竞品资料变化时，重新 `prepare`，竞品资料变化还要显式重建缓存。
