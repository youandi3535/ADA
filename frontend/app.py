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
import time
from typing import Any

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
    token = st.text_input("JWT (옵션)", type="password",
                           value=st.session_state.get("token", ""))
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
tab1, tab2, tab3, tab4 = st.tabs(["1) 업로드/시작", "2) 에이전트 현황판",
                                   "3) HITL 응답", "4) 산출물/KB"])

# === 탭 1 — 업로드 ============================================================
with tab1:
    st.header("1) 데이터 업로드 & 파이프라인 시작")
    upl = st.file_uploader("CSV / Parquet / XLSX / ZIP / JSON / PDF / TXT / HTML",
                            type=["csv", "parquet", "xlsx", "zip", "json",
                                  "pdf", "txt", "html"])
    col1, col2 = st.columns(2)
    with col1:
        cat = st.selectbox("카테고리",
                            ["tabular_ml", "tabular_dl", "timeseries",
                             "anomaly_detection"])
        target = st.text_input("Target 컬럼 (해당 시)")
    with col2:
        intent = st.text_area("분석 의도 (자유 서술 1~3 문장)")
        outs = st.multiselect("원하는 산출물",
                                ["OUT-01", "OUT-02", "OUT-03", "OUT-04", "OUT-07"],
                                default=["OUT-04", "OUT-07"])

    if st.button("업로드", type="primary", disabled=upl is None):
        with st.spinner("업로드 중..."):
            resp = requests.post(
                f"{API_BASE}/upload",
                files={"file": (upl.name, upl.getvalue())},
                headers=_headers(), timeout=60,
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
            r = requests.post(f"{API_BASE}/pipeline/start",
                              json=payload, headers=_headers(), timeout=10)
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
            s = requests.get(f"{API_BASE}/pipeline/status/{job_id}",
                              headers=_headers(), timeout=5).json()
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
    job_id_h = st.text_input("Job ID ", value=st.session_state.get("job_id", ""),
                              key="hitl_job")
    gate = st.selectbox("게이트", ["G1", "G2", "G3", "G4", "G5"])
    choice_text = st.text_area("선택 (JSON)", value='{"adopted_rank": 1}')
    if st.button("응답 전송") and job_id_h:
        try:
            choice = json.loads(choice_text)
            r = requests.post(
                f"{API_BASE}/pipeline/resume/{job_id_h}",
                json={"gate": gate, "choice": choice},
                headers=_headers(), timeout=10,
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
    job_id_o = st.text_input("Job ID  ", value=st.session_state.get("job_id", ""),
                              key="out_job")
    if job_id_o:
        try:
            r = requests.get(f"{API_BASE}/pipeline/result/{job_id_o}",
                              headers=_headers(), timeout=5).json()
            st.json(r)
        except Exception as e:
            st.warning(str(e))
