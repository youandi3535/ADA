"""frontend/app.py — ADA Studio (단일 플로우 UI).

1) 랜딩(스플래시) → Start
2) 업로드 → 5게이트(HITL) → 산출물 : 확정 디자인(다크 히어로·진행도 스텝퍼·카드)을
   임베드(components.html)하고, 임베드 안에서 브라우저가 ADA API(localhost:8000)에 직접
   fetch 로 연동. 게이트 추천(proposals)·분석 결과·현재 게이트는 GET /pipeline/gate/{job}
   (LangGraph state) 에서 받아 표시. 분석 중에는 로딩바·진행률·경과/예상시간 표시.
"""

from __future__ import annotations

import os
import time as _time

# Day10 KPI 메트릭 레이블 — tab5: KPI 대시보드
_KPI_LABELS: dict[str, str] = {
    "KP1 E2E 성공률": "파이프라인 완주율 (%)",
    "KP2 평균 종단": "평균 종단 간 지연 (ms)",
    "KP5 p95": "p95 레이턴시 (ms)",
    "KP9 KB 적용률": "KB 활용 응답 비율 (%)",
}
# tab5: KPI 대시보드 탭 (5번째 탭)

import streamlit as st
import streamlit.components.v1 as components

st.set_page_config(
    page_title="ADA Studio — Adaptive AutoAI",
    page_icon="🪄",
    layout="wide",
    initial_sidebar_state="collapsed",
)

_HERO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "ada_hero.png")

st.markdown(
    """
    <style>
    @import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.min.css');
    html, body, [data-testid="stAppViewContainer"] {
        font-family: 'Pretendard', 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
    }
    #MainMenu, footer, [data-testid="stToolbar"], [data-testid="stDecoration"] { visibility: hidden; height: 0; }
    [data-testid="stHeader"] { background: transparent; }
    [data-testid="stAppViewContainer"] { background: #dbe7f6; }
    [data-testid="stSidebar"],
    [data-testid="collapsedControl"],
    [data-testid="stSidebarCollapsedControl"] { display: none !important; }
    .block-container { padding-top: 3rem; padding-bottom: 3rem; max-width: 1100px; margin: 0 auto; }
    .stButton > button[kind="primary"] {
        background: #1f3e5c !important; border: none !important; color: #fff !important;
        border-radius: 999px; padding: .6rem 2rem; box-shadow: 0 10px 24px rgba(31,62,92,.28);
    }
    .stButton > button[kind="primary"]:hover { background: #284e74 !important; }
    </style>
    """,
    unsafe_allow_html=True,
)

# ===========================================================================
# 업로드 + 진행 플로우 — 확정 디자인 + API 연동 (게이트/추천/결과는 /gate=LangGraph state)
# ===========================================================================
# 프로세스 재시작마다 고유값 — React가 srcdoc 변화를 감지해 iframe 을 반드시 재생성하게 함
_FLOW_NONCE: str = _time.strftime("%Y%m%d%H%M%S")

