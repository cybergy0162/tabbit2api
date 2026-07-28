# Tabbit2API v2.0

[![Docker](https://img.shields.io/badge/Docker-ready-blue.svg)](https://www.docker.com/)
[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-green.svg)](https://fastapi.tiangolo.com/)

**Tabbit2API** 将 Tabbit 浏览器网页端内部 API 转换为 **OpenAI Chat Completions** 和 **Anthropic Claude Messages** 兼容的标准化接口，让任意支持自定义 API 的 AI Agent（WorkBuddy、Trae、CodeBuddy、Cherry Studio 等）都能使用 Tabbit 的模型能力。

> 架构类型：Web 端反代方案（类 Pandora / ChatGPT-Next-Web）  
> 支持域名：`web.tabbit.com`

## ✨ v2.0 新特性

- **Premium 模型支持** — Kimi-K3 等付费模型通过 v3 API 自动分流
- **对话记忆** — Session 缓存，同一 API Key 共享 Tabbit room，保持上下文连续
- **并发锁** — asyncio 锁防止 409 冲突，请求排队保证数据一致
- **429 自动重试** — 触发限流后等待重试
- **智能消息发送** — 只提取最后一条 user 消息，不重复拼接历史，解决超长消息截断问题
- **模型管理面板** — 一键拉取最新模型列表，实时标注 PRO/免费，选中后自动生成连接配置
- **连接配置预览** — 根据访问来源自动判断 localhost 或公网 IP，展示 OpenAI / Claude 完整配置
- **会话管理** — 实时查看/删除活跃会话，可配置 TTL 和开关
- **Token 池** — 多账户轮询负载均衡 + 智能健康管理

## 🚀 快速开始

### Docker（推荐）

```bash
cd /path/to/tabbit2api
docker compose up -d
```

服务默认监听 `http://localhost:8800`。

### 本地 Python

```bash
pip install -r requirements.txt
python tabbit2api.py
```

### 端口说明

| 地址 | 说明 |
|------|------|
| `http://localhost:8800/v1/chat/completions` | OpenAI 兼容端点 |
| `http://localhost:8800/v1/messages` | Claude 兼容端点 |
| `http://localhost:8800/v1/models` | 模型列表 |
| `http://localhost:8800/admin` | 管理面板（默认密码 `admin`） |
| `http://localhost:8800/health` | 健康检查 |

## 📦 模型列表（20 个）

| 模型 ID | 名称 | 类型 | 说明 |
|---------|------|------|------|
| `best` | 最佳 | 免费 | 默认模式，不消耗用量 |
| `kimi-k3` | Kimi-K3 | **PRO** | Kimi 最强旗舰，1M 上下文 |
| `longcat-2-0` | LongCat-2.0 | 免费 | 美团最新旗舰，1M 上下文 |
| `glm-5-2` | GLM-5.2 | 免费 | 智谱最新文本模型 |
| `qwen3-7-max` | Qwen3.7-Max | 免费 | 阿里千问旗舰文本 |
| `kimi-k2-7-code` | Kimi-K2.7-Code | 免费 | 旗舰多模态 Coding |
| `deepseek-v4-pro` | DeepSeek-V4-Pro | 免费 | DeepSeek 旗舰 Pro |
| `deepseek-v4-flash` | DeepSeek-V4-Flash | 免费 | DeepSeek 旗舰 Flash |
| `doubao-seed-2-1-pro` | Doubao-Seed-2.1-Pro | 免费 | 字节旗舰多模态 Pro |
| `doubao-seed-2-1-turbo` | Doubao-Seed-2.1-Turbo | 免费 | 字节旗舰多模态 Turbo |
| `minimax-m3` | MiniMax-M3 | 免费 | MiniMax 原生多模态 |
| `glm-5-1` | GLM-5.1 | 免费 | 智谱文本模型 |
| `glm-5v-turbo` | GLM-5V-Turbo | 免费 | 智谱多模态 |
| `kimi-k2-6` | Kimi-K2.6 | 免费 | Moonshot 旗舰多模态 |
| `kimi-k2-5` | Kimi-K2.5 | 免费 | Moonshot 旗舰多模态 |
| `minimax-m2-7` | MiniMax-M2.7 | 免费 | MiniMax 文本模型 |
| `doubao-seed-2-0-lite` | Doubao-Seed-2.0-lite | 免费 | 豆包多模态 |
| `qwen3-5-plus` | Qwen3.5-Plus | 免费 | 千问原生多模态 |
| `longcat-flash-chat` | LongCat-Flash-Chat | 免费 | 美团旗舰 |
| `longcat-flash-thinking` | LongCat-Flash-Thinking | 免费 | 美团旗舰思考模型 |

> PRO 模型自动走 v3 API（`/api/v3/chat/rooms/{id}/runs`），免费模型走 v1 API（`/api/v1/chat/completion`）。

## 🔌 API 使用

### OpenAI 兼容

```bash
curl http://localhost:8800/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-your-key" \
  -d '{
    "model": "kimi-k3",
    "messages": [{"role": "user", "content": "你好！"}],
    "stream": true
  }'
```

### Claude Code

```bash
export ANTHROPIC_BASE_URL=http://localhost:8800
export ANTHROPIC_API_KEY=any-key-here
claude
```

### 在 Agent 中配置

| 平台 | 配置方式 |
|------|----------|
| WorkBuddy / Trae / CodeBuddy | 添加 OpenAI 兼容 Provider，BASE_URL = `http://your-server:8800/v1` |
| Cherry Studio / ChatBox | 添加 OpenAI Provider，同上 |
| Claude Code | `ANTHROPIC_BASE_URL=http://your-server:8800` |

> 在管理面板 Settings → 模型管理 → 点击"测试模型更新" → 选择模型即可看到完整的连接配置。

## 🎯 对话记忆机制

| 机制 | 说明 |
|------|------|
| Session 缓存 | 同一 API Key + 模型共享 Tabbit room，上下文连续 |
| 并发锁 | 同 room 请求排队，防止 409 Conflict |
| TTL | 默认 30 分钟无请求后自动创建新 room |
| 消息发送 | 只提取 system prompt + 最后一条 user 消息，不重复拼接历史 |
| 429 重试 | 触发限流后自动等待 15 秒重试 |

## 🔧 配置

### 主要配置（管理面板 Settings）

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| 服务地址 | `0.0.0.0:8800` | 监听地址与端口 |
| Tabbit 域名 | `https://web.tabbit.com` | API 目标域名 |
| Client ID | `2dd8eb4c1ed9c344d173` | 客户端标识 |
| API Key | 空 | 全局 API Key（可选鉴权） |
| 会话缓存 | 启用 / 1800s TTL | 可关闭或调整过期时间 |

### 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `TABBIT_SERVER_PORT` | 监听端口 | `8800` |
| `TABBIT_BASE_URL` | Tabbit 域名 | `https://web.tabbit.com` |
| `TABBIT_API_KEY` | 全局 API Key | 空 |

## 🏗️ 架构

```
Agent (WorkBuddy/Trae/CodeBuddy)
         │
         │ OpenAI / Claude API
         ▼
    Tabbit2API (FastAPI :8800)
         │
         ├─ 免费模型 → v1 API
         │     └─ POST /api/v1/chat/completion
         │
         └─ PRO 模型 → v3 API
               ├─ POST /panel/session     (创建 room)
               ├─ GET  /session/{id}?_rsc (RSC 初始化)
               ├─ POST /api/v3/chat/rooms/{id}/runs (发送消息)
               └─ POST /api/v3/chat/rooms/{id}/join (SSE 流接收)
```

## 🐳 Docker 部署

```bash
# 启动
docker compose up -d

# 日志
docker compose logs -f tabbit2api

# 更新
docker compose down && docker compose up -d --build
```

### Nginx 反代（可选）

```nginx
server {
    listen 80;
    server_name api.your-domain.com;
    location / {
        proxy_pass http://localhost:8800;
        proxy_set_header Host $host;
        proxy_http_version 1.1;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 300s;
    }
}
```

## 📄 许可证

MIT License
