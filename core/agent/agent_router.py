"""
Agent Router — agent-aware model routing with phase detection.

Default: disabled. Enable via config: {"agent": {"router": {"enabled": true}}}

Supports:
- X-Agent-Phase header: reasoning / summary / tool / default
- Model ID suffix: *-reasoning, *-summary, *-tool
- ModelSelector: dynamic selection based on intent + health
"""

import logging
import re
from typing import Dict, Optional

logger = logging.getLogger("tabbit2agent.router")

# ── Phase → Model Mapping ──

DEFAULT_PHASE_MAP = {
    "reasoning": ["kimi-k3", "deepseek-v4-pro", "qwen3-7-max"],
    "summary": ["longcat-flash-chat", "longcat-flash-thinking", "doubao-seed-2-1-turbo"],
    "tool": ["kimi-k3", "deepseek-v4-pro", "qwen3-7-max"],
    "default": ["deepseek-v4-pro", "kimi-k3", "qwen3-7-max"],
}

# ── Model ID suffix patterns ──

SUFFIX_PATTERNS = {
    "reasoning": re.compile(r".*-reasoning$", re.I),
    "summary": re.compile(r".*-summary$", re.I),
    "tool": re.compile(r".*-tool$", re.I),
}


class ModelSelector:
    """Selects the best model based on agent phase, health, and availability."""

    def __init__(self, phase_map: Optional[Dict[str, list]] = None):
        self.phase_map = phase_map or DEFAULT_PHASE_MAP
        self._health: Dict[str, bool] = {}  # model_id → healthy?

    def detect_phase(self, model_id: str, headers: Optional[dict] = None) -> str:
        """Detect the agent phase from model ID suffix or X-Agent-Phase header.

        Returns one of: reasoning, summary, tool, default
        """
        # 1) Header-based detection
        if headers:
            phase = headers.get("x-agent-phase", "").lower()
            if phase in self.phase_map:
                return phase

        # 2) Model ID suffix
        for phase, pattern in SUFFIX_PATTERNS.items():
            if pattern.search(model_id):
                return phase

        return "default"

    def select_model(self, phase: str = "default", preferred: str = "") -> str:
        """Select the best model for a given phase.

        Args:
            phase: agent phase (reasoning/summary/tool/default)
            preferred: user-preferred model ID

        Returns:
            best model_id for this phase
        """
        candidates = self.phase_map.get(phase, self.phase_map["default"])

        # If user has a preferred model and it's in candidates, use it
        if preferred and preferred in candidates:
            return preferred

        # Pick the first healthy candidate
        for model in candidates:
            if self._health.get(model, True):  # default healthy
                return model

        # Fallback: first candidate regardless
        return candidates[0] if candidates else "deepseek-v4-pro"

    def mark_unhealthy(self, model_id: str):
        """Mark a model as temporarily unhealthy."""
        self._health[model_id] = False
        logger.warning(f"[router] model {model_id} marked unhealthy")

    def mark_healthy(self, model_id: str):
        """Mark a model as healthy."""
        self._health[model_id] = True

    def resolve(self, request_model: str, headers: Optional[dict] = None) -> str:
        """Full resolve: detect phase + select model.

        Args:
            request_model: the model ID from the API request
            headers: optional HTTP headers dict

        Returns:
            resolved model ID
        """
        phase = self.detect_phase(request_model, headers)
        selected = self.select_model(phase, preferred=request_model)
        if selected != request_model:
            logger.info(f"[router] {request_model} → {selected} (phase={phase})")
        return selected
