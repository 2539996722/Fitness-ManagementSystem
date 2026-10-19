"""admin_knowledge_base.py 单测（全部 mock）。

覆盖端点清单（11 个）：
- GET    /admin/knowledge-bases                      list_kbs
- POST   /admin/knowledge-bases                      create_kb
- PATCH  /admin/knowledge-bases/{kb_id}              update_kb
- DELETE /admin/knowledge-bases/{kb_id}              delete_kb
- GET    /admin/knowledge-bases/{kb_id}/documents    list_documents
- GET    /admin/knowledge-bases/{kb_id}/documents/{doc_id}/chunks  get_document_chunks
- POST   /admin/knowledge-bases/{kb_id}/documents    upload_document
- DELETE /admin/knowledge-bases/{kb_id}/documents/{doc_id}          delete_document
- POST   /admin/knowledge-bases/{kb_id}/documents/{doc_id}/rebuild  rebuild_document
- POST   /admin/knowledge-bases/{kb_id}/retrieval-test              retrieval_test

全局 admin 依赖在 router 上，单元测试不重复验证。

mock 约定：
- AsyncSession 用 `_mock_session_*` 辅助（与 test_trainer.py 风格一致）
- chroma / 文件 IO / 后台 ingest 全部 monkeypatch 掉
- `settings.upload_dir` / `settings.upload_max_size_mb` 用 monkeypatch.setattr 替换
"""
from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.api.v1.admin_knowledge_base import (
    create_kb,
    delete_document,
    delete_kb,
    get_document_chunks,
    list_documents,
    list_kbs,
    rebuild_document,
    retrieval_test,
    update_kb,
    upload_document,
)
from app.schemas.knowledge_base import (
    KnowledgeBaseCreate,
    KnowledgeBaseUpdate,
    RetrievalTestIn,
)


# ============ Helpers ============

def _make_admin(id=1, username="admin1", role="admin"):
    return SimpleNamespace(
        id=id, username=username, role=role,
        nickname=username, avatar_url=None,
        status=0, is_deleted=False, is_banned=False, is_locked=False,
    )


def _make_kb(
    id=1, name="训练动作库", description=None,
    enabled=True, chunk_size=500, chunk_overlap=80,
    top_k=5, similarity_threshold=0.0,
    created_by=1, created_at=None, updated_at=None,
):
    return SimpleNamespace(
        id=id, name=name, description=description,
        enabled=enabled, chunk_size=chunk_size, chunk_overlap=chunk_overlap,
        top_k=top_k, similarity_threshold=similarity_threshold,
        created_by=created_by,
        created_at=created_at or datetime(2024, 1, 1),
        updated_at=updated_at or datetime(2024, 1, 1),
    )


def _make_doc(
    id=1, kb_id=1, filename="a.txt", storage_path="/tmp/kb/x.txt",
    ext="txt", size_bytes=100, status="ready", chunk_count=5,
    error_message=None, uploaded_by=1,
    created_at=None, updated_at=None,
):
    return SimpleNamespace(
        id=id, kb_id=kb_id, filename=filename, storage_path=storage_path,
        ext=ext, size_bytes=size_bytes, status=status, chunk_count=chunk_count,
        error_message=error_message, uploaded_by=uploaded_by,
        created_at=created_at or datetime(2024, 1, 1),
        updated_at=updated_at or datetime(2024, 1, 1),
    )


def _mock_session():
    """通用 mock session：commit / refresh / flush / delete / add 都可用。"""
    session = AsyncMock()
    nxt = {"id": 1000}

    async def fake_refresh(obj):
        if getattr(obj, "id", None) is None:
            obj.id = nxt["id"]; nxt["id"] += 1
        now = datetime(2024, 1, 1)
        if getattr(obj, "created_at", None) is None:
            obj.created_at = now
        if getattr(obj, "updated_at", None) is None:
            obj.updated_at = now

    session.refresh.side_effect = fake_refresh
    session.commit = AsyncMock()
    session.flush = AsyncMock()
    session.add = MagicMock()
    session.delete = AsyncMock()
    session.get = AsyncMock(return_value=None)
    return session


# ============ 列出 KB ============

