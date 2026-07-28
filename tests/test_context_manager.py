"""Tests for context_manager module."""
import sys
sys.path.insert(0, "/home/tabbit")

from core.agent.context_manager import (
    estimate_tokens,
    get_context_limit,
    SlidingWindow,
    ContextCompressor,
)


def test_estimate_tokens_english():
    assert estimate_tokens("hello world") > 0


def test_estimate_tokens_chinese():
    """Chinese characters should have higher token ratio."""
    assert estimate_tokens("你好世界") > estimate_tokens("hello")


def test_get_context_limit():
    assert get_context_limit("kimi-k3") == 1_000_000
    assert get_context_limit("deepseek-v4-pro") == 128_000
    assert get_context_limit("unknown-model") == 128_000  # default


def test_sliding_window():
    sw = SlidingWindow(max_tokens=1000, max_turns=5)
    sw.add_system("You are helpful")
    sw.add_turn("hello", "hi there")
    sw.add_turn("how are you", "I'm fine")
    context = sw.build_context()
    assert "You are helpful" in context
    assert "hello" in context
    assert "how are you" in context


def test_sliding_window_max_turns():
    sw = SlidingWindow(max_tokens=100000, max_turns=2)
    sw.add_turn("q1", "a1")
    sw.add_turn("q2", "a2")
    sw.add_turn("q3", "a3")
    context = sw.build_context()
    assert "q1" not in context  # evicted
    assert "q2" in context
    assert "q3" in context


def test_context_compressor():
    cc = ContextCompressor("deepseek-v4-pro", threshold_ratio=0.8)
    # 128000 * 0.8 = 102400 tokens ~ 136533 chars
    short = "hello" * 100
    assert not cc.should_summarize(short)

    long_text = "hello world " * 50000
    assert cc.should_summarize(long_text)
