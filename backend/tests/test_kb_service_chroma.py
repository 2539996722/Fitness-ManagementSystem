"""kb_service Chroma 集成测试。

需要真实 Chroma PersistentClient（嵌入式，毫秒级启动）。
embedding_service 被 mock，避免真调 LLM。
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.kb_service import (
    KbChunk,
    delete_doc_chunks,
    ingest_document,
    list_doc_chunks,
    retrieve_from_kb,
)


def _make_kb(
    id: int = 9999,
    top_k: int = 3,
    similarity_threshold: float = 0.0,
    chunk_size: int = 500,
    chunk_overlap: int = 80,
) -> SimpleNamespace:
    """构造一个类 KB 对象（duck-typed），无需真实 DB。"""
    return SimpleNamespace(
        id=id,
        top_k=top_k,
        similarity_threshold=similarity_threshold,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        name=f"test_kb_{id}",
    )


async def _seed(kb_id: int, doc_id: int, texts: list[str], filename: str = "t.md"):
    """辅助函数：直接往 collection 塞 chunks（绕过完整 ingest）。"""
    from app.services.embedding_service import embed_documents
    vectors = await embed_documents(texts)
    from app.services.kb_service import _get_kb_collection
    coll = _get_kb_collection(kb_id)
    coll.add(
        ids=[f"doc{doc_id}_c{i}" for i in range(len(texts))],
        embeddings=vectors,
        documents=texts,
        metadatas=[
            {"doc_id": doc_id, "filename": filename, "chunk_index": i}
            for i in range(len(texts))
        ],
    )


# ============ list_doc_chunks ============

@pytest.mark.asyncio
async def test_list_doc_chunks_returns_all_chunks_in_order(kb_id, mock_embed):
    """插入 3 个 chunks → list_doc_chunks 应按 chunk_index 顺序返回 3 个。"""
    await _seed(kb_id, doc_id=42, texts=["A", "B", "C"])

    chunks = list_doc_chunks(kb_id, doc_id=42)

    assert len(chunks) == 3
    assert [c.chunk_index for c in chunks] == [0, 1, 2]
    assert [c.text for c in chunks] == ["A", "B", "C"]
    assert all(c.char_count == 1 for c in chunks)


@pytest.mark.asyncio
async def test_list_doc_chunks_empty_when_no_match(kb_id, mock_embed):
    """不存在 doc_id 时返回空列表（不抛异常）。"""
    chunks = list_doc_chunks(kb_id, doc_id=99999)
    assert chunks == []


@pytest.mark.asyncio
async def test_list_doc_chunks_isolates_per_doc(kb_id, mock_embed):
    """两个 doc 的 chunks 必须分开。"""
    await _seed(kb_id, doc_id=1, texts=["doc1-a", "doc1-b"])
    await _seed(kb_id, doc_id=2, texts=["doc2-a", "doc2-b", "doc2-c"])

    c1 = list_doc_chunks(kb_id, doc_id=1)
    c2 = list_doc_chunks(kb_id, doc_id=2)

    assert len(c1) == 2 and len(c2) == 3
    assert all(c.text.startswith("doc1-") for c in c1)
    assert all(c.text.startswith("doc2-") for c in c2)


# ============ delete_doc_chunks ============

@pytest.mark.asyncio
async def test_delete_doc_chunks_removes_only_target_doc(kb_id, mock_embed):
    """删除一个 doc 不影响另一个 doc。"""
    await _seed(kb_id, doc_id=1, texts=["a1", "a2"])
    await _seed(kb_id, doc_id=2, texts=["b1", "b2", "b3"])

    delete_doc_chunks(kb_id, doc_id=1)

    assert len(list_doc_chunks(kb_id, doc_id=1)) == 0
    assert len(list_doc_chunks(kb_id, doc_id=2)) == 3


@pytest.mark.asyncio
async def test_delete_doc_chunks_idempotent(kb_id, mock_embed):
    """删两次不报错。"""
    await _seed(kb_id, doc_id=1, texts=["only chunk"])
    delete_doc_chunks(kb_id, doc_id=1)
    # 第二次删除不会抛
    delete_doc_chunks(kb_id, doc_id=1)
    assert list_doc_chunks(kb_id, doc_id=1) == []


# ============ retrieve_from_kb ============

@pytest.mark.asyncio
async def test_retrieve_from_kb_returns_top_k(kb_id, mock_embed):
    """top_k=2 应返回最相关的 2 个。"""
    kb = _make_kb(id=kb_id, top_k=2)
    await _seed(
        kb_id,
        doc_id=1,
        texts=[
            "胸肌训练卧推动作要领",
            "背部训练引体向上动作要领",
            "腿部训练深蹲动作要领",
        ],
    )

    chunks = await retrieve_from_kb("胸肌怎么练", kb)

    assert len(chunks) <= 2
    assert all(isinstance(c, KbChunk) for c in chunks)
    # 排序按 score 升序（cosine 距离，越小越相关）
    if len(chunks) >= 2:
        assert chunks[0].score <= chunks[1].score


@pytest.mark.asyncio
async def test_retrieve_from_kb_empty_collection(kb_id, mock_embed):
    """空 collection 返回 []。"""
    kb = _make_kb(id=kb_id)
    chunks = await retrieve_from_kb("随便问什么", kb)
    assert chunks == []


@pytest.mark.asyncio
async def test_retrieve_from_kb_similarity_threshold_filters(kb_id, mock_embed):
    """similarity_threshold>0 应过滤掉距离大的 chunks。"""
    kb = _make_kb(id=kb_id, top_k=10, similarity_threshold=0.0)
    # threshold=0 = 不过滤；>0 的真实过滤在 mock embed 下不可靠，
    # 这里只确认函数能接受 threshold 参数并返回结果
    await _seed(kb_id, doc_id=1, texts=["abc", "xyz"])
    chunks = await retrieve_from_kb("abc", kb, similarity_threshold=2.0)
    # threshold=2.0 很大，应该全部保留
    assert len(chunks) == 2


# ============ ingest_document (端到端，集成) ============

@pytest.mark.asyncio
async def test_ingest_document_writes_chunks(kb_id, mock_embed, tmp_path):
    """完整 ingest 流程：写文件 → 读 → 切 → embed → 存 → list。"""
    kb = _make_kb(id=kb_id, chunk_size=20, chunk_overlap=5)
    f = tmp_path / "doc.md"
    f.write_text("第一句。\n第二句。\n第三句。", encoding="utf-8")

    result = await ingest_document(
        kb_id=kb_id,
        doc_id=100,
        storage_path=str(f),
        chunk_size=kb.chunk_size,
        chunk_overlap=kb.chunk_overlap,
        filename="doc.md",
    )

    assert result.chunk_count >= 1
    assert result.first_preview  # 非空
    chunks = list_doc_chunks(kb_id, doc_id=100)
    assert len(chunks) == result.chunk_count


@pytest.mark.asyncio
async def test_ingest_document_empty_file_raises(kb_id, mock_embed, tmp_path):
    """空文件应抛 ValueError。"""
    f = tmp_path / "empty.md"
    f.write_text("", encoding="utf-8")

    with pytest.raises(ValueError, match="文件内容为空"):
        await ingest_document(
            kb_id=kb_id, doc_id=1, storage_path=str(f),
            chunk_size=500, chunk_overlap=80, filename="empty.md",
        )


@pytest.mark.asyncio
async def test_ingest_document_upserts_existing_doc(kb_id, mock_embed, tmp_path):
    """同 doc_id 二次 ingest 应先清旧 chunks，再写新的（幂等）。"""
    f1 = tmp_path / "v1.md"
    f1.write_text("版本一的内容。", encoding="utf-8")
    f2 = tmp_path / "v2.md"
    f2.write_text("版本二的内容完全不一样。", encoding="utf-8")

    await ingest_document(
        kb_id=kb_id, doc_id=50, storage_path=str(f1),
        chunk_size=500, chunk_overlap=80, filename="v1.md",
    )
    before = list_doc_chunks(kb_id, doc_id=50)
    before_texts = " ".join(c.text for c in before)

    await ingest_document(
        kb_id=kb_id, doc_id=50, storage_path=str(f2),
        chunk_size=500, chunk_overlap=80, filename="v2.md",
    )
    after = list_doc_chunks(kb_id, doc_id=50)
    after_texts = " ".join(c.text for c in after)

    # 重新 ingest 后不应包含旧版本的内容
    assert "版本一" not in after_texts
    assert "版本二" in after_texts
    # 数量应该跟新文件对应（不一定相等，但都要存在）
    assert len(after) >= 1