_FLOW_HTML = """
<!doctype html><html lang="ko"><head><meta charset="utf-8">
<!-- ADA-NONCE:__NONCE__ -->
<style>
  @import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.min.css');
  :root{ --ink:#19395a; --deep:#1f3e5c; --muted:#52647d; --line:#d8e3f2; --line2:#cdddf0; }
  *{box-sizing:border-box;}
  html,body{margin:0;height:100%;}
  body{min-height:100%;background:linear-gradient(160deg,#2b4a6b 0%,#243f5c 58%,#1c3450 100%);
    font-family:'Pretendard','Inter',-apple-system,BlinkMacSystemFont,sans-serif;color:var(--ink);}
  /* HJ 2026-06-12 — 1~7단계 flow 화면 크기 = 기존 0.75 의 90% → 0.675.
     (첫 시작화면=랜딩 은 Streamlit 위젯이라 .shell 을 안 써서 그대로 유지됨.) */
  .shell{width:100%;max-width:1440px;margin:0 auto;padding:34px 40px 48px;min-height:100%;
    display:flex;flex-direction:column;justify-content:center;zoom:0.675;}
  .brand{display:flex;align-items:center;gap:18px;color:#bcd2ec;margin-bottom:26px;}
  .brand .globe{font-size:38px;}
  .brand .nm{font-size:21px;letter-spacing:.26em;font-weight:700;}
  .brand .status{margin-left:auto;font-size:21px;font-weight:600;border-radius:999px;padding:9px 24px;
    background:rgba(255,255,255,.10);border:1px solid rgba(255,255,255,.18);color:#dce7f5;}
  .brand .status.paused{background:rgba(245,196,120,.16);border-color:rgba(245,196,120,.5);color:#f3cf8a;}
  .brand .status.done{background:rgba(122,224,180,.16);border-color:rgba(122,224,180,.5);color:#9fe6c4;}
  .steps{position:relative;display:flex;justify-content:space-between;margin:8px 10px 0;}
  .steps .line{position:absolute;top:34px;left:34px;right:34px;height:4px;background:rgba(255,255,255,.16);}
  .steps .fill{position:absolute;top:34px;left:34px;height:4px;background:#9fe6c4;transition:width .3s;}
  .step{position:relative;z-index:2;flex:1;display:flex;flex-direction:column;align-items:center;gap:14px;}
  .step .dot{width:68px;height:68px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-weight:800;font-size:28px;}
  .step .lab{text-align:center;line-height:1.2;}
  .step .nm{font-size:21px;color:#9fb6d4;white-space:nowrap;}
  .step .sub{font-size:16px;letter-spacing:.04em;color:#7e98ba;margin-top:5px;}
  .step.pending .dot{background:rgba(255,255,255,.08);color:#88a0bf;border:1px solid rgba(255,255,255,.20);}
  .step.done .dot{background:#9fe6c4;color:#0f4a36;}
  .step.active .dot{background:#fff;color:var(--deep);box-shadow:0 0 0 9px rgba(255,255,255,.16);}
  .step.active .nm{color:#fff;font-weight:700;}
  .step.reachable{cursor:pointer;}
  .prog-meta{display:flex;justify-content:flex-end;align-items:center;margin:20px 8px 0;color:#bcd2ec;font-size:22px;}
  .prog-meta b{color:#fff;}
  .card{background:#fff;border-radius:28px;margin:26px auto 0;width:1360px;max-width:100%;
    box-shadow:0 0 0 1px rgba(255,255,255,.10),0 36px 84px rgba(0,0,0,.42);padding:44px 52px 32px;display:flex;flex-direction:column;}
  .card h2{font-size:38px;font-weight:800;margin:0 0 6px;text-align:center;}
  .card .desc{font-size:23px;color:var(--muted);text-align:center;margin:0 0 28px;}
  .ahdr{text-align:center;}
  .ahdr .en{font-size:20px;color:#8aa0bd;font-style:italic;margin:3px 0 0;}
  .databar{display:flex;flex-wrap:wrap;gap:10px 22px;justify-content:center;align-items:center;background:#eef6ef;
    border:1px solid #cfe9d8;border-radius:14px;padding:13px 20px;margin:14px 0 4px;font-size:18px;color:#2a5e44;}
  .databar .t{font-weight:700;color:#1f7a52;}
  .databar b{color:#176a45;}
  .loadwrap{text-align:center;margin-top:24px;}
  .loadtxt{font-size:22px;color:#52647d;}
  .progbox{margin:28px auto 0;max-width:760px;text-align:center;}
  .lbar{height:20px;border-radius:10px;background:#e6edf6;overflow:hidden;max-width:760px;margin:22px auto 0;position:relative;}
  .lfill{height:100%;border-radius:10px;background:linear-gradient(90deg,#3f5d7e,#1f3e5c);transition:width .6s ease;}
  .lmeta{font-size:20px;color:#7e98ba;margin-top:16px;}
  .lmeta b{color:#3f5168;}
  .lagent{font-size:19px;color:#1f7a52;margin-top:8px;}
  @keyframes adapop{0%{transform:scale(.06);opacity:0;}60%{opacity:1;}100%{transform:scale(1);opacity:1;}}
  .opts.popin{transform-origin:top center;animation:adapop .55s cubic-bezier(.2,.8,.25,1.25);}
  .lbar.indet{position:relative;}
  .lbar.indet .lfill{width:32% !important;position:absolute;top:0;left:-32%;animation:indet 1.3s ease-in-out infinite;}
  @keyframes indet{0%{left:-32%;}100%{left:100%;}}
  .diag{margin:18px auto 0;background:#fff7ec;border:1px solid #f0d9b5;color:#8a5a16;border-radius:14px;padding:16px 20px;font-size:17px;line-height:1.75;text-align:left;max-width:840px;}
  .diag code{background:#f1e7d4;border-radius:6px;padding:2px 7px;font-size:15px;}
  .diag b{color:#6a4310;}
  .dz{border:2px dashed var(--line2);background:#f7faff;border-radius:20px;padding:34px;display:flex;align-items:center;gap:26px;cursor:pointer;}
  .dz.has{border-color:#1f7a52;background:#eefbf4;}
  .dz .ic{width:56px;height:56px;color:#6f93c4;flex:none;}
  .dz .t{font-size:26px;font-weight:600;color:var(--ink);}
  .dz .s{font-size:19px;color:var(--muted);margin-top:5px;}
  .browse{border:1px solid var(--line2);background:#fff;color:var(--deep);border-radius:12px;padding:15px 28px;font-size:22px;font-weight:600;font-family:inherit;cursor:pointer;}
  .intent{width:100%;margin-top:20px;border:1px solid var(--line);border-radius:14px;padding:20px 22px;font-size:24px;background:#fff;color:var(--ink);font-family:inherit;resize:vertical;min-height:90px;}
  .intent::placeholder{color:#9aa9bd;}
  .opts{display:grid;grid-template-columns:repeat(3,1fr);gap:22px;margin-top:16px;}
  .opt{position:relative;border:2px solid #e3ecf7;border-radius:20px;background:#fff;padding:26px 26px;cursor:pointer;transition:.15s;display:flex;flex-direction:column;}
  .opt:hover{border-color:#b9cbe4;}
  .opt.sel{border-color:#1f3e5c;box-shadow:0 14px 34px rgba(31,62,92,.14);}
  .opt .onum{font-size:15px;letter-spacing:.13em;color:#9aa9bd;font-weight:700;}
  .opt .rec{display:inline-block;margin-left:9px;font-size:13px;font-weight:700;color:#1f7a52;background:#e6f7ef;border:1px solid #b7e6cf;border-radius:999px;padding:3px 11px;vertical-align:middle;}
  .opt h3{font-size:25px;font-weight:800;color:var(--ink);margin:14px 0 8px;}
  .opt p{font-size:18px;color:#52647d;line-height:1.5;margin:0 0 14px;}
  /* CS 2026-06-10 — 글머리표 위·아래 간격 가독성 */
  .opt .ratbody{margin:0 0 14px;}
  .opt .ratline{font-size:18px;color:#52647d;line-height:1.55;margin:10px 0;padding:2px 0;}
  .opt .ratline:first-child{margin-top:0;}
  .opt .ratline:last-child{margin-bottom:0;}
  .opt .hint{font-size:15px;color:#1f7a52;background:#f0faf4;border-radius:9px;padding:8px 12px;margin:0 0 12px;}
  .opt .en2{font-size:17px;color:#8aa0bd;margin-bottom:14px;}
  .opt .time{margin-top:auto;font-size:16px;color:#8aa0bd;}
  .opt .ck{position:absolute;top:15px;right:15px;width:32px;height:32px;border-radius:50%;background:#1f3e5c;color:#fff;display:none;align-items:center;justify-content:center;font-size:17px;font-weight:800;}
  .opt.sel .ck{display:flex;}
  .opt textarea{width:100%;border:1px solid var(--line);border-radius:11px;padding:13px 15px;font-size:18px;font-family:inherit;color:var(--ink);min-height:130px;resize:vertical;}
  .res .grid2{display:grid;grid-template-columns:1fr 1fr;gap:20px;}
  .rcard{border:1px solid var(--line);border-radius:16px;background:#f7faff;padding:24px 28px;}
  .rcard h4{margin:0 0 14px;font-size:21px;color:var(--ink);}
  .rtext{font-size:18px;color:#3f5168;line-height:1.6;white-space:pre-wrap;margin:0;}
  .kpi{display:flex;gap:26px;flex-wrap:wrap;}
  .kpi .it{flex:1;min-width:120px;}
  .kpi .v{font-size:30px;font-weight:800;color:var(--deep);word-break:break-all;}
  .kpi .l{font-size:15px;color:var(--muted);margin-top:2px;}
  .chip{display:inline-block;font-size:18px;font-weight:600;color:var(--deep);background:#e6f0fc;border:1px solid var(--line2);border-radius:999px;padding:7px 16px;margin:5px 8px 0 0;}
  .chip.on{background:var(--deep);color:#fff;border-color:transparent;}
  .dlbtn{display:inline-flex;align-items:center;gap:8px;background:var(--deep);color:#fff;border-radius:14px;padding:12px 22px;text-decoration:none;font-size:18px;font-weight:700;font-family:inherit;margin:6px 8px 0 0;transition:.15s;}
  .dlbtn:hover{background:#284e74;}
  .dlbtn.unavail{background:#c0cfe0;cursor:not-allowed;pointer-events:none;}
  .err{background:#fbeaea;border:1px solid #e7b7b7;color:#a33;border-radius:14px;padding:15px 20px;font-size:19px;margin:0 0 20px;}
  /* CS 2026-06-10 — G2 Sub-1 (주제 선정) 팝업 모달 */
  .topicmodal{position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(15,30,50,.45);display:flex;align-items:center;justify-content:center;z-index:9000;padding:20px;}
  .topicmodal-inner{position:relative;background:#fff;border-radius:24px;max-width:1100px;width:100%;max-height:90vh;overflow-y:auto;padding:40px;box-shadow:0 24px 64px rgba(0,0,0,.3);}
  .topichdr{text-align:center;}
  .topichdr h2{font-size:32px;font-weight:800;margin:0;color:var(--ink);}
  .topichdr .en{font-size:20px;color:#8aa0bd;font-style:italic;margin:4px 0 0;}
  .topichdr .stepline{margin-top:14px;display:inline-block;}
  .topichdr .stepchip{font-size:14px;color:#6b7c95;background:#f0f4fa;border-radius:999px;padding:4px 12px;vertical-align:middle;}
  .topichdr .desc{font-size:15px;color:#6b7c95;opacity:.85;margin-left:8px;white-space:nowrap;vertical-align:middle;}
  .topicwrap{display:grid;grid-template-columns:1.6fr 1fr;gap:22px;margin-top:28px;}
  @media(max-width:1100px){.topicwrap{grid-template-columns:1fr;}}
  .topicrec{display:flex;flex-direction:column;gap:12px;}
  .topiccust{display:flex;flex-direction:column;}
  .topicrec .topicopt, .topiccust .topicopt{padding:20px 22px;}
  .topiccust .topicopt h3{margin-top:10px;}
  .topiccust textarea{width:100%;border:1px solid var(--line);border-radius:11px;padding:13px 15px;font-size:17px;font-family:inherit;color:var(--ink);min-height:200px;resize:vertical;margin-top:10px;}
  /* CS 2026-06-10 — 팝업 박스 2개 (OPTION 1 + OPTION 2) + 라디오 input */
  .topicbox{border:2px solid #e3ecf7;border-radius:20px;background:#fff;padding:24px 26px;display:flex;flex-direction:column;}
  .topicbox.box-active{border-color:#1f3e5c;box-shadow:0 14px 34px rgba(31,62,92,.14);}
  .topicbox .onum{font-size:13px;letter-spacing:.13em;color:#9aa9bd;font-weight:700;}
  .topicbox h3{font-size:20px;font-weight:800;color:var(--ink);margin:8px 0 16px;}
  .topicradios{display:flex;flex-direction:column;gap:8px;}
  .topicradio{display:flex;align-items:flex-start;gap:11px;padding:11px 13px;border-radius:11px;cursor:pointer;transition:.12s;border:1px solid transparent;}
  .topicradio:hover{background:#f5f8fc;}
  .topicradio input[type=radio]{margin-top:5px;width:18px;height:18px;cursor:pointer;flex:none;accent-color:#1f3e5c;}
  .topicradio .trtext{font-size:16px;color:var(--ink);flex:1;line-height:1.4;}
  .topicradio .rec{display:inline-block;margin-left:8px;font-size:12px;font-weight:700;color:#1f7a52;background:#e6f7ef;border:1px solid #b7e6cf;border-radius:999px;padding:2px 9px;}
  .topicradio-custom{align-items:stretch;padding:0;flex:1;}
  .topicradio-custom input[type=radio]{margin-top:18px;margin-left:13px;}
  .topicradio-custom textarea{flex:1;border:1px solid var(--line);border-radius:11px;padding:13px 15px;font-size:15px;font-family:inherit;color:var(--ink);min-height:180px;resize:vertical;margin:8px;}
  .topicfoot{display:flex;justify-content:flex-end;margin-top:28px;}
  .topicbtn{display:inline-flex;align-items:center;gap:8px;background:#1f3e5c;color:#fff;border:none;border-radius:999px;padding:11px 26px;font-size:17px;font-weight:700;font-family:inherit;cursor:pointer;box-shadow:0 8px 18px rgba(31,62,92,.26);}
  .topicbtn:disabled{opacity:.45;cursor:default;box-shadow:none;}
  .footer{display:flex;align-items:center;gap:16px;margin-top:28px;padding-top:24px;border-top:1px solid #eef2f8;}
  .spacer{flex:1;}
  .btn{font-family:inherit;font-weight:600;border-radius:999px;cursor:pointer;font-size:24px;white-space:nowrap;display:inline-flex;align-items:center;gap:10px;}
  .btn-ghost{background:#fff;color:var(--deep);border:1px solid var(--line2);padding:15px 30px;}
  .btn-ghost:disabled{opacity:.4;cursor:default;color:#9aa9bd;}
  .btn-stop{background:#fff;color:#b5481f;border:1px solid #e7c8ba;padding:18px 48px;box-shadow:0 13px 28px rgba(181,72,31,.14);}
  .btn-stop.engaged{background:#b5481f;color:#fff;border-color:#b5481f;box-shadow:0 13px 28px rgba(181,72,31,.32);}
  .btn-stop:disabled{opacity:.45;cursor:default;box-shadow:none;}
  .btn-primary{background:var(--deep);color:#fff;border:none;padding:18px 48px;box-shadow:0 13px 28px rgba(31,62,92,.26);}
  .btn-primary.resume{background:#1f7a52;}
  .btn-primary:disabled{opacity:.45;cursor:default;box-shadow:none;}
  .btn-new{font-family:inherit;font-size:15px;font-weight:600;border-radius:999px;cursor:pointer;
    background:rgba(255,255,255,.12);border:1px solid rgba(255,255,255,.28);color:#dce7f5;
    padding:7px 18px;margin-left:auto;margin-right:12px;white-space:nowrap;}
  .btn-new:hover{background:rgba(255,255,255,.20);}
  /* HJ 2026-06-12 — 옆의 status(대기) 배지와 글자 크기(21px)·박스 높이(padding 9px) 통일. */
  .btn-home{font-family:inherit;font-size:21px;font-weight:600;border-radius:999px;cursor:pointer;
    background:rgba(255,255,255,.12);border:1px solid rgba(255,255,255,.28);color:#dce7f5;
    padding:9px 20px;margin-left:14px;white-space:nowrap;}
  .btn-home:hover{background:rgba(255,255,255,.20);}
  /* HJ 2026-06-10 G1 분석 팝업 (revision 2) — G1 진입부터 G2 proposals 도착 전까지 표시. 모달 2배+. */
  .modal-overlay{position:fixed;inset:0;z-index:1000;display:flex;align-items:center;justify-content:center;padding:24px;background:rgba(20,30,50,.42);backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px);}
  /* HJ 2026-06-12 — 모달 팝업 60% 축소. zoom:.6 (백드롭 .modal-overlay 는 미적용 → 풀스크린 유지). */
  /* HJ 2026-06-12 — 외부 스크롤바 제거(overflow:hidden) + flex 컬럼. 제목/현재작업/진행바는 고정,
     실시간 분석 영역(#modal-scroll)만 내부 스크롤. 최대 높이 = 화면의 90% (zoom .6 보정: 150vh×.6≈90vh). */
  .modal-card{position:relative;zoom:.6;display:flex;flex-direction:column;background:#fff;border-radius:32px;padding:56px 76px 48px;width:min(1300px,95%);max-height:150vh;overflow:hidden;box-shadow:0 40px 100px rgba(0,0,0,.55);animation:modalIn .42s cubic-bezier(.2,.85,.25,1.2);}
  .modal-card>#modal-body,.modal-card>#modal-pending-wrap,.modal-card>#modal-pb{flex:0 0 auto;}
  /* 실시간 분석 내용 박스 — 내용이 길어지면 이 영역만 세로 스크롤. 타자기 진행 시 자동 바닥 추적. */
  #modal-scroll{flex:1 1 auto;min-height:0;overflow-y:auto;overflow-x:hidden;scrollbar-gutter:stable;}
  #modal-scroll::-webkit-scrollbar{width:10px;}
  #modal-scroll::-webkit-scrollbar-thumb{background:#c7d2e0;border-radius:6px;}
  #modal-scroll::-webkit-scrollbar-thumb:hover{background:#aebccf;}
  #modal-scroll::-webkit-scrollbar-track{background:transparent;}
  /* HJ 2026-06-10 — 모달 닫기 버튼 (분석은 백그라운드 유지, 팝업만 숨김) */
  .modal-close{position:absolute;top:18px;right:22px;width:44px;height:44px;border-radius:50%;border:none;background:rgba(31,62,92,.08);color:#1f3e5c;font-size:24px;font-weight:700;cursor:pointer;display:flex;align-items:center;justify-content:center;transition:background .2s,transform .15s;z-index:5;}
  .modal-close:hover{background:rgba(31,62,92,.18);transform:scale(1.08);}
  .modal-close-hint{position:absolute;top:74px;right:22px;font-size:13px;color:#8aa0bd;font-style:italic;pointer-events:none;}
  @keyframes modalIn{0%{transform:scale(.82) translateY(20px);opacity:0;}100%{transform:scale(1) translateY(0);opacity:1;}}
  .modal-title{font-size:60px;font-weight:800;color:var(--ink);text-align:center;margin:0 0 10px;line-height:1.1;}
  .modal-en{font-size:32px;color:#8aa0bd;font-style:italic;text-align:center;margin:0 0 32px;}
  .modal-card .progbox{margin-top:30px;}
  .modal-card .lbar{box-shadow:0 0 0 2px rgba(31,62,92,.10);}
  .modal-pending{background:#fffbeb;border:1px solid #fde68a;border-radius:16px;padding:22px 28px;margin-top:18px;}
  .modal-pending .t{font-weight:700;color:#92400e;margin-bottom:8px;font-size:28px;}
  .modal-pending .s{font-size:22px;color:#7c5012;line-height:1.4;}
  .modal-placeholder{text-align:center;padding:36px 0;color:#52647d;font-size:26px;}
  /* HJ 2026-06-10 — 모래시계 SVG (모던 디자인). 11초 사이클 = 10초 모래 떨어지기 + 1초 180° 회전.
     대칭 모래시계라 180° 회전 끝상태 = 0° 시작상태 (visual 동일) → loop snap 없이 자연스러움.
     0~91% (10초): 위 모래 scaleY 1→0 drain, 아래 모래 scaleY 0→1 fill, stream 표시
     91~100% (1초): 180° 회전, sand reset (회전 중 자연스럽게 마스킹) */
  .hg-svg{display:inline-block;vertical-align:middle;margin-right:8px;width:30px;height:46px;animation:hgFlip 11s ease-in-out infinite;transform-origin:50% 50%;}
  /* SVG view-box 좌표계 절대 px. transform-box:fill-box 가 일부 환경에서 안 잡혀 fallback 되는 문제 회피. */
  .hg-sand-top{transform-origin:16px 22px;animation:hgDrain 11s ease-in-out infinite;}
  .hg-sand-bot{transform-origin:16px 44px;animation:hgFill 11s ease-in-out infinite;}
  .hg-stream{animation:hgStream 11s ease-in-out infinite;}
  @keyframes hgFlip{0%,80%{transform:rotate(0deg);}100%{transform:rotate(180deg);}}
  @keyframes hgDrain{0%{transform:scaleY(1);}76%,100%{transform:scaleY(0);}}
  @keyframes hgFill{0%{transform:scaleY(0);}76%,100%{transform:scaleY(1);}}
  @keyframes hgStream{0%,3%{opacity:0;}6%,72%{opacity:1;}76%,100%{opacity:0;}}
  @keyframes cmIn{from{opacity:0;transform:translateY(10px);}to{opacity:1;transform:translateY(0);}}
  /* HJ 2026-06-10 — 모달 텍스트 타자기 효과. 글자 단위 reveal. 분석 시간 흡수용. */
  .tw{display:inline;white-space:pre-wrap;}
  .tw-caret{display:inline-block;width:2px;height:1em;background:#1f3e5c;margin-left:2px;vertical-align:-2px;animation:twBlink 0.85s steps(2,start) infinite;opacity:.85;}
  @keyframes twBlink{to{visibility:hidden;}}
  /* HJ 2026-06-10 — 마일스톤 세그먼트 바. 각 segment = 단계의 한 agent. 완료/현재/대기 색상 구분. */
  .ms-bar{display:flex;width:100%;min-height:48px;background:#eef2f8;border-radius:12px;overflow:hidden;border:1px solid #d8e3f2;max-width:760px;margin:0 auto;}
  .ms-seg{flex:1;display:flex;align-items:center;justify-content:center;padding:6px 8px;font-size:13px;font-weight:600;color:#7e98ba;border-right:1px solid rgba(255,255,255,.6);transition:background .35s,color .35s;min-width:0;line-height:1.35;text-align:center;word-break:keep-all;overflow-wrap:break-word;}
  .ms-seg:last-child{border-right:none;}
  .ms-seg-icon{margin-right:4px;font-weight:800;}
  .ms-seg.done{background:#1f7a52;color:#fff;}
  .ms-seg.active{background:linear-gradient(90deg,#1f3e5c,#2c5783);color:#fff;animation:msPulse 1.6s ease-in-out infinite;}
  .ms-seg.pending{background:#f7faff;color:#8aa0bd;}
  @keyframes msPulse{0%,100%{box-shadow:inset 0 0 0 0 rgba(255,255,255,0);}50%{box-shadow:inset 0 0 0 100px rgba(255,255,255,.10);}}
  .modal-card .ms-bar{min-height:64px;border-radius:14px;max-width:none;}
  .modal-card .ms-seg{font-size:15px;padding:10px 14px;}
  @media(max-width:1100px){ .opts,.res .grid2{grid-template-columns:1fr;} }
</style></head><body>
  <!-- 랜딩 오버레이 — G1 이전 단계 클릭 시 표시. 원본 Python 랜딩과 동일한 스타일 -->
  <div id="landingOverlay" style="display:none;position:fixed;top:0;left:0;width:100%;height:100%;
    z-index:9999;background:#dbe7f6;flex-direction:column;align-items:center;justify-content:center;
    overflow-y:auto;padding:40px 20px;font-family:'Pretendard','Inter',-apple-system,sans-serif;">
    <!-- 히어로 카드 (원본 ada_hero.png 대체 — Python fallback 과 동일한 스타일) -->
    <!-- HJ 2026-06-12 — 랜딩 콘텐츠 60% 축소 (오버레이 백드롭은 풀스크린 유지). -->
    <div style="zoom:.6;max-width:960px;width:100%;border-radius:34px;padding:80px 64px;
      background:linear-gradient(160deg,#2b4a6b 0%,#3f5d7e 100%);color:#e6eef8;text-align:center;
      box-shadow:0 32px 80px rgba(31,62,92,.34);margin-bottom:44px;">
      <div style="font-size:18px;letter-spacing:.30em;opacity:.85;font-weight:600">ADAPTIVE&nbsp;&nbsp;DATA&nbsp;&nbsp;ANALYST</div>
      <div style="font-size:160px;line-height:1.0;margin:24px 0 4px">🌐</div>
    </div>
    <!-- 텍스트 + 버튼 -->
    <div style="text-align:center;zoom:.6;">
      <div style="font-size:72px;font-weight:800;color:#19395a;margin:0 0 18px">ADA Studio</div>
      <div style="font-size:24px;color:#52647d;margin:0 0 40px">다섯 번의 선택으로, 데이터를 전문가 수준 인사이트로!</div>
      <button onclick="startFromLanding()" style="font-family:inherit;font-size:20px;font-weight:600;
        border:none;border-radius:999px;cursor:pointer;background:#1f3e5c;color:#fff;
        padding:.7rem 2.4rem;box-shadow:0 10px 24px rgba(31,62,92,.28)">✦&nbsp;&nbsp;시작</button>
    </div>
  </div>
  <div class="shell">
    <div class="brand"><span class="globe">🌐</span><span class="nm">ADAPTIVE&nbsp;&nbsp;DATA&nbsp;&nbsp;ANALYST</span><span class="status" id="status">대기</span><button class="btn-home" id="homeBtn" onclick="goToStart()">← 처음(시작화면)으로</button></div>
    <div class="steps" id="steps"></div>
    <div class="prog-meta">현재 단계 <b id="curName">업로드</b> · 진행 <b id="curPct">0%</b> (<span id="curIdx">1</span>/<span id="curTot">7</span>)</div>
    <div class="card"><div class="content" id="content"></div><div id="pb-area"></div>
      <div class="footer">
        <button class="btn btn-ghost" id="prevBtn">← 이전 단계</button>
        <button class="btn btn-ghost" id="nextBtn">다음 단계 →</button>
        <span class="spacer"></span>
        <button class="btn btn-stop" id="stopBtn">⏹ 정지</button>
        <button class="btn btn-primary" id="primaryBtn">⬆ 업로드</button>
      </div>
    </div>
  </div>
  <!-- HJ 2026-06-10 G1→G2 전환 팝업 모달 — render() 가 inModalLoading() 기반으로 표시·숨김 제어. 배경 자동 blur. -->
  <div id="modalOverlay" class="modal-overlay" style="display:none">
    <div class="modal-card">
      <button class="modal-close" id="modalCloseBtn" title="팝업 닫기 (분석은 계속 진행)" onclick="dismissModal()">✕</button>
      <div class="modal-close-hint">분석은 백그라운드 계속</div>
      <div id="modal-body"></div><div id="modal-scroll"><div id="modal-insight"></div></div><div id="modal-pending-wrap"></div><div id="modal-pb"></div>
    </div>
  </div>
  <!-- HJ 2026-06-11 — 모달 ✕ 닫은 후 화면 가운데에 표시되는 '다시 열기' 버튼. 1~6단계 모두 지원.
       render() 가 modalDismissed && _shouldModalBeShown() 시점에만 display:flex 토글.
       2026-06-11 수정 — 우측 하단 floating → 화면 가운데, 크기 2배 (눈에 띄는 큰 박스 버튼). -->
  <button id="reopenModalBtn" onclick="reopenModal()" style="display:none;position:fixed;top:50%;left:50%;transform:translate(-50%,-50%) scale(.6);z-index:500;
    background:#1f3e5c;color:#fff;border:none;border-radius:24px;padding:28px 48px;font-size:34px;font-weight:600;font-family:inherit;
    cursor:pointer;box-shadow:0 20px 48px rgba(31,62,92,.4);align-items:center;justify-content:center;gap:16px;transition:transform .15s,box-shadow .2s">
    🔍 분석 모달 다시 열기
  </button>
<!-- HJ 2026-06-09 G1 단축 Phase 4 — client-side 파일 파싱 (PapaParse: CSV, SheetJS: XLSX) -->
<script src="https://cdnjs.cloudflare.com/ajax/libs/PapaParse/5.4.1/papaparse.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/xlsx/0.18.5/xlsx.full.min.js"></script>
<script>
const steps=[{label:'업로드',sub:'G1 · 데이터 파악'},{label:'분석 방향',sub:'G2 · EDA'},{label:'방법론',sub:'G3 · 전처리·피처링'},{label:'모델 전략',sub:'G4 · 모델학습·하이퍼파라미터'},{label:'모델 선택',sub:'G5 · 모델튜닝·평가'},{label:'산출물',sub:'G6 · 리포트'},{label:'완료',sub:'G7 · 인사이트'}];
const N=steps.length, LAST=N-1;
const ANALYZE_EST=45;  // 분석 중 진행률 추정용(초)
// 단계(cur 0~5)별 백엔드 글로벌 progress_pct 의 범위.
// orchestrator/runner.py AGENT_PHASE_MAP 의 "해당 단계 마지막 agent 종료점" 기준.
// 백엔드는 전체 파이프라인 0~100% 로 publish 하지만, 화면은 각 단계의 0~100% 로 보여줘야
// 사용자가 "G1 안에서 14% 천장 찍고 점프" 같은 혼란을 안 겪는다.
const STAGE_RANGE=[
  [0, 18],   // G1: supervisor → schema_validator → gate_direction
  [18, 33],  // G2: eda_agent → gate_methodology
  [33, 50],  // G3: preprocessing → feature_engineer → gate_model_strategy
  [50, 85],  // G4: model_selection → training → metrics → gate_best_model
  [85, 98],  // G5: fine_tune → eval → explainability → insight → gate_outputs
  [98, 100], // G6: report_composer → self_learning_dispatch
];
const GATE_TITLE={G2:['어떤 방식으로 분석할까요?','Choose your analysis direction'],G3:['어떤 방법론으로 진행할까요?','Choose your methodology'],G4:['어떤 모델 전략을 쓸까요?','Choose your model strategy'],G5:['어떤 모델을 채택할까요?','Pick the best model'],G6:['어떤 산출물을 만들까요?','Choose your outputs']};
// CS 2026-06-10 — 게이트 전환 구간 (proposals 도착 전) 사용자 친화 설명.
// 카드 보일 때 (proposals 도착) = 정적 GATE_TITLE. 그 외 로딩 = 동적.
const STAGE_TRANSITION_DESC={
  1:{ko:'분석 방향 카드를 준비 중입니다',en:'Preparing analysis direction cards'},
  2:{ko:'EDA를 분석 중입니다',en:'Running EDA analysis'},
  3:{ko:'전처리·피처 엔지니어링 중입니다',en:'Running preprocessing & feature engineering'},
  4:{ko:'모델 학습 중입니다',en:'Training models'},
  5:{ko:'평가·인사이트 분석 중입니다',en:'Running evaluation & insight analysis'},
  6:{ko:'산출물을 생성 중입니다',en:'Generating outputs'}
};
// CS 2026-06-10 — 카테고리별 헤더 매핑 (h2 + en + desc).
// 우선 G2 정적(cur=1) + G2→G3 로딩(cur=2) 만 적용. 나머지 게이트는 본인 확인 후 일괄.
const GATE_HEADER_BY_CATEGORY={
  static:{
    1:{
      tabular_ml:{h2:'어떤 정형 ML 데이터의 분석 방향으로 진행할까요?',en:'Choose your tabular ML analysis direction',desc:'분포·결측·도메인 등 정형 ML 데이터 파악을 마쳤습니다. 분석 방향을 선택해주세요.'},
      tabular_dl:{h2:'어떤 정형 DL 데이터의 분석 방향으로 진행할까요?',en:'Choose your tabular DL analysis direction',desc:'고차원·피처 분포 등 정형 DL 데이터 파악을 마쳤습니다. 분석 방향을 선택해주세요.'},
      timeseries:{h2:'어떤 시계열 데이터의 분석 방향으로 진행할까요?',en:'Choose your time series analysis direction',desc:'정상성·자기상관·계절성 등 시계열 데이터 파악을 마쳤습니다. 분석 방향을 선택해주세요.'},
      anomaly_detection:{h2:'어떤 이상탐지 데이터의 분석 방향으로 진행할까요?',en:'Choose your anomaly detection analysis direction',desc:'분포·outlier 후보·tail 등 이상탐지 데이터 파악을 마쳤습니다. 분석 방향을 선택해주세요.'},
      _default:{h2:'어떤 데이터의 분석 방향으로 진행할까요?',en:'Choose your data analysis direction',desc:'데이터 특성 파악을 마쳤습니다. 분석 방향을 선택해주세요.'}
    },
    2:{
      tabular_ml:{h2:'어떤 정형 ML 데이터의 방법론으로 진행할까요?',en:'Choose your tabular ML methodology',desc:'분포·상관관계·도메인 등 정형 ML EDA 분석을 마쳤습니다. 진행할 방법론을 선택해주세요.'},
      tabular_dl:{h2:'어떤 정형 DL 데이터의 방법론으로 진행할까요?',en:'Choose your tabular DL methodology',desc:'분포·상관관계·도메인 등 정형 DL EDA 분석을 마쳤습니다. 진행할 방법론을 선택해주세요.'},
      timeseries:{h2:'어떤 시계열 데이터의 방법론으로 진행할까요?',en:'Choose your time series methodology',desc:'분포·상관관계·도메인 등 시계열 EDA 분석을 마쳤습니다. 진행할 방법론을 선택해주세요.'},
      anomaly_detection:{h2:'어떤 이상탐지 데이터의 방법론으로 진행할까요?',en:'Choose your anomaly detection methodology',desc:'분포·상관관계·도메인 등 이상탐지 EDA 분석을 마쳤습니다. 진행할 방법론을 선택해주세요.'},
      _default:{h2:'어떤 데이터의 방법론으로 진행할까요?',en:'Choose your methodology',desc:'분포·상관관계·도메인 등 EDA 분석을 마쳤습니다. 진행할 방법론을 선택해주세요.'}
    },
    3:{
      tabular_ml:{h2:'어떤 정형 ML 데이터의 모델 전략으로 진행할까요?',en:'Choose your tabular ML model strategy',desc:'인코딩·스케일링·피처 생성 등 정형 ML 전처리·피처링을 마쳤습니다. 진행할 모델 전략을 선택해주세요.'},
      tabular_dl:{h2:'어떤 정형 DL 데이터의 모델 전략으로 진행할까요?',en:'Choose your tabular DL model strategy',desc:'인코딩·스케일링·피처 생성 등 정형 DL 전처리·피처링을 마쳤습니다. 진행할 모델 전략을 선택해주세요.'},
      timeseries:{h2:'어떤 시계열 데이터의 모델 전략으로 진행할까요?',en:'Choose your time series model strategy',desc:'인코딩·스케일링·피처 생성 등 시계열 전처리·피처링을 마쳤습니다. 진행할 모델 전략을 선택해주세요.'},
      anomaly_detection:{h2:'어떤 이상탐지 데이터의 모델 전략으로 진행할까요?',en:'Choose your anomaly detection model strategy',desc:'인코딩·스케일링·피처 생성 등 이상탐지 전처리·피처링을 마쳤습니다. 진행할 모델 전략을 선택해주세요.'},
      _default:{h2:'어떤 데이터의 모델 전략으로 진행할까요?',en:'Choose your model strategy',desc:'인코딩·스케일링·피처 생성 등 전처리·피처링을 마쳤습니다. 진행할 모델 전략을 선택해주세요.'}
    },
    4:{
      tabular_ml:{h2:'어떤 정형 ML 데이터의 모델 선택으로 진행할까요?',en:'Choose your tabular ML model selection',desc:'후보 모델 학습·하이퍼파라미터 탐색 등 정형 ML 모델 학습을 마쳤습니다. 사용할 모델을 선택해주세요.'},
      tabular_dl:{h2:'어떤 정형 DL 데이터의 모델 선택으로 진행할까요?',en:'Choose your tabular DL model selection',desc:'후보 모델 학습·하이퍼파라미터 탐색 등 정형 DL 모델 학습을 마쳤습니다. 사용할 모델을 선택해주세요.'},
      timeseries:{h2:'어떤 시계열 데이터의 모델 선택으로 진행할까요?',en:'Choose your time series model selection',desc:'후보 모델 학습·하이퍼파라미터 탐색 등 시계열 모델 학습을 마쳤습니다. 사용할 모델을 선택해주세요.'},
      anomaly_detection:{h2:'어떤 이상탐지 데이터의 모델 선택으로 진행할까요?',en:'Choose your anomaly detection model selection',desc:'후보 모델 학습·하이퍼파라미터 탐색 등 이상탐지 모델 학습을 마쳤습니다. 사용할 모델을 선택해주세요.'},
      _default:{h2:'어떤 데이터의 모델 선택으로 진행할까요?',en:'Choose your model selection',desc:'후보 모델 학습·하이퍼파라미터 탐색 등 모델 학습을 마쳤습니다. 사용할 모델을 선택해주세요.'}
    },
    5:{
      tabular_ml:{h2:'어떤 정형 ML 데이터의 산출물을 원하나요?',en:'Choose your tabular ML deliverables',desc:'교차검증·성능 비교 등 정형 ML 모델 튜닝·평가를 마쳤습니다. 원하는 산출물을 선택해주세요.'},
      tabular_dl:{h2:'어떤 정형 DL 데이터의 산출물을 원하나요?',en:'Choose your tabular DL deliverables',desc:'교차검증·성능 비교 등 정형 DL 모델 튜닝·평가를 마쳤습니다. 원하는 산출물을 선택해주세요.'},
      timeseries:{h2:'어떤 시계열 데이터의 산출물을 원하나요?',en:'Choose your time series deliverables',desc:'교차검증·성능 비교 등 시계열 모델 튜닝·평가를 마쳤습니다. 원하는 산출물을 선택해주세요.'},
      anomaly_detection:{h2:'어떤 이상탐지 데이터의 산출물을 원하나요?',en:'Choose your anomaly detection deliverables',desc:'교차검증·성능 비교 등 이상탐지 모델 튜닝·평가를 마쳤습니다. 원하는 산출물을 선택해주세요.'},
      _default:{h2:'어떤 데이터의 산출물을 원하나요?',en:'Choose your deliverables',desc:'교차검증·성능 비교 등 모델 튜닝·평가를 마쳤습니다. 원하는 산출물을 선택해주세요.'}
    }
  },
  loading:{
    1:{
      tabular_ml:{h2:'정형 데이터의 EDA 작업 중입니다',en:'G2 — Tabular Data EDA',desc:'정형 ML 데이터에 맞는 EDA와 방법론 후보를 평가하는 중입니다. 끝나면 자동으로 방법론 추천이 표시됩니다.'},
      tabular_dl:{h2:'정형 DL 데이터의 EDA 작업 중입니다',en:'G2 — Tabular DL Data EDA',desc:'정형 DL 데이터에 맞는 EDA와 방법론 후보를 평가하는 중입니다. 끝나면 자동으로 방법론 추천이 표시됩니다.'},
      timeseries:{h2:'시계열 데이터의 EDA 작업 중입니다',en:'G2 — Time Series Data EDA',desc:'시계열 ML 데이터에 맞는 EDA와 방법론 후보를 평가하는 중입니다. 끝나면 자동으로 방법론 추천이 표시됩니다.'},
      anomaly_detection:{h2:'이상탐지 데이터의 EDA 작업 중입니다',en:'G2 — Anomaly Detection Data EDA',desc:'이상탐지 ML 데이터에 맞는 EDA와 방법론 후보를 평가하는 중입니다. 끝나면 자동으로 방법론 추천이 표시됩니다.'},
      _default:{h2:'데이터의 EDA 작업 중입니다',en:'G2 — Data EDA',desc:'데이터에 맞는 EDA와 방법론 후보를 평가하는 중입니다. 끝나면 자동으로 방법론 추천이 표시됩니다.'}
    },
    2:{
      tabular_ml:{h2:'정형 ML 데이터의 EDA 분석 중입니다',en:'G2 - Tabular ML Data EDA',desc:'업로드하신 정형 ML 데이터에 대해 분포·결측·상관관계·클래스 균형 분석과 방법론 후보를 평가하는 중입니다. 끝나면 자동으로 방법론 추천이 표시됩니다.'},
      tabular_dl:{h2:'정형 DL 데이터의 EDA 분석 중입니다',en:'G2 - Tabular DL Data EDA',desc:'업로드하신 정형 DL 데이터에 대해 고차원 시각화·피처 상호작용 분석과 방법론 후보를 평가하는 중입니다. 끝나면 자동으로 방법론 추천이 표시됩니다.'},
      timeseries:{h2:'시계열 데이터의 EDA 분석 중입니다',en:'G2 - Time Series Data EDA',desc:'업로드하신 시계열 데이터에 대해 정상성 검정·자기상관·계절성 분해와 방법론 후보를 평가하는 중입니다. 끝나면 자동으로 방법론 추천이 표시됩니다.'},
      anomaly_detection:{h2:'이상탐지 데이터의 EDA 분석 중입니다',en:'G2 - Anomaly Detection Data EDA',desc:'업로드하신 이상탐지 데이터에 대해 신호·contamination 추정·heavy-tail 분석과 방법론 후보를 평가하는 중입니다. 끝나면 자동으로 방법론 추천이 표시됩니다.'},
      _default:{h2:'데이터의 EDA 분석 중입니다',en:'G2 - Data EDA',desc:'업로드하신 데이터에 대해 EDA를 진행하고 방법론 후보를 평가하는 중입니다. 끝나면 자동으로 방법론 추천이 표시됩니다.'}
    },
    3:{
      tabular_ml:{h2:'정형 ML 데이터의 전처리 및 피처링 중입니다',en:'G3 - Tabular ML Data Preprocessing & Feature Engineering',desc:'업로드하신 정형 ML 데이터에 대해 인코딩·스케일링·결측치 처리·피처 생성을 진행하며 모델 전략 후보를 검토하는 중입니다. 검토가 끝나면 모델 전략 추천을 자동으로 보여드립니다.'},
      tabular_dl:{h2:'정형 DL 데이터의 전처리 및 피처링 중입니다',en:'G3 - Tabular DL Data Preprocessing & Feature Engineering',desc:'업로드하신 정형 DL 데이터에 대해 임베딩·정규화·텐서 변환을 진행하며 모델 전략 후보를 검토하는 중입니다. 검토가 끝나면 모델 전략 추천을 자동으로 보여드립니다.'},
      timeseries:{h2:'시계열 데이터의 전처리 및 피처링 중입니다',en:'G3 - Time Series Data Preprocessing & Feature Engineering',desc:'업로드하신 시계열 데이터에 대해 결측 보간·차분·시차(lag)·롤링 피처 생성을 진행하며 모델 전략 후보를 검토하는 중입니다. 검토가 끝나면 모델 전략 추천을 자동으로 보여드립니다.'},
      anomaly_detection:{h2:'이상탐지 데이터의 전처리 및 피처링 중입니다',en:'G3 - Anomaly Detection Data Preprocessing & Feature Engineering',desc:'업로드하신 이상탐지 데이터에 대해 정규화·피처 스케일링·이상 점수 후보 피처 생성을 진행하며 모델 전략 후보를 검토하는 중입니다. 검토가 끝나면 모델 전략 추천을 자동으로 보여드립니다.'},
      _default:{h2:'데이터의 전처리 및 피처링 중입니다',en:'G3 - Data Preprocessing & Feature Engineering',desc:'업로드하신 데이터에 대해 전처리·피처 엔지니어링을 진행하며 모델 전략 후보를 검토하는 중입니다. 검토가 끝나면 모델 전략 추천을 자동으로 보여드립니다.'}
    },
    4:{
      tabular_ml:{h2:'정형 ML 데이터의 모델학습 및 하이퍼파라미터 작업을 진행 중입니다',en:'G4 - Tabular ML Model Training & Hyperparameter Tuning',desc:'업로드하신 정형 ML 데이터로 후보 모델 학습과 하이퍼파라미터 탐색을 진행하며 모델 후보를 비교하는 중입니다. 비교가 끝나면 모델 선택 추천을 자동으로 보여드립니다.'},
      tabular_dl:{h2:'정형 DL 데이터의 모델학습 및 하이퍼파라미터 작업을 진행 중입니다',en:'G4 - Tabular DL Model Training & Hyperparameter Tuning',desc:'업로드하신 정형 DL 데이터로 신경망 후보 모델 학습과 하이퍼파라미터 탐색을 진행하며 모델 후보를 비교하는 중입니다. 비교가 끝나면 모델 선택 추천을 자동으로 보여드립니다.'},
      timeseries:{h2:'시계열 데이터의 모델학습 및 하이퍼파라미터 작업을 진행 중입니다',en:'G4 - Time Series Model Training & Hyperparameter Tuning',desc:'업로드하신 시계열 데이터로 예측 모델 학습과 하이퍼파라미터 탐색을 진행하며 모델 후보를 비교하는 중입니다. 비교가 끝나면 모델 선택 추천을 자동으로 보여드립니다.'},
      anomaly_detection:{h2:'이상탐지 데이터의 모델학습 및 하이퍼파라미터 작업을 진행 중입니다',en:'G4 - Anomaly Detection Model Training & Hyperparameter Tuning',desc:'업로드하신 이상탐지 데이터로 이상탐지 모델 학습과 하이퍼파라미터 탐색을 진행하며 모델 후보를 비교하는 중입니다. 비교가 끝나면 모델 선택 추천을 자동으로 보여드립니다.'},
      _default:{h2:'데이터의 모델학습 및 하이퍼파라미터 작업을 진행 중입니다',en:'G4 - Model Training & Hyperparameter Tuning',desc:'업로드하신 데이터로 모델 학습과 하이퍼파라미터 탐색을 진행하며 모델 후보를 비교하는 중입니다. 비교가 끝나면 모델 선택 추천을 자동으로 보여드립니다.'}
    },
    5:{
      tabular_ml:{h2:'정형 ML 데이터의 모델 튜닝 및 평가를 진행 중입니다',en:'G5 - Tabular ML Model Tuning & Evaluation',desc:'선택하신 정형 ML 모델로 교차검증·성능 비교·설명가능성 분석을 진행하며 산출물 후보를 준비하는 중입니다. 준비가 끝나면 산출물 선택지를 자동으로 보여드립니다.'},
      tabular_dl:{h2:'정형 DL 데이터의 모델 튜닝 및 평가를 진행 중입니다',en:'G5 - Tabular DL Model Tuning & Evaluation',desc:'선택하신 정형 DL 모델로 검증 성능 비교·설명가능성 분석을 진행하며 산출물 후보를 준비하는 중입니다. 준비가 끝나면 산출물 선택지를 자동으로 보여드립니다.'},
      timeseries:{h2:'시계열 데이터의 모델 튜닝 및 평가를 진행 중입니다',en:'G5 - Time Series Model Tuning & Evaluation',desc:'선택하신 시계열 모델로 교차검증·예측 성능 비교를 진행하며 산출물 후보를 준비하는 중입니다. 준비가 끝나면 산출물 선택지를 자동으로 보여드립니다.'},
      anomaly_detection:{h2:'이상탐지 데이터의 모델 튜닝 및 평가를 진행 중입니다',en:'G5 - Anomaly Detection Model Tuning & Evaluation',desc:'선택하신 이상탐지 모델로 임계값 튜닝·탐지 성능 비교를 진행하며 산출물 후보를 준비하는 중입니다. 준비가 끝나면 산출물 선택지를 자동으로 보여드립니다.'},
      _default:{h2:'데이터의 모델 튜닝 및 평가를 진행 중입니다',en:'G5 - Model Tuning & Evaluation',desc:'선택하신 모델로 튜닝·평가를 진행하며 산출물 후보를 준비하는 중입니다. 준비가 끝나면 산출물 선택지를 자동으로 보여드립니다.'}
    },
    6:{
      tabular_ml:{h2:'정형 ML 데이터의 산출물 생성 중입니다',en:'G6 - Tabular ML Output Generation',desc:'선택하신 산출물을 바탕으로 정형 ML 분석 인사이트를 정리하는 중입니다. 정리가 끝나면 최종 산출물이 자동으로 생성됩니다.'},
      tabular_dl:{h2:'정형 DL 데이터의 산출물 생성 중입니다',en:'G6 - Tabular DL Output Generation',desc:'선택하신 산출물을 바탕으로 정형 DL 분석 인사이트를 정리하는 중입니다. 정리가 끝나면 최종 산출물이 자동으로 생성됩니다.'},
      timeseries:{h2:'시계열 데이터의 산출물 생성 중입니다',en:'G6 - Time Series Output Generation',desc:'선택하신 산출물을 바탕으로 시계열 분석 인사이트를 정리하는 중입니다. 정리가 끝나면 최종 산출물이 자동으로 생성됩니다.'},
      anomaly_detection:{h2:'이상탐지 데이터의 산출물 생성 중입니다',en:'G6 - Anomaly Detection Output Generation',desc:'선택하신 산출물을 바탕으로 이상탐지 분석 인사이트를 정리하는 중입니다. 정리가 끝나면 최종 산출물이 자동으로 생성됩니다.'},
      _default:{h2:'데이터의 산출물 생성 중입니다',en:'G6 - Output Generation',desc:'선택하신 산출물을 바탕으로 분석 인사이트를 정리하는 중입니다. 정리가 끝나면 최종 산출물이 자동으로 생성됩니다.'}
    }
  }
};
const API=(function(){ let p='http:',h='localhost'; try{ p=window.parent.location.protocol; h=window.parent.location.hostname; }catch(e){} if(p!=='http:'&&p!=='https:')p='http:'; if(!h)h='localhost'; return p+'//'+h+':8000'; })();
let cur=0, frontier=0, maxReached=0, paused=false, follow=true, busy=false, polling=false, pollTimer=null;
// HJ 2026-06-11 — 정지 토글: 눌림(navUnlocked=true) 상태에서만 이전/다음 단계 활성. 1~6단계(cur=0~5) 적용.
let navUnlocked=false;
let _suppressG1Advance=false; // 사용자가 뒤로가기로 G1 으로 이동했을 때 자동 G1→G2 전환 억제
let jobId=null, fileId=null, selectedFile=null, intentText='', status={}, errMsg='';
// HJ 2026-06-09 G1 단축 Phase 4 — θ-B prefetch state.
// 파일 선택 시점에 client-side 파싱 → 백엔드 /upload/prefetch → 카테고리 LLM 미리 시작.
// G1 시작 전에 사용자가 의도 입력하는 ~10s 동안 카테고리 LLM (~15s) 흡수.
let prefetchSig=null;                  // 현재 파일의 signature
let prefetchResult=null;               // {category, target_column, auto_intent, cached}
let prefetchPolling=false;             // /prefetch/{sig} polling 중복 방지
let prefetchPreview=null;              // {rows, cols, columns} — UI 즉시 표시용
let gateData={}, selId=null, selGate=null, customText='', analyzeStart=null, animatedGate=null;
// CS 2026-06-10 — G2 Sub-1 (주제 선정 팝업) 상태 변수
let g2SubStage='topic';          // 'topic' (디폴트) → 'direction' (선택 완료 후)
let selectedTopic={id:1};        // {id:1~5} 또는 {custom:"text"}
let topicCustomText='';          // 직접 입력 textarea 값
let g2DirectionsBusy=false;      // endpoint 호출 중 표시용
let g2DirectionsStartedAt=null;  // HJ 2026-06-11 — busy 시작 시각(ms). 버튼 라벨에 경과초 표시용.
let g2DirectionsReady=false;     // endpoint 응답 받았는지 (resume 가드)
let _g2PrefetchedJob=null;       // HJ 2026-06-12 — 분석 방향 백그라운드 선생성을 job 당 1회만 발사하기 위한 가드.
let lastSubmittedGate=null;  // resume 후 이 게이트가 사라질 때까지 계속 폴링
let g5Checked={};  // G6 멀티선택 상태 {proposal_id: bool}
let gateCache={};  // {G2: gateData, G3: gateData, ...} — 이전 단계 뒤로가기 시 재표시용
let _sawAnalyzingAfterSubmit=false;  // resume 후 analyzing() 상태를 거쳤는지 — stale gate 차단
// HJ 2026-06-10 — 모달 닫기 (사용자가 ✕ 누름). 같은 cur 동안만 유효, 다음 단계 진입 시 자동 reset.
let modalDismissed=false;
let _modalDismissedCur=-1;     // dismissed 가 발생한 cur — cur 변경되면 자동 해제
function dismissModal(){ modalDismissed=true; _modalDismissedCur=cur; try{render();}catch(e){} }
// HJ 2026-06-11 — 분석 모달 ✕ 닫은 후 다시 열기. 1~6단계(cur=0~5) 모두 동일 동작.
//   사용자가 떠다니는 "🔍 분석 모달 다시 열기" 버튼 클릭 → modalDismissed=false → render → 모달 재표시.
function reopenModal(){ modalDismissed=false; try{render();}catch(e){} }
// HJ 2026-06-11 — 주제 선정 팝업 닫기 (사용자가 ✕ 누름). 같은 cur 동안만 유효, cur 변경 시 자동 reset.
// 본문에 "🎯 주제 선정 다시 열기" 버튼이 노출되어 언제든 다시 띄울 수 있음.
let topicDismissed=false;
let _topicDismissedCur=-1;
function dismissTopic(){ topicDismissed=true; _topicDismissedCur=cur; try{render();}catch(e){} }
function reopenTopicPopup(){ topicDismissed=false; try{render();}catch(e){} }
// HJ 2026-06-12 — G2 분석 방향 백그라운드 선(先)생성 트리거.
//   주제 팝업이 뜨는 순간, 5개 주제(추천이 배열 첫번째)를 prefetch 엔드포인트로 1회 발사(fire-and-forget).
//   백엔드가 추천부터 순차 생성해 Redis 캐시에 저장 → 사용자가 '선택 완료' 누르면 즉시 응답(대기 0).
//   직접 입력(custom)은 캐시에 없어 기존대로 그 자리에서 생성된다.
//   job 당 1회만 발사(_g2PrefetchedJob 가드). 새 분석(jobId 변경)이면 자동 재발사.
function _g2FirePrefetch(d){
  if(!jobId || _g2PrefetchedJob===jobId) return;
  var tps=(d&&d.topic_proposals)||[];
  if(!tps.length) return;
  var topics=tps.slice(0,5).map(function(t){return (t&&t.title)||'';}).filter(function(s){return !!s;});
  if(!topics.length) return;
  _g2PrefetchedJob=jobId;  // 먼저 세팅 → render 반복 중 중복 발사 방지
  try{
    api('/pipeline/gate/G2/directions/prefetch/'+jobId,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({topics:topics})}).catch(function(){});
  }catch(e){}
}
// HJ 2026-06-11 — 모달 표시 후 콘텐츠 작성 시작까지 최소 대기(ms).
//   • 모달이 처음 떴을 때 잠시 "분석 중" placeholder 만 보여주고, 5초 후부터 실제 분석 내용을 작성한다.
//   • 만약 5초 경과 시점에 데이터가 아직 도착 안 했으면 placeholder 유지 → 데이터 도착 즉시(다음 render 주기) 자동 작성.
//   • cur 변경 / dismiss / 모달 닫힘 시 _modalOpenedAt 리셋되어 다음 단계에서 다시 0→5s 카운트.
let _modalOpenedAt=null;
let _modalOpenedCur=-1;
const MODAL_CONTENT_DELAY_MS=5000;
function _modalContentReady(){
  if(_modalOpenedAt==null) return false;
  return (Date.now()-_modalOpenedAt) >= MODAL_CONTENT_DELAY_MS;
}
// HJ 2026-06-11 — 타자기 작성 완료 후 다음 단계로 넘어가기까지 추가 hold 시간(ms).
//   • 모달 내 모든 타자기(_twAllDone) 가 끝난 시점부터 3초 동안 사용자가 내용을 읽을 시간 확보.
//   • 그 동안 backend 분석이 끝나(proposals 도착) 도 cur 자동 전환 / 모달 닫힘은 대기.
//   • 타자기에 새 콘텐츠가 추가되어 다시 미완료 상태가 되면 hold 카운트 리셋 → 다시 완료 후 3초.
let _twAllDoneAt=null;
const POST_TYPING_HOLD_MS=3000;
function _typingHoldComplete(){
  if(!_twAllDone()){
    if(_twAllDoneAt!=null) _twAllDoneAt=null;
    return false;
  }
  // HJ 2026-06-11 버그픽스: _shownPct<100 가드 제거.
  //   이 함수는 "다음 게이트 proposals 가 이미 도착한 후"에만 실질적으로 호출됨 → backend 추가 publish 없음.
  //   _shownPct<100 를 유지하면 G1 등에서 progress 가 100 에 도달하지 않는 엣지케이스(95% 고착 등)에서
  //   _twAllDoneAt 영구 리셋 → hold 영구 false → 11분 넘어도 다음 단계 불가 고착 버그.
  //   새 콘텐츠 도착 시 _miEl.innerHTML 교체 → _twAllDone()=false → _twAllDoneAt=null 자동 리셋.
  //   즉 "타자기 도중 추가 콘텐츠 도착" 케이스는 _twAllDone() 가 자연스럽게 처리. 별도 가드 불필요.
  if(_twAllDoneAt==null){
    _twAllDoneAt=Date.now();
    // 정확한 3초 시점 재렌더 보장. 모달 닫힘 직후 cur 전진 + stale 해제를 즉시 수행 (다음 poll 2.5s 기다리지 않음).
    setTimeout(function(){
      try{
        // hold 완료 시점(이 콜백 등록 = _twAllDoneAt 설정 시점 기준 3초 후)에 다음 게이트가 와있으면 전진.
        if(_nextGateArrived()){
          lastSubmittedGate=null; _sawAnalyzingAfterSubmit=false; follow=true;
        }
        if(follow && frontier>cur){ cur=Math.max(cur,frontier); }
        render();
      }catch(_e){}
    }, POST_TYPING_HOLD_MS+50);
  }
  return (Date.now()-_twAllDoneAt) >= POST_TYPING_HOLD_MS;
}
// HJ 2026-06-11 — "다음 단계 진입" 판정: 제출한 게이트보다 '높은 번호' 게이트가 도착했는지.
//   backend 는 분석 중 일시적으로 stale 이전 게이트(예: G3 분석 중 G2)를 publish 할 수 있다(app.py:998 주석 참조).
//   curGate()!==lastSubmittedGate 만으로 해제하면 그 stale G2 에 속아 모달이 분석 도중 사라지고
//   3단계 선택화면(cur=2 본문)으로 빠지는 버그 발생. 번호 비교로 '진짜 다음 게이트(G4)'만 인정.
function _nextGateArrived(){
  const g=curGate();
  if(!lastSubmittedGate || !g) return false;
  return parseInt(g.slice(1),10) > parseInt(lastSubmittedGate.slice(1),10);
}
// HJ 2026-06-12 — 6단계(G6) 완료 race fix.
//   G6 는 다음 게이트가 없어 isCompleted() 로 종료되는데, 팝업의 실시간 분석 타이핑이 끝나기 전에
//   완료 신호가 오면 모달이 즉시 닫히고 7단계(완료 페이지)로 점프해버린다.
//   다른 단계의 "_typingHoldComplete() 전까지 전진 금지" 원칙을 G6 완료에도 동일 적용한다.
//   이 hold 동안: ① 모달 유지 ② 진행률 95% 고정 ③ 마지막 마일스톤 active(파랑) 유지.
function _g6TypingHold(){ return cur===5 && isCompleted() && !_typingHoldComplete(); }

// ── F5 새로고침 복원용 스토리지 유틸 ────────────────────────────
// 1순위: URL 해시(#ada=…) — window.parent.history.replaceState 로 기록.
//   해시는 F5 후에도 URL 에 보존되며, origin 이슈 없이 동일 세션에서 접근 가능.
// 2순위: window.parent.localStorage — 1순위 읽기 실패 시 폴백.
var _FRESH_START=false;// __FRESH_START_INJECT__
const _SK='ada_flow_v1';
function _stateRead(){
  try{
    var h=window.parent.location.hash,m=h.match(/ada=([^&]*)/);
    if(m) return decodeURIComponent(m[1]);
  }catch(e){}
  try{ return window.parent.localStorage.getItem(_SK); }catch(e){}
  return null;
}
function saveState(){
  if(!jobId) return;
  if(isFailed()){ clearState(); return; }  // 완료 시엔 유지 — F5 새로고침 후 결과 화면 복원
  // CS 2026-06-10 — G2 Sub-1 (주제 팝업) 상태도 보존 (F5 새로고침 시 복원)
  var d=JSON.stringify({jobId:jobId,fileId:fileId,cur:cur,maxReached:maxReached,
    g2SubStage:g2SubStage,selectedTopic:selectedTopic,topicCustomText:topicCustomText,g2DirectionsReady:g2DirectionsReady});
  try{
    var u=window.parent.location;
    window.parent.history.replaceState({}, '', u.pathname+u.search+'#ada='+encodeURIComponent(d));
  }catch(e){}
  try{ window.parent.localStorage.setItem(_SK, d); }catch(e){}
}
function clearState(){
  try{ window.parent.history.replaceState({}, '', window.parent.location.pathname); }catch(e){}
  try{ window.parent.localStorage.removeItem(_SK); }catch(e){}
}
function startFromLanding(){
  var ov=document.getElementById('landingOverlay');
  if(ov){ ov.style.display='none'; }
  resetAll();
}
function goToStart(){
  // HJ 2026-06-12 — '처음(시작화면)으로': 모든 단계에서 시작화면(랜딩)으로.
  //   부모 reload 만으로 충분 — Streamlit 은 페이지 reload 시 새 세션이라 session_state(studio_started) 가
  //   자동 초기화되고, clearState() 가 URL 을 pathname 으로(flow=1 제거) 바꾸므로 reload 후 랜딩이 뜬다.
  //   ※ 이전의 ?reset=1 + 서버 reset 처리(st.rerun) 는 reload 직후 'SessionInfo before initialized' 에러를 유발 → 제거.
  try{ if(pollTimer){ clearTimeout(pollTimer); pollTimer=null; } }catch(e){}
  try{ clearState(); }catch(e){}
  try{ window.parent.localStorage.removeItem(_SK); }catch(e){}
  try{ window.parent.history.replaceState({}, '', window.parent.location.pathname); }catch(e){}
  try{ window.parent.location.reload(); return; }catch(e){}
  try{ window.location.reload(); }catch(e){}
}
function resetAll(){
  clearState();
  jobId=null; fileId=null; cur=0; frontier=0; maxReached=0;
  paused=false; navUnlocked=false; follow=true; busy=false; polling=false;
  if(pollTimer){ clearTimeout(pollTimer); pollTimer=null; }
  status={}; gateData={}; selId=null; selectedFile=null;
  intentText=''; errMsg=''; analyzeStart=null; animatedGate=null;
  gateCache={}; lastSubmittedGate=null; selGate=null; g5Checked={};
  _progressKey=null; _shownPct=0; _sawAnalyzingAfterSubmit=false; _stageStart=null; _barFlowPct=0;
  render();
}
const AGENT_KO={supervisor:'작업 분류',intent_elicitor:'분석 의도 파악',data_profiler:'데이터 프로파일링',schema_validator:'스키마 검증',gate_direction:'분석 방향 제안 생성',eda_agent:'탐색적 분석(EDA)',gate_methodology:'방법론 제안',preprocessing_strategist:'전처리 전략',feature_engineer:'피처 엔지니어링',preprocessing_choice:'전처리 옵션 확정',gate_model_strategy:'모델 전략 제안',model_selection:'모델 선택',hyperparameter_tuner:'하이퍼파라미터 튜닝',training_executor:'모델 학습',training_monitor:'학습 모니터링',metrics_aggregator:'지표 집계',gate_best_model:'최적 모델 선정',fine_tune_executor:'파인튜닝 실행',eval_agent:'평가',explainability:'설명가능성',insight:'인사이트 생성',gate_outputs:'산출물 선택',report_composer:'리포트 생성',
  G2:'분석 방향 제안 완료',G3:'방법론 제안 완료',G4:'모델 전략 제안 완료',G5:'최적 모델 선정 완료',G6:'산출물 선택 완료',
  error_recovery:'오류 복구 중',self_learning_dispatch:'학습 결과 저장 중'};
// HJ 2026-06-10 — 마일스톤 진행률 sub-step (단계별 5~7개 descriptive 라벨).
// backend agent 가 1~2개뿐인 단계도 내부적으로 여러 sub-task 거치므로 그걸 시각화.
// active sub-step 은 backend progress_pct → STAGE_RANGE 매핑으로 결정 (current_agent 매칭 X).
//   화면 단계 1 (cur=0, G1): 5 단계 — 데이터 파악
//   화면 단계 2 (cur=1, G2): 6 단계 — EDA·방법론
//   화면 단계 3 (cur=2, G3): 6 단계 — 전처리·피처
//   화면 단계 4 (cur=3, G4): 7 단계 — 모델 학습
//   화면 단계 5 (cur=4, G5): 6 단계 — 평가·인사이트
//   화면 단계 6 (cur=5, G6): 5 단계 — 리포트 생성
const STAGE_AGENT_FLOW={
  // 각 단계의 "도착지" 항목 (분석 방향 제안 생성 / 방법론 카드 생성 등) 은 처리 시간 없는 endpoint 라 제외.
  // G1·G6 은 5개, 그 외는 5~6개.
  G1:[
    '작업 분류',
    '분석 의도 파악',
    '데이터 프로파일링',
    '스키마 검증',
    '도메인 분석'
  ],
  G2:[
    'EDA — 통계 산출',
    'EDA — 분포 분석',
    'EDA — 상관관계 분석',
    'EDA — 도메인 인사이트',
    '방법론 후보 평가'
  ],
  G3:[
    '전처리 전략 수립',
    '결측치·이상치 처리 방안',
    '피처 인코딩 후보 탐색',
    '피처 엔지니어링',
    '전처리 옵션 확정'
  ],
  G4:[
    '후보 모델 선정',
    '하이퍼파라미터 탐색 공간 정의',
    '하이퍼파라미터 튜닝',
    '모델 학습',
    '학습 모니터링',
    '지표 집계·검증'
  ],
  G5:[
    '파인튜닝 데이터 준비',
    '파인튜닝 실행',
    '모델 평가',
    '설명가능성 분석',
    '인사이트 생성'
  ],
  G6:[
    '결과 데이터 수집',
    '리포트 본문 합성',
    '시각화 자료 생성',
    '산출물 파일 생성',
    '학습 결과 저장'
  ]
};
function _curStageKey(){
  if(cur<0||cur>5) return null;
  return 'G'+(cur+1);  // cur=0→G1, cur=1→G2, ..., cur=5→G6
}
function _curAgentFlow(){
  const k=_curStageKey();
  return k?(STAGE_AGENT_FLOW[k]||[]):[];
}
// HJ 2026-06-10 — 단계별 추정 총 소요 시간 (초). backend progress_pct 가 publish 안 될 때 time-based fallback.
// 실측 데이터 부족하면 보수적 추정. backend 신호가 있으면 그 값이 우선 (둘 중 max 사용).
const STAGE_EST_SEC={G1:80,G2:75,G3:60,G4:240,G5:90,G6:30};
// 마일스톤 active 인덱스 — _shownPct (이미 backend + time-based 결합값) 기반 균등 분할.
// _shownPct 가 60% 이고 5 sub-steps 라면 idx=3 (4번째 sub-step active).
function _curMilestoneIdx(){
  const flow=_curAgentFlow();
  if(!flow.length) return -1;
  const pct=_shownPct||0;
  const idx=Math.floor(pct/100*flow.length);
  return Math.max(0, Math.min(flow.length-1, idx));
}
// modal-pending 의 "현재 작업: X" 라벨 — 현재 active sub-step 의 라벨.
function _curAgentLabel(){
  const flow=_curAgentFlow();
  const idx=_curMilestoneIdx();
  if(idx<0||idx>=flow.length) return '';
  return flow[idx];
}
// HJ 2026-06-10 — 단계별 동적 로딩 메시지 6개씩. 10초마다 순환. 각 단계의 실제 작업 내용을 반영.
const STAGE_LOAD_MSGS={
  0:[  // 1단계 (G1 — 데이터 파악)
    '데이터의 도메인을 파악하는 중입니다',
    '스키마와 데이터 품질을 검증하고 있습니다',
    'AI가 컬럼 의미를 해석하는 중입니다',
    '카테고리와 타겟을 자동 판정하는 중입니다',
    '분석 방향 카드를 생성하는 중입니다',
    '거의 다 왔습니다. 잠시만 기다려 주세요'
  ],
  1:[  // 2단계 (G2 — EDA·방법론)
    'EDA 통계와 분포를 분석하는 중입니다',
    '컬럼 간 상관관계를 살피고 있습니다',
    'AI가 적합한 방법론을 평가하는 중입니다',
    '카테고리별 방법론 후보를 비교 중입니다',
    '방법론 카드를 생성하는 중입니다',
    '거의 다 왔습니다. 잠시만 기다려 주세요'
  ],
  2:[  // 3단계 (G3 — 전처리·피처)
    '전처리 전략을 수립하는 중입니다',
    '피처 엔지니어링 후보를 탐색 중입니다',
    '결측치·이상치 처리 방안을 검토 중입니다',
    'AI가 최적 피처 조합을 평가하는 중입니다',
    '모델 전략 카드를 생성하는 중입니다',
    '거의 다 왔습니다. 잠시만 기다려 주세요'
  ],
  3:[  // 4단계 (G4 — 모델 학습)
    '후보 모델을 선정하는 중입니다',
    '하이퍼파라미터를 튜닝하는 중입니다',
    'AI가 모델을 학습시키는 중입니다',
    '학습 모니터링과 지표를 집계 중입니다',
    '최적 모델 카드를 생성하는 중입니다',
    '거의 다 왔습니다. 잠시만 기다려 주세요'
  ],
  4:[  // 5단계 (G5 — 평가·인사이트)
    '파인튜닝을 진행하는 중입니다',
    '모델 평가를 진행하는 중입니다',
    '설명가능성 분석을 진행 중입니다',
    'AI가 인사이트를 생성하는 중입니다',
    '산출물 카드를 생성하는 중입니다',
    '거의 다 왔습니다. 잠시만 기다려 주세요'
  ],
  5:[  // 6단계 (G6 — 리포트 생성)
    '리포트를 합성하는 중입니다',
    '시각화 자료를 생성하는 중입니다',
    'AI가 최종 결과를 정리하는 중입니다',
    '학습 데이터를 자동 업데이트 중입니다',
    '결과 페이지를 준비하는 중입니다',
    '거의 다 왔습니다. 잠시만 기다려 주세요'
  ]
};
let _loadMsgIdx=0;
setInterval(function(){ _loadMsgIdx=_loadMsgIdx+1; }, 10000);  // 누적값, 모듈러로 인덱싱
function loadMsg(){
  const msgs=STAGE_LOAD_MSGS[cur]||STAGE_LOAD_MSGS[0];
  return msgs[_loadMsgIdx%msgs.length];
}
// 모래시계 SVG (모던) — g 래퍼 + clip-path + CSS scaleY 애니메이션. SMIL 없이 순수 CSS.
// 그라데이션 fill (#fbbf24 → #f59e0b) + slate-700 프레임 + 둥근 stroke 으로 현대적 룩.
const HOURGLASS_HTML='<svg class="hg-svg" width="30" height="46" viewBox="0 0 32 48" xmlns="http://www.w3.org/2000/svg">'
  +'<defs>'
  +'<linearGradient id="hgSandGrad" x1="0" y1="0" x2="0" y2="1">'
  +'<stop offset="0%" stop-color="#fbbf24"/><stop offset="100%" stop-color="#f59e0b"/>'
  +'</linearGradient>'
  +'<clipPath id="hgClipT"><polygon points="5,4 27,4 16,22"/></clipPath>'
  +'<clipPath id="hgClipB"><polygon points="5,44 27,44 16,26"/></clipPath>'
  +'</defs>'
  +'<g class="hg-sand-top" clip-path="url(#hgClipT)">'
  +'<rect x="0" y="4" width="32" height="18" fill="url(#hgSandGrad)"/></g>'
  +'<g class="hg-sand-bot" clip-path="url(#hgClipB)">'
  +'<rect x="0" y="26" width="32" height="18" fill="url(#hgSandGrad)"/></g>'
  +'<line class="hg-stream" x1="16" y1="22" x2="16" y2="26" stroke="#f59e0b" stroke-width="1.6" stroke-linecap="round"/>'
  +'<g fill="none" stroke="#475569" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
  +'<polygon points="5,4 27,4 16,22"/><polygon points="5,44 27,44 16,26"/>'
  +'<line x1="3" y1="4" x2="29" y2="4"/><line x1="3" y1="44" x2="29" y2="44"/>'
  +'</g></svg>';

function esc(s){ return String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
// HJ 2026-06-10 — 모달 텍스트 타자기 효과. 사용자 요구: "한 글자 한 글자, 천천히 — 분석 시간은 충분".
// 사용법: twSpan(text, stableKey) 로 placeholder span 생성 → _twTick 이 글자 단위로 채움.
// stableKey 가 같으면 innerHTML 재설정되어도 진행 상태(_twState) 유지 → 스트리밍 데이터 추가에 안전.
function attrEsc(s){return String(s==null?'':s).replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}
function twSpan(text, key){
  if(text==null||text==='') return '';
  return '<span class="tw" data-tw="'+attrEsc(String(text))+'" data-twk="'+attrEsc(String(key))+'"></span>';
}
var _twState={};        // key -> {shown:N, target:'...'}
var _twTimer=null;
var _TW_STEP_MS=95;     // 글자당 ms. 약 10자/초 = 사람 타이핑 속도. 사용자 요구로 의도적으로 느리게.
var _twDotsShownAt=0;   // 점 3개(⋮) 등장 시각 — 등장 후 ~800ms 정지하여 사용자가 점을 인지하게 함.
var _TW_DOTS_PAUSE_MS=800;
// HJ 2026-06-10 — 순차(sequential) 진행. DOM 순서대로 한 요소가 끝나야 다음 요소가 시작.
// 추가: 카드 도형 자체도 행(row) 단위로 등장. 그 행 카드의 타이핑이 시작될 때 도형 reveal.
// 사용자 요구: "한 줄 한 줄 사람이 직접 쓰듯 — 위에서 아래로 순서대로. 도형도 미리 안 보이고 글자랑 같이 등장".
function _twTick(){
  var els=document.querySelectorAll('span.tw[data-tw]');
  // [1차 패스] 상태 동기화 + 섹션 진행 분석 (상단 완료 / 하단 시작 여부)
  var hasTop=false, hasBot=false, topComplete=true, anyBotStarted=false;
  for(var i=0;i<els.length;i++){
    var el=els[i];
    var key=el.getAttribute('data-twk');
    var full=el.getAttribute('data-tw')||'';
    var st=_twState[key];
    if(!st){ st={shown:0,target:full}; _twState[key]=st; }
    if(st.target!==full){ st.target=full; if(st.shown>full.length) st.shown=full.length; }
    var card=el.closest?el.closest('.cmcard'):null;
    if(card){
      var sec=card.getAttribute('data-cmsec')||'';
      if(sec==='top'){ hasTop=true; if(st.shown<full.length) topComplete=false; }
      if(sec==='bot'){ hasBot=true; if(st.shown>0) anyBotStarted=true; }
    }
  }
  // [점 3개 visibility] 상단 완료 시점에 등장 → ~800ms 정지 후 하단 시작
  var shouldShowDots=hasTop && hasBot && topComplete;
  var dotsEl=document.querySelector('.cmdots');
  if(dotsEl){
    if(shouldShowDots){
      if(dotsEl._cmVis!==true){ dotsEl._cmVis=true; dotsEl.style.opacity='1'; dotsEl.style.visibility='visible'; if(!_twDotsShownAt) _twDotsShownAt=Date.now(); }
    } else {
      if(dotsEl._cmVis!==false){ dotsEl._cmVis=false; dotsEl.style.opacity='0'; dotsEl.style.visibility='hidden'; }
    }
  }
  var pauseActive=(shouldShowDots && !anyBotStarted && _twDotsShownAt>0 && (Date.now()-_twDotsShownAt)<_TW_DOTS_PAUSE_MS);
  // [2차 패스] 첫 미완료 요소 1글자 전진 + DOM 동기화 + 카드 행 visibility
  var advanced=false, maxStartedRow=-1;
  for(var j=0;j<els.length;j++){
    var el2=els[j];
    var key2=el2.getAttribute('data-twk');
    var full2=el2.getAttribute('data-tw')||'';
    var st2=_twState[key2];
    var card2=el2.closest?el2.closest('.cmcard'):null;
    var sec2='', row2=-1;
    if(card2){ sec2=card2.getAttribute('data-cmsec')||''; row2=parseInt(card2.getAttribute('data-cmrow')||'-1',10); }
    // 정지 중에는 하단 첫 카드 시작 차단 (상단 완료 후 ~800ms 점 노출)
    if(!advanced && st2.shown<full2.length){
      if(pauseActive && sec2==='bot' && st2.shown===0){
        /* skip — 정지 */
      } else {
        st2.shown++;
        advanced=true;
      }
    }
    if(card2 && row2>=0 && st2.shown>0 && row2>maxStartedRow) maxStartedRow=row2;
    var sig;
    if(st2.shown===0){
      sig='e';
      if(el2._twLast!==sig){ el2._twLast=sig; el2.innerHTML=''; }
    } else if(st2.shown<full2.length){
      sig='p:'+st2.shown+':'+full2.length;
      if(el2._twLast!==sig){ el2._twLast=sig; el2.innerHTML=esc(full2.slice(0,st2.shown))+'<span class="tw-caret"></span>'; }
    } else {
      sig='d:'+full2;
      if(el2._twLast!==sig){ el2._twLast=sig; el2.innerHTML=esc(full2); }
    }
  }
  // [카드 visibility] 행 인덱스 <= maxStartedRow 인 카드만 노출.
  // 하단 시작 시 상단은 모두 보이도록 보정 (anyBotStarted → 상단 카드도 강제 visible).
  var cards=document.querySelectorAll('.cmcard');
  for(var k=0;k<cards.length;k++){
    var c=cards[k];
    var r=parseInt(c.getAttribute('data-cmrow')||'-1',10);
    var s=c.getAttribute('data-cmsec')||'';
    var show=(r>=0 && r<=maxStartedRow) || (s==='top' && anyBotStarted);
    if(show){
      if(c._cmVis!==true){ c._cmVis=true; c.style.opacity='1'; c.style.visibility='visible'; }
    } else {
      if(c._cmVis!==false){ c._cmVis=false; c.style.opacity='0'; c.style.visibility='hidden'; }
    }
  }
  // [twrow visibility] 2~6단계 모달의 label row 등 — 내부 twSpan 의 shown>0 이면 행 reveal.
  // 사용자 요구: "2단계도 1단계 방식과 같이" — 행 단위로 등장.
  var twrows=document.querySelectorAll('.twrow');
  for(var t=0;t<twrows.length;t++){
    var rw=twrows[t];
    var rspans=rw.querySelectorAll('span.tw[data-tw]');
    var anyStarted=false;
    for(var u=0;u<rspans.length;u++){
      var rk=rspans[u].getAttribute('data-twk');
      var rst=_twState[rk];
      if(rst && rst.shown>0){ anyStarted=true; break; }
    }
    if(anyStarted){
      if(rw._twrVis!==true){ rw._twrVis=true; rw.style.opacity='1'; rw.style.visibility='visible'; }
    } else {
      if(rw._twrVis!==false){ rw._twrVis=false; rw.style.opacity='0'; rw.style.visibility='hidden'; }
    }
  }
  // HJ 2026-06-12 — 타자기가 한 글자라도 전진하면 분석 박스를 바닥으로 추적 → '현재 작성 중인 줄'이 항상 보이게.
  if(advanced) _modalScrollFollow();
}
// HJ 2026-06-12 — 실시간 분석 박스(#modal-scroll)가 '지금 써지고 있는 줄'을 따라가게 함.
//   ⚠️ 바닥(scrollHeight)으로 스크롤하면 안 됨: G1 컬럼 카드는 visibility:hidden 으로 '공간만 차지'하는
//   미작성 카드가 하단에 깔려 있어, 바닥으로 가면 빈 칸만 보이고 정작 현재 작성 줄이 화면 밖으로 밀린다.
//   → 현재 타이핑 위치(캐럿 .tw-caret)가 들어있는 카드/행을 #modal-scroll 안에서 보이도록 스크롤한다.
//   block:'nearest' → 이미 보이면 움직이지 않음(불필요한 점프·떨림 방지), 가려졌을 때만 최소로 따라감.
function _modalScrollFollow(){
  var sc=document.getElementById('modal-scroll');
  if(!sc) return;
  var caret=sc.querySelector('.tw-caret');
  if(caret && caret.scrollIntoView){
    try{ caret.scrollIntoView({block:'nearest', inline:'nearest'}); return; }catch(_e){}
  }
  // 캐럿이 없으면(타이핑 막 시작 전 등) 바닥 추적으로 폴백.
  sc.scrollTop=sc.scrollHeight;
}
function _twStart(){ if(_twTimer) return; _twTimer=setInterval(_twTick,_TW_STEP_MS); }
// HJ 2026-06-10 — 모달 내 모든 타자기 요소가 완료됐는지 확인. 분석 완료여도 타이핑 끝나기 전엔 다음 단계로 못 넘어가도록.
// HJ 2026-06-11 버그픽스: document 전체 querySelectorAll 사용 시 body(컬럼의미, 도메인카드 등)의 span 이 포함돼
//   body span 이 계속 새로 생성될 때 _twAllDone()=false 고착 → _twAllDoneAt 영구 리셋 → _typingHoldComplete()=false
//   → 모달 영구 stuck. #modal-insight 범위로만 제한.
function _twAllDone(){
  var _mi=document.getElementById('modal-insight');
  var els=_mi?_mi.querySelectorAll('span.tw[data-tw]'):[];
  if(!els.length) return false;  // 아직 요소 자체가 안 만들어짐(데이터 미도착) → 미완료로 간주
  for(var i=0;i<els.length;i++){
    var key=els[i].getAttribute('data-twk');
    var full=els[i].getAttribute('data-tw')||'';
    var st=_twState[key];
    if(!st || st.shown<full.length) return false;
  }
  // 9+ 컬럼 케이스: 점 3개 정지(_TW_DOTS_PAUSE_MS) 도 지나야 완료로 인정
  var dotsEl=document.querySelector('.cmdots');
  if(dotsEl && _twDotsShownAt>0 && (Date.now()-_twDotsShownAt)<_TW_DOTS_PAUSE_MS) return false;
  return true;
}
// 숫자 표시 헬퍼 — 부동소수점은 소수점 3자리, 정수는 그대로, 문자열은 원본
function fmtNum(v){
  if(v==null) return '';
  const n=Number(v);
  if(!Number.isFinite(n)) return String(v);
  if(Number.isInteger(n)) return String(n);
  return n.toFixed(3);
}
function fmtTime(s){ s=Math.max(0,Math.round(s)); const m=Math.floor(s/60), ss=s%60; return m+':'+(ss<10?'0':'')+ss; }
function curGate(){ const g=(gateData.gate)||(status.current_gate); return (g && /^G[2-6]$/.test(g))?g:null; }
function hasResults(){ return !!((gateData.output_paths && Object.keys(gateData.output_paths).length) || gateData.insights || gateData.eval_result || gateData.best_model); }
function isFailed(){ return (gateData.pipeline_status==='failed') || (status.status==='failed'); }
function isCompleted(){
  // 백엔드 status 를 우선 — 세 번째 fallback 조건은 G6 이후 최종 결과가 모두 갖춰진 경우만 허용.
  // (jobId && !curGate() && hasResults()) 만으로는 분석 중간에도 true 가 되어
  // clearState() 가 호출되므로, 반드시 pipeline_status 확인을 추가한다.
  if(['completed','succeeded','success'].includes(status.status)) return true;
  if(gateData.pipeline_status==='completed') return true;
  return false;
}
function analyzing(){ return !!(jobId && !curGate() && !isCompleted() && !isFailed()); }
// 시프트 후 (2026-06-04) 매핑:
//   백엔드 gate_code 'G2' (분석 방향) → 화면 cur=1  ←→  화면 G2 라벨
//   백엔드 gate_code 'G3' (방법론)    → 화면 cur=2  ←→  화면 G3 라벨
//   ...
//   백엔드 gate_code 'G6' (산출물)    → 화면 cur=5  ←→  화면 G6 라벨
// 즉 frontier = parseInt(gate_code[1]) - 1.
function computeFrontier(){
  if(isCompleted()){ frontier=LAST; return; }
  const g=curGate();
  // 게이트 없음(분석 중): frontier=0 으로 리셋하면 follow=true 상태에서 cur 도 0 으로
  // snap-back 되어 업로드 화면이 잠깐 보이다 다음 게이트로 점프하는 현상 발생.
  // maxReached 를 사용해 이전 최고 단계를 유지.
  frontier = g ? (+g[1] - 1) : (jobId ? maxReached : 0);
}
async function api(path, opts){
  const r=await fetch(API+path, opts||{});
  const txt=await r.text();
  if(!r.ok) throw new Error('HTTP '+r.status+' '+txt.slice(0,180));
  return txt ? JSON.parse(txt) : {};
}
// HJ 2026-06-09 G1 단축 Phase 4 — client-side 파일 헤더+sample 파싱 + prefetch.
// 파일 선택 시 즉시 실행 (fire-and-forget). 실패해도 정식 업로드는 정상 동작.
async function startPrefetch(file){
  if(!file) return;
  prefetchSig=null; prefetchResult=null; prefetchPreview=null;
  try{
    const ext=(file.name.split('.').pop()||'').toLowerCase();
    let columns=[], sample=[], dtypes={};
    if(ext==='csv'||ext==='tsv'){
      // PapaParse: 첫 100행만 파싱 (Worker 모드 비활성, sync 짧음)
      const buf=await file.slice(0, 1024*256).arrayBuffer();
      let text=new TextDecoder('utf-8',{fatal:false}).decode(buf);
      if(text.includes('�')){try{text=new TextDecoder('euc-kr',{fatal:false}).decode(buf);}catch(e){}}
      // 256KB 만 (헤더+sample 충분)
      const parsed=Papa.parse(text, {header:true, skipEmptyLines:true, preview:100});
      if(parsed.errors && parsed.errors.length) console.warn('PapaParse warn', parsed.errors);
      const rows=parsed.data||[];
      if(rows.length){
        columns=Object.keys(rows[0]);
        sample=rows.slice(0, 3);
        // dtype 추정: 첫 5행 기준
        columns.forEach(function(c){
          const vals=rows.slice(0,5).map(function(r){return r[c];}).filter(function(v){return v!=null && v!=='';});
          if(!vals.length){ dtypes[c]='object'; return; }
          const allNum=vals.every(function(v){return !isNaN(Number(v));});
          dtypes[c]=allNum?'float64':'object';
        });
      }
    } else if(ext==='xlsx'||ext==='xls'){
      const buf=await file.slice(0, 1024*512).arrayBuffer();  // 512KB
      const wb=XLSX.read(buf, {type:'array', sheetRows:100});
      const sn=wb.SheetNames[0];
      const ws=wb.Sheets[sn];
      const rows=XLSX.utils.sheet_to_json(ws, {defval:null});
      if(rows.length){
        columns=Object.keys(rows[0]);
        sample=rows.slice(0, 3);
        columns.forEach(function(c){
          const vals=rows.slice(0,5).map(function(r){return r[c];}).filter(function(v){return v!=null && v!=='';});
          dtypes[c]=vals.length && vals.every(function(v){return typeof v==='number';})?'float64':'object';
        });
      }
    } else if(ext==='json'){
      const _jbuf=await file.slice(0, 1024*256).arrayBuffer();
      let text=new TextDecoder('utf-8',{fatal:false}).decode(_jbuf);
      if(text.includes('�')){try{text=new TextDecoder('euc-kr',{fatal:false}).decode(_jbuf);}catch(e){}}
      try{
        const obj=JSON.parse(text);
        const rows=Array.isArray(obj)?obj:(Array.isArray(obj.data)?obj.data:[]);
        if(rows.length && typeof rows[0]==='object'){
          columns=Object.keys(rows[0]);
          sample=rows.slice(0, 3);
        }
      }catch(e){ /* JSON parse fail — prefetch 스킵 */ }
    }
    if(!columns.length) return;  // 파싱 실패 → prefetch 스킵
    // 미리보기 표시용 — UI 즉시 갱신
    prefetchPreview={cols:columns.length, sample_rows:sample.length, columns:columns.slice(0,8)};
    render();
    // signature = sha256(sorted_columns) — 백엔드도 동일 계산
    const sortedCols=columns.slice().sort();
    const sig=await sha256(JSON.stringify(sortedCols));
    prefetchSig=sig.slice(0,32);
    // 백엔드 prefetch 호출 (fire-and-forget)
    let resp;
    try{
      resp=await api('/upload/prefetch',{
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({columns:columns, dtypes:dtypes, sample:sample, signature:prefetchSig, user_intent:intentText||null})
      });
    }catch(e){ console.warn('prefetch failed:', e.message); return; }
    if(resp && resp.cached && resp.category){
      // 즉시 hit — 캐시 결과 적용
      prefetchResult=resp; render();
    } else {
      // 비동기 polling 시작 (LLM 완료 ~15s 후)
      pollPrefetch(prefetchSig);
    }
  }catch(e){
    console.warn('startPrefetch error:', e.message);
  }
}

async function pollPrefetch(sig){
  if(prefetchPolling) return;
  prefetchPolling=true;
  const maxTries=20;  // 2.5s × 20 = 50s
  for(let i=0; i<maxTries; i++){
    if(!selectedFile || prefetchSig!==sig){ break; }  // 파일 변경 시 중단
    try{
      const resp=await api('/upload/prefetch/'+sig);
      if(resp && resp.ready){
        prefetchResult=resp; render(); break;
      }
    }catch(e){ /* polling 실패는 silent */ }
    await new Promise(function(r){ setTimeout(r, 2500); });
  }
  prefetchPolling=false;
}

async function sha256(str){
  const buf=new TextEncoder().encode(str);
  const hash=await crypto.subtle.digest('SHA-256', buf);
  return Array.from(new Uint8Array(hash)).map(function(b){return b.toString(16).padStart(2,'0');}).join('');
}

async function doUpload(){
  if(!selectedFile){ errMsg='먼저 파일을 선택하세요.'; render(); return; }
  errMsg=''; busy=true; render();
  try{
    const fd=new FormData(); fd.append('file', selectedFile);
    const up=await api('/upload',{method:'POST',body:fd});
    fileId=up.file_id;
    const stt=await api('/pipeline/start',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({file_id:fileId,user_intent:intentText||null,requested_outputs:[]})});
    // Phase 1 — G1 데이터 파악 단계 유지. cur=0 으로 두고 follow=false 로 자동 전환 방지.
    // G2 proposals 도착 시점에 poll() 안에서 명시적으로 cur=1 전환 + follow=true 부여.
    // HJ 2026-06-09 G1 단축 fix — busy=false 직후 render() 로 G1 진행 화면 즉시 표시.
    // render() 없으면 첫 poll() 완료(~2.5s)까지 업로드 화면이 그대로 남는다.
    jobId=stt.job_id; follow=false; cur=0; frontier=0; maxReached=0; busy=false;
    gateData={}; analyzeStart=Date.now();
    render();
    saveState();
    startPolling();
  }catch(e){ errMsg='업로드/시작 실패 — '+e.message; busy=false; render(); }
}
async function doResume(){
  const tg='G'+(cur+1);  // cur(화면 인덱스) → 백엔드 게이트 코드. cur=1(분석방향)=G2 ... cur=5(산출물)=G6
  // CS 2026-06-10 — G2 가드: 사용자가 endpoint(주제 선택) 거치지 않고 resume 시도하면 차단
  if(tg==='G2' && !g2DirectionsReady){
    errMsg='주제를 먼저 선택하고 "선택 완료 ▶" 를 눌러주세요.';
    render(); return;
  }
  const ag=curGate();
  // cur 기준으로 올바른 proposals 선택 (이전 단계 재진행 시 캐시 사용)
  const d=(ag===tg)?gateData:(gateCache[tg]||{});
  const props=(d.proposals)||[];
  let choice;
  if(tg==='G6'){
    const outs=[];
    props.forEach(function(p){ if(g5Checked[p.id]&&p.outputs){ p.outputs.forEach(function(o){outs.push(o);}); } });
    if(!outs.length){ errMsg='최소 1개 이상 산출물을 선택하세요.'; render(); return; }
    choice={outputs:outs};
  } else if(selId==='custom'){
    if(!customText.trim()){ errMsg='옵션: 분석 방향을 입력해 주세요.'; render(); return; }
    choice={adopted_rank:0, custom_intent:customText};
  } else if(selId!=null){ choice={adopted_rank:selId}; }
  else { choice={adopted_rank:(props[0]&&props[0].id)||1}; }
  // CS 2026-06-10 — G2 일 때 선택된 주제도 choice 에 포함
  if(tg==='G2' && window._g2_selectedTopicText){ choice.topic=window._g2_selectedTopicText; }
  const gate=tg;  // curGate() 대신 cur 기준 게이트 코드 사용
  errMsg=''; busy=true; navUnlocked=false; render();  // 재진행 확정 → 정지 해제(정상 진행 복귀)
  try{
    await api('/pipeline/resume/'+jobId,{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({gate:gate,choice:choice})});
    lastSubmittedGate=gate;
    // 제출 게이트 이후 캐시 삭제 — 현재 게이트(tg) 캐시는 유지(뒤로가기 복원용)
    var _tgNum=parseInt(tg[1],10);
    Object.keys(gateCache).forEach(function(k){
      if(parseInt(k.slice(1),10)>_tgNum) delete gateCache[k];
    });
    // HJ 2026-06-11 — 재진행 확정 순간에만 하위 단계 진행 결과 폐기 (frontier·maxReached 를 현재 단계로).
    //   이전 단계 이동(prevBtn)만으로는 보존되고, 재진행을 눌러야 비로소 앞 단계가 무효화된다.
    //   (정상 진행 case 는 cur===frontier===maxReached 라 no-op.) 이후 재실행으로 자연스럽게 재구축.
    maxReached=cur; frontier=cur;
    // HJ 2026-06-10 — cur 그대로 유지. 각 단계 N 화면에서 진행 누르면 그 자리에서 G(N+1) 분석 모달이 뜨고,
    // 다음 gate 의 proposals 가 도착하면 frontier 추적으로 자연스럽게 cur=N+1 로 advance.
    // (이전엔 cur=cur+1 즉시 점프 → "단계 2 분석"이 단계 3 화면에서 표시되는 오프셋 발생)
    follow=true; busy=false; gateData={}; analyzeStart=Date.now();
    _progressKey=null; _shownPct=0; _sawAnalyzingAfterSubmit=false; _stageStart=null; _barFlowPct=0;  // gate 제출 직후 리셋
    saveState();
    startPolling();
  }catch(e){ errMsg='전송 실패 — '+e.message; busy=false; render(); }
}
async function poll(){
  if(!jobId) return;
  try{ status=await api('/pipeline/status/'+jobId,{}); }catch(e){ status={_err:e.message}; }
  try{ gateData=await api('/pipeline/gate/'+jobId,{}); }catch(e){ gateData={proposals:[], _err:e.message}; }
  // proposals 가 있는 게이트 응답은 캐시 — 이전 단계 뒤로가기 시 재사용
  if(gateData.gate && (gateData.proposals||[]).filter(function(p){return !p.is_custom;}).length){
    gateCache[gateData.gate]=gateData;
  }
  // HTTP 4xx → 세션 만료(서버 재시작·DB 초기화): localStorage 정리 후 업로드 화면으로
  if(status._err && /HTTP 4[0-9][0-9]/.test(status._err)){
    clearState();
    jobId=null; cur=0; frontier=0; maxReached=0; polling=false;
    errMsg='이전 분석 세션이 만료됐습니다. 새 파일을 업로드해 주세요.';
    render(); return;
  }
  // job이 failed 상태이고 업로드 화면(cur=0)에 머물고 있으면 자동 초기화.
  // 사용자가 F12 → localStorage 직접 지울 필요 없이 다음 폴링 시 자동 리셋.
  if(isFailed() && cur===0){
    clearState();
    jobId=null; cur=0; frontier=0; maxReached=0; polling=false;
    errMsg='이전 분석이 실패했습니다. 새 파일을 업로드해 주세요.';
    render(); return;
  }
  computeFrontier();
  // HJ 2026-06-10 — 백엔드가 일시적으로 stale gate (예: 4단계 진행 중 G2 로 publish) 를 반환해도
  // 사용자 진행 상태를 절대 regress 시키지 않도록 보호. maxReached 는 위로만 갱신.
  maxReached=Math.max(maxReached,frontier,cur);
  if(cur===0 && jobId && !_suppressG1Advance && curGate()==='G2'){
    const _g1Done=(gateData.proposals||[]).filter(function(p){return !p.is_custom;}).length;
    // CS 2026-06-10 — Sub-1 흐름: topic_proposals 도착도 G1 종료 신호로 인정
    const _topicReady=(gateData.topic_proposals||[]).length;
    // HJ 2026-06-10 — proposals 도착해도 모달 타자기 끝까지 안 적혔으면 자동 cur 전환 차단.
    // HJ 2026-06-11 — 타자기 완료 후 3초 추가 hold (사용자 읽을 시간) — _typingHoldComplete() 로 통합.
    if((_g1Done || _topicReady) && _typingHoldComplete()){ cur=1; follow=true; }
  }
  // follow=true 여도 cur 는 절대 자동 regress 안 함. 사용자 prev 버튼 클릭 으로만 내려갈 수 있음.
  // HJ 2026-06-11 — 모달 표시 중에는 cur 자동 전진 차단. frontier 가 올라가도 inModalLoading()=false 될 때까지 고정.
  //   (구 코드: cur=3 으로 올리면 inModalLoading(cur=3) 이 submittedHere=false 반환 → 모달 즉시 소멸 버그)
  if(follow && !inModalLoading()) cur=Math.max(cur, frontier);
  // cur 상한 = max(maxReached, frontier) — backend stale 일 때도 사용자 진행 단계 유지.
  cur=Math.max(0,Math.min(cur,Math.max(maxReached,frontier)));
  if(analyzing()){ if(analyzeStart==null) analyzeStart=Date.now(); } else { analyzeStart=null; }
  saveState();
  render();
  // resume 직후 Celery가 아직 task를 못 받아 Redis에 이전 게이트가 남아있을 수 있음 →
  // lastSubmittedGate 와 현재 게이트가 같으면 계속 폴링.
  // 분석 중(curGate=null)에는 유지 — 새 게이트 등장 시에만 클리어.
  // 실패·완료 시 stale 가드 즉시 해제 — 이전 단계 캐시 proposals 복원 가능하게
  // HJ 2026-06-12 — G6 타이핑 hold 중에는 lastSubmittedGate 유지 (모달 활성 조건 보존).
  if(isFailed()||(isCompleted()&&!_g6TypingHold())){ lastSubmittedGate=null; _sawAnalyzingAfterSubmit=false; }
  // resume 후 analyzing() 통과 확인 — staleRun(renderBody 의 이전 gate_data 무시) 보호용.
  if(lastSubmittedGate && analyzing()) _sawAnalyzingAfterSubmit=true;
  // HJ 2026-06-11 버그픽스: 진행 완료(다음 단계 전진) 판정을 '게이트 번호 비교 + 모달 hold 완료' 로.
  //   • _nextGateArrived(): 제출게이트보다 높은 번호(G3→G4)만 인정 → backend stale 이전 게이트(G2)에 안 속음.
  //     (구 `curGate()!==lastSubmittedGate` 는 stale G2 에 속아 모달이 분석 도중 사라지고 선택화면으로 빠짐)
  //   • _typingHoldComplete(): 모달의 실시간 분석 내용을 끝까지 작성 + 3초 hold 후에만 전진 (사용자 요구).
  //     hold 미완료면 lastSubmittedGate 유지 → inModalLoading()=true → 모달이 계속 내용 작성.
  if(_nextGateArrived() && _typingHoldComplete()){
    lastSubmittedGate=null;
    follow=true;  // 진행 완료 → 새 게이트로 자동 전진 복구
  }
  // G1→G2 자동 전환 대기 중에는 polling 을 유지해야 한다.
  // 백엔드가 G2 게이트 도달 시점에 analyzing()=false 가 되어 기존 조건만으론 폴링이 멈추고,
  // 그 결과 _shownPct 가 99 에 도달해도 cur 전환을 못 한 채 화면이 stuck 된다(2026-06-04 발견).
  const g0Pending = (cur===0 && jobId && _shownPct < 100);
  // 게이트 코드는 잡혔는데 proposals 이 아직 비어있는 상태 — analyzing()=false 이지만 폴링 유지 필요
  // (예: G6 gate 도달 후 eval/insight 완료 전에 gate_data 가 먼저 저장된 경우)
  const gateWaitProposals = !!curGate() && !(gateData.proposals||[]).filter(function(p){return !p.is_custom;}).length;
  const keepPolling=(analyzing() || !!lastSubmittedGate || g0Pending || gateWaitProposals) && !paused;
  if(keepPolling){ pollTimer=setTimeout(poll, 2500); }
  else { polling=false; }
}
function startPolling(){ if(polling){ render(); return; } polling=true; clearTimeout(pollTimer); poll(); }

// 0.5초 틱 — 진행률 보간용 render 트리거 (현재 agent 변경에 따라 마일스톤 갱신).
// HJ 2026-06-10 — Z' 단축 제거 + cur=0→1 안전망. polling 일시 멈춤 사이에 proposals 도착 시
// poll() 다음 cycle 까지 기다리지 않고 즉시 화면 전환.
setInterval(function(){
  if(paused) return;
  if(cur===0 && jobId && !_suppressG1Advance && curGate()==='G2'){
    const _p=(gateData.proposals||[]).filter(function(p){return !p.is_custom;}).length;
    // HJ 2026-06-10 — proposals 도착해도 모달 타자기 끝까지 안 적혔으면 자동 cur 전환 차단.
    // HJ 2026-06-11 — 타자기 완료 후 3초 추가 hold — _typingHoldComplete() 로 통합.
    if(_p && _typingHoldComplete()){
      cur=1; follow=true;
      saveState();
      render();
      if(!polling) startPolling();
      return;
    }
  }
  if(!jobId && cur===0) return;  // 업로드 대기 화면 — textarea 포커스 보호
  // HJ 2026-06-11 — g2DirectionsBusy 동안에도 render → "분석 방향 생성 중 (N초)" 라벨 1초 단위 갱신.
  if(analyzing() || _shownPct < 100 || (cur===0 && jobId) || g2DirectionsBusy) render();
}, 500);

// A 트랙(2026-06-04): 백엔드 BaseAgent 가 매초 phase 단위 진행률을 publish 하므로
// 클라이언트 하드코딩(STAGE_AVG_SEC) 추정은 폐기. 백엔드 progress_pct 가 진실의 소스다.
// 클라이언트는 그 값을 충실히 따라가되 (a) 단계 전환 시 0 리셋, (b) 큰 점프(예: 30→100)만
// 부드럽게 보간(2초 안에 따라잡기), (c) 진행률이 거꾸로 가지 않도록 last-shown 유지.
//
// 단계의 의미:
//   - cur=0 (업로드)  : jobId 없으면 0, 업로드 시작 후 백엔드 진행률 따름
//   - cur=1~5 (게이트): proposals 도착 = 분석 끝 → 100% (단계 종료 신호)
//   - cur=6 (완료)   : 항상 100%
let _shownPct=0;
let _progressKey=null;
let _stageStart=null;
let _barFlowPct=0;
let _lastSignalAt=null;      // 마지막 백엔드 신호 수신 시각(ms)
let _lastSignalPct=null;     // 마지막으로 수신한 단계 내 진행률
let _estimatedTotal=null;    // 예상 총 소요 시간(초) — eta_sec 전용, pct 역산 금지
let _completing=false;       // 완료 신호 수신 → 100% 애니메이션 중
let _estimatedFromEta=false; // eta_sec 로 _estimatedTotal 설정됐으면 true (pct override 방지)

function _stageProgress(){
  // HJ 2026-06-12 — G6 타이핑 hold 중에는 진행키를 'G6' 로 유지 (DONE 전환 시 _shownPct 0 리셋 방지).
  const key=(isFailed()?'FAIL':_g6TypingHold()?'G6':(isCompleted()||cur===LAST)?'DONE':'G'+(cur+1));
  if(_progressKey!==key){
    _progressKey=key;
    _shownPct=0; _stageStart=Date.now(); _barFlowPct=0;
    _lastSignalAt=null; _lastSignalPct=null;
    _estimatedTotal=null; _completing=false; _estimatedFromEta=false;
  }
  if(isFailed()){ _barFlowPct=0; return 0; }
  // HJ 2026-06-12 — G6 타이핑 hold 중에는 100% 점프 금지 (아래 일반 경로에서 95% 고정 유지).
  if((isCompleted()||cur===LAST)&&!_g6TypingHold()){ _shownPct=100; _barFlowPct=100; return 100; }
  if(cur===0&&!jobId){ _shownPct=0; _stageStart=null; _barFlowPct=0; return 0; }
  // jobId 도착(G1 분석 시작) 시 stageStart 기산점 — 항상 클라이언트 Date.now() 사용
  // (eta_base_ts 는 서버 시간 → 시계 차이로 elapsed 왜곡 발생 → 사용 금지)
  if(_stageStart==null&&cur===0&&jobId){ _stageStart=Date.now(); }

  // 완료 신호 감지 (즉시 100% 아님 — 아래 애니메이션 블록에서 부드럽게 처리)
  if(!_completing){
    if(cur===0){
      const g1Reached=curGate()==='G2'&&(gateData.proposals||[]).filter(function(p){return !p.is_custom;}).length;
      if(g1Reached) _completing=true;
    } else {
      const tg='G'+(cur+1); const ag=curGate();
      const _staleRun=!!(lastSubmittedGate&&!_sawAnalyzingAfterSubmit);
      const d=_staleRun?{}:((ag===tg)?gateData:(analyzing()?{}:(gateCache[tg]||{})));
      const ps=((d.proposals)||[]).filter(function(p){return !p.is_custom;});
      if(ps.length&&!(lastSubmittedGate===tg&&!ag)) _completing=true;
    }
  }
  if(_completing){
    // 팝업 로딩 중(proposals 미도착) → 95% 억제. proposals 도착 시 modal 닫히고 그 때 100%.
    // 완료 = 2단계로 실제 전환되는 시점. modal 닫힌 후에만 100%/'완료' 표시.
    // HJ 2026-06-12 — 모달 로딩 캡 99→95. 마지막 마일스톤이 active(진행중) 로 보이도록 일관화.
    const _cap=inModalLoading()?95:100;
    _shownPct=Math.min(_cap,_shownPct+10);
    _barFlowPct=_shownPct;
    return Math.round(_shownPct);
  }

  // HJ 2026-06-10 — backend progress_pct 와 time-based baseline 중 max.
  // backend 가 G2~G6 처럼 agent 수 적은 단계에서 publish 가 띄엄띄엄해도 시간 기반 fallback 이 진행을 보장.
  // 95% 캡 (마지막 5% 는 _completing 신호로 채워짐).
  let target=0;
  if(_stageStart!=null){
    const elSec=(Date.now()-_stageStart)/1000;
    const stageKey=_curStageKey();
    const totalSec=(STAGE_EST_SEC[stageKey]||60);
    target=Math.min(95, elSec/totalSec*100);
  }
  const rawP=gateData.progress_pct;
  if(rawP!=null && Number.isFinite(Number(rawP))){
    const rng=STAGE_RANGE[cur];
    if(rng){
      const stageProgress=(Number(rawP)-rng[0])/(rng[1]-rng[0]);
      if(stageProgress>0){
        target=Math.max(target, Math.min(95, stageProgress*100));
      }
    }
  }
  if(target>_shownPct) _shownPct=target;
  _barFlowPct=Math.max(_barFlowPct,_shownPct);
  _shownPct=_barFlowPct;
  return Math.round(_shownPct);
}

// ETA — 실측 elapsed/pct 비율로 역산 (적응형). 백엔드 estimate 의존 없음.
// rate(%/s) = 현재 pct / 경과 시간 → 남은 시간 = (100 - pct) / rate.
// 너무 이른 시점(elapsed<5s 이거나 pct<5)에서는 rate 가 불안정해 null 반환.
function _stageEta(p){
  if(_stageStart==null||p<5) return null;
  const elSec=(Date.now()-_stageStart)/1000;
  if(elSec<5) return null;
  const rate=p/elSec;
  if(rate<=0) return null;
  return Math.max(0,(100-p)/rate);
}

function failureBlock(){
  const msg=gateData.insights||gateData.pipeline_error||status.error||'알 수 없는 오류';
  return '<div class="loadwrap"><div class="loadtxt">⛔ 분석이 실패했습니다.</div>'
    +'<div class="diag">'+esc(msg)+'<br><br>'
    +'① 워커 로그 확인: <code>docker logs --tail 200 ada-worker-pipeline</code><br>'
    +'② 워커 재기동 후 새 파일로 재시도하세요.'
    +'</div></div>';
}
function loadingBlock(){
  // 본 진행바·메타는 progressBar() 가 카드 하단에 일괄 표시 → 여기는 분석 중 텍스트와
  // 현재 agent 라벨만 출력. 백엔드 무신호 5분 이상이면 진단 안내 추가.
  if(isFailed()) return failureBlock();
  const el=analyzeStart?((Date.now()-analyzeStart)/1000):0;
  const realP=(gateData.progress_pct!=null)?gateData.progress_pct:null;
  let agentLine='';
  // stale 구간(resume 직후 analyzing 미확인) + 이전 stage agent 가 남아있는 경우 모두 숨김.
  const _agLab=_curAgentLabel();
  if(_agLab && !(lastSubmittedGate&&!_sawAnalyzingAfterSubmit)){
    agentLine='<div class="lagent">현재 작업: <b>'+esc(_agLab)+'</b></div>';
  }
  let diag='';
  if(realP==null && el>300){
    diag='<div class="diag">⚠ 백엔드에서 진행 신호가 <b>'+fmtTime(el)+'</b> 동안 없습니다. 워커가 실제로 분석 중이 아닐 가능성이 큽니다.<br>'
      +'① 워커 실행: <code>docker ps | grep worker</code> &nbsp; ② 로그: <code>docker logs --tail 120 ada-worker-pipeline</code><br>'
      +'③ <code>ANTHROPIC_API_KEY</code> 설정 여부 &nbsp; ④ 백엔드(api·worker) 파일 복사 후 <b>재기동</b> 했는지'
      +(gateData._err?('<br><b>/gate 오류:</b> '+esc(gateData._err)+' → api 미배포/미기동 의심'):'')
      +(gateData._state_error?('<br><b>state 오류:</b> '+esc(gateData._state_error)):'')
      +'</div>';
  }
  return '<div class="loadwrap"><div class="loadtxt">'+HOURGLASS_HTML+'<span id="lmsg"></span></div><div class="lagent" id="lagent"></div>'+diag+'</div>';
}
// 현재 게이트 화면이 로딩 중인지 여부 (proposals 없는 상태)
function isGateLoading(){
  if(cur<1 || cur>5) return false;
  const tg='G'+(cur+1);
  const ag=curGate();
  if(lastSubmittedGate===tg && !ag) return true;
  const _staleRun=!!(lastSubmittedGate&&!_sawAnalyzingAfterSubmit);
  const d=_staleRun?{}:((ag===tg)?gateData:(analyzing()?{}:(gateCache[tg]||{})));
  const llmProps=(d.proposals||[]).filter(function(p){return !p.is_custom;});
  return !llmProps.length;
}
// HJ 2026-06-10 — 마일스톤 세그먼트 바 (기존 .lbar 진행바를 대체).
// 단계의 agent 마다 segment 하나. 완료=초록, 현재=파랑 펄스, 대기=회색.
// 메타: "진행 N% · 경과 Y" — ETA(예상 남은 시간) 표시 제거 (사용자 요구).
function progressBar(forceShow){
  if(isFailed()) return '';
  if(cur===LAST && isCompleted()) return '';                       // G7 완료 페이지 (결과 표시) — 바 숨김
  if(cur===0 && !jobId) return '';                                 // 업로드 전
  if(cur>=1 && cur<=5 && !isGateLoading() && !forceShow) return '';  // proposals 표시 중 (모달 내부는 forceShow 로 항상 표시)
  // CS 2026-06-10 — 본인 명시 "팝업에는 무조건 주제만". 팝업 활성 시 진행률 바 숨김.
  if(cur===1 && g2SubStage==='topic' && (gateData.topic_proposals||[]).length) return '';
  const p=_stageProgress();
  const stageEl=_stageStart?((Date.now()-_stageStart)/1000):0;
  // _stageStart 가 있고 실패·완료 상태가 아니면 단계가 진행 중 — 경과 시간 항상 표시.
  // (G1 끝에서 curGate='G2' 도달하고 proposals 미도착 transient 구간에서 analyzing()=false 가 되어
  //  isRunning 이 false 로 떨어져 경과 시간이 사라지던 버그 fix.)
  const isRunning=(_stageStart!=null)&&!isFailed()&&!isCompleted();

  // 마일스톤 세그먼트 — 단계의 agent 리스트가 곧 바의 구조.
  const flow=_curAgentFlow();
  let activeIdx=_curMilestoneIdx();
  // HJ 2026-06-12 — 모달 로딩 중(95% hold)에는 마지막 칸을 active(파랑)로 유지.
  //   실제 완료(모달 닫힘 후 p>=100) 시에만 전체 done(녹색).
  if(p>=100 || (_completing && !inModalLoading())) activeIdx=flow.length;
  let barHtml='';
  if(flow.length){
    const segs=flow.map(function(ag,i){
      let cls='ms-seg';
      let icon;
      if(i<activeIdx){ cls+=' done'; icon='✓'; }
      else if(i===activeIdx){ cls+=' active'; icon='●'; }
      else { cls+=' pending'; icon=(i+1)+'.'; }
      // STAGE_AGENT_FLOW 항목이 곧 라벨 (descriptive 한국어). AGENT_KO 조회 불필요.
      const name=esc(ag);
      return '<div class="'+cls+'" title="'+name+'"><span class="ms-seg-icon">'+icon+'</span>'+name+'</div>';
    }).join('');
    barHtml='<div class="ms-bar">'+segs+'</div>';
  }

  // 메타 — 진행 % + 경과 시간. ETA 제거.
  let meta;
  if(isRunning){
    meta='<div class="lmeta">진행 <b>'+p+'%</b> · 경과 <b>'+fmtTime(stageEl)+'</b></div>';
  } else if(p>=100){
    meta='<div class="lmeta">진행 <b>'+p+'%</b> · <b>완료</b></div>';
  } else {
    meta='<div class="lmeta">진행 <b>'+p+'%</b></div>';
  }
  return '<div class="progbox">'+barHtml+meta+'</div>';
}
function gateHeader(g){
  // CS 2026-06-10 — 동적 헤더 + 카테고리별 매핑.
  //   1) GATE_HEADER_BY_CATEGORY[mode][cur][category] 우선 (G2/G2→G3 적용)
  //   2) 매핑 없으면 GATE_TITLE / STAGE_TRANSITION_DESC 폴백
  const tt=GATE_TITLE[g]||['추천을 검토하세요','Review the recommendation'];
  const cat=(gateData.category && gateData.category!=='pending')?('<span>카테고리 <b>'+esc(gateData.category)+'</b></span>'):'';
  const tgt=gateData.target_column?('<span>타깃 <b>'+esc(gateData.target_column)+'</b></span>'):'';
  const props=(gateData.proposals||[]).filter(function(p){return !p.is_custom;});
  const stage=STAGE_TRANSITION_DESC[cur];
  // CS 2026-06-11 — 본인 명시 "강제 X". frontend 휴리스틱 override 제거.
  // backend 의 LLM 분류 결과를 그대로 신뢰. 미확정/빈값이면 _default 폴백.
  let catKey=gateData.category;
  let h2, en, desc;
  if(props.length){
    // proposals 도착 = 사용자 결정 시점
    const cmap=GATE_HEADER_BY_CATEGORY.static[cur]||{};
    const byCat=cmap[catKey]||cmap._default;   // catKey 매칭 없으면 _default 사용 (어떤 데이터든 대응)
    if(byCat){ h2=byCat.h2; en=byCat.en; desc=byCat.desc||'업로드하신 데이터를 ADA가 분석해 제안한 결과입니다.'; }
    else { h2=tt[0]; en=tt[1]; desc='업로드하신 데이터를 ADA가 분석해 제안한 결과입니다.'; }
  } else if(stage){
    // 로딩 구간 = 카테고리별 헤더 우선, _default fallback, 없으면 단계 친화 폴백
    const cmap=GATE_HEADER_BY_CATEGORY.loading[cur]||{};
    const byCat=cmap[catKey]||cmap._default;
    if(byCat){ h2=byCat.h2; en=byCat.en; desc=byCat.desc||('곧 "'+esc(tt[0])+'" 화면이 표시됩니다.'); }
    else { h2=stage.ko; en=stage.en; desc='곧 "'+esc(tt[0])+'" 화면이 표시됩니다.'; }
  } else {
    // 폴링 대기·미정 → 기본
    h2=tt[0]; en=tt[1];
    desc='업로드하신 데이터를 ADA가 분석해 제안한 결과입니다.';
  }
  return '<div class="ahdr"><h2>'+h2+'</h2><div class="en">'+en+'</div></div>'
    +'<p class="desc">'+desc+'</p>'
    +((cat||tgt)?('<div class="databar"><span class="t">✓ 데이터 분석 완료</span>'+cat+tgt+'</div>'):'');
}
function propCard(p, idx, recId){
  const g5=curGate()==='G6';
  const sel=g5?(g5Checked[p.id]?' sel':''):((selId===p.id)?' sel':'');
  const rec=(!g5&&p.id===recId)?'<span class="rec">추천</span>':'';
  let extra='';
  if(p.models && p.models.length) extra='<div class="hint">🧩 모델: '+p.models.map(esc).join(', ')+'</div>';
  else if(p.metrics && typeof p.metrics==='object'){ const ks=Object.keys(p.metrics).slice(0,3); if(ks.length) extra='<div class="hint">📊 '+ks.map(function(k){return esc(k)+' '+esc(fmtNum(p.metrics[k]));}).join(' · ')+'</div>'; }
  else if(p.outputs && p.outputs.length){ var OL={'OUT-01':'PPT','OUT-02':'PDF 보고서','OUT-03':'발표 대본','OUT-04':'HTML 대시보드','OUT-07':'인사이트 요약'}; extra='<div class="hint">📦 '+p.outputs.map(function(o){return esc(OL[o]||o);}).join(' · ')+'</div>'; }
  const score=(p.score!=null)?('<div class="time">⭐ 추천도 '+Math.round(p.score*100)+'%</div>'):'';
  // CS 2026-06-10 — 글머리표 가독성: <br><br> → div 래핑 + margin (위·아래 간격)
  const ratLines = esc(p.rationale||'').split('\\n').filter(function(s){return s.trim();});
  const rat = ratLines.map(function(line){return '<div class="ratline">'+line+'</div>';}).join('');
  return '<div class="opt'+sel+'" data-pid="'+esc(p.id)+'"><div class="ck">✓</div><div class="onum">OPTION 0'+(idx+1)+rec+'</div><h3>'+esc(p.title||('제안 '+p.id))+'</h3><div class="ratbody">'+rat+'</div>'+extra+score+'</div>';
}
function customCard(n){
  const sel=(selId==='custom')?' sel':'';
  const g=curGate()||('G'+(cur+1));  // 새 컨벤션: cur=1(분석방향)→G2 ... cur=5(산출물)→G6
  const ph=g==='G6'?'예) PPT, 대시보드, 인사이트 요약 (선택: PPT · PDF 보고서 · 발표 대본 · 대시보드 · 인사이트)':'예) 1등석 여성 승객의 생존 요인을 집중 분석하고 싶어요';
  const title=g==='G6'?'직접 선택':'직접 입력';
  return '<div class="opt'+sel+'" data-pid="custom"><div class="ck">✓</div><div class="onum">OPTION 0'+(n+1)+'</div><h3>'+title+'</h3><div class="en2">Custom Direction</div>'
    +'<textarea id="cust" placeholder="'+ph+'"></textarea><div class="time">자유 입력</div></div>';
}
// G6 화면 상단에 표시할 학습·평가 리포트 카드 — best_model + eval_result 요약.
// 사용자가 산출물을 선택하기 전에 "무엇이 학습됐는지" 확인할 수 있도록 한다.
function g6ReportBlock(d){
  const bm=d.best_model;
  const ev=d.eval_result;
  let parts='';
  if(bm && typeof bm==='object'){
    const nm=bm.model_name||bm.title||'?';
    let metricLine='';
    if(bm.metrics && typeof bm.metrics==='object'){
      const ks=Object.keys(bm.metrics).slice(0,3);
      metricLine=ks.map(function(k){return '<span class="chip">'+esc(k)+' <b>'+esc(fmtNum(bm.metrics[k]))+'</b></span>';}).join('');
    }
    parts+='<div class="rcard" style="grid-column:1/-1;margin-bottom:14px">'
      +'<h4>🏆 최적 모델 · '+esc(nm)+'</h4>'
      +(metricLine?('<div style="margin-top:6px">'+metricLine+'</div>'):'')
      +'</div>';
  }
  if(ev && typeof ev==='object'){
    let inner='';
    if(ev.rationale) inner+='<p class="rtext">'+esc(ev.rationale)+'</p>';
    if(ev.metrics && typeof ev.metrics==='object'){
      const ks=Object.keys(ev.metrics).slice(0,4);
      inner+='<div style="margin-top:8px">'+ks.map(function(k){return '<span class="chip">'+esc(k)+' <b>'+esc(fmtNum(ev.metrics[k]))+'</b></span>';}).join('')+'</div>';
    }
    if(inner) parts+='<div class="rcard" style="grid-column:1/-1;margin-bottom:14px"><h4>📊 평가 결과</h4>'+inner+'</div>';
  }
  return parts;
}

// HJ 2026-06-09 G1 단축 Z' — G2 "주제 선정" 영역 렌더링.
// schema_validator 가 _save_g2_screen_ready 로 도메인·column_meanings 사전 저장.
// gate_direction LLM (~55s) 진행 동안 사용자가 도메인 보면서 주제 고민 → 시간 흡수.
function g2TopicArea(d){
  const dp=(d&&d.data_profile)||{};
  const da=dp.domain_analysis||{};
  // domain_partial 캐시도 fallback (도메인 LLM streaming 중간 상태)
  const dpart=(d&&d.domain_partial)||{};
  const domain=da.domain||dpart.domain||'';
  const summary=da.dataset_summary||dpart.dataset_summary||'';
  const tInsight=da.target_insight||dpart.target_insight||'';
  const cm=da.column_meanings||{};
  if(!domain && !summary && !Object.keys(cm).length) return '';
  let cmHtml='';
  const cmKeys=Object.keys(cm).slice(0,12);
  if(cmKeys.length){
    cmHtml='<div style="margin-top:10px"><div style="font-size:18px;opacity:.7;margin-bottom:6px">컬럼 의미 ('+cmKeys.length+(Object.keys(cm).length>12?'/'+Object.keys(cm).length:'')+')</div>'
      +'<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:6px;font-size:18px">'
      +cmKeys.map(function(k,i){return '<div style="background:#fff;padding:6px 8px;border-radius:4px;border:1px solid #e2e8f0;opacity:0;animation:cmIn 0.35s ease forwards;animation-delay:'+(i*0.13).toFixed(2)+'s"><b>'+esc(k)+'</b> &nbsp;<span style="opacity:.75">'+esc(String(cm[k]))+'</span></div>';}).join('')
      +'</div></div>';
  }
  return '<div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:14px 16px;margin-bottom:14px">'
    +'<div style="font-size:25px;font-weight:600;color:#0f172a;margin-bottom:8px">📌 주제 선정 — 데이터 도메인</div>'
    +(domain?'<div style="font-size:18px"><span style="opacity:.7">도메인</span> &nbsp;<b>'+esc(domain)+'</b></div>':'')
    +(summary?'<div style="margin-top:6px;font-size:18px"><span style="opacity:.7">데이터셋</span> &nbsp;'+esc(summary)+'</div>':'')
    +(tInsight?'<div style="margin-top:6px;font-size:18px"><span style="opacity:.7">타깃 인사이트</span> &nbsp;'+esc(tInsight)+'</div>':'')
    +cmHtml
    +'</div>';
}

// CS 2026-06-10 — G2 Sub-1 (주제 선정) 팝업 모달 본문.
// gateData.topic_proposals (백엔드 schema_validator 가 prefetch 한 5개) 렌더링.
// 사용자가 카드 선택 후 "선택 완료" 클릭 → POST /pipeline/gate/G2/directions/{job_id}
// 호출되어 분석 방향 LLM 이 호출되고 g2SubStage='direction' 으로 전환.
function g2TopicCards(d){
  const tps = (d && d.topic_proposals) || [];
  if(!tps.length){
    return '<div class="topicmodal"><div class="topicmodal-inner">'
      +'<div class="topichdr"><h2>🎯 주제 선정</h2><div class="en">Choose your topic</div></div>'
      +'<div style="text-align:center;padding:40px;font-size:18px;color:#8aa0bd">🔄 주제 후보 준비 중…</div>'
      +'</div></div>';
  }
  // CS 2026-06-10 — 박스 2개 구조 (OPTION 1 = 5 라디오 그룹 / OPTION 2 = textarea).
  // 표준 <input type=radio> 사용 → 브라우저 기본 클릭·키보드 동작 보장.
  const customSelected = (selectedTopic && selectedTopic.custom !== undefined);
  const radios = tps.slice(0, 5).map(function(t, i){
    const checked = (!customSelected && selectedTopic && selectedTopic.id === t.id) ? ' checked' : '';
    const rec = (i === 0) ? '<span class="rec">추천</span>' : '';
    return '<label class="topicradio">'
      +'<input type="radio" name="topicchoice" value="'+esc(t.id)+'"'+checked+'>'
      +'<div class="trtext"><b>'+esc(t.title)+'</b>'+rec+'</div>'
      +'</label>';
  }).join('');
  const customChecked = customSelected ? ' checked' : '';
  const btnDisabled = g2DirectionsBusy
    || (customSelected && !topicCustomText.trim());
  // HJ 2026-06-11 — busy 중 경과초 표시. render 500ms 주기로 자동 갱신.
  const _gdSec = (g2DirectionsBusy && g2DirectionsStartedAt) ? Math.floor((Date.now()-g2DirectionsStartedAt)/1000) : 0;
  const btnLabel = g2DirectionsBusy ? ('… 분석 방향 생성 중 ('+_gdSec+'초)') : '선택 완료 ▶';
  return '<div class="topicmodal"><div class="topicmodal-inner">'
    +'<button class="modal-close" title="팝업 닫기 (다시 열기 버튼으로 복원 가능)" onclick="dismissTopic()">✕</button>'
    +'<div class="topichdr">'
    +'<h2>🎯 주제 선정</h2>'
    +'<div class="en">Choose your topic</div>'
    +'<div class="stepline">'
    +'<span class="stepchip">1/2</span>'
    +'<span class="desc">발표 자료(PPT) 표지 제목으로 사용할 주제를 선택해주세요</span>'
    +'</div>'
    +'</div>'
    +'<div class="topicwrap">'
    +'<div class="topicbox '+(customSelected?'':'box-active')+'">'
      +'<div class="onum">OPTION 1</div>'
      +'<h3>추천 주제</h3>'
      +'<div class="topicradios">'+radios+'</div>'
    +'</div>'
    +'<div class="topicbox '+(customSelected?'box-active':'')+'">'
      +'<div class="onum">OPTION 2</div>'
      +'<h3>직접 입력</h3>'
      +'<label class="topicradio topicradio-custom">'
        +'<input type="radio" name="topicchoice" value="custom"'+customChecked+'>'
        +'<textarea id="topiccust-ta" placeholder="원하는 주제를 입력하세요"></textarea>'
      +'</label>'
    +'</div>'
    +'</div>'
    +'<div class="topicfoot">'
    +'<button class="topicbtn" id="topicSubmitBtn"'+(btnDisabled?' disabled':'')+'>'+btnLabel+'</button>'
    +'</div>'
    +'</div></div>';
}

// HJ 2026-06-11 — 모달의 "논리적 활성" 조건. modalDismissed 와 무관 — backend 분석이 진행 중이고
//   모달이 원래 떠야 하는 상태이면 true. render 가 이 값으로 콘텐츠/타자기 백그라운드 갱신 결정.
//   사용자 요구: "모달 ✕ 닫아도 글 작성은 계속 진행. 다시 열면 그동안 작성된 글이 보임."
function _modalShouldBeActive(){
  if(!jobId) return false;
  if(isFailed()) return false;
  // HJ 2026-06-12 — G6 는 완료돼도 팝업 타이핑이 끝나기 전이면 모달 유지 (조기 종료·7단계 점프 방지).
  if(isCompleted() && !_g6TypingHold()) return false;
  // 1~6단계(cur=0~5) 모달은 진행률 41% 이상에서만 노출. 초반 40% 까지는 본문 카드 표시. (원래 동작 유지)
  // HJ 2026-06-12 — 4단계(G4 모델학습) 팝업 미표시 버그 fix.
  //   G4 는 backend 글로벌 진행 [50,85] 에 매핑되는데, 튜닝 종료 시점 글로벌 64% = 단계 40%(=(64-50)/35)
  //   로 41% 게이트 '직전'에 걸린다. 41% 돌파는 학습(글로벌 82%) 종료 시점이라, 그때는 이미 다음 게이트가
  //   도착해 모달 창이 스킵됨. 게다가 240s 추정치 탓에 시간 기반 폴백도 너무 느리다.
  //   → cur===3 한정, 단계 분석이 15초 이상 진행되면 pct 무관하게 모달 노출 (아래 lastSubmittedGate 가드 유지).
  const _stageElapsedMs=_stageStart?(Date.now()-_stageStart):0;
  const _g4ModalFallback=(cur===3 && _stageElapsedMs>=15000);
  if(cur>=0 && cur<=5 && _shownPct<41 && !_g4ModalFallback) return false;
  if(cur===0){
    const _p0=(gateData.proposals||[]).filter(function(p){return !p.is_custom;});
    if(_p0.length && curGate()==='G2' && _typingHoldComplete()) return false;
    return true;
  }
  if(cur>=1 && cur<=5){
    const currentGate='G'+(cur+1);
    const nextGate='G'+(cur+2);
    if(lastSubmittedGate!==currentGate) return false;
    const ag=curGate();
    const d=(ag===nextGate)?gateData:(gateCache[nextGate]||{});
    const llmProps=(d.proposals||[]).filter(function(p){return !p.is_custom;});
    if(llmProps.length && _typingHoldComplete()) return false;
    return true;
  }
  return false;
}
// HJ 2026-06-10 G1 분석 팝업 (revision 2) — G1 시작(jobId 셋)부터 G2 proposals 도착 전까지 모달 유지.
// 진행 단계와 무관하게 분석 내용 표시 시점부터(=업로드 직후) 노출. 모달이 본문 내용을 대체.
// HJ 2026-06-11 — 시각적 표시 여부 (modalDismissed=true 시 false). _modalShouldBeActive 와 분리.
function inModalLoading(){
  // HJ 2026-06-10 — 사용자가 ✕ 로 모달 닫음. 같은 cur 동안만 유효, cur 변경 시 자동 해제.
  if(modalDismissed && _modalDismissedCur===cur) return false;
  if(modalDismissed && _modalDismissedCur!==cur){
    // HJ 2026-06-11 — cur 변경 → modalDismissed 해제 + 이전 단계 모달 상태 모두 리셋.
    //   dismiss 보존 로직이 새 단계로 새지 않도록 fresh start.
    modalDismissed=false;
    _twState={}; _twDotsShownAt=0;
    _modalOpenedAt=null; _modalOpenedCur=-1;
    _twAllDoneAt=null;
  }
  return _modalShouldBeActive();
}
// (구 inModalLoading 본체는 위 _modalShouldBeActive() 로 통합됨)
// 모달 전용 주제 영역 — g2TopicArea 의 2배 사이즈 버전. 사용자 요구 (글씨 2x).
function modalTopicArea(d){
  const dp=(d&&d.data_profile)||{};
  const da=dp.domain_analysis||{};
  const dpart=(d&&d.domain_partial)||{};
  const domain=da.domain||dpart.domain||'';
  const summary=da.dataset_summary||dpart.dataset_summary||'';
  const tInsight=da.target_insight||dpart.target_insight||'';
  const cm=da.column_meanings||{};
  if(!domain && !summary && !Object.keys(cm).length) return '';
  let cmHtml='';
  const cmAllKeys=Object.keys(cm);
  if(cmAllKeys.length){
    // HJ 2026-06-10 — 컬럼 개수별 레이아웃 + 행 단위 순차 reveal:
    //   8개 이하: 전부 2x2 그리드. 각 행은 그 행 카드의 타이핑이 시작될 때 등장.
    //   9개 이상: 상단 4(첫 3 비타깃 + 타깃) — 중단 ⋮ — 하단 4. 도형도 행 단위로 순차 등장.
    // 카드는 초기 opacity:0;visibility:hidden 으로 숨김 → _twTick 이 data-cmrow 기반으로 reveal.
    // 점 3개(⋮)는 상단 4 카드의 타이핑이 모두 완료되어야 등장. ~800ms 정지 후 하단 시작.
    const _card=function(k,row,sec){return '<div class="cmcard" data-cmrow="'+row+'" data-cmsec="'+sec+'" style="background:#fff;padding:14px 18px;border-radius:8px;border:1px solid #e2e8f0;opacity:0;visibility:hidden;transition:opacity .35s ease"><b>'+esc(k)+'</b> &nbsp;<span style="opacity:.75">'+twSpan(String(cm[k]),'g1-cm-'+k)+'</span></div>';};
    const _grid='display:grid;grid-template-columns:repeat(2,1fr);gap:12px;font-size:22px';
    const _dots='<div class="cmdots" style="display:flex;flex-direction:column;align-items:center;gap:3px;margin:10px 0;color:#94a3b8;font-size:17px;line-height:1;font-weight:800;opacity:0;visibility:hidden;transition:opacity .4s ease"><span>·</span><span>·</span><span>·</span></div>';
    const _label='<div class="twrow" style="font-size:22px;margin-bottom:12px;opacity:0;visibility:hidden;transition:opacity .3s ease"><span style="opacity:.7">'+twSpan('컬럼 의미 ('+cmAllKeys.length+')','g1-cmlabel')+'</span></div>';
    if(cmAllKeys.length<=8){
      cmHtml='<div style="margin-top:22px">'+_label+'<div style="'+_grid+'">'
        +cmAllKeys.map(function(k,i){return _card(k,Math.floor(i/2),'all');}).join('')
        +'</div></div>';
    } else {
      const target=(d&&d.target_column)||'';
      const hasTarget=target && cmAllKeys.indexOf(target)>=0;
      let topKeys;
      if(hasTarget){
        const first3=cmAllKeys.filter(function(k){return k!==target;}).slice(0,3);
        topKeys=first3.concat([target]);
      } else {
        topKeys=cmAllKeys.slice(0,4);
      }
      const topSet={}; topKeys.forEach(function(k){topSet[k]=1;});
      const remaining=cmAllKeys.filter(function(k){return !topSet[k];});
      const botKeys=remaining.slice(-4);
      cmHtml='<div style="margin-top:22px">'+_label
        +'<div style="'+_grid+'">'+topKeys.map(function(k,i){return _card(k,Math.floor(i/2),'top');}).join('')+'</div>'
        +_dots
        +'<div style="'+_grid+'">'+botKeys.map(function(k,i){return _card(k,Math.floor(i/2)+2,'bot');}).join('')+'</div>'
        +'</div>';
    }
  }
  return '<div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:14px;padding:30px 36px;margin-bottom:20px">'
    +(domain?'<div class="twrow" style="font-size:28px;opacity:0;visibility:hidden;transition:opacity .3s ease"><span style="opacity:.7">도메인</span> &nbsp;<b>'+twSpan(domain,'g1-domain')+'</b></div>':'')
    +(summary?'<div class="twrow" style="margin-top:14px;font-size:26px;line-height:1.5;opacity:0;visibility:hidden;transition:opacity .3s ease"><span style="opacity:.7">데이터셋</span> &nbsp;'+twSpan(summary,'g1-summary')+'</div>':'')
    +(tInsight?'<div class="twrow" style="margin-top:14px;font-size:26px;line-height:1.5;opacity:0;visibility:hidden;transition:opacity .3s ease"><span style="opacity:.7">타깃 인사이트</span> &nbsp;'+twSpan(tInsight,'g1-tinsight')+'</div>':'')
    +cmHtml
    +'</div>';
}
// HJ 2026-06-10 — 단계별 누적 인사이트 (모달 안 표시). 각 단계가 진행되면서 backend 가 publish 한 결과들을 모달에 노출.
// 사용자가 분석 대기 중 지루하지 않도록 진행 과정의 결과를 실시간으로 확인.
// HJ 2026-06-10 — 단계별 sub-step 진행 설명. 1단계 (G1) 처럼 milestone 진행에 따라 순차로 누적 표시.
// 각 sub-step 의 작업 내용을 한 줄씩, 완료된 것은 ✓ 녹색, 현재 작업은 ● 파랑, 미래는 숨김 (순차 reveal).
const STAGE_SUBSTEP_DESC={
  G2:[
    '📊 컬럼별 평균·표준편차·분포 통계 계산',
    '📈 히스토그램·박스플롯·왜도·첨도 분석',
    '🔗 변수 간 Pearson·Spearman 상관계수 계산',
    '🎯 도메인 관점에서 주요 패턴·이상치 식별',
    '⚖️ 카테고리별 알고리즘 후보 매칭·평가'
  ],
  G3:[
    '🧹 결측치 처리 방안·스케일링·정규화 전략 수립',
    '🔍 결측 컬럼별 imputation, 이상치 임계값 결정',
    '🏷️ 범주형 인코딩 (One-hot·Target·Frequency) 후보 평가',
    '⚙️ 파생 변수·교호작용·도메인 피처 생성',
    '✅ 최종 전처리·피처 엔지니어링 파이프라인 구성'
  ],
  G4:[
    '🧬 카테고리·데이터 특성에 맞는 모델 풀 선정',
    '🎚️ 모델별 하이퍼파라미터 그리드·범위 설정',
    '🔧 Bayesian·Random Search 로 최적 조합 탐색',
    '🏋️ Cross-validation 으로 모델 학습·검증',
    '📡 학습 곡선·과적합·수렴 여부 모니터링',
    '📊 정확도·F1·AUC 등 지표 종합 집계'
  ],
  G5:[
    '📂 파인튜닝용 데이터 분할·전처리',
    '🎯 선정된 최적 모델 파인튜닝 실행',
    '🧪 테스트 데이터로 성능 평가',
    '🔬 SHAP·Feature Importance 로 모델 해석',
    '💡 결과 기반 도메인 인사이트 도출'
  ],
  G6:[
    '📥 분석 결과·모델·메트릭 데이터 수집',
    '✍️ AI 가 분석 보고서 본문 작성',
    '📊 차트·그래프·표 자동 생성',
    '📁 PPT·PDF·HTML 등 산출물 파일 생성',
    '💾 결과 DB 저장 및 자기 학습 데이터 업데이트'
  ]
};
function modalSubstepProgress(){
  const stageKey=_curStageKey();
  if(stageKey==='G1') return '';  // G1 은 modalTopicArea 가 따로 처리
  const descs=STAGE_SUBSTEP_DESC[stageKey];
  if(!descs||!descs.length) return '';
  const activeIdx=_curMilestoneIdx();
  // 완료된 것 + 현재 진행 중인 것만 표시 (미래 sub-step 은 milestone 바에서만 보이고 여기는 숨김 — 순차 reveal)
  const items=descs.map(function(text,i){
    let icon, color, bg, border, suffix;
    if(i<activeIdx){
      icon='✓'; color='#15803d'; bg='#f0fdf4'; border='#bbf7d0'; suffix=' <span style="font-weight:600">완료</span>';
    } else if(i===activeIdx){
      icon='●'; color='#1d4ed8'; bg='#eff6ff'; border='#93c5fd'; suffix=' <i style="opacity:.75">진행 중…</i>';
    } else {
      return '';
    }
    return '<div style="background:'+bg+';border:1px solid '+border+';border-radius:10px;padding:14px 22px;margin-bottom:8px;font-size:22px;color:'+color+';display:flex;align-items:center;gap:12px">'
      +'<span style="font-weight:800;font-size:24px">'+icon+'</span>'
      +'<span style="flex:1">'+esc(text)+suffix+'</span>'
      +'</div>';
  }).filter(function(s){return !!s;});
  if(!items.length) return '';
  return '<div style="margin-bottom:18px">'+items.join('')+'</div>';
}
// 라벨드 row 헬퍼 — G1 의 "도메인: 여객선 사고" 패턴.
function _labelRow(label, value, opts){
  if(value==null||value==='') return '';
  opts=opts||{};
  // HJ 2026-06-10 — 1단계 방식 통일: 행 전체 hidden → 차례에 reveal + 값 타이핑.
  //   라벨(span opacity:.7) 은 row 가 reveal 될 때 함께 등장.
  var key=opts.twk||('lr-'+cur+'-'+label);
  var v=twSpan(String(value),key);
  return '<div class="twrow" style="margin-top:'+(opts.mt==null?14:opts.mt)+'px;font-size:'+(opts.fs||26)+'px;line-height:1.5;opacity:0;visibility:hidden;transition:opacity .3s ease">'
    +'<span style="opacity:.7">'+esc(label)+'</span> &nbsp;'
    +(opts.bold?('<b>'+v+'</b>'):v)
    +'</div>';
}
// 한 단계의 모달 박스 — G1 modalTopicArea 와 동일한 구조 (제목 + 라벨링된 row 들).
function _stageBox(titleEmoji, titleText, rows){
  var body=(rows||[]).filter(function(s){return !!s;}).join('');
  if(!body) return '';
  // HJ 2026-06-12 — 사용자 요구로 팝업 줄 수 제한 해제(제한 없음). 모든 row 를 그대로 렌더.
  // HJ 2026-06-10 — 박스 제목도 twrow + twSpan 으로 — 가장 먼저 등장+타이핑되고 그 다음 row 들이 순차 reveal.
  return '<div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:14px;padding:30px 36px;margin-bottom:20px">'
    +'<div class="twrow" style="font-weight:700;color:#0f172a;margin-bottom:6px;font-size:32px;opacity:0;visibility:hidden;transition:opacity .3s ease">'+titleEmoji+' '+twSpan(titleText,'sbtitle-'+cur+'-'+titleText)+'</div>'
    +body+'</div>';
}
// HJ 2026-06-11 — G3~G6 모달 콘텐츠 공용 헬퍼.
//   _toBullets(v, maxLen): 어떤 데이터 타입이든 (string/array/object) 불릿 항목 배열로 변환.
//   _modalSection(emoji, title, items, opts): 섹션 헤더 + 들여쓴 불릿 묶음 HTML 반환 (G2 패턴과 동일).
//   각 단계 분기에서 호출 → 글 내용은 backend 데이터 그대로, 배치만 가독성 좋게.
function _toBullets(v, maxLen){
  maxLen = maxLen || 220;
  if(v==null) return [];
  if(typeof v === 'string') return v ? [v.slice(0, maxLen)] : [];
  if(Array.isArray(v)) return v.map(function(x){ return String(x).slice(0, maxLen); }).filter(function(s){ return !!s; });
  if(typeof v === 'object'){
    return Object.keys(v).map(function(k){
      var val = v[k];
      var s = (val!=null && typeof val === 'object') ? JSON.stringify(val) : String(val==null?'':val);
      return k + ': ' + s.slice(0, maxLen);
    });
  }
  return [String(v).slice(0, maxLen)];
}
function _modalSection(emoji, title, items, opts){
  opts = opts || {};
  if(!items || !items.length) return '';
  var mt = opts.mt != null ? opts.mt : 32;
  var twkPrefix = opts.twk || ('sec-'+cur+'-'+title);
  var parts = [];
  // 섹션 헤더 (G2 그룹 헤더와 동일 스타일)
  parts.push('<div class="twrow" style="margin-top:'+mt+'px;font-size:24px;font-weight:700;color:#0f172a;opacity:0;visibility:hidden;transition:opacity .3s ease">'
    + emoji + ' ' + twSpan(title, twkPrefix+'-hdr')
    + '</div>');
  // 들여쓴 불릿 항목들
  items.forEach(function(item, j){
    if(item==null || item==='') return;
    parts.push('<div class="twrow" style="margin-top:8px;font-size:21px;line-height:1.55;padding-left:24px;opacity:0;visibility:hidden;transition:opacity .3s ease">'
      + '<span style="opacity:.45;margin-right:10px;font-weight:700">•</span>'
      + twSpan(String(item), twkPrefix+'-'+j)
      + '</div>');
  });
  return parts.join('');
}
// HJ 2026-06-11 — backend 인사이트 배열을 prefix("결측 처리:", "튜닝 결과:") 별 그룹화 → HTML 반환.
// G2 의 eda_insights 와 동일 패턴을 G3~G6 모두 통일 적용. 입력: 인사이트 배열 + emoji 매핑.
function _modalGroupedInsights(insights, emojiMap, twkPrefix, firstMt){
  if(!Array.isArray(insights) || !insights.length) return '';
  firstMt = firstMt != null ? firstMt : 36;
  var groups = {}; var order = [];
  insights.forEach(function(ins){
    var s = String(ins);
    var ci = s.indexOf(':');
    var prefix, val;
    if(ci>0 && ci<30){ prefix = s.slice(0,ci).trim(); val = s.slice(ci+1).trim(); }
    else { prefix = '기타'; val = s; }
    if(!groups[prefix]){ groups[prefix] = []; order.push(prefix); }
    groups[prefix].push(val);
  });
  var firstGrp = true;
  var parts = [];
  order.forEach(function(prefix){
    var em = (emojiMap && emojiMap[prefix]) || '🔬';
    parts.push('<div class="twrow" style="margin-top:'+(firstGrp?firstMt:28)+'px;font-size:24px;font-weight:700;color:#0f172a;opacity:0;visibility:hidden;transition:opacity .3s ease">'
      + em + ' ' + twSpan(prefix, twkPrefix+'-hdr-'+prefix)
      + '</div>');
    firstGrp = false;
    groups[prefix].forEach(function(val, j){
      parts.push('<div class="twrow" style="margin-top:8px;font-size:21px;line-height:1.55;padding-left:24px;opacity:0;visibility:hidden;transition:opacity .3s ease">'
        + '<span style="opacity:.45;margin-right:10px;font-weight:700">•</span>'
        + twSpan(val, twkPrefix+'-'+prefix+'-'+j)
        + '</div>');
    });
  });
  return parts.join('');
}
function modalInsightArea(d){
  // HJ 2026-06-11 — 모달 표시 후 5초 경과 전에는 콘텐츠 숨김 (호출처가 cur 별 placeholder 노출).
  // 5초 경과 후 데이터 있으면 즉시 작성, 데이터 늦으면 도착한 render 주기에 자동 작성.
  if(!_modalContentReady()) return '';
  // 1단계 (G1, cur=0): 데이터 도메인 정보 — domain_partial streaming
  if(cur===0){
    return modalTopicArea(d);
  }
  const dp=(d&&d.data_profile)||{};
  // 2단계 (G2 — EDA·방법론 분석)
  // HJ 2026-06-10 — 사용자 요구: "1단계처럼 실시간 분석 내용이 들어가야". 상태 메시지(▶ ...) 위주에서
  // 백엔드 eda_agent 가 publish 하는 stage_partial.eda_insights (결측·상관·클래스·skew 자연어 분석 4종)
  // + methodology_candidates[].rationale (각 방법론의 3줄 글머리 설명) 을 본격 노출.
  if(cur===1){
    const r=[];
    // === 기본 정보 (좁은 간격) ===
    if(dp.rows&&dp.cols) r.push(_labelRow('데이터 크기', dp.rows.toLocaleString()+'행 × '+dp.cols+'컬럼', {mt:8,bold:true}));
    if(d.category&&d.category!=='pending') r.push(_labelRow('카테고리', d.category, {bold:true, mt:8}));
    if(d.target_column) r.push(_labelRow('타깃', d.target_column, {bold:true, mt:8}));
    if(dp.target_dtype) r.push(_labelRow('타깃 자료형', dp.target_dtype, {mt:8}));
    if(dp.class_distribution&&typeof dp.class_distribution==='object'){
      const cd=dp.class_distribution, ks=Object.keys(cd).slice(0,4);
      if(ks.length) r.push(_labelRow('클래스 분포', ks.map(function(k){return k+': '+cd[k];}).join(', '), {mt:8}));
    }
    const sp=(d&&d.stage_partial)||{};
    // HJ 2026-06-11 — EDA 현재 상태(✨ 2차 분석 업그레이드 멘트 포함)를 인사이트 위에 항상 표시.
    //   구버그: eda_insights(템플릿) 채워지면 eda_status 가 숨겨져 '✨…업그레이드하는 중…' 멘트가 영영 안 떴음.
    //   G3(g3_status 무조건 상단 표시)와 동일 패턴으로 통일.
    if(sp.eda_status) r.push(_labelRow('▶ 현재 작업', sp.eda_status, {fs:22, mt:8, twk:'eda-status'}));
    // === EDA 인사이트 — prefix("결측 분석:", "상관관계:" 등) 별 그룹화 ===
    // HJ 2026-06-11 — 사용자 요구: 같은 주제끼리 묶고 다른 주제로 넘어갈 때 한 칸 띄움.
    //   섹션 헤더(굵게) + 들여쓴 불릿 항목 구조. 글 내용 자체는 변경 없음 (배치만 가독성 개선).
    if(Array.isArray(sp.eda_insights)&&sp.eda_insights.length){
      var _groups={}; var _order=[];
      sp.eda_insights.forEach(function(ins){
        var s=String(ins);
        var ci=s.indexOf(':');
        var prefix, val;
        if(ci>0 && ci<30){ prefix=s.slice(0,ci).trim(); val=s.slice(ci+1).trim(); }
        else { prefix='EDA 인사이트'; val=s; }
        if(!_groups[prefix]){ _groups[prefix]=[]; _order.push(prefix); }
        _groups[prefix].push(val);
      });
      var _emoji={'결측 분석':'📭','상관관계':'🔗','클래스 분포':'⚖️','분포 비대칭':'🌀','EDA 인사이트':'🔍'};
      var _firstGrp=true;
      _order.forEach(function(prefix){
        var em=_emoji[prefix]||'🔍';
        // 섹션 헤더 (굵게, 큰 spacer로 이전 그룹과 분리)
        r.push('<div class="twrow" style="margin-top:'+(_firstGrp?36:28)+'px;font-size:24px;font-weight:700;color:#0f172a;opacity:0;visibility:hidden;transition:opacity .3s ease">'
          +em+' '+twSpan(prefix,'eda-hdr-'+prefix)
          +'</div>');
        _firstGrp=false;
        // 그룹 항목 (불릿 + 들여쓰기, 좁은 간격)
        _groups[prefix].forEach(function(val,j){
          r.push('<div class="twrow" style="margin-top:8px;font-size:21px;line-height:1.55;padding-left:24px;opacity:0;visibility:hidden;transition:opacity .3s ease">'
            +'<span style="opacity:.45;margin-right:10px;font-weight:700">•</span>'
            +twSpan(val,'eda-'+prefix+'-'+j)
            +'</div>');
        });
      });
    }
    // === 진행 상태 — eda_status(업그레이드 멘트 포함)는 위 '▶ 현재 작업' 배너로 이동(중복 표시 방지) ===
    if(sp.eda_charts_count!=null) r.push(_labelRow('▶ 차트 생성', sp.eda_charts_count+'종', {bold:true, mt:14}));
    // === 방법론 후보 — 섹션 헤더 + 들여쓴 불릿 구조로 통일 ===
    if(Array.isArray(sp.methodology_candidates)&&sp.methodology_candidates.length){
      r.push('<div class="twrow" style="margin-top:40px;font-size:24px;font-weight:700;color:#0f172a;opacity:0;visibility:hidden;transition:opacity .3s ease">'
        +'🧪 '+twSpan('방법론 후보','meth-hdr')
        +'</div>');
      sp.methodology_candidates.forEach(function(c,i){
        var titleLine=(c.id||(i+1))+'. '+(c.title||'')+(c.score!=null?' (점수: '+c.score+')':'');
        // 후보 제목 (불릿 + 굵게)
        r.push('<div class="twrow" style="margin-top:'+(i===0?12:20)+'px;font-size:22px;line-height:1.55;padding-left:24px;opacity:0;visibility:hidden;transition:opacity .3s ease">'
          +'<span style="opacity:.45;margin-right:10px;font-weight:700">•</span>'
          +'<b>'+twSpan(titleLine,'meth-title-'+i)+'</b>'
          +'</div>');
        // 후보 설명 (한 단계 더 들여쓰기)
        if(c.rationale){
          r.push('<div class="twrow" style="margin-top:4px;font-size:20px;line-height:1.55;padding-left:48px;color:#475569;opacity:0;visibility:hidden;transition:opacity .3s ease">'
            +'<span style="opacity:.55;margin-right:8px">└</span>'
            +twSpan(String(c.rationale),'meth-rat-'+i)
            +'</div>');
        }
      });
    } else if(sp.methodology_status){
      r.push(_labelRow('▶ 방법론', sp.methodology_status, {fs:22, mt:14}));
    }
    if(d.eda_summary) r.push(_labelRow('EDA 요약', typeof d.eda_summary==='string'?d.eda_summary:JSON.stringify(d.eda_summary).slice(0,200), {fs:22, mt:18}));
    return _stageBox('📊','EDA · 방법론 분석', r);
  }
  // 3단계 (G3 — 전처리·피처 분석)
  // HJ 2026-06-11 — G2 패턴(섹션 헤더 + 들여쓴 불릿) 으로 통일. 글 내용 동일, 배치만 가독성 개선.
  // HJ 2026-06-11 — 🌱 파생 피처 생성 라이브 피드 추가 (backend feature_engineer 가 publish 하는 fe_* 필드).
  if(cur===2){
    const r=[];
    const sp=(d&&d.stage_partial)||{};
    // === ▶ 라이브 진행 상태 (G2 와 동일 — 5초 게이트 통과 시 즉시 보이도록 무조건 1줄 보장) ===
    // HJ 2026-06-11 — backend g3_status 가 있으면 그걸, 없으면 일반 안내. state 필드 미도착 시에도 빈 placeholder 회피.
    if(sp.g3_status){
      r.push(_labelRow('▶ 현재 작업', sp.g3_status, {fs:22, mt:8, twk:'g3-status'}));
    } else {
      r.push(_labelRow('▶ 진행 상태', '전처리·피처 엔지니어링 분석을 진행하고 있습니다…', {fs:22, mt:8, twk:'g3-fallback'}));
    }
    // === 기본 정보 ===
    if(d.category&&d.category!=='pending') r.push(_labelRow('카테고리', d.category, {mt:14, bold:true}));
    if(d.chosen_recipe&&d.chosen_recipe.title) r.push(_labelRow('선택한 방법론', d.chosen_recipe.title, {bold:true, mt:8}));
    if(d.user_intent) r.push(_labelRow('분석 의도', String(d.user_intent).slice(0,200), {fs:22, mt:8}));
    // === 🔬 전처리 인사이트 — prefix("결측 처리:", "스케일링:", "인코딩:" 등) 별 그룹화 ===
    // HJ 2026-06-11 — G2 의 eda_insights 와 완전 동일 패턴 (공용 헬퍼 _modalGroupedInsights 사용).
    if(Array.isArray(sp.g3_insights)&&sp.g3_insights.length){
      var _g3emoji={'결측 처리':'📭','스케일링':'⚖️','인코딩':'🏷️','이상치 처리':'🚨','분포 변환':'📈','파생 피처':'🌿','구간화':'📊','컬럼 제거':'🗑️','행 제거':'🗑️','전처리':'🔧'};
      r.push(_modalGroupedInsights(sp.g3_insights, _g3emoji, 'g3-ins', 36));
    }
    // === 💭 LLM 전체 근거 (preprocessing_strategist 한 줄 요약) ===
    if(sp.g3_rationale){
      r.push(_modalSection('💭','전처리 전략 근거', [sp.g3_rationale], {mt:28, twk:'g3-rat'}));
    }
    // === ⚠️ Leakage 위험 ===
    if(Array.isArray(sp.g3_leakage_risks)&&sp.g3_leakage_risks.length){
      r.push(_modalSection('⚠️','Leakage 위험', sp.g3_leakage_risks, {mt:28, twk:'g3-leak'}));
    }
    // === 🧹 전처리 전략 (state 필드 — gate 도착 시) ===
    if(d.preprocessing_strategy){
      r.push(_modalSection('🧹','전처리 전략 (state)', _toBullets(d.preprocessing_strategy, 240), {mt:28, twk:'g3-prep'}));
    }
    // === 🔧 피처 엔지니어링 (LLM rationale) ===
    if(d.feature_engineering){
      r.push(_modalSection('🔧','피처 엔지니어링', _toBullets(d.feature_engineering, 240), {mt:28, twk:'g3-feat'}));
    }
    // === 🌱 파생 피처 생성 — backend feature_engineer 가 실제 적용한 변환 결과 ===
    // before/after 컬럼 수, 적용된 변환 목록, 신규 컬럼 예시 노출.
    if(sp.fe_after_count!=null){
      const fitems=[];
      // 컬럼 수 변화 한 줄
      if(sp.fe_before_count!=null){
        const _newN=Math.max(0, sp.fe_after_count - sp.fe_before_count);
        fitems.push('원본 '+sp.fe_before_count+'개 → '+sp.fe_after_count+'개 컬럼 (신규 '+_newN+'개)');
      } else {
        fitems.push('최종 '+sp.fe_after_count+'개 컬럼');
      }
      // 적용된 변환
      if(Array.isArray(sp.fe_applied_steps) && sp.fe_applied_steps.length){
        fitems.push('적용된 변환: '+sp.fe_applied_steps.join(' · '));
      }
      // 신규 컬럼 예시 (최대 8개)
      if(Array.isArray(sp.fe_new_columns) && sp.fe_new_columns.length){
        const _show=sp.fe_new_columns.slice(0,8);
        const _more=sp.fe_new_columns.length>8 ? (' 외 '+(sp.fe_new_columns.length-8)+'개') : '';
        fitems.push('신규 컬럼 예시: '+_show.join(', ')+_more);
      }
      r.push(_modalSection('🌱','파생 피처 생성', fitems, {mt:28, twk:'g3-deriv'}));
    } else if(sp.g3_phase==='feature_engineer_start' && sp.fe_before_count!=null){
      // 진행 중 라이브 메시지 (handler 실행 중)
      r.push(_modalSection('🌱','파생 피처 생성', ['원본 '+sp.fe_before_count+'개 컬럼에 변환 적용 중…'], {mt:28, twk:'g3-deriv'}));
    }
    return _stageBox('🧪','전처리 · 피처 분석', r);
  }
  // 4단계 (G4 — 모델 학습)
  // HJ 2026-06-11 — G2 패턴(섹션 헤더 + 들여쓴 불릿). agent 가 끝나는 순서대로 필드 채워짐:
  //   model_selection → candidate_models / hyperparameter_tuner → best_params /
  //   training_executor → best_model / metrics_aggregator → metrics
  if(cur===3){
    const r=[];
    const sp=(d&&d.stage_partial)||{};
    // === ▶ 라이브 진행 상태 (G2 와 동일 — 무조건 1줄 보장) ===
    if(sp.g4_status){
      r.push(_labelRow('▶ 현재 작업', sp.g4_status, {fs:22, mt:8, twk:'g4-status'}));
    } else {
      r.push(_labelRow('▶ 진행 상태', '모델 선택·하이퍼파라미터 튜닝·학습을 진행하고 있습니다…', {fs:22, mt:8, twk:'g4-fallback'}));
    }
    // === 기본 정보 ===
    if(d.chosen_recipe&&d.chosen_recipe.title) r.push(_labelRow('방법론', d.chosen_recipe.title, {mt:14, bold:true}));
    // === 🤖 모델 선정 인사이트 (backend 자연어 publish) ===
    if(Array.isArray(sp.g4_model_insights)&&sp.g4_model_insights.length){
      var _g4mEmoji={'모델 후보 1':'🥇','모델 후보 2':'🥈','모델 후보 3':'🥉','선정 근거':'💭','베이스라인':'📏'};
      r.push(_modalGroupedInsights(sp.g4_model_insights, _g4mEmoji, 'g4-ms', 36));
    }
    // === ⚙️ 하이퍼파라미터 튜닝 인사이트 (모델별 best_params) ===
    if(Array.isArray(sp.g4_hpo_insights)&&sp.g4_hpo_insights.length){
      var _g4hEmoji={'튜닝 결과':'⚙️'};
      r.push(_modalGroupedInsights(sp.g4_hpo_insights, _g4hEmoji, 'g4-hpo', 28));
    }
    // === 🏋️ 학습 결과 인사이트 (모델별 메트릭) ===
    if(Array.isArray(sp.g4_train_insights)&&sp.g4_train_insights.length){
      var _g4tEmoji={'학습 결과':'🏋️'};
      r.push(_modalGroupedInsights(sp.g4_train_insights, _g4tEmoji, 'g4-train', 28));
    }
    // === 🎯 후보 모델 (state 필드 — gate 도착 시 표시) ===
    if(d.candidate_models&&Array.isArray(d.candidate_models)&&d.candidate_models.length){
      r.push(_modalSection('🎯','후보 모델 (state)', d.candidate_models.slice(0,10), {mt:28, twk:'g4-cand'}));
    }
    // === ⚙️ 최적 하이퍼파라미터 (모델별) ===
    if(d.best_params&&typeof d.best_params==='object'&&Object.keys(d.best_params).length){
      const bpItems=[];
      Object.keys(d.best_params).forEach(function(mn){
        const p=d.best_params[mn];
        const pStr=(p!=null&&typeof p==='object')?JSON.stringify(p):String(p==null?'':p);
        bpItems.push(mn+' → '+pStr.slice(0,200));
      });
      r.push(_modalSection('⚙️','최적 하이퍼파라미터', bpItems, {mt:28, twk:'g4-hp'}));
    }
    // === 🏆 최적 모델 ===
    if(d.best_model&&d.best_model.model_name){
      r.push(_labelRow('🏆 최적 모델', d.best_model.model_name, {bold:true, mt:32, fs:24}));
    }
    // === 📊 학습 메트릭 ===
    if(d.best_model&&d.best_model.metrics&&typeof d.best_model.metrics==='object'){
      const m=d.best_model.metrics, ks=Object.keys(m).slice(0,6);
      if(ks.length){
        r.push(_modalSection('📊','학습 메트릭', ks.map(function(k){return k+': '+fmtNum(m[k]);}), {mt:14, twk:'g4-met'}));
      }
    }
    return _stageBox('🏋️','모델 학습', r);
  }
  // 5단계 (G5 — 평가·인사이트)
  // HJ 2026-06-11 — G2 패턴(섹션 헤더 + 들여쓴 불릿). agent 끝나는 순서:
  //   fine_tune → best_model 갱신 / eval_agent → eval_result / explainability / insight → insights
  if(cur===4){
    const r=[];
    const sp=(d&&d.stage_partial)||{};
    // === ▶ 라이브 진행 상태 (G2 와 동일 — 무조건 1줄 보장) ===
    if(sp.g5_status){
      r.push(_labelRow('▶ 현재 작업', sp.g5_status, {fs:22, mt:8, twk:'g5-status'}));
    } else {
      r.push(_labelRow('▶ 진행 상태', '모델 파인튜닝·평가·설명·인사이트를 생성하고 있습니다…', {fs:22, mt:8, twk:'g5-fallback'}));
    }
    // === 기본 정보 ===
    if(d.best_model&&d.best_model.model_name) r.push(_labelRow('대상 모델', d.best_model.model_name, {mt:14, bold:true}));
    // === 📊 평가 인사이트 (backend 자연어 publish) ===
    if(Array.isArray(sp.g5_eval_insights)&&sp.g5_eval_insights.length){
      var _g5eEmoji={'평가 결과':'📊','평가 메트릭':'📈','평가 요약':'💡','임계치 미달':'⚠️'};
      r.push(_modalGroupedInsights(sp.g5_eval_insights, _g5eEmoji, 'g5-ev', 36));
    }
    // === 🔍 SHAP 인사이트 (상위 피처) ===
    if(Array.isArray(sp.g5_shap_insights)&&sp.g5_shap_insights.length){
      var _g5sEmoji={'SHAP 상위 피처':'🔍','SHAP 계산 실패':'⚠️','시계열 분해':'📉'};
      r.push(_modalGroupedInsights(sp.g5_shap_insights, _g5sEmoji, 'g5-shap', 28));
    }
    // === 📝 최종 인사이트 (LLM 한국어 3~5문장 분리) ===
    if(Array.isArray(sp.g5_final_insights)&&sp.g5_final_insights.length){
      var _g5fEmoji={'인사이트':'📝'};
      r.push(_modalGroupedInsights(sp.g5_final_insights, _g5fEmoji, 'g5-final', 28));
    }
    // === 📊 평가 메트릭 ===
    if(d.eval_result&&d.eval_result.metrics&&typeof d.eval_result.metrics==='object'){
      const m=d.eval_result.metrics, ks=Object.keys(m).slice(0,6);
      if(ks.length){
        r.push(_modalSection('📊','평가 메트릭', ks.map(function(k){return k+': '+fmtNum(m[k]);}), {mt:32, twk:'g5-met'}));
      }
    }
    // === 💡 평가 요약 ===
    if(d.eval_result&&d.eval_result.rationale){
      r.push(_modalSection('💡','평가 요약', _toBullets(d.eval_result.rationale, 300), {mt:28, twk:'g5-ra'}));
    }
    // === 🔍 설명가능성 ===
    if(d.explainability){
      r.push(_modalSection('🔍','설명가능성', _toBullets(d.explainability, 300), {mt:28, twk:'g5-exp'}));
    }
    // === 📝 인사이트 ===
    if(d.insights&&typeof d.insights==='string'&&d.insights.length>20){
      r.push(_modalSection('📝','인사이트', _toBullets(d.insights, 500), {mt:28, twk:'g5-ins'}));
    }
    return _stageBox('📈','평가 · 인사이트', r);
  }
  // 6단계 (G6 — 리포트·산출물)
  // HJ 2026-06-11 — G2 패턴(섹션 헤더 + 들여쓴 불릿). agent 끝나는 순서:
  //   report_composer → output_paths 누적 / self_learning_dispatch → 마무리
  if(cur===5){
    const r=[];
    const sp=(d&&d.stage_partial)||{};
    const OL={'OUT-01':'PPT','OUT-02':'PDF 보고서','OUT-03':'발표 대본','OUT-04':'HTML 대시보드','OUT-07':'인사이트 요약'};
    // === ▶ 라이브 진행 상태 (G2 와 동일 — 무조건 1줄 보장) ===
    if(sp.g6_status){
      r.push(_labelRow('▶ 현재 작업', sp.g6_status, {fs:22, mt:8, twk:'g6-status'}));
    } else {
      r.push(_labelRow('▶ 진행 상태', '리포트 합성 및 학습 결과 저장을 진행하고 있습니다…', {fs:22, mt:8, twk:'g6-fallback'}));
    }
    // === 📦 산출물 생성 인사이트 (backend 자연어 publish — 산출물별 ✓/✗) ===
    if(Array.isArray(sp.g6_output_insights)&&sp.g6_output_insights.length){
      var _g6Emoji={'산출물 생성':'📦','종합':'🎯'};
      r.push(_modalGroupedInsights(sp.g6_output_insights, _g6Emoji, 'g6-out', 28));
    }
    // === 🎁 요청 산출물 ===
    if(d.requested_outputs&&Array.isArray(d.requested_outputs)&&d.requested_outputs.length){
      r.push(_modalSection('🎁','요청 산출물', d.requested_outputs.map(function(o){return OL[o]||o;}), {mt:28, twk:'g6-req'}));
    }
    // === ✅ 생성 완료 ===
    if(d.output_paths&&typeof d.output_paths==='object'){
      const ks=Object.keys(d.output_paths);
      if(ks.length){
        r.push(_modalSection('✅','생성 완료', ks.map(function(o){return OL[o]||o;}), {mt:28, twk:'g6-done'}));
      }
    }
    // === 📝 포함될 인사이트 ===
    if(d.insights&&typeof d.insights==='string'&&d.insights.length>20){
      r.push(_modalSection('📝','포함될 인사이트', _toBullets(d.insights, 400), {mt:28, twk:'g6-ins'}));
    }
    return _stageBox('📦','리포트 · 산출물', r);
  }
  return '';
}
// 모달 내부 컨텐츠 — 큰 타이틀 + modalInsightArea + 단계별 안내. 진행바는 카드 본문에 그대로 두고 모달에서 제외(사용자 요구).
function modalHtml(){
  // 단계별 안내 — 단계 N 화면에서 진행 누르면 그 자리에서 단계 N 분석 진행 (cur 그대로 유지).
  //   cur=0 (1단계 업로드)  → G1 분석 → 다음: 분석 방향 카드
  //   cur=1 (2단계 분석방향) → G2 분석 → 다음: 방법론 카드
  //   cur=2 (3단계 방법론)   → G3 분석 → 다음: 모델 전략 카드
  //   cur=3 (4단계 모델전략) → G4 분석 → 다음: 최적 모델 카드
  //   cur=4 (5단계 모델선택) → G5 분석 → 다음: 산출물 카드
  //   cur=5 (6단계 산출물)   → G6 분석 → 다음: 최종 결과
  // insightHtml → #modal-insight (render 에서 직접 갱신, 모래시계 리셋 방지)
  // pending/hourglass → #modal-pending-wrap (render 에서 1회 초기화 후 span 만 갱신)
  const stepNum=cur+1;
  let body='';
  if(errMsg) body+='<div class="err">⚠ '+esc(errMsg)+'</div>';
  // CS 2026-06-11 — modal 헤더 동기화.
  //   cur=0 (G1→G2 팝업, 주제 나오기 전) = G1 인라인 헤더와 동일 (단일 표현)
  //   cur=2 (G2→G3 팝업) = cur=2 loading 헤더와 동기화 (카테고리별)
  //   그 외 cur (1/3/4/5) = 기존 'N단계 분석 중'
  if(cur===0){
    body+='<div class="modal-title">데이터를 파악하는 중입니다</div>';
    body+='<div class="modal-en">G1 — Data Understanding</div>';
    body+='<div class="desc" style="text-align:center;font-size:20px;color:#6b7c95;margin:14px 0 0;line-height:1.5">출처·스키마·도메인 의미·데이터 품질·카테고리 판정·PII 점검까지 마치는 중입니다. 끝나면 자동으로 분석 방향 추천이 표시됩니다.</div>';
  } else {
    // CS 2026-06-11 — 본인 명시 "강제 X". modal 도 frontend 휴리스틱 제거. backend LLM 분류 신뢰.
    //   cur=1 (G2→G3 진행: 사용자 G2 응답 후 ~ G3 게이트 도달 전, eda_agent 동작)
    //   + cur=2 (G3 도달 후 → G4 진행 중) 모두 loading[2] = "EDA 작업 중" 헤더와 동기화.
    //   backend AGENT_PHASE_MAP 의 18~33% 가 cur=1 eda_agent 시점.
    var _useLoading2 = (cur===1 || cur===2);
    var _mc=_useLoading2?((GATE_HEADER_BY_CATEGORY.loading&&GATE_HEADER_BY_CATEGORY.loading[2])||{}):{};
    var _mb=_mc[gateData.category]||_mc._default;
    if(_useLoading2 && _mb){
      body+='<div class="modal-title">'+_mb.h2+'</div>';
      body+='<div class="modal-en">'+_mb.en+'</div>';
      body+='<div class="desc" style="text-align:center;font-size:20px;color:#6b7c95;margin:14px 0 0;line-height:1.5">'+_mb.desc+'</div>';
    } else {
      body+='<div class="modal-title">'+stepNum+'단계 분석 중</div>';
      body+='<div class="modal-en">Stage '+stepNum+' analysis in progress…</div>';
    }
  }
  return body;
}
function contentGate(){
  const tg='G'+(cur+1);           // 사용자가 보고 싶은 게이트 (cur 기준). cur=1→G2 ... cur=5→G6
  const ag=curGate();             // 백엔드 현재 게이트
  // HJ 2026-06-10 — 모달 활성 시 카드 본문은 헤더만. 모달이 분석 내용을 보여주므로 중복 제거.
  if(inModalLoading()) return gateHeader(tg);
  // 방금 제출한 게이트이고 다음 게이트 미도착(분석 중) → 캐시 proposals 재표시 방지
  if(lastSubmittedGate===tg && !ag){ return gateHeader(tg)+loadingBlock(); }
  // 실시간: ag===tg면 gateData, 뒤로가기 등 이전 단계: 캐시 사용
  // stale: resume 직후 analyzing() 미확인 구간은 이전 gate_data 무시
  const _staleRun=!!(lastSubmittedGate&&!_sawAnalyzingAfterSubmit);
  const d=_staleRun?{}:((ag===tg)?gateData:(analyzing()?{}:(gateCache[tg]||{})));
  const g=tg;
  const props=(d.proposals)||[];
  // CS 2026-06-10 — G2 Sub-1 (주제 선정 팝업).
  // g2SubStage='topic' + topic_proposals 도착했을 때만 팝업 모달 표시.
  // topic_proposals 없으면 (백그라운드 prefetch 미완료) → G1 모달 / 로딩 유지.
  if(g==='G2' && g2SubStage==='topic' && (d.topic_proposals||[]).length){
    // HJ 2026-06-12 — 팝업 표시 즉시 5개 분석 방향 백그라운드 선생성 1회 발사(추천부터).
    _g2FirePrefetch(d);
    // HJ 2026-06-11 — cur 변경 시 topicDismissed 자동 해제 (modalDismissed 와 동일 패턴).
    if(topicDismissed && _topicDismissedCur!==cur){ topicDismissed=false; }
    // 사용자가 ✕ 로 팝업 닫음 — 본문에 "다시 열기" 버튼만 표시. 주제 선택은 필수이므로 진행 불가 안내.
    if(topicDismissed && _topicDismissedCur===cur){
      return gateHeader(g)
        +'<div style="background:#f0f4fa;border:1px solid #d6e0ed;border-radius:14px;padding:22px 26px;margin-bottom:16px;display:flex;justify-content:space-between;align-items:center;gap:18px;flex-wrap:wrap">'
        +'<div style="font-size:18px;color:#1f3e5c"><b>🎯 주제 선정 팝업이 닫혔습니다.</b><br><span style="font-size:15px;color:#6b7c95">다음 단계 진행을 위해 주제를 선택해야 합니다.</span></div>'
        +'<button class="topicbtn" onclick="reopenTopicPopup()">주제 선정 다시 열기 ▶</button>'
        +'</div>';
    }
    // CS 2026-06-10 — 본인 명시 "팝업에는 무조건 주제만". gateHeader 제외.
    return g2TopicCards(d);
  }
  // HJ 2026-06-09 G1 단축 Z' — G2 에서 proposals 없을 때 (gate_direction 진행 중)
  // "주제 선정" 영역 먼저 표시 + 분석 방향 영역엔 spinner.
  if(g==='G2' && !props.length && d.g2_pending){
    // 팝업(inModalLoading)이 활성일 때는 팝업에서만 표시 — 인라인 중복 제거.
    // HJ 2026-06-10: G1 도메인 박스(g2TopicArea) 는 단계 2 인라인에 노출 금지 — 사용자 명시 요구.
    if(inModalLoading()) return gateHeader(g)+loadingBlock();
    return gateHeader(g)
      +'<div style="background:#fffbeb;border:1px solid #fde68a;border-radius:8px;padding:14px 16px;margin-bottom:10px">'
      +'<div style="font-size:18px;font-weight:600;color:#92400e;margin-bottom:6px">🔄 분석 방향 카드 생성 중…</div>'
      +'<div style="font-size:18px;opacity:.8">잠시만 기다려 주세요. 곧 추천 카드가 표시됩니다.</div>'
      +'</div>'
      +loadingBlock();
  }
  if(!props.length){ return gateHeader(g)+loadingBlock(); }
  // filter out backend-injected custom placeholder — customCard is added separately below
  const llmProps=props.filter(function(p){ return !p.is_custom; });
  if(!llmProps.length){ return gateHeader(g)+loadingBlock(); }
  let recId=llmProps.reduce(function(a,b){ return (b.score||0)>(a.score||0)?b:a; }, llmProps[0]).id;
  if(selId===null || selGate!==g){ selId=recId; selGate=g; }
  let cards=llmProps.map(function(p,i){ return propCard(p,i,recId); }).join('');
  if(g==='G2'||g==='G3'||g==='G4'||g==='G5') cards+=customCard(llmProps.length);
  let pop='';
  if(animatedGate!==g){ pop=' popin'; animatedGate=g; if(g==='G6') g5Checked={}; setTimeout(function(){ try{ window.scrollTo({top:0,behavior:'smooth'}); }catch(e){} }, 30); }
  // HJ 2026-06-10: G2 인라인에서도 G1 도메인 박스(g2TopicArea) 제거 — 단계별 콘텐츠 분리 요구.
  // G6 (산출물 선택) 화면은 산출물 카드만 표시 — 최적 모델·평가 결과 박스 숨김
  return gateHeader(g)+'<div class="opts'+pop+'">'+cards+'</div>';
}
function rcard(title, inner){ return '<div class="rcard"><h4>'+title+'</h4>'+inner+'</div>'; }
function contentResult(){
  const g=gateData; let panels='';
  if(g.eda_summary) panels+=rcard('데이터 요약 (EDA)','<p class="rtext">'+esc(g.eda_summary)+'</p>');
  if(g.best_model && typeof g.best_model==='object'){
    const m=g.best_model; let h='<div class="kpi">';
    if(m.model_name) h+='<div class="it"><div class="v">'+esc(m.model_name)+'</div><div class="l">최적 모델</div></div>';
    if(m.metrics && typeof m.metrics==='object'){ const mk=Object.keys(m.metrics)[0]; if(mk) h+='<div class="it"><div class="v">'+esc(fmtNum(m.metrics[mk]))+'</div><div class="l">'+esc(mk)+'</div></div>'; }
    h+='</div>'; panels+=rcard('최적 모델', h);
  }
  if(g.eval_result && typeof g.eval_result==='object'){
    const ev=g.eval_result; let h='';
    if(ev.rationale) h+='<p class="rtext">'+esc(ev.rationale)+'</p>';
    if(ev.metrics && typeof ev.metrics==='object'){ const ks=Object.keys(ev.metrics).slice(0,3); h+='<div class="kpi" style="margin-top:10px">'+ks.map(function(k){return '<div class="it"><div class="v">'+esc(fmtNum(ev.metrics[k]))+'</div><div class="l">'+esc(k)+'</div></div>';}).join('')+'</div>'; }
    if(h) panels+=rcard('평가 결과', h);
  }
  if(g.insights) panels+=rcard('인사이트','<p class="rtext">'+esc(g.insights)+'</p>');
  const reqOuts=g.requested_outputs||[];
  const OL={'OUT-01':'PPT 프레젠테이션','OUT-02':'PDF 보고서','OUT-03':'발표 대본','OUT-04':'HTML 대시보드','OUT-07':'인사이트 요약'};
  const outputPaths=g.output_paths||{};
  const dlKeys=Object.keys(outputPaths);
  if(reqOuts.length||dlKeys.length){
    const allOuts=reqOuts.length?reqOuts:dlKeys;
    const EXT={'OUT-01':'pptx','OUT-02':'pdf','OUT-03':'txt','OUT-04':'html','OUT-07':'md'};
    const ICON={'OUT-01':'📊','OUT-02':'📄','OUT-03':'🎙️','OUT-04':'🖥️','OUT-07':'💡'};
    const dlHtml=allOuts.map(function(o){
      if(outputPaths[o]){
        const url=API+'/pipeline/download/'+jobId+'/'+encodeURIComponent(o);
        return '<a href="'+esc(url)+'" download="ada_'+esc(EXT[o]||'bin')+'" class="dlbtn">'+esc(ICON[o]||'📦')+' '+esc(OL[o]||o)+'<span style="font-size:13px;opacity:.75;margin-left:4px">다운로드</span></a>';
      }
      return '<span class="dlbtn unavail">'+esc(ICON[o]||'📦')+' '+esc(OL[o]||o)+'<span style="font-size:13px;opacity:.75;margin-left:4px">생성 실패</span></span>';
    }).join('');
    panels='<div class="rcard" style="grid-column:1/-1"><h4>📥 산출물 다운로드</h4><div style="display:flex;flex-wrap:wrap;margin-top:8px">'+dlHtml+'</div></div>'+panels;
  }
  if(!panels) panels='<div class="rcard"><p class="rtext">결과를 불러오는 중…</p></div>';
  return '<div class="res"><div class="ahdr"><h2>분석 완료 🎉</h2></div><p class="desc">데이터를 분석한 결과입니다.</p><div class="grid2">'+panels+'</div></div>';
}
function content(i){
  if(i===0){
    // Phase 1 — G1 단계가 두 가지 상태를 가진다.
    //   (a) jobId 없음 → 파일 선택·의도 입력 화면(기존)
    //   (b) jobId 있음 + 분석 중 → 데이터 파악 진행 화면(15단계 백엔드 작업).
    //       이 화면을 끝까지 보여주다 G2 proposals 도착 시 poll() 이 cur=1 로 전환.
    if(jobId){
      // HJ 2026-06-10 — 모달 활성 시 카드 본문은 헤더만 (모달이 partial domain·loadingBlock 모두 표시).
      if(inModalLoading()){
        return '<div class="ahdr" style="opacity:.55"><h2>데이터를 파악하는 중입니다</h2>'
          +'<div class="en">G1 — Data Understanding</div></div>';
      }
      // 모달 미활성 (실패 등 폴백) — 기존 인라인 표시 유지
      // HJ 2026-06-09 G1 단축 γ — partial domain 점진 표시.
      // 도메인 LLM 의 streaming 콜백이 첫 필드 도착 시점부터 partial 값을 보냄.
      // 사용자가 71초를 빈 화면으로 보내지 않고 "도메인: 이커머스 ★" 같이 점진 확인.
      const dp=gateData.domain_partial||{};
      let partialHtml='';
      if(dp.domain || dp.dataset_summary || dp.target_insight){
        let lines=[];
        if(dp.domain) lines.push('<div><span style="opacity:.7">도메인</span> &nbsp;<b>'+esc(dp.domain)+'</b></div>');
        if(dp.dataset_summary) lines.push('<div style="margin-top:6px"><span style="opacity:.7">데이터셋</span> &nbsp;'+esc(dp.dataset_summary)+'</div>');
        if(dp.target_insight) lines.push('<div style="margin-top:6px"><span style="opacity:.7">타깃 인사이트</span> &nbsp;'+esc(dp.target_insight)+'</div>');
        if(dp.column_meanings_count) lines.push('<div style="margin-top:6px;opacity:.7">컬럼 의미 분석 중 ('+dp.column_meanings_count+'개 도착)</div>');
        partialHtml='<div style="background:#f1f5f9;border-left:3px solid #10b981;padding:10px 14px;margin:12px 0;border-radius:4px;font-size:18px">'
          +'<div style="font-weight:600;color:#10b981;font-size:18px;margin-bottom:6px">🟢 실시간 분석 결과</div>'
          +lines.join('')+'</div>';
      }
      return '<div class="ahdr"><h2>데이터를 파악하는 중입니다</h2>'
        +'<div class="en">G1 — Data Understanding</div></div>'
        +'<p class="desc">출처·스키마·도메인 의미·데이터 품질·카테고리 판정·PII 점검까지 마치는 중입니다. '
        +'끝나면 자동으로 분석 방향 추천이 표시됩니다.</p>'
        +partialHtml
        +loadingBlock();
    }
    const has=!!selectedFile;
    const t=has?('선택됨: '+esc(selectedFile.name)):'파일을 끌어다 놓거나 선택';
    // HJ 2026-06-09 G1 단축 Phase 4 — 사전 분석 UI (사용자 자연 연장).
    let prefetchUi='';
    if(has && prefetchPreview){
      let pvHtml='';
      pvHtml+='<div style="margin-top:8px;font-size:23px;opacity:.85">컬럼 <b>'+prefetchPreview.cols+'개</b>';
      if(prefetchPreview.columns && prefetchPreview.columns.length){
        pvHtml+=' &nbsp;·&nbsp; '+prefetchPreview.columns.slice(0,6).map(esc).join(', ');
        if(prefetchPreview.cols>6) pvHtml+=' …';
      }
      pvHtml+='</div>';
      let resultHtml='';
      if(prefetchResult && prefetchResult.category){
        resultHtml+='<div style="margin-top:10px;display:flex;flex-wrap:wrap;gap:8px;font-size:23px">';
        resultHtml+='<span style="background:#dcfce7;color:#15803d;padding:5px 12px;border-radius:4px"><b>추정 카테고리</b> '+esc(prefetchResult.category)+'</span>';
        if(prefetchResult.target_column){
          resultHtml+='<span style="background:#dbeafe;color:#1d4ed8;padding:5px 12px;border-radius:4px"><b>추정 타겟</b> '+esc(prefetchResult.target_column)+'</span>';
        }
        resultHtml+='</div>';
        if(prefetchResult.auto_intent && !intentText.trim()){
          resultHtml+='<div style="margin-top:8px;font-size:18px;color:#6b7280">💡 자동 추천 의도: <i>'+esc(prefetchResult.auto_intent)+'</i> &nbsp;<span style="opacity:.7">(의도란에 자유롭게 수정해 입력하세요)</span></div>';
        }
      } else if(prefetchSig){
        resultHtml='<div style="margin-top:8px;font-size:18px;color:#10b981">🟢 사전 분석 중… (의도를 입력하시는 동안 진행됩니다)</div>';
      }
      prefetchUi='<div style="background:#f0fdf4;border-left:4px solid #10b981;padding:14px 18px;margin:10px 0;border-radius:6px">'
        +'<div style="font-weight:700;color:#065f46;font-size:23px">📊 파일 사전 분석</div>'
        +pvHtml+resultHtml+'</div>';
    }
    return '<div class="ahdr"><h2>데이터 업로드</h2></div><p class="desc">파일을 올리면 ADA가 데이터를 분석해 방향을 제안합니다.</p>'
      +'<div class="dz'+(has?' has':'')+'" id="dz"><svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M7 18a4 4 0 0 1-.5-7.97A6 6 0 0 1 18 8.5a3.5 3.5 0 0 1 .5 6.96"/><path d="M12 19v-7"/><path d="m9 14 3-3 3 3"/></svg>'
      +'<div style="flex:1"><div class="t" id="dzt">'+t+'</div><div class="s">CSV · XLSX · JSON (최대 30MB)</div></div>'
      +'<button class="browse" id="browseBtn">찾아보기</button></div>'
      +'<input type="file" id="fileInput" style="display:none" accept=".csv,.xlsx,.json">'
      +prefetchUi
      +'<textarea class="intent" id="intentInput" placeholder="💬 분석 의도 — 예) 타이타닉 승객의 생존 여부를 예측하고 싶어요"></textarea>';
  }
  if(i>=1 && i<=5) return contentGate();
  return contentResult();
}
function primaryLabel(){
  if(busy) return '… 처리 중';
  if(paused) return '▶ 계속';
  if(cur===0) return '⬆ 업로드';
  if(cur===LAST) return '📥 완료';
  // HJ 2026-06-11 — 정지(navUnlocked) 눌림 중에는 어느 단계든 '재진행' 표기.
  //   누르면 그 단계를 현재 선택 카드로 재실행(doResume). cur<frontier(지난 단계)도 동일.
  if(cur>=1 && cur<=5 && (navUnlocked || cur<frontier)) return '🔄 재진행 ▸';
  return '진행 ▸';
}
function render(){
  // CS 2026-06-10 — 모든 textarea/input 포커스 보존 (polling render 시 포커스·커서 잃지 않게)
  // 주제 팝업 textarea (topiccust-ta), 분석 방향 직접 입력 (cust), G1 의도 입력 (intentInput) 등
  const _activeEl = document.activeElement;
  const _activeId = (_activeEl && _activeEl.id) || null;
  const _activeTag = (_activeEl && _activeEl.tagName) || null;
  let _selStart = 0, _selEnd = 0;
  try{
    if(_activeEl && _activeEl.selectionStart !== undefined){
      _selStart = _activeEl.selectionStart;
      _selEnd = _activeEl.selectionEnd;
    }
  }catch(e){}
  const sc=document.getElementById('steps');
  const fillPct=(frontier/(N-1))*100;
  let html='<div class="line"></div><div class="fill" style="width:calc((100% - 68px) * '+(fillPct/100)+')"></div>';
  steps.forEach(function(s,i){
    let cls, inner;
    if(i===cur){ cls='active'; inner=(i<frontier?'✓':(i+1)); }
    else if(i<=frontier){ cls='done'; inner='✓'; }
    else { cls='pending'; inner=(i+1); }
    if(i<=maxReached && i!==cur) cls+=' reachable';
    html+='<div class="step '+cls+'" data-i="'+i+'"><div class="dot">'+inner+'</div><div class="lab"><div class="nm">'+s.label+'</div><div class="sub">'+s.sub+'</div></div></div>';
  });
  sc.innerHTML=html;
  sc.querySelectorAll('.step.reachable').forEach(function(el){ el.onclick=function(){ cur=+el.dataset.i; if(cur<frontier) follow=false; paused=false; render(); }; });

  // 1~7 모든 단계 공통: 본문은 변화 있을 때만 innerHTML 교체 (SVG 애니메이션 리셋 방지).
  // 진행바는 500ms 마다 변하므로 별도 pb-area div 에 독립 갱신.
  var _nc=(errMsg?('<div class="err">⚠ '+esc(errMsg)+'</div>'):'')+content(cur);
  var _ce=document.getElementById('content');
  if(_ce._last!==_nc){_ce._last=_nc;_ce.innerHTML=_nc;}
  document.getElementById('pb-area').innerHTML=progressBar();
  // loadMsg·agentLabel 은 DOM 파괴 없이 직접 갱신 (innerHTML 리셋 방지 → SVG 애니메이션 유지)
  var _lmEl=document.getElementById('lmsg');
  if(_lmEl) _lmEl.textContent=loadMsg()+'…';
  var _laEl=document.getElementById('lagent');
  if(_laEl){var _agl2=_curAgentLabel();if(_agl2&&!(lastSubmittedGate&&!_sawAnalyzingAfterSubmit)){_laEl.innerHTML='현재 작업: <b>'+esc(_agl2)+'</b>';}else{_laEl.textContent='';}}
  document.getElementById('curName').textContent=steps[cur].label;
  // 상단 헤더 진행률 — 단계 전체(7개) 기준 달성도. 카드 안 로딩바(_stageProgress)와 다른 지표.
  document.getElementById('curPct').textContent=Math.round(frontier/(N-1)*100)+'%';
  document.getElementById('curIdx').textContent=cur+1;
  document.getElementById('curTot').textContent=N;
  const stt=document.getElementById('status');
  if(paused){ stt.textContent='⏸ 일시정지됨'; stt.className='status paused'; }
  else if(isFailed()){ stt.textContent='⛔ 실패'; stt.className='status failed'; }
  else if(isCompleted()){ stt.textContent='✓ 완료'; stt.className='status done'; }
  else if(jobId){ stt.textContent='진행 중'; stt.className='status'; }
  else { stt.textContent='대기'; stt.className='status'; }
  if(cur===0){
    const fi=document.getElementById('fileInput'), dz=document.getElementById('dz'),
          br=document.getElementById('browseBtn'), it=document.getElementById('intentInput');
    if(br&&fi) br.onclick=function(e){ e.stopPropagation(); fi.click(); };
    if(dz&&fi) dz.onclick=function(){ fi.click(); };
    // HJ 2026-06-09 G1 단축 Phase 4 — 파일 선택 즉시 client 파싱 + prefetch.
    if(fi) fi.onchange=function(){ if(fi.files[0]){ selectedFile=fi.files[0]; render(); startPrefetch(fi.files[0]); } };
    if(dz){ dz.ondragover=function(e){ e.preventDefault(); }; dz.ondrop=function(e){ e.preventDefault(); if(e.dataTransfer.files[0]){ selectedFile=e.dataTransfer.files[0]; render(); startPrefetch(e.dataTransfer.files[0]); } }; }
    if(it){
      it.value=intentText;
      it.oninput=function(){
        intentText=it.value;
        // auto_intent 추천 표시는 사용자가 직접 입력 시작하면 더 이상 안내 안 함
        if(prefetchResult && prefetchResult.auto_intent && it.value.trim()){ prefetchResult.auto_intent=null; }
      };
    }
  }
  if(cur>=1 && cur<=5){
    const isG5=curGate()==='G6';
    document.querySelectorAll('.opt').forEach(function(el){ el.onclick=function(){
      const pid=el.dataset.pid;
      if(isG5){ g5Checked[+pid]=!g5Checked[+pid]; render(); }
      else { selId=(pid==='custom')?'custom':(+pid); render(); }
    }; });
    const tc=document.getElementById('cust');
    if(tc){ tc.value=customText; tc.onclick=function(e){ e.stopPropagation(); };
      tc.onfocus=function(){ selId='custom'; document.querySelectorAll('.opt').forEach(function(el){ el.classList.toggle('sel', el.dataset.pid==='custom'); }); };
      tc.oninput=function(){ customText=tc.value; }; }
  }
  // CS 2026-06-10 — 주제 팝업 표준 라디오 onchange 핸들러
  document.querySelectorAll('input[type=radio][name=topicchoice]').forEach(function(r){
    r.onchange=function(){
      if(r.value==='custom'){ selectedTopic={custom:topicCustomText}; }
      else { selectedTopic={id:+r.value}; }
      saveState(); render();
    };
  });
  var tta=document.getElementById('topiccust-ta');
  if(tta){
    tta.value=topicCustomText;
    tta.onfocus=function(){
      var r=document.querySelector('input[type=radio][value=custom]');
      if(r) r.checked=true;
      selectedTopic={custom:topicCustomText};
      saveState();
    };
    tta.oninput=function(){
      topicCustomText=tta.value;
      if(selectedTopic && selectedTopic.custom!==undefined){
        selectedTopic.custom=topicCustomText;
        var b=document.getElementById('topicSubmitBtn'); if(b) b.disabled=!topicCustomText.trim();
      }
    };
  }
  var sb=document.getElementById('topicSubmitBtn');
  if(sb){
    sb.onclick=async function(){
      if(sb.disabled) return;
      var d=gateData; var tps=(d&&d.topic_proposals)||[];
      var topicText='';
      if(selectedTopic.custom!==undefined){ topicText=topicCustomText.trim(); }
      else { var t=tps.find(function(x){return x.id===selectedTopic.id;}); topicText=(t&&t.title)||''; }
      if(!topicText){ return; }
      g2DirectionsBusy=true; g2DirectionsStartedAt=Date.now(); render();
      try{
        await api('/pipeline/gate/G2/directions/'+jobId,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({topic:topicText})});
        window._g2_selectedTopicText=topicText;
        g2DirectionsReady=true;
        g2SubStage='direction';
        saveState();
      }catch(e){ errMsg='분석 방향 생성 실패 — '+e.message; }
      finally{ g2DirectionsBusy=false; g2DirectionsStartedAt=null; render(); }
    };
  }

  // CS 2026-06-10 — 활성 textarea/input 포커스 + 커서 위치 복원 (render 후)
  // generic: id 있는 모든 textarea/input 에 적용
  if(_activeId && (_activeTag === 'TEXTAREA' || _activeTag === 'INPUT')){
    const _newEl = document.getElementById(_activeId);
    if(_newEl && _newEl !== _activeEl){
      try{ _newEl.focus(); }catch(e){}
      try{ _newEl.setSelectionRange(_selStart, _selEnd); }catch(e){}
    }
  }

  const prev=document.getElementById('prevBtn'), next=document.getElementById('nextBtn'),
        stop=document.getElementById('stopBtn'), prim=document.getElementById('primaryBtn');
  prev.innerHTML=(cur===0)?'← 시작 화면':'← 이전 단계';
  // HJ 2026-06-11 — 정지 토글 기반 네비게이션 게이트. 1~6단계(cur=0~5)에서 정지(navUnlocked)가
  //   눌려 있어야만 이전/다음 단계 활성. 기본은 잠금(비활성). 정지 버튼은 진행 옆에 항상 노출.
  stop.style.display='inline-flex';
  stop.classList.toggle('engaged', navUnlocked);
  if(cur>=0 && cur<=5){
    prev.disabled=!navUnlocked;
    next.disabled=!navUnlocked || (cur>=maxReached);
  }else{
    prev.disabled=false;                 // 7단계(완료) — 기존 동작 유지
    next.disabled=(cur>=maxReached);
  }
  const _tg='G'+(cur+1);  // 새 컨벤션: cur 인덱스 → 백엔드 게이트 코드
  const _cd=gateCache[_tg]||{};
  const _llmCount=function(d){ return (d.proposals||[]).filter(function(p){return !p.is_custom;}).length; };
  const atCurrentGate=(cur===frontier)&&!!curGate()&&_llmCount(gateData)>0;
  const atPastGate=(cur<frontier)&&cur>=1&&cur<=5&&_llmCount(_cd)>0;
  // 실패 후 이전 단계로 돌아온 경우: curGate()=null 이어도 캐시 proposals 있으면 진행 허용
  const atFailedRetry=isFailed()&&cur>=1&&cur<=5&&(_llmCount(_cd)>0||_llmCount(gateData)>0);
  const atGate=atCurrentGate||atPastGate||atFailedRetry;
  const g5ok=curGate()!=='G6'||Object.keys(g5Checked).some(function(k){return g5Checked[k];});
  prim.innerHTML=primaryLabel();
  prim.classList.toggle('resume', paused);
  if(busy) prim.disabled=true;
  else if(paused) prim.disabled=false;
  else if(cur===0) prim.disabled=(!selectedFile || !!jobId);
  else if(cur===LAST) prim.disabled=true;
  else prim.disabled=!atGate||!g5ok;
  // HJ 2026-06-11 — 모달 토글 로직 재구성: 콘텐츠 갱신과 시각 표시 분리.
  //   _active = _modalShouldBeActive() : backend 분석 진행 중 + 모달 단계 = 콘텐츠 백그라운드 갱신 계속
  //   _show   = inModalLoading()       : 실제 화면에 모달 visible 여부 (modalDismissed 시 false)
  //   사용자 요구: "모달 ✕ 닫아도 글 작성은 계속 진행. 다시 열면 그동안 작성된 글이 그대로 보임."
  const _modalOv=document.getElementById('modalOverlay');
  if(_modalOv){
    const _active = _modalShouldBeActive();
    const _show   = inModalLoading();
    if(_active){
      // ── [A] 콘텐츠 백그라운드 갱신 — modalDismissed 여도 무조건 진행 ──
      // 5초 게이트 기준점 (cur 변경 시 재셋)
      if(_modalOpenedAt==null || _modalOpenedCur!==cur){
        _modalOpenedAt=Date.now();
        _modalOpenedCur=cur;
        setTimeout(function(){ if(_modalShouldBeActive()) try{render();}catch(_e){} }, MODAL_CONTENT_DELAY_MS+50);
      }
      // [1] 제목 영역
      var _mh=modalHtml(); var _mb=document.getElementById('modal-body');
      if(_mb._last!==_mh){_mb._last=_mh;_mb.innerHTML=_mh;}
      // [2] 진행바
      var _pbEl=document.getElementById('modal-pb');
      if(_pbEl) _pbEl.innerHTML=progressBar(true);  // HJ 2026-06-11 — 모달 내부 진행바는 isGateLoading 무관 항상 표시(사라짐 버그 fix)
      // [3] insight 영역 — modalInsightArea 가 모달 콘텐츠 생성. modalDismissed 와 무관하게 새 데이터 도착 시 갱신.
      var _miEl=document.getElementById('modal-insight');
      if(_miEl){var _MPH={0:'📊 데이터 도메인을 분석하는 중입니다…',1:'📊 EDA · 방법론 후보를 분석하는 중입니다…',2:'🧪 전처리 · 피처 엔지니어링 전략을 수립하는 중입니다…',3:'🏋️ 모델 선택 · 학습 · 하이퍼파라미터 튜닝을 진행하는 중입니다…',4:'📈 모델 평가 · 설명 · 인사이트를 생성하는 중입니다…',5:'📦 리포트 · 산출물을 합성하는 중입니다…'};var _iHtml=modalInsightArea(gateData)||(_MPH[cur]?'<div class="modal-placeholder">'+_MPH[cur]+'</div>':'');if(_miEl._last!==_iHtml){_miEl._last=_iHtml;_miEl.innerHTML=_iHtml;_twTick();}}
      // [3.5] 타자기 엔진 — modalDismissed 여도 setInterval 계속 도는 핵심.
      //   _twTick 가 span.tw[data-tw] 들을 95ms 마다 1글자씩 채움. 모달 숨겨져 있어도 DOM 은 살아있어 글자 누적.
      //   사용자가 다시 열면 그동안 그려진 글자가 그대로 보임.
      _twStart();
      // [4] 모래시계 pending 블록
      var _mpEl=document.getElementById('modal-pending-wrap');
      if(_mpEl&&!_mpEl._init){_mpEl._init=true;_mpEl.innerHTML='<div class="modal-pending"><div class="t">'+HOURGLASS_HTML+'<span id="mlmsg"></span></div><div class="s" id="msubinfo"></div></div>';}
      // [5] 동적 텍스트
      var _mlEl=document.getElementById('mlmsg');if(_mlEl)_mlEl.textContent=loadMsg()+'…';
      var _msiEl=document.getElementById('msubinfo');
      if(_msiEl){var _ml2=_curAgentLabel();var _sd={0:'데이터 출처·스키마·도메인·품질 점검 등을 진행하고 있습니다.',1:'EDA 분석 + 방법론 후보를 산출하고 있습니다.',2:'전처리·피처 엔지니어링 전략을 수립하고 있습니다.',3:'모델 선택·하이퍼파라미터 튜닝·학습을 진행하고 있습니다.',4:'파인튜닝·평가·설명·인사이트를 생성하고 있습니다.',5:'리포트를 합성하고 학습 결과를 저장하고 있습니다.'};var _sn={0:'분석 방향',1:'방법론',2:'모델 전략',3:'최적 모델',4:'산출물',5:'최종 결과'};var _d2=_sd[cur]||'다음 단계를 준비하고 있습니다.';var _n2=_sn[cur]||'다음 단계';_msiEl.innerHTML=_ml2?(_d2+' &nbsp;·&nbsp; 현재 작업: <b>'+esc(_ml2)+'</b> &nbsp;·&nbsp; 곧 <b>'+esc(_n2)+'</b> 카드가 표시됩니다.'):(_d2+' &nbsp;·&nbsp; 곧 <b>'+esc(_n2)+'</b> 카드가 표시됩니다.');}
    }
    // ── [B] 시각 표시 토글 — _show 만 보고 결정. modalDismissed=true 면 _show=false → 숨김 ──
    if(_show){
      _modalOv.style.display='flex';
    } else {
      _modalOv.style.display='none';
      // 자연 닫힘 (사용자 dismiss 아님 + 더 이상 active 아님) 시 _modalOpenedAt 만 리셋.
      // HJ 2026-06-11 버그픽스: _twState/_twAllDoneAt 를 여기서 지우면 _typingHoldComplete()=false 로 되돌아가
      //   → inModalLoading()=true 재반전 → 모달 재표시 → 재타자 → 완료 → reset → 무한루프 → cur 전진 불가.
      //   _twState/_twAllDoneAt 는 _typingHoldComplete() 가 자체 관리. 여기선 건드리지 않음.
      //   다음 단계 모달이 열릴 때 새 span 키 등장 → _twAllDone()=false → _twAllDoneAt 자동 리셋.
      if(!_active && !modalDismissed){
        _modalOpenedAt=null; _modalOpenedCur=-1;
      }
    }
  }
  // HJ 2026-06-11 — "분석 모달 다시 열기" floating 버튼 토글.
  //   조건: ① modalDismissed=true (사용자가 ✕ 로 닫음) AND ② 같은 cur 안에 있음 AND ③ 모달이 원래 떠야 하는 상태
  //   ③ = jobId 있음 + 실패·완료 아님 + 41% 도달 + cur=0~5 + 다음 게이트 proposals 미도착
  const _reBtn=document.getElementById('reopenModalBtn');
  if(_reBtn){
    let _shouldShow=false;
    if(modalDismissed && _modalDismissedCur===cur && jobId && !isFailed() && !isCompleted() && cur>=0 && cur<=5 && _shownPct>=41){
      if(cur===0){
        // G1: G2 proposals 미도착 (또는 도착했지만 타자기 미완료)이면 모달이 원래 떠야 함
        const _g2p=(gateData.proposals||[]).filter(function(p){return !p.is_custom;}).length;
        _shouldShow = !(_g2p && _typingHoldComplete());
      } else {
        // cur=1~5: submittedHere 이고 다음 게이트 proposals 미도착
        const _cg='G'+(cur+1), _ng='G'+(cur+2);
        if(lastSubmittedGate===_cg){
          const _ag=curGate();
          const _d=(_ag===_ng)?gateData:(gateCache[_ng]||{});
          const _np=(_d.proposals||[]).filter(function(p){return !p.is_custom;}).length;
          _shouldShow = !(_np && _typingHoldComplete());
        }
      }
    }
    _reBtn.style.display = _shouldShow ? 'inline-flex' : 'none';
  }
}
document.getElementById('prevBtn').onclick=function(){
  if(cur===0){
    // G1 에서 이전 = 랜딩 오버레이 표시 (iframe sandbox 로 부모 navigate 불가 → 자체 오버레이)
    clearState();
    var ov=document.getElementById('landingOverlay');
    if(ov){ ov.style.display='flex'; }
    return;
  }
  if(cur>0){
    const goTo=cur-1;
    if(goTo===0) _suppressG1Advance=true;  // G1 화면에서 자동 G2 전환 억제
    // HJ 2026-06-11 — 이전 단계로 가도 앞 단계 진행 결과(캐시·frontier·maxReached) 보존.
    //   다시 next 로 돌아와 이어서 진행할 수 있게. 하위 단계 폐기는 '재진행(doResume)' 누르는 순간에만 수행.
    cur=goTo; follow=false; render();
  }
};
document.getElementById('nextBtn').onclick=function(){ _suppressG1Advance=false; if(cur<maxReached){ cur++; if(cur>=frontier) follow=true; render(); } };
document.getElementById('stopBtn').onclick=function(){ navUnlocked=!navUnlocked; render(); };
document.getElementById('primaryBtn').onclick=function(){
  if(busy) return;
  if(paused){ paused=false; render(); if(analyzing()) startPolling(); return; }
  if(cur===0){ _suppressG1Advance=false; doUpload(); return; }
  if(cur>=1 && cur<=5){ doResume(); return; }
};
// ── F5 복원: localStorage 에 저장된 jobId 있으면 현재 단계 유지, API 폴링 재개 ──
// _FRESH_START=true 면 시작 버튼으로 진입 → 상태 초기화 후 업로드 화면
(function(){
  if(_FRESH_START){
    // 시작 버튼: 이전 데이터·해시 제거, ?flow=1 은 유지 (F5 시 플로우 화면 유지)
    try{ window.parent.history.replaceState({}, '', window.parent.location.pathname+'?flow=1'); }catch(e){}
    try{ window.parent.localStorage.removeItem(_SK); }catch(e){}
    render(); return;
  }
  var raw=_stateRead();
  try{
    var s=JSON.parse(raw||'null');
    if(s && s.jobId){
      jobId=s.jobId; fileId=s.fileId||null;
      cur=s.cur||1; maxReached=s.maxReached||cur; frontier=cur;
      // CS 2026-06-10 — G2 Sub-1 (주제 팝업) 상태 복원
      if(s.g2SubStage) g2SubStage=s.g2SubStage;
      if(s.selectedTopic) selectedTopic=s.selectedTopic;
      if(typeof s.topicCustomText==='string') topicCustomText=s.topicCustomText;
      if(s.g2DirectionsReady) g2DirectionsReady=s.g2DirectionsReady;
      render();  // 폴링 완료 전에 로딩 상태 즉시 렌더링
      startPolling(); return;
    }
  }catch(e){}
  render();
})();
</script></body></html>
"""


