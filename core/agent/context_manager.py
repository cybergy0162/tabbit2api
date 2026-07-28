"""
Context Manager — sliding window, summarization, token estimation.

Default: disabled. Enable via config: {"agent": {"context": {"enabled": true}}}
"""

import logging
import re
from typing import List, Dict, Optional, Tuple

logger = logging.getLogger("tabbit2agent.context")

# ── Approximate token estimator (no tiktoken dependency) ──

# Rough ratios: English ~0.75 tokens/char, Chinese ~1.5 tokens/char
def estimate_tokens(text: str) -> int:
    """Approximate token count without tiktoken dependency."""
    if not text:
        return 0
    chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
    other_chars = len(text) - chinese_chars
    return int(chinese_chars * 1.5 + other_chars * 0.75)


# ── Model context limits ──

MODEL_CONTEXT_LIMITS = {
    "kimi-k3": 1_000_000,
    "longcat-2-0": 1_000_000,
    "deepseek-v4-pro": 128_000,
    "deepseek-v4-flash": 128_000,
    "glm-5-2": 128_000,
    "qwen3-7-max": 128_000,
    "doubao-seed-2-1-pro": 128_000,
    "minimax-m3": 128_000,
    "default": 128_000,
}


def get_context_limit(model_id: str) -> int:
    """Get the context window size for a model."""
    return MODEL_CONTEXT_LIMITS.get(model_id, MODEL_CONTEXT_LIMITS["default"])


# ── Sliding window ──

class SlidingWindow:
    """Maintains a sliding window of messages, keeping system prompt + last N turns."""

    def __init__(self, max_tokens: int = 100_000, max_turns: int = 20):
        self.max_tokens = max_tokens
        self.max_turns = max_turns
        self.system_messages: List[str] = []
        self.turns: List[Tuple[str, str]] = []  # [(user, assistant), ...]

    def add_system(self, content: str):
        self.system_messages.append(content)

    def add_turn(self, user: str, assistant: str = ""):
        self.turns.append((user, assistant))
        if len(self.turns) > self.max_turns:
            self.turns = self.turns[-self.max_turns:]

    def build_context(self) -> str:
        """Build context string within token budget."""
        parts = []
        # System prompt always included
        sys_text = "\n".join(self.system_messages)
        sys_tokens = estimate_tokens(sys_text)
        budget = self.max_tokens - sys_tokens

        turn_texts = []
        for user, assistant in self.turns:
            turn_texts.append(f"[User]: {user}\n[Assistant]: {assistant}")

        # Include turns from newest to oldest until budget exhausted
        included = []
        remaining = budget
        for turn in reversed(turn_texts):
            t = estimate_tokens(turn)
            if t <= remaining:
                included.insert(0, turn)
                remaining -= t
            else:
                break

        if sys_text:
            parts.append(sys_text)
        parts.extend(included)

        return "\n\n".join(parts)

    def get_summary(self) -> str:
        """Return a summary of the window state."""
        total_tokens = estimate_tokens(self.build_context())
        return (
            f"SlidingWindow: {len(self.turns)} turns, "
            f"~{total_tokens} tokens / {self.max_tokens} budget"
        )


# ── Summarization trigger ──

class ContextCompressor:
    """Triggers summarization when context exceeds threshold."""

    def __init__(
        self,
        model_id: str,
        threshold_ratio: float = 0.8,
        summary_model: str = "longcat-flash-chat",
    ):
        self.model_id = model_id
        self.context_limit = get_context_limit(model_id)
        self.threshold = int(self.context_limit * threshold_ratio)
        self.summary_model = summary_model
        self.summary_text: str = ""

    def should_summarize(self, content: str) -> bool:
        """Check if content exceeds threshold and needs summarization."""
        return estimate_tokens(content) > self.threshold

    def compress(self, full_history: str, summary_fn) -> str:
        """Compress history by calling summary_fn (async callback to lightweight model).

        Args:
            full_history: the full conversation text
            summary_fn: async callable(content, model) -> summary_string

        Returns:
            compressed content with old history replaced by summary
        """
        if not self.should_summarize(full_history):
            return full_history

        # Simple truncation-based compression (summary_fn requires external LLM call)
        # Keep first 20% (recent context) and drop the rest
        tokens = estimate_tokens(full_history)
        keep_ratio = self.threshold / max(tokens, 1)
        keep_chars = int(len(full_history) * min(keep_ratio, 0.5))

        recent = full_history[-keep_chars:]
        self.summary_text = f"[Context compressed: {tokens} → ~{estimate_tokens(recent)} tokens]"
        logger.info(f"[context] compressed {tokens} → ~{estimate_tokens(recent)} tokens")
        return recent
