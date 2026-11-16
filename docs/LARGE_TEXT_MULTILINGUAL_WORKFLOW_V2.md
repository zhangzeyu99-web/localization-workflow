# 大文本多语言工作流 V2

## 稳定 API 执行补充

翻译、逐句校对和独立二审统一由中转 API 执行，不消耗正文处理的 Codex 订阅额度，不自动回退 subagent。总并发默认4、最多5，跨语言和角色共用；新增 `--task-mode review`、`resume` 和独立校对/二审配置。失败分类、逐格重试、任务锁、费用边界和验收见 `RELAY_STABLE_EXECUTION.md`。

## 效率与未完成回报

按 `RELAY_EFFICIENCY_AND_REPORTING.md` 读取分阶段验收量估计剩余时间，首轮未完成和约定检查点均报告原因与下一步；不可控等待单列。初译后缓存预检用于提前发现可读性/UI/系列问题，最终预检硬阻断未清零不得导出。XLSX 采用按行分组精确写回；全部正式质量和 Excel 验收门禁保留。

## 适用范围

满足任一条件时使用本流程：目标语言超过 4 个、多 workbook 交付、唯一文本超过 5,000 条，或用户明确要求全量逐句/深度校对。

新译使用 `--task-mode translate`（默认），要求本次目标格为空；已有译文深校使用 `--task-mode review`，保留当前译文并默认全量审校。review 的空译在 API 前报告，按另行明确的补译范围处理；不得为适配入口清空目标列。仅基础 QA 的已有译文继续走普通 CLI，不误用 review 扩大深校范围。

## 一键入口

下面是空目标格的新译示例。已有译文深校沿用输入、术语和项目说明参数，加 `--task-mode review`；只读 `prepare-pack` 是新译分包，不用于准备已有译文 review。

任务要求术语完善或发现词典外专名时，先按 `GLOSSARY_ENRICHMENT_WORKFLOW.md` 执行提取、裁决、补译与验收。下面正文命令增加 `--glossary-receipt <receipt.json>` 并引用更新术语表；未决候选或任一输入哈希漂移均在翻译API前中止。旧任务不触发时保持原调用兼容。

```powershell
python scripts\run_large_text_multilingual_runner.py run `
  --input "<语言表.xlsx>" `
  --input "<UI表.xlsx>" `
  --term-base "<术语表.xlsx>" `
  --history-dir "<历史交付目录>" `
  --target-langs "EN,IDN,DE,FR,ES,PT,RU,IT,TR,TH" `
  --task-dir "<任务目录>" `
  --relay-config "<relay-api-config.json>" `
  --batch-size 60 `
  --workers 4 `
  --proofread-batch-size 30 `
  --proofread-workers 4 `
  --proofread-mode full
```

若非英语目标语言需要参考已校对英语，加 `--source-mode cn+en`；只有英语逐行完整并明确作为主源时才用 `--source-mode en`。英语参考会进入唯一文本签名、API 请求、checkpoint 和深校请求，英语变化后不会复用旧缓存。完整契约见 `BILINGUAL_SOURCE_REFERENCE_WORKFLOW.md`。

项目已有含义说明/风格 prompt 时，`run` 与 `prepare-pack` 显式加 `--style-hint-file <项目私有说明.txt>`（UTF-8，支持 BOM）。实际文本进入初译、reviewer、auditor 的 context，包含结构化纯文本槽；`文本类型/文案类型/text_type/TextType` 显式列一并传入。run 保存说明内容，resume 在 API 前核对；缺失或改动须先解决输入绑定，不能绕过快照。无说明时保留原调用兼容，不自动遍历或猜选项目文件。

名称语义检查复用现有深校：明确名称/称号类型、整行术语名称分类或显式名称风险标记进入中心词、修饰对象、虚构实体和目标语自然度核对；sampled 也包含这些明确风险。不把所有短词视为称号，不将 `of` 或任何合法语法列为黑名单。KEEP 也须审查；名称的 source/final 复述、关系检查与目标盲读绑定实际选定文本（包括 REVERT）。二审换词只为该格补盲读及再审一次，再次变词走既有有界失败重试，不加全表第三轮。

