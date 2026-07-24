# 中英双源翻译与校对工作流

## 目的

非英语目标语言可以参考已校对英语，但英语不能无条件覆盖中文原意。工作流提供三种显式模式：

| 模式 | 语义主源 | 英语作用 | 适用场景 |
|---|---|---|---|
| `cn` | 中文 | 不使用 | 没有可靠英语，或目标语言是英语 |
| `cn+en` | 中文 | 术语、专名、语气和歧义参考 | 默认推荐的非英语多语言任务 |
| `en` | 已校对英语 | 主翻译源 | 用户明确要求按英语翻译，且英语逐行完整可靠 |

`en` 模式仍保留中文用于漏译、玩法条件、数字、占位符和术语回查，不等于丢弃中文。

## 输入要求

- `cn+en` 和 `en` 只用于非英语目标语言。
- 同一语言表必须有可识别的中文源列、英语列和目标语言列。
- `cn+en` 允许个别英语为空或仍是中文种子；这些行标为 `missing/chinese_seed`，逐行回退中文。
- `en` 要求所有有效源行都有非空且无中文残留的英语；任何缺失都会在 prepare 阶段中止。
- 机器只能验证英语列是否可用，不能证明其语义已经人工验收；选择 `en` 本身就是显式质量决策。

## 数据契约

翻译 workpack 和大文本 items 统一包含：

- `source` / `source_cn` / `cn`：中文或原始基准文本，用于术语和结构回查。
- `translation_source`：模型本行应优先依据的文本。
- `source_mode`：`cn`、`cn+en` 或 `en`。
- `reference_en`：可用英语参考。
- `reference_en_status`：`usable`、`missing`、`chinese_seed` 或 `not_requested`。

manifest 记录英语覆盖率。严格 AI 审校指纹、翻译缓存、API 唯一文本签名和深校 checkpoint 都包含源模式与英语参考；英语改动后不得复用旧结果。

## 翻译与校对规则

### `cn+en`

1. 中文决定完整语义、条件、数值、对象和逻辑关系。
2. 英语辅助确定术语、技能名、地名、角色名、语气和简洁表达。
3. 中英冲突时，不传播英语的漏译或错译；结合术语表和项目 brief 裁决。
4. 英语缺失的单行自动按中文翻译，不影响其他行使用英语参考。

### `en`

1. 英语作为主翻译源，目标语言按英语语义和表达关系生成。
2. 中文用于检查英语是否遗漏玩法条件、目标、数字、时间、占位符和强术语。
3. 发现中英实质冲突时必须进入人工/AI 复核，不得静默任选一方。

## CLI

标准翻译 workpack：

```powershell
python scripts\run_translation_harness.py --input <language.xlsx> --term-base <terms.xlsx> --lang fr --source-mode cn+en --output-dir <out>
```

按英语主源翻译：

```powershell
python scripts\run_translation_harness.py --input <language.xlsx> --term-base <terms.xlsx> --lang fr --source-mode en --output-dir <out>
```

已有译文 AI 审校：

```powershell
python cli.py --input <language.xlsx> --term-base <terms.xlsx> --lang fr --source-mode cn+en --agent prepare --output-dir <out>
```

大文本多语言：

```powershell
python scripts\run_large_text_multilingual_runner.py run --input <language.xlsx> --target-langs FR,DE,ES,PT --source-mode cn+en --task-dir <task_dir> --relay-config <relay.json> --proofread-mode full
```

## 验收

- manifest 英语覆盖率与真实行数一致。
- `en` 模式不存在缺失或中文种子英语行。
- AI 提示词和 API 请求包含正确的 `source_mode/reference_en`。
- prepare 与 merge 之间英语变化会触发输入漂移。
- 切换 `cn`、`cn+en`、`en` 不复用其他模式缓存。
- 最终译文继续通过术语、变量、标签、数字、中文残留和读回门禁。
