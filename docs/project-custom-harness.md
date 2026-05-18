# Project-Custom Harness Workflow

项目定制 harness 是通用 `quality_harness` 之外的项目级增强层，用来沉淀某个游戏项目的术语、风格、交付结构和历史问题。它不替代通用 QA gate；最终交付仍必须通过通用 `quality_harness`。

## Step 0：项目启动信息

项目开始前先建立单项目资料包，用于确定翻译风格和生成翻译提示词。资料包只在该项目私有环境中使用，不进入公开仓库。

必须收集：

- 游戏信息：游戏名、类型、题材、平台、目标市场、目标语言、玩家群体。
- 玩法信息：核心循环、主要系统、战斗/养成结构、商业化语境、UI 密度限制。
- 术语信息：强术语、软参考术语、禁用译法、人名/地名/道具/技能名策略。
- 风格信息：UI、技能描述、系统提示、邮件/剧情、错误提示、大小写策略。
- 技术约束：变量、占位符、BBCode、HTML 标签、颜色标签、换行、数字单位。
- 参考材料：术语表、合格交付参考、历史最终版、截图或 UI 上下文。

公开模板：

- `templates/project_profile_template.md`：给人填写和评审的项目资料模板。
- `templates/project_profile_template.json`：给脚本或项目 harness 读取的结构化 profile 模板。
- `templates/project_profile_template.yaml`：给偏配置化项目使用的 YAML profile 模板。
- `templates/translation_prompt_template.txt`：根据项目 profile 生成的翻译提示词模板。

建议私有项目目录：

```text
<private-project-dir>/
  project_profile.md
  project_profile.json
  project_profile.yaml
  translation_prompt.txt
  terms.xlsx
  references/
```

## Step 1：风格定标与提示词输出

项目资料确认后，先输出单项目 `translation_prompt.txt`，再进入翻译或 QA。提示词应包含：

- 项目背景和目标用户。
- 翻译风格：自然度、简短程度、语气、目标市场表达习惯。
- 术语规则：强术语必须使用，软术语只作参考，禁用译法不得出现。
- 人名/专名规则：角色、地点、道具、技能和连续编号词条必须一致。
- 技术规则：占位符、标签、颜色、换行、变量和数字单位必须保持。
- 输出协议：只输出 `ID + translation`，不输出解释、审计列或额外结构。

英语全量翻译 harness 使用该提示词时，应通过 `--style-hint-file` 注入：

```powershell
python scripts\run_translation_harness.py `
  --input <language.xlsx> `
  --term-base <terms.xlsx> `
  --lang en `
  --output-dir <work-dir> `
  --style-hint-file <private-project-dir>\translation_prompt.txt
```

项目定制 harness 不强制要求 profile；但如果同项目私有目录中存在 `project_profile.json` 或等价 profile，项目 harness 必须读取并执行其中规则，不能忽略。

## 适用场景

- 项目有固定术语口径，且通用术语表不足以表达上下文取舍。
- 项目有固定交付 workbook 结构，需要保护 sheet、列名和业务字段。
- 项目反复出现同类错误，例如人名近似错拼、UI 过度缩写、连续编号词条混译、礼包名大小写混乱。
- 用户提供了合格交付样本，需要把样本作为风格 benchmark，而不是直接照抄内容。

## 公开仓库边界

- 公开仓库只提交通用 harness 流程、模板和文档。
- 不提交客户 workbook、截图、参考样本、本地路径、项目专用术语表或可识别客户/项目名称的配置。
- 项目专用脚本、测试、prompt 和样本应放在仓库外私有目录，或通过 `.git/info/exclude` 隔离。

## 推荐目录

私有项目 harness 推荐放在公开仓库外：

```text
localization-workflow-private/
  <project-slug>/
    docs_<project-slug>-workflow.md
    scripts_run_<project-slug>_harness.py
    utils_<project-slug>_harness.py
    tests_test_<project-slug>_harness.py
    templates_<project-slug>-backfeed.txt
```

如果临时放在公开仓库工作区内，必须加入 `.git/info/exclude`，不要写进公开 `.gitignore`，避免暴露项目名。

## 执行链路

1. 先跑通用流程：识别语言表、术语表、目标列状态，完成翻译或已有译文 QA。
2. 生成最终 workbook 后，先跑通用最终门禁：

```powershell
python scripts\run_quality_harness.py fixtures\quality_regression.json --workbook <final.xlsx>
```

3. 再跑项目定制 harness：

```powershell
python <private-harness-dir>\scripts_run_<project-slug>_harness.py --workbook <final.xlsx>
```

4. 如果项目需要固定结构，再启用严格结构模式：

```powershell
python <private-harness-dir>\scripts_run_<project-slug>_harness.py `
  --workbook <final.xlsx> `
  --strict-structure `
  --reference <accepted-reference.xlsx>
```

5. 两层 hard error 都为 0 后，按交付目录规则清理：根目录只保留源表、术语表、`_最终版.xlsx`；QA 文件放入 `qa_<lang>/`；过程 cache 默认删除。

## 项目规则分层

- `通用 hard gate`：变量、占位符、标签、换行、中文残留、坏缩写、截断词、乱码符号、颜色标签、术语缺失、人名术语、连续编号一致性。
- `项目 hard gate`：项目核心术语、项目禁用译法、项目特定大小写规则、固定结构、合格参考样本的风格底线。
- `项目 soft warning`：风格不够贴近、表达略长、术语可选变体、合格样本相似度不足但不影响上线。

## 编写原则

- 项目 harness 只拦截明确、可复现、可解释的问题，不把一次性研发意见写成永久规则。
- 合格参考样本只用于校准格式、术语密度、大小写策略和自然度，不用于覆盖新任务内容。
- 人名、角色名、专名和连续编号词条优先用术语表或同批次临时术语沉淀，不能靠模型自由发挥。
- UI 长度约束不能逼出坏缩写；自然可懂优先，长度第二。
- 每新增一条项目规则，都应补一个坏例和一个好例，防止误杀。

## 交付回报

项目定制 harness 跑完后，只向用户汇报：

- 最终文件路径
- 处理范围
- 通用 QA 结果
- 项目 harness QA 结果
- 剩余 soft warning

不要把内部裁决、研发意见、批次中间文件或完整翻译清单作为交付主体。
