"""frontend/app.py — ADA Studio (단일 플로우 UI).

1) 랜딩(스플래시) → Start
2) 업로드 → 5게이트(HITL) → 산출물 : 확정 디자인(다크 히어로·진행도 스텝퍼·카드)을
   임베드(components.html)하고, 임베드 안에서 브라우저가 ADA API(localhost:8000)에 직접
   fetch 로 연동. 게이트 추천(proposals)·분석 결과·현재 게이트는 GET /pipeline/gate/{job}
   (LangGraph state) 에서 받아 표시. 분석 중에는 로딩바·진행률·경과/예상시간 표시.
"""

from __future__ import annotations

import os

# Day10 KPI 메트릭 레이블 — 성능 모니터링 대시보드용
_KPI_LABELS: dict[str, str] = {
    "KP1 E2E 성공률": "파이프라인 완주율 (%)",
    "KP2 평균 종단": "평균 종단 간 지연 (ms)",
    "KP5 p95": "p95 레이턴시 (ms)",
    "KP9 KB 적용률": "KB 활용 응답 비율 (%)",
}

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
  @media(max-width:1100px){ .opts,.res .grid2{grid-template-columns:1fr;} }
</style></head><body>
  <div class="shell">
    <div class="brand"><span class="globe">🌐</span><span class="nm">ADAPTIVE&nbsp;&nbsp;DATA&nbsp;&nbsp;ANALYST</span><span class="status" id="status">대기</span></div>
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
const steps=[{label:'업로드',sub:'데이터'},{label:'분석 방향',sub:'G1'},{label:'방법론',sub:'G2'},{label:'모델 전략',sub:'G3'},{label:'모델 선택',sub:'G4'},{label:'산출물',sub:'G5'},{label:'완료',sub:'인사이트'}];
const N=steps.length, LAST=N-1;
const ANALYZE_EST=45;  // 분석 중 진행률 추정용(초)
const GATE_TITLE={G1:['어떤 방식으로 분석할까요?','Choose your analysis direction'],G2:['어떤 방법론으로 진행할까요?','Choose your methodology'],G3:['어떤 모델 전략을 쓸까요?','Choose your model strategy'],G4:['어떤 모델을 채택할까요?','Pick the best model'],G5:['어떤 산출물을 만들까요?','Choose your outputs']};
const API=(function(){ let p='http:',h='localhost'; try{ p=window.parent.location.protocol; h=window.parent.location.hostname; }catch(e){} if(p!=='http:'&&p!=='https:')p='http:'; if(!h)h='localhost'; return p+'//'+h+':8000'; })();
let cur=0, frontier=0, maxReached=0, paused=false, follow=true, busy=false, polling=false, pollTimer=null;
let jobId=null, fileId=null, selectedFile=null, intentText='', status={}, errMsg='';
let gateData={}, selId=null, selGate=null, customText='', analyzeStart=null, animatedGate=null;
const AGENT_KO={supervisor:'작업 분류',intent_elicitor:'분석 의도 파악',data_profiler:'데이터 프로파일링',schema_validator:'스키마 검증',gate_direction:'분석 방향 제안 생성',eda_agent:'탐색적 분석(EDA)',gate_methodology:'방법론 제안',preprocessing_strategist:'전처리 전략',feature_engineer:'피처 엔지니어링',gate_model_strategy:'모델 전략 제안',model_selection:'모델 선택',hyperparameter_tuner:'하이퍼파라미터 튜닝',training_executor:'모델 학습',training_monitor:'학습 모니터링',metrics_aggregator:'지표 집계',gate_best_model:'최적 모델 선정',eval_agent:'평가',explainability:'설명가능성',insight:'인사이트 생성',gate_outputs:'산출물 선택',report_composer:'리포트 생성'};

