# Localization QA Workflow

> 游戏本地化质检工作流 — AI 粗翻后的人机协作质检工具

## 概述

面向游戏本地化场景的自动化质检工具，处理 AI 粗翻后的语言包（Excel 格式），自动检测变量占位符、UI 标记、术语一致性等问题，输出质检报告。

## 功能

| 模块 | 说明 |
|------|------|
| **变量检测** | 检查翻译中变量占位符（`{0}`, `%s` 等）是否完整 |
| **UI 标记检测** | 检查 UI 控件标记（`<color>`, `<size>` 等）是否匹配 |
| **术语一致性** | 基于术语库检查关键术语翻译是否一致 |
| **格式模式检测** | 检测数字格式、标点、空格等模式问题 |
| **AI 审查** | 调用 LLM 对可疑条目进行二次审查 |
| **GUI 界面** | 可视化操作界面，支持拖放 Excel 文件 |

## 支持语言

| 优先级 | 语言 |
|--------|------|
| P0 | 英语 |
| P1 | 法语、德语、土耳其语、西班牙语、葡萄牙语、俄语 |

## 安装

```bash
pip install -r requirements.txt
```

## 使用

```bash
# CLI 模式
python cli.py --input <excel_file> --language en

# GUI 模式
python gui.py

# 处理单个语言
python process_language.py --input <excel_file> --lang en
```

## 项目结构

```text
localization-workflow-project/
├── cli.py                  # 命令行入口
├── gui.py                  # GUI 入口（Tkinter）
├── process_language.py     # 语言处理主逻辑
├── requirements.txt        # Python 依赖
├── utils/                  # 工具模块
│   ├── ai_checker.py       #   AI 审查器
│   ├── excel_reader.py     #   Excel 读取器
│   ├── pattern_detector.py #   格式模式检测
│   ├── term_checker.py     #   术语一致性检查
│   ├── ui_detector.py      #   UI 标记检测
│   └── variable_checker.py #   变量占位符检查
├── docs/
│   └── 使用说明书.md        # 详细使用文档
├── output/                 # 输出目录
│   └── ai_review/          #   AI 审查结果
└── workflow-design.md      # 需求与设计文档
```

## 文档

- [使用说明书](docs/使用说明书.md)
- [工作流设计文档](workflow-design.md)

## License

MIT
