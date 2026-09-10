"""RequestId middleware — 读 / 生成 X-Request-ID，存入 ContextVar，回写响应头。"""
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
from starlette.requests import Request

from app.core.tracing import set_request_id, new_request_id


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get("X-Request-ID") or new_request_id()
        set_request_id(rid)
        request.state.request_id = rid
        response: Response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        return response