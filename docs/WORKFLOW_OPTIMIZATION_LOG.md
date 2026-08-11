# 工作流优化验收档案

本文件是跨任务、跨线程共享的工作流优化记录。只记录已经通过测试和真实任务证据验证的优化；想法、待验证方案和单次临时修复不得写成“已生效”。本文件采用追加式维护，历史条目不得覆盖。

## 落档门禁

每次优化只有同时满足以下条件后才能标记为 `validated`：

1. 问题有可复现证据或真实任务数据。
2. 代码改动有对应回归测试，且相关测试和全仓测试通过。
3. 至少完成一次真实任务只读基准、真实交付验证或等价端到端验收。
4. 写明适用范围、不适用范围、回滚边界和剩余风险。
5. 更新 `AGENTS.md`、相关专项工作流文档和本档案，使新线程不依赖旧线程上下文也能执行。

## 条目模板

```markdown
## YYYY-MM-DD 优化名称

- 状态：validated | rolled_back | superseded
- 代码版本：<commit/branch>
- 触发问题：<真实问题和证据>
- 实施改动：<流程、脚本、门禁>
- 验收证据：<测试命令、测试数量、真实任务指标>
- 生效范围：<哪些任务默认使用>
- 回滚边界：<如何关闭或回到旧路径>
- 剩余风险：<尚未覆盖的边界>
- 必读文档：<相关文档路径>
```

## 2026-08-11 在线术语快照与缓存命中重算门禁

- 状态：`validated`
- 代码版本：随本次 `main` 流程门禁修复提交发布
- 触发问题：金手指 33 行七语交付漏用主角术语“双生魔偶 → Clockwork Twins”。旧任务复用了仅 2176 条的本地术语表，而在线术语表 revision 512 已有 2387 个有效行；同时飞书导出的 XLSX 把 worksheet dimension 低报为 `A1`，只读加载器将整表误判为单单元格，导致新快照仍得到 0 个术语命中。旧 `cache-lint` 又只检查缓存内已有且标为 required/strict 的命中，无法发现缺失命中。
- 实施改动：术语 pack 加载器在遇到可疑 `A1` 维度时重置维度再扫描；读取分类列，将主角、角色名、人物名、英雄名、怪物名、BOSS、NPC 标为强制术语；`cache-lint` 新增 `--term-base`，用本次术语快照重新计算命中并阻断缓存快照漂移，pipeline 初检和终检均传入 term base。
- 验收证据：3 个回归测试先分别复现分类未标强制、缓存漏词未阻断、XLSX 维度低报导致 0 命中，再修复为通过；项目全量 274 项、部署 harness 全量 258 项测试通过。真实任务重算后 33 行中 28 行命中 95 个术语，审查 665 个术语×语言组合，准确检出 21 个硬错误；修正后 cache hard blocker 0、成品读回 hard blocker 0、21 个预期改单元格与缓存逐格一致、ID/CN 和其余单元格不变。
- 生效范围：所有使用大文本 pack/cache-lint 的在线术语表与本地术语表校对任务。
- 回滚边界：不得回退为只信任缓存 `term_hits` 或在线任务默认复用旧本地术语表；若项目明确允许角色名自由变体，应在术语表分类或 accepted variants 中显式声明，不得全局关闭强术语门禁。
- 剩余风险：普通动词、属性和非命名实体仍允许词形与语境变体，确定性门禁只阻断强术语；其余语义一致性仍需逐句审校和二次纠偏。
- 必读文档：`docs/LARGE_TEXT_MULTILINGUAL_WORKFLOW_V2.md`、`docs/DEEP_LINE_PROOFREADING_SUBAGENT_WORKFLOW.md`

## 2026-08-10 大文本尾部空行与占位符增量门禁

