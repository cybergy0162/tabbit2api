import json
import os
import hashlib
import secrets
import copy
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.json"

DEFAULT_CONFIG = {
    "server": {"host": "0.0.0.0", "port": 8800},
    "admin": {"password_hash": "", "salt": "", "jwt_secret": ""},
    "tabbit": {
        "active_site": "intl",
        "base_url": "https://web.tabbit.ai",
        "client_id": "2dd8eb4c1ed9c344d173",
        "sites": {
            "intl": {"label": "国际版", "base_url": "https://web.tabbit.ai"},
            "cn": {"label": "国内版", "base_url": "https://web.tabbit.com"},
        },
    },
    "tokens": [],
    "proxy": {"api_key": "", "system_prompt": ""},
    "claude": {"default_model": "default", "system_prompt": ""},
    "openai": {"default_model": "default"},
    "agent": {
        "cleaner": {"enabled": False},
        "context": {"enabled": False, "max_turns": 20, "threshold_ratio": 0.8},
        "tools": {"enabled": False},
        "router": {"enabled": False},
        "token_pool": {"enabled": False, "cooldown_seconds": 300, "max_consecutive_errors": 3, "encryption_key": ""},
    },
    "logging": {"max_entries": 500},
}

ENV_VAR_MAP = {
    "TABBIT_SERVER_HOST": ("server", "host"),
    "TABBIT_SERVER_PORT": ("server", "port"),
    "TABBIT_BASE_URL": ("tabbit", "base_url"),
    "TABBIT_CLIENT_ID": ("tabbit", "client_id"),
    "TABBIT_API_KEY": ("proxy", "api_key"),
    "TABBIT_SYSTEM_PROMPT": ("proxy", "system_prompt"),
    "TABBIT_CLAUDE_DEFAULT_MODEL": ("claude", "default_model"),
    "TABBIT_CLAUDE_SYSTEM_PROMPT": ("claude", "system_prompt"),
    "TABBIT_OPENAI_DEFAULT_MODEL": ("openai", "default_model"),
}


def _apply_env_overrides(config: dict) -> dict:
    for env_var, keys in ENV_VAR_MAP.items():
        value = os.environ.get(env_var)
        if value is not None:
            d = config
            for k in keys[:-1]:
                d = d.setdefault(k, {})
            if keys[-1] == "port":
                try:
                    d[keys[-1]] = int(value)
                except ValueError:
                    pass
            else:
                d[keys[-1]] = value
    return config


def _normalize_sites(config: dict) -> dict:
    """确保 tabbit.sites / active_site / base_url 一致（向后兼容旧配置）。
    - sites 缺失时用默认值补齐
    - active_site 缺失时从当前 base_url 推断（含 tabbit.com → cn，否则 intl）
    - 最后把 tabbit.base_url 同步为 active_site 的 base_url
    """
    tabbit = config.setdefault("tabbit", {})
    defaults = DEFAULT_CONFIG["tabbit"]["sites"]
    sites = tabbit.get("sites")
    if not isinstance(sites, dict) or not sites:
        sites = copy.deepcopy(defaults)
    else:
        sites = _deep_merge(copy.deepcopy(defaults), sites)
    tabbit["sites"] = sites

    active = tabbit.get("active_site")
    if active not in sites:
        # 从现有 base_url 推断
        cur = str(tabbit.get("base_url") or "")
        active = "cn" if "tabbit.com" in cur else "intl"
    tabbit["active_site"] = active
    tabbit["base_url"] = sites[active]["base_url"]
    return config


def _deep_merge(base: dict, override: dict) -> dict:
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    if salt is None:
        salt = secrets.token_hex(16)
    hashed = hashlib.sha256((password + salt).encode()).hexdigest()
    return hashed, salt


class ConfigManager:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else CONFIG_PATH
        self.config = self._load()

    def _load(self) -> dict:
        if self.path.exists():
            with open(self.path, "r", encoding="utf-8") as f:
                saved = json.load(f)
            config = _deep_merge(copy.deepcopy(DEFAULT_CONFIG), saved)
            config = _normalize_sites(config)
            config = _apply_env_overrides(config)
            self._save(config)
            return config

        config = copy.deepcopy(DEFAULT_CONFIG)
        config["admin"]["jwt_secret"] = secrets.token_hex(32)
        pw_hash, salt = hash_password("admin")
        config["admin"]["password_hash"] = pw_hash
        config["admin"]["salt"] = salt
        config = _normalize_sites(config)
        config = _apply_env_overrides(config)
        self._save(config)
        return config

    def _save(self, config: dict | None = None):
        if config is None:
            config = self.config
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)

    def save(self):
        self._save()

    def get(self, *keys, default=None):
        val = self.config
        for k in keys:
            if isinstance(val, dict):
                val = val.get(k)
            else:
                return default
            if val is None:
                return default
        return val

    def set_val(self, *keys_and_value):
        """set_val('server', 'port', 8800) — 最后一个参数是值"""
        keys = keys_and_value[:-1]
        value = keys_and_value[-1]
        d = self.config
        for k in keys[:-1]:
            d = d.setdefault(k, {})
        d[keys[-1]] = value
        self.save()

    # ── 站点（国际版/国内版）──

    def get_active_site(self) -> str:
        site = self.get("tabbit", "active_site", default="intl")
        sites = self.get("tabbit", "sites", default={}) or {}
        return site if site in sites else "intl"

    def get_sites(self) -> dict:
        return self.get("tabbit", "sites", default={}) or {}

    def get_site_base_url(self, site: str | None = None) -> str:
        site = site or self.get_active_site()
        sites = self.get_sites()
        if site in sites:
            return sites[site].get("base_url")
        return self.get("tabbit", "base_url", default="https://web.tabbit.ai")

    def get_active_base_url(self) -> str:
        return self.get_site_base_url(self.get_active_site())

    def set_active_site(self, site: str):
        """切换当前站点，并同步 tabbit.base_url。"""
        sites = self.get_sites()
        if site not in sites:
            raise ValueError(f"unknown site: {site}")
        self.set_val("tabbit", "active_site", site)
        self.set_val("tabbit", "base_url", sites[site]["base_url"])
