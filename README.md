# Localization QA Workflow

> Game localization QA workflow for Excel language packs, AI draft review, terminology consistency, placeholder validation, and UI tag safety.

这是一个面向**游戏本地化团队**的质检工作流仓库，专门处理 **AI 粗翻后的 Excel 语言包**。它会自动检查变量占位符、UI 标签、术语一致性、格式模式和高风险翻译问题，并输出可复核的质检结果。

**Keywords:** game localization QA, localization workflow, Excel translation QA, terminology consistency, placeholder validation, UI tag validation, AI translation review, game LQA.

## Why This Project Exists

Most localization tools stop at translation or generic QA. This project focuses on the messy middle:

- AI draft output that still needs human review
- Excel-based language packs used by game teams
- Variables, BBCode, UI tags, and short UI strings that are easy to break
- Repeatable QA rules that can run before delivery instead of after bug reports

## 中文概述

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
├── tools/
│   └── codex-residential-launcher/  # Codex + Clash 住宅 IP 启动封装（见该目录 README）
├── output/                 # 输出目录
│   └── ai_review/          #   AI 审查结果
└── workflow-design.md      # 需求与设计文档
```

## 相关工具

- **[Codex + 固定住宅 IP（Clash Verge）完整落地指南](tools/codex-residential-launcher/README.md)**  
  Windows 下可用 **`tools/codex-residential-launcher/start-codex-desktop.cmd`**（根入口，路径自适应）或 `scripts\Start-CodexDesktop.cmd` 启动 Desktop；另有 CLI 脚本、Merge 模板、VS Code 代理说明与排障；可单独拷贝目录到其他机器复用。

## 文档

- [变更日志](CHANGELOG.md)
- [使用说明书](docs/使用说明书.md)
- [工作流说明](工作流说明.md)
- [工作流设计文档](workflow-design.md)

## 最新更新（2026-04-14）

本次更新把近期已经验证过的质量增强正式合入主工作流，重点是减少批次错配、拼音残留、占位符破坏和短 UI 文案超框风险。

### 已合入改动

- 严格 AI 审核链路
  - `prepare / merge` 以 manifest 和 fingerprint 绑定批次，避免输入输出词条错配
  - 模型回填必须逐条输出 `ID | KEEP` 或 `ID | FIX | corrected translation`，缺行或乱序会直接拒绝合并
- 工作区批处理入口
  - 支持按目录发现语言表和术语表，适合直接处理项目目录
- 拼音残留检测与自动修复
  - 能识别 `Hongshangu`、`Jushizhen`、`Meiguihu`、`Xigu...`、`Lanshidi` 这类专名拼音残留
  - 对已知地图名和地点名可直接按标准映射回写
- UI 短文案长度硬约束
  - 先把中文原文可见长度 `<= 10` 的短文本纳入候选
  - 再按类型分层处理：紧凑 UI 走硬约束，普通短文本走软提示，编号专名和复杂富文本豁免
  - 机审会新增 `ui_length_overflow`
  - AI 审核 prompt 会带上 `LEN:mode=...,source=...,target=...,budget<=...` 元数据，要求在自然可懂前提下尽量贴近中文长度

### 典型适用场景

- 游戏 UI 文案、按钮、标签、菜单项
- 地图名、地点名、编号地名
- 含变量、BBCode、换行和富文本标签的语言表

## 使用注意事项

### 1. 首跑建议走小批次

- 建议 `batch-size` 先用 `80` 到 `100`
- 第一轮优先稳定性，不优先吞吐量

### 2. `prepare` 和 `merge` 之间不要换输入文件

- 严格链路会校验输入指纹
- 如果语言表在两步之间被替换、重排或改动，`merge` 会拒绝回填

### 3. 短文本长度约束先入池，再分层

- 中文原文可见长度 `<= 10` 的文本会先进入长度检查候选池
- 其中紧凑 UI 文案是硬约束，普通短文本是软提示，编号专名和复杂富文本会豁免
- 完整句子仍然不适合用这条规则强压长度
- 规则优先级仍然是：自然可懂第一，长度第二

### 4. 专名和世界观名词要尽量进术语表

- 如果项目故意保留音译或有官方专名，不要只依赖内置规则
- 建议把标准译名补进术语表，避免被拼音残留规则或长度规则误判

### 5. 复杂富文本不要走激进自动修复

- 含大量 `[color]`、`[size]`、`[v0]`、`[b0]` 之类标签的行，优先保结构安全
- 模型和规则都必须保留占位符、标签和换行

### 6. 报告里重点关注这几类问题

- `romanized_name_residue`
- `ui_length_overflow`
- `variable_missing`
- `variable_extra`
- `term_missing`

## License

MIT
