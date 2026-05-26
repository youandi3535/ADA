"""ada.harness.distiller — SelfLearningHarness (Day09).

성공/실패 job 을 self_learning_kb 5종(KB type) 로 증류.
R-501 인용 강제 · R-502 confidence cap 0.95 · R-503 record_outcome
R-504 자동 retraction · R-505 decay (60d 미사용 0.9×)
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ada.core.logger import get_logger
from ada.db.models import Job, JobDistillationLog, SelfLearningKB

log = get_logger("harness")

CONFIDENCE_CAP = 0.95
RETRACT_CONFIDENCE = 0.20
DECAY_DAYS = 60
DECAY_RATE = 0.9


def _hash_payload(payload: dict[str, Any]) -> str:
    canon = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


class SelfLearningHarness:
    """KB 증류·인용·감쇠·재교정 단일 진입점."""

    KB_TYPES = ("success_pattern", "recipe", "eda_template", "hpo_warm_start", "failure_lesson")

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ------------------------------------------------------------------
    async def distill_from_job(self, job_id: str) -> dict[str, Any]:
        """job 완료 시점에 5종 KB 후보 추출 → upsert.

        반환::
            {
                "distilled":      int,           # 새로 삽입된 KB row 수
                "created_kb_ids": list[str],     # 새 KB UUID 문자열 목록
                "summaries":      dict[str,str], # kb_id → 요약 텍스트
            }
        """
        job = await self.session.scalar(select(Job).where(Job.id == uuid.UUID(job_id)))
        if job is None:
            return {"distilled": 0, "created_kb_ids": [], "summaries": {}}

        inserted = 0
        created_kb_ids: list[str] = []
        summaries: dict[str, str] = {}

        # 1) success_pattern — 성공 job 전체 메타
        if job.status == "completed":
            payload = {
                "category": job.category,
                "target": job.target_column,
                "user_intent": job.user_intent or "",
                "requested_outputs": job.requested_outputs or [],
            }
            kb_id, is_new = await self._upsert(
                kb_type="success_pattern",
                category=job.category,
                payload=payload,
                source_job_id=job.id,
            )
            if is_new and kb_id:
                inserted += 1
                created_kb_ids.append(str(kb_id))
                summaries[str(kb_id)] = (
                    f"성공 패턴: {job.category} / {job.target_column or ''} / {job.user_intent or ''}"
                )[:500]

        # 2) failure_lesson — 실패 job
        if job.status == "failed":
            payload = {
                "category": job.category,
                "error": (job.error_message or "")[:1000],
                "retry_count": job.retry_count,
            }
            kb_id, is_new = await self._upsert(
                kb_type="failure_lesson",
                category=job.category,
                payload=payload,
                source_job_id=job.id,
                confidence_init=0.6,
            )
            if is_new and kb_id:
                inserted += 1
                created_kb_ids.append(str(kb_id))
                summaries[str(kb_id)] = (f"실패 교훈: {job.category} / {(job.error_message or '')[:200]}")[:500]

        await self.session.commit()
        return {
            "distilled": inserted,
            "created_kb_ids": created_kb_ids,
            "summaries": summaries,
        }

    # ------------------------------------------------------------------
    async def _upsert(
        self,
        *,
        kb_type: str,
        category: str,
        payload: dict[str, Any],
        source_job_id: uuid.UUID,
        confidence_init: float = 0.5,
    ) -> tuple[uuid.UUID | None, bool]:
        """KB row upsert. 반환: (kb_id, is_new)."""
        h = _hash_payload({**payload, "kb_type": kb_type})
        existing = await self.session.scalar(select(SelfLearningKB).where(SelfLearningKB.hash == h))
        if existing is not None:
            existing.success_count = (existing.success_count or 0) + 1
            existing.confidence = min(
                CONFIDENCE_CAP,
                (existing.confidence or 0.5) + 0.05,
            )
            existing.source_job_ids = list(
                set([str(j) for j in (existing.source_job_ids or [])] + [str(source_job_id)])
            )
            existing.updated_at = datetime.utcnow()
            return existing.id, False
        else:
            new = SelfLearningKB(
                kb_type=kb_type,
                category=category,
                hash=h,
                payload=payload,
                confidence=confidence_init,
                success_count=1,
                source_job_ids=[str(source_job_id)],
            )
            self.session.add(new)
            await self.session.flush()
            self.session.add(
                JobDistillationLog(
                    job_id=source_job_id,
                    kb_type=kb_type,
                    kb_id=new.id,
                )
            )
            return new.id, True

    # ------------------------------------------------------------------
    async def record_outcome(self, kb_id: uuid.UUID, success: bool) -> None:
        """R-503 — 그래프 노드에서 KB 적용 결과 마킹."""
        kb = await self.session.get(SelfLearningKB, kb_id)
        if kb is None:
            return
        delta = 0.05 if success else -0.10
        kb.confidence = max(0.0, min(CONFIDENCE_CAP, (kb.confidence or 0.5) + delta))
        if success:
            kb.success_count = (kb.success_count or 0) + 1
        await self.session.flush()

    async def retract_low_confidence(self) -> int:
        """R-504 — confidence < 0.20 KB 비활성화."""
        result = await self.session.execute(
            select(SelfLearningKB).where(SelfLearningKB.confidence < RETRACT_CONFIDENCE)
        )
        rows = result.scalars().all()
        for kb in rows:
            kb.payload = {**(kb.payload or {}), "retracted": True}
        await self.session.commit()
        return len(rows)

    async def decay_unused(self) -> int:
        """R-505 — 60일 미사용 confidence 0.9×."""
        cutoff = datetime.utcnow() - timedelta(days=DECAY_DAYS)
        result = await self.session.execute(select(SelfLearningKB).where(SelfLearningKB.updated_at < cutoff))
        rows = result.scalars().all()
        for kb in rows:
            kb.confidence = (kb.confidence or 0.5) * DECAY_RATE
        await self.session.commit()
        return len(rows)
