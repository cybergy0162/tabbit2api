import json
import time
import uuid
import logging
import asyncio
from typing import Any, Optional, List, Dict

from fastapi import APIRouter, HTTPException, Header, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

import core.tabbit_client as tabbit_client
from core.tabbit_client import TabbitClient
from core.tabbit_client import get_model_access_type, MODEL_META, TIERS_FREE, TIERS_PREMIUM
from core.token_manager import TokenManager
from core.log_store import LogStore, LogEntry
from core.config import ConfigManager

# Agent modules (optional, enabled via config)
from core.agent.message_cleaner import build_agent_content
from core.agent.context_manager import SlidingWindow, ContextCompressor, estimate_tokens
from core.agent.agent_router import ModelSelector
from core.agent.tool_handler import (
    parse_openai_tools, build_tool_prompt, detect_tool_call,
    build_openai_tool_response, add_tool_call, get_tool_chain, clear_tool_chain,
)

logger = logging.getLogger("tabbit2openai")

router = APIRouter()

_tm: TokenManager | None = None
_cfg: ConfigManager | None = None
_logs: LogStore | None = None
_fallback_clients: dict[str, TabbitClient] = {}

# Session cache: key = (bearer_token, model_id) -> {"session_id": str, "created_at": float, "use_v3": bool, "last_used": float, "request_count": int}
_session_cache: dict[str, dict] = {}
SESSION_TTL = 604800  # 7 days — effectively permanent, user manages via admin panel
SESSION_ENABLED = True  # configurable

# Fixed session bindings: key = (bearer_token, model_id) -> room_id (manually set, never expires)
_fixed_sessions: dict[str, str] = {}

# Per-session locks to prevent concurrent runs (avoids 409 Conflict)
_session_locks: dict[str, asyncio.Lock] = {}


def get_session_list() -> list:
    """Return all active sessions for admin display."""
    result = []
    now = time.time()
    for key, entry in _session_cache.items():
        parts = key.split(":", 1)
        bearer = parts[0] if len(parts) > 0 else ""
        model_id = parts[1] if len(parts) > 1 else ""
        result.append({
            "cache_key": key,
            "api_key_preview": (bearer[:12] + "...") if len(bearer) > 12 else bearer,
            "model_id": model_id,
            "session_id": entry.get("session_id", ""),
            "created_at": entry.get("created_at", 0),
            "last_used": entry.get("last_used", entry.get("created_at", 0)),
            "request_count": entry.get("request_count", 0),
            "ttl_remaining": max(0, int(SESSION_TTL - (now - entry.get("created_at", 0)))),
            "use_v3": entry.get("use_v3", False),
        })
    # Add fixed bindings
    for key, room_id in _fixed_sessions.items():
        parts = key.split(":", 1)
        bearer = parts[0] if len(parts) > 0 else ""
        model_id = parts[1] if len(parts) > 1 else ""
        result.append({
            "cache_key": key,
            "api_key_preview": (bearer[:12] + "...") if len(bearer) > 12 else bearer,
            "model_id": model_id,
            "session_id": room_id,
            "created_at": 0,
            "last_used": 0,
            "request_count": 0,
            "ttl_remaining": -1,  # -1 = 永久
            "use_v3": False,
            "fixed": True,
        })
    return sorted(result, key=lambda x: x["last_used"], reverse=True)


def delete_session(cache_key: str) -> bool:
    """Delete a session by cache_key. Returns True if found."""
    if cache_key in _session_cache:
        del _session_cache[cache_key]
        return True
    return False


def clear_all_sessions():
    _session_cache.clear()


def _session_key(bearer: str, model_id: str) -> str:
    return f"{bearer}:{model_id}"


