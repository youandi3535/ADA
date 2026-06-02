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
# 로그인 흐름 (Day 18 v2):
#   1) email + password 입력 → POST /auth/login
#   2) 200 OK 면 access_token + role 을 session_state 에 저장
#   3) _headers() 가 이후 모든 API 호출에 Bearer 자동 부착
#   4) raw JWT 직접 입력은 expander 로 보존 (개발/디버그용)


def _do_login(email: str, password: str) -> tuple[bool, str]:
    """POST /auth/login. 성공 시 session_state 저장. (ok, message)."""
    try:
        r = requests.post(
            f"{API_BASE}/auth/login",
            json={"email": email, "password": password},
            timeout=8,
        )
    except Exception as e:
        return False, f"네트워크 오류: {e}"
    if r.status_code == 401:
        return False, "이메일 또는 비밀번호가 올바르지 않습니다."
    if not r.ok:
        return False, f"HTTP {r.status_code}: {r.text[:200]}"
    data = r.json()
    st.session_state["token"] = data.get("access_token", "")
    st.session_state["role"] = data.get("role", "analyst")
    st.session_state["email"] = email
    return True, f"로그인 성공 — {email} ({data.get('role')})"


def _do_logout() -> None:
    for k in ("token", "role", "email"):
        st.session_state.pop(k, None)


def _fetch_me() -> dict | None:
    """현재 토큰으로 /auth/me 조회. 토큰 만료 검증용."""
    if not st.session_state.get("token"):
        return None
    try:
        r = requests.get(f"{API_BASE}/auth/me", headers=_auth_header(), timeout=5)
        return r.json() if r.ok else None
    except Exception:
        return None


def _auth_header() -> dict[str, str]:
    """사이드바 내부 전용 — _headers() 정의 전에 사용해야 해서 별도."""
    t = st.session_state.get("token", "")
    return {"Authorization": f"Bearer {t}"} if t else {}


with st.sidebar:
    st.title("ADA v2")
    st.caption("정형 ML / 정형 DL / 시계열 / 이상탐지")
    st.text(f"API: {API_BASE}")
    st.divider()

    # ── 로그인 상태 분기 ──────────────────────────────────────────────────────
    if st.session_state.get("token"):
        # 로그인 후: 사용자 정보 + 로그아웃
        email = st.session_state.get("email", "(unknown)")
        role = st.session_state.get("role", "analyst")
        role_emoji = {"admin": "👑", "analyst": "📊", "viewer": "👁️"}.get(role, "👤")
        st.success(f"{role_emoji} **{email}**\n\nrole: `{role}`")
        if st.button("🚪 로그아웃", use_container_width=True):
            _do_logout()
            st.rerun()
    else:
        # 로그인 폼
        st.subheader("🔐 로그인")
        with st.form("login_form", clear_on_submit=False):
            email = st.text_input("이메일", placeholder="user@example.com", key="login_email")
            password = st.text_input("비밀번호", type="password", key="login_pw")
            submitted = st.form_submit_button("로그인", type="primary", use_container_width=True)
            if submitted:
                if not email or not password:
                    st.warning("이메일과 비밀번호를 입력하세요.")
                else:
                    ok, msg = _do_login(email, password)
                    if ok:
                        st.success(msg)
                        st.rerun()
                    else:
                        st.error(msg)

    # ── 고급: raw JWT 직접 입력 (개발/디버그) ─────────────────────────────────
    with st.expander("🛠️ 고급 — JWT 직접 입력", expanded=False):
        raw_token = st.text_input(
            "JWT (Bearer 토큰)",
            type="password",
            value=st.session_state.get("token", ""),
            key="raw_jwt",
            help="개발/디버그용. 외부에서 발급받은 토큰 붙여넣기.",
        )
        if st.button("토큰 적용", key="apply_raw_jwt"):
            if raw_token:
                st.session_state["token"] = raw_token
                st.session_state["email"] = "(raw JWT)"
                st.session_state["role"] = "unknown"
                st.rerun()

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
# 원리
# ----
# 1) GET /pipeline/result/{job_id} → outputs 테이블 행 + presigned URL 리스트
# 2) OUT-04 (HTML 대시보드) 는 requests 로 받아 components.html 인라인 임베드
# 3) OUT-01/02/03/07 은 presigned URL 로 다운로드 → st.download_button 제공
# 4) 새 탭 링크도 같이 제공해 MinIO 외부 접근 가능성 점검
_OUT_LABELS = {
    "OUT-01": ("📊 PPT 발표 자료", "pptx"),
    "OUT-02": ("📄 PDF 보고서", "pdf"),
    "OUT-03": ("📝 스크립트", "txt"),
    "OUT-04": ("🖥️ HTML 대시보드", "html"),
    "OUT-07": ("🧠 인사이트 요약", "md"),
}
_OUT_MIME = {
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "pdf": "application/pdf",
    "txt": "text/plain",
    "html": "text/html",
    "md": "text/markdown",
}


