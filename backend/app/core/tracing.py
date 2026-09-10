"""RequestId / trace_id 全链路上下文。

通过 ContextVar 在 asyncio 任务内传递，不依赖全局变量。
每个 HTTP 请求由 RequestIdMiddleware 注入；也可在脚本/CLI 手动用 trace_id_scope。
"""
from contextvars import ContextVar
from uuid import uuid4

_request_id_ctx: ContextVar[str | None] = ContextVar("request_id", default=None)


def get_request_id() -> str | None:
    return _request_id_ctx.get()


def set_request_id(rid: str) -> None:
    _request_id_ctx.set(rid)


def new_request_id() -> str:
    """生成 32 字符无连字符的 UUID（便于日志搜索/数据库索引）。"""
    return uuid4().hex


class trace_id_scope:
    """代码块内临时设置 request_id；退出时还原。

    用法：
        with trace_id_scope() as rid:
            logger.info("do something")  # 日志自动带 rid
    """

    def __init__(self, rid: str | None = None):
        self.rid = rid or new_request_id()
        self._token = None

    def __enter__(self):
        self._token = _request_id_ctx.set(self.rid)
        return self.rid

    def __exit__(self, *exc):
        _request_id_ctx.reset(self._token)