`glossary_exact` 的主译禁止静默改写或静默恢复。纯风格建议由 auditor 明确选回正确 current；源义与词典有冲突则报 `glossary_semantic_conflict`/未决项阻断交付，按 `TERM_CHANGE_DELIVERY_SYNC.md` 裁决、更新实际词典和已授权引用。词典变化后沿用输入快照保护，以新的范围任务目录复核受影响词条，保留旧 checkpoint。此门禁不授予任意改名，也不证明模型能识别所有未知错译；未启用深校时不会自动增加模型审校轮次。

共享 API 策略版本以 `utils/localization_quality_policy.py` 的 `QUALITY_POLICY_VERSION` 为准，后续显式续跑会按现有策略作用域隔离旧请求结果；已完成任务仍按现有成品验收路径返回，不自动重开。普通 harness 的明确名称缓存另绑定当前实际术语分类及命中快照，普通未分类短提示不按名称策略失效。

只准备分包、不调用 API：

```powershell
python scripts\run_large_text_multilingual_runner.py prepare-pack `
  --input "<语言表.xlsx>" `
  --target-langs "EN,IDN,DE,FR,ES,PT,RU,IT,TR,TH" `
  --work-dir "<任务目录>\_work\large_text_multilingual"
```

## 实际执行图

```mermaid
flowchart LR
  Z[飞书长表整表导出、revision 与内容留档] --> A[只读抽取本地源表]
  A --> B[历史交付与精确术语复用]
  B --> C[唯一文本去重分包]
  C --> D[API 并发翻译与批次断点]
  D --> E[缓存级确定性 QA]
  E --> F{是否明确要求深校}
  F -- 否 --> I[写回前演练]
  F -- 是 --> G[审校建议]
  G --> H[主控二次审计与最终缓存 QA]
  H --> I
  I --> J[精确 XLSX 目标单元格写回]
  J --> K[普通打开、样式索引和交付读回]
  K --> L[QA 摘要与复盘指标]
  L --> M[核对 revision、分块回填飞书并在线读回]
