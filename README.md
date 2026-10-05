# Tabbit2API v3.0（定制版）

[![Docker](https://img.shields.io/badge/Docker-ready-blue.svg)](https://www.docker.com/)
[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-green.svg)](https://fastapi.tiangolo.com/)

**Tabbit2API** 将 Tabbit 浏览器网页端内部 API 转换为 **OpenAI Chat Completions** 和 **Anthropic Claude Messages** 兼容的标准化接口，让 WorkBuddy、Trae、CodeBuddy、Cherry Studio、Claude Code 等 AI Agent 无缝使用 Tabbit 的模型能力。

> 架构类型：Web 端反代方案（类 Pandora / ChatGPT-Next-Web）
> 支持站点：国际版 `web.tabbit.ai` + 国内版 `web.tabbit.com`（**运行时一键切换**）
> 本仓库是基于上游 [`hoinata/tabbit2api`](https://github.com/hoinata/tabbit2api) 的**定制版**，改动见下文「定制说明」。

---

## 🆕 相对上游的定制改动

本定制版在保留上游全部能力的基础上，新增/修正：

- **国际版 / 国内版双站点支持** —— 管理面板顶部一键切换 `web.tabbit.ai`（国际版，海外模型）/ `web.tabbit.com`（国内版，国产模型）。每个站点独立的模型目录与 Token 池，Token 与站点绑定，互不干扰。
- **端点按档位隔离** —— `/v1`（免费档：默认 + 免费计量）与 `/v3`（会员档：premium_only）分开暴露，跨档请求返回 400 并提示正确端点，避免误用。
- **模型列表实时获取** —— `/v1/models`、`/v3/models` 与管理面板均**实时**从上游拉取，不再依赖任何预置/硬编码列表（上游新增模型自动出现）。
- **统一默认模型 id 为 `default`** —— 修复上游因站点显示名（`Default` / `默认`）不同导致的 id 漂移；`best` / `最佳` / 空值均作为输入别名归一化为 `default`。
- **移除失效的 Google 登录按钮** —— 面板内置的 Google 快捷登录用的是第三方 client_id，必然 `origin_mismatch`，已移除并改为「粘贴 Token / 脚本导出」引导。
- **跨平台 Token 导出脚本** —— `tools/` 提供 macOS / Windows 自适应的 Token 导出与一键刷新脚本。
- **base_url 透传修复** —— 拉取模型目录时正确使用配置的 `base_url`（上游此 bug 会导致指定国际版域名时拉模型 422 / 列表为空）。
- **数据集分离（站点级）** —— Token 池、模型缓存按站点隔离。
- 管理面板版本号更新为 **v3.0**。

---

## ✨ 核心特性

- **双协议兼容** — OpenAI `/v1/chat/completions` + Claude `/v1/messages`
- **双站点切换** — 国际版 / 国内版，一套服务同时管理两套账号与模型
- **端点分档** — `/v1` 免费、`/v3` 会员，隔离清晰
- **实时模型目录** — 从上游 `/proxy/v1/model_config/models` 实时拉取
- **Premium 模型支持** — 会员档模型通过 v3 API 自动分流
- **Agent 级消息清洗** — 过滤伪请求（标题生成等），去重 system/tool 消息，从超长消息中提取 `<user_query>` 真实问题
- **上下文管理** — 滑动窗口 + Token 估算，防止上下文溢出
- **Token 池增强** — 加权轮询 + ACTIVE/COOLDOWN/BANNED 状态机 + 可选 Fernet 加密存储
- **Agent 模型路由** — 支持 `X-Agent-Phase` 头部按阶段选择不同模型
- **Tool Calling 支持** — 解析 OpenAI tools 定义，注入工具 prompt，检测工具调用输出
- **对话记忆** — Session 自动缓存，同一 API Key 共享 Tabbit room，保持上下文连续
- **永久会话** — 默认 TTL 7 天，用户可在管理面板管理所有活跃会话
- **固定绑定** — 可手动绑定 Tabbit room，实现真正的永久对话
- **并发锁** — asyncio 锁防止 409 冲突，请求排队
- **429 自动重试** — 触发限流后等待重试
- **管理面板** — 站点切换、模型管理、Token 管理（含站点列）、会话管理、Agent 状态监控、Settings 功能开关
- **Docker 一键部署**

---

## 🚀 快速开始

```bash
git clone <this-repo>
cd tabbit2api
docker compose up -d
```

服务默认监听 `http://localhost:8800`。

### 端口说明

| 地址 | 说明 |
|------|------|
| `http://localhost:8800/v1/chat/completions` | OpenAI 兼容端点（免费档） |
| `http://localhost:8800/v1/models` | 免费档模型列表（实时） |
| `http://localhost:8800/v3/chat/completions` | OpenAI 兼容端点（会员档） |
| `http://localhost:8800/v3/models` | 会员档模型列表（实时） |
| `http://localhost:8800/v1/messages` | Claude 兼容端点（免费档） |
| `http://localhost:8800/v3/messages` | Claude 兼容端点（会员档） |
| `http://localhost:8800/admin` | 管理面板（默认密码 `admin`） |
| `http://localhost:8800/health` | 健康检查 |

> `/models` 与 `/chat/completions` 为无前缀的兼容别名（等同 `/v1/*`）。
> 跨档调用会返回 `400`，例如用 `/v1` 调会员模型会提示「请使用 /v3 端点」。

### 添加 Tabbit Token

首次使用需为每个 Tabbit 账号添加一个 **Access Token**（管理面板 → Tokens 管理 → 添加 Token）。
获取方法见 **[TOKEN.md](./TOKEN.md)**（也可用 `tools/get_tabbit_token.mjs` 一键导出）。

> ⚠️ **Token 与站点绑定**：国际版账号导出的 Token 只能用于国际版站点，国内版同理。添加 Token 时请在表单里选对**站点**。

---

## 🌐 双站点（国际版 / 国内版）

Tabbit 有两个官方站点，按地区分发、内置模型不同：

| 站点 | 域名 | 模型目录 | 数据区域 |
|------|------|----------|----------|
| 国际版 | `web.tabbit.ai` | 海外模型（Claude / GPT / Gemini 等 30+） | 中国大陆以外 |
| 国内版 | `web.tabbit.com` | 国产模型（DeepSeek / GLM / Kimi / Qwen 等 20+） | 中国大陆 |

- 在**管理面板左上角**用站点切换器一键切换；切换后 `/v1`、`/v3` 的模型目录会随站点刷新。
- 每个站点的 Token 各自独立，`/api/admin/sites` 可查看各站点 Token 数与模型数。
- **同一个项目即可同时承载两个站点**：分别用两个站点登录的账号各导出一个 Token，在添加时选对站点即可。

---

## 📦 模型档位（实时目录）

端点按「档位」隔离，档位来自上游 `model_access_type` 字段：

| 档位 | 端点 | 说明 |
|------|------|------|
| `free_unlimited` | `/v1` | 默认模型（`default`），不消耗用量、无限使用 |
| `free_metered` | `/v1` | 免费但有倍率消耗 |
| `premium_only` | `/v3` | 会员专享 |

- 具体有哪些模型**完全以运行时实时拉取的目录为准**（`/v1/models`、`/v3/models`），本 README 不固定列表。
- 国际版与国内版的模型集合不同；切换站点后目录随之变化。
- 会员档模型需要**有会员的账号**；免费账号调用 premium 模型会被上游拒绝（`code 492`）。

---

## 🔌 API 使用

### OpenAI 兼容

```bash
# 免费档
curl http://localhost:8800/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-your-key" \
  -d '{"model": "default", "messages": [{"role": "user", "content": "你好！"}], "stream": true}'

# 会员档（需会员账号）
curl http://localhost:8800/v3/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-your-key" \
  -d '{"model": "<premium-model-id>", "messages": [{"role": "user", "content": "你好！"}], "stream": true}'
```

> `model` 可省略或填 `default`（默认模型）、`best`（`default` 的别名）；也可填 `/v1/models` 里的具体 id。

### Claude Code

```bash
export ANTHROPIC_BASE_URL=http://localhost:8800
export ANTHROPIC_API_KEY=any-key-here
claude
```

### Agent 集成

| 平台 | 配置 |
|------|------|
| WorkBuddy / Trae / CodeBuddy | OpenAI Compatible Provider，BASE_URL = `http://your-server:8800/v1`（会员档用 `/v3`） |
| Cherry Studio / ChatBox | 添加 OpenAI Provider |
| Claude Code | `ANTHROPIC_BASE_URL=http://your-server:8800` |

> 管理面板 Settings → 模型管理 → 点击「测试模型更新」→ 选择模型即可看到完整连接配置。

---

## 🎯 会话管理

| 机制 | 说明 |
|------|------|
| **自动缓存** | 同一 API Key + 模型自动共享 Tabbit room，保持对话记忆 |
| **永久会话** | 默认 TTL 7 天，room 在 Tabbit 对话列表中持久可见 |
| **固定绑定** | 手动绑定 Tabbit room → API Key，实现真正永久对话 |
| **并发锁** | 同 room 请求排队，防止 409 Conflict |
| **智能消息** | 自动过滤 WorkBuddy 标题生成指令，从超长消息提取真实问题 |
| **429 重试** | 触发限流后自动等待重试 |

### 会话管理面板

- **Sessions 页面**：查看所有活跃会话、请求次数、TTL 剩余时间
- **固定绑定**：输入 API Key + 模型 + Room ID，永久绑定
- **单个删除 / 全部清除**

---

## 🔧 配置

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| 服务地址 | `0.0.0.0:8800` | 监听地址与端口 |
| 激活站点 | `intl` | `intl`（国际版 `web.tabbit.ai`）/ `cn`（国内版 `web.tabbit.com`） |
| 站点域名 | 见 `tabbit.sites` | 每个站点的 `base_url`，可在面板修改 |
| API Key | 空 | 全局鉴权（可选） |
| 默认模型 | `default` | OpenAI / Claude 默认模型（`best` 为别名） |
| 会话缓存 | 启用 / 604800s TTL | 可关闭或调整 |

> 站点、Token 均可在**管理面板**中修改，无需手改 `config.json`。

### 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `TABBIT_SERVER_HOST` | 监听地址 | `0.0.0.0` |
| `TABBIT_SERVER_PORT` | 监听端口 | `8800` |
| `TABBIT_BASE_URL` | Tabbit 域名 | `https://web.tabbit.ai` |
| `TABBIT_CLIENT_ID` | 客户端 id | `2dd8eb4c1ed9c344d173` |
| `TABBIT_API_KEY` | 全局 API Key | 空 |
| `TABBIT_CLAUDE_DEFAULT_MODEL` | Claude 默认模型 | `default` |
| `TABBIT_OPENAI_DEFAULT_MODEL` | OpenAI 默认模型 | `default` |

### Agent 功能开关（管理面板 Settings 页面）

| 功能 | 说明 |
|------|------|
| **消息清洗** | 过滤伪请求、去重系统消息、提取 `<user_query>` |
| **上下文管理** | 滑动窗口截断，防止超长上下文 |
| **Token 池** | 多账户轮询 + 状态机健康管理 |
| **Agent 路由** | 按 Agent 阶段选择模型 |
| **Tool Calling** | 解析并注入工具定义 |

---

## 🏗️ 架构

```
Agent (WorkBuddy / Trae / CodeBuddy / Claude Code)
         │
         │ OpenAI / Claude API  (/v1 免费 · /v3 会员)
         ▼
    Tabbit2API (FastAPI :8800)
         │
         ├─ 站点路由 ─────────────┐
         │  ├─ 国际版 web.tabbit.ai │  ← 面板一键切换
         │  └─ 国内版 web.tabbit.com│
         │                          │
         ├─ Agent 模块 ─────────────┤
         │  ├─ Message Cleaner      │
         │  ├─ Context Manager      │
         │  ├─ Token Pool (站点级)   │
         │  ├─ Agent Router         │
         │  └─ Tool Handler         │
         │                          │
         ├─ 免费档 (/v1) → 上游 v1 API (/api/v1/chat/completion)
         │
         └─ 会员档 (/v3) → 上游 v3 API
               ├─ POST /panel/session
               ├─ GET  /session/{id}?_rsc
               ├─ POST /api/v3/chat/rooms/{id}/runs
               └─ POST /api/v3/chat/rooms/{id}/join (SSE)
```

---

## 🐳 Docker

```bash
docker compose up -d          # 启动
docker compose logs -f        # 日志
docker compose restart        # 重启
docker compose down && docker compose up -d --build  # 更新
```

> `config.json`（含 Token）已加入 `.dockerignore`，不会被打进镜像；数据通过卷 `/app/data` 持久化。

---

## 🛠️ 工具脚本（tools/）

| 脚本 | 用途 |
|------|------|
| `get_tabbit_token.mjs` | 跨平台（macOS / Windows）从本机已登录的 Tabbit 导出 Access Token |
| `login_and_get_token.mjs` | 打开可见窗口登录 Tabbit 并导出 Token（首次登录用） |
| `refresh_fnos_token.mjs` | 一键闭环：导出 Token → 登录面板 → 写入/更新 → 刷新模型 → 验证 |

需要 `node >= 18` 与 `playwright-core`。**在仓库目录**里安装并运行：

```bash
cd ~/tabbit2api                 # 先进仓库目录（重要：tools/ 是相对路径）
npm install                     # 装一次（package.json 已声明依赖）
node tools/get_tabbit_token.mjs # 导出 Token（先完全退出 Tabbit）
```

> 快捷命令：`npm run get-token` / `npm run login-and-get-token` / `npm run refresh-fnos-token`。
> 提示：`node tools/...` 是**相对路径**，只在你当前位于仓库目录时有效；也可用绝对路径 `node ~/tabbit2api/tools/get_tabbit_token.mjs`。
> 详细图文步骤见 **[TOKEN.md](./TOKEN.md)**（保姆级 SOP）。

---

## 📄 许可证

MIT License

---

## 🙏 致谢

上游项目：[`hoinata/tabbit2api`](https://github.com/hoinata/tabbit2api)。
本仓库为面向多站点（国际版 / 国内版）与端点分档的定制分支。
