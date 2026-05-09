# 项目管理

## GitHub 地址

- 仓库：[zhangzeyu99-web/localization-workflow](https://github.com/zhangzeyu99-web/localization-workflow)
- 里程碑：[Quality Harness v1](https://github.com/zhangzeyu99-web/localization-workflow/milestone/1)
- 备份 tag：[`backup/quality-harness-20260509-180652`](https://github.com/zhangzeyu99-web/localization-workflow/releases/tag/backup%2Fquality-harness-20260509-180652)

## 标签体系

- `type:harness`：质量回归、fixture、harness gate。
- `type:workflow`：本地化处理链路、交付流程、备份流程。
- `type:docs`：说明文档、操作手册。
- `priority:p0`：可靠交付前必须处理。
- `priority:p1`：重要增强项。
- `status:ready`：可以直接执行。
- `status:backlog`：已记录，等待排期。

## 当前里程碑

`Quality Harness v1` 用来把本轮已经暴露的问题从临时修补转成可持续工程能力。

当前跟踪项：

- [#2 P0: Make quality harness a mandatory final delivery gate](https://github.com/zhangzeyu99-web/localization-workflow/issues/2)
- [#3 P0: Add CI for unit tests and quality harness fixtures](https://github.com/zhangzeyu99-web/localization-workflow/issues/3)
- [#4 P1: Add project-specific private regression snapshots without committing customer workbooks](https://github.com/zhangzeyu99-web/localization-workflow/issues/4)
- [#5 P1: Add change-budget and delta report before workbook overwrite](https://github.com/zhangzeyu99-web/localization-workflow/issues/5)
- [#6 P1: Expand quality harness for supported non-English target languages](https://github.com/zhangzeyu99-web/localization-workflow/issues/6)
- [#7 P1: Formalize backup and release routine for delivery workbooks](https://github.com/zhangzeyu99-web/localization-workflow/issues/7)

## 维护节奏

每次交付或规则迭代必须做三件事：

1. 更新 `fixtures/quality_regression.json`，同时补坏例和好例。
2. 运行 `python -m unittest discover -s tests -p "test_*.py"`。
3. 对最终 workbook 跑 `python scripts\run_quality_harness.py fixtures\quality_regression.json --workbook <最终版.xlsx>`。

## 文件边界

- 公共仓库只提交代码、文档、通用 fixture。
- 客户 workbook 不提交到公共仓库。
- 客户交付备份放本机备份目录或私有备份仓库。
