# Cursor Task: 游戏本地化质检工作流

**任务来源**: 小虾需求梳理  
**创建时间**: 2026-03-19 16:20  
**优先级**: P0 (英语先跑通)

---

## 一、背景与目标

### 业务场景
Post-AI-Translation 质检流程。AI粗翻后的语言包需要自动化质检，减少人工重复劳动。

### 核心目标
1. **输入**: AI粗翻语言表（Excel）+ AI粗翻术语表（Excel）
2. **输出**: 
   - 处理后的语言表（同输入格式，错误已修复，备注处理原因）
   - 问题归纳汇总报告（learning用）
   - 需人工确认的子集文件
3. **原则**: 先AI判断处理，处理不了或有异议再人工确认

---

## 二、输入数据规格

### 2.1 语言表结构

| 列 | 字段名 | 类型 | 示例 |
|----|--------|------|------|
| A | ID | int | 1, 2, 3... |
| B | 原文 | string | 充值积分达到{icon1}[color=#dc6c00]{num1}[/color] |
| C | 译文 | string | Top-up Points reaching {icon1}[color=#dc6c00]{num1}[/color] in total |

**数据规模**: 约1913行  
**格式标签**:
- BBCode: `[color=#dc6c00]`, `[/color]`
- 变量: `{icon1}`, `{num1}`, `{name}` 等

### 2.2 多语言结构
- 单语言: A列ID、B列中文原文、**C列译文**、D列备注
- 多语言: A列ID、B列中文原文、**C列译文（A语种）、D列备注（A语种）**、E列译文（B语种）、F列备注（B语种）...

### 2.3 术语表结构
与语言表相同结构: ID | 中文原文 | 译文

---

## 三、核心处理规则

### 3.1 术语双层校验

**Layer 1: 命中检测**
- 检查译文中是否使用了标准术语
- 原文包含"机甲战士" → 检查是否用了"Mech Warrior"

**Layer 2: 语法正确性**
- 检查术语使用的语法环境
- 大小写（句首/句中）
- 单复数形式
- 冠词搭配（a/an/the）

**UI术语特殊处理**: 
- **自动判断**: 脚本自动识别UI文本（基于特征：短文本、按钮类词汇、无完整句子结构等）
- **手动标记**: 支持用户手动标记UI文本（通过配置文件或输入标记列）
- **切换机制**: 保留判断切换接口，可在自动/手动模式间切换
- **处理策略**: 识别为UI文本时，尽量使用简短用语

### 3.2 同格式用语一致性 ⭐ 关键规则

**要求**: 上下文相近的同格式用语、格式必须相同

**示例** (见附图):
```
752 获得后，可解锁亚力斯特头像 → Unlocks the Alistair Avatar upon obtaining
753 获得后，可解锁艾丽莎头像   → Unlocks the Elisa Avatar upon obtaining
754 获得后，可解锁未来战士头像 → Unlocks the Austin Avatar after obtaining  ❌
755 获得后，可解锁武士头像     → Unlocks the Payne Avatar upon obtaining
...
```

**754行错误**: 其他行用 "upon obtaining"，754行用 "after obtaining" → 必须统一

**处理策略**:
1. 识别相同句式模板（如"获得后，可解锁{角色}头像"）
2. 统计该模板的所有译文变体
3. 选择最常见/最规范的变体作为标准
4. 标记不一致项为"需统一"

### 3.3 格式标签处理

**术语表**: 格式标签不一定完全一致，需要处理时自行积累规则

**语言表**: 格式标签必须严格一致
- 变量完整性: `{icon1}`, `{num1}` 等不能缺失
- 标签闭合: `[color=xxx]` 必须有 `[/color]`
- 标签一致性: 同语境下的颜色代码必须一致

---

## 四、输出文件规格

### 4.1 主输出：处理后的语言表

**格式**: 同输入格式
- 单语言: ID | 原文 | 译文 | **备注**
- 多语言: ID | 原文 | 译文(A) | 备注(A) | 译文(B) | 备注(B) ...

**内容要求**:
- 错误文本已被修复文本替代
- 无须改动的文本保持不动
- 备注列简要说明处理原因（如"统一句式"、"修正术语大小写"、"补充缺失变量"）

**示例**:
| ID | 原文 | 译文 | 备注 |
|----|------|------|------|
| 754 | 获得后，可解锁未来战士头像 | Unlocks the Austin Avatar **upon obtaining** | 统一句式: after→upon |
| 1001 | 充值积分{num1} | Recharge Points **{num1}** | 补充缺失变量 |

### 4.2 归纳汇总报告

**格式**: Excel表格（或飞书表格导出Excel）  
**用途**: 自我进化learning，分析错误模式

**Excel结构**:
| 工作表 | 内容 |
|--------|------|
| Summary | 总体统计（处理数、自动修复数、人工确认数） |
| ErrorPatterns | 错误模式汇总（类型、数量、示例ID、描述） |
| LearningNotes | 学习笔记（发现的语言规律） |
| Details | 每条处理的详细记录（ID、原文、修改前、修改后、原因） |

**JSON备用结构**（如需程序化读取）:
```json
{
  "summary": {
    "total_processed": 1913,
    "auto_fixed": 156,
    "need_human_review": 23,
    "no_change": 1734
  },
  "error_patterns": [
    {
      "pattern": "句式不一致",
      "count": 45,
      "example_ids": [754, 823, 901],
      "description": "同模板使用不同译文变体"
    },
    {
      "pattern": "术语大小写错误",
      "count": 67,
      "example_ids": [120, 340, 567],
      "description": "句中术语未小写或句首未大写"
    },
    {
      "pattern": "变量缺失",
      "count": 23,
      "example_ids": [1001, 1056],
      "description": "原文有变量但译文缺失"
    }
  ],
  "learning_notes": [
    "UI文本中'获得'统一译为'unlock'而非'get'",
    "颜色标签[color=#dc6c00]出现频率最高，可能是标准橙色"
  ]
}
```

### 4.3 人工确认文件

**触发条件**: AI判断处理不了或有异议

**内容**: 从主输出中筛选出的子集，需要人工最终确认

**筛选标准**:
- 语境存疑（AI不确定是否适用标准术语）
- 句式统一但统计结果接近（如51%用A，49%用B）
- 新发现术语（术语库中不存在）
- 长度可能溢出UI限制

**格式**: 同主输出，但备注列增加"AI建议"和"置信度"

---

## 五、处理流程设计

### Stage 1: 术语库标准化
**输入**: AI粗翻术语表（Excel）  
**输出**: `term_base_{lang}.json`

```python
# 伪代码
def extract_terms(term_excel):
    terms = read_excel(term_excel)  # ID | 原文 | 译文
    term_dict = {row['原文']: row['译文'] for row in terms}
    
    # AI建议优化（可选）
    for cn, en in term_dict.items():
        if is_ui_text(cn):
            term_dict[cn] = suggest_shorter(en)
    
    return term_dict
```

### Stage 2: 规则预检与自动修复
**输入**: 语言表（Excel）+ 术语库（JSON）  
**输出**: 
- `processed_{lang}.xlsx` (主输出)
- `report_{lang}.json` (归纳汇总)
- `human_review_{lang}.xlsx` (人工确认子集)

**检测项**:
1. **变量完整性**: 检查 `{xxx}` 和 BBCode 标签
2. **术语命中**: 检查术语是否使用
3. **术语语法**: 检查大小写、单复数
4. **句式一致性**: 同模板译文必须统一
5. **中文残留**: 检查 `[\u4e00-\u9fa5]`

**自动修复**:
- 变量缺失 → 从原文复制
- 术语大小写 → 按规则修正
- 句式不一致 → 统一为最常见变体

**人工确认标记**:
- 语境存疑 → 标记
- 统计接近 → 标记
- 新术语 → 标记
- 长度溢出 → 标记

### Stage 3: 大包处理（如需要）
**策略**: 拆分 → 并行处理 → 拼合

```python
# 伪代码
def process_large_file(file_path, chunk_size=500):
    df = read_excel(file_path)
    chunks = split(df, chunk_size)
    
    results = []
    for chunk in chunks:
        result = process_chunk(chunk)  # Stage 2
        results.append(result)
    
    merged = merge(results)
    # 全局一致性校验（跨chunk的句式统一）
    return final_check(merged)
```

---

## 六、脚本接口设计

### 6.1 术语提取
```bash
python extract_terms.py \
  --input raw_terms.xlsx \
  --lang en \
  --output term_base_en.json \
  --short-ui-terms  # UI术语尽量简短
```

### 6.2 主处理脚本
```bash
python process_language.py \
  --input language.xlsx \
  --term-base term_base_en.json \
  --lang en \
  --output-dir ./output/ \
  --auto-fix  # 自动修复可修复项
```

**输出文件**:
- `./output/processed_en.xlsx`
- `./output/report_en.json`
- `./output/human_review_en.xlsx`

### 6.3 多语言批处理
```bash
python batch_process.py \
  --input language.xlsx \
  --langs en,fr,de,tr,es,pt,ru \
  --term-base-dir ./terms/ \
  --output-dir ./output/
```

### 句式统一统计策略
**策略**: AI判断选择"合适的翻译"并**直接采用**（非简单多数决）

**判断维度**:
1. 语法正确性（优先考虑）
2. 语境自然度
3. 游戏内一致性（是否与同类UI文本风格一致）
4. 出现频率（参考，非决定因素）

**审计报告**: 在报告中记录AI的判断理由（如"选择'upon obtaining'因为更正式，适合成就解锁类UI"）

**示例**: "upon obtaining" vs "after obtaining"
- "upon"更正式，适合成就/解锁类UI
- "after"更口语，可能出现在剧情文本
- AI根据上下文判断，直接采用，并在报告中说明

### 人工确认文件交互方式
**流程**: 脚本读取修改标记 → 合并进完整包

**详细步骤**:
1. 脚本输出 `human_review_en.xlsx`（含AI建议）
2. 用户在Excel里审阅，在"人工修改"列填写最终译文（或保留AI建议）
3. 运行合并脚本 `merge_human_edits.py`
4. 脚本读取人工修改，按ID定位，合并到主输出文件

**标记规范**:
| 列 | 用途 |
|----|------|
| ID | 定位键 |
| 原文 | 参考 |
| AI建议 | 脚本生成的修改建议 |
| 人工修改 | 用户填写的最终译文（为空则使用AI建议） |
| 确认状态 | Confirmed / Modified / Rejected |

### 术语库处理流程
**来源**: AI粗翻术语表

**处理步骤**:
```
AI粗翻术语表
    ↓
脚本提取候选术语
    ↓
AI建议优化（简短UI用语）
    ↓
人工快速审核（标记Yes/No/修改）
    ↓
生成 term_base_{lang}_confirmed.json（标准术语库）
    ↓
用于语言表质检
```

**注意**: 只有经过人工确认的术语才能作为标准使用

### 多语言处理策略
**优先级**: 英语（P0）先跑通

**英语跑通后**:
- 复用核心逻辑（变量检测、句式统一、术语校验）
- 各语言独立术语库
- 各语言独立句式模板（不同语言句式结构不同）

**暂不处理**: 其他6种语言（法语、德语、土耳其语、西班牙语、葡萄牙语、俄语）

---

1. **格式标签处理**: 术语表格式标签可能不一致，需自行积累规则；语言表格式标签必须严格一致
2. **句式一致性**: 同格式用语必须相同，基于统计选择最规范变体
3. **人工确认边界**: AI先处理，处理不了或有异议的才人工确认
4. **UI术语**: 识别到UI文本时尽量简短
5. **输出格式**: 必须与输入格式一致（便于替换回原工作流程）

---

## 八、验收标准

### 功能验收
- [ ] 能正确读取Excel语言表和术语表
- [ ] 能检测变量完整性（包括BBCode标签）
- [ ] 能检测术语命中和语法正确性
- [ ] 能识别并统一同句式模板
- [ ] 能生成符合格式要求的三个输出文件
- [ ] 多语言支持（C/D列、E/F列...模式）

### 质量验收
- [ ] 自动修复率 > 80%
- [ ] 误修复率 < 5%（人工抽查）
- [ ] 句式统一检测准确率 > 95%

---

## 九、附件

1. **示例Excel**: `language_sample_1913rows.xlsx` (1913行，3列)
2. **句式统一示例图**: 见本文档上方截图
3. **输入样本路径**: `C:\Users\Administrator\.openclaw\media\inbound\è_è_è_è_å_ç_ºä¾---33c89333-39ec-4f36-bbb3-82875b009fd9.xlsx`

---

**开发启动条件**: 本需求文档已完整  
**建议开发顺序**:
1. Excel读取 + 术语库提取
2. 变量完整性检测
3. 术语命中检测
4. 句式一致性检测（核心难点）
5. 输出文件生成
6. 多语言支持
7. 大包处理优化
