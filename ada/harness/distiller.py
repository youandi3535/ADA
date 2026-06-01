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
from ada.db.models import AgentRun, Job, JobDistillationLog, Model, SelfLearningKB

log = get_logger("harness")

CONFIDENCE_CAP = 0.95
RETRACT_CONFIDENCE = 0.20
DECAY_DAYS = 60
DECAY_RATE = 0.9


def _hash_payload(payload: dict[str, Any]) -> str:
    canon = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


_EDA_STEPS = {
    "tabular_ml": ["결측·이상치 요약", "타깃 분포/불균형", "수치형 상관 히트맵", "범주형 카디널리티"],
    "tabular_dl": ["결측·이상치 요약", "타깃 분포/불균형", "임베딩 대상 범주 분포", "수치형 스케일 점검"],
    "timeseries": ["추세/계절성 분해", "정상성(ADF) 점검", "ACF/PACF", "결측 구간·리샘플링"],
    "anomaly": ["분포·꼬리 두께", "시간성 여부", "라벨 유무/오염도", "수치형 차원 수"],
}


def _eda_steps_for(category: str) -> list[str]:
    return _EDA_STEPS.get(category, ["결측·이상치 요약", "타깃 분포", "주요 변수 상관"])


def _primary_metric(metrics: Any) -> dict[str, Any]:
    """metrics dict 에서 대표 지표 1개를 {name, value} 로 추출."""
    if not isinstance(metrics, dict) or not metrics:
        return {}
    for key in (
        "roc_auc",
        "val_roc_auc",
        "f1",
        "val_f1",
        "accuracy",
        "val_accuracy",
        "rmse",
        "val_rmse",
        "mae",
        "r2",
        "val_r2",
    ):
        if isinstance(metrics.get(key), (int, float)):
            return {"name": key, "value": float(metrics[key])}
    for k, v in metrics.items():
        if isinstance(v, (int, float)):
            return {"name": k, "value": float(v)}
    return {}


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

            # 1-2) recipe / hpo_warm_start / eda_template — 성공 job 의 재사용 레시피
            best_model = await self.session.scalar(
                select(Model)
                .where(Model.job_id == job.id)
                .order_by(Model.is_best.desc(), Model.created_at.desc())
                .limit(1)
            )
            agent_payloads = await self._collect_agent_payloads(job.id)
            metric_summary = _primary_metric(best_model.metrics if best_model else None)

            # recipe — model_selection._fetch_recipes 가 인용
            if best_model is not None:
                recipe_payload = {
                    "category": job.category,
                    "target": job.target_column,
                    "best_model": best_model.model_name,
                    "framework": best_model.framework,
                    "metric": metric_summary,
                    "requested_outputs": job.requested_outputs or [],
                }
                kb_id, is_new = await self._upsert(
                    kb_type="recipe",
                    category=job.category,
                    payload=recipe_payload,
                    source_job_id=job.id,
                    confidence_init=0.55,
                )
                if is_new and kb_id:
                    inserted += 1
                    created_kb_ids.append(str(kb_id))
                    summaries[str(kb_id)] = (
                        f"레시피: {job.category} → {best_model.model_name} "
                        f"({metric_summary.get('name', '')} {metric_summary.get('value', '')})"
                    )[:500]

            # hpo_warm_start — 다음 튜닝의 warm-start 시드
            best_params = agent_payloads.get("best_params")
            if best_model is not None and best_params:
                hpo_payload = {
                    "category": job.category,
                    "model": best_model.model_name,
                    "best_params": best_params,
                    "metric": metric_summary,
                }
                kb_id, is_new = await self._upsert(
                    kb_type="hpo_warm_start",
                    category=job.category,
                    payload=hpo_payload,
                    source_job_id=job.id,
                    confidence_init=0.5,
                )
                if is_new and kb_id:
                    inserted += 1
                    created_kb_ids.append(str(kb_id))
                    summaries[str(kb_id)] = (f"HPO warm-start: {best_model.model_name} {list(best_params)[:6]}")[:500]

            # eda_template — 카테고리·데이터형태별 EDA 재사용
            data_profile = agent_payloads.get("data_profile") or {}
            eda_payload = {
                "category": job.category,
                "n_rows": data_profile.get("rows") or data_profile.get("n_rows"),
                "n_cols": data_profile.get("cols") or data_profile.get("n_cols"),
                "recommended_eda": _eda_steps_for(job.category),
            }
            kb_id, is_new = await self._upsert(
                kb_type="eda_template",
                category=job.category,
                payload=eda_payload,
                source_job_id=job.id,
                confidence_init=0.5,
            )
            if is_new and kb_id:
                inserted += 1
                created_kb_ids.append(str(kb_id))
                summaries[str(kb_id)] = (f"EDA 템플릿: {job.category} ({len(_eda_steps_for(job.category))} steps)")[
                    :500
                ]

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
    async def _collect_agent_payloads(self, job_id: uuid.UUID) -> dict[str, Any]:
        """job 의 AgentRun payload 들에서 best_params / data_profile 재사용 키를 추출."""
        out: dict[str, Any] = {}
        try:
            rows = await self.session.scalars(select(AgentRun).where(AgentRun.job_id == job_id))
            for run in rows:
                p = run.payload if isinstance(run.payload, dict) else {}
                if not p:
                    continue
                if "best_params" in p and "best_params" not in out:
                    out["best_params"] = p["best_params"]
                if "data_profile" in p and "data_profile" not in out:
                    out["data_profile"] = p["data_profile"]
        except Exception as e:  # noqa: BLE001
            log.warning("collect_agent_payloads_failed", error=str(e))
        return out

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
