"""llm_service 客户端管理：_get_client 缓存 + close_http_client 清理。

验证 SSE 断连修复的核心逻辑：
- 同一 (api_base, api_key) 复用 AsyncOpenAI + httpx.AsyncClient
- close_http_client() 后 cache 清空 + httpx.AsyncClient.aclose() 被调用
- 下次 _get_client() 会重新创建
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import llm_service


@pytest.fixture(autouse=True)
def clear_client_cache():
    """每个测试前后清空 _client_cache，避免污染。"""
    llm_service._client_cache.clear()
    yield
    llm_service._client_cache.clear()


def _make_fake_httpx_client() -> MagicMock:
    """构造一个 isinstance(_, httpx.AsyncClient) 通过的 mock。"""
    import httpx
    fake = MagicMock(spec=httpx.AsyncClient)
    fake.aclose = AsyncMock()
    return fake


class TestCloseHttpClient:
    """close_http_client：SSE 断连时强制关闭上游 httpx 连接。"""

    @pytest.mark.asyncio
    async def test_cache_hit_aclose_called(self):
        """cache 里有对应 client → aclose 被调用 + cache 清空。"""
        fake_http = _make_fake_httpx_client()
        fake_openai = MagicMock(spec=["_client"])  # 只有 _client 属性
        fake_openai._client = fake_http
        llm_service._client_cache[("base1", "key1")] = fake_openai

        await llm_service.close_http_client("base1", "key1")

        fake_http.aclose.assert_awaited_once()
        assert ("base1", "key1") not in llm_service._client_cache

    @pytest.mark.asyncio
    async def test_cache_miss_no_error(self):
        """cache miss → 不抛异常，安静返回。"""
        await llm_service.close_http_client("base_x", "key_x")  # 不应抛
        assert llm_service._client_cache == {}

    @pytest.mark.asyncio
    async def test_aclose_error_swallowed(self):
        """aclose 抛异常时，记录 warning 但不传播；cache 仍要清。"""
        import httpx
        fake_http = MagicMock(spec=httpx.AsyncClient)
        fake_http.aclose = AsyncMock(side_effect=RuntimeError("connection already closed"))
        fake_openai = MagicMock(spec=["_client"])
        fake_openai._client = fake_http
        llm_service._client_cache[("base2", "key2")] = fake_openai

        # 不应抛
        await llm_service.close_http_client("base2", "key2")
        # cache 仍清（避免下次拿到坏 client）
        assert ("base2", "key2") not in llm_service._client_cache

    @pytest.mark.asyncio
    async def test_fallback_to_http_client_attr(self):
        """部分 openai SDK 版本用 http_client 字段而非 _client。"""
        fake_http = _make_fake_httpx_client()
        fake_openai = MagicMock(spec=["http_client"])  # 只有 http_client 属性
        fake_openai.http_client = fake_http
        llm_service._client_cache[("base3", "key3")] = fake_openai

        await llm_service.close_http_client("base3", "key3")
        fake_http.aclose.assert_awaited_once()
        assert ("base3", "key3") not in llm_service._client_cache

    @pytest.mark.asyncio
    async def test_no_http_client_attr_noop(self):
        """OpenAI client 没用自定义 httpx（走 SDK 默认连接池）时，安静返回。"""
        class BareClient:
            pass

        bare = BareClient()
        llm_service._client_cache[("base4", "key4")] = bare

        # 不应抛
        await llm_service.close_http_client("base4", "key4")
        # cache 仍清理（避免累积过期引用）
        assert ("base4", "key4") not in llm_service._client_cache


class TestGetClientCaching:
    """_get_client 缓存语义：同 (api_base, api_key) 命中；不同 key 各自独立。"""

    def test_same_key_returns_cached(self):
        """同一 key 两次调用，返回同一对象。"""
        # patch openai 真实模块里的 AsyncOpenAI（llm_service 内部 from openai import AsyncOpenAI）
        # httpx 在 llm_service 函数内 import，需要 patch 'httpx.AsyncClient'
        import httpx
        import openai
        with patch.object(openai, "AsyncOpenAI") as MockAI, \
             patch.object(httpx, "AsyncClient") as MockHttpxClient:
            MockHttpxClient.return_value = MagicMock()
            MockAI.return_value = "fake_client_1"

            c1 = llm_service._get_client("base", "key")
            c2 = llm_service._get_client("base", "key")

            assert c1 is c2
            assert MockAI.call_count == 1

    def test_different_key_creates_new(self):
        """不同 api_key 各自独立。"""
        import httpx
        import openai
        with patch.object(openai, "AsyncOpenAI") as MockAI, \
             patch.object(httpx, "AsyncClient") as MockHttpxClient:
            MockHttpxClient.return_value = MagicMock()
            MockAI.side_effect = ["client_a", "client_b"]

            c1 = llm_service._get_client("base", "key_a")
            c2 = llm_service._get_client("base", "key_b")

            assert c1 == "client_a"
            assert c2 == "client_b"
            assert MockAI.call_count == 2
