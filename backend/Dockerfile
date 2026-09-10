# ============================================
# FitHub FastAPI 后端 Dockerfile
# ============================================
# 构建：
#   docker build -t fithub-backend .
# 运行：
#   docker run -p 8000:8000 --env-file .env fithub-backend
# ============================================

# ---------- 阶段 1：构建依赖 ----------
FROM python:3.11-slim AS builder

# 避免 Python 输出缓冲
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

# 系统依赖（构建阶段需要 gcc 编译 cryptography、bcrypt）
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    default-libmysqlclient-dev \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

# 单独装依赖（利用 Docker 层缓存）
COPY requirements.txt .
RUN pip install --prefix=/install -r requirements.txt

# ---------- 阶段 2：运行时镜像 ----------
FROM python:3.11-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Asia/Shanghai \
    PATH="/app/.local/bin:${PATH}"

# 运行时系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    default-libmysqlclient-dev \
    tzdata \
    curl \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime \
    && echo $TZ > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

# 从构建阶段复制已安装的包
COPY --from=builder /install /usr/local

# 创建非 root 用户
RUN useradd --create-home --shell /bin/bash --uid 1000 appuser \
    && mkdir -p /app /app/data /app/data/chroma /app/data/uploads \
    && chown -R appuser:appuser /app

WORKDIR /app

# 复制代码
COPY --chown=appuser:appuser . .

USER appuser

EXPOSE 8000

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# 默认启动命令（开发模式，支持 reload）
# 生产请改为：
#   ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]