def _get_cached_session(bearer: str, model_id: str) -> Optional[str]:
    """Return cached session_id if valid, else None.
    Priority: fixed binding > auto-cached session."""
    sk = _session_key(bearer, model_id)
    
    # 1) Fixed binding (manually set, never expires)
    if sk in _fixed_sessions:
        return _fixed_sessions[sk]
    
    # 2) Auto-cached session (TTL-based)
    if not SESSION_ENABLED:
        return None
    entry = _session_cache.get(sk)
    if entry and time.time() - entry["created_at"] < SESSION_TTL:
        entry["last_used"] = time.time()
        entry["request_count"] = entry.get("request_count", 0) + 1
        return entry["session_id"]
    return None


def set_fixed_session(bearer: str, model_id: str, room_id: str):
    """Manually bind a Tabbit room to an API Key + model."""
    _fixed_sessions[_session_key(bearer, model_id)] = room_id


def remove_fixed_session(bearer: str, model_id: str) -> bool:
    """Remove a fixed binding. Returns True if found."""
    sk = _session_key(bearer, model_id)
    if sk in _fixed_sessions:
        del _fixed_sessions[sk]
        return True
    return False


def get_fixed_sessions() -> dict:
    """Return all fixed bindings."""
    return dict(_fixed_sessions)


def get_session_list() -> list:
    """Return all active sessions for admin display."""
    result = []
    now = time.time()
    for key, entry in _session_cache.items():
        parts = key.split(":", 1)
        bearer = parts[0] if len(parts) > 0 else ""
        model_id = parts[1] if len(parts) > 1 else ""
        result.append({
            "cache_key": key,
            "api_key_preview": (bearer[:12] + "...") if len(bearer) > 12 else bearer,
            "model_id": model_id,
            "session_id": entry.get("session_id", ""),
            "created_at": entry.get("created_at", 0),
            "last_used": entry.get("last_used", entry.get("created_at", 0)),
            "request_count": entry.get("request_count", 0),
            "ttl_remaining": max(0, int(SESSION_TTL - (now - entry.get("created_at", 0)))),
            "use_v3": entry.get("use_v3", False),
            "fixed": False,
        })
    # Add fixed bindings
    for key, room_id in _fixed_sessions.items():
        parts = key.split(":", 1)
        bearer = parts[0] if len(parts) > 0 else ""
        model_id = parts[1] if len(parts) > 1 else ""
        result.append({
            "cache_key": key,
            "api_key_preview": (bearer[:12] + "...") if len(bearer) > 12 else bearer,
            "model_id": model_id,
            "session_id": room_id,
            "created_at": 0,
            "last_used": 0,
            "request_count": 0,
            "ttl_remaining": -1,
            "use_v3": False,
            "fixed": True,
        })
    return sorted(result, key=lambda x: x["last_used"], reverse=True)


def _cache_session(bearer: str, model_id: str, session_id: str, use_v3: bool):
    _session_cache[_session_key(bearer, model_id)] = {
        "session_id": session_id,
        "created_at": time.time(),
        "last_used": time.time(),
        "request_count": 0,
        "use_v3": use_v3,
    }


def _invalidate_session(bearer: str, model_id: str):
    _session_cache.pop(_session_key(bearer, model_id), None)


def _get_session_lock(session_id: str) -> asyncio.Lock:
    """Get or create a per-session async lock to serialize runs."""
    if session_id not in _session_locks:
        _session_locks[session_id] = asyncio.Lock()
    return _session_locks[session_id]


def init(token_manager: TokenManager, config: ConfigManager, log_store: LogStore):
    global _tm, _cfg, _logs
    _tm = token_manager
    _cfg = config
    _logs = log_store


import re