function esc(s){ return String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
function fmtTime(s){ s=Math.max(0,Math.round(s)); const m=Math.floor(s/60), ss=s%60; return m+':'+(ss<10?'0':'')+ss; }
function curGate(){ const g=(gateData.gate)||(status.current_gate); return (g && /^G[1-5]$/.test(g))?g:null; }
function hasResults(){ return !!((gateData.output_paths && Object.keys(gateData.output_paths).length) || gateData.insights || gateData.eval_result || gateData.best_model); }
function isFailed(){ return (gateData.pipeline_status==='failed') || (status.status==='failed'); }
function isCompleted(){ return ['completed','succeeded','success'].includes(status.status) || (gateData.pipeline_status==='completed') || (jobId && !curGate() && hasResults()); }
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
    jobId=stt.job_id; follow=true; cur=1; frontier=1; maxReached=1; busy=false;
    gateData={}; analyzeStart=Date.now();
    startPolling();
  }catch(e){ errMsg='업로드/시작 실패 — '+e.message; busy=false; render(); }
}
async function doResume(){
  const props=(gateData.proposals)||[];
  let choice;
  if(selId==='custom'){
    if(!customText.trim()){ errMsg='옵션: 분석 방향을 입력해 주세요.'; render(); return; }
    choice={adopted_rank:0, custom_intent:customText};
  } else if(selId!=null){ choice={adopted_rank:selId}; }
  else { choice={adopted_rank:(props[0]&&props[0].id)||1}; }
  const gate=curGate() || ('G'+cur);
  errMsg=''; busy=true; render();
  try{
    await api('/pipeline/resume/'+jobId,{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({gate:gate,choice:choice})});
    follow=true; busy=false; gateData={}; selId=null; analyzeStart=Date.now();
    startPolling();
  }catch(e){ errMsg='전송 실패 — '+e.message; busy=false; render(); }
}
async function poll(){
  if(!jobId) return;
  try{ status=await api('/pipeline/status/'+jobId,{}); }catch(e){ status={_err:e.message}; }
  try{ gateData=await api('/pipeline/gate/'+jobId,{}); }catch(e){ gateData={proposals:[], _err:e.message}; }
  computeFrontier(); maxReached=Math.max(maxReached,frontier);
  if(follow) cur=frontier;
  cur=Math.max(0,Math.min(cur,frontier));
  if(analyzing()){ if(analyzeStart==null) analyzeStart=Date.now(); } else { analyzeStart=null; }
  render();
  if(analyzing() && !paused){ pollTimer=setTimeout(poll, 2500); }
  else { polling=false; }
}
function startPolling(){ if(polling){ render(); return; } polling=true; clearTimeout(pollTimer); poll(); }

// 1초 틱 — 분석 중 로딩바/경과시간 갱신
setInterval(function(){ if(analyzing() && !paused) render(); }, 1000);