- 状态：`validated`
- 代码版本：随本次 `main` 流程门禁修复提交发布
- 触发问题：金手指真实 33 行七语深校任务的源表预设到第 1318 行，旧 `readback-gate` 把尾部 1284 个空白样式行当成有效内容，产生 `1284 × 7 = 8988` 个假 `blank_target_cell`；独立复核同时发现 ID 17 英语凭空新增 `<@6>-<@8>` 与 `<color>/<u>` 标签，而旧 `TOKEN_RE` 不识别 `<@n>`，缓存门禁错误放行。
- 实施改动：`readback-gate` 只跳过 ID 与源文同时为空的预设行，有 ID 或源文的真实行仍检查空译文；自动受保护 token 增加 `<@n>`，对目标译文新增的 `<@n>` 一律阻断，源文完全没有富文本标签时新增标签同样阻断，同时保留已有富文本源允许补闭合标签的兼容行为。
- 验收证据：新增测试先分别稳定复现 `196` 个尾部假错误和 `<@n>` 增删 `0` 告警，再实现后通过；真实最终缓存在加固门禁下先准确报出 7 个 ID 17 英语新增 token，修正后 33 行、231 个目标单元格 hard blocker 0，本地缓存与成品逐格一致；飞书 revision `474 -> 476`，在线回读 33 行、231 个译文格、99 个元数据格，不一致 0。
- 生效范围：所有使用大文本 V2 `cache-lint` 和 `readback-gate` 的 XLSX 多语言任务。
- 回滚边界：不得恢复为扫描所有预设空行或只检查 token 丢失；若项目确实允许新增富文本，必须在源文已有富文本结构或专用结构规则中显式处理，不得全局关闭新增 token 门禁。
- 剩余风险：当前新增标签检查在源文已有任一富文本标签时保持兼容，不做严格标签多重集相等；复杂富文本仍需深校 reviewer 与最终逐格读回共同兜底。
- 必读文档：`docs/LARGE_TEXT_MULTILINGUAL_WORKFLOW_V2.md`、`docs/DEEP_LINE_PROOFREADING_SUBAGENT_WORKFLOW.md`

## 2026-07-29 飞书长表离线优先与深校断点加速

- 状态：`validated`
- 代码版本：工作区待提交，基于 `main`
- 触发问题：真实飞书前端长表任务包含 3,372 行、7 个目标语言和 23,604 个深校单元。初译耗时 3,964.734 秒；旧深校批次同时承载多语言，响应易截断，且只按整批复用 checkpoint，调整批大小会重审。现场还发现 5 个重复审校进程共享同一 checkpoint，造成重复调用；飞书导出的 XLSX worksheet dimension 错标为 `A1`，`openpyxl` 只读模式误判缺少语言列。
- 实施改动：飞书长表固定为“整表导出并记录 revision/hash -> 本地翻译/深校/QA/成品读回 -> 写前 revision 门禁 -> 指定范围分块回填 -> 在线逐格读回”；深校改为单语言小批、受控并发，翻译与深校新增独立 `batch-size/workers` 参数；review checkpoint 按 `review_key + lang` 复用，改变批大小只补缺失单元；增加单任务 `proofread.lock`，拒绝重复主进程；二次审计同样按 worker 并发；reviewer 返回 `KEEP` 但省略重复译文时使用当前译文补齐，`FIX` 为空仍阻断；XLSX 精确写回和读回改用普通加载，兼容 underreported worksheet dimension。
- 验收证据：金手指真实任务最终深校建议 3,713 项、审计回退 65 项、保留修改 3,539 个单元；缓存 hard blocker 0，本地成品与缓存逐格一致；飞书 revision 438 -> 450，在线读回 3,372 行、30,348 个 A:I 单元格，不一致 0。地狱 SLG 真实任务 491 行、380 条唯一文本，43 行复用历史译文、222 行命中术语，深校保留 78 个单元修改，处理 17 个占用英语列的合并区域；飞书 revision 387 -> 410，在线读回 1,964 个 A/B/C/E 单元格，不一致 0。新增回归覆盖单语言批次、跨批大小单元续跑、重复进程拦截、并发审计、`KEEP` 空 suggested 补齐和 worksheet dimension 异常；全量 `python -m unittest discover -s tests -p 'test_*.py'` 共 262 项通过，语法编译、CLI help 和 `git diff --check` 通过。
- 生效范围：飞书/在线表格中的大文本、多语言、全量逐行深校任务，以及所有使用大文本 V2 精确 XLSX 写回的任务。
- 回滚边界：本地文件小任务可继续直接使用原入口；关闭深校时不启动 proofread 阶段。不得回滚为边翻译边写飞书、跳过 revision 门禁、多个进程共享同一任务目录，或仅检查在线单元格非空。
- 剩余风险：API 总耗时仍受模型延迟和供应端限流影响；默认 `30 × 8 workers` 是稳定起点，不保证所有供应端都适用。在线表在最终回填期间仍可能被他人修改，因此每批必须记录 revision，发现非本任务漂移立即停止。
- 必读文档：`docs/LARGE_TEXT_MULTILINGUAL_WORKFLOW_V2.md`、`docs/workflow-execution-thread-handoff.md`

