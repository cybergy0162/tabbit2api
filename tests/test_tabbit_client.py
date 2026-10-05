"""基础单测：TabbitClient 的 base_url / user_id / 档位处理（无需联网）。"""
import base64
import json

from core.tabbit_client import (
    TabbitClient,
    fetch_model_map,
    fetch_model_map_ex,
    get_model_access_type,
    MODEL_MAP,
    TIERS_FREE,
    TIERS_PREMIUM,
)


def _fake_jwt(payload: dict) -> str:
    def seg(d):
        return base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()
    return f"{seg({'alg': 'RS256'})}.{seg(payload)}.sig"


def test_default_base_url_is_cn_domain():
    # TabbitClient 自身默认=国内版 tabbit.com；实际运行由配置/站点决定
    c = TabbitClient("x.y.z")
    assert c.base_url == "https://web.tabbit.com"


def test_base_url_override_international():
    c = TabbitClient("x.y.z", base_url="https://web.tabbit.ai")
    assert c.base_url == "https://web.tabbit.ai"


def test_user_id_extracted_from_jwt():
    tok = _fake_jwt({"id": "00000000-0000-0000-0000-000000000000"})
    c = TabbitClient(tok)
    assert c.user_id == "00000000-0000-0000-0000-000000000000"


def test_fetch_model_map_accepts_base_url():
    # 验证签名/参数透传（不实际发请求）
    import inspect
    assert "base_url" in inspect.signature(fetch_model_map).parameters
    assert "base_url" in inspect.signature(fetch_model_map_ex).parameters


def test_model_map_has_known_entries():
    assert "default" in MODEL_MAP
    assert "kimi-k3" in MODEL_MAP


def test_default_model_access_type_is_free_unlimited():
    # 未加载上游元数据时，default/best 视为免费无限档
    assert get_model_access_type("default") == "free_unlimited"
    assert get_model_access_type("best") == "free_unlimited"


def test_tier_constants():
    assert "free_unlimited" in TIERS_FREE
    assert "free_metered" in TIERS_FREE
    assert "premium_only" in TIERS_PREMIUM
    assert not (TIERS_FREE & TIERS_PREMIUM)