def _clean_text(text: str) -> str:
    text = re.sub(r'<system-reminder>.*?</system-reminder>', '', text, flags=re.DOTALL)
    text = re.sub(r'<user_input>.*?</user_input>', '', text, flags=re.DOTALL)
    text = re.sub(r'<env>.*?</env>', '', text, flags=re.DOTALL)
    text = re.sub(r'<task_list>.*?</task_list>', '', text, flags=re.DOTALL)
    text = re.sub(r'<tool_list>.*?</tool_list>', '', text, flags=re.DOTALL)
    text = re.sub(r'<tool_call>.*?</tool_call>', '', text, flags=re.DOTALL)
    text = re.sub(r'<tool_result>.*?</tool_result>', '', text, flags=re.DOTALL)
    text = re.sub(r'<function_calls>.*?</function_calls>', '', text, flags=re.DOTALL)
    text = re.sub(r'<task_type>.*?</task_type>', '', text, flags=re.DOTALL)
    text = re.sub(r'<goal>.*?</goal>', '', text, flags=re.DOTALL)
    text = re.sub(r'<thought>.*?</thought>', '', text, flags=re.DOTALL)
    text = re.sub(r'<content>.*?</content>', '', text, flags=re.DOTALL)
    
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'\n+', '\n', text)
    text = re.sub(r'^\s+|\s+$', '', text)
    
    return text

def _normalize_content(content) -> str:
    if isinstance(content, str):
        return _clean_text(content)
    elif isinstance(content, list):
        result = ""
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text":
                    result += _clean_text(item.get("text", ""))
                elif item.get("type") == "image_url":
                    result += f"[Image: {item.get('image_url', {}).get('url', '')}]"
                else:
                    result += _clean_text(str(item.get("content", "")))
            else:
                result += _clean_text(str(item))
        return result.strip()
    return _clean_text(str(content))


class ChatMessageContentPart(BaseModel):
    type: str
    text: Optional[str] = None
    image_url: Optional[Dict[str, str]] = None


class ChatMessage(BaseModel):
    role: str
    content: str | List[ChatMessageContentPart]


class ToolChoice(BaseModel):
    type: str = "function"
    function: Optional[dict] = None


class Tool(BaseModel):
    type: str = "function"
    function: dict


class ChatCompletionRequest(BaseModel):
    model: Optional[str] = None
    messages: List[ChatMessage]
    stream: bool = False
    max_tokens: Optional[int] = None
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    n: Optional[int] = 1
    stop: Optional[List[str]] = None
    presence_penalty: Optional[float] = None
    frequency_penalty: Optional[float] = None
    logit_bias: Optional[Dict[str, float]] = None
    user: Optional[str] = None
    tools: Optional[List[Tool]] = None
    tool_choice: Optional[Any] = None  # "auto", "none", {"type":"function","function":{"name":"xxx"}}


class SimpleChatRequest(BaseModel):
    role: str = "user"
    content: Any


MAX_CONTENT_LENGTH = 8000
MAX_MESSAGES = 6

def _build_content(messages: List[ChatMessage]) -> str:
    system_prompt = _cfg.get("proxy", "system_prompt") if _cfg else ""
    
    recent_messages = messages[-MAX_MESSAGES:]
    
    parts = []
    if system_prompt:
        parts.append(f"[System]: {system_prompt}")
    
    for m in recent_messages:
        label = {"user": "User", "assistant": "Assistant", "system": "System"}.get(
            m.role, m.role.capitalize()
        )
        parts.append(f"[{label}]: {_normalize_content(m.content)}")
    
    full_content = "\n\n".join(parts) + "\n\n[Assistant]:"
    
    if len(full_content) > MAX_CONTENT_LENGTH:
        logger.warning(f"Content too long ({len(full_content)} chars), truncating to {MAX_CONTENT_LENGTH}")
        # Keep system prompt + last N messages, drop middle ones
        keep_last = min(len(recent_messages), 3)  # keep at most last 3 messages
        kept_messages = recent_messages[-keep_last:]
        parts = []
        if system_prompt:
            parts.append(f"[System]: {system_prompt}")
        for m in kept_messages:
            label = {"user": "User", "assistant": "Assistant", "system": "System"}.get(
                m.role, m.role.capitalize()
            )
            content_str = _normalize_content(m.content)
            # Truncate each message to avoid single message dominating
            max_per_msg = MAX_CONTENT_LENGTH // max(keep_last, 1)
            if len(content_str) > max_per_msg:
                content_str = content_str[:max_per_msg] + "..."
            parts.append(f"[{label}]: {content_str}")
        full_content = "\n\n".join(parts) + "\n\n[Assistant]:"
        if len(full_content) > MAX_CONTENT_LENGTH:
            full_content = full_content[:MAX_CONTENT_LENGTH]
    
    return full_content


