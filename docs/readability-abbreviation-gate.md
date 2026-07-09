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