function failureBlock(){
  const msg=gateData.pipeline_error||status.error||'알 수 없는 오류';
  return '<div class="loadwrap"><div class="loadtxt">⛔ 분석이 실패했습니다.</div>'
    +'<div class="diag"><b>오류:</b> '+esc(msg)+'<br>'
    +'① 워커 로그 확인: <code>docker logs --tail 200 ada-worker-pipeline</code><br>'
    +'② 워커 재기동 후 새 파일로 재시도하세요.'
    +'</div></div>';
}
function loadingBlock(){
  if(isFailed()) return failureBlock();
  const el=analyzeStart?((Date.now()-analyzeStart)/1000):0;
  const realP=(gateData.progress_pct!=null)?gateData.progress_pct:null;
  // 지연/정체 판단 — 마지막 진행 갱신이 120초 이상 없으면 ETA 를 동결한다
  let since=null;
  if(gateData.progress_ts){ since=Math.max(0, Date.now()/1000 - gateData.progress_ts); }
  const stale=(since!=null && since>120);
  if(realP!=null){
    const p=Math.max(2, Math.min(99, realP));
    let etaStr='추정 중…';
    if(stale){
      etaStr='지연/멈춤 의심 — 추정 불가';
    } else if(realP>5 && el>5){
      // 진행률이 너무 낮으면 선형 외삽이 곧 elapsed 와 같아져 오해를 부른다 → 5% 미만은 표시 안 함
      etaStr='약 '+fmtTime(Math.max(0, el*100/realP - el));
    }
    let agentLine='';
    if(gateData.current_agent){ agentLine='<div class="lagent">현재 작업: <b>'+esc(AGENT_KO[gateData.current_agent]||gateData.current_agent)+'</b></div>'; }
    let staleLine='';
    if(since!=null){ staleLine=' · 마지막 갱신 '+fmtTime(since)+' 전'+(stale?' ⚠ 지연/멈춤 의심':''); }
    return '<div class="loadwrap"><div class="loadtxt">🔄 데이터를 분석해 추천을 생성하는 중입니다…</div>'+agentLine
      +'<div class="lbar"><div class="lfill" style="width:'+p+'%"></div></div>'
      +'<div class="lmeta">진행 <b>'+p+'%</b> · 분석 시간 <b>'+fmtTime(el)+'</b> · 예상 남은 시간 <b>'+etaStr+'</b>'+staleLine+'</div></div>';
  }
  // 백엔드가 진행률을 안 보냄 → 가짜 % 대신 미정(indeterminate) 바 + 진단
  let diag='';
  if(el>75){
    diag='<div class="diag">⚠ 백엔드에서 진행 신호가 <b>'+fmtTime(el)+'</b> 동안 없습니다. 워커가 실제로 분석 중이 아닐 가능성이 큽니다.<br>'
      +'① 워커 실행: <code>docker ps | grep worker</code> &nbsp; ② 로그: <code>docker logs --tail 120 ada-worker-pipeline</code><br>'
      +'③ <code>ANTHROPIC_API_KEY</code> 설정 여부 &nbsp; ④ 백엔드(api·worker) 파일 복사 후 <b>재기동</b> 했는지'
      +(gateData._err?('<br><b>/gate 오류:</b> '+esc(gateData._err)+' → api 미배포/미기동 의심'):'')
      +(gateData._state_error?('<br><b>state 오류:</b> '+esc(gateData._state_error)):'')
      +'</div>';
  }
  return '<div class="loadwrap"><div class="loadtxt">🔄 데이터를 분석하는 중입니다…</div>'
    +'<div class="lbar indet"><div class="lfill"></div></div>'
    +'<div class="lmeta">분석 시간 <b>'+fmtTime(el)+'</b> · 백엔드 진행 신호 <b>대기 중</b></div>'+diag+'</div>';
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
  const sel=(selId===p.id)?' sel':'';
  const rec=(p.id===recId)?'<span class="rec">추천</span>':'';
  let extra='';
  if(p.models && p.models.length) extra='<div class="hint">🧩 모델: '+p.models.map(esc).join(', ')+'</div>';
  else if(p.metrics && typeof p.metrics==='object'){ const ks=Object.keys(p.metrics).slice(0,3); if(ks.length) extra='<div class="hint">📊 '+ks.map(function(k){return esc(k)+' '+esc(p.metrics[k]);}).join(' · ')+'</div>'; }
  else if(p.outputs && p.outputs.length) extra='<div class="hint">📦 '+p.outputs.map(esc).join(', ')+'</div>';
  const score=(p.score!=null)?('<div class="time">⭐ 추천도 '+Math.round(p.score*100)+'%</div>'):'';
  return '<div class="opt'+sel+'" data-pid="'+esc(p.id)+'"><div class="ck">✓</div><div class="onum">OPTION 0'+(idx+1)+rec+'</div><h3>'+esc(p.title||('제안 '+p.id))+'</h3><p>'+esc(p.rationale||'')+'</p>'+extra+score+'</div>';
}
function customCard(n){
  const sel=(selId==='custom')?' sel':'';
  return '<div class="opt'+sel+'" data-pid="custom"><div class="ck">✓</div><div class="onum">OPTION 0'+(n+1)+'</div><h3>직접 입력</h3><div class="en2">Custom Direction</div>'
    +'<textarea id="cust" placeholder="예) 1등석 여성 승객의 생존 요인을 집중 분석하고 싶어요"></textarea><div class="time">자유 입력</div></div>';
}
function contentGate(){
  const g=curGate() || ('G'+cur);
  const props=(gateData.proposals)||[];
  if(!curGate() || !props.length){ return gateHeader(g)+loadingBlock(); }
  let recId=props.reduce(function(a,b){ return (b.score||0)>(a.score||0)?b:a; }, props[0]).id;
  if(selId===null || selGate!==g){ selId=recId; selGate=g; }
  let cards=props.map(function(p,i){ return propCard(p,i,recId); }).join('');
  if(g==='G1') cards+=customCard(props.length);
  let pop='';
  if(animatedGate!==g){ pop=' popin'; animatedGate=g; setTimeout(function(){ try{ window.scrollTo({top:0,behavior:'smooth'}); }catch(e){} }, 30); }
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
  const outs=Object.keys(g.output_paths||{});
  if(outs.length) panels+=rcard('산출물', outs.map(function(o){return '<span class="chip on">'+esc(o)+'</span>';}).join(''));
  if(!panels) panels='<div class="rcard"><p class="rtext">결과를 불러오는 중…</p></div>';
  return '<div class="res"><div class="ahdr"><h2>분석 완료 🎉</h2></div><p class="desc">데이터를 분석한 결과입니다.</p><div class="grid2">'+panels+'</div></div>';
}
function content(i){
  if(i===0){
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

  document.getElementById('content').innerHTML=(errMsg?('<div class="err">⚠ '+esc(errMsg)+'</div>'):'')+content(cur);
  document.getElementById('curName').textContent=steps[cur].label;
  document.getElementById('curPct').textContent=((gateData.progress_pct!=null && !isCompleted())?gateData.progress_pct:Math.round(fillPct))+'%';
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
    if(fi) fi.onchange=function(){ if(fi.files[0]){ selectedFile=fi.files[0]; render(); } };
    if(dz){ dz.ondragover=function(e){ e.preventDefault(); }; dz.ondrop=function(e){ e.preventDefault(); if(e.dataTransfer.files[0]){ selectedFile=e.dataTransfer.files[0]; render(); } }; }
    if(it){ it.value=intentText; it.oninput=function(){ intentText=it.value; }; }
  }
  if(cur>=1 && cur<=5){
    document.querySelectorAll('.opt').forEach(function(el){ el.onclick=function(){ const pid=el.dataset.pid; selId=(pid==='custom')?'custom':(+pid); render(); }; });
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
  const atGate=(cur===frontier) && !!curGate() && ((gateData.proposals||[]).length>0);
  prim.innerHTML=primaryLabel();
  prim.classList.toggle('resume', paused);
  if(busy) prim.disabled=true;
  else if(paused) prim.disabled=false;
  else if(cur===0) prim.disabled=(!selectedFile || !!jobId);
  else if(cur===LAST) prim.disabled=true;
  else prim.disabled=!atGate;
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
render();
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
    components.html(_FLOW_HTML, height=900, scrolling=True)


# ===========================================================================
# 라우팅 — 랜딩 → 플로우
# ===========================================================================
if not st.session_state.get("studio_started"):
    # ── 스플래시(랜딩) ── (화면 세로 중앙 정렬, 히어로 이미지·폴백 공통)
    st.markdown(
        """
        <style>
        .block-container {
            min-height: calc(100vh - 4rem);
            display: flex; flex-direction: column; justify-content: center;
            padding-top: 1.5rem; padding-bottom: 1.5rem;
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
            st.rerun()
else:
    _flow_screen()