def _fmt_size(n: int | None) -> str:
    if not n:
        return "-"
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


with tab4:
    st.header("4) 산출물 / 자체학습 KB")

    colj, colb = st.columns([4, 1])
    with colj:
        job_id_o = st.text_input(
            "Job ID",
            value=st.session_state.get("job_id", ""),
            key="out_job",
            placeholder="UUID 형식 (예: 3f2a...e4d)",
        )
    with colb:
        st.write("")
        st.write("")
        do_refresh = st.button("🔄 새로고침", key="out_refresh")

    if job_id_o:
        try:
            r = requests.get(
                f"{API_BASE}/pipeline/result/{job_id_o}",
                headers=_headers(),
                timeout=10,
            )
        except Exception as e:
            st.warning(f"API 호출 실패: {e}")
            r = None

        if r is not None:
            if r.status_code == 404:
                st.error("해당 Job ID 를 찾을 수 없습니다.")
            elif not r.ok:
                st.error(f"HTTP {r.status_code}: {r.text[:200]}")
            else:
                data = r.json()
                status = data.get("status", "unknown")
                outputs = data.get("outputs") or []
                requested = data.get("requested_outputs") or []

                # ── 상단 요약 ─────────────────────────────────────────────────
                c1, c2, c3 = st.columns(3)
                c1.metric("Job 상태", status)
                c2.metric("산출물 개수", len(outputs))
                c3.metric("요청 코드", ", ".join(requested) or "-")

                if not outputs:
                    if status != "completed":
                        st.info(f"아직 산출물이 없습니다. (현재 상태: {status})")
                    else:
                        st.warning("Job 은 완료됐지만 outputs 테이블이 비어 있습니다. worker 로그를 확인하세요.")
                else:
                    st.divider()

                    # ── OUT-04 (HTML 대시보드) — 인라인 임베드 ───────────────
                    out04 = next((o for o in outputs if o.get("code") == "OUT-04"), None)
                    if out04 and out04.get("url"):
                        st.subheader("🖥️ HTML 대시보드 미리보기 (OUT-04)")
                        st.caption(
                            f"파일: `{out04.get('filename')}` · 크기: {_fmt_size(out04.get('size_bytes'))} · "
                            f"presigned URL 유효: {out04.get('url_expires_in', 3600)}초"
                        )
                        try:
                            resp = requests.get(out04["url"], timeout=30)
                            if resp.ok:
                                import streamlit.components.v1 as components

                                components.html(resp.text, height=820, scrolling=True)
                                st.markdown(
                                    f"[🔗 새 탭에서 열기]({out04['url']})  ·  "
                                    f"브라우저가 MinIO 에 직접 접근하지 못하면 위 임베드는 비어 보일 수 있습니다."
                                )
                            else:
                                st.warning(
                                    f"HTML 다운로드 실패 (HTTP {resp.status_code}). "
                                    f"MinIO endpoint 가 외부에서 접근 가능한지 .env 의 MINIO_ENDPOINT 확인."
                                )
                        except Exception as e:
                            st.warning(f"HTML 임베드 실패: {e}")

                        st.divider()

                    # ── 산출물 카드 그리드 ────────────────────────────────────
                    st.subheader("📦 산출물 목록")
                    cols = st.columns(2)
                    for i, item in enumerate(outputs):
                        code = item.get("code", "")
                        label, ext = _OUT_LABELS.get(code, (code, "bin"))
                        with cols[i % 2]:
                            with st.container(border=True):
                                st.markdown(f"**{label}**  `{code}`")
                                st.caption(
                                    f"파일: `{item.get('filename', '?')}`  ·  "
                                    f"크기: {_fmt_size(item.get('size_bytes'))}  ·  "
                                    f"생성: {item.get('generation_ms') or '-'} ms"
                                )

                                url = item.get("url")
                                if not url:
                                    st.warning("URL 발급 실패 (MinIO 미연결?). minio_path: "
                                               f"`{item.get('minio_path', '')}`")
                                    continue

                                # 다운로드 버튼 — presigned URL 로 직접 받음
                                try:
                                    dl = requests.get(url, timeout=30)
                                    if dl.ok:
                                        st.download_button(
                                            label=f"📥 {ext.upper()} 다운로드",
                                            data=dl.content,
                                            file_name=item.get("filename") or f"{code}.{ext}",
                                            mime=_OUT_MIME.get(ext, "application/octet-stream"),
                                            key=f"dl_{code}_{i}",
                                        )
                                    else:
                                        st.caption(f"다운로드 실패 HTTP {dl.status_code}")
                                except Exception as e:
                                    st.caption(f"다운로드 오류: {e}")

                                st.markdown(f"[🔗 새 탭에서 열기]({url})")

                # ── raw JSON (디버그용) ──────────────────────────────────────
                with st.expander("raw JSON (디버그)"):
                    st.json(data)