## 2026-07-28 建筑名移动端地图 UI 精简策略

- 状态：validated
- 代码版本：工作区待提交
- 触发问题：真实移动端 SLG 建筑名复核中，76 条英语正式名平均 15.33 字符，建筑标签与等级、阶级同时挤在主城地图上；普通术语流程没有建筑名类型，较长功能短语不会进入专名复核。
- 实施改动：新增显式 `ui_building_name` 分类；英语正式名采用 2 个核心词 / 18 字符软预算，有独立地图标签时目标为 14 字符；等级和阶级优先拆成 UI 徽标。超预算生成 `building_name_compactness_watch`，交给 AI/人工按语义复核，不机械截词。
- 验收证据：真实任务 76 条提案的正式名平均降至 12.14 字符、地图标签平均 9.55 字符；`python -m unittest discover -s tests` 共 256 项通过，`python scripts\run_quality_harness.py fixtures\quality_regression.json --json` 共 69 个 fixture 通过，含建筑名好坏例；语法编译与 `git diff --check` 通过。
- 生效范围：术语表 `分类/category/type` 明确为建筑名或设施名的移动端地图、主城和建筑列表 UI；其他语言参考英语功能结构和简洁度自然重组。
- 回滚边界：删除或不填写建筑名/设施名分类即可保持普通术语流程；不得根据中文长度自动猜建筑名，也不得把软预算升级为无例外 hard blocker。
- 剩余风险：正式名与地图短标签仍依赖产品提供独立字段；没有独立字段时只能在语义完整、自然和紧凑之间人工取舍。
- 必读文档：`docs/UI_NAME_TRANSLATION_STANDARD.md`、`docs/quality-harness.md`

## 2026-07-13 大文本多语言工作流 V2

- 状态：`validated`
- 代码版本：`3f816ed`，分支 `codex/large-text-workflow-hardening`
- 触发问题：多 workbook、多语言任务存在重复源文重复调用、失败后整批重跑、深校建议直接影响最终译文、XLSX 多次保存后才暴露结构问题，以及只检查目标单元格非空导致的假通过风险。
- 实施改动：增加线性只读分包、历史交付和精确术语复用、唯一文本去重、API 并发和字符预算、失败拆包、按模型/供应端/语言隔离的 checkpoint、深校建议 checkpoint、主控二次审计、缓存级 QA、精确 XLSX XML 写回、ID/key/源文四重定位、样式索引检查和最终缓存逐格读回。
- 审查返工：提交前代码审查发现并修复 1 个 Critical 和 5 个 Important 问题，包括 `QA摘要.xlsx` 同名覆盖、切换供应端或审校器错误复用 checkpoint、worksheet 命名空间丢失、重复源文错行和读回只查非空不查值。
- 验收证据：基线为 184 项测试；最终 `python -m unittest discover -s tests -p 'test_*.py'` 为 206 项全部通过。真实 `7.13新增.xlsx + 7.13UI新增.xlsx` 只读分包得到 267 行、145 条唯一文本、2670 个目标单元格，分包耗时 0.55 秒。
- 生效范围：目标语言超过 4 个、多 workbook、唯一文本超过 5,000 条，或用户明确要求全量逐句/深度校对的大文本任务。
- 默认入口：`python scripts\run_large_text_multilingual_runner.py run ...`
- 回滚边界：普通单语言小表继续使用原 translation/quality harness；如 V2 runner 失败，不允许跳过缓存门禁后手工覆盖 workbook，只能保留 `_work` checkpoint 后修复或回到原小表工作流重新执行。
- 剩余风险：当前提交尚未合并到 `main`、尚未推送，也未同步到下游 studio；其他线程必须确认当前分支或后续合并版本包含本条记录后再使用 V2。
- 必读文档：`docs/LARGE_TEXT_MULTILINGUAL_WORKFLOW_V2.md`

