"""
Claude Messages API 路由 (/v1/messages)
为 Claude Code 提供 Anthropic Messages API 兼容端点。
"""

import json
import time
import uuid
import math
import logging

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import StreamingResponse

from core.config import ConfigManager
from core.tabbit_client import TabbitClient, MODEL_MAP, get_model_access_type, TIERS_FREE, TIERS_PREMIUM
from core.token_manager import TokenManager
from core.log_store import LogStore, LogEntry
from core.claude_compat import (
    random_trigger_signal,
    map_claude_to_content,
    normalize_blocks,
    estimate_tokens,
    ToolifyParser,
    ClaudeSSEWriter,
)

logger = logging.getLogger("tabbit2openai")

router = APIRouter()

_tm: TokenManager | None = None
_cfg: ConfigManager | None = None
_logs: LogStore | None = None
_fallback_clients: dict[str, TabbitClient] = {}

# Session cache for Claude API
_claude_session_cache: dict[str, dict] = {}
CLAUDE_SESSION_TTL = 1800  # 30 minutes

# Claude 模型名 → Tabbit 模型名映射
CLAUDE_MODEL_MAP = {
    "claude-opus-4-6": "kimi-k3",
    "claude-opus-4-5": "kimi-k3",
    "claude-opus-4-1": "kimi-k3",
    "claude-sonnet-4-6": "deepseek-v4-pro",
    "claude-sonnet-4-5": "deepseek-v4-pro",
    "claude-sonnet-4-1": "deepseek-v4-pro",
    "claude-haiku-4-5": "doubao-seed-2-1-turbo",
    "claude-3-5-sonnet": "qwen3-7-max",
    "claude-3-5-haiku": "doubao-seed-2-1-turbo",
}


def init(token_manager: TokenManager, config: ConfigManager, log_store: LogStore):
    global _tm, _cfg, _logs
    _tm = token_manager
    _cfg = config
    _logs = log_store


def _tier_allows(tier: str, model_id: str) -> bool:
    at = get_model_access_type(model_id)
    if tier == "premium":
        return at in TIERS_PREMIUM
    return (at in TIERS_FREE) or (not at)


def _resolve_tabbit_model(model: str, tier: str = "free") -> tuple[str, str]:
    """将请求中的模型名映射到 (model_id, display_name)，并按端点档位校验。"""
    # 归一化默认模型别名：best / 默认 → default
    if model in ("best", "默认"):
        model = "default"
    # 精确匹配
    if model in MODEL_MAP:
        mid = model
    else:
        mid = None
        # Claude 模型名映射
        for prefix, target in CLAUDE_MODEL_MAP.items():
            if model.startswith(prefix):
                mid = target
                break
        if mid is None:
            # 从 config 中读取默认模型
            default = _cfg.get("claude", "default_model") if _cfg else None
            if default in ("best", "默认"):
                default = "default"
            mid = default if (default and default in MODEL_MAP) else "default"
    if mid == "best":
        mid = "default"
    if not _tier_allows(tier, mid):
        if tier == "premium":
            raise HTTPException(400, f"模型 '{mid}' 属于免费档（默认/倍率），请使用 /v1/messages 端点")
        raise HTTPException(400, f"模型 '{mid}' 属于会员档（需付费/会员），请使用 /v3/messages 端点")
    return mid, MODEL_MAP.get(mid, "最佳")


async def _get_client_and_token(
    request: Request,
) -> tuple[TabbitClient, str, str]:
    """获取客户端实例，返回 (client, token_name, token_id)"""
    # 验证客户端 API key
    api_key = _cfg.get("proxy", "api_key") if _cfg else ""
    auth_header = request.headers.get("x-api-key") or request.headers.get(
        "authorization", ""
    )
    bearer = auth_header.replace("Bearer ", "") if auth_header.startswith("Bearer ") else auth_header

    if _tm and _tm.has_tokens:
        if api_key and bearer != api_key:
            raise HTTPException(status_code=401, detail="invalid api key")
        token_info, client = await _tm.get_next()
        if token_info is None:
            raise HTTPException(
                status_code=503, detail="no available tokens (all cooling down)"
            )
        return client, token_info.get("name", "unknown"), token_info["id"]

    # fallback
    token = bearer
    if not token:
        raise HTTPException(status_code=401, detail="missing token")
    if token not in _fallback_clients:
        _fallback_clients[token] = TabbitClient(
            token,
            _cfg.get_active_base_url() if _cfg else None,
            _cfg.get("tabbit", "client_id") if _cfg else None,
        )
    return _fallback_clients[token], "bearer", ""


