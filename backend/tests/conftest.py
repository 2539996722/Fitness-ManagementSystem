"""共享测试 fixtures。

- 纯函数测试：无需任何 fixture
- Chroma 集成测试：`cleanup_test_kb`（autouse）隔离 kb_9999
- Mock embedding：`mock_embed` fixture 替换 LLM embedding
- MySQL 集成测试：`integration_session` fixture（自动建 fithub_test 库，嵌套事务 rollback）

策略：
- mock_embed + integration_session 可同时使用：
  mock 替换 LLM，真实 DB 写入
- function-scoped：避免 event loop 冲突（pytest-asyncio 默认 test loop 是 function）
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
    """每个测试前后自动清理 kb_9999 collection，防止跨测试数据污染。"""
    from app.services.kb_service import delete_kb_collection
    delete_kb_collection(kb_id)
    yield
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
        seed = int.from_bytes(hashlib.md5(text.encode("utf-8")).digest()[:4], "big")
        v = []
        for i in range(dim):
            v.append(((seed >> i) & 0xFF) / 255.0)
        norm = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / norm for x in v]

    async def fake_embed_documents(texts):
        return [_fake_vec(t) for t in texts]

    async def fake_embed_query(text):
        return _fake_vec(text)

    from app.services import embedding_service
    monkeypatch.setattr(embedding_service, "embed_documents", fake_embed_documents)
    monkeypatch.setattr(embedding_service, "embed_query", fake_embed_query)
    return _fake_vec


# ============ MySQL 集成 fixture（可选，需要本地 MySQL）============

def _mysql_reachable(host="localhost", port=3306, timeout=1.0) -> bool:
    """探测 MySQL 是否可达。"""
    import socket
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (OSError, socket.timeout):
        return False


@pytest.fixture(scope="session")
def mysql_available() -> bool:
    """session 级：探测一次 MySQL 是否在线。"""
    return _mysql_reachable()


@pytest.fixture
def integration_db_url(mysql_available) -> str:
    """返回测试用 DSN。若 MySQL 不可用则跳过测试。"""
    if not mysql_available:
        pytest.skip("MySQL 不可达，跳过集成测试")

    from app.core.config import settings
    import re
    dsn = settings.mysql_dsn
    test_dsn = re.sub(r"/fithub(\?|$)", r"/fithub_test\1", dsn)
    return test_dsn


@pytest.fixture
async def bootstrap_test_db(integration_db_url):
    """每个 test 前确保 fithub_test 库存在（async，与 test 共享 loop）。"""
    import re
    from sqlalchemy.ext.asyncio import create_async_engine

    server_dsn = re.sub(r"/fithub_test(\?|$)", r"/\1", integration_db_url)
    engine = create_async_engine(server_dsn, isolation_level="AUTOCOMMIT")
    async with engine.connect() as conn:
        await conn.exec_driver_sql(
            "CREATE DATABASE IF NOT EXISTS fithub_test "
            "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
        )
    await engine.dispose()


@pytest.fixture
async def integration_session(integration_db_url, bootstrap_test_db):
    """异步 DB session（嵌套事务，测试结束自动 rollback）。"""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.db.base import Base
    engine = create_async_engine(integration_db_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        await session.begin_nested()
        yield session
        await session.rollback()

    await engine.dispose()