## 2026-07-14 检索优先的唯一文本逐语言深校契约

- 状态：`validated`
- 代码版本：文档基线 `3ace84a`；本次为执行契约更新，无生产代码改动。
- 触发问题：小型多语言表存在大量重复行；如果逐行重复翻译/审校会浪费时间，而直接复用历史译文又可能保留旧语病。原 `AGENTS.md` 还要求用户另行明确授权 subagent，与“用户明确触发深校后按语言审校”的 handoff 约定不一致。
- 实施改动：固定为“精确历史复用 -> 精确术语复用 -> 模型补译 -> 唯一文本去重 -> 按语言 reviewer 建议 -> 主控二次纠偏 -> 稳定键扩展写回 -> 结构与客户端读回”；明确深校触发即授权按语言 reviewer subagent，且 subagent 不得直接写交付文件。
- 验收证据：真实匿名单 workbook 任务共 257 个源行、104 条唯一文本、2 个目标语言、514 个目标单元格；49 条复用精确术语/历史，55 条模型补译；两语完整审校提出 40 项建议，主控回退 3 项并补充 3 项纠偏，最终保留 40 项修改。最终空译文 0、中文残留 0、重复冲突 0、hard blocker 0，源列未改，交付目录仅含成品和 `QA摘要.xlsx`，Excel 原生只读打开成功。本次无生产代码改动，因此未新增代码回归测试。
- 生效范围：所有需要术语/历史检索的 workbook 翻译任务；用户明确触发深校时，普通 harness 和大文本 V2 都必须采用相同的“建议与最终写回分离”审计契约。
- 回滚边界：没有精确历史或术语时允许直接进入模型补译，但仍须唯一文本去重、逐语言审校和主控纠偏；不得回退为按重复源行多次调用模型或让 subagent 直接写 workbook。
- 剩余风险：短分类名可能缺少上下文，主控仍需结合英文参考、项目 brief 和相邻内容判断；本次任务目录中的临时脚本不是公共 API，不得跨项目复制为正式 harness。
- 必读文档：`docs/workflow-execution-thread-handoff.md`

## 2026-07-21 公告双 Sheet 句子级术语适配

- 状态：`validated`
- 触发问题：公告术语交付表新增 `Glossary + SentenceTemplates` 格式，旧 harness 只读活动 Sheet，句子级官方表达完全不进入 workpack；同时真实译文回放暴露中文月份数字、全半角括号和术语空格/连字符的 8 个误报。
- 实施改动：新增可选 `SentenceTemplates` 严格解析、`official_exact/official_similar` 分级检索、`<@数字>` 动态占位符匹配、`sentence_adaptations_json` 中转列和逐语言 workpack 证据；精确句覆盖范围可采用官方自然词形，相似句只作参考。受保护 token 改为 Unicode/括号等价比较，中文月份数字允许月份名称本地化，术语空格和连字符按等价形式比较；`import-ai` 失败会生成逐项 QA JSON 并在重试前清理旧报告。
- 验收证据：单元测试先出现 5 个预期失败，再实现通过；真实匿名公告回放为 23 个非空段落、4 个目标语言、92 个译文，词级命中 17 行、句子级适配命中 16 行、`official_exact` 1 次、`official_similar` 25 次。完整执行 `prepare -> import-ai -> apply -> deliver`，hard blocker 0，生成 4 个 DOCX 和 1 个 `QA摘要.xlsx`，交付目录无过程文件。
- 生效范围：所有通过 `scripts/run_announcement_docx_harness.py` 执行的公告 `.docx/.txt` 任务；旧单 Sheet 术语表和旧中转表继续兼容。
- 回滚边界：删除 `SentenceTemplates` 可回到纯词级检索；不得回退为把 `official_similar` 示例整句复制到当前公告，也不得恢复月份数字、全半角括号和连字符的机械误报。
- 剩余风险：句子级语义一致性仍由模型翻译和人工/深校判断，机器 QA 只验证结构、受保护内容和可确定的术语约束；不把任何客户术语表或任务目录脚本提交公共仓库。
- 必读文档：`docs/workflow-harness-context.md`、`docs/workflow-execution-thread-handoff.md`

## 2026-07-24 技能名与地名 UI 专名策略

