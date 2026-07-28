"""
Token Pool — enhanced token management with weighted round-robin, state machine, encryption.

Default: disabled (backward compatible). Enable via config: {"agent": {"token_pool": {"enabled": true}}}
"""

import asyncio
import base64
import hashlib
import logging
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("tabbit2agent.token_pool")


# ── Token State Machine ──

class TokenState(Enum):
    ACTIVE = "active"
    COOLDOWN = "cooldown"
    BANNED = "banned"
    UNKNOWN = "unknown"


@dataclass
class TokenMetrics:
    """Per-token runtime metrics."""
    qps: float = 0.0
    success_rate: float = 1.0
    avg_latency: float = 0.0
    total_requests: int = 0
    total_success: int = 0
    total_errors: int = 0
    last_request_time: float = 0.0
    last_error_time: float = 0.0
    consecutive_errors: int = 0

    def record_success(self, latency: float = 0):
        self.total_requests += 1
        self.total_success += 1
        self.consecutive_errors = 0
        self.last_request_time = time.time()
        self.success_rate = self.total_success / max(self.total_requests, 1)
        if latency > 0:
            n = self.total_success
            self.avg_latency = (self.avg_latency * (n - 1) + latency) / n

    def record_error(self):
        self.total_requests += 1
        self.total_errors += 1
        self.consecutive_errors += 1
        self.last_error_time = time.time()
        self.last_request_time = time.time()
        self.success_rate = self.total_success / max(self.total_requests, 1)


@dataclass
class PoolToken:
    """A token in the enhanced pool."""
    token_id: str
    value: str  # encrypted or raw token string
    weight: int = 1
    state: TokenState = TokenState.ACTIVE
    metrics: TokenMetrics = field(default_factory=TokenMetrics)
    cooldown_until: float = 0.0


# ── Weighted Round-Robin Pool ──

class EnhancedTokenPool:
    """Weighted round-robin token pool with state machine and metrics."""

    def __init__(
        self,
        tokens: List[dict],
        cooldown_seconds: int = 300,
        max_consecutive_errors: int = 3,
        encryption_key: Optional[bytes] = None,
    ):
        self.cooldown_seconds = cooldown_seconds
        self.max_consecutive_errors = max_consecutive_errors
        self.encryption_key = encryption_key

        self._tokens: Dict[str, PoolToken] = {}
        self._index = 0
        self._lock = asyncio.Lock()

        for t in tokens:
            tid = t.get("id", t.get("token_id", hashlib.md5(t["value"].encode()).hexdigest()[:8]))
            raw_value = t["value"]
            if encryption_key:
                raw_value = self._decrypt(raw_value)
            self._tokens[tid] = PoolToken(
                token_id=tid,
                value=raw_value,
                weight=t.get("weight", 1),
                state=TokenState(t.get("status", "active")),
            )

    def _decrypt(self, encrypted: str) -> str:
        """Decrypt token value using Fernet-compatible key."""
        try:
            from cryptography.fernet import Fernet
            f = Fernet(self.encryption_key)
            return f.decrypt(encrypted.encode()).decode()
        except Exception:
            return encrypted  # fallback: treat as plaintext

    def _encrypt(self, plaintext: str) -> str:
        """Encrypt token value."""
        try:
            from cryptography.fernet import Fernet
            f = Fernet(self.encryption_key)
            return f.encrypt(plaintext.encode()).decode()
        except Exception:
            return plaintext

    async def get_next(self) -> Optional[Tuple[str, str]]:
        """Get next available token. Returns (token_id, token_value) or None."""
        async with self._lock:
            active = [
                t for t in self._tokens.values()
                if t.state == TokenState.ACTIVE
                or (t.state == TokenState.COOLDOWN and time.time() > t.cooldown_until)
            ]
            if not active:
                logger.warning("[token_pool] no available tokens")
                return None

            # Weighted selection
            total_weight = sum(t.weight for t in active)
            if total_weight == 0:
                return None

            # Simple weighted round-robin
            self._index = (self._index + 1) % len(active)
            selected = active[self._index]
            return (selected.token_id, selected.value)

    async def report_success(self, token_id: str, latency: float = 0):
        async with self._lock:
            t = self._tokens.get(token_id)
            if t:
                t.metrics.record_success(latency)
                if t.state == TokenState.COOLDOWN:
                    t.state = TokenState.ACTIVE

    async def report_error(self, token_id: str, status_code: int = 0):
        async with self._lock:
            t = self._tokens.get(token_id)
            if not t:
                return
            t.metrics.record_error()

            if status_code in (401, 403):
                t.state = TokenState.BANNED
                logger.warning(f"[token_pool] token {token_id} BANNED (status={status_code})")
            elif t.metrics.consecutive_errors >= self.max_consecutive_errors:
                t.state = TokenState.COOLDOWN
                t.cooldown_until = time.time() + self.cooldown_seconds
                logger.warning(
                    f"[token_pool] token {token_id} COOLDOWN for {self.cooldown_seconds}s"
                )

    async def get_metrics(self) -> List[dict]:
        """Return metrics for all tokens."""
        async with self._lock:
            return [
                {
                    "token_id": t.token_id,
                    "state": t.state.value,
                    "weight": t.weight,
                    "success_rate": round(t.metrics.success_rate, 3),
                    "avg_latency": round(t.metrics.avg_latency, 3),
                    "total_requests": t.metrics.total_requests,
                    "consecutive_errors": t.metrics.consecutive_errors,
                    "qps": round(t.metrics.qps, 2),
                }
                for t in self._tokens.values()
            ]

    async def add_token(self, token_data: dict):
        """Add a new token to the pool."""
        async with self._lock:
            tid = token_data.get("id", hashlib.md5(token_data["value"].encode()).hexdigest()[:8])
            raw_value = token_data["value"]
            if self.encryption_key:
                raw_value = self._decrypt(raw_value)
            self._tokens[tid] = PoolToken(
                token_id=tid,
                value=raw_value,
                weight=token_data.get("weight", 1),
            )

    async def remove_token(self, token_id: str):
        """Remove a token from the pool."""
        async with self._lock:
            self._tokens.pop(token_id, None)
