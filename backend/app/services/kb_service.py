"""知识库（KB）RAG 服务（M10+ 文档问答）。

每个 KB = 一个 Chroma collection（命名 `kb_{id}`），与其他 KB 物理隔离。

提供：
- ingest_document(kb, doc) — 读取上传文件 → 分片 → embed → 写入 collection
- retrieve_from_kb(query, kb) — 从指定 KB 检索 top_k 片段
- retrieve_from_all(query, kbs) — 多 KB 合并检索
- format_kb_context(chunks) — 拼成 LLM system 消息，标注来源
- delete_kb_collection(kb_id) — 删除整个 KB 的 collection
- delete_doc_chunks(kb_id, doc_id) — 删除文档的所有 chunk
"""
from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from pathlib import Path

from loguru import logger

from app.core.config import settings


# ============ 复用 rag_service 客户端 ============

def _get_chroma_client():
    """返回共享 Chroma PersistentClient（复用 rag_service 的懒加载）。"""
    from app.services.rag_service import _get_collection
    # _get_collection() 会同时初始化 _client 和 _collection；我们只要 client
    _get_collection()
    from app.services import rag_service
    if rag_service._client is None:
        # fallback：rag_service 还没初始化（理论上不可能）
        raise RuntimeError("Chroma client 未初始化")
    return rag_service._client


def _get_kb_collection(kb_id: int):
    """按 kb_id 获取或创建独立 Chroma collection。"""
    client = _get_chroma_client()
    if client is None:
        raise RuntimeError("Chroma client 未初始化（可能 chromadb 未安装）")
    return client.get_or_create_collection(
        name=f"kb_{kb_id}",
        metadata={"hnsw:space": "cosine"},
    )


def delete_kb_collection(kb_id: int) -> None:
    """删除 KB 的整个 collection（KB 删除时调用）。"""
    try:
        client = _get_chroma_client()
        if client is None:
            return
        client.delete_collection(name=f"kb_{kb_id}")
        logger.info(f"已删除 Chroma collection kb_{kb_id}")
    except Exception as e:
        # collection 不存在时静默忽略
        logger.debug(f"删除 collection kb_{kb_id} 失败（可能不存在）：{e}")


def delete_doc_chunks(kb_id: int, doc_id: int) -> None:
    """删除文档的所有 chunk（文档删除时调用）。"""
    try:
        coll = _get_kb_collection(kb_id)
        coll.delete(where={"doc_id": doc_id})
        logger.info(f"已删除 kb_{kb_id} 中 doc_id={doc_id} 的 chunks")
    except Exception as e:
        logger.warning(f"删除 kb_{kb_id} doc={doc_id} chunks 失败：{e}")


@dataclass
class DocChunk:
    """单个分片预览（按 doc_id 列出）。"""

    chunk_index: int
    text: str
    char_count: int


def list_doc_chunks(kb_id: int, doc_id: int) -> list[DocChunk]:
    """列出某个文档在 collection 里的所有分片（按 chunk_index 排序）。

    用于 B 端"查看分片"调试面板，看到每个分片的原文 + 字符数。
    """
    try:
        coll = _get_kb_collection(kb_id)
        res = coll.get(where={"doc_id": doc_id})
    except Exception as e:
        logger.warning(f"读取 doc={doc_id} chunks 失败：{e}")
        return []
    docs = res.get("documents") or []
    metas = res.get("metadatas") or []
    chunks: list[DocChunk] = []
    for text, meta in zip(docs, metas):
        chunks.append(DocChunk(
            chunk_index=int((meta or {}).get("chunk_index", 0)),
            text=text or "",
            char_count=len(text or ""),
        ))
    chunks.sort(key=lambda c: c.chunk_index)
    return chunks


# ============ 文档分片 + ingest ============

@dataclass
class IngestResult:
    """ingest 结果（用于返回给 admin + 更新 document row）。"""

    chunk_count: int
    first_preview: str  # 第一段前 100 字