def _estimate_input_tokens(body: dict) -> int:
    """估算输入 token 数"""
    total_text = ""
    # system
    system = body.get("system")
    if system:
        if isinstance(system, str):
            total_text += system
        elif isinstance(system, list):
            for b in system:
                if isinstance(b, dict):
                    total_text += b.get("text", "")
    # messages
    for msg in body.get("messages", []):
        content = msg.get("content", "")
        if isinstance(content, str):
            total_text += content
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    total_text += block.get("text", "")
                    total_text += block.get("thinking", "")
                    total_text += str(block.get("content", ""))
    # tools
    tools = body.get("tools", [])
    if tools:
        total_text += json.dumps(tools, ensure_ascii=False)

    return estimate_tokens(total_text)


async def _stream_claude_response(
    client: TabbitClient,
    session_id: str,
    content: str,
    tabbit_model: str,
    body: dict,
    token_name: str,
    token_id: str,
    use_v3: bool = False,
):
    """流式生成 Claude SSE 响应"""
    request_id = uuid.uuid4().hex[:12]
    model = body.get("model", "claude-proxy")
    input_tokens = _estimate_input_tokens(body)

    writer = ClaudeSSEWriter(request_id, model, input_tokens)

    # 解析器配置
    tools = body.get("tools", [])
    has_tools = len(tools) > 0
    trigger_signal = body.get("_trigger_signal")  # 在调用前注入
    thinking_enabled = (
        body.get("thinking", {}).get("type") == "enabled"
        if isinstance(body.get("thinking"), dict)
        else False
    )
    parser = ToolifyParser(trigger_signal, thinking_enabled)

    # message_start
    yield writer.init_event()

    start_time = time.time()
    error_msg = ""

    try:
        event_gen = client.send_message_v3(session_id, content, tabbit_model) if use_v3 else client.send_message(session_id, content, tabbit_model)
        async for event in event_gen:
            et = event["event"]
            ed = event["data"]

            if et == "error":
                error_msg = ed.get("message", str(ed))
                break

            if et == "message_chunk" and "content" in ed:
                text = ed["content"]
                for char in text:
                    parser.feed_char(char)
                    events = parser.consume_events()
                    if events:
                        for line in writer.handle_events(events):
                            yield line
            elif et in ("message_finish", "finish"):
                break

        # 流结束
        parser.finish()
        final_events = parser.consume_events()
        if final_events:
            for line in writer.handle_events(final_events):
                yield line

        if token_id and _tm:
            _tm.report_success(token_id)

    except Exception as e:
        error_msg = str(e)
        if token_id and _tm:
            _tm.report_error(token_id)
        # 尝试发送错误后仍然关闭流
        parser.finish()
        final_events = parser.consume_events()
        if final_events:
            for line in writer.handle_events(final_events):
                yield line
    finally:
        duration = time.time() - start_time
        if _logs:
            _logs.add(
                LogEntry(
                    model=body.get("model", "unknown"),
                    token_name=token_name,
                    stream=True,
                    status="success" if not error_msg else "error",
                    duration=duration,
                    error=error_msg,
                )
            )


@router.post("/v1/messages")
async def claude_messages_v1(request: Request):
    return await _claude_messages(request, tier="free")


@router.post("/v3/messages")
async def claude_messages_v3(request: Request):
    return await _claude_messages(request, tier="premium")