class TestListKBs:

    @pytest.mark.asyncio
    async def test_list_no_filter(self):
        """无 enabled 过滤：返回全部 KB + 文档/分片统计。"""
        kbs = [_make_kb(id=i, name=f"kb{i}") for i in range(3)]
        session = AsyncMock()
        # list_kbs 内部多次 execute：
        # 1) count(*)  2) rows.select   3-n) 每个 kb doc_count + chunk_count
        # 简化为：第一个 return rows，第二个 return 0，循环内每次 0
        results = []
        # 1: total count
        results.append(MagicMock(scalar=MagicMock(return_value=3)))
        # 2: rows (scalars().all())
        results.append(MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=kbs)))))
        # 3-8: doc_count + chunk_count × 3 个 KB
        for _ in range(6):
            results.append(MagicMock(scalar=MagicMock(return_value=0)))
        session.execute.side_effect = results

        result = await list_kbs(session, enabled=None, limit=50, offset=0)
        assert result.total == 3
        assert len(result.items) == 3
        assert result.items[0].document_count == 0


# ============ 新建 KB ============

class TestCreateKB:

    @pytest.mark.asyncio
    async def test_create_success(self):
        session = AsyncMock()
        # 唯一性检查：scalar_one_or_none() = None
        r_check = MagicMock(); r_check.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=r_check)
        # commit/refresh/add
        nxt = {"id": 42}
        async def fake_refresh(obj):
            if getattr(obj, "id", None) is None:
                obj.id = nxt["id"]
            now = datetime(2024, 1, 1)
            if getattr(obj, "created_at", None) is None:
                obj.created_at = now
            if getattr(obj, "updated_at", None) is None:
                obj.updated_at = now
        session.refresh.side_effect = fake_refresh
        session.commit = AsyncMock()
        session.add = MagicMock()

        body = KnowledgeBaseCreate(name="训练库")
        result = await create_kb(body, session, _make_admin())
        assert result.id == 42
        assert result.name == "训练库"
        assert result.document_count == 0
        assert result.chunk_count == 0

    @pytest.mark.asyncio
    async def test_create_name_taken_400(self):
        """重名 → 400。"""
        session = AsyncMock()
        existing = _make_kb(name="训练库")
        r = MagicMock(); r.scalar_one_or_none.return_value = existing
        session.execute = AsyncMock(return_value=r)

        body = KnowledgeBaseCreate(name="训练库")
        with pytest.raises(HTTPException) as exc:
            await create_kb(body, session, _make_admin())
        assert exc.value.status_code == 400
        assert "已被占用" in exc.value.detail


# ============ 修改 KB ============

class TestUpdateKB:

    @pytest.mark.asyncio
    async def test_update_name_success(self):
        """get(kb) 命中 + 改名无冲突 + 执行 update。"""
        kb = _make_kb(name="旧名")
        session = AsyncMock()
        # 1) session.get(KnowledgeBase, 1) -> kb
        # 2) 唯一性 check (无冲突, None)
        # 3) doc_count  4) chunk_count
        results = [
            MagicMock(scalar_one_or_none=MagicMock(return_value=None)),
        ]
        session.execute = AsyncMock(side_effect=results)
        session.get = AsyncMock(return_value=kb)
        session.commit = AsyncMock()
        nxt = {"id": 1}
        async def fake_refresh(obj):
            obj.updated_at = datetime(2024, 1, 2)
        session.refresh.side_effect = fake_refresh
        session.add = MagicMock()

        # doc_count + chunk_count 查询（update_kb 末尾）
        # 它们走 session.execute 但 side_effect 已经耗尽，需要更多 result
        r1 = MagicMock(); r1.scalar_one_or_none.return_value = None  # 唯一性 check
        r2 = MagicMock(); r2.scalar.return_value = 0  # doc_count
        r3 = MagicMock(); r3.scalar.return_value = 0  # chunk_count
        session.execute.side_effect = [r1, r2, r3]

        body = KnowledgeBaseUpdate(name="新名")
        result = await update_kb(1, body, session, _make_admin())
        assert result.name == "新名"
        assert kb.name == "新名"  # 已 mutate

    @pytest.mark.asyncio
    async def test_update_not_found_404(self):
        session = AsyncMock()
        session.get = AsyncMock(return_value=None)

        body = KnowledgeBaseUpdate(name="x")
        with pytest.raises(HTTPException) as exc:
            await update_kb(999, body, session, _make_admin())
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_update_name_conflict_400(self):
        kb = _make_kb(id=1, name="旧名")
        session = AsyncMock()
        session.get = AsyncMock(return_value=kb)
        # 唯一性 check → 命中另一个 KB
        r = MagicMock(); r.scalar_one_or_none.return_value = _make_kb(id=2)
        session.execute = AsyncMock(return_value=r)

        body = KnowledgeBaseUpdate(name="新名")
        with pytest.raises(HTTPException) as exc:
            await update_kb(1, body, session, _make_admin())
        assert exc.value.status_code == 400
        assert "已被占用" in exc.value.detail