def _read_text_file(path: str) -> str:
    """读取 txt/md 文件（utf-8 优先，gbk 兜底）。"""
    raw = Path(path).read_bytes()
    for enc in ("utf-8", "utf-8-sig", "gbk", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _split_text(text: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    """用 langchain-text-splitters 做中文友好分片。

    chunk_size / overlap 单位：字符（langchain 默认按字符切；M10+ MVP 不切 token）。
    后续如需 token 级别切分再加 tiktoken。
    """
    try:
        from langchain_text_splitters import RecursiveCharacterTextSplitter
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=["\n\n", "\n", "。", "！", "？", "；", "，", " ", ""],
            length_function=len,
        )
        return splitter.split_text(text)
    except ImportError:
        # fallback：纯 Python 滑动窗口（兜底）
        logger.warning("langchain_text_splitters 未安装，使用 sliding window fallback")
        return _sliding_window_split(text, chunk_size, chunk_overlap)


def _sliding_window_split(text: str, size: int, overlap: int) -> list[str]:
    """无 langchain 时的兜底切分器。"""
    if size <= 0:
        return [text]
    chunks = []
    step = max(1, size - overlap)
    for start in range(0, len(text), step):
        end = min(len(text), start + size)
        chunks.append(text[start:end])
        if end >= len(text):
            break
    return chunks


async def ingest_document(*, kb_id: int, doc_id: int, storage_path: str,
                          chunk_size: int, chunk_overlap: int,
                          filename: str) -> IngestResult:
    """读取文件 → 分片 → 写入指定 KB 的 collection。

    同 doc_id 已有 chunks 时先删除（重新上传场景）。
    """
    # 1. 读文件
    text = await asyncio.to_thread(_read_text_file, storage_path)
    if not text.strip():
        raise ValueError("文件内容为空")

    # 2. 切分（CPU-bound，开线程跑）
    chunks = await asyncio.to_thread(_split_text, text, chunk_size, chunk_overlap)
    if not chunks:
        raise ValueError("切分后无有效片段")

    # 3. embed + 写入（async）
    from app.services.embedding_service import embed_documents

    vectors = await embed_documents(chunks)

    # 4. 写 Chroma
    coll = _get_kb_collection(kb_id)
    # 先清旧 chunks（同 doc_id）
    try:
        coll.delete(where={"doc_id": doc_id})
    except Exception:
        pass
    coll.add(
        ids=[f"doc{doc_id}_c{i}" for i in range(len(chunks))],
        embeddings=vectors,
        documents=chunks,
        metadatas=[
            {"doc_id": doc_id, "filename": filename, "chunk_index": i}
            for i in range(len(chunks))
        ],
    )

    return IngestResult(
        chunk_count=len(chunks),
        first_preview=chunks[0][:100],
    )


# ============ 检索 ============

@dataclass
class KbChunk:
    """KB 检索结果。"""

    doc_id: int
    filename: str
    chunk_index: int
    text: str
    score: float  # cosine distance（越小越相关）


async def retrieve_from_kb(query: str, kb, *, top_k: int | None = None,
                          similarity_threshold: float | None = None) -> list[KbChunk]:
    """从单个 KB 检索。

    similarity_threshold: cosine distance 上限（KB.similarity_threshold 默认 0=不过滤）
    """
    k = min(top_k or kb.top_k, kb.top_k)
    threshold = similarity_threshold if similarity_threshold is not None else float(kb.similarity_threshold)

    coll = _get_kb_collection(kb.id)
    try:
        if coll.count() == 0:
            return []
    except Exception:
        return []

    from app.services.embedding_service import embed_query

    q_vec = await embed_query(query)

    res = coll.query(
        query_embeddings=[q_vec],
        n_results=k,
    )

    docs = (res.get("documents") or [[]])[0]
    dists = (res.get("distances") or [[]])[0]
    metas = (res.get("metadatas") or [[]])[0]
    out: list[KbChunk] = []
    for text, dist, meta in zip(docs, dists, metas):
        if threshold > 0 and dist > threshold:
            continue
        out.append(
            KbChunk(
                doc_id=int(meta.get("doc_id", 0)),
                filename=str(meta.get("filename", "")),
                chunk_index=int(meta.get("chunk_index", 0)),
                text=text,
                score=float(dist),
            )
        )
    return out


async def retrieve_from_all(query: str, kbs: list, *, per_kb_top_k: int | None = None) -> list[KbChunk]:
    """从多个 KB 合并检索，按 score 排序返回前 N。"""
    if not kbs:
        return []
    tasks = [retrieve_from_kb(query, kb, top_k=per_kb_top_k) for kb in kbs]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    all_chunks: list[KbChunk] = []
    for kb, res in zip(kbs, results):
        if isinstance(res, Exception):
            logger.warning(f"KB {kb.id} 检索失败：{res}")
            continue
        all_chunks.extend(res)
    all_chunks.sort(key=lambda c: c.score)
    return all_chunks


# ============ LLM 上下文格式化 ============

def format_kb_context(chunks: list[KbChunk]) -> str:
    """拼成 system message：标注来源文件 + 片段位置。

    强制要求 LLM 优先参考：
    - 知识库有相关内容 → 基于此回答
    - 知识库没有 → 明确说明，不要编造
    """
    if not chunks:
        return ""
    lines = [
        "以下是知识库中检索到的参考资料，你必须优先基于此回答用户问题：",
        "如果知识库内容无法回答用户问题，请明确说明「知识库中没有找到相关内容」，不要凭空编造。",
        "",
    ]
    for i, c in enumerate(chunks, 1):
        lines.append(f"[参考资料 {i}] 来源：{c.filename} · 第 {c.chunk_index} 段 · 相关度 {c.score:.3f}")
        lines.append(c.text)
        lines.append("")
    return "\n".join(lines).strip()