# 游戏本地化质检工作流
**需求梳理与设计文档**

> 状态：样本已确认，工作流设计中  
> 最后更新：2026-03-19 15:54  
> 样本规模：1913行

---

## 一、需求总览

### 1.1 业务场景
- **阶段**：Post-AI-Translation（AI粗翻后）
- **输入**：AI粗翻的完整语言包（Excel格式）
- **输出**：质检后的标准语言包 + 术语库
- **核心诉求**：人机协作，高效质检，避免整包塞给大模型

### 1.2 处理语言（优先级）

| 优先级 | 语言 | 状态 |
|--------|------|------|
| P0 | 英语 | 先跑通 |
| P1 | 法语、德语、土耳其语、西班牙语、葡萄牙语、俄语 | 批量处理 |

---

## 二、输入数据规格（已确认）

### 2.1 AI粗翻文档结构

| 列 | 字段名 | 类型 | 示例 |
|----|--------|------|------|
| A | ID | int | 1, 2, 3... |
| B | 原文 | string | 充值积分达到{icon1}[color=#dc6c00]{num1}[/color] |
| C | 译文 | string | Top-up Points reaching {icon1}[color=#dc6c00]{num1}[/color] in total |

**数据规模**：1913行  
**格式标签**：
- BBCode标签：`[color=#dc6c00]`, `[/color]`
- 变量占位符：`{icon1}`, `{num1}` 等

### 2.2 AI粗翻术语表结构
- **格式**：Excel（待提供）
- **现状**：AI生成，术语僵硬
- **处理方式**：AI建议 + 人工快速审核 → 标准术语库（JSON格式）

---

## 三、工作流设计（人工 vs 脚本）

### Stage 1: 术语库标准化
**方式**：AI建议 + 人工快速审核  
**工具**：Cursor 本地脚本  
**输入**：AI粗翻术语表（Excel）  
**输出**：`term_base_{lang}.json`

```
输入: AI粗翻术语表 (Excel)
  ↓
脚本: 提取术语候选 + AI建议优化
  ↓
人工: 快速审核 (Yes/No/修改)
  ↓
输出: 标准术语库 (JSON)
```

**关键操作**：
- 脚本提取原文-译文对
- Cursor AI建议更自然的术语表达
- 人工逐条确认或批量确认

---

### Stage 2: 规则预检（零API成本）
**方式**：本地Python脚本  
**输出**：`pre_check_report.json`

#### 2.1 基础检测规则
| 规则 | 类型 | 示例 |
|------|------|------|
| 中文残留检测 | Critical | 检查 `[\u4e00-\u9fa5]` |
| 变量标签完整性 | Critical | 检查 `{icon1}`, `{num1}`, `[color]`, `[/color]` |
| 术语一致性 | Major | 对照术语库检查 |
| 格式错误 | Major | 未闭合标签、编码问题 |
| 长度溢出 | Minor | 超出UI限制（如有） |

#### 2.2 术语双层校验 ⭐ NEW
**第一层：术语命中检测**
```python
# 检查译文中是否使用了标准术语
def check_term_hit(text: str, term_base: dict) -> list:
    # 返回：哪些术语已使用，哪些术语缺失
    # 示例：原文"机甲战士" → 检查是否用了 "Mech Warrior"
```

**第二层：术语语法正确性**
```python
# 检查术语使用的语法环境是否正确
def check_term_grammar(text: str, term: str, context: dict) -> bool:
    # 检查点：
    # - 大小写（句首/句中）
    # - 单复数形式
    # - 冠词搭配（a/an/the）
    # - 词性变化（动词/名词）
```

**示例**：
| 原文 | 术语库 | 译文 | 命中检查 | 语法检查 |
|------|--------|------|----------|----------|
| 获得机甲战士 | 机甲战士 = Mech Warrior | Get mech warrior | ✅ 命中 | ❌ 小写错误 |
| 机甲战士出击 | 机甲战士 = Mech Warrior | Mech Warriors attack | ✅ 命中 | ⚠️ 复数形式需确认 |

---

### Stage 3: AI深度审校（按需触发）
**方式**：Cursor Agent，分块处理  
**原则**：不是所有文本都过AI，只处理标记项

**触发条件**：
1. 规则检测标记的"语境风险"项
2. 术语语法存疑的项
3. 自然度存疑的译文
4. 新术语发现

**处理流程**：
```
输入: 问题文本块 (原文+译文+术语表)
  ↓
Cursor Agent: 深度审校
  - 语境适配检查
  - 术语语法验证
  - 自然度评估
  - 风格一致性
  ↓
输出: AI审校建议 (JSON)
```

#### 3.1 大语言包拆分策略 ⭐ NEW
```python
# 大包拆分 → 并行处理 → 结果拼合

def split_large_package(df, chunk_size=100):
    """
    按chunk_size拆分为多个子包
    保持关联文本在同一chunk（按界面/功能分组）
    """
    chunks = []
    for i in range(0, len(df), chunk_size):
        chunk = df.iloc[i:i+chunk_size]
        chunks.append({
            'id': f'chunk_{i//chunk_size:03d}',
            'data': chunk,
            'range': (i, min(i+chunk_size, len(df)))
        })
    return chunks

def merge_results(chunk_results):
    """
    拼合各chunk的处理结果
    处理边界问题（跨chunk的术语一致性）
    """
    merged = concat(chunk_results)
    # 全局一致性校验
    return merged
```

**拆分策略**：
- 默认chunk: 100条/块
- 保持功能模块完整（不拆分同一界面文本）
- 1913行 → 约20个chunk

---

### Stage 4: 人工终审
**方式**：人工确认  
**工具**：飞书表格 / Cursor  
**输入**：合并报告（规则问题 + AI审校问题）  
**动作**：确认 / 修改 / 忽略

**优先级队列**：
| 优先级 | 处理方式 | 时限 |
|--------|----------|------|
| P0 (Critical) | 自动阻断，必须人工确认 | 立即 |
| P1 (Major) | 生成待办，分配给审校 | 当日 |
| P2 (Minor) | 批量审核，批量修改 | 本周 |
| P3 (建议) | 记录到优化清单 | 可选 |

---

### Stage 5: 自动修复
**方式**：本地Python脚本  
**输入**：确认的问题清单  
**输出**：修复后语言包

**自动修复项**：
| 问题类型 | 自动修复 | 人工确认 |
|----------|----------|----------|
| 变量缺失 | ✅ 自动补全 | ❌ 无需 |
| 术语大小写 | ✅ 自动修正 | ⚠️ 抽查 |
| 中文残留 | ✅ 标记待翻译 | ❌ 无需 |
| 术语语法 | ⚠️ 建议修正 | ✅ 必须 |
| 语境不符 | ❌ 无法自动 | ✅ 必须 |
| 长度溢出 | ⚠️ 建议缩写 | ✅ 必须 |

---

## 四、工具栈

| 环节 | 工具 | 说明 |
|------|------|------|
| 脚本开发 | Cursor | 本地Python脚本，零API依赖 |
| 术语审核 | Cursor + 人工 | AI建议，人工拍板 |
| 规则预检 | Python本地脚本 | pandas + regex，零成本 |
| 大包拆分 | Python脚本 | 自动拆分与拼合 |
| AI审校 | Cursor Agent | 按需触发，分块处理 |
| 问题追踪 | 飞书表格 | 可视化管理，优先级队列 |
| 版本管理 | Git | 语言包版本控制 |

---

## 五、脚本接口设计

### 5.1 术语库生成脚本
```python
# term_extractor.py
# 输入: raw_terms.xlsx (AI粗翻术语表)
# 输出: term_base_en.json (标准术语库)

python term_extractor.py \
  --input raw_terms.xlsx \
  --lang en \
  --output term_base_en.json \
  --review-mode interactive  # interactive | batch
```

### 5.2 规则预检脚本
```python
# pre_checker.py
# 输入: translation.xlsx (AI粗翻文档)
# 输出: pre_check_report.json

python pre_checker.py \
  --input translation.xlsx \
  --term-base term_base_en.json \
  --output pre_check_report.json \
  --rules all  # all | critical | custom
  --chunk-size 100  # 大包拆分参数 ⭐ NEW
```

**术语双层校验实现**：
```python
# term_validator.py

class TermValidator:
    def __init__(self, term_base: dict):
        self.term_base = term_base
        self.grammar_rules = self.load_grammar_rules()
    
    def validate(self, source: str, target: str) -> dict:
        """
        双层校验：命中 + 语法
        """
        result = {
            'hits': [],      # 命中的术语
            'misses': [],    # 缺失的术语
            'grammar_errors': []  # 语法错误
        }
        
        # Layer 1: 命中检测
        for cn_term, en_term in self.term_base.items():
            if cn_term in source:
                if en_term.lower() in target.lower():
                    result['hits'].append({
                        'term': cn_term,
                        'expected': en_term,
                        'found': self.extract_term_instance(target, en_term)
                    })
                else:
                    result['misses'].append({
                        'term': cn_term,
                        'expected': en_term
                    })
        
        # Layer 2: 语法检查
        for hit in result['hits']:
            grammar_check = self.check_grammar(
                target, 
                hit['expected'],
                hit['found']
            )
            if not grammar_check['valid']:
                result['grammar_errors'].append({
                    'term': hit['term'],
                    'issue': grammar_check['issue'],
                    'suggestion': grammar_check['suggestion']
                })
        
        return result
```

### 5.3 大包处理脚本 ⭐ NEW
```python
# batch_processor.py
# 大语言包拆分与拼合

python batch_processor.py \
  --input translation.xlsx \
  --action split \
  --chunk-size 100 \
  --output-dir ./chunks/

# 处理完成后拼合
python batch_processor.py \
  --action merge \
  --input-dir ./chunks/processed/ \
  --output translation_final.xlsx
```

### 5.4 AI审校脚本
```python
# ai_reviewer.py
# 输入: 问题文本块
# 输出: ai_review.json

python ai_reviewer.py \
  --input chunk_001.json \
  --model cursor-agent \
  --prompt prompts/quality_check.txt \
  --output ai_review.json
```

### 5.5 自动修复脚本
```python
# apply_fixes.py
# 输入: final_fixes.json (确认的问题清单)
# 输出: translation_fixed.xlsx

python apply_fixes.py \
  --input translation.xlsx \
  --fixes final_fixes.json \
  --output translation_fixed.xlsx \
```

---

## 六、下一步行动

**等待提供**：
1. **AI粗翻术语表**样本（Excel格式）
2. **UI字符长度限制**（如有）
3. **Critical错误处理策略**：自动阻断 vs 人工确认？
4. **质检报告格式偏好**：Markdown / JSON / 飞书表格？

**我立即开始**：
1. 编写 `pre_checker.py` 规则预检脚本（含术语双层校验）
2. 编写 `batch_processor.py` 大包拆分拼合脚本
3. 设计检测规则（变量完整性、术语双层校验、格式检查）
4. 准备测试用例验证

**确认后即可启动开发**，预计3-4小时完成第一阶段脚本。

---

## 七、关键设计要点汇总

| 设计要点 | 实现方案 |
|----------|----------|
| 术语双层校验 | 命中检测 → 语法正确性检查 |
| 大包处理 | 拆分(100条/块) → 并行处理 → 拼合 |
| 零API成本 | Python本地脚本，Cursor按需触发 |
| 人机边界 | 术语标准化+终审人工，其余脚本 |
| 错误分级 | Critical/Major/Minor三级处理 |

---

*文档创建时间：2026-03-19 15:30*  
*术语双层校验设计：2026-03-19 15:54*  
*下次更新：确认术语表样本后*
