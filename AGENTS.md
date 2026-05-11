# AGENTS.md

## 语言

- 始终使用简体中文回复。

## 本仓库定位

- 本目录是游戏本地化处理的主工作流根目录。
- 优先使用 `workspace_runner.py`、`cli.py`、`process_language.py`。
- 不要默认退回到旧版 GUI 的人工复制粘贴流程。

## 默认执行方式

- 当用户给出语言表文件或项目目录时，不要停在机审阶段。
- 除非用户明确要求只跑部分步骤，否则默认执行完整闭环：
  1. 预检
  2. 机审
  3. 自动修复
  4. AI 审核或人工收口
  5. 严格回填
  6. 复检
  7. 导出最终版

## Subagent 规则

- 除非用户明确要求，否则禁止使用 `subagent`。
- 默认由主 agent 直接执行完整工作流。
- 主 agent 负责总控、`prepare / merge`、最终回填和最终导出。
- 不要为了并行而拆分同一语言表的严格批次映射。
- 不允许多个 agent 同时写同一个输出文件。
- 如果用户明确要求启用 `subagent`，只允许按“语言”或“项目”拆分，不允许按同一语言表的批次拆分。

## 稳定性优先

- 首跑优先稳定性，不优先吞吐量。
- 默认使用小批次，建议 `batch-size=80~100`。
- `prepare` 和 `merge` 之间不要替换、重排或改写输入语言表。
- 如果发现输入漂移、批次错配、词条漏回、响应格式错误，优先保证链路正确，不要强行合并。
- 如果需要批量翻译，必须持续输出进度，不要长时间无反馈。

## 输入假设

- 当前主支持场景是：中文原文 -> 目标语言列。
- 当前已稳定或可用的目标语言包括：
  - `en`
  - `idn`
  - `fr`
  - `de`
  - `tr`
  - `es`
  - `pt`
  - `ru`
- 如果同目录或工作区里存在术语表，默认一起使用。
- 如果没有术语表，则按无术语模式继续处理，不要因此停住。

## 目标列状态规则

- 如果目标语言列已有有效文本，直接进入主工作流收口，不要重建翻译管线。
- 如果目标语言列为空，或接近全空，则允许直接启动备用翻译管线。
- 如果目标语言列全空，而用户又希望更稳的处理，可先把中文原文整列复制到目标语言列，再进入主工作流；这通常比“纯空列从零生成”更稳。

## 备用翻译管线

- 备用翻译管线只在“目标语言列为空或近乎全空”时使用。
- 只处理当前任务目录，不扫描整个工作区，不做工作区级翻译记忆库扫描，除非用户明确要求。
- 输入物料只使用当前目录中的：
  - 语言表
  - 术语表
  - 当前任务相关输出目录
- 翻译前必须保护：
  - 变量
  - 占位符
  - BBCode / 标签
  - 换行
  - 术语表里的术语
- 批量翻译时必须给每一行加唯一行号 token，再按 token 回填，避免批次错位、串行和漏行。
- 不允许用仅靠行顺序猜测的拼接方式回填。
- 备用翻译管线的输出必须立刻回写到目标语言列，再进入主工作流继续做机审和收口。

## 质量要求

- 变量、占位符、BBCode、换行必须严格保留。
- 不要为了缩短文案破坏占位符、标签、变量顺序或结构。
- 短文本长度规则默认启用：
  - 中文原文可见长度 `<= 10` 先入池
  - `mode=hard`：紧凑 UI / 按钮 / 标签
  - `mode=soft`：普通短文本软提示
  - `mode=exempt`：编号专名、复杂富文本等豁免
