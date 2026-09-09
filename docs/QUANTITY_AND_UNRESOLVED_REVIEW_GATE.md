# 显式数量与未决审校问题门禁

触发条件：中文源文的英、西、葡语翻译及既有译文校对；审校记录声明已发现但未解决的缺失或语义问题。

## 执行规则

- `utils/quantity_guard.py` 独立于旧数字集合检查：显式小时、分钟、秒、天和次数不受 0～10 豁免影响；同时检查多次攻击的每次伤害范围。数值必须与对应单位/次数表达匹配，目标数量或程序标签中的同值数字不能代替攻击次数。
- `cache-lint` 和正式 workbook `quality_harness` 共用同一检查。英、西、葡数词按语言区分，葡语介词 `dos` 不能冒充数字 2；each/cada、每小时及服务器第几天等已验证等价形式不拦截。
- 审校记录使用 `unresolved_issues` 数组保存未决缺陷。非空或非法类型阻断；旧记录的“提交主控QA”“待主控确认/复核/处理”等明确交接语句也阻断。它们不能被 KEEP/FIX 状态盖过去。当前 review 输入校验和 cache-lint 已接入。
- 导入外部/项目审校结果时必须保留未决问题字段，不能只提取目标译文而丢弃问题。原文、译文或语境改变后重新复核，关闭问题须以最终文本和理由为证据。
- 已发现的语义缺陷不能以“旧版已有”“本次未新增硬错误”作为合格依据。超出授权修改范围时保留源文件、单列未决项，明确交付未达到该项验收；不得把备注登记等同于问题解决。
- 中文改名及备注修改仍按 `MODIFIED_SOURCE_REVIEW.md` 逐行复核；数字检查不替代语义审校。

## 验证

运行 `python -m pytest tests -q`、`python scripts/run_quality_harness.py fixtures/quality_regression.json`，再对实际成品按各语言单独运行 workbook harness 和 cache-lint。通用 fixture 默认英语，不能用 `--lang es/pt` 强行改变未指定语言的英语 fixture；三语规则案例自身携带语言。

数量回归覆盖缺数、错单位、同数字不同作用、标签数字、各语言数词、每次伤害、each/cada 等价形式；未决问题回归必须覆盖 KEEP 和 FIX 两种状态。验收同时保留修复前被拦截和修复后通过的真实数据回放。

## 边界

本规则是有限模式的确定性阻断，不是完整语义理解：目前只覆盖中文到 EN/ES/PT 的上述显式数量表达，复杂单位换算、未列语言及隐含数量仍需语义判断。对未决备注也仅识别结构化字段和明确交接短语，不保证识别任意自然语言暗示。

只在本地 workflow 维护源生效。未同步工作台及其 backend 数量逻辑；禁止将本地验证描述为产品端已上线。旧项目脚本若丢弃审校元数据，必须按本契约重新导入，不能原样复用旧脚本放行。


## 2026-09-09 自检补充：验收完整性

上一版仅覆盖单位/次数，未覆盖所有可读小数字；旧通用引擎也未自动实施文档中的 KEEP 二审要求。本节为修复后的补充契约。

- EN/ES/PT 可读源数字不再统一豁免 0～10；有限语义规则覆盖编队/队伍/VIP 编号、明确攻防条件、攻击敌方归属和短句显式否定。相同数字出现在变量中不能充当可读数量；PT dos 不作 2。其它语言及复杂语义改写不在该规则保证范围。
- 所有 review KEEP/FIX 进入 audit，KEEP 必须 ACCEPT 或 REVISE，不得 REVERT；KEEP 的 suggested 必须等于 current。审校及二审旧检查点版本失效；audit ACCEPT/REVISE 同样执行未决问题阻断。
- 共用 pair_integrity_issues 接入 cache-lint 和实际成品 readback：变量出现次数、额外受保护变量、自定义游戏色码、BBCode 色值和实际/转义换行均受检。harness 接入相同小数字和换行约束。
- 空缓存、空目标语言、空交付目录、缺源列或目标列、歧义目标列和不可识别翻译 workbook 不得通过；readback 报告 checked_workbooks/checked_target_cells。apply-dry-run 不得覆盖解析后同一路径的源文件。
- 验证必须包含重复变量丢失、额外变量、编号/攻防/敌方丢失、空结果、ACCEPT 带未决问题、KEEP 偷改译文，以及 KEEP 被二审纠正后最终缓存读回的反例。入口为 tests/test_acceptance_integrity.py、test_semantic_constraints.py 及正式 fixture。

本节是通用维护源执行器和门禁的实际实现，不仅是 Agent 文字规则；生效仍限本地，未同步 Studio。有限规则不能替代完整语义审校。
