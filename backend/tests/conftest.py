"""共享测试 fixtures。

- 纯函数测试：无需任何 fixture
- Chroma 集成测试：用 `chroma_collection` fixture（独立 collection，避免污染生产数据）
- DB 集成测试：暂未实现（生产建议接 testcontainers）
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# 让 `from app.xxx import yyy` 能跑通
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


# ============ 修复 starlette.config.Config 的 .env 读取编码 ============
# 与 backend/app/main.py 同款 patch：slowapi 初始化时会读 .env，
# Windows 默认 GBK 编码会失败。强制 UTF-8。
import starlette.config


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


# ============ Chroma 集成 fixture ============

@pytest.fixture
def kb_id() -> int:
    """每个测试用一个独立 KB id（9999 起），避免冲突。"""
    return 9999


@pytest.fixture(autouse=True)
def cleanup_test_kb(kb_id):
    """每个测试前后自动清理 kb_9999 collection，防止跨测试数据污染。

    autouse=True → 不需要在测试函数里显式声明。
    """
    from app.services.kb_service import delete_kb_collection
    # 测试前先清
    delete_kb_collection(kb_id)
    yield
    # 测试后再清
    delete_kb_collection(kb_id)


# ============ Mock embedding fixture ============

@pytest.fixture
def mock_embed(monkeypatch):
    """把 embed_documents / embed_query 替换成确定性 fake。

    用 hash 当作向量，保证同一文本 → 同一向量；
    不同文本 → 不同向量（让相似度检索有意义）。
    """
    import hashlib
    import math

    def _fake_vec(text: str, dim: int = 8) -> list[float]:
        # 8 维够测试用了
        seed = int.from_bytes(hashlib.md5(text.encode("utf-8")).digest()[:4], "big")
        v = []
        for i in range(dim):
            v.append(((seed >> i) & 0xFF) / 255.0)
        # 归一化（cosine 距离要归一化向量）
        norm = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / norm for x in v]

    async def fake_embed_documents(texts):
        return [_fake_vec(t) for t in texts]

    async def fake_embed_query(text):
        # embed_query 返回单条 1-dim 向量（与 embed_documents 返回的 list[list[float] 不同）
        return _fake_vec(text)

    from app.services import embedding_service
    monkeypatch.setattr(embedding_service, "embed_documents", fake_embed_documents)
    monkeypatch.setattr(embedding_service, "embed_query", fake_embed_query)
    # kb_service 是函数内部 import，不能在模块层级 setattr；
    # 函数内部 `from app.services.embedding_service import embed_documents`
    # 会重新走 sys.modules 查找，所以 mock embedding_service.embed_documents 已足够
    return _fake_vec
