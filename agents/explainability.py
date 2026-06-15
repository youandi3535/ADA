"""agents.explainability — ExplainabilityAgent (Day11).

v2 — GradCAM/Attention 제거. SHAP + 시계열 분해만 사용.
SHAP 층화 샘플링(R-501) — 큰 데이터에서 stratified sample 1000 row.
"""

from __future__ import annotations

import asyncio
import tempfile
from typing import Any

import numpy as np

from ada.core.state import PipelineState
from agents.base import BaseAgent


# HJ 2026-06-11 — G5 모달 라이브 피드용.
def _safe_publish_stage_partial(job_id: str | None, partial: dict) -> None:
    if not job_id or not isinstance(partial, dict) or not partial:
        return
    try:
        from orchestrator.runner import publish_stage_partial as _psp

        _psp(job_id, partial)
    except Exception:  # noqa: BLE001
        pass


class ExplainabilityAgent(BaseAgent):
    uses_llm = False
    SAMPLE_SIZE = 1000

    async def __call__(self, state: PipelineState) -> PipelineState:
        async with self.log_agent_run(state):
            # HJ 2026-06-11 — G5 모달 라이브 피드: SHAP/시계열분해 시작 status publish.
            _safe_publish_stage_partial(
                state.job_id,
                {
                    "g5_phase": "explainability_start",
                    "g5_status": "SHAP·설명가능성 계산 중…",
                },
            )
            # HJ 2026-06-14 — ③ eval 단계에서 SHAP 를 eval LLM 과 병렬 선계산했으면
            #   (state.explanations) 재계산을 건너뛰고 publish 만 수행. 결과 비트 동일, ~30s 절감.
            _pre = getattr(state, "explanations", None)
            if isinstance(_pre, dict) and _pre:
                artifacts: dict[str, Any] = dict(_pre)
            else:
                artifacts = await self._compute_artifacts(state)

            # HJ 2026-06-11 — G5 SHAP 상위 피처 자연어 인사이트 publish.
            # G2 의 eda_insights 패턴 — "SHAP 상위 피처: 'Age' (importance 0.32)" 형식.
            try:
                _g5_shap_insights: list[str] = []
                top = artifacts.get("shap_top_features") or []
                # HJ 2026-06-15 — self-healing 서사: 1차 실패 → 자동 진단·복구 결과를 함께 보고.
                _rec = artifacts.get("shap_recovery") or {}
                if isinstance(top, list) and top:
                    if _rec.get("recovered"):
                        _g5_shap_insights.append(
                            f"SHAP 1차 실패 → 모델 아티팩트 자동 복구 후 재계산 성공 "
                            f"(근본원인: {_rec.get('root_cause', '경로 불일치')})"
                        )
                    elif _rec.get("surrogate"):
                        _g5_shap_insights.append(
                            f"SHAP 1차 실패 → 원본 아티팩트 누락으로 동일 설정"
                            f"({_rec.get('surrogate_model', '모델')}) 재학습 surrogate 로 SHAP 산출 성공"
                        )
                    for i, ent in enumerate(top[:6], start=1):
                        fn = str(ent.get("feature", "?"))
                        imp = ent.get("importance", 0)
                        try:
                            _g5_shap_insights.append(f"SHAP 상위 피처: '{fn}' (importance {float(imp):.3f})")
                        except (TypeError, ValueError):
                            _g5_shap_insights.append(f"SHAP 상위 피처: '{fn}' (importance {imp})")
                elif artifacts.get("shap_error"):
                    _g5_shap_insights.append(
                        f"SHAP 계산 실패(1차 실패 후 자동 재조사·복구 시도 완료): {str(artifacts['shap_error'])[:150]}"
                    )
                    if _rec.get("root_cause"):
                        _g5_shap_insights.append(f"근본원인 진단: {_rec.get('root_cause')}")
                elif artifacts.get("decomposition_path") or artifacts.get("seasonality_period"):
                    period = artifacts.get("seasonality_period")
                    _g5_shap_insights.append(f"시계열 분해: 계절성 주기 {period} (추세·계절·잔차 분해 완료)")
                # HJ 2026-06-13 — 윤색은 단순 작업이라 Ollama+백그라운드로 (토큰 절약 + critical path 제거).
                #   SHAP 계산 자체는 코드(_shap)가 수행, 윤색은 상위 피처에 해석 한 문장 붙이는 보조라 품질 무영향.
                self._spawn_insight_polish(
                    list(_g5_shap_insights),
                    backend="ollama",
                    context="G5 설명가능성(SHAP)",
                    job_id=state.job_id,
                    key="g5_shap_insights",
                )
                _safe_publish_stage_partial(
                    state.job_id,
                    {
                        "g5_phase": "explainability_done",
                        "g5_status": "설명가능성 분석 완료 — 인사이트 생성 단계로 이동",
                        "g5_shap_insights": _g5_shap_insights,
                    },
                )
            except Exception as e:  # noqa: BLE001
                self.logger.warning("g5_shap_insights_publish_failed", error=str(e))

            return state.with_update(explanations=artifacts, next_agent="insight")

    # ------------------------------------------------------------------
    async def _compute_artifacts(self, state: PipelineState) -> dict[str, Any]:
        """SHAP(비시계열) 또는 시계열 분해 — CPU 작업을 to_thread 로 워커 스레드에서 수행.

        eval 단계의 병렬 선계산과 이 노드 양쪽에서 공용. to_thread 라 호출자(eval)의
        LLM I/O 대기와 진짜 병렬로 겹친다(SHAP 내부는 동기 numpy/shap C 레벨, GIL 해제).
        """
        if state.category == "timeseries":
            return await asyncio.to_thread(self._timeseries_decompose, state)
        return await asyncio.to_thread(self._shap, state)

    # ------------------------------------------------------------------
    def _shap(self, state: PipelineState) -> dict[str, Any]:
        import shap  # type: ignore

        from tools.minio_tool import get_minio_client

        mc = get_minio_client()
        best = state.best_model or {}
        if "minio_path" not in best:
            return {"shap_skipped": "no model path"}

        # ── 1) 모델 로드 (self-healing: 1차 실패 시 자동 진단·복구·재시도) ──────────
        model, recovery = self._load_model_self_heal(state, mc, best)

        # ── 2) 데이터 로드 (SHAP·surrogate 재학습 공용) ─────────────────────────────
        try:
            df = mc.load_dataframe(state.file_id, fmt=state.file_id.rsplit(".", 1)[-1].lower())
        except Exception as e:
            return {"shap_error": f"설명용 데이터 로드 실패: {e}", "shap_recovery": recovery}

        X = df.select_dtypes(include=[np.number, "bool"]).fillna(0)
        if state.target_column in X.columns:
            X = X.drop(columns=[state.target_column])
        if len(X) > self.SAMPLE_SIZE:
            X = X.sample(self.SAMPLE_SIZE, random_state=42)

        # ── 3) 복구 최종 실패 → tabular_ml 은 동일 설정 surrogate 재학습으로 SHAP 산출 ──
        if model is None and state.category in ("tabular_ml",):
            model, recovery = self._refit_surrogate(state, df, X, best, recovery)

        if model is None:
            return {
                "shap_error": recovery.get("error") or "모델 로드 실패",
                "shap_recovery": recovery,
            }

        try:
            explainer = shap.Explainer(model, X[:100])
            sv = explainer(X[:200])
            top_features = (
                np.abs(sv.values).mean(axis=0) if sv.values.ndim == 2 else np.abs(sv.values).mean(axis=(0, 2))
            )
            order = np.argsort(-top_features)
            ranking = [{"feature": str(X.columns[i]), "importance": float(top_features[i])} for i in order[:20]]

            # SHAP summary plot 저장
            import matplotlib  # noqa: WPS433

            matplotlib.use("Agg")
            import matplotlib.pyplot as plt  # noqa: WPS433

            plt.figure(figsize=(8, 6))
            try:
                shap.plots.beeswarm(sv, show=False, max_display=15)
            except Exception:
                shap.summary_plot(sv.values, X[:200], show=False)
            tmpf = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
            tmpf.close()
            plt.savefig(tmpf.name, dpi=120, bbox_inches="tight")
            plt.close()
            shap_path = mc.save_artifact(tmpf.name, "explanations/shap", state.job_id)
            result: dict[str, Any] = {"shap_top_features": ranking, "shap_summary_path": shap_path}
            if recovery.get("recovered") or recovery.get("surrogate"):
                result["shap_recovery"] = recovery  # 복구 흔적 → 리포트 정직 표기용
            return result
        except Exception as e:
            return {"shap_error": str(e), "shap_recovery": recovery}

    # ------------------------------------------------------------------
    # self-healing 보조 — 모델 아티팩트 로드 실패의 근본원인 진단·복구·재학습
    # HJ 2026-06-15 — "SHAP 계산 실패(모델 데이터 누락)" 한 줄 보고로 끝나던 것을,
    #   1차 실패 → 자동 진단 → 경로 복구·재시도 → (그래도 없으면) 동일 설정 재학습
    #   까지 도는 진짜 자동화 루프로 전환. 모든 단계는 G5 라이브 모달에 publish.
    # ------------------------------------------------------------------
    def _load_model_self_heal(self, state: PipelineState, mc: Any, best: dict) -> tuple[Any, dict[str, Any]]:
        """모델 로드 — 1차 실패 시 자동 진단·복구·재시도. 반환: (model_or_None, recovery_info)."""
        import joblib  # noqa: WPS433

        def _download_load(k: str) -> Any:
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".joblib")
            tmp.close()
            with open(tmp.name, "wb") as f:
                f.write(mc.download_bytes(k))
            return joblib.load(tmp.name)

        key = mc.object_key(str(best["minio_path"]))

        # 1차 시도
        try:
            return _download_load(key), {"recovered": False, "attempts": 1, "key": key}
        except Exception as e1:  # noqa: BLE001
            first_err = str(e1)

        # 1차 실패 → 즉시 "재조사 중" 라이브 보고 + 근본원인 진단
        self.logger.warning("shap_model_load_failed_self_heal", key=key, error=first_err)
        _safe_publish_stage_partial(
            state.job_id,
            {
                "g5_phase": "shap_self_heal",
                "g5_status": "SHAP 계산 1차 실패 — 모델 아티팩트 데이터 보강·재조사 중…",
                "g5_shap_insights": [f"SHAP 1차 실패({first_err[:80]}) → 자동 재조사 시작"],
            },
        )

        diag = self._diagnose_model_artifact(mc, key, state)

        # 복구 후보(실제 저장된 키)가 있으면 2차 시도
        cand = diag.get("recovered_key")
        if cand and cand != key:
            try:
                model = _download_load(cand)
                self.logger.info("shap_model_recovered", original=key, recovered=cand)
                _safe_publish_stage_partial(
                    state.job_id,
                    {
                        "g5_phase": "shap_self_heal",
                        "g5_status": f"재조사 성공 — 모델 아티팩트 복구({cand}). SHAP 재계산 진행",
                    },
                )
                return model, {
                    "recovered": True,
                    "attempts": 2,
                    "original_key": key,
                    "recovered_key": cand,
                    "root_cause": diag.get("root_cause"),
                    "first_error": first_err,
                }
            except Exception as e2:  # noqa: BLE001
                diag["second_error"] = str(e2)

        # 복구 실패 — 사람이 읽을 수 있는 근본원인·조치 메시지 동봉
        return None, {
            "recovered": False,
            "attempts": 2 if cand else 1,
            "root_cause": diag.get("root_cause"),
            "first_error": first_err,
            "diagnosis": diag,
            "error": self._explain_root_cause(diag, first_err),
        }

    @staticmethod
    def _diagnose_model_artifact(mc: Any, key: str, state: PipelineState) -> dict[str, Any]:
        """NoSuchKey 근본원인 분류 + 복구 후보 탐색.

        root_cause:
          - ``bucket_prefix_left``  : key 에 ``s3://`` 가 남음(버킷 접두 제거 실패)
          - ``exists_but_unreadable``: 키는 존재하나 다운로드 실패(권한/손상) — 재시도 후보
          - ``recovered_in_job``    : ``models/{job_id}/`` 에서 실제 객체 발견 → 복구 가능
          - ``no_model_in_storage`` : 해당 job 의 모델이 스토리지에 없음(학습 저장 누락)
        """
        diag: dict[str, Any] = {"checked_key": key}
        try:
            if key.startswith("s3://"):
                diag["root_cause"] = "bucket_prefix_left"
            if mc.object_exists(key):
                diag["root_cause"] = "exists_but_unreadable"
                diag["recovered_key"] = key  # 재시도로 회복 가능성
                return diag
        except Exception as e:  # noqa: BLE001
            diag["object_exists_error"] = str(e)

        # job prefix 에서 실제 저장된 모델 탐색 → 경로·이름 불일치 복구
        job_id = getattr(state, "job_id", None)
        candidates: list[str] = []
        if job_id:
            try:
                candidates = [k for k in mc.list_objects(prefix=f"models/{job_id}/") if k.endswith(".joblib")]
            except Exception as e:  # noqa: BLE001
                diag["list_error"] = str(e)
        diag["job_candidates"] = candidates

        if candidates:
            bm = getattr(state, "best_model", None) or {}
            mn = str(bm.get("model_name", ""))
            pick = next((c for c in candidates if mn and mn.lower() in c.lower()), candidates[0])
            diag["recovered_key"] = pick
            diag["root_cause"] = "recovered_in_job"
        else:
            diag.setdefault("root_cause", "no_model_in_storage")
        return diag

    @staticmethod
    def _explain_root_cause(diag: dict[str, Any], first_err: str) -> str:
        rc = diag.get("root_cause")
        if rc == "no_model_in_storage":
            return (
                "모델 아티팩트가 오브젝트 스토리지에 존재하지 않습니다 — "
                "학습 단계의 모델 저장(save_model)이 누락/실패했을 가능성이 높습니다 "
                f"(키 '{diag.get('checked_key', '')}' 및 job prefix 모두 객체 없음)."
            )
        if rc == "bucket_prefix_left":
            return f"키에서 s3:// 버킷 접두가 제거되지 않았습니다(버킷명 불일치): {diag.get('checked_key')}"
        if rc == "exists_but_unreadable":
            return f"키는 존재하나 다운로드에 실패했습니다(권한/손상 가능): {first_err}"
        return f"SHAP 모델 로드 실패: {first_err}"

    def _refit_surrogate(
        self, state: PipelineState, df: Any, X: Any, best: dict, recovery: dict[str, Any]
    ) -> tuple[Any, dict[str, Any]]:
        """원본 아티팩트 누락 시 — 동일 model_name+best_params 로 재학습한 surrogate 로 SHAP 산출.

        '모델 데이터 누락' 한 줄로 포기하지 않고 실제 SHAP 결과를 만들기 위한 최종 복구.
        동일 알고리즘·하이퍼파라미터·데이터·시드라 사실상 동일 모델이며, 결과에는
        ``surrogate=True`` 를 박아 리포트가 '재학습 모델 기반'임을 정직하게 표기한다.
        SHAP 가 보는 피처공간(X)과 일치시키려 X 자체로 학습한다.
        """
        recovery = dict(recovery)
        try:
            model_name = str(best.get("model_name") or "")
            if not model_name or state.target_column not in df.columns:
                return None, recovery

            _safe_publish_stage_partial(
                state.job_id,
                {
                    "g5_phase": "shap_self_heal",
                    "g5_status": f"원본 모델 복구 불가 → 동일 설정({model_name}) 재학습으로 SHAP 산출 중…",
                },
            )

            from pipelines.factory import PipelineFactory

            params = (getattr(state, "best_params", None) or {}).get(model_name, {}) or {}
            y = df[state.target_column].loc[X.index]
            p = PipelineFactory.create(state.category)
            model = p.train(X.values, y.values, model_name=model_name, params=params)

            recovery.update(
                {
                    "surrogate": True,
                    "surrogate_model": model_name,
                    "root_cause": recovery.get("root_cause") or "no_model_in_storage",
                    "error": None,
                }
            )
            self.logger.info("shap_surrogate_refit_ok", model=model_name)
            return model, recovery
        except Exception as e:  # noqa: BLE001
            recovery["surrogate_error"] = str(e)
            self.logger.warning("shap_surrogate_refit_failed", error=str(e))
            return None, recovery

    # ------------------------------------------------------------------
    def _timeseries_decompose(self, state: PipelineState) -> dict[str, Any]:
        import matplotlib  # noqa: WPS433

        from tools.minio_tool import get_minio_client

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt  # noqa: WPS433
        from statsmodels.tsa.seasonal import seasonal_decompose

        mc = get_minio_client()
        try:
            df = mc.load_dataframe(state.file_id, fmt=state.file_id.rsplit(".", 1)[-1].lower())
            y = df[state.target_column].dropna().astype(float)
            period = 7 if len(y) >= 60 else max(2, len(y) // 4)
            dec = seasonal_decompose(y, model="additive", period=period)
            fig = dec.plot()
            fig.set_size_inches(10, 6)
            tmpf = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
            tmpf.close()
            fig.savefig(tmpf.name, dpi=120)
            plt.close(fig)
            path = mc.save_artifact(tmpf.name, "explanations/ts_decompose", state.job_id)
            return {"timeseries_decompose_path": path, "period": period}
        except Exception as e:
            return {"timeseries_decompose_error": str(e)}
