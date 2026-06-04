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
    display:flex;flex-direction:column;justify-content:center;}
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
  @media(max-width:1100px){ .opts,.res .grid2{grid-template-columns:1fr;} }
</style></head><body>
  <div class="shell">
    <div class="brand"><span class="globe">🌐</span><span class="nm">ADAPTIVE&nbsp;&nbsp;DATA&nbsp;&nbsp;ANALYST</span><button class="btn-new" id="newBtn" style="display:none" onclick="resetAll()">＋ 새 분석</button><span class="status" id="status">대기</span></div>
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
<script>
const steps=[{label:'업로드',sub:'G1 · 데이터 파악'},{label:'분석 방향',sub:'G2 · EDA'},{label:'방법론',sub:'G3 · 전처리'},{label:'모델 전략',sub:'G4 · 피처링'},{label:'모델 선택',sub:'G5 · 학습·평가'},{label:'산출물',sub:'G6 · 리포트'},{label:'완료',sub:'G7 · 인사이트'}];
const N=steps.length, LAST=N-1;
const ANALYZE_EST=45;  // 분석 중 진행률 추정용(초)
const GATE_TITLE={G1:['어떤 방식으로 분석할까요?','Choose your analysis direction'],G2:['어떤 방법론으로 진행할까요?','Choose your methodology'],G3:['어떤 모델 전략을 쓸까요?','Choose your model strategy'],G4:['어떤 모델을 채택할까요?','Pick the best model'],G5:['어떤 산출물을 만들까요?','Choose your outputs']};
const API=(function(){ let p='http:',h='localhost'; try{ p=window.parent.location.protocol; h=window.parent.location.hostname; }catch(e){} if(p!=='http:'&&p!=='https:')p='http:'; if(!h)h='localhost'; return p+'//'+h+':8000'; })();
let cur=0, frontier=0, maxReached=0, paused=false, follow=true, busy=false, polling=false, pollTimer=null;
let jobId=null, fileId=null, selectedFile=null, intentText='', status={}, errMsg='';
let gateData={}, selId=null, selGate=null, customText='', analyzeStart=null, animatedGate=null;
let lastSubmittedGate=null;  // resume 후 이 게이트가 사라질 때까지 계속 폴링
let g5Checked={};  // G5 멀티선택 상태 {proposal_id: bool}
let gateCache={};  // {G1: gateData, G2: gateData, ...} — 이전 단계 뒤로가기 시 재표시용

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
  if(isCompleted() || isFailed()){ clearState(); return; }
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
function resetAll(){
  clearState();
  jobId=null; fileId=null; cur=0; frontier=0; maxReached=0;
  paused=false; follow=true; busy=false; polling=false;
  if(pollTimer){ clearTimeout(pollTimer); pollTimer=null; }
  status={}; gateData={}; selId=null; selectedFile=null;
  intentText=''; errMsg=''; analyzeStart=null; animatedGate=null;
  var nb=document.getElementById('newBtn'); if(nb) nb.style.display='none';
  render();
}
const AGENT_KO={supervisor:'작업 분류',intent_elicitor:'분석 의도 파악',data_profiler:'데이터 프로파일링',schema_validator:'스키마 검증',gate_direction:'분석 방향 제안 생성',eda_agent:'탐색적 분석(EDA)',gate_methodology:'방법론 제안',preprocessing_strategist:'전처리 전략',feature_engineer:'피처 엔지니어링',gate_model_strategy:'모델 전략 제안',model_selection:'모델 선택',hyperparameter_tuner:'하이퍼파라미터 튜닝',training_executor:'모델 학습',training_monitor:'학습 모니터링',metrics_aggregator:'지표 집계',gate_best_model:'최적 모델 선정',eval_agent:'평가',explainability:'설명가능성',insight:'인사이트 생성',gate_outputs:'산출물 선택',report_composer:'리포트 생성'};

