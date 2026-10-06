"""Agent Router 回归测试。

关键保证：启用「模型路由」时，客户端明确指定的模型**绝不会被静默改写**；
仅当出现显式相位信号（X-Agent-Phase 头 或 -reasoning/-summary/-tool 后缀）时才路由。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.agent.agent_router import ModelSelector


def test_explicit_model_is_never_remapped():
    s = ModelSelector()
    for model in [
        "default",
        "best",
        "claude-opus-5-5",
        "claude-sonnet-5-5",
        "gpt-6-luna",
        "kimi-k3",
        "deepseek-v4-pro",
        "gemini-3-8-flash",
    ]:
        assert s.resolve(model) == model


def test_empty_model_is_not_forced_to_a_specific_model():
    s = ModelSelector()
    assert s.resolve("") == ""


def test_suffix_signal_triggers_routing():
    s = ModelSelector()
    assert s.resolve("kimi-k3-reasoning") == "kimi-k3"
    assert s.resolve("kimi-k3-tool") == "kimi-k3"
    # summary 相位候选是 longcat 系
    assert s.resolve("kimi-k3-summary") == "longcat-flash-chat"


def test_header_signal_triggers_routing():
    s = ModelSelector()
    # default phase 首选 deepseek-v4-pro
    assert s.resolve("default", headers={"x-agent-phase": "default"}) == "deepseek-v4-pro"
    assert s.resolve("default", headers={"x-agent-phase": "tool"}) == "kimi-k3"


def test_preferred_model_kept_when_it_is_in_candidates():
    s = ModelSelector()
    # kimi-k3 在 tool/reasoning 候选内 → 保持
    assert s.resolve("kimi-k3-tool") == "kimi-k3"
