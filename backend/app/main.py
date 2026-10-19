"""FastAPI 应用入口。

统一入口（前后端共一个端口）：

启动方式：
    uvicorn app.main:app --reload --port 8000

访问入口：
    http://localhost:8000/             # 重定向到 /c/
    http://localhost:8000/c/           # C 端首页
    http://localhost:8000/c/login.html
    http://localhost:8000/c/detail.html?id=0001
    http://localhost:8000/admin/       # B 端首页
    http://localhost:8000/admin/login.html
    http://localhost:8000/api/v1/...   # API
    http://localhost:8000/docs         # Swagger UI

部署：
    gunicorn app.main:app -w 4 -k uvicorn.workers.UvicornWorker
"""

from contextlib import asynccontextmanager
from pathlib import Path

import starlette.config
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from loguru import logger
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

# Monkey patch: starlette.config.Config opens .env without specifying encoding.
# On Windows the default codec is GBK, which fails on Chinese comments in .env.
# Force UTF-8 so slowapi (which calls Config internally) can read .env cleanly.
_original_read_file = starlette.config.Config._read_file


def _read_file_utf8(self, file_name):
    file_values: dict[str, str] = {}
    try:
        with open(file_name, encoding="utf-8") as input_file:
            for line in input_file.readlines():
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    key, value = line.split("=", 1)
                    file_values[key.strip()] = value.strip().strip("\"'")
    except FileNotFoundError:
        pass
    return file_values


starlette.config.Config._read_file = _read_file_utf8

from app.api.v1 import api_router
from app.core.config import settings
from app.core.logging import configure_logging
from app.db.session import engine

# 前端静态文件目录（项目根目录 / web/）
# __file__ = backend/app/main.py → 父级父级 = 项目根
PROJECT_ROOT = Path(__file__).resolve().parents[2]
WEB_DIR = PROJECT_ROOT / "web"
C_DIR = WEB_DIR / "c"
ADMIN_DIR = WEB_DIR / "admin"


class NoCacheStaticFiles(StaticFiles):
    """禁用缓存的静态文件服务。

    开发模式下，前端代码频繁改动，但浏览器会因为 304 缓存命中而不重新加载。
    这个类在响应头里强制 no-cache、no-store、must-revalidate。
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        # 强制每次都重新加载
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期。"""
    configure_logging(settings.log_level)
    logger.info(
        "🚀 FitHub 启动中 | env={env} | debug={debug}",
        env=settings.app_env,
        debug=settings.debug,
    )
    logger.info("📖 API 文档：http://{host}:{port}/docs", host=settings.host, port=settings.port)
    logger.info("💪 C 端首页：http://{host}:{port}/c/", host=settings.host, port=settings.port)
    logger.info("⚙️ B 端后台：http://{host}:{port}/admin/", host=settings.host, port=settings.port)

    yield

    logger.info("🛑 FitHub 关闭中...")
    await engine.dispose()
    logger.info("✅ 数据库连接池已释放")


def create_app() -> FastAPI:
    """应用工厂。"""
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description="FitHub 健身管理系统 API",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    # ---------- CORS ----------
    # 注意：因为前后端同源（同端口），CORS 主要用于本地分离开发场景
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=settings.cors_allow_credentials,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ---------- RequestId（M10+ 全链路追踪）----------
    # 注意：注册顺序 = 外层先执行。CORS 在外，RequestId 在内。
    # 顺序：客户端 → RequestId (注入 rid) → CORS → ... → handler
    from app.middleware.request_id import RequestIdMiddleware
    app.add_middleware(RequestIdMiddleware)

    # ---------- 限流 ----------
    app.state.limiter = settings.limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    # ---------- API 路由 ----------
    app.include_router(api_router, prefix="/api/v1")

    # ---------- 静态资源：动作 GIF / 缩略图 ----------
    # 候选路径（按优先级）：
    #   1. 环境变量 EXERCISES_DATA_DIR（绝对路径）
    #   2. settings.exercises_path（相对 cwd）
    #   3. 项目根 /data/exercises-dataset-zh（绝对路径，最稳）
    #   4. 项目根 /data/exercises-dataset-zh-master/exercises-dataset-zh-master（嵌套解压）
    candidate_paths = []
    if settings.exercises_path:
        candidate_paths.append(settings.exercises_path)
    candidate_paths.append(PROJECT_ROOT / "data" / "exercises-dataset-zh")
    candidate_paths.append(PROJECT_ROOT / "data" / "exercises-dataset-zh-master" / "exercises-dataset-zh-master")
    candidate_paths.append(PROJECT_ROOT / "data" / "exercises-dataset-zh-master")
    # 也扫一下 data 下的所有子目录（兼容不同解压结构）
    data_root = PROJECT_ROOT / "data"
    if data_root.exists():
        for sub in data_root.iterdir():
            if sub.is_dir():
                candidate_paths.append(sub)
                # 再往里一层
                for subsub in sub.iterdir():
                    if subsub.is_dir() and subsub != sub:
                        candidate_paths.append(subsub)

    images_dir = videos_dir = None
    for base in candidate_paths:
        cand_img = base / "images"
        cand_vid = base / "videos"
        if cand_img.exists() and cand_vid.exists():
            images_dir = cand_img
            videos_dir = cand_vid
            break

    if images_dir and videos_dir:
        app.mount("/static/images", StaticFiles(directory=str(images_dir)), name="exercise-images")
        app.mount("/static/videos", StaticFiles(directory=str(videos_dir)), name="exercise-videos")
        logger.info("📸 缩略图已挂载：/static/images → {}", images_dir)
        logger.info("🎬 GIF 已挂载：/static/videos → {}", videos_dir)
    else:
        logger.warning("⚠️ 数据集 images/videos 目录未找到，候选路径：")
        for base in candidate_paths:
            logger.warning("   - {} (images: {}, videos: {})",
                           base, (base / "images").exists(), (base / "videos").exists())

    # ---------- 前端静态文件 ----------
    # C 端：/c/* 映射到 web/c/*
    if C_DIR.exists():
        app.mount("/c", NoCacheStaticFiles(directory=str(C_DIR), html=True), name="c-frontend")
        logger.info("💪 C 端已挂载：/c/* → {}", C_DIR)
    else:
        logger.warning("⚠️ C 端目录不存在：{}", C_DIR)

    # B 端：/admin/* 映射到 web/admin/*
    if ADMIN_DIR.exists():
        app.mount("/admin", NoCacheStaticFiles(directory=str(ADMIN_DIR), html=True), name="admin-frontend")
        logger.info("⚙️ B 端已挂载：/admin/* → {}", ADMIN_DIR)
    else:
        logger.warning("⚠️ B 端目录不存在：{}", ADMIN_DIR)

    # ---------- 根路径：重定向到 C 端 ----------
    @app.get("/", include_in_schema=False)
    async def root():
        """默认首页：重定向到 C 端。"""
        return RedirectResponse(url="/c/", status_code=302)

    @app.get("/portal", include_in_schema=False)
    async def portal():
        """入口选择页：让用户选择 C 端或 B 端。"""
        return HTMLResponse(content=_PORTAL_HTML)

    # ---------- favicon：返回 1x1 透明 png，静默浏览器自动请求 ----------
    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon():
        return Response(content=FAVICON_PNG, media_type="image/png")

    # ---------- 全局异常处理 ----------
    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request, exc):
        logger.exception("Unhandled exception: {}", exc)
        from fastapi.responses import JSONResponse

        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
        )

    return app


