"""frontend/app.py — ADA Studio (단일 플로우 UI).

1) 랜딩(스플래시) → Start
2) 업로드 → 5게이트(HITL) → 산출물 : 확정 디자인(다크 히어로·진행도 스텝퍼·카드)을
   임베드(components.html)하고, 임베드 안에서 브라우저가 ADA API(localhost:8000)에 직접
   fetch 로 연동. 게이트 추천(proposals)·분석 결과·현재 게이트는 GET /pipeline/gate/{job}
   (LangGraph state) 에서 받아 표시. 분석 중에는 로딩바·진행률·경과/예상시간 표시.
"""

from __future__ import annotations

import os

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
_FLOW_HTML = """
<!doctype html><html lang="ko"><head><meta charset="utf-8">
<style>
  @import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.min.css');
  :root{ --ink:#19395a; --deep:#1f3e5c; --muted:#52647d; --line:#d8e3f2; --line2:#cdddf0; }
  *{box-sizing:border-box;}
  html,body{margin:0;height:100%;}
  body{min-height:100%;background:linear-gradient(160deg,#2b4a6b 0%,#243f5c 58%,#1c3450 100%);
    font-family:'Pretendard','Inter',-apple-system,BlinkMacSystemFont,sans-serif;color:var(--ink);}
  .shell{width:100%;max-width:1440px;margin:0 auto;padding:34px 40px 48px;min-height:100%;
    display:flex;flex-direction:column;justify-content:center;zoom:1.25;}
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
  .footer{display:flex;align-items:center;gap:16px;margin-top:28px;padding-top:24px;border-top:1px solid #eef2f8;}
  .spacer{flex:1;}
  .btn{font-family:inherit;font-weight:600;border-radius:999px;cursor:pointer;font-size:24px;white-space:nowrap;display:inline-flex;align-items:center;gap:10px;}
  .btn-ghost{background:#fff;color:var(--deep);border:1px solid var(--line2);padding:15px 30px;}
  .btn-ghost:disabled{opacity:.4;cursor:default;color:#9aa9bd;}
  .btn-stop{background:#fff;color:#b5481f;border:1px solid #e7c8ba;padding:15px 28px;}
  .btn-primary{background:var(--deep);color:#fff;border:none;padding:18px 48px;box-shadow:0 13px 28px rgba(31,62,92,.26);}
  .btn-primary.resume{background:#1f7a52;}
  .btn-primary:disabled{opacity:.45;cursor:default;box-shadow:none;}
  .btn-new{font-family:inherit;font-size:15px;font-weight:600;border-radius:999px;cursor:pointer;
    background:rgba(255,255,255,.12);border:1px solid rgba(255,255,255,.28);color:#dce7f5;
    padding:7px 18px;margin-left:auto;margin-right:12px;white-space:nowrap;}
  .btn-new:hover{background:rgba(255,255,255,.20);}
  .btn-home{font-family:inherit;font-size:15px;font-weight:600;border-radius:999px;cursor:pointer;
    background:rgba(255,255,255,.12);border:1px solid rgba(255,255,255,.28);color:#dce7f5;
    padding:7px 18px;margin-left:14px;white-space:nowrap;}
  .btn-home:hover{background:rgba(255,255,255,.20);}
  /* HJ 2026-06-10 G1 분석 팝업 (revision 2) — G1 진입부터 G2 proposals 도착 전까지 표시. 모달 2배+. */
  .modal-overlay{position:fixed;inset:0;z-index:1000;display:flex;align-items:center;justify-content:center;padding:24px;background:rgba(20,30,50,.42);backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px);}
  .modal-card{position:relative;background:#fff;border-radius:32px;padding:56px 76px 48px;width:min(1300px,95%);max-height:88vh;overflow-y:auto;box-shadow:0 40px 100px rgba(0,0,0,.55);animation:modalIn .42s cubic-bezier(.2,.85,.25,1.2);}
  @keyframes modalIn{0%{transform:scale(.82) translateY(20px);opacity:0;}100%{transform:scale(1) translateY(0);opacity:1;}}
  .modal-title{font-size:60px;font-weight:800;color:var(--ink);text-align:center;margin:0 0 10px;line-height:1.1;}
  .modal-en{font-size:32px;color:#8aa0bd;font-style:italic;text-align:center;margin:0 0 32px;}
  .modal-card .progbox{margin-top:30px;}
  .modal-card .lbar{box-shadow:0 0 0 2px rgba(31,62,92,.10);}
  .modal-pending{background:#fffbeb;border:1px solid #fde68a;border-radius:16px;padding:22px 28px;margin-top:18px;}
  .modal-pending .t{font-weight:700;color:#92400e;margin-bottom:8px;font-size:28px;}
  .modal-pending .s{font-size:22px;color:#7c5012;line-height:1.4;}
  .modal-placeholder{text-align:center;padding:36px 0;color:#52647d;font-size:26px;}
  /* HJ 2026-06-10 — 마일스톤 세그먼트 바. 각 segment = 단계의 한 agent. 완료/현재/대기 색상 구분. */
  .ms-bar{display:flex;width:100%;height:48px;background:#eef2f8;border-radius:12px;overflow:hidden;border:1px solid #d8e3f2;max-width:760px;margin:0 auto;}
  .ms-seg{flex:1;display:flex;align-items:center;justify-content:center;padding:0 10px;font-size:14px;font-weight:600;color:#7e98ba;border-right:1px solid rgba(255,255,255,.6);transition:background .35s,color .35s;text-overflow:ellipsis;overflow:hidden;white-space:nowrap;min-width:0;line-height:1.2;}
  .ms-seg:last-child{border-right:none;}
  .ms-seg-icon{margin-right:6px;font-weight:800;}
  .ms-seg.done{background:#1f7a52;color:#fff;}
  .ms-seg.active{background:linear-gradient(90deg,#1f3e5c,#2c5783);color:#fff;animation:msPulse 1.6s ease-in-out infinite;}
  .ms-seg.pending{background:#f7faff;color:#8aa0bd;}
  @keyframes msPulse{0%,100%{box-shadow:inset 0 0 0 0 rgba(255,255,255,0);}50%{box-shadow:inset 0 0 0 100px rgba(255,255,255,.10);}}
  .modal-card .ms-bar{height:64px;border-radius:14px;max-width:none;}
  .modal-card .ms-seg{font-size:18px;padding:0 16px;}
  @media(max-width:1100px){ .opts,.res .grid2{grid-template-columns:1fr;} }
</style></head><body>
  <!-- 랜딩 오버레이 — G1 이전 단계 클릭 시 표시. 원본 Python 랜딩과 동일한 스타일 -->
  <div id="landingOverlay" style="display:none;position:fixed;top:0;left:0;width:100%;height:100%;
    z-index:9999;background:#dbe7f6;flex-direction:column;align-items:center;justify-content:center;
    overflow-y:auto;padding:40px 20px;font-family:'Pretendard','Inter',-apple-system,sans-serif;">
    <!-- 히어로 카드 (원본 ada_hero.png 대체 — Python fallback 과 동일한 스타일) -->
    <div style="max-width:960px;width:100%;border-radius:34px;padding:80px 64px;
      background:linear-gradient(160deg,#2b4a6b 0%,#3f5d7e 100%);color:#e6eef8;text-align:center;
      box-shadow:0 32px 80px rgba(31,62,92,.34);margin-bottom:44px;">
      <div style="font-size:18px;letter-spacing:.30em;opacity:.85;font-weight:600">ADAPTIVE&nbsp;&nbsp;DATA&nbsp;&nbsp;ANALYST</div>
      <div style="font-size:160px;line-height:1.0;margin:24px 0 4px">🌐</div>
    </div>
    <!-- 텍스트 + 버튼 -->
    <div style="text-align:center;">
      <div style="font-size:72px;font-weight:800;color:#19395a;margin:0 0 18px">ADA Studio</div>
      <div style="font-size:24px;color:#52647d;margin:0 0 40px">다섯 번의 선택으로, 데이터를 전문가 수준 인사이트로!</div>
      <button onclick="startFromLanding()" style="font-family:inherit;font-size:20px;font-weight:600;
        border:none;border-radius:999px;cursor:pointer;background:#1f3e5c;color:#fff;
        padding:.7rem 2.4rem;box-shadow:0 10px 24px rgba(31,62,92,.28)">✦&nbsp;&nbsp;시작</button>
    </div>
  </div>
  <div class="shell">
    <div class="brand"><span class="globe">🌐</span><span class="nm">ADAPTIVE&nbsp;&nbsp;DATA&nbsp;&nbsp;ANALYST</span><span class="status" id="status">대기</span><button class="btn-home" id="homeBtn" onclick="goToStart()">← 처음으로</button></div>
    <div class="steps" id="steps"></div>
    <div class="prog-meta">현재 단계 <b id="curName">업로드</b> · 진행 <b id="curPct">0%</b> (<span id="curIdx">1</span>/<span id="curTot">7</span>)</div>
    <div class="card"><div class="content" id="content"></div>
      <div class="footer">
        <button class="btn btn-ghost" id="prevBtn">← 이전 단계</button>
        <button class="btn btn-ghost" id="nextBtn">다음 단계 →</button>
        <span class="spacer"></span>
        <button class="btn btn-stop" id="stopBtn">⏸ 멈춤</button>
        <button class="btn btn-primary" id="primaryBtn">⬆ 업로드</button>
      </div>
    </div>
  </div>
  <!-- HJ 2026-06-10 G1→G2 전환 팝업 모달 — render() 가 inModalLoading() 기반으로 표시·숨김 제어. 배경 자동 blur. -->
  <div id="modalOverlay" class="modal-overlay" style="display:none">
    <div class="modal-card" id="modalCard"></div>
  </div>
<!-- HJ 2026-06-09 G1 단축 Phase 4 — client-side 파일 파싱 (PapaParse: CSV, SheetJS: XLSX) -->
<script src="https://cdnjs.cloudflare.com/ajax/libs/PapaParse/5.4.1/papaparse.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/xlsx/0.18.5/xlsx.full.min.js"></script>
<script>
const steps=[{label:'업로드',sub:'G1 · 데이터 파악'},{label:'분석 방향',sub:'G2 · EDA'},{label:'방법론',sub:'G3 · 전처리'},{label:'모델 전략',sub:'G4 · 피처링'},{label:'모델 선택',sub:'G5 · 학습·평가'},{label:'산출물',sub:'G6 · 리포트'},{label:'완료',sub:'G7 · 인사이트'}];
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
const API=(function(){ let p='http:',h='localhost'; try{ p=window.parent.location.protocol; h=window.parent.location.hostname; }catch(e){} if(p!=='http:'&&p!=='https:')p='http:'; if(!h)h='localhost'; return p+'//'+h+':8000'; })();
let cur=0, frontier=0, maxReached=0, paused=false, follow=true, busy=false, polling=false, pollTimer=null;
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
let lastSubmittedGate=null;  // resume 후 이 게이트가 사라질 때까지 계속 폴링
let g5Checked={};  // G6 멀티선택 상태 {proposal_id: bool}
let gateCache={};  // {G2: gateData, G3: gateData, ...} — 이전 단계 뒤로가기 시 재표시용
let _sawAnalyzingAfterSubmit=false;  // resume 후 analyzing() 상태를 거쳤는지 — stale gate 차단

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
  var d=JSON.stringify({jobId:jobId,fileId:fileId,cur:cur,maxReached:maxReached});
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
  try{ if(pollTimer){ clearTimeout(pollTimer); pollTimer=null; } }catch(e){}
  try{ clearState(); }catch(e){}
  try{ window.parent.localStorage.removeItem(_SK); }catch(e){}
  try{ window.parent.history.replaceState({}, '', window.parent.location.pathname); }catch(e){}
  try{
    window.parent.location.href = window.parent.location.origin + window.parent.location.pathname + '?reset=1';
  }catch(e){
    window.location.reload();
  }
}
function resetAll(){
  clearState();
  jobId=null; fileId=null; cur=0; frontier=0; maxReached=0;
  paused=false; follow=true; busy=false; polling=false;
  if(pollTimer){ clearTimeout(pollTimer); pollTimer=null; }
  status={}; gateData={}; selId=null; selectedFile=null;
  intentText=''; errMsg=''; analyzeStart=null; animatedGate=null;
  gateCache={}; lastSubmittedGate=null; selGate=null; g5Checked={};
  _progressKey=null; _shownPct=0; _sawAnalyzingAfterSubmit=false; _stageStart=null; _barFlowPct=0;
  render();
}
const AGENT_KO={supervisor:'작업 분류',intent_elicitor:'분석 의도 파악',data_profiler:'데이터 프로파일링',schema_validator:'스키마 검증',gate_direction:'분석 방향 제안 생성',eda_agent:'탐색적 분석(EDA)',gate_methodology:'방법론 제안',preprocessing_strategist:'전처리 전략',feature_engineer:'피처 엔지니어링',gate_model_strategy:'모델 전략 제안',model_selection:'모델 선택',hyperparameter_tuner:'하이퍼파라미터 튜닝',training_executor:'모델 학습',training_monitor:'학습 모니터링',metrics_aggregator:'지표 집계',gate_best_model:'최적 모델 선정',eval_agent:'평가',explainability:'설명가능성',insight:'인사이트 생성',gate_outputs:'산출물 선택',report_composer:'리포트 생성',
  G2:'분석 방향 제안 완료',G3:'방법론 제안 완료',G4:'모델 전략 제안 완료',G5:'최적 모델 선정 완료',G6:'산출물 선택 완료',
  error_recovery:'오류 복구 중',self_learning_dispatch:'학습 결과 저장 중'};
// HJ 2026-06-10 — 마일스톤 진행률용 단계별 agent 흐름. orchestrator/runner.py STAGE_AGENTS 와 동기.
// cur(UI 인덱스) → 실제 backend stage:
//   cur=0,1 → G1 (cur=1 은 Z' 단축으로 UI 만 먼저 전환, backend 는 gate_direction 마무리 중)
//   cur=2~5 → G2~G5 (cur=N 의 loading 은 backend stage G(N) agents 실행 중)
const STAGE_AGENT_FLOW={
  G1:['supervisor','intent_elicitor','data_profiler','schema_validator','gate_direction'],
  G2:['eda_agent','gate_methodology'],
  G3:['preprocessing_strategist','feature_engineer','preprocessing_choice','gate_model_strategy'],
  G4:['model_selection','hyperparameter_tuner','training_executor','training_monitor','metrics_aggregator','gate_best_model'],
  G5:['fine_tune_executor','eval_agent','explainability','insight','gate_outputs']
};
function _curStageKey(){
  if(cur===0||cur===1) return 'G1';
  if(cur>=2 && cur<=5) return 'G'+cur;
  return null;
}
function _curAgentFlow(){
  const k=_curStageKey();
  return k?(STAGE_AGENT_FLOW[k]||[]):[];
}
function _curMilestoneIdx(){
  const flow=_curAgentFlow();
  const ca=gateData.current_agent;
  if(!flow.length||!ca) return -1;
  return flow.indexOf(ca);
}

function esc(s){ return String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
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
  const gate=tg;  // curGate() 대신 cur 기준 게이트 코드 사용
  errMsg=''; busy=true; render();
  try{
    await api('/pipeline/resume/'+jobId,{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({gate:gate,choice:choice})});
    lastSubmittedGate=gate;
    // 제출 게이트 이후 캐시 삭제 — 현재 게이트(tg) 캐시는 유지(뒤로가기 복원용)
    var _tgNum=parseInt(tg[1],10);
    Object.keys(gateCache).forEach(function(k){
      if(parseInt(k.slice(1),10)>_tgNum) delete gateCache[k];
    });
    cur=cur+1; maxReached=cur; frontier=cur;  // 다음 로딩 화면으로 즉시 이동
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
  // 백엔드 frontier 가 maxReached 보다 낮으면 이전 세션 stale 가능성 → 클램프.
  // (정상 뒤로가기: frontier=현재게이트 ≥ maxReached 이므로 클램프 안 됨)
  if(maxReached > frontier) maxReached=frontier;
  maxReached=Math.max(maxReached,frontier);
  // Phase 1 (2026-06-04 수정) — G1 데이터 파악 완료 신호만으로 cur 전환.
  // 백엔드가 G2 게이트 도달했는데 proposals 가 비어 있는 경우(LLM 응답 직전·직렬화 실패 등)에도
  // 클라이언트가 stuck 되지 않도록 proposals 조건 제거. G2 화면에서 contentGate 가 자체적으로
  // loading→옵션 전환을 처리한다. _shownPct 는 100 으로 보존하여 시각 단절 방지.
  // HJ 2026-06-09 G1 단축 Z' — schema_validator 가 g2_pending 신호 보내면
  // 진행률 무관하게 G2 화면 진입 (gate_direction 백그라운드 대기).
  if(cur===0 && jobId && !_suppressG1Advance && curGate()==='G2' && (_shownPct >= 99 || gateData.g2_pending===true)){
    cur=1; follow=true; _progressKey='G2';
    if(_shownPct < 99) _shownPct = Math.max(_shownPct, 10); // Z' 진입은 진행률 보존, 100% 강제 안 함
    else _shownPct=100;
  }
  if(follow) cur=frontier;
  cur=Math.max(0,Math.min(cur,frontier));
  if(analyzing()){ if(analyzeStart==null) analyzeStart=Date.now(); } else { analyzeStart=null; }
  saveState();
  render();
  // resume 직후 Celery가 아직 task를 못 받아 Redis에 이전 게이트가 남아있을 수 있음 →
  // lastSubmittedGate 와 현재 게이트가 같으면 계속 폴링.
  // 분석 중(curGate=null)에는 유지 — 새 게이트 등장 시에만 클리어.
  // 실패·완료 시 stale 가드 즉시 해제 — 이전 단계 캐시 proposals 복원 가능하게
  if(isFailed()||isCompleted()){ lastSubmittedGate=null; _sawAnalyzingAfterSubmit=false; }
  // resume 후 analyzing() 통과 확인 — stale gate_data 로 lastSubmittedGate 조기 클리어 방지
  if(lastSubmittedGate && analyzing()) _sawAnalyzingAfterSubmit=true;
  if(lastSubmittedGate && _sawAnalyzingAfterSubmit && curGate() && curGate()!==lastSubmittedGate) lastSubmittedGate=null;
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

// 0.5초 틱 — 진행률 보간 + G1→G2 자동 전환 안전망(polling 멈춤 후에도 보간 완료 시 cur 전환).
setInterval(function(){
  if(paused) return;
  // G1→G2 자동 전환: polling 이 멈춘 케이스에 대비해 매 500ms 도 조건 재확인.
  // HJ 2026-06-09 G1 단축 Z' — g2_pending=true 면 진행률 무관하게 전환 (schema_validator 직후).
  if(cur===0 && jobId && !_suppressG1Advance && curGate()==='G2' && (_shownPct >= 99 || gateData.g2_pending===true)){
    cur=1; follow=true;
    // _progressKey/_shownPct 를 여기서 세팅하지 않음 — _stageProgress() 가 key 불일치 감지 후
    // 자연스럽게 _shownPct=0 으로 리셋. G2 로딩 중에 100% 고정되는 버그 방지.
    saveState();
    render(); // 전환 직후 즉시 G2 화면 갱신 — 없으면 다음 poll(2.5s)까지 G1 stuck
    if(!polling) startPolling();
    return;
  }
  // jobId 없는 업로드 대기 화면에서는 타이머 렌더 생략 — textarea 포커스 보호
  if(!jobId && cur===0) return;
  if(analyzing() || _shownPct < 100 || (cur===0 && jobId)) render();
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
  const key=(isFailed()?'FAIL':(isCompleted()||cur===LAST)?'DONE':'G'+(cur+1));
  if(_progressKey!==key){
    _progressKey=key;
    _shownPct=0; _stageStart=Date.now(); _barFlowPct=0;
    _lastSignalAt=null; _lastSignalPct=null;
    _estimatedTotal=null; _completing=false; _estimatedFromEta=false;
  }
  if(isFailed()){ _barFlowPct=0; return 0; }
  if(isCompleted()||cur===LAST){ _shownPct=100; _barFlowPct=100; return 100; }
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
    // 팝업 로딩 중(proposals 미도착) → 99% 억제. proposals 도착 시 modal 닫히고 그 때 100%.
    // 완료 = 2단계로 실제 전환되는 시점. modal 닫힌 후에만 100%/'완료' 표시.
    const _cap=inModalLoading()?99:100;
    _shownPct=Math.min(_cap,_shownPct+10);
    _barFlowPct=_shownPct;
    return Math.round(_shownPct);
  }

  // HJ 2026-06-10 — 마일스톤 기반 진행률 (사용자 요구).
  // 현재 backend가 보고하는 current_agent 가 단계의 agent 리스트에서 몇 번째인지로 % 산출.
  // 예) G1 (5 agents): supervisor 실행 중 = 0%, intent 실행 중 = 20%, profiler = 40%,
  //                    schema = 60%, gate_direction = 80%. proposals 도착 = 100% (위 _completing 블록).
  // 데이터마다 분석 시간이 달라도 항상 정확. 시간 예측 일체 안 함.
  const flow=_curAgentFlow();
  const idx=_curMilestoneIdx();
  if(flow.length && idx>=0){
    const milestone=Math.round(idx*100/flow.length);
    if(milestone>_shownPct) _shownPct=milestone;
  }

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
  // stale 구간(resume 직후 analyzing 미확인)에는 이전 에이전트 라벨 숨김
  if(gateData.current_agent && !(lastSubmittedGate&&!_sawAnalyzingAfterSubmit)){
    agentLine='<div class="lagent">현재 작업: <b>'+esc(AGENT_KO[gateData.current_agent]||gateData.current_agent)+'</b></div>';
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
  return '<div class="loadwrap"><div class="loadtxt">🔄 데이터를 분석해 추천을 생성하는 중입니다…</div>'+agentLine+diag+'</div>';
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
function progressBar(){
  if(isFailed()) return '';
  if(cur===LAST) return '';                                       // G7 완료 페이지
  if(cur===0 && !jobId) return '';                                // 업로드 전
  if(cur>=1 && cur<=5 && !isGateLoading()) return '';             // proposals 표시 중
  const p=_stageProgress();
  const stageEl=_stageStart?((Date.now()-_stageStart)/1000):0;
  const isRunning=analyzing()||isGateLoading();

  // 마일스톤 세그먼트 — 단계의 agent 리스트가 곧 바의 구조.
  const flow=_curAgentFlow();
  let activeIdx=_curMilestoneIdx();
  if(_completing||p>=100) activeIdx=flow.length;  // 완료 시 모든 칸 done
  let barHtml='';
  if(flow.length){
    const segs=flow.map(function(ag,i){
      let cls='ms-seg';
      let icon;
      if(i<activeIdx){ cls+=' done'; icon='✓'; }
      else if(i===activeIdx){ cls+=' active'; icon='●'; }
      else { cls+=' pending'; icon=(i+1)+'.'; }
      const name=esc(AGENT_KO[ag]||ag);
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
  const tt=GATE_TITLE[g]||['추천을 검토하세요','Review the recommendation'];
  const cat=(gateData.category && gateData.category!=='pending')?('<span>카테고리 <b>'+esc(gateData.category)+'</b></span>'):'';
  const tgt=gateData.target_column?('<span>타깃 <b>'+esc(gateData.target_column)+'</b></span>'):'';
  return '<div class="ahdr"><h2>'+tt[0]+'</h2><div class="en">'+tt[1]+'</div></div>'
    +'<p class="desc">업로드하신 데이터를 ADA가 분석해 제안한 결과입니다.</p>'
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
  const rat=esc(p.rationale||'').replace(/\\n/g,'<br><br>');
  return '<div class="opt'+sel+'" data-pid="'+esc(p.id)+'"><div class="ck">✓</div><div class="onum">OPTION 0'+(idx+1)+rec+'</div><h3>'+esc(p.title||('제안 '+p.id))+'</h3><p>'+rat+'</p>'+extra+score+'</div>';
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
      +cmKeys.map(function(k){return '<div style="background:#fff;padding:6px 8px;border-radius:4px;border:1px solid #e2e8f0"><b>'+esc(k)+'</b> &nbsp;<span style="opacity:.75">'+esc(String(cm[k]))+'</span></div>';}).join('')
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

// HJ 2026-06-10 G1 분석 팝업 (revision 2) — G1 시작(jobId 셋)부터 G2 proposals 도착 전까지 모달 유지.
// 진행 단계와 무관하게 분석 내용 표시 시점부터(=업로드 직후) 노출. 모달이 본문 내용을 대체.
function inModalLoading(){
  if(!jobId) return false;
  if(isFailed()) return false;
  if(isCompleted()) return false;
  if(cur===0){
    // 도메인 데이터 도착 시부터 팝업. proposals 이미 도착했으면 false — 완료 오표시 방지.
    if(!g2TopicArea(gateData)) return false;
    const _p0=(gateData.proposals||[]).filter(function(p){return !p.is_custom;});
    if(_p0.length && curGate()==='G2') return false;
    return true;
  }
  if(cur===1){               // G2 대기 — proposals 도착 전까지 표시
    const tg='G2';
    const ag=curGate();
    const _staleRun=!!(lastSubmittedGate&&!_sawAnalyzingAfterSubmit);
    const d=_staleRun?{}:((ag===tg)?gateData:(analyzing()?{}:(gateCache[tg]||{})));
    const llmProps=(d.proposals||[]).filter(function(p){return !p.is_custom;});
    return !llmProps.length;
  }
  return false;
}
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
  const cmKeys=Object.keys(cm).slice(0,12);
  if(cmKeys.length){
    cmHtml='<div style="margin-top:22px"><div style="font-size:22px;opacity:.7;margin-bottom:12px">컬럼 의미 ('+cmKeys.length+(Object.keys(cm).length>12?'/'+Object.keys(cm).length:'')+')</div>'
      +'<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(380px,1fr));gap:12px;font-size:22px">'
      +cmKeys.map(function(k){return '<div style="background:#fff;padding:14px 18px;border-radius:8px;border:1px solid #e2e8f0"><b>'+esc(k)+'</b> &nbsp;<span style="opacity:.75">'+esc(String(cm[k]))+'</span></div>';}).join('')
      +'</div></div>';
  }
  return '<div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:14px;padding:30px 36px;margin-bottom:20px">'
    +'<div style="font-weight:700;color:#0f172a;margin-bottom:18px;font-size:32px">📌 주제 선정 — 데이터 도메인</div>'
    +(domain?'<div style="font-size:28px"><span style="opacity:.7">도메인</span> &nbsp;<b>'+esc(domain)+'</b></div>':'')
    +(summary?'<div style="margin-top:14px;font-size:26px;line-height:1.5"><span style="opacity:.7">데이터셋</span> &nbsp;'+esc(summary)+'</div>':'')
    +(tInsight?'<div style="margin-top:14px;font-size:26px;line-height:1.5"><span style="opacity:.7">타깃 인사이트</span> &nbsp;'+esc(tInsight)+'</div>':'')
    +cmHtml
    +'</div>';
}
// 모달 내부 컨텐츠 — 큰 타이틀 + modalTopicArea + 단계별 안내. 진행바는 카드 본문에 그대로 두고 모달에서 제외(사용자 요구).
function modalHtml(){
  const tg='G2';
  const ag=curGate();
  const d=(cur===0||ag===tg)?gateData:(gateCache[tg]||{});
  const topic=modalTopicArea(d);
  let body='';
  if(errMsg) body+='<div class="err">⚠ '+esc(errMsg)+'</div>';
  body+='<div class="modal-title">데이터를 분석하고 있습니다</div>';
  body+='<div class="modal-en">Analyzing your data…</div>';
  if(topic){
    body+=topic;
  } else {
    body+='<div class="modal-placeholder">📊 데이터 도메인을 분석하는 중입니다…</div>';
  }
  // 단계별 진행 안내
  if(cur===0){
    const ca=gateData.current_agent;
    const lab=ca?(AGENT_KO[ca]||ca):'';
    if(lab){
      body+='<div class="modal-pending"><div class="t">🔄 현재 작업: '+esc(lab)+'</div>'
        +'<div class="s">데이터 출처·스키마·도메인·품질 점검 등을 진행하고 있습니다.</div></div>';
    } else {
      body+='<div class="modal-pending"><div class="t">🔄 데이터 파악 진행 중…</div>'
        +'<div class="s">곧 도메인 분석 결과가 표시됩니다.</div></div>';
    }
  } else {
    body+='<div class="modal-pending"><div class="t">🔄 분석 방향 카드 생성 중…</div>'
      +'<div class="s">잠시만 기다려 주세요. 추천 카드가 곧 표시됩니다.</div></div>';
  }
  // 사용자 요청 — 진행바는 모달 내부에 그대로 유지 (이슈 4 수정 안 함).
  body+=progressBar();
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
  // HJ 2026-06-09 G1 단축 Z' — G2 에서 proposals 없을 때 (gate_direction 진행 중)
  // "주제 선정" 영역 먼저 표시 + 분석 방향 영역엔 spinner.
  if(g==='G2' && !props.length && d.g2_pending){
    // 팝업(inModalLoading)이 활성일 때는 팝업에서만 표시 — 인라인 중복 제거
    if(inModalLoading()) return gateHeader(g)+loadingBlock();
    const topic=g2TopicArea(d);
    return gateHeader(g)+topic
      +'<div style="background:#fffbeb;border:1px solid #fde68a;border-radius:8px;padding:14px 16px;margin-bottom:10px">'
      +'<div style="font-size:18px;font-weight:600;color:#92400e;margin-bottom:6px">🔄 분석 방향 카드 생성 중…</div>'
      +'<div style="font-size:18px;opacity:.8">위 도메인 정보를 보면서 어떤 분석을 원하시는지 떠올려 보세요. 곧 추천 카드가 표시됩니다.</div>'
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
  // HJ 2026-06-09 G1 단축 Z' — G2 에선 카드 위에 "주제 선정" 영역 함께 표시.
  const topicArea = (g==='G2') ? g2TopicArea(d) : '';
  // G6 (산출물 선택) 화면은 산출물 카드만 표시 — 최적 모델·평가 결과 박스 숨김
  return gateHeader(g)+topicArea+'<div class="opts'+pop+'">'+cards+'</div>';
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
  if(cur>=1 && cur<=5 && cur<frontier) return '🔄 재진행 ▸';
  return '진행 ▸';
}
function render(){
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

  // 1~7 모든 단계 공통: 본문 + 진행바 (실패 시 progressBar() 내부에서 빈 문자열 반환).
  // 사용자 요구로 진행바 변경은 일체 손대지 않음 — 모달 안/밖 모두 기존 동작 유지.
  document.getElementById('content').innerHTML=
    (errMsg?('<div class="err">⚠ '+esc(errMsg)+'</div>'):'')+content(cur)+progressBar();
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

  const prev=document.getElementById('prevBtn'), next=document.getElementById('nextBtn'),
        stop=document.getElementById('stopBtn'), prim=document.getElementById('primaryBtn');
  prev.disabled=false;  // cur=0 에서도 활성 — 클릭 시 시작 화면으로
  prev.innerHTML=(cur===0)?'← 시작 화면':'← 이전 단계';
  next.disabled=(cur>=maxReached);
  stop.style.display=(!paused && analyzing())?'inline-flex':'none';
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
  // HJ 2026-06-10 G1→G2 전환 팝업 토글 — inModalLoading() 동안 modal 표시, 끝나면 자동 숨김.
  // backdrop-filter:blur 로 배경 카드·스텝 자동 흐림. 모달 내부 progressBar 만 선명.
  const _modalOv=document.getElementById('modalOverlay');
  if(_modalOv){
    if(inModalLoading()){
      document.getElementById('modalCard').innerHTML=modalHtml();
      _modalOv.style.display='flex';
    } else {
      _modalOv.style.display='none';
    }
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
    if(goTo>=1 && goTo<=4 && maxReached>goTo){
      Object.keys(gateCache).forEach(function(k){ if(parseInt(k.slice(1),10)>goTo+1) delete gateCache[k]; });
      maxReached=goTo; frontier=goTo;
    }
    cur=goTo; follow=false; render();
  }
};
document.getElementById('nextBtn').onclick=function(){ _suppressG1Advance=false; if(cur<maxReached){ cur++; if(cur>=frontier) follow=true; render(); } };
document.getElementById('stopBtn').onclick=function(){ paused=true; if(pollTimer) clearTimeout(pollTimer); polling=false; render(); };
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
    flow_html = (
        _FLOW_HTML.replace(
            "var _FRESH_START=false;// __FRESH_START_INJECT__",
            "var _FRESH_START=true;// __FRESH_START_INJECT__",
        )
        if fresh
        else _FLOW_HTML
    )
    components.html(flow_html, height=900, scrolling=True)


# ===========================================================================
# 라우팅 — 랜딩 → 플로우
# ===========================================================================
# F5 새로고침 시 URL 쿼리 파라미터로 flow 상태 복원
# ── 처음으로 버튼 — 전체 세션 초기화 후 랜딩 복귀 ──
if st.query_params.get("reset") == "1":
    for k in list(st.session_state.keys()):
        del st.session_state[k]
    st.query_params.clear()
    st.rerun()

if st.query_params.get("flow") == "1":
    st.session_state["studio_started"] = True

if not st.session_state.get("studio_started"):
    # ── 스플래시(랜딩) ── (화면 세로 중앙 정렬, 히어로 이미지·폴백 공통)
    # F5 복원은 saveState() 가 URL 해시(#ada=…)에 상태를 기록하고,
    # F5 후 ?flow=1 이 URL 에 남아 Python 이 자동으로 플로우 화면을 보여주는 방식으로 처리.
    # (height=0 redirect iframe 제거 → Streamlit iframe 경고 감소)
    st.markdown(
        """
        <style>
        .block-container {
            min-height: calc(100vh - 4rem);
            display: flex; flex-direction: column; justify-content: center;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    if os.path.exists(_HERO):
        st.image(_HERO, use_column_width=True)
    else:
        st.markdown(
            """
            <div style="max-width:960px;margin:0 auto;border-radius:34px;padding:104px 64px;
                        background:linear-gradient(160deg,#2b4a6b 0%,#3f5d7e 100%);color:#e6eef8;text-align:center;
                        box-shadow:0 32px 80px rgba(31,62,92,.34)">
              <div style="font-size:20px;letter-spacing:.30em;opacity:.85;font-weight:600">ADAPTIVE&nbsp;&nbsp;DATA&nbsp;&nbsp;ANALYST</div>
              <div style="font-size:200px;line-height:1.0;margin:28px 0 6px">🌐</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    st.markdown(
        """
        <div style="text-align:center;margin-top:44px">
          <div style="font-size:76px;font-weight:800;color:#19395a">ADA Studio</div>
          <div style="font-size:26px;color:#52647d;margin-top:18px">
            다섯 번의 선택으로, 데이터를 전문가 수준 인사이트로!</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.write("")
    _bc = st.columns([2, 1, 2])
    with _bc[1]:
        if st.button("✦  시작", type="primary", use_container_width=True):
            st.session_state["studio_started"] = True
            st.session_state["_fresh_start"] = True  # localStorage 초기화 후 업로드 화면으로
            st.query_params["flow"] = "1"
            st.rerun()
else:
    _flow_screen()