def _extract_bearer_token(authorization: str | None) -> str:
    if not authorization:
        return ""
    token = authorization.strip()
    for prefix in ["Bearer ", "Bearer=", "bearer ", "bearer=", "Bearar ", "bearar="]:
        if token.startswith(prefix):
            return token[len(prefix):]
    return token


async def _get_client_and_token(authorization: str | None) -> tuple[TabbitClient, str, str]:
    if _tm.has_tokens:
        api_key = _cfg.get("proxy", "api_key")
        if api_key:
            bearer = _extract_bearer_token(authorization)
            if bearer != api_key:
                raise HTTPException(status_code=401, detail="invalid api key")
        token_info, client = await _tm.get_next()
        if token_info is None:
            raise HTTPException(status_code=503, detail="no available tokens (all cooling down)")
        return client, token_info.get("name", "unknown"), token_info["id"]

    token = _extract_bearer_token(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="missing token")
    if token not in _fallback_clients:
        _fallback_clients[token] = TabbitClient(
            token,
            _cfg.get_active_base_url(),
            _cfg.get("tabbit", "client_id"),
        )
    return _fallback_clients[token], "bearer", ""


def _get_model_access_type(model_id: str) -> str:
    """Return the access_type for a given model_id (live from upstream meta)."""
    return get_model_access_type(model_id)


def _is_premium_model(model_id: str) -> bool:
    return _get_model_access_type(model_id) == "premium_only"


# ── 端点档位（分档隔离）──
# /v1 = 默认 + 免费计量；/v3 = 会员档
def _tier_allows(tier: str, model_id: str) -> bool:
    at = _get_model_access_type(model_id)
    if tier == "premium":
        return at in TIERS_PREMIUM
    # tier == "free"：默认(免费无限) + 免费计量 + 默认模型别名
    return (at in TIERS_FREE) or (not at)


def _resolve_tier(tier: str, model_id: str) -> str:
    """按端点档位归一化模型 id；不允许的档位报错。
    - 空 model → 本端默认（free 端用 default，premium 端用 premium 档第一个可用模型）
    - '/v1 传会员模型' → 400（引导去 /v3）
    - /v3 传免费模型 → 400（引导去 /v1）
    - 别名 best / '默认模型' id 统一归一化为 default
    """
    norm = (model_id or "").lower().strip()
    if not norm or norm in ("best", "默认"):
        norm = "default"
    if norm not in tabbit_client.MODEL_MAP:
        # 空 model：premium 端取该档第一个可用模型
        if tier == "premium":
            for mid in tabbit_client.MODEL_MAP.keys():
                if _tier_allows("premium", mid):
                    return mid
        return "default"
    if not _tier_allows(tier, norm):
        if tier == "premium":
            raise HTTPException(
                status_code=400,
                detail=f"模型 '{norm}' 属于免费档（默认/倍率），请使用 /v1 端点",
            )
        raise HTTPException(
            status_code=400,
            detail=f"模型 '{norm}' 属于会员档（需付费/会员），请使用 /v3 端点",
        )
    return norm


