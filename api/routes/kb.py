"""api.routes.kb — 자체학습 KB API (Day19).

GET  /kb/recipes/{category}
GET  /kb/lessons/search?q=...
DELETE /kb/{kb_id}      — 삭제 권리(GDPR)
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ada.db.models import SelfLearningKB
from ada.db.session import get_db
from ada.harness.rag import KBRAG
from ada.security.rbac import require_perm

router = APIRouter()


@router.get("/recipes/{category}")
async def list_recipes(category: str, db: AsyncSession = Depends(get_db),
                       user: dict = Depends(require_perm("pipeline.read"))) -> list[dict]:
    rag = KBRAG(db)
    return await rag.search_recipes(category, top_k=10)


@router.get("/lessons/search")
async def search_lessons(q: str = Query(min_length=2),
                          db: AsyncSession = Depends(get_db),
                          user: dict = Depends(require_perm("pipeline.read"))) -> list[dict]:
    rag = KBRAG(db)
    return await rag.search_lessons(q, top_k=5)


@router.delete("/{kb_id}")
async def delete_kb(kb_id: str, db: AsyncSession = Depends(get_db),
                    user: dict = Depends(require_perm("*"))) -> dict:
    """삭제 권리 — Day19. admin 만 호출."""
    kb = await db.scalar(select(SelfLearningKB).where(
        SelfLearningKB.id == uuid.UUID(kb_id)
    ))
    if kb is None:
        raise HTTPException(404, detail="not found")
    await db.delete(kb)
    await db.flush()
    return {"deleted": kb_id}
