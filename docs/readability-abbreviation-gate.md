# 可读性、缩写与大小写拦截规则

## 典型坏例

以下过度压缩属于最终版阻断错误：

- 职业/人名：`Chef Yifang`、`Ener Scie Owen`、`Stru Expe Ethan`、`Smel Expe Kevin`
- 道具/资源：`10 Pts impr esse`、`100 elec ener`、`1K hero expe`
- 装备名：`Shen Armo`、`Tian Engi`、`Thun Wing`
- 状态/搜索：`No sear resu yet`、`No beds avai`
- 活动/功能：`Orde Thun`、`Lege Hero Gath`
- 技能/商店/消息/容量/提示文案：`Fast Trac Bull`、`Pene bull`、`Mult sanc`、`Inte guid`、`Fina ATK SPD`、`Repl This mess expi`、`No unre mess`、`Hara swip spam mess`、`Troo capa`、`Conf spen ##1 diam`、`Figh modi leve ##1`、`Offline Rwds`、`Glor Cont`、`Dese Cara`、`Cont cann empt`、`Your cont ##1`、`Loca cann plac`、`Wear equi cann rese`、`No wear equi`、`Stro equi Pack`、`TPRM#P`

处理原则：这些词不要为了长度继续压缩，直接使用自然可读译法，例如 `Chef Yvonne`、`Energy Scientist Owen`、`Divine Edge Armor`、`Thunder Order`、`Rapid Tracking Round`、`Final ATK SPD`、`Reply: This message has expired`、`No unread mail`、`Harassment, spam, or junk messages`、`Troop Capacity`、`Spend ##1 Diamonds?`、`Fighter Mod Level: ##1`、`Offline Rewards`、`Glory Contract`、`Position limit reached`、`Content cannot be empty`、`Cannot place here`、`Equipped gear cannot be reset`、`No wearable gear available`、`Powerful Gear Pack`、`No search results`。

## 目标

避免 UI 长度优化和模型风格漂移把可上线文案压成用户看不懂的内部代码、残缺词或不自然的 Title Case。长度优化只能服务于可读性，不能反过来破坏可读性。

## 已有建议短译的取舍标准

适用于用户要求精简、缩短或校对已有建议短译的任务；不是空白目标列的新译流程，也不覆盖用户明确要求抛弃旧译重译的任务。

1. **先锁定基线**：从实际表头识别中文、原长译和建议短译，明确目标语言、源行及建议列。送入既有审校入口的当前译文应为建议短译；原长译只作语境参考，不能作为默认修改或回退基线。入口不能选建议列时，用本批工作副本或审校 packet 承载建议短译，不覆盖源表或原长译列，不新增整包重译。
2. **先判断能否直接采用**：只修改会误导玩家理解/操作，或目标语言确实不通顺的地方。能读懂且不误导的建议直接保留；更完整、更优雅、换同义词或统一句式，均不足以单独构成修改理由。
3. **允许合理省略**：按句意和已有文案语境判断。提示语、重复主语/称谓、量词或可由上下文理解的修饰可以省，不因中文出现“当前、请、以下”等字样就补回；达到门槛的自然句式不机械补充“至少”。不得为了给省略定罪而假设不存在的误读，也不凭空断言实际界面已有图标或标签。
4. **保留关键判断**：容量与速度、效果增减、每次/每秒、概率、攻防与敌我、否定、取消状态、目标与队伍编号、上下限和生效时间窗口等不得混淆。若省略确实改变判断，应就地作最小修正；含义和必要的语言修复优先于一律更短。上下文不足时不猜机制、实体或计日算法；有既有可靠口径则明确沿用，否则单列待确认，不把未决说成已验证。
5. **不以补词代替校对**：每条修改说明具体误导或明确的语言缺陷。二次审计要回退仅为补齐字面或改善轻微语感而扩写的建议。自然屈折、已有可理解简写和情境省略不做机械术语替换；不得混同正式名称或制造名称冲突。
6. **统一比较口径**：修改数与标色按最终译文是否不同于建议短译计算。字符变化为 `最终译文字符数 - 建议短译字符数`，正数增字、负数缩短；默认包含空格、标点与程序片段。若报告可见字符则另标口径；相对原长译的缩短单列，不与新增修改混算。不预设统一缩短百分比，也不把字符变少当作已经通过游戏内适配。
7. **逐条给出采用结果**：区分沿用建议、必要修订、沿用原译口径或待确认；未决项不混进可直接应用的修改表。只交付本批范围的必要改动和取舍理由，不动其他词条。主控对新增词语逐项确认必要性后再导出，成品回读与明细逐格一致。
8. **技术门禁保持**：源行/ID/非目标列、占位符及顺序、标签、数值含义、换行、术语和最终读回继续验收，不因允许省略关闭数字或结构检查。机器提示需结合语境裁决并留依据；长度预算与本次字符增减的比较基线是不同用途，不改写现有 UI 预算算法。

实际模型提示已接入普通审校及术语二审（`utils/ai_checker.py`）和大文本 reviewer/auditor（`utils/large_text_multilingual_executor.py`）。项目提示模板同步同一条件规则；调用者仍须把建议列正确绑定为当前译文，模型不会自动识别或改选 workbook 列。此规则不增加模型轮次或新的执行模式。

## 阻断规则

以下问题属于最终版阻断错误：

- `opaque_abbreviation`：不可读缩写或内部代码式文案，例如 `PERR`、`DTT`、`IDNE`、`IJA`、`CL##1##2`。
- `clipped_word`：截断词、删元音词或机械压缩片段，例如 `rewa`、`obta`、`coll imme`、`tmrw`。
- `title_case_overuse`：错误、状态、提示类文案无理由使用 Title Case，例如 `Too Many Roles`、`System Error`。

最终交付前这三类明显问题必须为 `0`。

## 允许缩写

默认允许稳定游戏缩写：

- `HP`
- `ATK`
- `DEF`
- `DMG`
- `DPS`
- `PVP`
- `PVE`
- `VIP`
- `FPS`
- `SFX`
- `UI`
- `Lv`

其他缩写只有在项目术语表或客户规则中明确允许时才可使用。`Rwd`、`Req`、`Acct`、`Tmrw`、`OC`、`Mod` 不再默认视为安全缩写。

## AI 审核约束

模型审核时必须遵守：

- 不为了贴近中文长度而发明缩写。
- 不通过截断单词、删除元音、拼内部首字母来压长度。
- 如果长度预算和自然可懂冲突，以自然可懂为准，宁可略长。
- UI / 按钮 / 标签 / 中文原文 10 字以内短文本优先短，但不能牺牲理解成本。
- 英文错误、状态、提示类文案默认使用 sentence case，例如 `Too many roles`、`System error`。
- Title Case 只用于专名、功能名、标题、商店项、术语表明确要求的名称。

## 流程位置

该规则在两处生效：

- 源头：`utils/ai_checker.py` 的 prompt 明确禁止不可读缩写和截断词。
- 终点：`utils/readability_checker.py` 在机审阶段输出硬错误，`process_language.py` 会把问题行加入复审。
- 大小写检查是保守规则，只对明显错误/状态/提示类中文源文触发，避免误伤 `Battle Pass` 这类合理功能名。

## 交付检查

最终交付前必须查看 `report_{lang}.xlsx` 的错误模式：

- `opaque_abbreviation = 0`
- `clipped_word = 0`
- `title_case_overuse = 0`
- `ui_length_overflow = 0`
- `variable_missing = 0`
- `variable_extra = 0`

如果仍有 `short_text_length_watch`，它是软提示，不等同于阻断错误；但不能用坏缩写去消掉软提示。