# === 탭 5 — KPI 대시보드 (Day 10) =============================================
# 임계치 색상 (Phase 11-3) — 초록/노랑/빨강 emoji
_KPI_THRESHOLDS = {
    "kp1": (0.80, 0.95),  # success rate: <80% 빨강, 80~95% 노랑, ≥95% 초록
    "kp2": (10.0, 30.0),  # avg duration min: ≤10 초록, 10~30 노랑, >30 빨강 (역방향)
    "kp5": (500.0, 2000.0),  # p95 ms: ≤500 초록, 500~2000 노랑, >2000 빨강 (역방향)
    "kp9": (0.10, 0.30),  # KB rate: <10% 빨강, 10~30% 노랑, ≥30% 초록
}


def _kpi_status_emoji(metric: str, value: float | None) -> str:
    """KPI 값을 임계치와 비교해 🟢🟡🔴 반환. None → ⚪."""
    if value is None:
        return "⚪"
    lo, hi = _KPI_THRESHOLDS.get(metric, (0, 0))
    # KP2, KP5 는 값이 작을수록 좋음 (역방향)
    if metric in ("kp2", "kp5"):
        if value <= lo:
            return "🟢"
        if value <= hi:
            return "🟡"
        return "🔴"
    # KP1, KP9 는 값이 클수록 좋음
    if value >= hi:
        return "🟢"
    if value >= lo:
        return "🟡"
    return "🔴"


def _kpi_fetch(api_base: str, headers: dict, since_h: int, bypass_cache: bool) -> tuple[dict, dict]:
    """KPI API 호출 → (data, meta). 실패 시 ({}, {"error": ...})."""
    params = {"since_hours": since_h}
    if bypass_cache:
        params["cache"] = "bypass"
    try:
        r = requests.get(
            f"{api_base}/admin/observability/kpi",
            params=params,
            headers=headers,
            timeout=10,
        )
    except Exception as e:
        return {}, {"error": f"네트워크 오류: {e}"}
    if r.status_code == 401:
        return {}, {"error": "401 — JWT 토큰을 사이드바에 입력하세요 (admin role)"}
    if r.status_code == 403:
        return {}, {"error": "403 — 관리자 권한 필요 (role=admin)"}
    if not r.ok:
        return {}, {"error": f"HTTP {r.status_code}: {r.text[:200]}"}
    return r.json(), {
        "cache_status": r.headers.get("X-KPI-Cache-Status", "unknown"),
        "cache_age": r.headers.get("X-KPI-Cache-Age", "0"),
    }