app = create_app()


# ========== 入口选择页 HTML ==========
# 1x1 透明 PNG（67 bytes），用于静默浏览器自动请求 /favicon.ico
FAVICON_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\xff"
    b"\xff?\x00\x05\xfe\x02\xfe\x86\xa6\x9cH\x00\x00\x00\x00IEND\xaeB`\x82"
)

_PORTAL_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>FitHub · 入口</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
            background: linear-gradient(135deg, #ff6b35 0%, #f7931e 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            color: #1a1a1a;
        }
        .portal {
            background: white;
            padding: 48px 64px;
            border-radius: 24px;
            box-shadow: 0 16px 48px rgba(0, 0, 0, 0.15);
            max-width: 720px;
            width: 90%;
            text-align: center;
        }
        .portal__logo { font-size: 64px; margin-bottom: 16px; }
        .portal__title { font-size: 32px; font-weight: bold; margin-bottom: 8px; }
        .portal__subtitle { color: #6b7280; font-size: 14px; margin-bottom: 40px; }
        .portal__choices {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 24px;
        }
        .portal__card {
            display: block;
            padding: 32px 24px;
            border: 2px solid #e5e7eb;
            border-radius: 16px;
            text-decoration: none;
            color: inherit;
            transition: all 0.2s;
        }
        .portal__card:hover {
            border-color: #ff6b35;
            transform: translateY(-4px);
            box-shadow: 0 8px 24px rgba(255, 107, 53, 0.15);
        }
        .portal__card-icon { font-size: 48px; margin-bottom: 12px; }
        .portal__card-title { font-size: 20px; font-weight: 600; margin-bottom: 8px; }
        .portal__card-desc { color: #6b7280; font-size: 13px; line-height: 1.5; }
        .portal__card--admin { border-color: #1e293b; }
        .portal__card--admin:hover { border-color: #1e293b; box-shadow: 0 8px 24px rgba(30, 41, 59, 0.15); }
        .portal__footer {
            margin-top: 32px;
            color: #9ca3af;
            font-size: 12px;
        }
        .portal__footer a { color: #ff6b35; text-decoration: none; }
        @media (max-width: 480px) {
            .portal__choices { grid-template-columns: 1fr; }
            .portal { padding: 32px 24px; }
        }
    </style>
</head>
<body>
    <div class="portal">
        <div class="portal__logo">💪</div>
        <h1 class="portal__title">FitHub</h1>
        <p class="portal__subtitle">健身动作库 · AI 教练 · 一体化管理系统</p>

        <div class="portal__choices">
            <a href="/c/" class="portal__card">
                <div class="portal__card-icon">🏋️</div>
                <div class="portal__card-title">C 端 · 用户端</div>
                <div class="portal__card-desc">
                    浏览 1,324 个健身动作<br>
                    创建训练计划<br>
                    与 AI 教练对话
                </div>
            </a>
            <a href="/admin/" class="portal__card portal__card--admin">
                <div class="portal__card-icon">⚙️</div>
                <div class="portal__card-title">B 端 · 管理后台</div>
                <div class="portal__card-desc">
                    会员管理<br>
                    教练工作台<br>
                    计划模板审核
                </div>
            </a>
        </div>

        <div class="portal__footer">
            API 文档：<a href="/docs">/docs</a> ·
            健康检查：<a href="/api/v1/health">/api/v1/health</a>
        </div>
    </div>
</body>
</html>"""