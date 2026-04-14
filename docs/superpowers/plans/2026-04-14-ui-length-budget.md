# UI Length Budget Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 UI / 按钮 / 标签 / 短词组增加长度硬约束，并把长度预算注入 AI 审核 prompt。

**Architecture:** 新增独立的 UI 长度预算检查模块，先在机审阶段标记 `ui_length_overflow`，再在 AI prompt 中注入预算元数据，最后在 AI 回填后重新校验。该设计复用现有 `ui_detector`、`process_language` 和 `ai_checker` 链路，不改动长句文案处理逻辑。

**Tech Stack:** Python, pandas, openpyxl, unittest

---

### Task 1: 新增 UI 长度预算检查器

**Files:**
- Create: `C:\Users\Administrator\Desktop\localization-workflow-remote\utils\ui_length_checker.py`
- Test: `C:\Users\Administrator\Desktop\localization-workflow-remote\tests\test_ui_length_checker.py`

- [ ] 写失败测试：覆盖短 UI、完整句子、超预算和预算内样例
- [ ] 运行测试确认失败
- [ ] 实现最小长度预算判定
- [ ] 运行测试确认通过

### Task 2: 把长度问题接入机审状态

**Files:**
- Modify: `C:\Users\Administrator\Desktop\localization-workflow-remote\process_language.py`
- Test: `C:\Users\Administrator\Desktop\localization-workflow-remote\tests\test_process_language.py`

- [ ] 写失败测试：UI 短文案超预算时生成 `ui_length_overflow`
- [ ] 运行测试确认失败
- [ ] 接入长度检查，写入 `state.issues`、`needs_human_review`、`ai_suggestion`
- [ ] 运行测试确认通过

### Task 3: 把预算信息注入 AI prompt

**Files:**
- Modify: `C:\Users\Administrator\Desktop\localization-workflow-remote\utils\ai_checker.py`
- Test: `C:\Users\Administrator\Desktop\localization-workflow-remote\tests\test_ai_review_protocol.py`

- [ ] 写失败测试：主审 prompt 包含 UI 长度规则说明和 `LEN` 元数据
- [ ] 运行测试确认失败
- [ ] 修改 prompt 生成逻辑
- [ ] 运行测试确认通过

### Task 4: 完整验证

**Files:**
- Modify: `C:\Users\Administrator\Desktop\localization-workflow-remote\docs\superpowers\specs\2026-04-14-ui-length-budget-design.md`

- [ ] 运行 `python -m unittest discover -s tests -p 'test_*.py'`
- [ ] 运行 `python -m py_compile process_language.py utils\\ai_checker.py utils\\ui_length_checker.py`
- [ ] 用真实语言表生成 prompt 和结果，检查是否出现 `ui_length_overflow`
- [ ] 整理测试输出给用户判断是否合并
