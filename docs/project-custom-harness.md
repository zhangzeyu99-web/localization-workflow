# Project-Custom Harness Workflow

项目定制 harness 是通用 `quality_harness` 之外的项目级增强层，用来沉淀某个游戏项目的术语、风格、交付结构和历史问题。它不替代通用 QA gate；最终交付仍必须通过通用 `quality_harness`。

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