- 状态：`validated`
- 代码版本：本次提交（基于 `main` 的 `51cf374`）
- 触发问题：真实移动端 UI 技能名筛选中，63 条候选有 25 条需要从三词以上压缩为两词以内；原流程只有通用短文本预算，不能区分技能名、地名和描述句，也不能发现不同中文专名被压成同一目标译名。
- 实施改动：术语加载保留 `分类/category/type` 并派生 `name_type`；只有显式技能名/地名类别才启用策略。workpack 和 AI 审校提示新增 `NAME` 元数据；英语技能名采用两词 / 24 字符软预算，地名采用两个核心词 / 28 字符软预算，其他语言按约两个核心语义单位自然表达。机审和最终 workbook 扫描新增超长与撞名预警，不做机械截断或自动覆盖。
- 验收证据：先运行定向测试确认 `utils.name_policy` 缺失、workpack 无专名字段、AI prompt 无规则共 3 类预期失败；实现后定向 8 项通过。`python -m unittest discover -s tests` 共 226 项通过；`python scripts\run_quality_harness.py fixtures\quality_regression.json` 共 67 个 fixture 全部通过，含技能名/地名好坏例和两条撞名回归；语法编译检查通过。
- 生效范围：普通 translation harness、`process_language` 基础/深度审校、最终 `quality_harness` workbook 扫描，以及项目提示词模板。
- 回滚边界：删除或不填写术语表专名分类即可保持原通用短文本流程；不得改成根据中文长度自动猜技能名/地名，也不得把软预算升级为无例外 hard blocker。
- 剩余风险：机器只能检查英文表面长度和重复目标名，不能自动判断意象、玩法差异或世界观专名是否保留；超预算项和撞名项仍需模型结合项目 brief、上下文和既有术语逐项裁决。
- 必读文档：`docs/UI_NAME_TRANSLATION_STANDARD.md`、`docs/workflow-execution-thread-handoff.md`

## 2026-07-24 中英双源翻译与校对

- 状态：`validated`
- 代码版本：本次提交（基于 `main` 的 `51cf374`）
- 触发问题：多语言正文和技能/地名翻译需要利用已校对英语稳定术语与表达，但旧标准 harness、AI 审校和大文本 V2 只传中文；如果直接把英语替换成原文，又会丢失中文条件、数字、占位符和术语回查，并可能跨来源误用旧缓存。
- 实施改动：新增显式 `cn / cn+en / en` 三种源模式。`cn+en` 以中文为主、英语为参考，缺失英语逐行回退中文；`en` 以英语为主并用中文回查，要求英语 100% 可用。标准 workpack、AI prompt、严格审校指纹、翻译缓存、workspace runner、大文本分包、API 唯一文本签名、checkpoint 和深校请求统一携带 `translation_source/source_mode/reference_en/reference_en_status`。
- 验收证据：测试先确认标准 prepare 不接受 `source_mode`、RowState 无参考字段、AI prompt 无双源规则，以及大文本未按英语参考区分唯一请求等预期失败；实现后相关模块回归通过。`python -m unittest discover -s tests` 共 239 项通过；`python scripts\run_quality_harness.py fixtures\quality_regression.json` 共 67 个 fixture 通过；标准小表与大文本等价端到端测试均覆盖英语完整、部分缺失、英语主源拒绝、缓存隔离、英语参考内容变化失效、英语参考漂移和 API 请求签名；CLI help 与语法编译检查通过。
- 生效范围：非英语标准全量翻译、已有译文 AI 审校、workspace runner 和大文本多语言 V2；默认 `cn` 行为保持不变。
- 回滚边界：不传 `--source-mode` 即回到中文单源；不得改成发现英语列后自动切换，也不得允许 `en` 模式在英语不完整时静默回退。
- 剩余风险：机器只能判断英语非空且无中文种子，不能证明英语语义已经人工验收；选择 `en` 前仍需项目负责人确认英语质量。中英实质冲突仍需模型结合 brief、术语表和上下文裁决。
- 必读文档：`docs/BILINGUAL_SOURCE_REFERENCE_WORKFLOW.md`、`docs/workflow-execution-thread-handoff.md`、`docs/LARGE_TEXT_MULTILINGUAL_WORKFLOW_V2.md`
