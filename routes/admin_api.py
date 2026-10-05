import uuid
import time
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional

from core.config import ConfigManager, hash_password
from core.auth import create_jwt, verify_password, require_admin
from core.token_manager import TokenManager
from core.tabbit_client import TabbitClient
from core.log_store import LogStore

logger = logging.getLogger("tabbit2openai")


def _normalize_default_model(name: Optional[str]) -> str:
    """默认模型名归一化：best / 默认 / 空 → default（实际模型 id）。"""
    if not name or name in ("best", "默认"):
        return "default"
    return name

# 模块级状态
_cfg: ConfigManager | None = None
_tm: TokenManager | None = None
_logs: LogStore | None = None

# Pydantic models（需在模块级定义才能被 FastAPI 正确解析）
class LoginRequest(BaseModel):
    password: str

class TokenAddRequest(BaseModel):
    name: str
    value: str
    enabled: bool = True
    site: Optional[str] = None

class TokenUpdateRequest(BaseModel):
    name: Optional[str] = None
    value: Optional[str] = None
    enabled: Optional[bool] = None
    site: Optional[str] = None

class SettingsUpdateRequest(BaseModel):
    host: Optional[str] = None
    port: Optional[int] = None
    base_url: Optional[str] = None
    client_id: Optional[str] = None
    site: Optional[str] = None
    api_key: Optional[str] = None
    max_entries: Optional[int] = None
    claude_default_model: Optional[str] = None
    openai_default_model: Optional[str] = None
    openai_system_prompt: Optional[str] = None
    claude_system_prompt: Optional[str] = None
    session_enabled: Optional[bool] = None
    session_ttl: Optional[int] = None
    agent_cleaner: Optional[bool] = None
    agent_context: Optional[bool] = None
    agent_tools: Optional[bool] = None
    agent_router: Optional[bool] = None
    agent_token_pool: Optional[bool] = None


class PasswordUpdateRequest(BaseModel):
    old_password: str
    new_password: str


# router 初始为占位，init() 后替换为带鉴权的完整路由
router = APIRouter(prefix="/api/admin")