# ============ 删除 KB ============

class TestDeleteKB:

    @pytest.mark.asyncio
    async def test_delete_success(self):
        kb = _make_kb(id=1, name="待删")
        session = AsyncMock()
        session.get = AsyncMock(return_value=kb)
        session.delete = AsyncMock()
        session.commit = AsyncMock()
        session.add = MagicMock()

        with patch("app.api.v1.admin_knowledge_base.delete_kb_collection") as mock_del_col:
            result = await delete_kb(1, session, _make_admin())
            assert result is None
            mock_del_col.assert_called_once_with(1)
            session.delete.assert_awaited_once_with(kb)

    @pytest.mark.asyncio
    async def test_delete_not_found_404(self):
        session = AsyncMock()
        session.get = AsyncMock(return_value=None)

        with patch("app.api.v1.admin_knowledge_base.delete_kb_collection"):
            with pytest.raises(HTTPException) as exc:
                await delete_kb(999, session, _make_admin())
            assert exc.value.status_code == 404


# ============ 列文档 ============

class TestListDocuments:

    @pytest.mark.asyncio
    async def test_list_success(self):
        kb = _make_kb(id=1)
        docs = [_make_doc(id=i, filename=f"d{i}.txt") for i in range(3)]
        session = AsyncMock()
        session.get = AsyncMock(return_value=kb)
        # 1) count total  2) rows
        r1 = MagicMock(); r1.scalar.return_value = 3
        r2 = MagicMock(); r2.scalars.return_value.all.return_value = docs
        session.execute = AsyncMock(side_effect=[r1, r2])

        result = await list_documents(1, session, limit=50, offset=0)
        assert result.total == 3
        assert len(result.items) == 3

    @pytest.mark.asyncio
    async def test_list_kb_not_found_404(self):
        session = AsyncMock()
        session.get = AsyncMock(return_value=None)
        with pytest.raises(HTTPException) as exc:
            await list_documents(999, session, limit=50, offset=0)
        assert exc.value.status_code == 404


# ============ 查看分片 ============

class TestGetChunks:

    @pytest.mark.asyncio
    async def test_get_chunks_success(self):
        kb = _make_kb(id=1, chunk_size=500)
        doc = _make_doc(id=10, kb_id=1, filename="笔记.txt")
        session = AsyncMock()
        # doc → kb → list_doc_chunks
        session.get = AsyncMock(side_effect=[doc, kb])

        # mock list_doc_chunks 返回 DocChunk 列表
        from app.services.kb_service import DocChunk
        fake_chunks = [
            DocChunk(chunk_index=0, text="第一段文本", char_count=5),
            DocChunk(chunk_index=1, text="第二段文本", char_count=5),
        ]
        with patch("app.api.v1.admin_knowledge_base.list_doc_chunks", return_value=fake_chunks):
            result = await get_document_chunks(1, 10, session)
            assert result.doc_id == 10
            assert result.kb_id == 1
            assert result.filename == "笔记.txt"
            assert result.chunk_size == 500
            assert len(result.chunks) == 2
            assert result.total_chars == 10

    @pytest.mark.asyncio
    async def test_get_chunks_doc_not_match_kb_404(self):
        """doc.kb_id != kb_id → 404。"""
        doc = _make_doc(id=10, kb_id=2)  # kb=2
        session = AsyncMock()
        session.get = AsyncMock(return_value=doc)  # 第一个 get → doc
        with patch("app.api.v1.admin_knowledge_base.list_doc_chunks"):
            with pytest.raises(HTTPException) as exc:
                await get_document_chunks(1, 10, session)  # 但查 kb_id=1
            assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_get_chunks_doc_not_found_404(self):
        session = AsyncMock()
        session.get = AsyncMock(return_value=None)
        with patch("app.api.v1.admin_knowledge_base.list_doc_chunks"):
            with pytest.raises(HTTPException) as exc:
                await get_document_chunks(1, 999, session)
            assert exc.value.status_code == 404


