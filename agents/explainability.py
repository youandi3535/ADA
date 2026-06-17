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
                # HJ 2026-06-16 — 키 정합 버그 수정: _timeseries_decompose 는 실제로
                #   timeseries_decompose_path/period 를 반환하는데, 여기서 부재 키
                #   (decomposition_path/seasonality_period)를 읽어 분해 메시지가 한 번도
                #   안 뜨던 문제. 실제 키를 읽되 기존 별칭도 하위호환으로 함께 인정한다.
                elif (
                    artifacts.get("timeseries_decompose_path")
                    or artifacts.get("period") is not None
                    or artifacts.get("decomposition_path")
                    or artifacts.get("seasonality_period") is not None
                ):
                    period = artifacts.get("period")
                    if period is None:
                        period = artifacts.get("seasonality_period")
                    _g5_shap_insights.append(f"시계열 분해: 계절성 주기 {period} (추세·계절·잔차 분해 완료)")
                elif artifacts.get("timeseries_decompose_error"):
                    _g5_shap_insights.append(f"시계열 분해 실패: {str(artifacts['timeseries_decompose_error'])[:150]}")
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
        """SHAP 산출 — '어떤 데이터가 와도 실패가 안 뜨도록' 다중 방어.

        HJ 2026-06-16 — 근본 원인 수정:
          (1) tabular_ml/tabular_dl 은 jh 의 검증된 본구현(handlers.tabular.explain)에
              위임. 전처리 피처공간 일치·explainer 라우팅·멀티클래스·graceful skip 포함.
          (2) 그 외(anomaly) 또는 위임 빈손 시 자체 견고화 경로(_shap_robust):
              · 학습과 동일한 전처리 데이터 로드(file_id raw → preprocessed_data_id)
              · 모델 feature_names_in_/n_features_in_ 로 X 피처공간 정렬(불일치 차단)
              · explainer 모델명 라우팅 + KernelExplainer 최종 폴백
              · SHAP 전부 실패해도 feature_importances_/coef_/permutation 으로 산출
        """
        best = state.best_model or {}
        if "minio_path" not in best:
            return {"shap_skipped": "no model path"}

        # 회귀 안전 — 내부 예외는 절대 에이전트 흐름으로 전파하지 않고 dict 로 귀결.
        try:
            # (1) tabular → jh 본구현 위임 (전처리 피처공간 일치가 보장된 경로)
            if str(getattr(state, "category", "")).startswith("tabular"):
                adapted = self._shap_via_tabular_handler(state)
                if adapted and adapted.get("shap_top_features"):
                    return adapted
                # 위임이 빈손(skip/실패)이면 아래 자체 견고화 경로로 폴백

            # (2) 비-tabular 또는 위임 폴백 — 자체 견고화 경로
            return self._shap_robust(state, best)
        except Exception as e:  # noqa: BLE001
            self.logger.warning("shap_unexpected_error", error=str(e))
            return {"shap_error": f"SHAP 예기치 못한 오류: {e}"}

    # ------------------------------------------------------------------
    def _shap_via_tabular_handler(self, state: PipelineState) -> dict[str, Any] | None:
        """jh 의 tabular SHAP 본구현 결과를 G5/insight 가 읽는 키로 매핑.

        반환 키 정합: 팝업은 shap_top_features[].importance, insight 는 top_features(이름)를
        읽으므로 둘 다 채운다. 빈손이면 None → 자체 경로로 폴백.
        """
        try:
            from agents.handlers.tabular.explainability import explain as _tab_explain

            res = _tab_explain(state)
        except Exception as e:  # noqa: BLE001
            self.logger.warning("tabular_shap_delegate_failed", error=str(e))
            return None
        if not isinstance(res, dict):
            return None
        top = res.get("shap_top_features") or []
        ranking: list[dict[str, Any]] = []
        for ent in top:
            if not isinstance(ent, dict):
                continue
            imp = ent.get("mean_abs_shap", ent.get("importance", 0))
            try:
                imp = float(imp)
            except (TypeError, ValueError):
                imp = 0.0
            ranking.append(
                {"feature": str(ent.get("feature", "?")), "importance": imp, "direction": ent.get("direction")}
            )
        if not ranking:
            return None
        out: dict[str, Any] = {
            "shap_top_features": ranking,
            "top_features": [r["feature"] for r in ranking],  # insight._top_features 호환
            "explain_method": "tabular_handler",
        }
        for k in ("shap_summary_path", "shap_dependence_paths", "explainer_type"):
            if res.get(k):
                out[k] = res[k]
        return out

    # ------------------------------------------------------------------
    def _shap_robust(self, state: PipelineState, best: dict) -> dict[str, Any]:
        """자체 SHAP 경로 — 전처리 데이터·피처 정렬·explainer 라우팅·중요도 폴백."""
        import shap  # type: ignore

        from tools.minio_tool import get_minio_client

        mc = get_minio_client()

        # ── 1) 모델 로드 (self-healing: 1차 실패 시 자동 진단·복구·재시도) ──────────
        model, recovery = self._load_model_self_heal(state, mc, best)

        # ── 2) 데이터 로드 — 학습과 동일한 전처리 데이터 우선(피처공간 일치의 핵심) ──
        df = None
        try:
            from agents.handlers.common.shared import load_dataframe_from_state

            df = load_dataframe_from_state(state)
        except Exception as e:  # noqa: BLE001
            self.logger.warning("preprocessed_load_failed_raw_fallback", error=str(e))
            try:
                df = mc.load_dataframe(state.file_id, fmt=state.file_id.rsplit(".", 1)[-1].lower())
            except Exception as e2:
                return {"shap_error": f"설명용 데이터 로드 실패: {e2}", "shap_recovery": recovery}

        X = df.select_dtypes(include=[np.number, "bool"]).fillna(0)
        if state.target_column and state.target_column in X.columns:
            X = X.drop(columns=[state.target_column])

        # ── 3) 복구 최종 실패 → tabular_ml 은 동일 설정 surrogate 재학습으로 SHAP 산출 ──
        if model is None and state.category in ("tabular_ml",):
            model, recovery = self._refit_surrogate(state, df, X, best, recovery)
        if model is None:
            return {"shap_error": recovery.get("error") or "모델 로드 실패", "shap_recovery": recovery}

        # ── 4) 피처공간 정렬 — 모델이 학습한 컬럼/순서에 X 를 맞춤(불일치=실패 원천 차단) ──
        X = self._align_features(X, model)
        if X.shape[1] == 0 or len(X) == 0:
            return self._importance_fallback(model, X, None, recovery, "유효 수치 피처 없음")

        # permutation 폴백용 y (있으면)
        y = None
        if state.target_column and state.target_column in df.columns:
            try:
                y = df[state.target_column].loc[X.index]
            except Exception:  # noqa: BLE001
                y = None

        if len(X) > self.SAMPLE_SIZE:
            X = X.sample(self.SAMPLE_SIZE, random_state=42)
            if y is not None:
                try:
                    y = y.loc[X.index]
                except Exception:  # noqa: BLE001
                    y = None

        # ── 5) SHAP 계산 (실패 시 중요도 폴백) ──────────────────────────────────────
        try:
            result = self._compute_shap(shap, model, X, state, mc)
            if recovery.get("recovered") or recovery.get("surrogate"):
                result["shap_recovery"] = recovery  # 복구 흔적 → 리포트 정직 표기용
            return result
        except Exception as e:  # noqa: BLE001
            self.logger.warning("shap_compute_failed_importance_fallback", error=str(e))
            return self._importance_fallback(model, X, y, recovery, str(e))

    # ------------------------------------------------------------------
    @staticmethod
    def _align_features(X: Any, model: Any) -> Any:
        """모델이 학습한 피처공간에 X 를 정렬 — 누락=0채움, 여분=drop, 순서=일치."""
        names = getattr(model, "feature_names_in_", None)
        if names is not None:
            names = [str(n) for n in names]
            for n in names:
                if n not in X.columns:
                    X[n] = 0
            try:
                return X[names]
            except Exception:  # noqa: BLE001
                return X
        n_expected = getattr(model, "n_features_in_", None)
        if isinstance(n_expected, int) and n_expected > 0 and X.shape[1] != n_expected:
            if X.shape[1] > n_expected:
                return X.iloc[:, :n_expected]
            for i in range(n_expected - X.shape[1]):
                X[f"_pad_{i}"] = 0
        return X

    # ------------------------------------------------------------------
    def _compute_shap(self, shap: Any, model: Any, X: Any, state: PipelineState, mc: Any) -> dict[str, Any]:
        """explainer 라우팅 → top features + summary plot."""
        model_name = str((state.best_model or {}).get("model_name", ""))
        values, sv_obj = self._build_explainer(shap, model, X, model_name)
        mean_abs = self._mean_abs(values)
        n = min(len(mean_abs), X.shape[1])
        cols = list(X.columns[:n])
        mean_abs = np.asarray(mean_abs[:n], dtype=float)
        order = np.argsort(-mean_abs)
        ranking = [{"feature": str(cols[i]), "importance": float(mean_abs[i])} for i in order[:20]]
        summary_path = self._save_summary_plot(shap, sv_obj, values, X, state, mc)
        out: dict[str, Any] = {
            "shap_top_features": ranking,
            "top_features": [r["feature"] for r in ranking],
            "explain_method": "shap",
        }
        if summary_path:
            out["shap_summary_path"] = summary_path
        return out

    @staticmethod
    def _build_explainer(shap: Any, model: Any, X: Any, model_name: str) -> tuple[Any, Any]:
        """모델명 라우팅 + 범용 + KernelExplainer 폴백. 반환: (values, sv_obj_or_None)."""
        tree_models = {
            "RandomForest",
            "XGBoost",
            "LightGBM",
            "CatBoost",
            "GradientBoosting",
            "ExtraTrees",
            "DecisionTree",
            "IsolationForest",
            "HistGradientBoosting",
        }
        linear_models = {"LogisticRegression", "Ridge", "Lasso", "LinearRegression", "ElasticNet"}
        bg = X[:100]
        makers: list[Any] = []
        if model_name in tree_models:
            makers.append(lambda: shap.TreeExplainer(model))
        elif model_name in linear_models:
            makers.append(lambda: shap.LinearExplainer(model, bg))
        makers.append(lambda: shap.Explainer(model, bg))  # 범용 자동
        for make in makers:
            try:
                ex = make()
                sv = ex(X[:200])
                return (sv.values if hasattr(sv, "values") else sv), sv
            except Exception:  # noqa: BLE001
                continue
        # 최종 폴백 — KernelExplainer (어떤 모델이든 산출)
        predict_fn = getattr(model, "predict_proba", None) or model.predict
        ex = shap.KernelExplainer(predict_fn, X[:50])
        raw = ex.shap_values(X[:100], nsamples=50)
        return raw, None

    @staticmethod
    def _mean_abs(values: Any) -> Any:
        """shap values(list/2D/3D) → 피처별 평균 |SHAP|."""
        if isinstance(values, list):  # multi-class: class 별 (n, f)
            return np.mean([np.abs(np.asarray(v)).mean(axis=0) for v in values], axis=0)
        arr = np.asarray(values)
        if arr.ndim == 3:  # (n, f, classes)
            return np.abs(arr).mean(axis=(0, 2))
        if arr.ndim == 2:
            return np.abs(arr).mean(axis=0)
        return np.abs(arr).reshape(arr.shape[0], -1).mean(axis=0)

    def _save_summary_plot(
        self, shap: Any, sv_obj: Any, values: Any, X: Any, state: PipelineState, mc: Any
    ) -> str | None:
        try:
            import matplotlib  # noqa: WPS433

            matplotlib.use("Agg")
            import matplotlib.pyplot as plt  # noqa: WPS433

            plt.figure(figsize=(8, 6))
            try:
                if sv_obj is None:
                    raise RuntimeError("no explanation obj")
                shap.plots.beeswarm(sv_obj, show=False, max_display=15)
            except Exception:  # noqa: BLE001
                sv2 = values[0] if isinstance(values, list) else np.asarray(values)
                sv2 = np.asarray(sv2)
                if sv2.ndim == 3:
                    sv2 = sv2[..., 0]
                shap.summary_plot(sv2, X[: len(sv2)], show=False, max_display=15)
            tmpf = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
            tmpf.close()
            plt.savefig(tmpf.name, dpi=120, bbox_inches="tight")
            plt.close()
            return mc.save_artifact(tmpf.name, "explanations/shap", state.job_id)
        except Exception as e:  # noqa: BLE001
            self.logger.warning("shap_summary_plot_failed", error=str(e))
            return None

    def _importance_fallback(self, model: Any, X: Any, y: Any, recovery: dict[str, Any], reason: str) -> dict[str, Any]:
        """SHAP 최종 실패 시 — 모델 내장 중요도/계수/permutation 으로 산출(실패 대신 대체)."""
        imp = None
        try:
            fi = getattr(model, "feature_importances_", None)
            if fi is not None:
                imp = np.abs(np.asarray(fi, dtype=float))
            else:
                coef = getattr(model, "coef_", None)
                if coef is not None:
                    coef = np.asarray(coef, dtype=float)
                    imp = np.abs(coef).mean(axis=0) if coef.ndim > 1 else np.abs(coef)
            if imp is None and y is not None and len(X) > 0:
                from sklearn.inspection import permutation_importance

                r = permutation_importance(model, X, y, n_repeats=5, random_state=42, n_jobs=1)
                imp = np.abs(np.asarray(r.importances_mean, dtype=float))
        except Exception as e:  # noqa: BLE001
            self.logger.warning("importance_fallback_failed", error=str(e))
            imp = None

        if imp is not None and len(imp) > 0:
            n = min(len(imp), X.shape[1])
            cols = list(X.columns[:n])
            imp = np.asarray(imp[:n], dtype=float)
            order = np.argsort(-imp)
            ranking = [{"feature": str(cols[i]), "importance": float(imp[i])} for i in order[:20]]
            out: dict[str, Any] = {
                "shap_top_features": ranking,
                "top_features": [r["feature"] for r in ranking],
                "explain_method": "importance_fallback",
                "shap_fallback_reason": str(reason)[:200],
            }
            if recovery.get("recovered") or recovery.get("surrogate"):
                out["shap_recovery"] = recovery
            return out

        # 모든 수단 소진 — 정직 에러(근본원인 동봉)
        return {"shap_error": str(reason), "shap_recovery": recovery}

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