function esc(s){ return String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
function fmtTime(s){ s=Math.max(0,Math.round(s)); const m=Math.floor(s/60), ss=s%60; return m+':'+(ss<10?'0':'')+ss; }
function curGate(){ const g=(gateData.gate)||(status.current_gate); return (g && /^G[1-5]$/.test(g))?g:null; }
function hasResults(){ return !!((gateData.output_paths && Object.keys(gateData.output_paths).length) || gateData.insights || gateData.eval_result || gateData.best_model); }
function isFailed(){ return (gateData.pipeline_status==='failed') || (status.status==='failed'); }
function isCompleted(){
  // 백엔드 status 를 우선 — 세 번째 fallback 조건은 G5 이후 최종 결과가 모두 갖춰진 경우만 허용.
  // (jobId && !curGate() && hasResults()) 만으로는 분석 중간에도 true 가 되어
  // clearState() 가 호출되므로, 반드시 pipeline_status 확인을 추가한다.
  if(['completed','succeeded','success'].includes(status.status)) return true;
  if(gateData.pipeline_status==='completed') return true;
  return false;
}
function analyzing(){ return !!(jobId && !curGate() && !isCompleted() && !isFailed()); }
function computeFrontier(){
  if(isCompleted()){ frontier=LAST; return; }
  const g=curGate();
  frontier = g ? (+g[1]) : (jobId?1:0);
}
async function api(path, opts){
  const r=await fetch(API+path, opts||{});
  const txt=await r.text();
  if(!r.ok) throw new Error('HTTP '+r.status+' '+txt.slice(0,180));
  return txt ? JSON.parse(txt) : {};
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
    // Phase 1 — G0 데이터 파악 단계 유지. cur=0 으로 두고 follow=false 로 자동 전환 방지.
    // G1 proposals 도착 시점에 poll() 안에서 명시적으로 cur=1 전환 + follow=true 부여.
    jobId=stt.job_id; follow=false; cur=0; frontier=0; maxReached=0; busy=false;
    gateData={}; analyzeStart=Date.now();
    saveState();
    startPolling();
  }catch(e){ errMsg='업로드/시작 실패 — '+e.message; busy=false; render(); }
}
async function doResume(){
  const tg='G'+cur;
  const ag=curGate();
  // cur 기준으로 올바른 proposals 선택 (이전 단계 재진행 시 캐시 사용)
  const d=(ag===tg)?gateData:(gateCache[tg]||{});
  const props=(d.proposals)||[];
  let choice;
  if(curGate()==='G5'){
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
    // 이전 단계 재진행: 이후 게이트 캐시와 frontier 초기화
    if(cur < maxReached){
      Object.keys(gateCache).forEach(function(k){
        if(parseInt(k.slice(1),10)>cur) delete gateCache[k];
      });
      frontier=cur; maxReached=cur;
    }
    // selId 를 초기화하지 않음 — 제출 직후 poll 이 돌아와도 선택이 옵션1로 리셋되지 않도록
    follow=true; busy=false; gateData={}; analyzeStart=Date.now();
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
  computeFrontier(); maxReached=Math.max(maxReached,frontier);
  // Phase 1 — G0 데이터 파악 완료(=백엔드가 G1 게이트 도달 + proposals 보유) + 클라이언트
  // 표시 진행률이 99% 이상 도달한 시점에 cur=0 → cur=1 자동 전환.
  // _shownPct 가 99 미만이면 _stageProgress 의 보간이 끝날 때까지 cur=0 화면을 유지하여,
  // 사용자가 "G0 100% 표시 → G1 전환" 시퀀스를 시각적으로 끝까지 본다.
  if(cur===0 && jobId && curGate()==='G1'
      && (gateData.proposals||[]).filter(function(p){return !p.is_custom;}).length
      && _shownPct >= 99){
    cur=1; follow=true;
  }
  if(follow) cur=frontier;
  cur=Math.max(0,Math.min(cur,frontier));
  if(analyzing()){ if(analyzeStart==null) analyzeStart=Date.now(); } else { analyzeStart=null; }
  saveState();
  render();
  // resume 직후 Celery가 아직 task를 못 받아 Redis에 이전 게이트가 남아있을 수 있음 →
  // lastSubmittedGate 와 현재 게이트가 같으면 계속 폴링, 달라지면(새 게이트 or null) 클리어
  if(lastSubmittedGate && curGate()!==lastSubmittedGate) lastSubmittedGate=null;
  const keepPolling=(analyzing() || !!lastSubmittedGate) && !paused;
  if(keepPolling){ pollTimer=setTimeout(poll, 2500); }
  else { polling=false; }
}
function startPolling(){ if(polling){ render(); return; } polling=true; clearTimeout(pollTimer); poll(); }

// 0.5초 틱 — 진행률 보간을 더 부드럽게. 분석 종료 후에도 _shownPct 가 100% 에 도달할 때까지 계속 그린다.
setInterval(function(){
  if(paused) return;
  if(analyzing() || _shownPct < 100) render();
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
function _stageProgress(){
  const key=(isFailed()?'FAIL':(isCompleted()||cur===LAST)?'DONE':'G'+cur);
  if(_progressKey!==key){ _progressKey=key; _shownPct=0; }
  if(isFailed()) return 0;
  if(isCompleted()||cur===LAST){ _shownPct=100; return 100; }
  if(cur===0 && !jobId){ _shownPct=0; return 0; }
  // 목표 진행률 계산
  let target;
  if(cur===0){
    // Phase 1 — G0 데이터 파악 단계는 백엔드 진행률 0~18% 를 0~95% 로 정규화.
    // G1 게이트(proposals 도착) 진입 = G0 완전 종료 → 100% 로 점프(잠시 후 cur=1 전환).
    const g1Reached = curGate()==='G1' && (gateData.proposals||[]).filter(function(p){return !p.is_custom;}).length;
    if(g1Reached){
      target=100;
    } else {
      const raw=(gateData.progress_pct!=null)?gateData.progress_pct:_shownPct;
      // G0 의 백엔드 진행률 천장 = 18 (AGENT_PHASE_MAP 의 gate_direction 시작). 정규화.
      target=Math.min(95, Math.round((raw/18)*95));
    }
  } else {
    // 게이트 단계(G1~G5): proposals 도착=100%, 아니면 백엔드 progress_pct 그대로.
    const tg='G'+cur;
    const ag=curGate();
    const d=(ag===tg)?gateData:(gateCache[tg]||{});
    const ps=((d.proposals)||[]).filter(function(p){return !p.is_custom;});
    if(ps.length){
      target=100;
    } else {
      target=(gateData.progress_pct!=null)?gateData.progress_pct:_shownPct;
    }
  }
  // 점프 보간 — 매 호출(500ms) 최대 step. 작은 차이는 즉시, 큰 점프(예: 30→100)는 약 2초간 부드럽게.
  if(target>_shownPct){
    const diff=target-_shownPct;
    const step=Math.max(2, Math.ceil(diff/4));
    _shownPct=Math.min(target, _shownPct+step);
  }
  // 거꾸로 가지 않음(백엔드 일시 감소도 무시).
  return Math.round(_shownPct);
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
  if(gateData.current_agent){
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
// 공통 진행바 — 1~7 모든 단계에서 카드 하단에 동일하게 표시.
// 진행률은 _stageProgress() 가 단계 완료(proposals 도착·isCompleted)면 100% 강제 점프.
function progressBar(){
  if(isFailed()) return '';
  const p=_stageProgress();
  const el=analyzeStart?((Date.now()-analyzeStart)/1000):0;
  let etaStr='';
  if(p>=100){ etaStr='완료'; }
  else if(analyzing()){
    // ETA 는 elapsed × (남은%/현재%) 으로 외삽. 진행률이 너무 낮으면 표시 보류.
    if(p>=5) etaStr='약 '+fmtTime(Math.max(0, el*(100-p)/p));
    else etaStr='추정 중…';
  }
  const showMeta=analyzing() || p>=100;
  let meta='';
  if(showMeta){
    meta='<div class="lmeta">진행 <b>'+p+'%</b>'
      +(analyzing()?(' · 분석 시간 <b>'+fmtTime(el)+'</b> · 예상 남은 시간 <b>'+etaStr+'</b>'):(p>=100?' · <b>'+etaStr+'</b>':''))
      +'</div>';
  } else {
    meta='<div class="lmeta">진행 <b>'+p+'%</b></div>';
  }
  return '<div class="progbox"><div class="lbar"><div class="lfill" style="width:'+p+'%"></div></div>'+meta+'</div>';
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
  const g5=curGate()==='G5';
  const sel=g5?(g5Checked[p.id]?' sel':''):((selId===p.id)?' sel':'');
  const rec=(!g5&&p.id===recId)?'<span class="rec">추천</span>':'';
  let extra='';
  if(p.models && p.models.length) extra='<div class="hint">🧩 모델: '+p.models.map(esc).join(', ')+'</div>';
  else if(p.metrics && typeof p.metrics==='object'){ const ks=Object.keys(p.metrics).slice(0,3); if(ks.length) extra='<div class="hint">📊 '+ks.map(function(k){return esc(k)+' '+esc(p.metrics[k]);}).join(' · ')+'</div>'; }
  else if(p.outputs && p.outputs.length){ var OL={'OUT-01':'PPT','OUT-02':'PDF 보고서','OUT-03':'발표 대본','OUT-04':'HTML 대시보드','OUT-07':'인사이트 요약'}; extra='<div class="hint">📦 '+p.outputs.map(function(o){return esc(OL[o]||o);}).join(' · ')+'</div>'; }
  const score=(p.score!=null)?('<div class="time">⭐ 추천도 '+Math.round(p.score*100)+'%</div>'):'';
  return '<div class="opt'+sel+'" data-pid="'+esc(p.id)+'"><div class="ck">✓</div><div class="onum">OPTION 0'+(idx+1)+rec+'</div><h3>'+esc(p.title||('제안 '+p.id))+'</h3><p>'+esc(p.rationale||'')+'</p>'+extra+score+'</div>';
}
function customCard(n){
  const sel=(selId==='custom')?' sel':'';
  const g=curGate()||('G'+(cur));
  const ph=g==='G5'?'예) PPT, 대시보드, 인사이트 요약 (선택: PPT · PDF 보고서 · 발표 대본 · 대시보드 · 인사이트)':'예) 1등석 여성 승객의 생존 요인을 집중 분석하고 싶어요';
  const title=g==='G5'?'직접 선택':'직접 입력';
  return '<div class="opt'+sel+'" data-pid="custom"><div class="ck">✓</div><div class="onum">OPTION 0'+(n+1)+'</div><h3>'+title+'</h3><div class="en2">Custom Direction</div>'
    +'<textarea id="cust" placeholder="'+ph+'"></textarea><div class="time">자유 입력</div></div>';
}
function contentGate(){
  const tg='G'+cur;               // 사용자가 보고 싶은 게이트 (cur 기준)
  const ag=curGate();             // 백엔드 현재 게이트
  // 사용자 위치와 백엔드 위치가 같으면 실시간 gateData, 다르면 캐시 사용
  const d=(ag===tg)?gateData:(gateCache[tg]||{});
  const g=tg;
  const props=(d.proposals)||[];
  if(!props.length){ return gateHeader(g)+loadingBlock(); }
  // filter out backend-injected custom placeholder — customCard is added separately below
  const llmProps=props.filter(function(p){ return !p.is_custom; });
  if(!llmProps.length){ return gateHeader(g)+loadingBlock(); }
  let recId=llmProps.reduce(function(a,b){ return (b.score||0)>(a.score||0)?b:a; }, llmProps[0]).id;
  if(selId===null || selGate!==g){ selId=recId; selGate=g; }
  let cards=llmProps.map(function(p,i){ return propCard(p,i,recId); }).join('');
  if(g==='G1'||g==='G2'||g==='G3'||g==='G4') cards+=customCard(llmProps.length);
  let pop='';
  if(animatedGate!==g){ pop=' popin'; animatedGate=g; if(g==='G5') g5Checked={}; setTimeout(function(){ try{ window.scrollTo({top:0,behavior:'smooth'}); }catch(e){} }, 30); }
  return gateHeader(g)+'<div class="opts'+pop+'">'+cards+'</div>';
}
function rcard(title, inner){ return '<div class="rcard"><h4>'+title+'</h4>'+inner+'</div>'; }
function contentResult(){
  const g=gateData; let panels='';
  if(g.eda_summary) panels+=rcard('데이터 요약 (EDA)','<p class="rtext">'+esc(g.eda_summary)+'</p>');
  if(g.best_model && typeof g.best_model==='object'){
    const m=g.best_model; let h='<div class="kpi">';
    if(m.model_name) h+='<div class="it"><div class="v">'+esc(m.model_name)+'</div><div class="l">최적 모델</div></div>';
    if(m.metrics && typeof m.metrics==='object'){ const mk=Object.keys(m.metrics)[0]; if(mk) h+='<div class="it"><div class="v">'+esc(m.metrics[mk])+'</div><div class="l">'+esc(mk)+'</div></div>'; }
    h+='</div>'; panels+=rcard('최적 모델', h);
  }
  if(g.eval_result && typeof g.eval_result==='object'){
    const ev=g.eval_result; let h='';
    if(ev.rationale) h+='<p class="rtext">'+esc(ev.rationale)+'</p>';
    if(ev.metrics && typeof ev.metrics==='object'){ const ks=Object.keys(ev.metrics).slice(0,3); h+='<div class="kpi" style="margin-top:10px">'+ks.map(function(k){return '<div class="it"><div class="v">'+esc(ev.metrics[k])+'</div><div class="l">'+esc(k)+'</div></div>';}).join('')+'</div>'; }
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
    // Phase 1 — G0 단계가 두 가지 상태를 가진다.
    //   (a) jobId 없음 → 파일 선택·의도 입력 화면(기존)
    //   (b) jobId 있음 + 분석 중 → 데이터 파악 진행 화면(15단계 백엔드 작업).
    //       이 화면을 끝까지 보여주다 G1 proposals 도착 시 poll() 이 cur=1 로 전환.
    if(jobId){
      return '<div class="ahdr"><h2>데이터를 파악하는 중입니다</h2>'
        +'<div class="en">G0 — Data Understanding</div></div>'
        +'<p class="desc">출처·스키마·도메인 의미·데이터 품질·카테고리 판정·PII 점검까지 마치는 중입니다. '
        +'끝나면 자동으로 분석 방향 추천이 표시됩니다.</p>'
        +loadingBlock();
    }
    const has=!!selectedFile;
    const t=has?('선택됨: '+esc(selectedFile.name)):'파일을 끌어다 놓거나 선택';
    return '<div class="ahdr"><h2>데이터 업로드</h2></div><p class="desc">파일을 올리면 ADA가 데이터를 분석해 방향을 제안합니다.</p>'
      +'<div class="dz'+(has?' has':'')+'" id="dz"><svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M7 18a4 4 0 0 1-.5-7.97A6 6 0 0 1 18 8.5a3.5 3.5 0 0 1 .5 6.96"/><path d="M12 19v-7"/><path d="m9 14 3-3 3 3"/></svg>'
      +'<div style="flex:1"><div class="t" id="dzt">'+t+'</div><div class="s">CSV · XLSX · PARQUET · JSON · PDF · ZIP · TXT (최대 100MB)</div></div>'
      +'<button class="browse" id="browseBtn">찾아보기</button></div>'
      +'<input type="file" id="fileInput" style="display:none" accept=".csv,.parquet,.xlsx,.zip,.json,.pdf,.txt,.html">'
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

  // 1~7 모든 단계 공통: 본문 + 진행바 (실패 시 진행바 생략 → progressBar() 내부에서 빈 문자열 반환).
  document.getElementById('content').innerHTML=
    (errMsg?('<div class="err">⚠ '+esc(errMsg)+'</div>'):'')+content(cur)+progressBar();
  document.getElementById('curName').textContent=steps[cur].label;
  // 상단 헤더 진행률 — progressBar 와 동일한 _stageProgress() 사용 → 카드 안 진행바와 항상 일치.
  document.getElementById('curPct').textContent=_stageProgress()+'%';
  document.getElementById('curIdx').textContent=cur+1;
  document.getElementById('curTot').textContent=N;
  const stt=document.getElementById('status');
  if(paused){ stt.textContent='⏸ 일시정지됨'; stt.className='status paused'; }
  else if(isFailed()){ stt.textContent='⛔ 실패'; stt.className='status failed'; }
  else if(isCompleted()){ stt.textContent='✓ 완료'; stt.className='status done'; }
  else if(jobId){ stt.textContent='진행 중'; stt.className='status'; }
  else { stt.textContent='대기'; stt.className='status'; }
  var nb=document.getElementById('newBtn'); if(nb) nb.style.display=jobId?'inline-flex':'none';

  if(cur===0){
    const fi=document.getElementById('fileInput'), dz=document.getElementById('dz'),
          br=document.getElementById('browseBtn'), it=document.getElementById('intentInput');
    if(br&&fi) br.onclick=function(e){ e.stopPropagation(); fi.click(); };
    if(dz&&fi) dz.onclick=function(){ fi.click(); };
    if(fi) fi.onchange=function(){ if(fi.files[0]){ selectedFile=fi.files[0]; render(); } };
    if(dz){ dz.ondragover=function(e){ e.preventDefault(); }; dz.ondrop=function(e){ e.preventDefault(); if(e.dataTransfer.files[0]){ selectedFile=e.dataTransfer.files[0]; render(); } }; }
    if(it){ it.value=intentText; it.oninput=function(){ intentText=it.value; }; }
  }
  if(cur>=1 && cur<=5){
    const isG5=curGate()==='G5';
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
  prev.disabled=(cur===0);
  next.disabled=(cur>=maxReached);
  stop.style.display=(!paused && analyzing())?'inline-flex':'none';
  const _tg='G'+cur;
  const _cd=gateCache[_tg]||{};
  const _llmCount=function(d){ return (d.proposals||[]).filter(function(p){return !p.is_custom;}).length; };
  const atCurrentGate=(cur===frontier)&&!!curGate()&&_llmCount(gateData)>0;
  const atPastGate=(cur<frontier)&&cur>=1&&cur<=5&&_llmCount(_cd)>0;
  const atGate=atCurrentGate||atPastGate;
  const g5ok=curGate()!=='G5'||Object.keys(g5Checked).some(function(k){return g5Checked[k];});
  prim.innerHTML=primaryLabel();
  prim.classList.toggle('resume', paused);
  if(busy) prim.disabled=true;
  else if(paused) prim.disabled=false;
  else if(cur===0) prim.disabled=(!selectedFile || !!jobId);
  else if(cur===LAST) prim.disabled=true;
  else prim.disabled=!atGate||!g5ok;
}
document.getElementById('prevBtn').onclick=function(){ if(cur>0){ cur--; follow=false; render(); } };
document.getElementById('nextBtn').onclick=function(){ if(cur<maxReached){ cur++; if(cur>=frontier) follow=true; render(); } };
document.getElementById('stopBtn').onclick=function(){ paused=true; if(pollTimer) clearTimeout(pollTimer); polling=false; render(); };
document.getElementById('primaryBtn').onclick=function(){
  if(busy) return;
  if(paused){ paused=false; render(); if(analyzing()) startPolling(); return; }
  if(cur===0){ doUpload(); return; }
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
        [data-testid="stAppViewContainer"] { background: #1c3450; }
        [data-testid="stHeader"] { display: none; }
        .block-container { max-width: 100% !important; padding: 0 !important; }
        [data-testid="stMain"] .block-container { padding: 0 !important; }
        [data-testid="stIFrame"] iframe, .block-container iframe {
            width: 100% !important; height: 97vh !important; border: 0; display: block;
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
