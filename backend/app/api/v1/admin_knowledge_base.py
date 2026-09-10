"""B 端知识库 CRUD + 文档上传（M10+ RAG）。"""
from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_session, require_role
from app.db.models import (
    KnowledgeBase,
    KnowledgeDocument,
    User,
)
from app.schemas.knowledge_base import (
    KnowledgeBaseCreate,
    KnowledgeBaseListOut,
    KnowledgeBaseOut,
    KnowledgeBaseUpdate,
    KnowledgeDocumentListOut,
    KnowledgeDocumentOut,
    KnowledgeDocumentUploadOut,
    RetrievalTestIn,
    RetrievalTestOut,
)
from app.services import operation_log
from app.services.kb_service import (
    delete_doc_chunks,
    delete_kb_collection,
    ingest_document,
    retrieve_from_kb,
)
from app.core.config import settings


admin_router = APIRouter(
    prefix="/admin/knowledge-bases",
    tags=["知识库"],
    dependencies=[Depends(require_role("admin"))],
)


_ALLOWED_EXTS = {"txt", "md"}


def _upload_root() -> Path:
    root = Path(settings.upload_dir) / "kb"
    root.mkdir(parents=True, exist_ok=True)
    return root


@admin_router.get("", response_model=KnowledgeBaseListOut, summary="列出所有 KB")
async def list_kbs(
    session: Annotated[AsyncSession, Depends(get_session)],
    enabled: bool | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> KnowledgeBaseListOut:
    stmt = select(KnowledgeBase)
    if enabled is not None:
        stmt = stmt.where(KnowledgeBase.enabled == enabled)
    total = (await session.execute(
        select(func.count()).select_from(KnowledgeBase).where(*(stmt.whereclause.children if stmt.whereclause is not None else []))
    )).scalar() or 0
    rows = (await session.execute(
        stmt.order_by(KnowledgeBase.id.desc()).limit(limit).offset(offset)
    )).scalars().all()

    items: list[KnowledgeBaseOut] = []
    for kb in rows:
        doc_count = (await session.execute(
            select(func.count()).select_from(KnowledgeDocument).where(KnowledgeDocument.kb_id == kb.id)
        )).scalar() or 0
        chunk_count = (await session.execute(
            select(func.coalesce(func.sum(KnowledgeDocument.chunk_count), 0))
            .where(KnowledgeDocument.kb_id == kb.id, KnowledgeDocument.status == "ready")
        )).scalar() or 0
        items.append(KnowledgeBaseOut(
            id=kb.id, name=kb.name, description=kb.description,
            enabled=kb.enabled, chunk_size=kb.chunk_size, chunk_overlap=kb.chunk_overlap,
            top_k=kb.top_k, similarity_threshold=float(kb.similarity_threshold),
            created_by=kb.created_by, created_at=kb.created_at, updated_at=kb.updated_at,
            document_count=doc_count, chunk_count=int(chunk_count),
        ))
    return KnowledgeBaseListOut(items=items, total=total)


@admin_router.post("", response_model=KnowledgeBaseOut, status_code=status.HTTP_201_CREATED, summary="新建 KB")
async def create_kb(
    body: KnowledgeBaseCreate,
    session: Annotated[AsyncSession, Depends(get_session)],
    admin: Annotated[User, Depends(get_current_user)],
) -> KnowledgeBaseOut:
    # 唯一名检查
    exists = (await session.execute(
        select(KnowledgeBase).where(KnowledgeBase.name == body.name)
    )).scalar_one_or_none()
    if exists:
        raise HTTPException(status_code=400, detail=f"KB 名「{body.name}」已被占用")

    kb = KnowledgeBase(
        name=body.name,
        description=body.description,
        enabled=body.enabled,
        chunk_size=body.chunk_size,
        chunk_overlap=body.chunk_overlap,
        top_k=body.top_k,
        similarity_threshold=body.similarity_threshold,
        created_by=admin.id,
    )
    session.add(kb)
    await session.commit()
    await session.refresh(kb)

    await operation_log.record(
        session=session,
        operator=admin,
        action="create_kb",
        target_type="knowledge_base",
        target_id=kb.id,
        summary=f"新建知识库「{kb.name}」",
    )
    await session.commit()

    return KnowledgeBaseOut(
        id=kb.id, name=kb.name, description=kb.description,
        enabled=kb.enabled, chunk_size=kb.chunk_size, chunk_overlap=kb.chunk_overlap,
        top_k=kb.top_k, similarity_threshold=float(kb.similarity_threshold),
        created_by=kb.created_by, created_at=kb.created_at, updated_at=kb.updated_at,
        document_count=0, chunk_count=0,
    )


@admin_router.patch("/{kb_id}", response_model=KnowledgeBaseOut, summary="修改 KB")
async def update_kb(
    kb_id: int,
    body: KnowledgeBaseUpdate,
    session: Annotated[AsyncSession, Depends(get_session)],
    admin: Annotated[User, Depends(get_current_user)],
) -> KnowledgeBaseOut:
    kb = await session.get(KnowledgeBase, kb_id)
    if not kb:
        raise HTTPException(status_code=404, detail="KB 不存在")

    if body.name and body.name != kb.name:
        exists = (await session.execute(
            select(KnowledgeBase).where(KnowledgeBase.name == body.name, KnowledgeBase.id != kb_id)
        )).scalar_one_or_none()
        if exists:
            raise HTTPException(status_code=400, detail=f"KB 名「{body.name}」已被占用")
        kb.name = body.name
    if body.description is not None:
        kb.description = body.description
    if body.enabled is not None:
        kb.enabled = body.enabled
    if body.chunk_size is not None:
        kb.chunk_size = body.chunk_size
    if body.chunk_overlap is not None:
        kb.chunk_overlap = body.chunk_overlap
    if body.top_k is not None:
        kb.top_k = body.top_k
    if body.similarity_threshold is not None:
        kb.similarity_threshold = body.similarity_threshold

    await session.commit()
    await session.refresh(kb)

    await operation_log.record(
        session=session,
        operator=admin,
        action="update_kb",
        target_type="knowledge_base",
        target_id=kb.id,
        summary=f"修改知识库「{kb.name}」",
    )
    await session.commit()

    doc_count = (await session.execute(
        select(func.count()).select_from(KnowledgeDocument).where(KnowledgeDocument.kb_id == kb.id)
    )).scalar() or 0
    chunk_count = (await session.execute(
        select(func.coalesce(func.sum(KnowledgeDocument.chunk_count), 0))
        .where(KnowledgeDocument.kb_id == kb.id, KnowledgeDocument.status == "ready")
    )).scalar() or 0
    return KnowledgeBaseOut(
        id=kb.id, name=kb.name, description=kb.description,
        enabled=kb.enabled, chunk_size=kb.chunk_size, chunk_overlap=kb.chunk_overlap,
        top_k=kb.top_k, similarity_threshold=float(kb.similarity_threshold),
        created_by=kb.created_by, created_at=kb.created_at, updated_at=kb.updated_at,
        document_count=doc_count, chunk_count=int(chunk_count),
    )


@admin_router.delete("/{kb_id}", summary="删除 KB（级联删文档 + collection）")
async def delete_kb(
    kb_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    admin: Annotated[User, Depends(get_current_user)],
) -> None:
    kb = await session.get(KnowledgeBase, kb_id)
    if not kb:
        raise HTTPException(status_code=404, detail="KB 不存在")

    # 先删 Chroma collection（DB cascade 删 documents 行）
    delete_kb_collection(kb_id)

    kb_name = kb.name
    await session.delete(kb)
    await session.commit()

    await operation_log.record(
        session=session,
        operator=admin,
        action="delete_kb",
        target_type="knowledge_base",
        target_id=kb_id,
        summary=f"删除知识库「{kb_name}」",
    )
    await session.commit()


# ============ 文档管理 ============

@admin_router.get("/{kb_id}/documents", response_model=KnowledgeDocumentListOut, summary="列文档")
async def list_documents(
    kb_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> KnowledgeDocumentListOut:
    kb = await session.get(KnowledgeBase, kb_id)
    if not kb:
        raise HTTPException(status_code=404, detail="KB 不存在")
    total = (await session.execute(
        select(func.count()).select_from(KnowledgeDocument).where(KnowledgeDocument.kb_id == kb_id)
    )).scalar() or 0
    rows = (await session.execute(
        select(KnowledgeDocument).where(KnowledgeDocument.kb_id == kb_id)
        .order_by(KnowledgeDocument.id.desc()).limit(limit).offset(offset)
    )).scalars().all()
    items = [KnowledgeDocumentOut.model_validate(r) for r in rows]
    return KnowledgeDocumentListOut(items=items, total=total)


@admin_router.post(
    "/{kb_id}/documents",
    response_model=KnowledgeDocumentUploadOut,
    status_code=status.HTTP_201_CREATED,
    summary="上传文档（txt/md）",
)
async def upload_document(
    kb_id: int,
    file: Annotated[UploadFile, File(...)],
    session: Annotated[AsyncSession, Depends(get_session)],
    admin: Annotated[User, Depends(get_current_user)],
) -> KnowledgeDocumentOut | KnowledgeDocumentUploadOut:
    """上传 .txt / .md，自动分片 + 向量化。

    流程：
    1. 校验 ext + size
    2. 保存到 data/uploads/kb/<uuid>.<ext>
    3. 创建 KnowledgeDocument row（status=processing）
    4. 后台 ingest_document → 更新 status / chunk_count
    5. 返回 doc + chunk_count + first_preview
    """
    kb = await session.get(KnowledgeBase, kb_id)
    if not kb:
        raise HTTPException(status_code=404, detail="KB 不存在")

    # 1. 校验扩展
    raw_name = file.filename or ""
    ext = raw_name.rsplit(".", 1)[-1].lower() if "." in raw_name else ""
    if ext not in _ALLOWED_EXTS:
        raise HTTPException(
            status_code=400,
            detail=f"仅支持 {' / '.join(_ALLOWED_EXTS)}（当前 .{ext or '??'}）",
        )

    # 2. 读 + size 校验
    blob = await file.read()
    if len(blob) > settings.upload_max_size_mb * 1024 * 1024:
        raise HTTPException(
            status_code=400,
            detail=f"文件超过 {settings.upload_max_size_mb}MB 限制",
        )

    # 3. 保存
    kb_dir = _upload_root() / f"kb_{kb_id}"
    kb_dir.mkdir(parents=True, exist_ok=True)
    storage_filename = f"{uuid.uuid4().hex}.{ext}"
    storage_path = kb_dir / storage_filename
    await asyncio.to_thread(storage_path.write_bytes, blob)

    # 4. 创建 DB row（processing）
    doc = KnowledgeDocument(
        kb_id=kb_id,
        filename=raw_name,
        storage_path=str(storage_path),
        ext=ext,
        size_bytes=len(blob),
        status="processing",
        uploaded_by=admin.id,
    )
    session.add(doc)
    await session.commit()
    await session.refresh(doc)

    # 5. 后台 ingest（不阻塞响应）
    async def _do_ingest():
        from app.db.session import async_session
        try:
            result = await ingest_document(
                kb_id=kb_id,
                doc_id=doc.id,
                storage_path=str(storage_path),
                chunk_size=kb.chunk_size,
                chunk_overlap=kb.chunk_overlap,
                filename=raw_name,
            )
            async with async_session() as s:
                d = await s.get(KnowledgeDocument, doc.id)
                if d:
                    d.status = "ready"
                    d.chunk_count = result.chunk_count
                await s.commit()
        except Exception as e:
            logger.exception(f"ingest 失败 doc={id=}: {e}")
            async with async_session() as s:
                d = await s.get(KnowledgeDocument, doc.id)
                if d:
                    d.status = "failed"
                    d.error_message = str(e)[:500]
                await s.commit()

    asyncio.create_task(_do_ingest())

    # 6. 操作日志
    await operation_log.record(
        session=session,
        operator=admin,
        action="upload_doc",
        target_type="knowledge_document",
        target_id=doc.id,
        summary=f"上传文档「{raw_name}」到 KB「{kb.name}」",
    )
    await session.commit()

    # 7. 返回一次性预览（前端显示 ingest 进度）
    first_preview = blob[:100].decode("utf-8", errors="replace")
    return KnowledgeDocumentUploadOut(
        document=KnowledgeDocumentOut.model_validate(doc),
        chunk_count=0,
        first_preview=first_preview,
    )


@admin_router.delete(
    "/{kb_id}/documents/{doc_id}",
    summary="删除文档",
)
async def delete_document(
    kb_id: int,
    doc_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    admin: Annotated[User, Depends(get_current_user)],
) -> None:
    doc = await session.get(KnowledgeDocument, doc_id)
    if not doc or doc.kb_id != kb_id:
        raise HTTPException(status_code=404, detail="文档不存在")
    # 删 Chroma chunks
    delete_doc_chunks(kb_id, doc_id)
    # 删物理文件
    try:
        await asyncio.to_thread(os.remove, doc.storage_path)
    except FileNotFoundError:
        pass
    filename = doc.filename
    await session.delete(doc)
    await session.commit()

    await operation_log.record(
        session=session,
        operator=admin,
        action="delete_doc",
        target_type="knowledge_document",
        target_id=doc_id,
        summary=f"删除文档「{filename}」",
    )
    await session.commit()


@admin_router.post(
    "/{kb_id}/documents/{doc_id}/rebuild",
    summary="重建索引（删 chunks 重 ingest）",
)
async def rebuild_document(
    kb_id: int,
    doc_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    admin: Annotated[User, Depends(get_current_user)],
) -> dict:
    """同 doc_id 先删旧 chunks 再重新 ingest。"""
    kb = await session.get(KnowledgeBase, kb_id)
    doc = await session.get(KnowledgeDocument, doc_id)
    if not kb or not doc or doc.kb_id != kb_id:
        raise HTTPException(status_code=404, detail="文档不存在")

    async def _do_rebuild():
        from app.db.session import async_session
        try:
            delete_doc_chunks(kb_id, doc_id)
            result = await ingest_document(
                kb_id=kb_id, doc_id=doc_id,
                storage_path=doc.storage_path,
                chunk_size=kb.chunk_size, chunk_overlap=kb.chunk_overlap,
                filename=doc.filename,
            )
            async with async_session() as s:
                d = await s.get(KnowledgeDocument, doc_id)
                if d:
                    d.status = "ready"
                    d.chunk_count = result.chunk_count
                    d.error_message = None
                await s.commit()
        except Exception as e:
            logger.exception(f"rebuild 失败 doc={doc_id}: {e}")
            async with async_session() as s:
                d = await s.get(KnowledgeDocument, doc_id)
                if d:
                    d.status = "failed"
                    d.error_message = str(e)[:500]
                await s.commit()

    asyncio.create_task(_do_rebuild())
    return {"ok": True, "doc_id": doc_id, "status": "rebuilding"}


# ============ 检索测试（admin 调试）============

@admin_router.post(
    "/{kb_id}/retrieval-test",
    response_model=RetrievalTestOut,
    summary="测试 KB 检索（admin 调试用）",
)
async def retrieval_test(
    kb_id: int,
    body: RetrievalTestIn,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RetrievalTestOut:
    kb = await session.get(KnowledgeBase, kb_id)
    if not kb:
        raise HTTPException(status_code=404, detail="KB 不存在")
    chunks = await retrieve_from_kb(body.query, kb, top_k=body.top_k)
    return RetrievalTestOut(
        query=body.query,
        chunks=[
            {
                "doc_id": c.doc_id,
                "filename": c.filename,
                "chunk_index": c.chunk_index,
                "score": c.score,
                "text": c.text,
            }
            for c in chunks
        ],
    )