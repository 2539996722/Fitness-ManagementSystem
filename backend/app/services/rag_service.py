"""RAG 服务（Chroma 嵌入式）。

- 持久化目录：settings.chroma_persist_dir
- 集合：settings.chroma_collection_name（默认 exercises_zh）
- 一个动作 = 一个 chunk，文档 = name_zh + 元信息 + instructions.zh
- 元数据：body_part, equipment, target, category（用于后过滤）

RAG 设计：top_k 默认 3；失败抛 RAGError，调用方决定降级。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from loguru import logger
from sqlalchemy import select

from app.core.config import settings
from app.db.models import Exercise
from app.db.session import async_session
from app.services.embedding_service import embed_query


# ============ 数据类 ============

@dataclass
class RagChunk:
    id: str  # exercise.id
    name_zh: str | None
    name_en: str
    body_part: str
    equipment: str
    target: str
    snippet: str  # 用于注入 system prompt 的简短摘要
    score: float  # 距离，越小越近（Chroma L2）


class RAGError(Exception):
    """RAG 检索失败（embedding 或 Chroma 异常）。"""


# ============ Chroma 客户端（懒加载）============

_client = None
_collection = None


def _get_collection():
    """懒加载 Chroma 客户端 + collection。"""
    global _client, _collection
    if _collection is not None:
        return _collection
    try:
        import chromadb
    except ImportError as e:
        raise RAGError("chromadb 未安装，请先 pip install chromadb") from e

    settings.chroma_path.mkdir(parents=True, exist_ok=True)
    _client = chromadb.PersistentClient(path=str(settings.chroma_path))
    _collection = _client.get_or_create_collection(
        name=settings.chroma_collection_name,
        metadata={"hnsw:space": "cosine"},
    )
    return _collection


def is_indexed() -> bool:
    """是否已经有索引数据。"""
    try:
        return _get_collection().count() > 0
    except Exception:
        return False


# ============ 构建 chunk 文本 ============

def _build_chunk_text(ex: Exercise) -> str:
    """把一个 exercise 拍平成一段可嵌入的文本。

    ponytail: 中文优先（PRD D10），name_en 作补充。模板硬编码 →
    升级路径：多语言字段 / instruction_steps 分块时再细化。
    """
    zh = ex.name_zh or ex.name_en
    inst = ""
    if isinstance(ex.instructions, dict):
        inst = ex.instructions.get("zh") or ex.instructions.get("en") or ""
    target_zh = ex.target  # target 字段值是英文（abs/biceps...），先这样
    return (
        f"{zh}（{ex.name_en}）。"
        f"部位：{ex.body_part}；目标肌群：{target_zh}；器械：{ex.equipment}。"
        f"{inst}"
    )


def _build_snippet(ex: Exercise, max_len: int = 160) -> str:
    """用于引用展示的简短摘要。"""
    zh = ex.name_zh or ex.name_en
    base = f"【{zh} · {ex.body_part} · {ex.equipment}】"
    if len(base) >= max_len:
        return base
    return base


# ============ 索引 ============

async def index_all(batch_size: int = 64) -> int:
    """把 exercises 全表写进 Chroma。幂等（upsert by id）。

    返回写入条数。
    """
    if not settings.rag_enabled:
        logger.warning("RAG 未启用（settings.rag_enabled=False），跳过索引")
        return 0
    coll = _get_collection()
    written = 0

    async with async_session() as session:
        result = await session.execute(select(Exercise).order_by(Exercise.id))
        exercises = result.scalars().all()

    if not exercises:
        logger.warning("exercises 表为空，跳过 RAG 索引")
        return 0

    from app.services.embedding_service import embed_documents

    for i in range(0, len(exercises), batch_size):
        batch = exercises[i : i + batch_size]
        docs = [_build_chunk_text(ex) for ex in batch]
        try:
            vectors = await embed_documents(docs)
        except Exception as e:
            logger.exception("embedding 失败 batch={}: {}", i // batch_size, e)
            raise RAGError(f"embedding 失败：{e}") from e

        ids = [ex.id for ex in batch]
        metadatas = [
            {
                "name_zh": ex.name_zh or "",
                "name_en": ex.name_en,
                "body_part": ex.body_part,
                "equipment": ex.equipment,
                "target": ex.target,
            }
            for ex in batch
        ]

        coll.upsert(ids=ids, documents=docs, embeddings=vectors, metadatas=metadatas)
        written += len(batch)
        logger.info("RAG 索引进度：{}/{}", written, len(exercises))

    return written


# ============ 检索 ============

async def retrieve(query: str, top_k: int = 3) -> list[RagChunk]:
    """检索最相关的 top_k 个动作。

    ponytail: 不做意图分类的元数据过滤。简化版先召回，
    后续按 intent 加 where={body_part: ...} 收紧范围。
    """
    if not settings.rag_enabled:
        # RAG 未启用，直接返回（chat.py 不会拼 prompt context）
        return []
    if not query or not query.strip():
        return []
    coll = _get_collection()
    if coll.count() == 0:
        logger.warning("RAG 索引为空，跳过检索")
        return []

    try:
        vector = await embed_query(query)
    except Exception as e:
        raise RAGError(f"embedding 失败：{e}") from e

    try:
        result = coll.query(query_embeddings=[vector], n_results=top_k)
    except Exception as e:
        raise RAGError(f"Chroma 查询失败：{e}") from e

    ids = (result.get("ids") or [[]])[0]
    docs = (result.get("documents") or [[]])[0]
    metas = (result.get("metadatas") or [[]])[0]
    distances = (result.get("distances") or [[]])[0]

    out: list[RagChunk] = []
    for i, ex_id in enumerate(ids):
        m = metas[i] if i < len(metas) else {}
        out.append(
            RagChunk(
                id=ex_id,
                name_zh=m.get("name_zh") or None,
                name_en=m.get("name_en", ""),
                body_part=m.get("body_part", ""),
                equipment=m.get("equipment", ""),
                target=m.get("target", ""),
                snippet=_build_snippet_from_meta(m),
                score=float(distances[i]) if i < len(distances) else 0.0,
            )
        )
    return out


def _build_snippet_from_meta(m: dict[str, Any], max_len: int = 160) -> str:
    name = m.get("name_zh") or m.get("name_en") or "未知动作"
    base = f"【{name} · {m.get('body_part', '?')} · {m.get('equipment', '?')}】"
    return base[:max_len]


# ============ Prompt 注入 ============

def to_prompt_context(chunks: list[RagChunk]) -> str:
    """把检索结果拼成 system prompt 片段。"""
    if not chunks:
        return ""
    lines = ["以下是数据库中可能相关的健身动作参考（仅供参考）："]
    for i, c in enumerate(chunks, 1):
        lines.append(f"{i}. {c.snippet}")
    return "\n".join(lines)
