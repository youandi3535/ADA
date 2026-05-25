"""frontend/app.py — Streamlit 메인 대시보드 (Day18).

페이지 구조:
  Sidebar — 환경/API URL/로그인 토큰
  1. 업로드 & 시작
  2. 에이전트 현황판 (실시간)
  3. 5게이트 HITL UI
  4. 산출물 다운로드
  5. 자체학습 KB 모니터
"""

from __future__ import annotations

import json
import os
from datetime import datetime

import requests
import streamlit as st

API_BASE = os.environ.get("API_BASE_URL", "http://api:8000")

st.set_page_config(
    page_title="ADA v2 — Adaptive AutoAI Studio",
    page_icon="🤖",
    layout="wide",
)

# --- 사이드바 ----------------------------------------------------------------
with st.sidebar:
    st.title("ADA v2")
    st.caption("정형 ML / 정형 DL / 시계열 / 이상탐지")
    st.text(f"API: {API_BASE}")
    token = st.text_input("JWT (옵션)", type="password", value=st.session_state.get("token", ""))
    if token:
        st.session_state["token"] = token
    st.divider()
    st.markdown("**5게이트 HITL**\nG1 분석 방향 · G2 방법론 · G3 모델 전략 · G4 모델 선택 · G5 산출물")


def _headers() -> dict[str, str]:
    h = {}
    if st.session_state.get("token"):
        h["Authorization"] = f"Bearer {st.session_state['token']}"
    return h


# --- 탭 ------------------------------------------------------------------
tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(
    [
        "1) 업로드/시작",
        "2) 에이전트 현황판",
        "3) HITL 응답",
        "4) 산출물/KB",
        "5) KPI 대시보드",
        "6) 🚨 오류 대시보드",
    ]
)

# === 탭 1 — 업로드 ============================================================
with tab1:
    st.header("1) 데이터 업로드 & 파이프라인 시작")
    upl = st.file_uploader(
        "CSV / Parquet / XLSX / ZIP / JSON / PDF / TXT / HTML",
        type=["csv", "parquet", "xlsx", "zip", "json", "pdf", "txt", "html"],
    )
    col1, col2 = st.columns(2)
    with col1:
        cat = st.selectbox("카테고리", ["tabular_ml", "tabular_dl", "timeseries", "anomaly_detection"])
        target = st.text_input("Target 컬럼 (해당 시)")
    with col2:
        intent = st.text_area("분석 의도 (자유 서술 1~3 문장)")
        outs = st.multiselect(
            "원하는 산출물", ["OUT-01", "OUT-02", "OUT-03", "OUT-04", "OUT-07"], default=["OUT-04", "OUT-07"]
        )

    if st.button("업로드", type="primary", disabled=upl is None):
        with st.spinner("업로드 중..."):
            resp = requests.post(
                f"{API_BASE}/upload",
                files={"file": (upl.name, upl.getvalue())},
                headers=_headers(),
                timeout=60,
            )
        if resp.ok:
            data = resp.json()
            st.success(f"file_id = {data['file_id']}")
            st.session_state["file_id"] = data["file_id"]
        else:
            st.error(resp.text)

    if st.session_state.get("file_id"):
        if st.button("파이프라인 시작"):
            payload = {
                "file_id": st.session_state["file_id"],
                "category": cat,
                "target_column": target or None,
                "user_intent": intent or None,
                "requested_outputs": outs,
            }
            r = requests.post(f"{API_BASE}/pipeline/start", json=payload, headers=_headers(), timeout=10)
            if r.ok:
                st.session_state["job_id"] = r.json()["job_id"]
                st.success(f"job_id = {st.session_state['job_id']}")
            else:
                st.error(r.text)


# === 탭 2 — 현황판 ===========================================================
with tab2:
    st.header("2) 에이전트 현황판")
    job_id = st.text_input("Job ID", value=st.session_state.get("job_id", ""))
    if job_id:
        try:
            s = requests.get(f"{API_BASE}/pipeline/status/{job_id}", headers=_headers(), timeout=5).json()
            col = st.columns(4)
            col[0].metric("status", s.get("status"))
            col[1].metric("gate", s.get("current_gate") or "-")
            col[2].metric("progress", f"{s.get('progress_pct', 0)}%")
            col[3].metric("error", s.get("error") or "-")
            st.json(s)
        except Exception as e:
            st.warning(f"status 조회 실패: {e}")
        st.caption("실시간 SSE 진행률은 /stream/progress/{job_id} 로 구독")