- 英语 UI hard 预算：`min(26, max(8, 中文可见长度 * 2 + 8))`。
- 印尼语 UI hard 预算：`min(28, max(9, 中文可见长度 * 2 + 9))`。
- 自然可懂优先，长度第二。
- 不允许为了长度生成不可读缩写或内部代码式文案，例如 `PERR`、`DTT`、`IDNE`、`IJA`、`CL##1##2`、`TPRM#P`。
- 不允许截断英文单词或删除元音来压长度，例如 `rewa`、`obta`、`coll imme`、`tmrw`。
- 不允许把职业、资源、装备、技能名、商店名、搜索结果、消息/邮件、容量、积分、内容/敏感词提示、摆放提示等常规词压成片段，例如 `Ener Scie`、`Stru Expe`、`Smel Expe`、`Pts impr esse`、`No sear resu`、`Shen Armo`、`Orde Thun`、`Fast Trac Bull`、`Fina ATK SPD`、`Repl This mess expi`、`No unre mess`、`Hara swip spam mess`、`Troo capa`、`Conf spen ##1 diam`、`Figh modi leve ##1`、`Offline Rwds`、`Glor Cont`、`Cont cann empt`、`Your cont ##1`、`Loca cann plac`、`Wear equi cann rese`、`No wear equi`、`Stro equi Pack`。
- 不允许保留不该上线的中文拼音残留，例如 `Chef Yifang`；应改为自然本地化姓名，例如 `Chef Yvonne`。
- 允许稳定游戏缩写：`HP`、`ATK`、`DEF`、`DMG`、`DPS`、`PVP`、`PVE`、`VIP`、`FPS`、`SFX`、`UI`、`Lv`。
- 如果长度预算和可读性冲突，以自然可懂为准，宁可略长，不用坏缩写。
- 英文错误、状态、提示类文案默认使用 sentence case，例如 `Too many roles`、`System error`；不要无理由写成 `Too Many Roles`、`System Error`。
- Title Case 只用于合理范围：专名、功能名、标题、商店项、术语表明确要求的名称。
- 新增任何质量规则时，必须同步补 `fixtures/quality_regression.json`：坏例要被拦住，好例不能被误杀。

## 最终版交付管线

- 最终交付不是只跑机审，而是必须按下面顺序执行：
  1. 识别当前目录中的语言表和术语表
  2. 判断目标语言列是否为空
  3. 若为空则先走备用翻译管线；若不为空则直接进入主工作流
  4. 跑预检、机审、自动修复
  5. 优先清掉硬错误：
     - `term_missing`
     - `chinese_residue`
     - `variable_missing`
     - `ui_length_overflow`
     - `opaque_abbreviation`
     - `clipped_word`
     - `title_case_overuse`
     - 其他结构性错误
  6. 反复复检，直到不再有硬错误
  7. 跑质量回归 harness：`python scripts\run_quality_harness.py fixtures\quality_regression.json --workbook <最终版.xlsx>`
  8. 允许保留 `short_text_length_watch` 这类软提示作为说明项，除非用户明确要求清到 0
  9. 在任务目录落一个明确命名的最终版文件，例如 `原文件名_最终版.xlsx`
  10. 同时输出 `result_{lang}.xlsx` 和 `report_{lang}.xlsx`

## 交付要求

- 结果直接输出回原目录或项目目录。
- 默认同时生成：
  - 最终版语言表
  - `result_{lang}.xlsx`
  - `report_{lang}.xlsx`
- 回复用户时优先给出最终版文件的准确路径。
- 除非用户明确要求，否则不要把中间目录、临时术语表、批次文件当成交付物。
- 如无明确要求，不要额外产出无关的过程文件。
- 如果当前交付仍有剩余问题，必须明确区分：
  - 硬错误是否已清零
  - 剩余的是软提示还是结构性问题
- 最终复检必须确认 `opaque_abbreviation`、`clipped_word`、明显的 `title_case_overuse` 为 0；否则不能说是可上线最终版。

## 文档优先级

- 处理前优先参考这些文件：
  - `README.md`
  - `CHANGELOG.md`
  - `工作流说明.md`
  - `docs/使用说明书.md`
