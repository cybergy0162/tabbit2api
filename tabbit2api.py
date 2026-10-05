#!/usr/bin/env python3
import logging
from pathlib import Path
from contextlib import asynccontextmanager

import asyncio
import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

from core.config import ConfigManager
from core.token_manager import TokenManager
from core.log_store import LogStore
import core.tabbit_client as tabbit_client
from core.tabbit_client import fetch_model_map_ex, update_model_map_for_site, activate_site, set_active_site_marker
from routes import openai_compat, admin_api, claude_api

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("tabbit2openai")

# ── 初始化核心组件 ──
cfg = ConfigManager()
token_manager = TokenManager(cfg)
log_store = LogStore(max_entries=cfg.get("logging", "max_entries", default=500))

# ── 初始化路由模块 ──
openai_compat.init(token_manager, cfg, log_store)
admin_api.init(cfg, token_manager, log_store)
claude_api.init(token_manager, cfg, log_store)


async def _refresh_active_site_models():
    """抓取当前激活站点的模型目录（用该站点的 token）。"""
    site = cfg.get_active_site()
    base_url = cfg.get_site_base_url(site)
    tokens = [t for t in cfg.get("tokens", default=[])
              if (t.get("site") or "intl") == site and t.get("value")]
    if not tokens:
        logger.warning(f"站点 {site} 下没有可用 token，跳过模型刷新")
        return 0
    new_models, meta = await fetch_model_map_ex(tokens[0]["value"], base_url)
    if new_models:
        update_model_map_for_site(site, new_models, meta)
        set_active_site_marker(site)
        activate_site(site)
        logger.info(f"Updated model map (site={site}, {len(new_models)} models) from {base_url}")
        return len(new_models)
    return 0


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时按配置激活站点（同步全局模型视图）
    _init_site = cfg.get_active_site()
    set_active_site_marker(_init_site)
    activate_site(_init_site)
    logger.info(
        "Tabbit2API started — site: %s (%s), tokens: %d, port: %d",
        _init_site,
        cfg.get_active_base_url(),
        len(cfg.get("tokens", default=[])),
        cfg.get("server", "port", default=8800),
    )

    # 启动时立即更新当前站点模型列表
    try:
        await _refresh_active_site_models()
    except Exception as e:
        logger.error(f"Failed to update model map on startup: {e}")
    
    # 后台任务：定期更新当前站点模型列表
    async def update_models_periodically():
        while True:
            try:
                await _refresh_active_site_models()
            except Exception as e:
                logger.error(f"Failed to update model map: {e}")
            await asyncio.sleep(3600)  # 每小时更新一次
    
    task = asyncio.create_task(update_models_periodically())
    
    yield
    
    task.cancel()
    await token_manager.close_all()


app = FastAPI(lifespan=lifespan)

# ── CORS 中间件 ──
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── 挂载路由 ──
app.include_router(claude_api.router)  # Claude Messages API（/v1/messages）
app.include_router(openai_compat.router)  # OpenAI 兼容（/v1/chat/completions）
app.include_router(admin_api.router)

# ── 静态文件 & 管理面板入口 ──
static_dir = Path(__file__).parent / "static"
if static_dir.exists() and static_dir.is_dir():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    logger.info(f"Static files mounted from: {static_dir}")
else:
    logger.warning(f"Static directory not found: {static_dir}")


@app.get("/admin")
async def admin_page():
    if static_dir.exists() and (static_dir / "index.html").exists():
        return FileResponse(
            str(static_dir / "index.html"),
            headers={"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache", "Expires": "0"},
        )
    else:
        return {"error": "Admin panel not available", "message": "Static files not found. Please check if static directory exists."}


@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "Tabbit2API"}


if __name__ == "__main__":
    import urllib3

    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    uvicorn.run(
        app,
        host=cfg.get("server", "host", default="0.0.0.0"),
        port=cfg.get("server", "port", default=8800),
    )