```

## 性能策略

- 分包只顺序读取一次 workbook；源行和唯一文本分开记录。
- API 只处理历史交付、精确术语未覆盖的唯一内容。
- 初译续跑先在同一模型/提示词/语言作用域内按文本、上下文、术语签名读取已有请求结果，再处理当前批次；改变批大小不重新调用已完成请求，源文或上下文变更只补对应请求。冲突缓存明确报错，不静默挑选旧译。沿用现有批次文件，不增加一套任务或缓存服务。
- 中文源为 JSON 或包含 3 个以上技术标签时，runner 由程序解析结构并只把可读文本槽交给 API；模型不接触、不返回 JSON、`<@n>` 或标签，程序按原路径、原标签顺序重建。结构重建不一致立即失败，不降级为整段重译。
- JSON 完整性由共享门禁覆盖初译响应、KEEP/FIX、控制器 ACCEPT/REVISE/REVERT、旧 checkpoint 复用、最终缓存和实际 workbook 回读。必须完整解析整格，保持源容器路径、固定值和逐叶技术 token；尾缀、多根、截断、未转义引号、重复键、非标准常量和结构漂移均阻断。REVERT 必须检验实际回退到的 `current`，不能使用建议或响应中的 `final` 代替。校验失败进入既有失败/重试路径，未修复不得写回或交付，不能解析前缀、删内容或回退坏稿凑通过。
- 翻译批次与深校批次独立配置。默认初译 `60 × 4 workers`，深校 `30 × 4 workers`；所有 API 角色受 `--api-concurrency` 共同限制，最多5。根据模型限流调整，不用放大多语言响应换取表面上的少批次。
- 深校按单一目标语言分批，避免一个响应同时承载多语言结果而截断；初审及二审均按语言和实际语义输入逐格复用，改变批大小后只补缺失单元。审校键保留当前语言的译文及关联话轮、源文、显式英语参考和术语约束；无关语种变化不牵连其他语言。二审另绑定建议、理由及语义证据要求，不把不同建议当作旧审计复用。
- 旧批次缓存不删除：相同输入和原批次能验证时继续复用，再补逐格绑定供后续续跑。缺绑定、冲突或未决/语义校验不合格的结果不能作为已通过缓存。
- OpenAI-compatible 传输将批内重复的场景、话轮和术语证据放入 `shared_contexts`，行内用 `$context_ref` 引用，模型递归解析完整内容；不截短或摘要化证据。分包按共享后的体积判断，最大行数和原 smoke 不变；发生引用字段冲突或不能减少体积时原样发送。未采用此传输的自定义客户端仍按原始体积分包。请求/审校键和模型响应格式不变，初译、KEEP/FIX 二审及确定性 QA 的覆盖要求不变。
- reviewer 对 `KEEP` 省略重复译文时，以当前译文补齐 `suggested`；`FIX` 缺少新译文仍是校验失败，不能降低审校覆盖门禁。
- 初审/二审响应局部失败时，已验收单元立即写入原 checkpoint，仅重发失败或缺失项，并附具体 `validation_feedback`，最多三次；相同失败反馈重试后没有进展即提前停止，不原样重复第三次。重复键的单元不接收；额外键或不可绑定对象必须先纠正，不静默丢弃后称覆盖完整。失败退出仍可复用已验收项，不增加模型阶段，也不降低全量审校和独立二审要求。
- 同一任务目录只允许一个主进程；`task.lock` 覆盖准备、翻译、校对、导出，旧 `proofread.lock` 继续保护单独深校入口，防止共享 checkpoint 重复调用。
- 翻译、深校建议和二次审计允许受控并发；XLSX 只在最终缓存 hard blocker 为 0 后写一次。
- 深校建议不能直接修改 workbook。API reviewer 输出建议，独立 API auditor 二审后由主控校验并进入最终缓存；不启动或回退 Codex subagent。
- 已有建议短译的精简校对按 `readability-abbreviation-gate.md` 执行：当前译文绑定建议短译，reviewer 只修误导或确实不通顺，auditor 回退无必要补词；修改量与字符变化对建议短译计算。合理省略不按逐词漏译处理，数字/机制/技术门禁不降低。
- 审校策略版本升级至 `review-v7-existing-short-baseline` / `audit-v10-existing-short-baseline`，显式续跑时隔离旧标准的 review/audit 结论；历史 checkpoint 保留，不自动重跑已完成任务，初译缓存不受此策略版本调整影响。
- 结构化长文本的 reviewer 和 auditor 同样只审纯文本槽；审计通过后由主控回填到当前目标结构。已经通过 QA 的原行/语言保持不变，不能因少量失败项推翻重跑。
- `sampled` 模式审全部高风险唯一文本，并按稳定签名抽取 10% 低风险唯一文本；`full` 模式审全部唯一文本。
- 过程 JSONL、checkpoint、manifest、日志和复盘指标都留在 `_work`；交付目录只包含成品 workbook 和 `QA摘要.xlsx`。

## 失败恢复收口

中断后先读 `status --manifest`，确认原主进程已退出，再用 `resume --manifest` 复用保存的配置与 checkpoint；不得重复启动整批或清空 `_work`。解决失败原因后才显式使用 `--retry-failed` 重开耗尽预算的失败格。源表、术语或项目说明变化需新建范围任务目录，保留旧凭据；已完成任务只验成品，不自动重译或重导出。

```powershell
python scripts\run_large_text_multilingual_runner.py status --manifest "<manifest.json>"
python scripts\run_large_text_multilingual_runner.py resume --manifest "<manifest.json>"
```

API 返回截断等异常如果已通过缓存补齐继续完成，不得让 manifest 永久停留在 `api_translate_failed`。只有 final cache-lint、深校摘要、apply-dry-run、交付目录和 readback 全部存在且通过时，才运行：

```powershell
python scripts\run_large_text_multilingual_runner.py reconcile `
  --manifest "<task>\_work\large_text_multilingual\large_text_multilingual_manifest.json" `
  --final-cache "<task>\_work\large_text_multilingual\final_cache.jsonl" `
  --final-cache-lint "<task>\_work\large_text_multilingual\final_cache_lint.json" `
  --proofread-summary "<task>\_work\large_text_multilingual\proofread_summary.json" `
  --apply-dry-run "<task>\_work\large_text_multilingual\apply_dry_run.json" `
  --readback-gate "<task>\_work\large_text_multilingual\final_readback_gate.json" `
  --delivery-dir "<task>\交付目录" `
  --reason "provider response truncated"