with tab5:
    st.header("5) KPI 대시보드")
    st.caption("최근 N 시간의 운영 지표 — KP1 E2E 성공률 / KP2 평균 종단 / KP5 p95 / KP9 KB 적용률")

    col_c1, col_c2, col_c3 = st.columns([1, 1, 3])
    with col_c1:
        since_h = st.number_input("최근 (시간)", min_value=1, max_value=720, value=24, step=1, key="kpi_since_h")
    with col_c2:
        st.write("")
        st.write("")
        refresh = st.button("🔄 KPI 갱신", key="kpi_refresh")
    with col_c3:
        st.write("")
        st.write("")
        force = st.checkbox("강제 갱신 (캐시 무시)", key="kpi_force")

    # 최초 진입 시 자동 1회
    if refresh or "kpi_data" not in st.session_state:
        with st.spinner("KPI 측정 중..."):
            data, meta = _kpi_fetch(API_BASE, _headers(), int(since_h), force)
        st.session_state["kpi_data"] = data
        st.session_state["kpi_meta"] = meta
        # 트렌드 누적 (Phase 11-1, 세션 한정 최대 20건)
        if data:
            history = st.session_state.setdefault("kpi_history", [])
            history.append(
                {
                    "measured_at": data.get("measured_at"),
                    "kp1": data.get("kp1_e2e_success_rate"),
                    "kp2": data.get("kp2_avg_duration_min"),
                    "kp5": data.get("kp5_p95_api_ms"),
                    "kp9": data.get("kp9_kb_citation_rate"),
                    "n_jobs": data.get("n_jobs_total"),
                }
            )
            if len(history) > 20:
                history.pop(0)

    data = st.session_state.get("kpi_data") or {}
    meta = st.session_state.get("kpi_meta") or {}

    # 에러 표시
    if meta.get("error"):
        st.error(meta["error"])

    # 캐시 상태 배지
    cache_status = meta.get("cache_status", "")
    if cache_status == "cached":
        st.caption(f"🔄 캐시 응답 (age {meta.get('cache_age', '0')}s)")
    elif cache_status == "fresh":
        st.caption("✨ 신규 측정")

    # KP 5종 카드 + emoji 상태
    kp1_v = data.get("kp1_e2e_success_rate")
    kp2_v = data.get("kp2_avg_duration_min")
    kp5_v = data.get("kp5_p95_api_ms")
    kp9_v = data.get("kp9_kb_citation_rate")
    n_total = data.get("n_jobs_total", 0)
    n_terminal = data.get("n_jobs_terminal", 0)

    kpi_cols = st.columns(5)
    kpi_cols[0].metric(
        f"KP1 E2E 성공률 {_kpi_status_emoji('kp1', kp1_v)}",
        f"{kp1_v * 100:.1f}%" if kp1_v is not None else "—",
    )
    kpi_cols[1].metric(
        f"KP2 평균 종단(분) {_kpi_status_emoji('kp2', kp2_v)}",
        f"{kp2_v:.2f}" if kp2_v is not None else "—",
    )
    kpi_cols[2].metric(
        f"KP5 p95 응답(ms) {_kpi_status_emoji('kp5', kp5_v)}",
        f"{kp5_v:.1f}" if kp5_v is not None else "—",
    )
    kpi_cols[3].metric(
        f"KP9 KB 적용률 {_kpi_status_emoji('kp9', kp9_v)}",
        f"{kp9_v * 100:.1f}%" if kp9_v is not None else "—",
    )
    kpi_cols[4].metric(
        "측정 Job 수",
        f"{n_total}",
        delta=f"terminal {n_terminal}" if n_total else None,
        delta_color="off",
    )

    # warnings 배너
    warnings_list = data.get("warnings") or []
    if warnings_list:
        with st.expander(f"⚠️ 측정 신뢰도 안내 ({len(warnings_list)}건)"):
            for w in warnings_list[:10]:
                st.caption(f"• {w}")

    # 트렌드 차트 (세션 한정)
    history = st.session_state.get("kpi_history") or []
    if len(history) >= 2:
        with st.expander("📈 KPI 트렌드 (세션 한정, 최근 20회)"):
            import pandas as _pd

            df = _pd.DataFrame(history)
            df["measured_at"] = _pd.to_datetime(df["measured_at"])
            df = df.set_index("measured_at")
            g1, g2 = st.columns(2)
            g3, g4 = st.columns(2)
            with g1:
                st.caption("KP1 (성공률)")
                if df["kp1"].notna().any():
                    st.line_chart(df["kp1"])
            with g2:
                st.caption("KP9 (KB 적용률)")
                if df["kp9"].notna().any():
                    st.line_chart(df["kp9"])
            with g3:
                st.caption("KP2 (평균 종단 분)")
                if df["kp2"].notna().any():
                    st.line_chart(df["kp2"])
            with g4:
                st.caption("KP5 (p95 ms)")
                if df["kp5"].notna().any():
                    st.line_chart(df["kp5"])

    # 데이터 소스
    ds = data.get("data_source") or {}
    if ds:
        with st.expander("🔍 데이터 출처"):
            for k, v in ds.items():
                st.caption(f"**{k.upper()}** ← {v}")

    # raw JSON
    with st.expander("raw KPI JSON"):
        if data:
            st.download_button(
                "📥 JSON 다운로드",
                data=json.dumps(data, ensure_ascii=False, indent=2),
                file_name=f"kpi_{(data.get('measured_at') or '')[:19].replace(':', '')}.json",
                mime="application/json",
                key="kpi_download",
            )
        st.json(data)


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


