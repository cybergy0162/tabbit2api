import time
import asyncio
from typing import Optional

from core.config import ConfigManager
from core.tabbit_client import TabbitClient

COOLDOWN_SECONDS = 300  # 5 分钟冷却
MAX_CONSECUTIVE_ERRORS = 3


class TokenManager:
    def __init__(self, config: ConfigManager):
        self.config = config
        self._clients: dict[str, TabbitClient] = {}
        self._index: int = 0
        self._cooldowns: dict[str, float] = {}  # token_id -> 冷却截止时间戳
        self._lock = asyncio.Lock()

    @property
    def has_tokens(self) -> bool:
        return len(self._eligible_tokens()) > 0

    def _eligible_tokens(self, site: str | None = None) -> list[dict]:
        """返回可用（enabled 且站点匹配）的 token 列表。site=None 用当前激活站点。"""
        site = site or self.config.get_active_site()
        tokens = self.config.get("tokens", default=[])
        out = []
        for t in tokens:
            if not t.get("enabled", True):
                continue
            # 未标注站点的旧 token 视为国际版
            t_site = t.get("site") or "intl"
            if t_site != site:
                continue
            out.append(t)
        return out

    def _get_available_tokens(self, site: str | None = None) -> list[dict]:
        now = time.time()
        available = []
        for t in self._eligible_tokens(site):
            cooldown_until = self._cooldowns.get(t["id"], 0)
            if now >= cooldown_until:
                if t["id"] in self._cooldowns:
                    del self._cooldowns[t["id"]]
                    # 冷却恢复 → 重置状态
                    t["status"] = "unknown"
                    t["error_count"] = 0
                available.append(t)
        return available

    def _get_client(self, token_info: dict) -> TabbitClient:
        tid = token_info["id"]
        # 站点切换后，若该 token 的 base_url 变了则重建客户端
        base_url = self.config.get_site_base_url(token_info.get("site") or "intl")
        if tid not in self._clients or getattr(self._clients[tid], "base_url", None) != base_url:
            self._clients[tid] = TabbitClient(
                token_info["value"],
                base_url,
                self.config.get("tabbit", "client_id"),
            )
        return self._clients[tid]

    async def get_next(self, site: str | None = None) -> tuple[Optional[dict], Optional[TabbitClient]]:
        async with self._lock:
            available = self._get_available_tokens(site)
            if not available:
                return None, None
            self._index = self._index % len(available)
            token_info = available[self._index]
            self._index = (self._index + 1) % len(available)
            client = self._get_client(token_info)
            return token_info, client

    def report_success(self, token_id: str):
        for t in self.config.get("tokens", default=[]):
            if t["id"] == token_id:
                t["total_requests"] = t.get("total_requests", 0) + 1
                t["error_count"] = 0
                t["last_used_at"] = time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
                )
                t["status"] = "active"
                break
        self.config.save()

    def report_error(self, token_id: str):
        for t in self.config.get("tokens", default=[]):
            if t["id"] == token_id:
                t["error_count"] = t.get("error_count", 0) + 1
                t["total_requests"] = t.get("total_requests", 0) + 1
                if t["error_count"] >= MAX_CONSECUTIVE_ERRORS:
                    self._cooldowns[t["id"]] = time.time() + COOLDOWN_SECONDS
                    t["status"] = "cooldown"
                else:
                    t["status"] = "error"
                break
        self.config.save()

    def remove_client(self, token_id: str):
        self._clients.pop(token_id, None)
        self._cooldowns.pop(token_id, None)

    def invalidate_all_clients(self):
        """站点切换后调用：丢弃所有已缓存客户端，下次按新 base_url 重建。"""
        self._clients.clear()

    def get_token_status(self, token_id: str) -> str:
        now = time.time()
        cooldown_until = self._cooldowns.get(token_id, 0)
        if now < cooldown_until:
            return "cooldown"
        for t in self.config.get("tokens", default=[]):
            if t["id"] == token_id:
                return t.get("status", "unknown")
        return "unknown"

    async def close_all(self):
        for client in self._clients.values():
            await client.client.aclose()
        self._clients.clear()