# ============ 上传文档 ============

class TestUploadDocument:

    @pytest.mark.asyncio
    async def test_upload_success(self, monkeypatch, tmp_path):
        kb = _make_kb(id=1, name="训练库", chunk_size=500, chunk_overlap=80)
        session = AsyncMock()
        session.get = AsyncMock(return_value=kb)
        nxt = {"id": 999}

        async def fake_refresh(obj):
            if getattr(obj, "id", None) is None:
                obj.id = nxt["id"]
            now = datetime(2024, 1, 1)
            if getattr(obj, "created_at", None) is None:
                obj.created_at = now
            if getattr(obj, "updated_at", None) is None:
                obj.updated_at = now
            if getattr(obj, "chunk_count", None) is None:
                obj.chunk_count = 0

        session.refresh.side_effect = fake_refresh
        session.commit = AsyncMock()
        session.add = MagicMock()

        # 替换 upload_dir 指向 tmp_path + mock 后台任务
        monkeypatch.setattr("app.core.config.settings.upload_dir", str(tmp_path))
        monkeypatch.setattr("app.core.config.settings.upload_max_size_mb", 10)

        # mock 后台 asyncio.create_task → 不真跑
        with patch("app.api.v1.admin_knowledge_base.asyncio.create_task") as mock_task:
            # mock UploadFile
            uf = MagicMock()
            uf.filename = "笔记.txt"
            uf.read = AsyncMock(return_value=b"hello world content")

            result = await upload_document(1, uf, session, _make_admin())
            assert result.document.id == 999
            assert result.document.filename == "笔记.txt"
            assert result.document.status == "processing"
            assert result.chunk_count == 0
            assert result.first_preview  # 非空
            # 后台 ingest 被调度
            mock_task.assert_called_once()

    @pytest.mark.asyncio
    async def test_upload_kb_not_found_404(self, monkeypatch, tmp_path):
        monkeypatch.setattr("app.core.config.settings.upload_dir", str(tmp_path))
        session = AsyncMock()
        session.get = AsyncMock(return_value=None)

        uf = MagicMock(); uf.filename = "a.txt"
        with pytest.raises(HTTPException) as exc:
            await upload_document(999, uf, session, _make_admin())
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_upload_bad_ext_400(self, monkeypatch, tmp_path):
        kb = _make_kb(id=1)
        monkeypatch.setattr("app.core.config.settings.upload_dir", str(tmp_path))
        session = AsyncMock()
        session.get = AsyncMock(return_value=kb)

        uf = MagicMock(); uf.filename = "bad.exe"
        with pytest.raises(HTTPException) as exc:
            await upload_document(1, uf, session, _make_admin())
        assert exc.value.status_code == 400
        assert "txt" in exc.value.detail or "md" in exc.value.detail

    @pytest.mark.asyncio
    async def test_upload_too_large_400(self, monkeypatch, tmp_path):
        kb = _make_kb(id=1)
        monkeypatch.setattr("app.core.config.settings.upload_dir", str(tmp_path))
        monkeypatch.setattr("app.core.config.settings.upload_max_size_mb", 1)  # 1MB
        session = AsyncMock()
        session.get = AsyncMock(return_value=kb)

        uf = MagicMock(); uf.filename = "big.txt"
        uf.read = AsyncMock(return_value=b"x" * (2 * 1024 * 1024))  # 2MB

        with pytest.raises(HTTPException) as exc:
            await upload_document(1, uf, session, _make_admin())
        assert exc.value.status_code == 400
        assert "MB" in exc.value.detail


# ============ 删除文档 ============