async def _stream_handler(client, session_id, content, tabbit_model, req_model, completion_id, token_name, token_id, use_v3=False):
    start = time.time()
    error_msg = ""
    try:
        yield f"data: {json.dumps({'id': completion_id, 'object': 'chat.completion.chunk', 'choices': [{'index': 0, 'delta': {'role': 'assistant', 'content': ''}, 'finish_reason': None}]})}\n\n"

        if use_v3:
            async for event in client.send_message_v3(session_id, content, tabbit_model):
                et, ed = event["event"], event["data"]
                if et == "error":
                    error_msg = ed.get("message", str(ed))
                    yield f"data: {json.dumps({'id': completion_id, 'object': 'chat.completion.chunk', 'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'stop'}]})}\n\n"
                    yield "data: [DONE]\n\n"
                    return
                if et == "message_chunk":
                    if "content" in ed:
                        chunk = {
                            "id": completion_id,
                            "object": "chat.completion.chunk",
                            "choices": [{"index": 0, "delta": {"content": ed["content"]}, "finish_reason": None}],
                        }
                        yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
                elif et == "finish":
                    yield f"data: {json.dumps({'id': completion_id, 'object': 'chat.completion.chunk', 'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'stop'}]})}\n\n"
        else:
            async for event in client.send_message(session_id, content, tabbit_model):
                et, ed = event["event"], event["data"]
                if et == "message_chunk" and "content" in ed:
                    chunk = {
                        "id": completion_id,
                        "object": "chat.completion.chunk",
                        "choices": [{"index": 0, "delta": {"content": ed["content"]}, "finish_reason": None}],
                    }
                    yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
                elif et in ("message_finish", "finish"):
                    yield f"data: {json.dumps({'id': completion_id, 'object': 'chat.completion.chunk', 'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'stop'}]})}\n\n"

        yield "data: [DONE]\n\n"
        if token_id:
            _tm.report_success(token_id)
    except Exception as e:
        error_msg = str(e)
        if token_id:
            _tm.report_error(token_id)
        raise
    finally:
        duration = time.time() - start
        _logs.add(LogEntry(
            model=req_model, token_name=token_name, stream=True,
            status="success" if not error_msg else "error",
            duration=duration, error=error_msg
        ))


@router.post("/v1/chat/completions")
async def chat_completions_v1(
    req: ChatCompletionRequest | SimpleChatRequest, authorization: str = Header(None)
):
    return await _chat_completions(req, authorization, tier="free")


@router.post("/v3/chat/completions")
async def chat_completions_v3(
    req: ChatCompletionRequest | SimpleChatRequest, authorization: str = Header(None)
):
    return await _chat_completions(req, authorization, tier="premium")