def _flow_screen() -> None:
    """확정 디자인 임베드(가운데 정렬 + 스크롤) + API 직접 연동."""
    st.markdown(
        """
        <style>
        /* 외부 배경을 랜딩 오버레이 색과 통일 — 97vh 틈새 어두운 띠 방지 */
        [data-testid="stAppViewContainer"] { background: #dbe7f6; }
        [data-testid="stHeader"] { display: none; }
        .block-container { max-width: 100% !important; padding: 0 !important; margin: 0 !important; }
        [data-testid="stMain"] .block-container { padding: 0 !important; margin: 0 !important; }
        [data-testid="stIFrame"] iframe, .block-container iframe {
            width: 100% !important; height: 100vh !important; border: 0; display: block;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    # 시작 버튼으로 진입 시 _FRESH_START=true 주입 → IIFE가 localStorage 초기화
    fresh = bool(st.session_state.pop("_fresh_start", False))
    flow_html = _FLOW_HTML.replace("__NONCE__", _FLOW_NONCE)
    if fresh:
        flow_html = flow_html.replace(
            "var _FRESH_START=false;// __FRESH_START_INJECT__",
            "var _FRESH_START=true;// __FRESH_START_INJECT__",
        )
    components.html(flow_html, height=900, scrolling=True)


# ===========================================================================
# 라우팅 — 랜딩 → 플로우
# ===========================================================================
# F5 새로고침 시 URL 쿼리 파라미터로 flow 상태 복원
# ── 처음으로 버튼 — 전체 세션 초기화 후 랜딩 복귀 ──
if st.query_params.get("reset") == "1":
    # HJ 2026-06-12 — 하위호환(혹시 남은 ?reset=1 URL). st.rerun() 제거:
    #   reload 직후 rerun 은 'SessionInfo before initialized' 에러를 유발한다.
    #   세션·쿼리만 정리하면 그대로 진행되어 studio_started 없음 → 아래에서 랜딩이 렌더된다.
    for k in list(st.session_state.keys()):
        del st.session_state[k]
    st.query_params.clear()

if st.query_params.get("flow") == "1":
    st.session_state["studio_started"] = True

if not st.session_state.get("studio_started"):
    # ── 스플래시(랜딩) ── (화면 세로 중앙 정렬, 히어로 이미지·폴백 공통)
    # F5 복원은 saveState() 가 URL 해시(#ada=…)에 상태를 기록하고,
    # F5 후 ?flow=1 이 URL 에 남아 Python 이 자동으로 플로우 화면을 보여주는 방식으로 처리.
    # (height=0 redirect iframe 제거 → Streamlit iframe 경고 감소)
    # HJ 2026-06-12 — 스플릿 대시보드 랜딩 (밝은 배경 · 모노크롬 A · 좌 텍스트 / 우 분석 대시보드).
    st.markdown(
        """
        <style>
        [data-testid="stAppViewContainer"]{background:#f4f6fa;}
        [data-testid="stHeader"]{background:transparent;}
        .block-container{min-height:calc(100vh - 4rem);max-width:1060px;
            display:flex;flex-direction:column;justify-content:center;}
        /* HJ 2026-06-12 — st.columns(vertical_alignment=) 는 1.36+ 전용. 1.35 호환 위해 CSS 로 세로 중앙 정렬. */
        [data-testid="stHorizontalBlock"]{align-items:center;}
        div.stButton > button{background:#2f6fed;color:#ffffff;border:none;border-radius:11px;
            font-weight:600;font-size:1.02rem;padding:.72rem 0;width:100%;
            box-shadow:0 12px 28px rgba(47,111,237,.28);transition:transform .12s,background .15s;}
        div.stButton > button:hover{background:#1f5fd8;transform:translateY(-1px);}
        </style>
        """,
        unsafe_allow_html=True,
    )
    _L, _R = st.columns([1.05, 0.95], gap="large")
    with _L:
        st.markdown(
            """
            <div style="text-align:left;">
              <div style="display:flex;align-items:center;gap:11px;">
                <svg width="40" height="40" viewBox="0 0 48 48" fill="none">
                  <path d="M10 38 L24 10 L38 38" stroke="#15273d" stroke-width="2.6" stroke-linejoin="round" stroke-linecap="round"/>
                  <path d="M16.5 30 L31.5 30" stroke="#15273d" stroke-width="2.6" stroke-linecap="round"/>
                </svg>
                <span style="font-size:1.7rem;font-weight:700;color:#15273d;">ada <span style="color:#2f6fed;">studio</span></span>
              </div>
              <div style="margin-top:14px;display:inline-block;background:#e8f1fe;color:#1d5fd6;font-size:.8rem;font-weight:600;letter-spacing:.06em;padding:5px 14px;border-radius:999px;">AI 데이터 분석 에이전트</div>
              <div style="color:#64718a;font-size:1rem;margin-top:22px;line-height:1.6;">숫자만 가득한 데이터 어떻게 처리해야 할지 막막하셨나요?<br>분석에 몇 주, 몇 달째 붙잡혀 계셨나요?<br>데이터를 분석하고 PPT, PDF 등으로 만드는데 골치 아프셨나요?</div>
              <div style="color:#2f6fed;font-size:1.2rem;font-weight:700;margin-top:18px;">이제, 끝났습니다!</div>
              <div style="font-size:2.45rem;font-weight:800;color:#15273d;line-height:1.24;margin-top:6px;">3명이,<br>3주 걸릴 프로젝트를,<br><span style="color:#2f6fed;">30분</span> 만에.</div>
              <div style="color:#6b7787;font-size:1.04rem;margin-top:14px;">몇 번의 선택이면, 원본 데이터가 <span style="color:#2f6fed;font-weight:700;">&ldquo;전문가 인사이트&rdquo;</span>로 바뀝니다.</div>
              <div style="color:#9aa6b5;font-size:.78rem;margin-top:12px;">(소요 시간은 데이터 규모에 따라 달라질 수 있습니다.)</div>
              <div style="height:20px;"></div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button("지금 시작하기", type="primary", use_container_width=True):
            st.session_state["studio_started"] = True
            st.session_state["_fresh_start"] = True
            st.query_params["flow"] = "1"
            st.rerun()
    with _R:
        st.markdown(
            """
            <div style="background:#ffffff;border:1px solid #e6ebf3;border-radius:18px;padding:22px;box-shadow:0 18px 44px rgba(31,55,99,.10);">
              <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:18px;">
                <span style="font-size:.95rem;font-weight:600;color:#15273d;">분석 리포트(예시)</span>
                <span style="background:#e3f7ef;color:#0f9d6a;font-size:.74rem;font-weight:600;padding:3px 11px;border-radius:999px;">● 완료</span>
              </div>
              <div style="display:flex;align-items:flex-end;gap:9px;height:104px;margin-bottom:18px;">
                <div style="flex:1;height:38%;background:#bcd5f7;border-radius:5px;"></div>
                <div style="flex:1;height:60%;background:#7faaf0;border-radius:5px;"></div>
                <div style="flex:1;height:46%;background:#bcd5f7;border-radius:5px;"></div>
                <div style="flex:1;height:78%;background:#4f8aec;border-radius:5px;"></div>
                <div style="flex:1;height:96%;background:#2f6fed;border-radius:5px;"></div>
              </div>
              <div style="display:flex;gap:10px;">
                <div style="flex:1;background:#e8f1fe;border-radius:11px;padding:12px 13px;">
                  <div style="color:#1d5fd6;font-size:1.5rem;font-weight:800;">94%</div>
                  <div style="color:#5a7596;font-size:.76rem;margin-top:2px;">예측 정확도</div>
                </div>
                <div style="flex:1;background:#efeafb;border-radius:11px;padding:12px 13px;">
                  <div style="color:#6d49c4;font-size:1.5rem;font-weight:800;">28</div>
                  <div style="color:#6a5e86;font-size:.76rem;margin-top:2px;">핵심 피처</div>
                </div>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
else:
    _flow_screen()
