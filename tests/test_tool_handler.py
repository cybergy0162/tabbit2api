"""Tests for tool_handler module."""
import sys
sys.path.insert(0, "/home/tabbit")

from core.agent.tool_handler import (
    parse_openai_tools,
    parse_claude_tools,
    build_tool_prompt,
    detect_tool_call,
    build_openai_tool_response,
    ToolCall,
)


def test_parse_openai_tools():
    tools = [
        {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "Get weather for a city",
                "parameters": {"type": "object", "properties": {"city": {"type": "string"}}},
            },
        }
    ]
    parsed = parse_openai_tools(tools)
    assert len(parsed) == 1
    assert parsed[0]["name"] == "get_weather"


def test_parse_claude_tools():
    tools = [
        {
            "name": "get_weather",
            "description": "Get weather",
            "input_schema": {"type": "object", "properties": {"city": {"type": "string"}}},
        }
    ]
    parsed = parse_claude_tools(tools)
    assert len(parsed) == 1
    assert parsed[0]["name"] == "get_weather"


def test_build_tool_prompt():
    tools = [{"name": "get_weather", "description": "Get weather", "parameters": {}}]
    prompt = build_tool_prompt(tools)
    assert "get_weather" in prompt
    assert "tool_call" in prompt


def test_detect_tool_call():
    text = 'some text\n<tool_call>\n{"name": "get_weather", "arguments": {"city": "Beijing"}}\n</tool_call>'
    result = detect_tool_call(text)
    assert result is not None
    assert result.name == "get_weather"
    assert result.arguments == {"city": "Beijing"}


def test_detect_tool_call_none():
    assert detect_tool_call("no tool call here") is None


def test_build_openai_tool_response():
    call = ToolCall(id="call_123", name="get_weather", arguments={"city": "Beijing"})
    resp = build_openai_tool_response("cmpl-123", "kimi-k3", call)
    assert resp["object"] == "chat.completion.chunk"
    choices = resp["choices"]
    assert len(choices) == 1
    tc = choices[0]["delta"]["tool_calls"][0]
    assert tc["function"]["name"] == "get_weather"
    assert "Beijing" in tc["function"]["arguments"]
    assert choices[0]["finish_reason"] == "tool_calls"