# === 탭 3 — HITL 응답 =========================================================
with tab3:
    st.header("3) HITL 게이트 응답")
    job_id_h = st.text_input("Job ID ", value=st.session_state.get("job_id", ""), key="hitl_job")
    gate = st.selectbox("게이트", ["G1", "G2", "G3", "G4", "G5"])
    choice_text = st.text_area("선택 (JSON)", value='{"adopted_rank": 1}')
    if st.button("응답 전송") and job_id_h:
        try:
            choice = json.loads(choice_text)
            r = requests.post(
                f"{API_BASE}/pipeline/resume/{job_id_h}",
                json={"gate": gate, "choice": choice},
                headers=_headers(),
                timeout=10,
            )
            if r.ok:
                st.success("재개 큐 적재 완료")
            else:
                st.error(r.text)
        except Exception as e:
            st.error(e)


# === 탭 4 — 산출물/KB ========================================================
with tab4:
    st.header("4) 산출물 / 자체학습 KB")
    job_id_o = st.text_input("Job ID  ", value=st.session_state.get("job_id", ""), key="out_job")
    if job_id_o:
        try:
            r = requests.get(f"{API_BASE}/pipeline/result/{job_id_o}", headers=_headers(), timeout=5).json()
            st.json(r)
        except Exception as e:
            st.warning(str(e))


