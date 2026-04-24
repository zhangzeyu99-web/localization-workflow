# Codex + 固定住宅 IP（Clash Verge）完整落地指南

在 **Windows** 上，用 **Clash Verge** 的 **mixed-port + Merge 规则分流**，让 **OpenAI / ChatGPT / Claude** 相关域名从 **固定住宅 SOCKS5** 出口；**不开 TUN、不设系统代理**，其余流量 **DIRECT**，尽量不影响公司内网与普通浏览器。

**本目录可单独拷贝或从本仓库拉取后在其他机器复用。** 密钥只放本机，勿提交 Git。

---

## 目录

1. [目标与原则](#1-目标与原则)  
2. [前置条件](#2-前置条件)  
3. [Clash Verge：Merge 与端口](#3-clash-vergemerge-与端口)  
4. [本仓库脚本做什么](#4-本仓库脚本做什么)  
5. [自适应路径与快捷方式](#5-自适应路径与快捷方式)  
6. [新机落地步骤（复制即用）](#6-新机落地步骤复制即用)  
7. [Codex Desktop](#7-codex-desktop)  
8. [Codex CLI](#8-codex-cli)  
9. [VS Code 里的 Codex 扩展](#9-vs-code-里的-codex-扩展)  
10. [登录与令牌](#10-登录与令牌)  
11. [验证是否走住宅出口](#11-验证是否走住宅出口)  
12. [排障](#12-排障)  
13. [内地环境：链式代理（可选）](#13-内地环境链式代理可选)  
14. [仓库与许可](#14-仓库与许可)

---

## 1. 目标与原则

| 目标 | 做法 |
|------|------|
| Codex 访问 OpenAI 使用 **固定住宅 IP** | Clash Merge 里 SOCKS5 住宅节点 + 域名规则走 `AI-Services` |
| **不破坏公司网** | **不用 TUN**；不用 Windows「系统代理」全局开关；仅对 **从脚本启动的 Codex 进程树** 注入 `HTTPS_PROXY` |
| 可复现、可上 Git | 仓库只含 **示例配置**与脚本；**密码、真实 Merge、`.env` 不入库**（见 `.gitignore`） |

---

## 2. 前置条件

- Windows 10/11 或 Windows Server（能跑 Clash Verge 与 Codex）
- 已安装 **Clash Verge Rev**：[releases](https://github.com/clash-verge-rev/clash-verge-rev/releases)
- 已安装 **Codex Desktop** 与/或 **Codex CLI**（OpenAI 官方安装路径常见为 `%LOCALAPPDATA%\Programs\OpenAI\...`）
- 一条 **SOCKS5 住宅代理**（如 kookeey；HTTP 代理若仅有 SOCKS5，仍由 Clash 接 SOCKS5，本机 mixed-port 用 HTTP 即可）

---

## 3. Clash Verge：Merge 与端口

### 3.1 Merge 文件位置（常见）

将 `config/clash-merge.yaml.example` 复制为 Clash Verge 的 **Merge** 内容（在 UI 里编辑 Merge，或编辑生成目录下的 `profiles\Merge.yaml`，以你本机 Clash Verge 数据目录为准）。

常见数据目录：

`%APPDATA%\io.github.clash-verge-rev.clash-verge-rev\`

其中 `profiles\Merge.yaml` 会与订阅合并；**把 example 里的占位符改成你的住宅 SOCKS5**。

### 3.2 规则思路（与 example 一致）

- `DOMAIN-SUFFIX`：`openai.com`、`chatgpt.com`、`auth0.com`、Anthropic 等 → 走 `AI-Services`（住宅）
- **`MATCH,DIRECT`**：其余全部直连（公司网、普通浏览）

### 3.3 mixed-port

在 Clash Verge 设置里查看 **mixed-port**（常见 `7890` / `7897`）。**必须与** `.env` 里的 `CLASH_MIXED_PORT` 一致。

### 3.4 为何默认不用 TUN

TUN 在部分公司环境会劫持 DNS/路由导致内网异常。本方案用 **进程级 HTTP 代理** 只裹 Codex，风险更小。

---

## 4. 本仓库脚本做什么

| 文件 | 作用 |
|------|------|
| `start-codex-desktop.cmd`（**launcher 根目录**） | **推荐双击入口**：`%~dp0` 定位本目录，再调用 `scripts\Start-CodexDesktop.ps1 -KillExisting`；不依赖资源管理器「当前文件夹」 |
| `scripts/Start-CodexDesktop.ps1` | 未运行则启动 Clash；**等待 mixed-port 监听**；设置 `HTTPS_PROXY`/`HTTP_PROXY`；默认 `-KillExisting` 关掉旧 Desktop 再启动 |
| `scripts/Start-CodexDesktop.cmd` | 与根目录入口等价，仅路径少一层；同样用 `%~dp0` + `cd /d` 保证自适应 |
| `scripts/Start-CodexCLI.ps1` | 同上拉起 Clash + 代理，再执行 `codex.exe`，参数原样透传 |
| `env.example` | 复制为同目录 `.env` 填写路径与端口 |
| `config/clash-merge.yaml.example` | Merge 模板（**无真实密码**） |

**相对「手动开 Clash + 直接双击 Codex 图标」的优化**：等端口、关旧实例减 token 争用、路径可配置、文档可随仓库走。

---

## 5. 自适应路径与快捷方式

### 5.1 为何「拷到哪都能用」

- **批处理**里使用 `%~dp0`（本 `.cmd` 所在目录的绝对路径，**含末尾反斜杠**），再 `cd /d "%~dp0"`，避免从「开始 → 运行」或任务栏启动时 **当前工作目录** 落在 `System32` 等错误位置导致找不到相邻文件。
- **PowerShell**里 `$PSScriptRoot` 始终指向 **正在执行的 `.ps1` 所在目录**；`.env` 通过「`scripts` 的上一级 = launcher 根」解析，因此 **与仓库克隆在 `D:\`、`C:\Users\...\Desktop\` 或 U 盘路径无关**，只要保持目录结构不变即可。

### 5.2 `.env` 应放哪里

将 `env.example` 复制为 **`codex-residential-launcher\.env`**（与 `env.example`、`start-codex-desktop.cmd` 同级，**不要**放进 `scripts\`）。`Start-CodexDesktop.ps1` / `Start-CodexCLI.ps1` 会读取该文件。

### 5.3 两个 `.cmd` 入口（任选其一）

| 入口 | 适用 |
|------|------|
| **`start-codex-desktop.cmd`**（launcher 根目录） | 少进一层文件夹，适合固定到任务栏 / 发快捷方式给同事 |
| **`scripts\Start-CodexDesktop.cmd`** | 习惯所有脚本都在 `scripts\` 下时使用 |

二者逻辑一致；**Windows 不区分大小写**，仓库内 PascalCase 文件名与你在别处习惯的小写写法可视为同一文件类入口。

### 5.4 快捷方式建议

- **目标**：填 **带引号的完整路径**，例如 `"D:\project\localization-workflow-project\tools\codex-residential-launcher\start-codex-desktop.cmd"`（路径含空格时必须加引号）。
- **起始位置**：可留空，或填 launcher 根目录；**不影响**脚本内对 `.ps1` / `.env` 的解析（由 `%~dp0` / `$PSScriptRoot` 决定）。

---

## 6. 新机落地步骤（复制即用）

1. **Clone 或拷贝**本仓库中的 `tools/codex-residential-launcher/` 到目标机任意路径。  
2. 安装 **Clash Verge**、**Codex**（路径非默认则后面 `.env` 写绝对路径）。  
3. 按 [§3](#3-clash-vergemerge-与端口) 配置 **Merge**（住宅 SOCKS5 + AI 域名规则 + `MATCH,DIRECT`），重载配置。  
4. 在 launcher 根目录执行 `copy env.example .env`，编辑 `.env`：`CLASH_VERGE_EXE`、`CLASH_MIXED_PORT`，必要时 `CODEX_DESKTOP_EXE` / `CODEX_CLI_EXE`。  
5. **桌面版**：双击根目录 **`start-codex-desktop.cmd`**，或双击 **`scripts\Start-CodexDesktop.cmd`**。  
6. **CLI**：在 launcher 根打开终端：`powershell -ExecutionPolicy Bypass -File .\scripts\Start-CodexCLI.ps1`（可加 `exec "..."` 等参数）。

---

## 7. Codex Desktop

- **Electron 主进程**（`Codex.exe`）可能仍有直连（更新、遥测等），**一般不影响 OpenAI 主链路**。  
- 真正调模型的是子进程 **`resources\codex.exe`**：会继承启动脚本设置的 **`HTTPS_PROXY`**，从而连接 **`http://127.0.0.1:<mixed-port>`** → Clash 规则 → 住宅出口。  
- **不要**只从开始菜单/桌面快捷方式直接点 Codex（除非该快捷方式已改为调用本仓库 **`start-codex-desktop.cmd`** 或 **`scripts\Start-CodexDesktop.cmd`**），否则子进程**可能**不带代理。

---

## 8. Codex CLI

- 使用 `scripts\Start-CodexCLI.ps1`，或在同一 PowerShell 会话中手动：

  ```powershell
  $env:HTTPS_PROXY="http://127.0.0.1:7897"
  $env:HTTP_PROXY="http://127.0.0.1:7897"
  & "$env:LOCALAPPDATA\Programs\OpenAI\Codex\bin\codex.exe" @args
  ```

- 端口以你 `.env` / Clash 实际为准。

---

## 9. VS Code 里的 Codex 扩展

扩展 Marketplace ID 一般为 **`openai.chatgpt`**（即 Codex 相关能力）。在 **用户级** `settings.json` 中建议：

```json
{
  "http.proxy": "http://127.0.0.1:7897",
  "http.proxyStrictSSL": false,
  "http.proxySupport": "on",
  "chatgpt.cliPath": "C:\\Users\\<你>\\AppData\\Local\\Programs\\OpenAI\\Codex\\bin\\codex.exe"
}
```

路径与端口按本机修改；**先启动 Clash Verge** 再开 VS Code。

---

## 10. 登录与令牌

| 场景 | 建议 |
|------|------|
| **设备码登录** `codex login --device-auth` | 使用 **直连**（不设 `HTTPS_PROXY`），避免住宅 IP 对 `auth.openai.com` **429 Too Many Requests** |
| **`refresh token was already used`** | 多实例（Desktop + CLI + VS Code）**并发刷新**同一 `~/.codex\auth.json` 会导致；先 **关 Desktop**，再 `codex logout` 后重新 `login --device-auth`，最后再开 Desktop |
| 凭据文件 | `%USERPROFILE%\.codex\auth.json`（勿上传） |

---

## 11. 验证是否走住宅出口

1. Clash 已运行、Merge 已加载。  
2. **不设代理**的终端：`curl https://httpbin.org/ip` → 应为你本机/公司出口（如香港 IDC）。  
3. **走代理**的终端：`curl -x http://127.0.0.1:<PORT> https://api.openai.com/v1/models -H "Authorization: Bearer test"` → 期望 **HTTP 401** JSON（说明到达 OpenAI API，而非被墙 HTML）。

---

## 12. 排障

| 现象 | 可能原因 | 处理 |
|------|-----------|------|
| Codex 仍提示 IP/地区 | 未走 Clash 或规则未命中 | 用本仓库 **cmd/ps1** 启动 Desktop；检查 Merge 域名与 `MATCH` 顺序 |
| 公司网上不去 | 曾开 TUN 或系统代理 | 关闭 TUN；关闭系统代理；仅用脚本注入进程代理 |
| Desktop 子进程无 `127.0.0.1:7897` 连接 | 未通过脚本启动 | 改用根目录 **`start-codex-desktop.cmd`** 或 **`scripts\Start-CodexDesktop.cmd`**（见 [§5](#5-自适应路径与快捷方式)） |
| OpenClaw / 其它工具 WebSocket 500 | `chatgpt.com/backend-api` 与 curl 不同，Cloudflare 策略更严 | 见各产品文档；本仓库仅解决 **经 Clash 的 HTTP(S) 出口 IP** |
| `git push` 凭据异常 | 与 Codex 无关 | 使用 `gh auth login` 或 PAT |

---

## 13. 内地环境：链式代理（可选）

若本机 **无法直连** 住宅 SOCKS5 出口，需在 Merge 里为住宅节点配置 **`dialer-proxy`**（先走机场/出境节点，再连住宅）。参见 [Clash Verge 链式代理文档](https://www.clashverge.dev/guide/proxy_chain.html)。

---

## 14. 仓库与许可

- 脚本与文档以 **MIT** 随仓库发布（若根仓库另有协议，以根仓库为准）。  
- Clash Verge、Codex、住宅 IP 服务商条款各自遵守。

---

## 一键链接（本仓库路径）

本工具在 monorepo 中的路径：**`tools/codex-residential-launcher/`**  
根目录说明见仓库 **`README.md`** 中的「相关工具」一节。