def init(config: ConfigManager, token_manager: TokenManager, log_store: LogStore):
    global _cfg, _tm, _logs, router
    _cfg = config
    _tm = token_manager
    _logs = log_store

    admin_dep = require_admin(config)
    r = APIRouter(prefix="/api/admin")

    # ── Login（无需鉴权）──

    @r.post("/login")
    async def login(req: LoginRequest):
        if not verify_password(req.password, _cfg):
            raise HTTPException(status_code=401, detail="wrong password")
        return {"token": create_jwt(_cfg)}

    # ── Status ──

    @r.get("/status", dependencies=[Depends(admin_dep)])
    async def get_status():
        tokens = _cfg.get("tokens", default=[])
        active = sum(
            1 for t in tokens
            if t.get("enabled") and t.get("status") == "active"
        )
        # 按站点统计 token
        by_site = {}
        for t in tokens:
            s = t.get("site") or "intl"
            by_site[s] = by_site.get(s, 0) + 1
        return {
            "total_requests": _logs.total_requests,
            "total_success": _logs.total_success,
            "total_errors": _logs.total_errors,
            "success_rate": round(
                _logs.total_success / max(_logs.total_requests, 1) * 100, 1
            ),
            "total_tokens": len(tokens),
            "active_tokens": active,
            "tokens_by_site": by_site,
            "active_site": _cfg.get_active_site(),
            "sites": _cfg.get_sites(),
            "recent_logs": _logs.query(page=1, page_size=10)["items"],
        }

    # ── Tokens ──

    @r.get("/tokens", dependencies=[Depends(admin_dep)])
    async def list_tokens():
        tokens = _cfg.get("tokens", default=[])
        result = []
        for t in tokens:
            info = {**t}
            info["status"] = _tm.get_token_status(t["id"])
            v = info.get("value", "")
            info["value_preview"] = (v[:10] + "...") if len(v) > 10 else v
            del info["value"]
            result.append(info)
        return {"tokens": result}

    @r.post("/tokens", dependencies=[Depends(admin_dep)])
    async def add_token(req: TokenAddRequest):
        site = req.site or _cfg.get_active_site()
        if site not in _cfg.get_sites():
            site = "intl"
        token_entry = {
            "id": str(uuid.uuid4()),
            "name": req.name,
            "value": req.value,
            "enabled": req.enabled,
            "site": site,
            "added_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "last_used_at": None,
            "total_requests": 0,
            "error_count": 0,
            "status": "unknown",
        }
        tokens = _cfg.get("tokens", default=[])
        tokens.append(token_entry)
        _cfg.config["tokens"] = tokens
        _cfg.save()
        return {"id": token_entry["id"], "site": site}

    @r.put("/tokens/{token_id}", dependencies=[Depends(admin_dep)])
    async def update_token(token_id: str, req: TokenUpdateRequest):
        for t in _cfg.get("tokens", default=[]):
            if t["id"] == token_id:
                if req.name is not None:
                    t["name"] = req.name
                if req.value is not None:
                    t["value"] = req.value
                    _tm.remove_client(token_id)
                if req.enabled is not None:
                    t["enabled"] = req.enabled
                if req.site is not None and req.site in _cfg.get_sites():
                    t["site"] = req.site
                    _tm.remove_client(token_id)
                _cfg.save()
                return {"ok": True}
        raise HTTPException(status_code=404, detail="token not found")

    @r.delete("/tokens/{token_id}", dependencies=[Depends(admin_dep)])
    async def delete_token(token_id: str):
        tokens = _cfg.get("tokens", default=[])
        _cfg.config["tokens"] = [t for t in tokens if t["id"] != token_id]
        _cfg.save()
        _tm.remove_client(token_id)
        return {"ok": True}

    @r.post("/tokens/{token_id}/test", dependencies=[Depends(admin_dep)])
    async def test_token(token_id: str):
        target = None
        for t in _cfg.get("tokens", default=[]):
            if t["id"] == token_id:
                target = t
                break
        if not target:
            raise HTTPException(status_code=404, detail="token not found")

        client = TabbitClient(
            target["value"],
            _cfg.get_site_base_url(target.get("site") or "intl"),
            _cfg.get("tabbit", "client_id"),
        )
        try:
            session_id = await client.create_chat_session()
            target["status"] = "active"
            target["error_count"] = 0
            _cfg.save()
            return {"ok": True, "session_id": session_id}
        except Exception as e:
            target["status"] = "error"
            _cfg.save()
            return {"ok": False, "error": str(e)}
        finally:
            await client.client.aclose()

    # ── Settings ──

    @r.get("/settings", dependencies=[Depends(admin_dep)])
    async def get_settings():
        from routes.openai_compat import SESSION_TTL, SESSION_ENABLED
        return {
            "server": _cfg.get("server"),
            "tabbit": _cfg.get("tabbit"),
            "active_site": _cfg.get_active_site(),
            "sites": _cfg.get_sites(),
            "active_base_url": _cfg.get_active_base_url(),
            "proxy": {
                "api_key": _cfg.get("proxy", "api_key", default=""),
                "system_prompt": _cfg.get("proxy", "system_prompt", default=""),
            },
            "claude": _cfg.get("claude", default={"default_model": "default", "system_prompt": ""}),
            "openai": _cfg.get("openai", default={"default_model": "default"}),
            "session": {
                "enabled": SESSION_ENABLED,
                "ttl_seconds": SESSION_TTL,
            },
            "agent": _cfg.get("agent", default={
                "cleaner": {"enabled": False}, "context": {"enabled": False},
                "tools": {"enabled": False}, "router": {"enabled": False},
                "token_pool": {"enabled": False},
            }),
            "logging": _cfg.get("logging"),
        }

    @r.put("/settings", dependencies=[Depends(admin_dep)])
    async def update_settings(req: SettingsUpdateRequest):
        if req.host is not None:
            _cfg.set_val("server", "host", req.host)
        if req.port is not None:
            _cfg.set_val("server", "port", req.port)
        # 切换站点（优先于 base_url）
        if req.site is not None:
            if req.site not in _cfg.get_sites():
                raise HTTPException(status_code=400, detail=f"unknown site: {req.site}")
            _cfg.set_active_site(req.site)
            _tm.invalidate_all_clients()
            import core.tabbit_client as _tc
            _tc.set_active_site_marker(req.site)
            _tc.activate_site(req.site)
        elif req.base_url is not None:
            # 更新当前站点的 base_url
            site = _cfg.get_active_site()
            sites = _cfg.get_sites()
            _cfg.set_val("tabbit", "sites", site, "base_url", req.base_url)
            _cfg.set_val("tabbit", "base_url", req.base_url)
            _tm.invalidate_all_clients()
        if req.client_id is not None:
            _cfg.set_val("tabbit", "client_id", req.client_id)
        if req.api_key is not None:
            _cfg.set_val("proxy", "api_key", req.api_key)
        if req.claude_default_model is not None:
            _cfg.set_val("claude", "default_model", _normalize_default_model(req.claude_default_model))
        if req.openai_default_model is not None:
            _cfg.set_val("openai", "default_model", _normalize_default_model(req.openai_default_model))
        if req.openai_system_prompt is not None:
            _cfg.set_val("proxy", "system_prompt", req.openai_system_prompt)
        if req.claude_system_prompt is not None:
            _cfg.set_val("claude", "system_prompt", req.claude_system_prompt)
        if req.max_entries is not None:
            _cfg.set_val("logging", "max_entries", req.max_entries)
            _logs.resize(req.max_entries)
        if req.session_enabled is not None:
            import routes.openai_compat as oc
            oc.SESSION_ENABLED = req.session_enabled
        if req.session_ttl is not None:
            import routes.openai_compat as oc
            oc.SESSION_TTL = req.session_ttl
        # Agent toggles
        for key, attr in [("agent_cleaner", "cleaner"), ("agent_context", "context"),
                          ("agent_tools", "tools"), ("agent_router", "router"),
                          ("agent_token_pool", "token_pool")]:
            val = getattr(req, key, None)
            if val is not None:
                _cfg.set_val("agent", attr, "enabled", val)
        return {"ok": True}

    # ── Model Update ──

    async def _refresh_models_for_site(site: str) -> dict:
        """为该站点拉取模型目录并写入其缓存；若为当前站点则同步全局。"""
        from core.tabbit_client import fetch_model_map_ex, update_model_map_for_site
        tokens = [t for t in _cfg.get("tokens", default=[])
                  if (t.get("site") or "intl") == site and t.get("value")]
        if not tokens:
            return {"ok": False, "error": f"站点 {site} 下没有可用 Token，请先添加"}
        token_str = tokens[0]["value"]
        base_url = _cfg.get_site_base_url(site)
        new_models, meta = await fetch_model_map_ex(token_str, base_url)
        if not new_models:
            return {"ok": False, "error": f"从站点 {site} 拉取模型失败（{base_url}）"}
        update_model_map_for_site(site, new_models, meta)
        return {"ok": True, "site": site, "count": len(new_models),
                "models": new_models, "base_url": base_url}

    @r.post("/test-models", dependencies=[Depends(admin_dep)])
    async def test_model_update(site: Optional[str] = None):
        try:
            site = site or _cfg.get_active_site()
            if site not in _cfg.get_sites():
                return {"ok": False, "error": f"unknown site: {site}"}
            res = await _refresh_models_for_site(site)
            if not res.get("ok"):
                return res
            from core.tabbit_client import MODEL_MAP
            return {
                "ok": True,
                "site": site,
                "message": f"已更新站点 {site} 的 {res['count']} 个模型",
                "new_models_count": res["count"],
                "total_models_count": len(MODEL_MAP),
                "current_model": _cfg.get("claude", "default_model", default="default"),
                "new_models": dict(list(res["models"].items())[:20]),
            }
        except Exception as e:
            logger.error(f"Failed to test model update: {e}", exc_info=True)
            return {"ok": False, "error": str(e)}

    # ── 站点切换 ──

    @r.get("/sites", dependencies=[Depends(admin_dep)])
    async def list_sites():
        tokens = _cfg.get("tokens", default=[])
        by_site = {}
        for t in tokens:
            s = t.get("site") or "intl"
            by_site[s] = by_site.get(s, 0) + 1
        import core.tabbit_client as _tc
        return {
            "active_site": _cfg.get_active_site(),
            "sites": [
                {
                    "key": k,
                    "label": v.get("label", k),
                    "base_url": v.get("base_url"),
                    "token_count": by_site.get(k, 0),
                    "model_count": len(_tc.MODEL_MAP_BY_SITE.get(k, {})),
                }
                for k, v in _cfg.get_sites().items()
            ],
        }

    @r.post("/site/switch", dependencies=[Depends(admin_dep)])
    async def switch_site(req: dict):
        site = (req or {}).get("site")
        if site not in _cfg.get_sites():
            raise HTTPException(status_code=400, detail=f"unknown site: {site}")
        refresh = bool((req or {}).get("refresh", True))

        _cfg.set_active_site(site)
        _tm.invalidate_all_clients()
        import core.tabbit_client as _tc
        _tc.set_active_site_marker(site)
        _tc.activate_site(site)

        # 清理会话与兜底客户端缓存（不同站点模型/会话不通用）
        try:
            import routes.openai_compat as _oc
            import routes.claude_api as _ca
            _oc._fallback_clients.clear()
            _oc.clear_all_sessions()
            _ca._fallback_clients.clear()
            _ca._claude_session_cache.clear()
        except Exception as e:
            logger.warning(f"clear caches on site switch failed: {e}")

        result = {"ok": True, "active_site": site, "base_url": _cfg.get_active_base_url(),
                  "model_count": len(_tc.MODEL_MAP)}
        if refresh:
            r = await _refresh_models_for_site(site)
            result["refresh"] = r
            result["model_count"] = len(_tc.MODEL_MAP)
        return result

    # ── Password ──

    @r.put("/password", dependencies=[Depends(admin_dep)])
    async def update_password(req: PasswordUpdateRequest):
        if not verify_password(req.old_password, _cfg):
            raise HTTPException(status_code=401, detail="wrong old password")
        pw_hash, salt = hash_password(req.new_password)
        _cfg.set_val("admin", "password_hash", pw_hash)
        _cfg.set_val("admin", "salt", salt)
        return {"ok": True}

    # ── Sessions ──

    @r.get("/sessions", dependencies=[Depends(admin_dep)])
    async def get_sessions():
        from routes.openai_compat import get_session_list, SESSION_TTL, SESSION_ENABLED
        sessions = get_session_list()
        return {
            "sessions": sessions,
            "total": len(sessions),
            "ttl_seconds": SESSION_TTL,
            "enabled": SESSION_ENABLED,
        }

    @r.delete("/sessions/{cache_key}", dependencies=[Depends(admin_dep)])
    async def delete_session_endpoint(cache_key: str):
        from routes.openai_compat import delete_session
        ok = delete_session(cache_key)
        if not ok:
            raise HTTPException(status_code=404, detail="session not found")
        return {"ok": True}

    @r.post("/sessions/clear", dependencies=[Depends(admin_dep)])
    async def clear_sessions():
        from routes.openai_compat import clear_all_sessions
        clear_all_sessions()
        return {"ok": True}

    @r.post("/sessions/bind", dependencies=[Depends(admin_dep)])
    async def bind_session(request: dict):
        from routes.openai_compat import set_fixed_session
        bearer = request.get("api_key", "")
        model_id = request.get("model_id", "")
        room_id = request.get("room_id", "")
        if not bearer or not model_id or not room_id:
            raise HTTPException(status_code=400, detail="api_key, model_id, room_id required")
        set_fixed_session(bearer, model_id, room_id)
        return {"ok": True, "message": f"已绑定 {model_id} → {room_id}"}

    @r.post("/sessions/unbind", dependencies=[Depends(admin_dep)])
    async def unbind_session(request: dict):
        from routes.openai_compat import remove_fixed_session
        bearer = request.get("api_key", "")
        model_id = request.get("model_id", "")
        ok = remove_fixed_session(bearer, model_id)
        if not ok:
            raise HTTPException(status_code=404, detail="未找到该绑定")
        return {"ok": True}

    # ── Logs ──

    @r.get("/logs", dependencies=[Depends(admin_dep)])
    async def get_logs(
        status: Optional[str] = None, page: int = 1, page_size: int = 50
    ):
        return _logs.query(status=status, page=page, page_size=page_size)

    router = r