async def _chat_completions(
    req: ChatCompletionRequest | SimpleChatRequest,
    authorization: str | None,
    tier: str = "free",
):
    try:
        client, token_name, token_id = await _get_client_and_token(authorization)
    except HTTPException as e:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error")
    
    try:
        if isinstance(req, SimpleChatRequest):
            model_id = "default"
            tabbit_model = "最佳"
            content = _normalize_content(req.content)
        else:
            raw_model = (req.model or _cfg.get("openai", "default_model", default="default")) if _cfg else (req.model or "default")
            model_id = _resolve_tier(tier, raw_model)

            # Agent router: detect phase and potentially remap model
            agent_config = _cfg.get("agent", default={}) if _cfg else {}
            if agent_config.get("router", {}).get("enabled", False):
                selector = ModelSelector()
                model_id = _resolve_tier(tier, selector.resolve(model_id))

            tabbit_model = tabbit_client.MODEL_MAP.get(model_id, model_id)

            # Agent message cleaner
            if agent_config.get("cleaner", {}).get("enabled", False):
                bearer = _extract_bearer_token(authorization) if authorization else ""
                # Use per-request session key to avoid stale dedup cache
                dedup_key = f"{bearer}:{model_id}:{int(time.time())}"
                content = build_agent_content(
                    [{"role": m.role, "content": _normalize_content(m.content)} for m in req.messages],
                    dedup_session=dedup_key,
                )
            else:
                # Legacy content building (kept for backward compatibility)
                import re as _re
                last_user = ""
                for m in reversed(req.messages):
                    if m.role == "user":
                        raw_str = m.content if isinstance(m.content, str) else str(m.content)
                        # IMPORTANT: extract <user_query> BEFORE _clean_text() strips XML tags
                        match = _re.search(r'<user_query>(.*?)</user_query>', raw_str, _re.DOTALL)
                        if match:
                            last_user = match.group(1).strip()
                        else:
                            raw = _normalize_content(m.content)
                            if len(raw) > 2000:
                                lines = raw.strip().split('\n')
                                meaningful = []
                                for line in reversed(lines):
                                    line = line.strip()
                                    if not line:
                                        continue
                                    if len(line) > 200 or line.startswith(('OS Version:', 'Shell:', 'Workspace:', 'Current date:', '<system-reminder', '</system-reminder>', '```')):
                                        continue
                                    meaningful.insert(0, line)
                                    if len('\n'.join(meaningful)) > 500:
                                        break
                                last_user = '\n'.join(meaningful) if meaningful else raw[-500:]
                            else:
                                last_user = raw
                        break
                system_msgs = []
                for m in req.messages:
                    if m.role == "system":
                        content_str = _normalize_content(m.content)
                        if 'isNewTopic' in content_str or 'Generate a concise' in content_str or 'sentence-case title' in content_str or 'Respond with EXACTLY one JSON object' in content_str:
                            continue
                        if len(content_str) > 2000:
                            continue
                        system_msgs.append(content_str)
                if system_msgs:
                    content = "\n\n".join(system_msgs) + "\n\n" + last_user
                else:
                    content = last_user
            
            # Tool calling: inject tool prompt if tools are present
            if not isinstance(req, SimpleChatRequest) and req.tools and agent_config.get("tools", {}).get("enabled", False):
                tools_parsed = parse_openai_tools([t.model_dump() for t in req.tools])
                tool_prompt = build_tool_prompt(tools_parsed)
                if tool_prompt:
                    content = tool_prompt + "\n\n" + content
            logger.info(f"[DEBUG] Final content ({len(content)} chars): {content[:300]}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail="Invalid request format")
    
    use_v3 = _is_premium_model(model_id)
    is_stream = getattr(req, 'stream', False)
    
    # Session cache: reuse session for same API key + model
    bearer = _extract_bearer_token(authorization) if authorization else ""
    cached_session = _get_cached_session(bearer, model_id)
    
    if cached_session:
        session_id = cached_session
        logger.info(f"Reusing cached session {session_id} for model {model_id}")
    else:
        try:
            session_id = await client.create_chat_session()
            _cache_session(bearer, model_id, session_id, use_v3)
            logger.info(f"Created new session {session_id} for model {model_id}")
        except Exception as e:
            if token_id:
                _tm.report_error(token_id)
            _logs.add(LogEntry(
                model=getattr(req, 'model', 'unknown'), token_name=token_name,
                stream=is_stream, status="error", error=str(e)
            ))
            raise HTTPException(status_code=502, detail=f"Failed to create chat session: {e}")
    
    completion_id = f"chatcmpl-{uuid.uuid4().hex}"
    
    if is_stream:
        # Serialize concurrent requests to same session via async lock
        lock = _get_session_lock(session_id)
        async def locked_stream():
            async with lock:
                async for chunk in _stream_handler(
                    client, session_id, content, tabbit_model, getattr(req, 'model', 'unknown'),
                    completion_id, token_name, token_id, use_v3=use_v3
                ):
                    yield chunk
        return StreamingResponse(locked_stream(), media_type="text/event-stream")
    
    start = time.time()
    full_text = ""
    error_msg = ""
    
    async def _do_chat(sid):
        nonlocal full_text, error_msg
        if use_v3:
            async for event in client.send_message_v3(sid, content, tabbit_model):
                et, ed = event["event"], event["data"]
                if et == "error":
                    error_msg = ed.get("message", str(ed))
                    logger.warning(f"[DEBUG] V3 error: {error_msg}")
                    break
                if et == "message_chunk" and "content" in ed:
                    full_text += ed["content"]
        else:
            async for event in client.send_message(sid, content, tabbit_model):
                et = event["event"]
                ed = event["data"]
                if et == "message_chunk":
                    full_text += ed.get("content", "")
                elif et == "error":
                    error_msg = ed.get("message", str(ed))
                    logger.warning(f"[DEBUG] V1 error: code={ed.get('code')} msg={error_msg}")
                elif et not in ("message_chunk",):
                    logger.info(f"[DEBUG] V1 event: {et} data_keys={list(ed.keys()) if isinstance(ed, dict) else str(ed)[:100]}")
        logger.info(f"[DEBUG] _do_chat result: full_text_len={len(full_text)} error_msg={error_msg[:200] if error_msg else 'None'}")
    
    try:
        # Serialize requests to the same session to avoid 409 Conflict
        lock = _get_session_lock(session_id)
        async with lock:
            await _do_chat(session_id)
        
        # Auto-retry: if session failed (e.g. expired), create new one
        if error_msg and cached_session:
            logger.warning(f"Session {session_id} failed: {error_msg}, retrying with new session")
            _invalidate_session(bearer, model_id)
            new_sid = await client.create_chat_session()
            _cache_session(bearer, model_id, new_sid, use_v3)
            full_text = ""
            error_msg = ""
            lock2 = _get_session_lock(new_sid)
            async with lock2:
                await _do_chat(new_sid)
        
        if token_id and not error_msg:
            _tm.report_success(token_id)
    except Exception as e:
        error_msg = str(e)
        if token_id:
            _tm.report_error(token_id)
        _logs.add(LogEntry(
            model=getattr(req, 'model', 'unknown'), token_name=token_name,
            stream=False, status="error", error=error_msg
        ))
        raise HTTPException(status_code=502, detail=str(e))
    
    duration = time.time() - start
    _logs.add(LogEntry(
        model=getattr(req, 'model', 'unknown'), token_name=token_name,
        stream=False, status="success" if not error_msg else "error", duration=duration, error=error_msg
    ))

    input_tokens = len(content) // 4
    output_tokens = len(full_text) // 4

    return {
        "id": completion_id,
        "object": "chat.completion",
        "created": int(time.time()),
        "model": getattr(req, 'model', 'unknown'),
        "choices": [{"index": 0, "message": {"role": "assistant", "content": full_text}, "finish_reason": "stop"}],
        "usage": {
            "prompt_tokens": input_tokens,
            "completion_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens
        }
    }




def _build_model_list(tier: str) -> list:
    models = []
    for model_id, model_name in tabbit_client.MODEL_MAP.items():
        if not _tier_allows(tier, model_id):
            continue
        meta = MODEL_META.get(model_id, {})
        models.append({
            "id": model_id,
            "object": "model",
            "created": 1714502400,
            "owned_by": "tabbit",
            "name": model_name,
            "description": meta.get("description") or f"Tabbit model: {model_name}",
            "max_tokens": 128000,
            "supports_streaming": True,
            "supports_vision": meta.get("supports_vision", True),
            "access_type": _get_model_access_type(model_id),
            "multiplier": meta.get("multiplier"),
        })
    return models


@router.get("/v1/models")
async def list_models_v1():
    """免费端点：default(免费无限) + 倍率(免费计量)"""
    return {"object": "list", "data": _build_model_list("free")}


@router.get("/v3/models")
async def list_models_v3():
    """会员端点：premium_only"""
    return {"object": "list", "data": _build_model_list("premium")}


@router.get("/models")
async def list_models_v0():
    return await list_models_v1()


@router.post("/chat/completions")
async def chat_completions_v0(
    req: ChatCompletionRequest | SimpleChatRequest, authorization: str = Header(None)
):
    return await _chat_completions(req, authorization, tier="free")