```

命令会保留原失败状态和原因，登记验证证据，生成 `recovery_retro.json`，再把关键阶段收口为 `done`。任一门禁未通过时拒绝收口。

## 飞书长表离线优先

1. 解析 Wiki 到真实 sheet token，读取当前 revision。
2. 整个 workbook 导出到 `<task_dir>\_source\`，记录 revision、下载时间、源路径、sheet 和原始内容快照。不另生成交付哈希清单；工具内部输入漂移检查保持原协议。
3. 后续抽取、翻译、深校、缓存 QA、精确 XLSX 写回和本地读回都只基于该归档副本；处理中不写飞书。
4. 本地 `cache-lint`、成品逐格读回和交付目录检查全部通过后，再读取在线 revision；与基线不一致时停止并重新比对，不盲目覆盖。
5. 只写用户指定 sheet、行列范围，分块记录每次写入后的 revision；完成后在线读取源列和目标列，与本地最终缓存逐格比较。
6. “本地成品完成”和“飞书回填读回完成”是两个独立验收点，任一失败都不得声明完整交付。

## 验收门禁

独立评估与对白质量反馈按 `INDEPENDENT_TRANSLATION_QUALITY_EVALUATION.md`：合并同批批准名称基线，记录语义审读覆盖，并对深校引入或加重的问题单独计数。auditor 输入包括主控源文、原译、上下文和术语；仅因输入契约或结构测试通过，不能宣称模型已消除语义错误。

姓名快照使用 `run_approved_name_snapshot.py`，将输出 JSON 作为 pack 和 cache-lint 的同一 `--term-base`。对白语义检查有三个不同证据：无源文的目标盲读、含源文/原译/话轮的审计、源条件化的已知语义回归规则。盲读不是确定性保证；角色仍未知时不得依据交替行号猜测。具体协议、费用影响和语境豁免见独立评估规范。

1. `cache-lint`：空译文、中文残留、占位符/标签/数字丢失、强术语遗漏和未请求语言必须为 0。
   初译后先执行保守的本地残留修复：只替换该行 `term_hits` 中仍残留的中文术语和章节序号；无法确定的中文正文不改，继续由 `cache-lint` 阻断。
2. `apply-dry-run`：普通模式可打开，样式引用合法。
3. 精确写回：文件、sheet、行号和源文四重匹配；源文漂移立即停止。
4. `readback-gate`：所有目标列非空，交付目录无过程文件；`QA摘要.xlsx` 不作为译文表重复扫描。
5. manifest：每阶段记录 `running/done/failed`、耗时和产物路径；API key 不得进入任何产物。
6. 恢复任务：计算阶段用 `resume`，已有合格产物需收口失败状态时才用 `reconcile`；不得手工改 manifest。

## 模型角色与写回边界

- 只有用户明确要求深校时启用 reviewer/auditor；V2 三个模型阶段使用中转 API，不启用 Codex subagent，失败后也不自动切换通道。
- review 模式用于已有译文深校，默认 full；translate 模式未要求深校时使用 basic，sampled 不声称全量。
- 输入是唯一文本、当前译文、术语命中、语境和受保护 token。
- reviewer 输出 `KEEP/FIX` 建议，auditor 独立裁决；通过主控覆盖、语义与结构校验后才精确写回，模型不直接修改 workbook。
- 中断保留已验收 checkpoint，resume 只补未完成格；同一任务目录只保留一个主控写入者。
