# Tabbit2API

[![Docker](https://img.shields.io/badge/Docker-ready-blue.svg)](https://www.docker.com/)
[![Python](https://img.shields.io/badge/Python-3.11-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110-green.svg)](https://fastapi.tiangolo.com/)

**Tabbit2API** 是一个非官方的 API 适配器，将 **Tabbit 浏览器网页端**的内部 API 转换为与 **OpenAI** 和 **Anthropic Claude** 兼容的标准化接口。

> **类型**：Web 端反代方案（类似 Pandora、ChatGPT-Next-Web）
>
> **支持域名**：`web.tabbit.com`
>
> **已测试 Agent**：WorkBuddy、Trae、CodeBuddy、Cherry Studio

## ✨ 核心功能

- **双协议兼容**：OpenAI (`/v1/chat/completions`) + Claude (`/v1/messages`)
- **Premium 模型支持**：Kimi-K3 等付费模型通过 v3 API 自动分流
- **对话记忆**：Session 缓存机制，同一 API Key 共享 Tabbit room 保持上下文
- **并发锁**：asyncio 锁防止 409 冲突，请求排队保证数据一致性
- **429 自动重试**：触发限流后自动等待重试
- **多账户 Token 池**：轮询负载均衡 + 智能健康管理
- **Web 管理面板**：Token 管理、会话监控、日志查看、配置修改
- **流式 & 非流式**：完整支持 SSE streaming
- **Docker 部署**：一键启动

## 🚀 快速开始

### Docker Compose（推荐）

```bash
cd /home/tabbit
docker compose up -d
```

服务监听 `http://localhost:8800`。

### 本地 Python

```bash
pip install -r requirements.txt
python tabbit2api.py
```

### 访问

| 地址 | 说明 |
|------|------|
| `http://localhost:8800/v1/chat/completions` | OpenAI 兼容 API |
| `http://localhost:8800/v1/messages` | Claude 兼容 API |
| `http://localhost:8800/admin` | 管理面板（默认密码 `admin`） |
| `http://localhost:8800/health` | 健康检查 |

## 📦 支持的模型

| 模型 ID | 显示名称 | 类型 | 说明 |
|---------|----------|------|------|
| `best` | 最佳 | Free | 默认模式，不消耗用量 |
| `kimi-k3` | Kimi-K3 | Premium | Kimi 最强旗舰，1M 上下文 |
| `longcat-2-0` | LongCat-2.0 | Free | 美团最新旗舰，1M 上下文 |
| `glm-5-2` | GLM-5.2 | Free | 智谱最新文本模型 |
| `qwen3-7-max` | Qwen3.7-Max | Free | 阿里千问旗舰文本模型 |
| `kimi-k2-7-code` | Kimi-K2.7-Code | Free | 旗舰多模态 Coding 模型 |
| `deepseek-v4-pro` | DeepSeek-V4-Pro | Free | DeepSeek 旗舰 Pro |
| `deepseek-v4-flash` | DeepSeek-V4-Flash | Free | DeepSeek 旗舰 Flash |
| `doubao-seed-2-1-pro` | Doubao-Seed-2.1-Pro | Free | 字节旗舰多模态 Pro |
| `doubao-seed-2-1-turbo` | Doubao-Seed-2.1-Turbo | Free | 字节旗舰多模态 Turbo |
| `minimax-m3` | MiniMax-M3 | Free | MiniMax 原生多模态 |
| `glm-5-1` | GLM-5.1 | Free | 智谱文本模型 |
| `glm-5v-turbo` | GLM-5V-Turbo | Free | 智谱多模态 |
| `kimi-k2-6` | Kimi-K2.6 | Free | Moonshot 旗舰多模态 |
| `kimi-k2-5` | Kimi-K2.5 | Free | Moonshot 旗舰多模态 |
| `minimax-m2-7` | MiniMax-M2.7 | Free | MiniMax 文本模型 |
| `doubao-seed-2-0-lite` | Doubao-Seed-2.0-lite | Free | 豆包多模态 |
| `qwen3-5-plus` | Qwen3.5-Plus | Free | 千问原生多模态 |
| `longcat-flash-chat` | LongCat-Flash-Chat | Free | 美团旗舰 |
| `longcat-flash-thinking` | LongCat-Flash-Thinking | Free | 美团旗舰思考模型 |

> Premium 模型自动走 v3 API，Free 模型走 v1 API。

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

### Claude 兼容

```bash
curl http://localhost:8800/v1/messages \
  -H "Content-Type: application/json" \
  -H "anthropic-version: 2023-06-01" \
  -d '{
    "model": "claude-sonnet-4-6",
    "messages": [{"role": "user", "content": "你好！"}],
    "stream": true
  }'
```

## 🎯 Agent 集成

### WorkBuddy / Trae / CodeBuddy 配置

1. 添加自定义 OpenAI 兼容 API Provider
2. **API Base URL**: `http://your-server:8800/v1`
3. **API Key**: 留空或填写 `proxy.api_key`
4. 添加模型：`kimi-k3`、`deepseek-v4-pro` 等

### 对话记忆机制

| 机制 | 说明 |
|------|------|
| Session 缓存 | 同一 API Key + 模型共享一个 Tabbit room，保持上下文连续 |
| 并发锁 | 同 room 请求排队执行，防止 409 冲突 |
| TTL | 默认 30 分钟无请求后自动创建新 room |
| 429 重试 | 触发限流后自动等待 15 秒重试 |

> **注意**：Agent 发来的 messages 数组包含完整历史是正常的（OpenAI API 标准行为）。我们只取 system prompt + 最后一条 user 消息发给 Tabbit，room 自动维护对话历史。

### 管理面板功能

- **Dashboard**：服务状态概览
- **Tokens**：添加/管理 Tabbit 账户 Token
- **Sessions**：查看/删除活跃会话，监控请求次数
- **Settings**：配置 base_url、默认模型、会话缓存策略
- **Logs**：请求日志与错误追踪

## 🔧 配置说明

### 主要配置项

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `tabbit.base_url` | `https://web.tabbit.com` | Tabbit 域名 |
| `tabbit.client_id` | `2dd8eb4c1ed9c344d173` | 客户端标识 |
| `proxy.api_key` | 空 | 全局 API Key |
| `openai.default_model` | `best` | OpenAI 默认模型 |
| `claude.default_model` | `best` | Claude 默认模型 |
| `logging.max_entries` | 500 | 最大日志条数 |

### 会话缓存配置（管理面板 Settings 中可调）

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `session.enabled` | `true` | 启用会话缓存 |
| `session.ttl_seconds` | `1800` | 会话过期时间（秒） |

### 环境变量

| 环境变量 | 说明 | 默认值 |
|----------|------|--------|
| `TABBIT_SERVER_HOST` | 监听地址 | `0.0.0.0` |
| `TABBIT_SERVER_PORT` | 监听端口 | `8800` |
| `TABBIT_BASE_URL` | Tabbit 域名 | `https://web.tabbit.com` |
| `TABBIT_CLIENT_ID` | 客户端标识 | `2dd8eb4c1ed9c344d173` |
| `TABBIT_API_KEY` | 全局 API Key | 空 |
| `TABBIT_OPENAI_DEFAULT_MODEL` | OpenAI 默认模型 | `best` |
| `TABBIT_CLAUDE_DEFAULT_MODEL` | Claude 默认模型 | `best` |

## 🐳 Docker 部署

```bash
# 启动
docker compose up -d

# 查看日志
docker compose logs -f

# 重启
docker compose restart

# 更新
docker compose down && docker compose up -d --build
```

### Nginx 反向代理

```nginx
server {
    listen 80;
    server_name api.your-domain.com;

    location / {
        proxy_pass http://localhost:8800;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_http_version 1.1;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 300s;
    }
}
```

## 🏗️ 架构

```
Agent (WorkBuddy/Trae/CodeBuddy)
         │
         │ OpenAI Chat Completions API
         ▼
    Tabbit2API (FastAPI)
         │
         ├─ Free 模型 → v1 API (/api/v1/chat/completion)
         │
         └─ Premium 模型 → v3 API
               ├─ POST /panel/session (创建 room)
               ├─ GET /session/{id}?_rsc (RSC 初始化)
               ├─ POST /api/v3/chat/rooms/{id}/runs (发送消息)
               └─ POST /api/v3/chat/rooms/{id}/join (SSE 流接收)
```

## 📄 许可证

MIT License

## 🙏 参考

本项目参考了 [hih24337/tabb2](https://github.com/hih24337/tabb2) 的设计思路。