class TestDeleteDocument:

    @pytest.mark.asyncio
    async def test_delete_success(self, monkeypatch, tmp_path):
        kb = _make_kb(id=1)
        doc = _make_doc(id=10, kb_id=1, filename="a.txt",
                        storage_path=str(tmp_path / "fake.txt"))
        session = AsyncMock()
        # session.get(KnowledgeDocument, doc_id) → doc（第一调用）
        # doc.kb_id == kb_id  校验通过 → session.get(KnowledgeDocument, doc_id) 走一次
        session.get = AsyncMock(return_value=doc)
        session.delete = AsyncMock()
        session.commit = AsyncMock()
        session.add = MagicMock()

        # mock os.remove（容忍 FileNotFoundError → 直接略过）
        with patch("app.api.v1.admin_knowledge_base.delete_doc_chunks") as mock_del_chunks:
            result = await delete_document(1, 10, session, _make_admin())
            assert result is None
            mock_del_chunks.assert_called_once_with(1, 10)
            session.delete.assert_awaited_once_with(doc)

    @pytest.mark.asyncio
    async def test_delete_doc_not_match_kb_404(self):
        doc = _make_doc(id=10, kb_id=2)  # kb=2
        session = AsyncMock()
        session.get = AsyncMock(return_value=doc)

        with patch("app.api.v1.admin_knowledge_base.delete_doc_chunks"):
            with pytest.raises(HTTPException) as exc:
                await delete_document(1, 10, session, _make_admin())
            assert exc.value.status_code == 404


# ============ 重建文档 ============

class TestRebuildDocument:

    @pytest.mark.asyncio
    async def test_rebuild_schedules_task(self):
        kb = _make_kb(id=1, chunk_size=500, chunk_overlap=80)
        doc = _make_doc(id=10, kb_id=1)
        session = AsyncMock()
        # session.get(KnowledgeBase, 1) → kb, session.get(KnowledgeDocument, 10) → doc
        session.get = AsyncMock(side_effect=[kb, doc])

        with patch("app.api.v1.admin_knowledge_base.asyncio.create_task") as mock_task:
            result = await rebuild_document(1, 10, session, _make_admin())
            assert result["ok"] is True
            assert result["doc_id"] == 10
            assert result["status"] == "rebuilding"
            mock_task.assert_called_once()

    @pytest.mark.asyncio
    async def test_rebuild_not_found_404(self):
        session = AsyncMock()
        # kb 找不到
        session.get = AsyncMock(return_value=None)
        with patch("app.api.v1.admin_knowledge_base.asyncio.create_task"):
            with pytest.raises(HTTPException) as exc:
                await rebuild_document(1, 10, session, _make_admin())
            assert exc.value.status_code == 404


# ============ 检索测试 ============

class TestRetrievalTest:

    @pytest.mark.asyncio
    async def test_retrieval_success(self):
        kb = _make_kb(id=1, top_k=5)
        session = AsyncMock()
        session.get = AsyncMock(return_value=kb)

        # mock KbChunk 返回
        from app.services.kb_service import KbChunk
        fake_chunks = [
            KbChunk(doc_id=10, filename="a.txt", chunk_index=0,
                    text="相关文本片段", score=0.123),
            KbChunk(doc_id=20, filename="b.md", chunk_index=1,
                    text="另一片段", score=0.456),
        ]
        with patch("app.api.v1.admin_knowledge_base.retrieve_from_kb",
                   AsyncMock(return_value=fake_chunks)):
            body = RetrievalTestIn(query="怎么练胸？", top_k=5)
            result = await retrieval_test(1, body, session)
            assert result.query == "怎么练胸？"
            assert len(result.chunks) == 2
            assert result.chunks[0]["doc_id"] == 10
            assert result.chunks[0]["filename"] == "a.txt"
            assert result.chunks[0]["text"] == "相关文本片段"

    @pytest.mark.asyncio
    async def test_retrieval_kb_not_found_404(self):
        session = AsyncMock()
        session.get = AsyncMock(return_value=None)

        with patch("app.api.v1.admin_knowledge_base.retrieve_from_kb", new=AsyncMock()):
            body = RetrievalTestIn(query="x", top_k=5)
            with pytest.raises(HTTPException) as exc:
                await retrieval_test(999, body, session)
            assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_retrieval_empty(self):
        kb = _make_kb(id=1)
        session = AsyncMock()
        session.get = AsyncMock(return_value=kb)

        with patch("app.api.v1.admin_knowledge_base.retrieve_from_kb",
                   AsyncMock(return_value=[])):
            body = RetrievalTestIn(query="啥也没有", top_k=5)
            result = await retrieval_test(1, body, session)
            assert result.chunks == []