async def _claude_messages(request: Request, tier: str = "free"):
    """Anthropic Messages API 兼容端点（按端点档位区分）"""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid JSON body")

    # 获取客户端
    client, token_name, token_id = await _get_client_and_token(request)

    # 模型映射（含档位校验）
    model_id, tabbit_model = _resolve_tabbit_model(body.get("model", "default"), tier=tier)

    # Check if premium model
    from routes.openai_compat import _is_premium_model
    use_v3 = _is_premium_model(model_id)

    # Session cache: get bearer for cache key
    auth_header = request.headers.get("x-api-key") or request.headers.get("authorization", "")
    bearer = auth_header.replace("Bearer ", "") if auth_header.startswith("Bearer ") else auth_header
    cache_key = f"{bearer}:{model_id}"
    cached = _claude_session_cache.get(cache_key)
    
    if cached and time.time() - cached["created_at"] < CLAUDE_SESSION_TTL:
        session_id = cached["session_id"]
        logger.info(f"Claude reusing cached session {session_id}")
    else:
        try:
            session_id = await client.create_chat_session()
            _claude_session_cache[cache_key] = {"session_id": session_id, "created_at": time.time()}
            logger.info(f"Claude created new session {session_id}")
        except Exception as e:
            if token_id and _tm:
                _tm.report_error(token_id)
            raise HTTPException(status_code=502, detail=f"Session creation failed: {e}")

    # 工具调用准备
    tools = body.get("tools", [])
    trigger_signal = random_trigger_signal() if tools else None
    body["_trigger_signal"] = trigger_signal

    # 注入全局 Claude system prompt
    claude_system_prompt = _cfg.get("claude", "system_prompt") if _cfg else ""
    if claude_system_prompt:
        body["_injected_system_prompt"] = claude_system_prompt

    # 构建发送内容
    content = map_claude_to_content(body, trigger_signal)

    # Claude Code 总是 stream
    is_stream = body.get("stream", True)
    if is_stream:
        return StreamingResponse(
            _stream_claude_response(
                client, session_id, content, tabbit_model, body, token_name, token_id, use_v3=use_v3
            ),
            media_type="text/event-stream",
            headers={
                "cache-control": "no-cache",
                "connection": "keep-alive",
            },
        )

    # 非流式（少见，但仍支持）
    request_id = uuid.uuid4().hex[:12]
    model = body.get("model", "claude-proxy")
    input_tokens = _estimate_input_tokens(body)
    full_text = ""
    start_time = time.time()
    error_msg = ""

    try:
        if use_v3:
            async for event in client.send_message_v3(session_id, content, tabbit_model):
                et, ed = event["event"], event["data"]
                if et == "error":
                    error_msg = ed.get("message", str(ed))
                    break
                if et == "message_chunk" and "content" in ed:
                    full_text += ed["content"]
        else:
            async for event in client.send_message(session_id, content, tabbit_model):
                if event["event"] == "message_chunk":
                    full_text += event["data"].get("content", "")
        if token_id and _tm and not error_msg:
            _tm.report_success(token_id)
    except Exception as e:
        error_msg = str(e)
        if token_id and _tm:
            _tm.report_error(token_id)
        raise HTTPException(status_code=502, detail=str(e))
    finally:
        duration = time.time() - start_time
        if _logs:
            _logs.add(
                LogEntry(
                    model=model,
                    token_name=token_name,
                    stream=False,
                    status="success" if not error_msg else "error",
                    duration=duration,
                    error=error_msg,
                )
            )

    output_tokens = estimate_tokens(full_text)
    return {
        "id": f"msg_{request_id}",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": [{"type": "text", "text": full_text}],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        },
    }


@router.post("/v1/messages/count_tokens")
async def count_tokens(request: Request):
    """Token 计数端点"""
    return await _count_tokens(request)


@router.post("/v3/messages/count_tokens")
async def count_tokens_v3(request: Request):
    return await _count_tokens(request)


async def _count_tokens(request: Request):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid JSON body")

    input_tokens = _estimate_input_tokens(body)
    return {"input_tokens": input_tokens}
