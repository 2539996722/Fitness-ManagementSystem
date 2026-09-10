"""日志配置（基于 loguru）。"""

import sys

from loguru import logger


def _inject_request_id(record):
    """从 ContextVar 取 request_id，注入到每条日志 extra。"""
    from app.core.tracing import get_request_id

    record["extra"].setdefault("request_id", get_request_id() or "-")


def configure_logging(level: str = "INFO") -> None:
    """配置 loguru。

    - 控制台彩色输出（开发）
    - 生产可改为 JSON 输出（未实现，按需扩展）
    """
    logger.remove()  # 移除默认 handler

    logger.add(
        sys.stderr,
        level=level,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
            "<level>{level: <8}</level> | "
            "rid=<magenta>{extra[request_id]}</magenta> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
            "<level>{message}</level>"
        ),
        filter=_inject_request_id,
        backtrace=True,
        diagnose=False,
        enqueue=True,  # 异步写入，多线程安全
    )

    # 文件日志（生产环境启用）
    # logger.add(
    #     "logs/fithub_{time:YYYY-MM-DD}.log",
    #     rotation="00:00",
    #     retention="30 days",
    #     compression="zip",
    #     level=level,
    #     encoding="utf-8",
    # )

    logger.info("📝 日志系统已初始化 | level={}", level)


# 在模块导入时即初始化默认配置（INFO）
# 应用启动时会被 main.py 的 lifespan 重新配置
configure_logging()