# =============================================================================
# ADR-008 L4 — PII 마스킹 통계 위젯
# =============================================================================
try:
    import requests
    import streamlit as st

    with st.expander("🛡️ 오늘의 PII 마스킹 (ADR-008 L4)", expanded=False):
        admin_jwt = st.text_input(
            "Admin JWT (PII 통계 조회용)",
            type="password",
            key="pii_admin_jwt",
        )
        if admin_jwt:
            try:
                r = requests.get(
                    f"{API_BASE}/admin/security/pii?since_hours=24",
                    headers={"Authorization": f"Bearer {admin_jwt}"},
                    timeout=5,
                )
                if r.status_code == 200:
                    data = r.json()
                    c1, c2, c3 = st.columns(3)
                    c1.metric("마스킹된 토큰 (24h)", data.get("total_tokens_masked", 0))
                    c2.metric("처리 요청 수", data.get("total_events", 0))
                    avg = (data["total_tokens_masked"] / data["total_events"]) if data["total_events"] else 0
                    c3.metric("요청당 평균 토큰", f"{avg:.2f}")

                    if data.get("by_hour"):
                        import pandas as pd

                        df_h = pd.DataFrame(data["by_hour"])
                        if not df_h.empty:
                            df_h = df_h.set_index("hour")
                            st.line_chart(df_h[["events", "tokens"]])

                    if data.get("top_actors"):
                        st.caption("상위 PII 처리 actor")
                        st.dataframe(data["top_actors"][:5], use_container_width=True, hide_index=True)
                elif r.status_code == 403:
                    st.error("403 — admin role JWT 필요")
                else:
                    st.warning(f"조회 실패: HTTP {r.status_code}")
            except Exception as e:
                st.error(f"네트워크 오류: {e}")
        else:
            st.info("Admin JWT 입력 시 PII 마스킹 통계 표시")
except Exception:
    pass