# === 탭 5 — KPI 대시보드 (Day 10) =============================================
with tab5:
    st.header("5) KPI 대시보드")
    st.caption("최근 N 시간의 운영 지표 — KP1 E2E 성공률 / KP2 평균 시간 / KP5 p95 / KP9 KB 적용률")

    col_c1, col_c2 = st.columns([1, 4])
    with col_c1:
        since_h = st.number_input("최근 (시간)", min_value=1, max_value=720, value=24, step=1)
    with col_c2:
        st.write("")
        refresh = st.button("KPI 갱신", key="kpi_refresh")

    if refresh or "kpi_data" not in st.session_state:
        try:
            r = requests.get(
                f"{API_BASE}/admin/observability/prometheus_check",
                headers=_headers(),
                timeout=5,
            )
            if r.ok:
                st.session_state["kpi_prom"] = r.json()
        except Exception:
            pass

        # API 가 없으면 로컬 스크립트 호출 (개발 환경)
        try:
            import json as _j
            import subprocess

            p = subprocess.run(
                ["python", "scripts/kpi_measure.py", "--since", str(since_h), "--json"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if p.returncode == 0 and p.stdout.strip():
                st.session_state["kpi_data"] = _j.loads(p.stdout.strip())
        except Exception:
            st.session_state["kpi_data"] = None

    data = st.session_state.get("kpi_data") or {}
    kpi_cols = st.columns(5)
    kpi_cols[0].metric(
        "KP1 E2E 성공률",
        f"{(data.get('KP1_e2e_success_rate') or 0) * 100:.1f}%"
        if data.get("KP1_e2e_success_rate") is not None
        else "—",
    )
    kpi_cols[1].metric(
        "KP2 평균 종단(분)",
        f"{data.get('KP2_avg_duration_min', '—')}" if data.get("KP2_avg_duration_min") is not None else "—",
    )
    kpi_cols[2].metric(
        "KP5 p95 응답(ms)",
        f"{data.get('KP5_p95_api_ms', '—')}" if data.get("KP5_p95_api_ms") is not None else "—",
    )
    kpi_cols[3].metric(
        "KP9 KB 적용률",
        f"{(data.get('KP9_kb_citation_rate') or 0) * 100:.1f}%"
        if data.get("KP9_kb_citation_rate") is not None
        else "—",
    )
    kpi_cols[4].metric("최근 job 수", data.get("n_jobs", "—"))

    with st.expander("raw KPI JSON"):
        st.json(data)

    prom = st.session_state.get("kpi_prom")
    if prom:
        st.divider()
        st.subheader("Prometheus exposition 샘플")
        if prom.get("available"):
            st.success(f"메트릭 노출 OK · size {prom.get('size_bytes', 0)} bytes")
        else:
            st.warning("ada_agent_duration_seconds 미노출 — /metrics 확인 필요")


# === 탭 6 — 오류 자동처리 & KB 모니터링 대시보드 ================================
with tab6:
    # ── 헤더 ──────────────────────────────────────────────────────────────────
    st.markdown(
        """
        <div style="
            background: linear-gradient(90deg, #1a1a2e 0%, #16213e 100%);
            border-radius: 10px;
            padding: 16px 24px;
            margin-bottom: 16px;
            display: flex;
            align-items: center;
            border-left: 4px solid #e94560;
        ">
            <span style="font-size:24px; margin-right:12px;">🚨</span>
            <div>
                <span style="color:#fff; font-size:18px; font-weight:700;">
                    오류 자동처리 & 자체학습 모니터링 대시보드
                </span><br>
                <span style="color:#aaa; font-size:12px;">
                    AutoErrorHandlerAgent · SelfLearningAgent · ErrorKB · PendingPatch
                </span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # ── 조회 범위 & 새로고침 ───────────────────────────────────────────────────
    ctrl_c1, ctrl_c2, ctrl_c3 = st.columns([1, 1, 2])
    with ctrl_c1:
        err_since_h = st.number_input(
            "조회 범위 (시간)", min_value=1, max_value=720, value=24, step=1, key="err_since_h"
        )
    with ctrl_c2:
        st.write("")
        st.write("")
        err_refresh = st.button("🔄 새로고침", key="err_refresh")
    with ctrl_c3:
        only_unhandled = st.checkbox("미처리 오류만 표시", key="err_unhandled")

    # ── 데이터 로드 ────────────────────────────────────────────────────────────
    if err_refresh or "err_summary" not in st.session_state:
        try:
            r = requests.get(
                f"{API_BASE}/errors/dashboard/summary",
                params={"since_hours": err_since_h},
                headers=_headers(),
                timeout=8,
            )
            if r.ok:
                st.session_state["err_summary"] = r.json()
            else:
                st.session_state["err_summary"] = None
                st.warning(f"요약 조회 실패: {r.status_code} — JWT 토큰(admin)이 필요합니다.")
        except Exception as e:
            st.session_state["err_summary"] = None
            st.warning(f"API 연결 실패: {e}")

        try:
            r2 = requests.get(
                f"{API_BASE}/errors/dashboard/recent",
                params={"limit": 50, "only_unhandled": only_unhandled},
                headers=_headers(),
                timeout=8,
            )
            st.session_state["err_recent"] = r2.json() if r2.ok else None
        except Exception:
            st.session_state["err_recent"] = None

        try:
            r3 = requests.get(
                f"{API_BASE}/errors/dashboard/patches",
                headers=_headers(),
                timeout=8,
            )
            st.session_state["err_patches"] = r3.json() if r3.ok else None
        except Exception:
            st.session_state["err_patches"] = None

    summary_data = st.session_state.get("err_summary") or {}
    sm = summary_data.get("summary", {})
    recent_data = st.session_state.get("err_recent") or {}
    patch_data = st.session_state.get("err_patches") or {}

    # ── 요약 카드 4개 ──────────────────────────────────────────────────────────
    CARD_CSS = """
    <div style="
        background:{bg};
        border-radius:10px;
        padding:16px 20px;
        text-align:center;
        border-top: 4px solid {accent};
        box-shadow: 0 2px 8px rgba(0,0,0,0.15);
    ">
        <div style="font-size:32px; font-weight:800; color:{accent};">{value}</div>
        <div style="font-size:13px; color:#555; margin-top:4px;">{label}</div>
        <div style="font-size:11px; color:#999; margin-top:2px;">{sub}</div>
    </div>
    """

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown(
            CARD_CSS.format(
                bg="#fff8f8",
                accent="#e94560",
                value=sm.get("total_errors", "—"),
                label="총 오류 발생",
                sub="전체 누적",
            ),
            unsafe_allow_html=True,
        )
    with c2:
        rate = sm.get("auto_resolve_rate", 0)
        st.markdown(
            CARD_CSS.format(
                bg="#f0fff4",
                accent="#38a169",
                value=sm.get("auto_resolved", "—"),
                label="자동 해결",
                sub=f"해결률 {rate * 100:.1f}%",
            ),
            unsafe_allow_html=True,
        )
    with c3:
        st.markdown(
            CARD_CSS.format(
                bg="#fffaf0",
                accent="#dd6b20",
                value=sm.get("pending_patches", "—"),
                label="패치 검토 대기",
                sub="review_status=pending",
            ),
            unsafe_allow_html=True,
        )
    with c4:
        st.markdown(
            CARD_CSS.format(
                bg="#ebf8ff",
                accent="#3182ce",
                value=sm.get("kb_patterns", "—"),
                label="KB 등록 오류 패턴",
                sub="ErrorKB 총계",
            ),
            unsafe_allow_html=True,
        )

    st.write("")  # 간격

    # ── 차트 2개 (시간별 오류 + 카테고리별 비율) ──────────────────────────────
    chart_l, chart_r = st.columns([3, 2])

    with chart_l:
        st.markdown("#### 📈 시간별 오류 발생 현황")
        hourly = summary_data.get("hourly_errors", [])
        if hourly:
            import pandas as pd

            df_h = pd.DataFrame(hourly).rename(columns={"hour": "시간", "count": "오류 건수"})
            df_h["시간"] = pd.to_datetime(df_h["시간"])
            df_h = df_h.set_index("시간")
            st.line_chart(df_h["오류 건수"], use_container_width=True)
        else:
            st.info("최근 오류 데이터가 없습니다.")

    with chart_r:
        st.markdown("#### 🥧 오류 유형별 비율")
        by_cat = summary_data.get("by_category", [])
        if by_cat:
            import pandas as pd

            df_c = pd.DataFrame(by_cat).rename(columns={"category": "카테고리", "count": "건수"}).set_index("카테고리")
            st.bar_chart(df_c["건수"], use_container_width=True)
        else:
            st.info("카테고리 데이터가 없습니다.")

    st.divider()

    # ── 최근 경보 목록 ─────────────────────────────────────────────────────────
    st.markdown("#### 🔔 최근 오류 경보 목록")

    _SEV_ICON = {"CRITICAL": "🔴", "MEDIUM": "🟡", "INFO": "🟢"}
    _SEV_COLOR = {"CRITICAL": "#e94560", "MEDIUM": "#dd6b20", "INFO": "#38a169"}

    recent_items = (recent_data.get("items") or [])[:10]
    if recent_items:
        import pandas as pd

        df_r = pd.DataFrame(recent_items)
        df_r["등급"] = df_r["severity"].map(lambda s: _SEV_ICON.get(s, "⚪") + " " + s)
        df_r["자동처리"] = df_r["auto_handled"].map(lambda x: "✅ 완료" if x else "❌ 미처리")
        df_r["KB매칭"] = df_r["has_kb_match"].map(lambda x: "✅" if x else "—")
        display_cols = ["created_at", "등급", "error_category", "error_message", "자동처리", "KB매칭"]
        display_cols = [c for c in display_cols if c in df_r.columns]
        st.dataframe(
            df_r[display_cols].rename(
                columns={
                    "created_at": "발생시각",
                    "error_category": "오류 유형",
                    "error_message": "메시지 (200자)",
                }
            ),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.success("✅ 최근 오류 없음")

    st.divider()

    # ── 상세 로그 테이블 + CSV 다운로드 ────────────────────────────────────────
    with st.expander("📋 상세 오류 로그 (전체)", expanded=False):
        all_items = recent_data.get("items") or []
        if all_items:
            import pandas as pd

            df_all = pd.DataFrame(all_items)
            # CSV 다운로드
            csv_bytes = df_all.to_csv(index=False).encode("utf-8-sig")
            st.download_button(
                label="📥 CSV 다운로드",
                data=csv_bytes,
                file_name=f"error_log_{datetime.utcnow().strftime('%Y%m%d_%H%M')}.csv",
                mime="text/csv",
            )
            st.dataframe(df_all, use_container_width=True, hide_index=True)
        else:
            st.info("데이터 없음")

    st.divider()

    # ── 패치 관리 테이블 ───────────────────────────────────────────────────────
    st.markdown("#### 🔧 패치 대기 목록 (승인 / 거부)")

    patch_items = patch_data.get("items") or []
    pending_only = [p for p in patch_items if p.get("review_status") == "pending"]

    if pending_only:
        for patch in pending_only:
            with st.container(border=True):
                p1, p2, p3 = st.columns([3, 1, 1])
                with p1:
                    conf = patch.get("confidence", 0)
                    conf_color = "#38a169" if conf >= 0.7 else "#dd6b20" if conf >= 0.4 else "#e94560"
                    st.markdown(
                        f"**ID**: `{patch['id'][:16]}…` &nbsp;|&nbsp; "
                        f"신뢰도: <span style='color:{conf_color};font-weight:700'>{conf:.0%}</span> &nbsp;|&nbsp; "
                        f"생성: {(patch.get('created_at') or '')[:16]}",
                        unsafe_allow_html=True,
                    )
                    if patch.get("patch_preview"):
                        st.code(patch["patch_preview"], language="diff")
                with p2:
                    if st.button("✅ 승인", key=f"approve_{patch['id']}"):
                        try:
                            rv = requests.patch(
                                f"{API_BASE}/errors/dashboard/patches/{patch['id']}",
                                json={"action": "approve", "reviewer": "dashboard"},
                                headers=_headers(),
                                timeout=5,
                            )
                            if rv.ok:
                                st.success("승인 완료")
                                st.session_state.pop("err_patches", None)
                                st.rerun()
                            else:
                                st.error(rv.text)
                        except Exception as e:
                            st.error(str(e))
                with p3:
                    if st.button("❌ 거부", key=f"reject_{patch['id']}"):
                        try:
                            rv = requests.patch(
                                f"{API_BASE}/errors/dashboard/patches/{patch['id']}",
                                json={"action": "reject", "reviewer": "dashboard"},
                                headers=_headers(),
                                timeout=5,
                            )
                            if rv.ok:
                                st.warning("거부 처리됨")
                                st.session_state.pop("err_patches", None)
                                st.rerun()
                            else:
                                st.error(rv.text)
                        except Exception as e:
                            st.error(str(e))
    else:
        st.success("✅ 대기 중인 패치 없음")

    # 처리 완료된 패치 이력
    done_patches = [p for p in patch_items if p.get("review_status") != "pending"]
    if done_patches:
        with st.expander(f"처리 완료 패치 이력 ({len(done_patches)}건)", expanded=False):
            import pandas as pd

            df_done = pd.DataFrame(done_patches)[
                ["id", "review_status", "reviewer", "confidence", "created_at"]
            ].rename(
                columns={
                    "id": "패치 ID",
                    "review_status": "처리 결과",
                    "reviewer": "검토자",
                    "confidence": "신뢰도",
                    "created_at": "생성일시",
                }
            )
            st.dataframe(df_done, use_container_width=True, hide_index=True)

    st.divider()

    # ── KB 학습 현황 ───────────────────────────────────────────────────────────
    st.markdown("#### 🧠 자체학습 KB 현황")
    kb_type_data = summary_data.get("kb_by_type", [])
    top_kb_data = summary_data.get("top_kb", [])

    kb_l, kb_r = st.columns([1, 2])
    with kb_l:
        if kb_type_data:
            import pandas as pd

            df_kb = pd.DataFrame(kb_type_data).rename(columns={"kb_type": "KB 유형", "count": "건수"})
            st.dataframe(df_kb, use_container_width=True, hide_index=True)
        else:
            st.info("KB 데이터 없음")

    with kb_r:
        st.caption("ErrorKB 상위 패턴 (성공 횟수 기준)")
        if top_kb_data:
            import pandas as pd

            df_top = pd.DataFrame(top_kb_data).rename(
                columns={
                    "signature": "오류 시그니처",
                    "success_count": "자동처리 성공",
                    "fail_count": "실패",
                    "confidence": "신뢰도",
                }
            )
            st.dataframe(df_top, use_container_width=True, hide_index=True)
        else:
            st.info("ErrorKB 패턴 없음")
