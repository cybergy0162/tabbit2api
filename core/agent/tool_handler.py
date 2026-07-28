"""
Tool Handler — function calling / tool use support for OpenAI and Claude APIs.

Default: disabled. Enable via config: {"agent": {"tools": {"enabled": true}}}

Implements:
- Soft tool calling: intercept tool definitions, return tool_use, wait for tool_result
- Tool call loop: assistant → tool_use → user/tool_result → assistant chain
- Same room_id guarantee for tool chains
"""

import json
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple

logger = logging.getLogger("tabbit2agent.tools")

# ── Tool definitions ──

@dataclass
class ToolCall:
    """Represents a single tool call."""
    id: str
    name: str
    arguments: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolCallChain:
    """Tracks a tool call chain within a single room."""
    room_id: str
    tool_calls: List[ToolCall] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)


# In-memory tool call chains (room_id → chain)
_tool_chains: Dict[str, ToolCallChain] = {}


# ── Tool definition parser ──

def parse_openai_tools(tools: List[dict]) -> List[dict]:
    """Parse OpenAI tools array into a normalized format."""
    if not tools:
        return []
    result = []
    for t in tools:
        if t.get("type") == "function":
            func = t.get("function", {})
            result.append({
                "name": func.get("name", ""),
                "description": func.get("description", ""),
                "parameters": func.get("parameters", {}),
            })
    return result


def parse_claude_tools(tools: List[dict]) -> List[dict]:
    """Parse Claude tools array into a normalized format."""
    if not tools:
        return []
    result = []
    for t in tools:
        result.append({
            "name": t.get("name", ""),
            "description": t.get("description", ""),
            "parameters": t.get("input_schema", {}),
        })
    return result


def build_tool_prompt(tools: List[dict]) -> str:
    """Build a tool-calling prompt to inject into the Tabbit message.

    This is a 'soft tool call' approach: we tell the model what tools are
    available and expect it to respond with <tool_call> XML blocks.
    """
    if not tools:
        return ""

    tool_descriptions = []
    for t in tools:
        name = t.get("name", "")
        desc = t.get("description", "")
        params = json.dumps(t.get("parameters", {}), ensure_ascii=False)
        tool_descriptions.append(
            f"- {name}: {desc}\n  Parameters: {params}"
        )

    prompt = (
        "You have access to the following tools:\n\n"
        + "\n".join(tool_descriptions)
        + "\n\n"
        "To use a tool, respond with exactly:\n"
        '<tool_call>\n'
        '{"name": "<tool_name>", "arguments": <json_args>}\n'
        '</tool_call>\n'
        "After receiving the tool result, continue the conversation naturally."
    )
    return prompt


# ── Tool call detection ──

TOOL_CALL_PATTERN = re.compile(
    r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.DOTALL
)


def detect_tool_call(text: str) -> Optional[ToolCall]:
    """Detect if the model output contains a tool call."""
    match = TOOL_CALL_PATTERN.search(text)
    if not match:
        return None
    try:
        data = json.loads(match.group(1))
        return ToolCall(
            id=f"call_{uuid.uuid4().hex[:8]}",
            name=data.get("name", ""),
            arguments=data.get("arguments", {}),
        )
    except json.JSONDecodeError:
        return None


# ── Tool call chain management ──

def get_tool_chain(room_id: str) -> Optional[ToolCallChain]:
    """Get the tool call chain for a room."""
    return _tool_chains.get(room_id)


def start_tool_chain(room_id: str) -> ToolCallChain:
    """Start a new tool call chain."""
    chain = ToolCallChain(room_id=room_id)
    _tool_chains[room_id] = chain
    return chain


def add_tool_call(room_id: str, call: ToolCall):
    """Add a tool call to the chain."""
    chain = _tool_chains.get(room_id)
    if not chain:
        chain = start_tool_chain(room_id)
    chain.tool_calls.append(call)


def clear_tool_chain(room_id: str):
    """Clear a tool call chain."""
    _tool_chains.pop(room_id, None)


# ── OpenAI tool call response builder ──

def build_openai_tool_response(
    completion_id: str,
    model: str,
    tool_call: ToolCall,
    index: int = 0,
) -> dict:
    """Build an OpenAI-compatible tool call response chunk."""
    return {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [{
            "index": index,
            "delta": {
                "tool_calls": [{
                    "index": 0,
                    "id": tool_call.id,
                    "type": "function",
                    "function": {
                        "name": tool_call.name,
                        "arguments": json.dumps(tool_call.arguments, ensure_ascii=False),
                    },
                }],
            },
            "finish_reason": "tool_calls",
        }],
    }


# ── Claude tool use response builder ──

def build_claude_tool_response(
    request_id: str,
    model: str,
    tool_call: ToolCall,
    input_tokens: int = 0,
) -> str:
    """Build a Claude-compatible tool_use SSE event."""
    event = {
        "type": "content_block_start",
        "index": 0,
        "content_block": {
            "type": "tool_use",
            "id": tool_call.id,
            "name": tool_call.name,
            "input": tool_call.arguments,
        },
    }
    return f"event: content_block_start\ndata: {json.dumps(event)}\n\n"


# ── Tool result merger ──

def merge_tool_results(
    messages: List[dict],
    tool_result_role: str = "tool",
) -> str:
    """Merge tool results from messages into a context string for the model."""
    parts = []
    for msg in messages:
        role = msg.get("role", "")
        if role == tool_result_role:
            content = str(msg.get("content", ""))
            call_id = msg.get("tool_call_id", "unknown")
            parts.append(f"[Tool Result {call_id}]: {content}")
    return "\n".join(parts)
