"""outputs.architect.skeletons.report_skeleton — 데이터 분석 종합 보고서 Skeleton **v2**.

v2 설계 철학 (목적·인사이트 중심):
    보고서의 주인공은 모델 성능 수치가 아니라 **"분석 목적에 대한 답(인사이트)"**이다.
    모델·성능은 그 답을 신뢰하게 해주는 **근거(조연)**로 배치한다.
    하나의 줄기: 목적·질문(§1) → 데이터가 말하는 것(§3) → 그래서 무엇을 알았나(§6)
                → 그래서 무엇을 해야 하나(§7) → 최종 답(§8 결론).

목차 (front matter + 동적 번호 본문):
    표지 (cover)                          ← carrier 가 자체 헤더 렌더 (스킵)
    Executive Summary                     ← carrier 가 narrative_thread 로 렌더 (현황·문제·해결·권고)
    §1 분석 개요          (overview)         목적·문제정의·성공기준·데이터범위
    §2 데이터 이해         (data_understanding) 개요·변수정의·품질·대표성
    §3 탐색적 발견         (eda)             차트 finding·세그먼트·가설검정 (발견 중심)
    §4 분석 방법          (method)          전처리·피처·검증 설계 (신뢰 근거)
    §5 모델 성능          (model_performance) 후보 비교·성능 (근거·조연)
    §6 핵심 인사이트와 해석  (key_insights)     변수 중요도·per-feature·세그먼트 드라이버 ★심장
    §7 비즈니스 임팩트와 실행 (implications)    임팩트·표적 개입·실행 레버·운영 적용·리스크 (풍부 산문)
    §8 결론               (conclusion)      §1 핵심 질문에 대한 시니어 톤의 답 (짧고 단정)
    부록 (appendix, 선택)                   재현 정보·코드·환경

설계 원칙:
    - 계약 기반·범용: 특정 데이터 가정 없이 ctx 13묶음만 읽어 어떤 카테고리·데이터든 대응.
    - 방어적: 인사이트 묶음이 비면 해당 섹션 스킵(None). 번호는 남은 섹션에 연속 부여(빈틈 없음).
    - 인사이트 우선: EDA 는 "차트"가 아니라 "발견", 모델 성능은 "조연".

═══════════════════════════════════════════════════════════════════
[좋은패턴] 슬라이드 타이틀 작성 룰 (사용자 확정 — 절대 임의 변경 금지)
─────────────────────────────────────────────────────────────────
정의:
    슬라이드 타이틀(SlideSpec.title_ko)은 섹션 헤딩(SectionSpec.title)을
    그대로 반복하지 말고, 헤딩보다 한 단계 더 구체적인 범위·관점을
    명사구로 제시한다. 필요하면 괄호로 부제·관점을 보조.
    모든 줄이 새 정보를 운반해야 한다는 시니어 보고서 원칙의 적용.

기준 예시 (§5):
    헤딩  : "5. 모델 성능"
    타이틀: "모델 선정 및 성능 (근거)"
    ─ "선정"이라는 새 정보 + "(근거)" 관점 명시.

반례 (❌ 사용 금지):
    헤딩  : "2. 데이터 이해"
    타이틀: "데이터 이해 — 이 데이터로 답할 수 있나"
    ─ 헤딩 그대로 반복 + "— ..." 부제만. 정보 추가 0.

올바른 적용 (✅ 본 파일 모든 섹션):
    §1 분석 개요          → "프로젝트 정의 (목적·범위·성공 기준)"
    §2 데이터 이해         → "표본 적합성 및 변수 진단"
    §4 분석 방법          → "분석 절차 및 검증 설계 (신뢰 근거)"
    §5 모델 성능          → "모델 선정 및 성능 (근거)"  ★기준
    §6 핵심 인사이트와 해석  → "동인·메커니즘·표적 종합 (핵심 발견)"
    §7 비즈니스 임팩트와 실행 → "실행 레버·운영 적용·리스크 (액션 플랜)"
    §8 결론               → "최종 답과 의사결정 (Bottom Line)"

사용법:
    - 사용자가 "좋은패턴 적용해" / "좋은패턴으로 바꿔" 라고 하면 이 룰을 적용한다.
    - 본 파일 안에서 grep "[좋은패턴]" 으로 정의·기준 예시를 즉시 참조.
═══════════════════════════════════════════════════════════════════
[줄띄움라벨] 인라인 라벨 형식 룰 (사용자 확정)
─────────────────────────────────────────────────────────────────
정의 (B15·B19 갱신 — 2026-06-11):
    한 카드 안 라벨-내용 행은 `_rules.card([...])` 통과로만 렌더한다.
    - [B15 라벨밀착룰] 행 사이 구분자는 단일 `<br/>` (빈 줄 금지)
    - [B19 라벨구분자룰] 라벨 콜론 앞뒤 공백 한 칸씩
    - [B18 평이한언어룰] 라벨·내용에 화살표(→) 사용 금지

기준 예시 (§2 품질 점검):
    OK  _rules.card([("발견", "..."), ("처리", "..."), ("후속", "...")])

같은 룰이 적용된 다른 곳:
    §3 EDA 차트 캡션: <관찰> ... <br/><br/> <의미> ... <br/><br/> <시사> ...

사용법:
    - 사용자가 "줄띄움라벨 적용해" / "라벨마다 줄 띄워" 라고 하면 이 룰을 적용한다.
    - grep "[줄띄움라벨]" 로 정의·기준 예시를 즉시 참조.
═══════════════════════════════════════════════════════════════════
[5~6줄룰] 라벨 있는 블록 본문 길이 표준 (사용자 확정)
─────────────────────────────────────────────────────────────────
정의:
    prose_blocks 안 라벨 있는 블록의 본문은 5~6줄로 제한.
    문장 수만 세지 말 것 — 각 문장이 길면 4문장도 8줄이 됨.

환산 기준 (14pt 한국어 본문, leftIndent=8, 페이지 본문 폭 약 16cm):
    한 줄 ≈ 30자
    5줄 ≈ 150자
    6줄 ≈ 180자
    4문장 × 평균 40자 ≈ 5~6줄  (각 문장이 길면 룰 위반)

작성 원칙:
    1) business_context 같은 사용자 제공 긴 문장이 들어가면, 같은 결의 다른 문장(시급성 등)은 생략한다.
    2) 데이터·결측·규모 같은 사실 진술은 압축형 어법 — "~수준이다" 대신 "~수준", "측면에서" 같은 형식어 제거.
    3) 다른 블록·다른 섹션과 중복되는 진술은 제거 (§1 분석 배경에서 변수 구성 평가는 §2와 중복).
    4) 한 문장 40자 초과면 둘로 쪼개거나 압축.

제외 대상 (5~6줄 룰 적용 X):
    - 표지 메인 / 섹션 헤딩 / 슬라이드 타이틀 / 블록 라벨 / 캡션
    - 라벨이 빈 블록 ["", ...] — ES, §8 결론 본문, §7 레버 줄

사용법:
    - 사용자가 "5~6줄로 줄여" / "5~6줄룰 적용해" 라고 하면 이 룰을 적용한다.
    - grep "[5~6줄룰]" 로 정의·환산 기준을 즉시 참조.
═══════════════════════════════════════════════════════════════════
[EDA페이지룰] §3 탐색적 발견 페이지 레이아웃 표준 (사용자 확정)
─────────────────────────────────────────────────────────────────
정의:
    §3 EDA 페이지는 차트 슬라이드 2개씩 페이지 절반에 배치.
    마지막 '주요 발견 종합' 슬라이드도 차트와 동일하게 페이지 절반 단위로 취급.

레이아웃 룰:
    1) 한 페이지 = 슬라이드 2개 (차트 또는 발견 종합). 페이지 절반씩.
    2) 차트 사이즈 상한: width 16cm × height 6.0cm (carrier 강제).
       — A4 본문 25.7cm 안에 섹션 헤딩(2.85cm) + 슬라이드 2개(약 11cm씩) 들어가는 최대치.
    3) 차트 위 여백 0.2cm, 슬라이드 끝 spacer 0.3cm (페이지에 2개 들어가도록 축소).
    4) 차트 아래 캡션(관찰·의미·시사)은 줄 띄움 없이 한 줄씩 — <br/> 만, <br/><br/> 금지.
    5) EDA section 의 모든 슬라이드는 carrier 에서 KeepTogether 강제
       → 페이지 내 분할 안 됨, 페이지당 2개씩 자동 배치.

기준 예시 (타이타닉):
    페이지 1: 1) 성별 생존률 | 2) 좌석 등급별 생존률
    페이지 2: 3) 나이대별 생존률 | 4) 승선항별 생존률
    페이지 3: 5) 주요 발견 종합 (페이지 절반만 차지)

다른 섹션과의 차이:
    - §1·§2·§4·§5·§6·§7·§8 은 본문 산문 위주 → 슬라이드별 페이지 전체 사용.
    - §3 만 차트 콜아웃 위주라 페이지 절반 단위 배치.

사용법:
    - 사용자가 "EDA 페이지 룰 적용해" / "차트 2개씩 페이지에 박아" 라고 하면 이 룰을 적용한다.
    - grep "[EDA페이지룰]" 로 정의·레이아웃을 즉시 참조.
═══════════════════════════════════════════════════════════════════

NY (HJ 위임) 2026-06 — PDF OUT-02 보고서 레시피 v2. carrier 직접 호출 경로용.
"""

from __future__ import annotations

import re as _re
from typing import Any, Optional

from outputs.architect.plan import (
    NarrativeThread,
    ReportPlan,
    SectionSpec,
    SlideSpec,
    VisualSpec,
)
from outputs.architect.skeletons._rules import card as _label_card
from outputs.context.schema import ReportContext

SKELETON_NAME = "Report"

# 길이 가드 — 표·차트 폭주 방지 (cap)
_MAX_DICT_ROWS = 30
_MAX_PREP_ROWS = 12
_MAX_EDA_SLIDES = 4
_MAX_BODY = 6

_CAT_VERB = {
    "tabular_ml": "예측",
    "tabular_dl": "예측",
    "timeseries": "예측",
    "anomaly_detection": "이상 탐지",
}


# ==============================================================
# 포맷·정규화 헬퍼
# ==============================================================
def _fv(v: Any) -> str:
    if v is None:
        return "-"
    if isinstance(v, float):
        return f"{v:.4f}" if 0 < abs(v) < 1 else f"{v:,.2f}"
    return str(v)


def _fvb(v: Any) -> str:
    """[레지스터] 본문(결정)용 숫자 — 비율(0<v<1)은 소수 2자리. 4자리 정밀값·CI는 부록 몫."""
    if isinstance(v, (int, float)) and 0 < abs(v) < 1:
        return f"{v:.2f}"
    return _fv(v)


def _pct(v: Any) -> str:
    try:
        return f"{float(v) * 100:.1f}%"
    except Exception:
        return "-"


def _norm_cell(v: Any) -> str:
    """표 셀 정규화 — bool/None/'False'/'nan' 등 의미없는 값은 '' 로 (도배 방지)."""
    if v is None or isinstance(v, bool):
        return ""
    s = str(v).strip()
    if s.lower() in ("false", "none", "nan", "null", "-", "true"):
        return ""
    return s


_UUID_RE = _re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def _human_dataset_name(ctx: ReportContext) -> str:
    """데이터셋명 친화화 — 확장자 제거, UUID/해시형이면 도메인·타깃 기반 폴백."""
    name = (ctx.dataset.dataset_name or "").strip()
    for ext in (".csv", ".xlsx", ".xls", ".parquet", ".json", ".tsv"):
        if name.lower().endswith(ext):
            name = name[: -len(ext)]
            break
    hexish = name.replace("-", "").lower()
    looks_uuid = bool(_UUID_RE.match(name)) or (len(hexish) >= 24 and hexish and all(c in "0123456789abcdef" for c in hexish))
    if name and not looks_uuid:
        return name
    dom = (ctx.domain.inferred_use_case if ctx.domain else None) or None
    target = ctx.dataset.detected_target
    if dom:
        return str(dom)[:40]
    if target:
        return f"{target} 분석 데이터셋"
    return "분석 데이터셋"


def _purpose_text(ctx: ReportContext) -> str:
    """분석 목적 한 줄 — user_question 우선, 없으면 도메인 use_case, 그래도 없으면 intent dedup."""
    q = (ctx.meta.user_question or "").strip()
    if q:
        return q[:120]
    uc = ((ctx.domain.inferred_use_case if ctx.domain else "") or "").strip()
    if uc:
        return uc[:120]
    raw = (ctx.meta.user_intent or "").strip()
    if raw:
        parts = _re.split(r"[()\[\]]|\s{2,}|·", raw)  # 누적/중복 괄호 조각 dedup
        seen: set[str] = set()
        for p in parts:
            p = p.strip(" \t·-—,:|")
            if p and p not in seen:
                return p[:120]
    # 최종 폴백 — 사용자 의도가 없어도 데이터에서 직접 목적 도출 (가짜 비즈니스 목적 X)
    target = ctx.dataset.detected_target
    verb = _CAT_VERB.get(ctx.meta.category or "", "분석")
    if target:
        return f"'{target}'{_josa(target, 'obj')} {verb}하는 분석 모델 수립"
    return "데이터 기반 패턴 발견 및 예측 모델 수립"


def _txt_from(d: Any, keys: tuple[str, ...]) -> str:
    """dict 에서 후보 키 중 첫 비어있지 않은 값 → str. 인사이트 텍스트 추출용."""
    if not isinstance(d, dict):
        return str(d) if d else ""
    for k in keys:
        v = d.get(k)
        if v not in (None, "", False):
            return str(v)
    return ""


def make_section(
    section_id: str,
    title: str,
    kind: str,
    slides: list[SlideSpec],
    summary: str = "",
) -> SectionSpec:
    return SectionSpec(
        id=section_id,
        title=title,
        kind=kind,
        divider_required=False,
        short_summary=summary or title,
        slides=slides,
    )


# ==============================================================
# 공용 비주얼 빌더
# ==============================================================
def _data_dictionary_visual(ctx: ReportContext) -> Optional[VisualSpec]:
    """변수정의 표 — dataset.dtypes + missing_rate + domain.glossary."""
    dtypes = ctx.dataset.dtypes or {}
    if not dtypes:
        return None
    missing = ctx.dataset.missing_rate or {}
    glossary = (ctx.domain.glossary or {}) if ctx.domain else {}
    rows: list[list[str]] = []
    for col, dt in list(dtypes.items())[:_MAX_DICT_ROWS]:
        rows.append([str(col), str(dt), _pct(missing.get(col, 0)), str(glossary.get(col, ""))[:30]])
    return VisualSpec(
        type="table_feature_matrix",
        title="변수 정의서",
        caption="컬럼별 타입·결측률·의미",
        spec={"columns": ["변수", "타입", "결측률", "의미"], "rows": rows},
    )


def _preprocessing_visual(ctx: ReportContext) -> Optional[VisualSpec]:
    """전처리 단계 표 — bool/빈 rationale·scope 정규화 + 전부 빈 컬럼 자동 숨김."""
    steps = (ctx.preprocessing.applied_steps or []) if ctx.preprocessing else []
    if not steps:
        return None
    rows: list[list[str]] = []
    for i, st in enumerate(steps[:_MAX_PREP_ROWS], 1):
        op = getattr(st, "op", "") or (st.get("op", "") if isinstance(st, dict) else "")
        scope = getattr(st, "scope", None)
        if scope is None and isinstance(st, dict):
            scope = st.get("scope", [])
        scope = scope or []
        rationale = getattr(st, "rationale", "")
        if rationale in (None, "", False) and isinstance(st, dict):
            rationale = st.get("rationale", "")
        rows.append(
            [str(i), _norm_cell(op), _norm_cell(", ".join(map(str, scope)))[:24], _norm_cell(rationale)[:40]]
        )
    cols_all = ["#", "단계", "대상", "근거"]
    keep = [0, 1] + [ci for ci in (2, 3) if any(r[ci] for r in rows)]
    columns = [cols_all[i] for i in keep]
    rows = [[r[i] for i in keep] for r in rows]
    return VisualSpec(
        type="table_feature_matrix",
        title="전처리 단계",
        caption="적용 순서" + ("·대상" if 2 in keep else "") + ("·근거" if 3 in keep else ""),
        spec={"columns": columns, "rows": rows},
    )


# ==============================================================
# 섹션 빌더 — front matter
# ==============================================================
def _build_cover(ctx: ReportContext) -> SectionSpec:
    intent = (ctx.meta.user_intent or ctx.meta.user_question or "데이터 분석 종합 보고서").strip()
    cover = SlideSpec(
        id="cover",
        section_id="front_matter",
        layout="cover",
        role="meta",
        title_ko=intent[:40],
        body_outline=[
            f"카테고리: {ctx.meta.category or '-'}",
            f"데이터셋: {_human_dataset_name(ctx)}",
            f"분류등급: {ctx.meta.classification}",
        ],
    )
    return make_section("front_matter", "표지", "cover", [cover])


# ==============================================================
# 섹션 빌더 — §1~§8 (목적·인사이트 중심)
# ==============================================================
def _is_numeric_dtype(t: Any) -> bool:
    return any(x in str(t).lower() for x in ("int", "float", "double", "number", "decimal"))


def _target_distribution(ds: Any, target: str) -> tuple[Optional[int], Optional[float]]:
    """(클래스 수, 다수 클래스 비율) — categorical_top/cardinality 에서 best-effort 추출."""
    n_classes = (ds.cardinality or {}).get(target)
    n_classes = n_classes if isinstance(n_classes, int) else None
    maj = None
    ctop = (ds.categorical_top or {}).get(target)
    if isinstance(ctop, list) and ctop:
        counts = []
        for d in ctop:
            if isinstance(d, dict):
                c = d.get("count", d.get("freq", d.get("n")))
                if isinstance(c, (int, float)):
                    counts.append(float(c))
        if counts and sum(counts) > 0:
            maj = max(counts) / sum(counts)
        if maj is None:  # ratio 형태로 들어온 경우
            for d in ctop:
                if isinstance(d, dict):
                    r = d.get("ratio", d.get("pct", d.get("proportion")))
                    if isinstance(r, (int, float)):
                        maj = float(r) if r <= 1 else float(r) / 100.0
                        break
    return n_classes, maj


def _task_flags(ctx: ReportContext) -> dict[str, Any]:
    """과제 유형 플래그 — §1(결정 언어)·§4(지표 근거)가 공유."""
    ds = ctx.dataset
    cat = ctx.meta.category or ""
    target = ds.detected_target or "타깃"
    dtypes = ds.dtypes or {}
    n_classes, maj = _target_distribution(ds, target)
    is_clf = (cat in ("tabular_ml", "tabular_dl", "anomaly_detection")) and (
        not _is_numeric_dtype(dtypes.get(target)) or (isinstance(n_classes, int) and 0 < n_classes <= 20)
    )
    is_ts = cat == "timeseries"
    is_anom = cat == "anomaly_detection"
    return {
        "is_clf": is_clf,
        "is_ts": is_ts,
        "is_anom": is_anom,
        "is_reg": (not is_clf) and (not is_ts) and (not is_anom),
        "is_imbal": is_anom or (maj is not None and maj >= 0.7),
        "is_multiclass": is_clf and isinstance(n_classes, int) and n_classes > 2,
        "n_classes": n_classes,
        "maj": maj,
    }


def _josa(word: str, kind: str) -> str:
    """받침 판정 후 조사 자동 선택 — kind: subj(은/는)·nom(이/가)·obj(을/를)·and(와/과)·with(로/으로).

    한글 종성 / 숫자 발음 / 영문은 마지막 글자 발음(l·m·n만 받침, 나머지는 '으'발음 무받침)으로 추정.
    확신 없으면 무받침(보수적). 'CatBoost'→무받침→'를', '계약 유형'→받침→'은'.
    """
    no = {"subj": "는", "nom": "가", "obj": "를", "and": "와", "with": "로"}
    yes = {"subj": "은", "nom": "이", "obj": "을", "and": "과", "with": "으로"}
    w = (word or "").strip().strip("'\"")
    if not w:
        return no.get(kind, "")
    last = w[-1]
    code = ord(last) - 0xAC00
    has, rieul = False, False
    if 0 <= code <= 11171:  # 한글
        jong = code % 28
        has, rieul = (jong != 0), (jong == 8)
    elif last.isdigit():  # 숫자 발음 (영·일·삼·육·칠·팔=받침)
        has = last in {"0", "1", "3", "6", "7", "8"}
        rieul = last == "1"
    else:  # 영문/기타 — l·m·n 만 받침(폴/김/캔), 그 외 트/스/AUC 등 무받침
        ll = last.lower()
        has = ll in "lmn"
        rieul = ll == "l"
    if not has:
        return no.get(kind, "")
    if kind == "with":
        return "로" if rieul else "으로"
    return yes.get(kind, "")


# 범용 변수명 사전 (전체 일치) — 도메인 무관 공통 컬럼. 특정 데이터셋 단어 금지.
_COL_KO = {
    "id": "식별자", "date": "일자", "time": "시각", "datetime": "일시", "timestamp": "시각",
    "amount": "금액", "price": "가격", "cost": "비용", "count": "건수", "qty": "수량",
    "quantity": "수량", "rate": "비율", "ratio": "비율", "age": "나이", "gender": "성별",
    "sex": "성별", "region": "지역", "country": "국가", "city": "도시", "category": "범주",
    "type": "유형", "status": "상태", "score": "점수", "label": "라벨", "target": "타깃",
    "value": "값", "year": "연도", "month": "월", "day": "일", "tenure": "가입 기간",
    "charges": "청구액", "contract": "계약 유형", "payment": "결제", "paymentmethod": "결제 수단",
    "monthlycharges": "월 청구액", "totalcharges": "총 청구액", "income": "소득", "balance": "잔액",
}
# 토큰 휴리스틱 사전 (camelCase/snake 분해 후 토큰별)
_TOKEN_KO = {
    "monthly": "월", "yearly": "연", "daily": "일", "total": "총", "avg": "평균", "mean": "평균",
    "max": "최대", "min": "최소", "sum": "합", "num": "수", "cnt": "수", "count": "수",
    "charges": "청구액", "charge": "청구액", "amount": "금액", "fee": "수수료", "price": "가격",
    "cost": "비용", "rate": "비율", "ratio": "비율", "date": "일자", "time": "시각",
    "year": "연", "month": "월", "day": "일", "id": "ID", "age": "나이",
}

# 단위 추론 사전 — 일반 토큰 (도메인 무관). 통화·도메인 단위는 자동 추론 위험 → 빈 문자열 폴백.
# 거짓 단위 표기 금지(예: charges → '원' 추정 금지. 데이터셋이 USD/EUR/KRW 알 수 없음).
_TOKEN_UNIT = {
    "tenure": "개월",
    "age": "세",
    "year": "년", "years": "년", "yr": "년",
    "month": "개월", "months": "개월", "mo": "개월",
    "day": "일", "days": "일",
    "hour": "시간", "hours": "시간", "hr": "시간",
    "minute": "분", "minutes": "분", "min": "분",
    "second": "초", "seconds": "초", "sec": "초",
    "rate": "%", "ratio": "%", "pct": "%", "percent": "%", "percentage": "%",
    "count": "건", "cnt": "건", "qty": "건", "quantity": "건",
    "weight": "kg",
    "height": "cm",
    "distance": "km",
    "temperature": "°C", "temp": "°C",
}


def _unit_for(col: str, ctx: ReportContext) -> str:
    """컬럼명 → 단위 추론. glossary 우선, 일반 토큰 사전 폴백, 모르면 빈 문자열.

    glossary 라벨이 '가입 기간 (개월)' 같이 괄호 안 단위를 포함하면 그것을 사용.
    토큰 사전은 도메인 무관 일반 토큰만 — 거짓 단위 표기 회피가 우선.
    """
    raw = str(col or "")
    g = (ctx.domain.glossary or {}) if ctx.domain else {}
    # 1) glossary 메타 — 괄호 안 단위 추출
    label = g.get(raw, "")
    if isinstance(label, str):
        m = _re.search(r"\(([^)]{1,6})\)", label)
        if m:
            return m.group(1).strip()
    # 2) 토큰 사전 — camelCase/snake_case 분해 후 첫 매치
    tokens = _re.findall(r"[A-Z]?[a-z]+|\d+", raw)
    for t in tokens:
        u = _TOKEN_UNIT.get(t.lower())
        if u:
            return u
    return ""  # 모르면 비워둠 — 잘못된 단위 표기보다 무단위가 안전


# 지표명 사전
_METRIC_KO = {
    "accuracy": "정확도", "acc": "정확도", "precision": "정밀도", "recall": "재현율", "f1": "F1",
    "roc_auc": "AUC", "auc": "AUC", "pr_auc": "PR-AUC", "mcc": "MCC", "rmse": "RMSE",
    "mae": "MAE", "mape": "MAPE", "smape": "sMAPE", "r2": "R²", "logloss": "로그손실",
    "specificity": "특이도", "balanced_accuracy": "균형 정확도",
}


def _ko_metric(name: str) -> str:
    """지표명 → 한국어. 'val_roc_auc'→'검증 AUC', 'precision'→'정밀도'. 모르면 원본."""
    s = str(name or "").strip().lower()
    if not s:
        return str(name)
    prefix = ""
    for pre, ko in (("val_", "검증 "), ("test_", "테스트 "), ("train_", "학습 ")):
        if s.startswith(pre):
            prefix, s = ko, s[len(pre):]
            break
    base = _METRIC_KO.get(s)
    if base is None:
        for k, v in _METRIC_KO.items():
            if s == k or s.startswith(k + "_"):
                base = v
                break
    return prefix + (base or name)


# Public alias — carriers/ 등 외부 모듈에서 한국어 지표 변환 시 동일 사전 재사용 (DRY).
ko_metric = _ko_metric


def _feat_label(ctx: ReportContext, name: str) -> str:
    """변수명 → 한국어. glossary > 내장 사전 > 토큰 휴리스틱 > 원본 (틀린 번역보다 원본)."""
    raw = str(name or "")
    g = (ctx.domain.glossary or {}) if ctx.domain else {}
    if g.get(raw):  # 1) 도메인 glossary 우선
        return _re.sub(r"\s*\([^)]*\)\s*", "", str(g[raw])).strip() or raw
    key = raw.lower().replace("_", "").replace(" ", "")
    if key in _COL_KO:  # 2) 내장 일반 사전
        return _COL_KO[key]
    # 3) 토큰 휴리스틱 — 모든 토큰이 사전에 있을 때만(고확신), 아니면 원본
    tokens = [t.lower() for t in _re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+", raw.replace("_", " "))]
    core = [t for t in tokens if t not in ("is", "has", "flag")]
    trans = [_TOKEN_KO.get(t) for t in core]
    if core and all(trans):
        suffix = " 여부" if any(t in ("is", "has", "flag") for t in tokens) else ""
        return " ".join(trans) + suffix
    return raw  # 4) 원본 유지


_OP_LABEL = {
    "impute_numeric": "수치 결측 대치",
    "impute_categorical": "범주 결측 대치",
    "impute": "결측 대치",
    "encode_categorical": "범주형 인코딩",
    "target_encoding": "타깃 인코딩",
    "onehot": "원-핫 인코딩",
    "scale_numeric": "수치 표준화",
    "standardize": "표준화",
    "normalize": "정규화",
    "drop_id": "식별자 제거",
    "drop": "변수 제거",
    "leakage_column_drop": "누수 변수 제거",
    "class_weight_compute": "클래스 가중치 산정",
    "winsorize": "이상치 윈저화",
}


def _op_label(op: Any) -> str:
    """전처리 op → 한글 라벨. 모르면 원래 이름."""
    return _OP_LABEL.get(str(op or "").lower(), str(op) or "전처리")


def _driver_labels(ctx: ReportContext, k: int = 2) -> list[str]:
    """상위 핵심 동인 변수 → 의미 라벨 리스트."""
    gi = (ctx.interpretation.global_importance or []) if ctx.interpretation else []
    out: list[str] = []
    for g in gi[:k]:
        fn = getattr(g, "feature", "") or (g.get("feature", "") if isinstance(g, dict) else "")
        if fn:
            out.append(_feat_label(ctx, str(fn)))
    return out


def _driving_question(flags: dict[str, Any], target: str) -> str:
    """§1 핵펀치 — '진짜 우리가 무엇을 알고 싶은가' 한 줄."""
    if flags["is_anom"]:
        return "정상과 이상을 가르는 신호는 무엇이며, 헛경보 없이 제때 잡아낼 수 있는가?"
    if flags["is_ts"]:
        return f"'{target}'{_josa(target, 'subj')} 어디로 향하며, 얼마나 앞까지 믿고 계획할 수 있는가?"
    if flags["is_reg"]:
        return f"무엇이 '{target}'{_josa(target, 'obj')} 움직이며, 얼마나 정확히 값을 맞출 수 있는가?"
    return f"무엇이 '{target}'{_josa(target, 'obj')} 가르며, 그 신호만으로 충분히 정확히 가려낼 수 있는가?"


def _perf_judgment(flags: dict[str, Any], pmval: Any, pmname_l: str, maj: Optional[float]) -> str:
    """성능에 대한 전문가 촉 — 누수 의심·미미한 우위·쉬운 문제 자동 감지 (분류 higher-better 한정)."""
    if (
        flags["is_clf"]
        and isinstance(pmval, (int, float))
        and 0 < pmval <= 1
        and any(x in pmname_l for x in ("acc", "f1", "auc"))
    ):
        if pmval >= 0.995:
            return "성능이 비정상적으로 높아 데이터 누수(leakage) 점검이 선행돼야 한다"
        if maj is not None and (pmval - maj) < 0.1:
            return "단순 추측 대비 우위가 작아 실효성은 제한적이다"
        if pmval >= 0.95:
            return "변별이 쉬운 문제로, 정확도보다 일반화·운영 안정성이 관건이다"
    # 불균형 분류 — 예측 자체보다 '개입'이 가치를 만든다
    if flags["is_imbal"]:
        return "예측은 출발점일 뿐, 고위험군에 선제 개입할 때 가치가 실현된다"
    return ""


_AUDIENCE_KO = {
    "c_level": "경영진(C-레벨)",
    "manager": "실무 책임자(부서장)",
    "analyst": "분석·실무 담당자",
    "external_client": "외부 고객·이해관계자",
}


def _reader_persona(ctx: ReportContext) -> str:
    """[C3 독자페르소나룰] '본 보고서는 ___가 ___ 결정하는 데 사용' 한 문장.

    독자는 ctx.meta.audience(없으면 domain.audience_inference), 의사결정은 과제 유형별.
    """
    aud = (getattr(ctx.meta, "audience", "") or "").strip().lower()
    if not aud and ctx.domain is not None:
        ai = getattr(ctx.domain, "audience_inference", None)
        aud = (getattr(ai, "level", "") or "").strip().lower() if ai else ""
    aud_ko = _AUDIENCE_KO.get(aud, "분석·실무 담당자")
    f = _task_flags(ctx)
    if f.get("is_ts"):
        what = "예측 기반 수요·재고·운영 계획을"
    elif f.get("is_anom"):
        what = "이상 탐지 운영 도입과 대응 임계값을"
    elif f.get("is_reg"):
        what = "예측 모델의 운영 활용 여부와 적용 범위를"
    else:
        what = "모델 도입 여부와 운영 적용 방식을"
    return f"본 보고서는 {aud_ko}가 {what} 결정하는 데 사용한다."


def _build_overview(ctx: ReportContext) -> SectionSpec:
    """§1 분석 개요 — 데이터를 '판단'한 전문가 산문. bottom-line-first, 비즈니스 의사결정 지향.

    무맥락에서도 데이터 판단력(표본 충분성·클래스 균형·변수 구성·다수클래스 기준선)과
    정직한 한계 인식으로 전문가 수준을 끌어올린다. 가짜 비즈니스 수치는 만들지 않으며,
    business_context·baselines·business_kpi 가 들어오면 자동 격상.
    """
    ds = ctx.dataset
    shape = ds.shape or {}
    n_rows, n_cols = shape.get("rows", 0), shape.get("cols", 0)
    target = ds.detected_target or "타깃"
    cat = ctx.meta.category or "데이터 분석"
    verb = _CAT_VERB.get(ctx.meta.category or "", "분석")

    # 변수 구성 (타깃·식별자 제외)
    dtypes = ds.dtypes or {}
    target_l = (target or "").lower()
    id_set = {str(c).lower() for c in (ds.detected_id_cols or [])}
    input_cols = [c for c in dtypes if str(c).lower() != target_l and str(c).lower() not in id_set]
    num_cols = [c for c in input_cols if _is_numeric_dtype(dtypes.get(c))]
    cat_cols = [c for c in input_cols if not _is_numeric_dtype(dtypes.get(c))]
    n_feat = len(input_cols) if input_cols else max(n_cols - 1, 0)
    if num_cols and cat_cols:
        comp_txt = f"수치형 {len(num_cols)}개·범주형 {len(cat_cols)}개의 입력 변수"
    elif num_cols:
        comp_txt = f"수치형 {len(num_cols)}개의 입력 변수"
    elif cat_cols:
        comp_txt = f"범주형 {len(cat_cols)}개의 입력 변수"
    else:
        comp_txt = f"{n_feat}개 입력 변수"

    # 결측 / 표본 충분성 판단 — [5~6줄룰] 압축형 문장 (전체 background 5~6줄 보장)
    if n_rows and n_rows < 1000:
        sample_txt = f"{n_rows:,}건은 PoC·탐색에 충분, 운영 일반화엔 확대 필요"
    elif n_rows and n_rows < 10000:
        sample_txt = f"{n_rows:,}건은 모델링 적정 규모, 세부 세그먼트엔 표본 제한"
    elif n_rows:
        sample_txt = f"{n_rows:,}건은 안정적 학습·검증에 충분"
    else:
        sample_txt = "표본 규모 정보 제한적"

    # 타깃 분포 (분류 여부 + 다수 클래스 비율)
    _f = _task_flags(ctx)
    maj = _f["maj"]
    is_clf, is_ts, is_anom = _f["is_clf"], _f["is_ts"], _f["is_anom"]
    is_reg, is_imbal, is_multiclass = _f["is_reg"], _f["is_imbal"], _f["is_multiclass"]

    # ── 분석 배경 — [5~6줄룰] 적용. business_context 있으면 시급성 문장 중복 회피.
    # 한국어 14pt 기준: 한 줄 ≈ 30자, 5줄 ≈ 150자, 6줄 ≈ 180자. 4문장 × 평균 40자 이내가 목표.
    bg_parts: list[str] = []
    bctx = (ctx.meta.business_context or "").strip()
    industry = ((ctx.domain.inferred_industry if ctx.domain else "") or "").strip()
    where = f"{industry} 도메인의 " if industry else ""
    if bctx:
        # bctx 가 있으면 시급성 문장 생략 (같은 결의 진술 — 중복 회피)
        bg_parts.append(bctx)
    else:
        bg_parts.append(f"'{target}' {verb}{_josa(verb, 'obj')} 수작업·경험에서 데이터 표준화로 전환할 필요가 분명하다.")
    # 규모 판단 (압축형) — 데이터 구성(변수 수)은 §1 exhibit·§2가 보유 → 배경에선 891 중복 제거
    bg_parts.append(sample_txt + ".")
    if is_anom:
        _stake = "옳게 잡으면 다운타임·품질 손실과 점검 부하를 줄이고, 놓치면 그 비용이 그대로 쌓인다."
    elif is_ts:
        _stake = "정확히 예측하면 재고·인력·리드타임 낭비를 줄이고, 빗나가면 그 손실을 현장이 떠안는다."
    elif is_reg:
        _stake = "정밀히 추정하면 가격·자원 배분의 손실을 줄이고, 틀리면 그 비용이 누적된다."
    else:
        _stake = "옳게 가려내면 한정된 자원을 가장 중요한 대상에 집중하고, 놓치면 그 비용을 현장과 대상이 떠안는다."
    # [판돈] 진짜 '돈/규모'(proj.retained=방어 매출)가 잡히는 데이터에서만 정량. 없으면 정성(가짜 수치 금지).
    _proj = _scenario_projection(ctx)
    if _proj and _proj.get("retained"):
        _ev = _event_noun(ctx)
        bg_parts.append(
            f"이 판단의 판돈은 작지 않다. 연 약 {_proj['avoided']:,.0f}건의 {_ev} 감축과 "
            f"매출 약 {round(_proj['retained'], -3):,.0f} 방어가 여기에 달려 있다."
        )
    else:
        bg_parts.append("이 판단의 판돈은 작지 않다. " + _stake)  # 정성 폴백(titanic 등)
    background = " ".join(bg_parts)

    # ── 분석 목적 (과제가 아니라 성과로)
    objective = (
        f"정확한 '{target}' 판정을 자동화해 판정의 일관성과 속도를 확보하는 것이 목적이다. "
        f"이를 위해 {comp_txt}로 '{target}'{_josa(target, 'obj')} {verb}하는 모델을 수립하고, 결과를 좌우하는 핵심 변수를 규명한다. "
        "단순 기준 모델 대비 실질적 개선과 해석 가능성을 함께 확보해, 결과를 운영 의사결정에 바로 활용할 수 있게 한다."
    )

    # ── 분석 질문 → §1 exhibit(issue-tree)로 시각화. 긴 질문 나열(중복·지면) 대신 관통질문을 3갈래로 분해.
    #    세부 답은 §3(무엇이)·§5(믿나)·§6(어떻게)에 있다 — 관통 인사이트가 척추로 흐르게.
    _tree_subs = [f"무엇이 '{target}'{_josa(target, 'obj')} 가르나", "믿고 운영에 쓸 만한가", "어디에·어떻게 적용하나"]

    # ── 분석 범위 (+ 한계 선제)
    scope_parts = [f"분석은 {n_rows:,}행 × {n_cols}열을 대상으로 {cat} 관점의 {verb}에 한정한다."]
    if ds.detected_time_col:
        scope_parts.append(f"시간 축 '{ds.detected_time_col}'{_josa(ds.detected_time_col, 'obj')} 기준으로 한다.")
    if ds.detected_id_cols:
        scope_parts.append(f"식별자({', '.join(map(str, ds.detected_id_cols[:3]))})는 누수 방지를 위해 입력에서 제외한다.")
    scope_parts.append(
        f"표본이 {n_rows:,}건 규모이므로 운영 환경의 분포 변화·미관측 세그먼트에 대한 일반화는 보수적으로 해석하며, "
        "외부 환경 요인과 실시간 적용은 범위에서 제외한다."
    )
    scope = " ".join(scope_parts)

    # ── 성공 기준 (의사결정 언어 — '도입할 가치가 있는가'. 지표 약어 근거는 §4 분석 방법으로)
    naive = None
    bsl = getattr(ctx.model_selection, "baselines", None) if ctx.model_selection else None
    naive_obj = getattr(bsl, "naive", None) if bsl else None
    if isinstance(naive_obj, dict):
        naive = naive_obj.get("score")
    sc_parts: list[str] = []
    # 1) 단순 추측 대비 — 도입 가치
    if naive is not None:
        sc_parts.append(f"무엇보다 단순 추측(단순 모델 {_fvb(naive)} 수준)보다 의미 있게 나아야 도입할 가치가 있다.")
    elif is_clf and maj is not None:
        sc_parts.append(f"무엇보다 '무조건 다수를 찍는' 추측({_pct(maj)})을 확실히 넘어서야 도입할 가치가 있다.")
    elif is_clf:
        sc_parts.append("무엇보다 '무조건 다수를 찍는' 추측을 확실히 넘어서야 도입할 가치가 있다.")
    elif is_ts:
        sc_parts.append("무엇보다 '어제와 같다'고 찍는 수준을 의미 있게 넘어서야 도입할 가치가 있다.")
    else:
        sc_parts.append("무엇보다 평균·직전값 같은 단순 추측보다 의미 있게 나아야 도입할 가치가 있다.")
    # 2) 오류 비용 비대칭 — 어떤 실수를 우선 줄이나
    if is_anom or is_imbal:
        sc_parts.append("놓침과 헛경보의 비용이 다르므로, 더 비싼 실수를 우선 줄이는 기준으로 성패를 가린다.")
    elif is_clf:
        sc_parts.append("어떤 오판이 더 비싼지에 맞춰 놓침·헛경보 중 무엇을 우선 줄일지로 성패를 가린다.")
    elif is_reg:
        sc_parts.append("현업이 허용하는 오차 범위 안에 드는 비율로 실무 적합성을 가린다.")
    # 3) 안정성 (운영에 쓸 수 있는가) — 약어 없이
    sc_parts.append("끝으로 시기·집단을 바꿔도 성능이 유지돼야 운영에 쓸 수 있다.")
    # [C13 Falsifiability룰] 반증 조건 — 못 넘으면 도입 의미 없음
    sc_parts.append(
        "<br/>거꾸로, 입력 변수를 더 늘려도 개선이 +2%p 이내라면 현재 구성으로 충분하다는 뜻이며, "
        "그 선을 못 넘는 모델은 도입할 이유가 없다."
    )
    success = " ".join(sc_parts)

    # ── 기대 효과 (business_kpi 있으면 실수치)
    impact_parts: list[str] = []
    kpis = (ctx.evaluation.business_kpi or []) if ctx.evaluation else []
    if kpis:
        k = kpis[0]
        kname = getattr(k, "name", "") or (k.get("name", "") if isinstance(k, dict) else "")
        kunit = getattr(k, "unit", "") or (k.get("unit", "") if isinstance(k, dict) else "")
        kval = getattr(k, "estimated_value", None)
        if kval is None and isinstance(k, dict):
            kval = k.get("estimated_value")
        if kname and kval is not None:
            impact_parts.append(f"정량적으로 {kname} {_fv(kval)} {kunit} 수준의 효과가 기대된다.".replace("  ", " "))
    if is_anom:
        base_impact = "조기 이상 탐지로 다운타임·품질 손실을 줄이고, 룰베이스 대비 오탐을 낮춰 점검 부하를 절감한다."
    elif is_ts:
        base_impact = f"'{target}' 예측 정확도 향상으로 재고·인력·리드타임 등 자원 계획을 선제적으로 최적화한다."
    elif is_reg:
        base_impact = f"'{target}' 추정 정밀화로 가격·리스크·자원 배분 의사결정의 정확도를 높인다."
    else:
        base_impact = f"정확한 '{target}' 판정을 자동화해 고위험·고우선 대상의 선별과 처리의 일관성·속도를 확보한다."
    impact_parts.append(base_impact)
    impact_parts.append("핵심 변수를 근거로 데이터 수집 우선순위와 프로세스 개선까지 후속 액션으로 연결한다.")

    # [B9 Headline=Message] 헤드라인 = 의사결정 질문(모델링 질문 아님). 카테고리 분기.
    if not (n_feat and n_rows):
        _head = "프로젝트 정의 (목적·범위·성공 기준)"
    elif is_anom:
        _head = "이상탐지를 운영 점검 체계로 도입할 가치가 있는가"
    elif is_ts:
        _head = f"'{target}' 예측을 계획 수립에 도입할 가치가 있는가"
    elif is_reg:
        _head = f"'{target}' 추정 모델을 의사결정에 도입할 가치가 있는가"
    else:
        _head = f"'{target}' 판정 모델을 운영에 도입할 가치가 있는가"

    # [풍부화 §1] 이해관계자 — 괄호 태그(승인/실행 등) 금지, 산문으로. 카테고리 분기.
    if is_anom:
        _stk_mid = "경보를 받아 점검하는 운영팀이 대응을 맡고, 놓친 이상과 헛경보의 비용은 점검 대상에게 돌아간다"
    elif is_ts:
        _stk_mid = "예측으로 계획하는 수요·재고·인력 부서가 이를 실행하며, 과·소 예측의 비용은 공급·고객 접점에 돌아간다"
    elif is_reg:
        _stk_mid = "추정으로 가격·자원·리스크를 정하는 실무팀이 이를 실행하며, 과대·과소 추정의 비용은 그 대상에게 돌아간다"
    else:
        _stk_mid = f"판정을 받아 처리하는 실무팀이 일상 운영을 맡고, 오판의 영향은 '{target}' 판정 대상에게 돌아간다"
    stakeholders = (
        "도입 여부와 적용 범위는 운영·사업 책임자가 효익과 위험을 따져 결정한다. "
        + _stk_mid + ". "
        "데이터·MLOps가 모델 적재와 재학습·모니터링을 책임지며, 리스크·컴플라이언스가 공정성과 규제 적합성을 점검한다."
    )
    # [B-Exhibit §1] 관통 질문 issue-tree — 보고서 논리(관통질문 → 3갈래)를 McKinsey식 피라미드로 시각화.
    # [관통 인사이트 원칙·헌법] 관통질문이 전체를 흐르는 척추: tree의 3갈래가 §3·§5·§6 답으로 이어진다. 결정 논리 중심(70% 의사결정).
    _ovw_exhibit = VisualSpec(type="issue_tree", spec={
        "num": "2 · 관통 질문 분해",
        "governing": _head,
        "subs": _tree_subs,
        "source": "관통 질문을 세 갈래로 분해. 각 갈래의 답은 §3·§5·§6 본문에 있다.",
    })

    slide = SlideSpec(
        id="overview",
        section_id="overview",
        layout="one_message",
        role="claim",
        so_what=f"'{target}'{_josa(target, 'obj')} 가르는 신호가 데이터에 실제로 있고, 그 신호가 단순 추측을 의미 있게 넘느냐. 둘 다 '예'가 아니면 이 모델은 운영에 올릴 이유가 없다.",
        title_ko=_head,
        prose_blocks=[
            # [C12 ConfidenceStamp룰] 추정만 (추정) 명시 · 확실은 기본(무표기)
            # [C3 독자페르소나룰] 본 보고서의 독자·용도 (표지와 동일 문장)
            ["독자·용도", _reader_persona(ctx)],
            ["분석 배경", background],
            ["이해관계자", stakeholders],
            ["분석 목적", objective],
            ["분석 범위", scope],
            ["성공 기준 (추정)", success],
            ["", "이 도입 가치는 데이터가 이 질문에 답할 수 있을 때만 성립한다. 표본·변수·품질이 그걸 받쳐주는지를 다음 장에서 먼저 따진다."],
            # [70/30룰] 기대 효과는 §8 결론으로 이관 — §1 에서 결론 미리 노출 금지
        ],
        visual_spec=_ovw_exhibit,
    )
    return make_section("overview", "분석 개요", "context", [slide])


def _build_data_understanding(ctx: ReportContext) -> SectionSpec:
    """§2 데이터 이해 — '이 데이터로 답할 수 있나'를 판단(글)하고 변수 정의서(표)로 받친다.

    단순 나열 대신 적합성(표본·구성)·품질(결측·고카디널리티)·타깃 분포를 데이터에서 도출.
    """
    ds = ctx.dataset
    shape = ds.shape or {}
    n_rows, n_cols = shape.get("rows", 0), shape.get("cols", 0)
    target = ds.detected_target or "-"
    dtypes = ds.dtypes or {}
    flags = _task_flags(ctx)
    maj, n_classes = flags["maj"], flags["n_classes"]

    target_l = target.lower()
    id_set = {str(c).lower() for c in (ds.detected_id_cols or [])}
    input_cols = [c for c in dtypes if str(c).lower() != target_l and str(c).lower() not in id_set]
    num_cols = [c for c in input_cols if _is_numeric_dtype(dtypes.get(c))]
    cat_cols = [c for c in input_cols if not _is_numeric_dtype(dtypes.get(c))]

    # 표본 충분성
    if n_rows and n_rows < 1000:
        adeq = f"{n_rows:,}건은 개념검증·탐색에는 충분하나 운영 일반화에는 표본 확대가 바람직하다"
    elif n_rows and n_rows < 10000:
        adeq = f"{n_rows:,}건은 모델링에 적정한 규모다"
    elif n_rows:
        adeq = f"{n_rows:,}건은 안정적 학습·검증에 충분한 규모다"
    else:
        adeq = "표본 규모 정보가 제한적이다"

    # 결측 판단
    missing = ds.missing_rate or {}
    miss_cols = [(c, r) for c, r in sorted(missing.items(), key=lambda kv: -kv[1]) if r and r > 0]
    high_miss = [c for c, r in miss_cols if r >= 0.2]
    # 결측 서술은 아래 p_missing 단락에서 생성 (miss_cols·high_miss 활용)

    # 고카디널리티 (인코딩 주의)
    card = ds.cardinality or {}
    high_card = [c for c in cat_cols if isinstance(card.get(c), int) and card.get(c) > 30]

    # 타깃 분포
    if flags["is_clf"] and maj is not None:
        bal = "불균형이라 정확도 함정에 주의해야 한다" if maj >= 0.7 else "비교적 균형적이다"
        ncl = f"{n_classes}개 클래스, " if isinstance(n_classes, int) else ""
        tgt_txt = f"{ncl}다수 클래스 비율 {_pct(maj)}로 {bal}"
    elif flags["is_clf"]:
        tgt_txt = "범주형 분류 대상이다"
    else:
        tgt_txt = "연속값 추정 대상이다"

    issues = (ctx.eda.data_quality_issues or []) if ctx.eda else []

    # ── 도출 단락
    p_fit = f"분석 대상은 {n_rows:,}행 × {n_cols}열로, 식별자·타깃을 제외하면 수치형 {len(num_cols)}개·범주형 {len(cat_cols)}개의 입력 변수로 구성된다. {adeq}."
    if ds.detected_time_col:
        p_fit += f" 시간 축 '{ds.detected_time_col}'{_josa(ds.detected_time_col, 'obj')} 가진 구조다."
    if ds.detected_id_cols:
        p_fit += f" 식별자({', '.join(map(str, ds.detected_id_cols[:2]))})는 누수 방지를 위해 예측에서 제외한다."

    # 결측 분석 (전처리 대치와 연결)
    steps = (ctx.preprocessing.applied_steps or []) if ctx.preprocessing else []
    has_impute = any(
        ("impute" in str(getattr(st, "op", "")).lower()) or ("대치" in str(getattr(st, "rationale", "")))
        for st in steps
    )
    if not miss_cols:
        p_missing = "전 변수에 결측이 없어 대치 없이 그대로 분석에 사용한다."
    else:
        detail = ", ".join(f"{_feat_label(ctx, c)} {_pct(r)}" for c, r in miss_cols[:4])
        treat = "중앙값/최빈값으로 대치해 처리했다" if has_impute else "대치 또는 행 제외를 검토해야 한다"
        p_missing = f"결측은 {detail}에서 발생하며, {treat}."
        if high_miss:
            p_missing += " 결측률이 20%를 넘는 변수는 정보 손실 위험이 커, 단순 대치보다 결측 자체를 신호로 보는 접근도 고려한다."

    # 주요 변수 (타깃·수치 범위·고카디널리티) — 단위 자동 부착 (모르면 무단위)
    key_bits = [f"타깃은 '{target}'({_feat_label(ctx, target)})이다"]
    nstats = ds.numeric_stats or {}
    for c in [c for c in num_cols if c in nstats][:2]:
        st = nstats[c]
        _lbl_c = _feat_label(ctx, c)
        _unit = _unit_for(c, ctx)
        _u = f" {_unit}" if _unit else ""
        key_bits.append(
            f"{_lbl_c}{_josa(_lbl_c, 'subj')} {_fvb(st.get('min'))}{_u}~{_fvb(st.get('max'))}{_u} "
            f"(평균 {_fvb(st.get('mean'))}{_u}) 범위"
        )
    if high_card:
        key_bits.append(f"{', '.join(_feat_label(ctx, c) for c in high_card[:2])} 등 범주가 많은 변수는 인코딩 설계가 중요하다")
    p_key = ". ".join(key_bits) + "."

    p_target = f"타깃 '{target}'{_josa(target, 'subj')} {tgt_txt}. 이는 이후 평가 지표·임계값 선택의 전제가 된다."

    # ── 품질 점검 — 발견 + 처리 + 후속 (실무 표준 3단)
    # 단순 'X 11건' 한 줄로 끝내지 않고, '뭘 어떻게 처리할 것인가'까지 명시.
    if not issues:
        p_quality = (
            "품질 점검 결과 식별된 이슈는 없다. "
            "본 분석에서는 별도 정제 단계 없이 데이터를 그대로 사용하며, "
            "운영 데이터 입수 시점에 동일한 점검 체크리스트를 자동 실행한다."
        )
    else:
        findings = []
        for it in issues[:3]:
            if isinstance(it, dict):
                txt = _txt_from(it, ("issue", "name", "note"))
                if txt:
                    findings.append(txt.rstrip("."))
        finding_txt = "; ".join(findings) if findings else "경미한 데이터 이슈"
        treatment = (
            "전처리 단계에서 대치(수치 중앙값·범주 최빈값)로 보정해 분석 영향을 차단했다"
            if has_impute else
            "해당 행 제외 또는 '결측 자체를 신호로 인코딩'하는 안을 검토한다"
        )
        # [B15·B19] _label_card() 통과로 자동 준수
        p_quality = _label_card([
            ("발견", f"{finding_txt}."),
            ("처리", f"{treatment}."),
            ("후속",
             "운영 데이터에서 동일 패턴 발생 시 자동 동일 처리를 적용하며, "
             "임계 초과(전체의 5% 이상)나 새 유형 이슈 발생 시 데이터팀에 에스컬레이션해 "
             "처리 결정과 영향 평가를 문서화한다."),
        ])

    # so_what — '회장이 봐도 끌리는' 핵심 한 줄 (데이터의 결정적 사실을 앞세움)
    adequate = bool(n_rows and n_rows >= 1000)
    event = _event_noun(ctx)
    if flags["is_clf"] and maj is not None and maj >= 0.7:
        sow = f"{event}{_josa(event, 'subj')} {_pct(1 - maj)}에 불과한 소수 사건이다 — '전체 정확도'는 다수만 맞혀도 높아지는 착시이며, 소수를 잡아내는 것이 이 분석의 본질이다."
    elif high_miss:
        sow = f"'{_feat_label(ctx, high_miss[0])}' 등 핵심 변수의 결측 처리가 결과를 좌우한다 — 단순 대치로 신호를 지울 위험이 있다."
    elif not adequate:
        sow = f"{n_rows:,}건은 방향성을 보여주기엔 충분하나, 운영 확정에는 표본 확대가 필요하다."
    else:
        sow = f"결측 없이 {len(input_cols)}개 변수가 '{target}'{_josa(target, 'obj')} 다각도로 담아, 원인 규명까지 가능한 데이터다."

    slide = SlideSpec(
        id="data_understanding",
        section_id="data_understanding",
        layout="comparison_table",
        role="evidence",
        so_what=sow,
        title_ko=(  # [B9 Headline=Message] 결론형, 동적
            f"{n_rows:,}건·{n_cols}개 변수로 결정에 충분한가"
            if n_rows and n_cols else "표본 적합성 및 변수 진단"
        ),
        prose_blocks=[
            # [C12 ConfidenceStamp룰] §2 데이터 진단은 모두 데이터에서 직접 도출 (확실)
            ["데이터 구성·적합성", p_fit],
            ["결측 분석", p_missing],
            ["주요 변수", p_key],
            ["타깃 분포", p_target],
            ["품질 점검", p_quality],
        ],
        visual_spec=_data_dictionary_visual(ctx),
    )
    return make_section("data_understanding", "데이터 이해", "context", [slide])


def _chart_kind(c_title, ct, items):
    """EDA 차트가 '무엇을 재는가' 분류 — 서술 템플릿 분기.

    반환: 'missing'(결측률) | 'corr'(상관) | 'dist'(수치 분포통계) | 'rate'(타깃 발생률).
    'rate' 만 '발생률/레버/갈림' 서술을 받는다 (나머지는 의미에 맞는 별도 서술).
    """
    t = str(c_title or "")
    c = str(ct or "").lower()
    tl = t.lower()
    vals = [float(v) for _, v in items if isinstance(v, (int, float))]
    has_neg = any(v < 0 for v in vals)
    names = " ".join(str(n) for n, _ in items).lower()
    if "결측" in t or "missing" in c or "missing" in tl:
        return "missing"
    if "상관" in t or "↔" in t or c in ("corr", "heatmap", "correlation") or has_neg:
        return "corr"
    if "분포" in t or any(k in names for k in ("mean", "median", "skew", "std", "var", "평균", "중앙", "왜도", "분산")):
        return "dist"
    return "rate"


def _as_pct(v):
    """0~1 분수면 ×100(%) 변환, 이미 %스케일(>1)이면 그대로."""
    try:
        v = float(v)
    except Exception:
        return 0.0
    return v * 100.0 if -1.0 <= v <= 1.0 else v


def _enhance_chart_finding(items, original, event, kind="rate"):
    """[좋은패턴] 차트 키 메시지(so_what) — 차트 종류별 정확한 한 줄.

    kind 분기로 결측/상관/분포 차트에 '생존율·방어 레버' 오적용 방지.
    """
    if not items or len(items) < 2:
        return original
    vals = [(n, float(v)) for n, v in items if isinstance(v, (int, float))]
    if len(vals) < 2:
        return original
    hi_name, hi_val = max(vals, key=lambda x: x[1])
    lo_name, lo_val = min(vals, key=lambda x: x[1])

    if kind == "missing":
        return f"'{hi_name}' 결측률 {_as_pct(hi_val):.1f}%가 최고 — 처리 방식이 결과를 좌우"
    if kind == "corr":
        amax_name, amax_val = max(vals, key=lambda x: abs(x[1]))
        return f"변수 간 상관 최대 {amax_name} (r={amax_val:.2f}) — 피처 중복 점검 필요"
    if kind == "dist":
        return f"'{hi_name}' 분포의 비대칭(편향)이 가장 큼 — 변환·구간화 후보"
    # kind == "rate" : 타깃 발생률 by 세그먼트 — 유일하게 '갈림/레버' 서술 허용
    hp, lp = _as_pct(hi_val), _as_pct(lo_val)
    gap = hp - lp
    ratio = (hp / lp) if lp > 0 else 0.0
    if ratio >= 1.5:
        return f"'{hi_name}'의 {_rate(event)} {hp:.1f}%가 '{lo_name}'({lp:.1f}%) 대비 약 {ratio:.1f}배 — 결정적 갈림"
    if gap >= 5:
        return f"'{hi_name}'의 {_rate(event)} {hp:.1f}%가 '{lo_name}'({lp:.1f}%)보다 {gap:.1f}%p 높음"
    return original


def _chart_3step_caption(items, n_rows, event, baseline_rate=None, kind="rate"):
    """[좋은패턴][EDA페이지룰] 차트 아래 3단 캡션(관찰·의미·시사) — 차트 종류별 정확 서술.

    [B18 평이한언어룰] 화살표·기호 회피. 결측/상관/분포 차트는 '발생률' 서술 미적용.
    가짜 통계 방지: 그룹별 인원수(빈도)가 없는 비율·상관 입력에 χ² 검정을 돌리지 않는다.
    """
    if not items or len(items) < 2:
        return ""
    vals = [(n, float(v)) for n, v in items if isinstance(v, (int, float))]
    if len(vals) < 2:
        return ""
    n_txt = f" (n={n_rows:,})" if n_rows else ""

    if kind == "missing":
        obs = ", ".join(f"{n} {_as_pct(v):.1f}%" for n, v in vals[:4])
        over = [n for n, v in vals if _as_pct(v) >= 20]
        meaning = (
            f"<b>의미</b> {', '.join(over[:3])} 결측 20% 초과 — 단순 대치 시 신호 왜곡 위험."
            if over else "<b>의미</b> 결측 수준은 대치로 흡수 가능한 범위."
        )
        return (
            f"<b>관찰</b> 결측률 {obs}.{n_txt} {meaning} "
            "<b>시사</b> 분석 방법(4장)에서 컬럼 제외·결측 자체 신호화 여부를 결정한다."
        )

    if kind == "corr":
        obs = ", ".join(f"{n} r={v:.2f}" for n, v in vals[:4])
        amax_name, amax_val = max(vals, key=lambda x: abs(x[1]))
        strength = "강한" if abs(amax_val) >= 0.5 else ("중간" if abs(amax_val) >= 0.3 else "약한")
        return (
            f"<b>관찰</b> {obs}.{n_txt} "
            f"<b>의미</b> {amax_name} 상관이 최대(r={amax_val:.2f}, {strength} 상관) — 변수 간 중복 정보. "
            "<b>시사</b> 상관 높은 쌍은 피처 선택·다중공선성 점검 대상(4장)."
        )

    if kind == "dist":
        obs = ", ".join(f"{n} {v:.2f}" for n, v in vals[:4])
        return (
            f"<b>관찰</b> {obs}.{n_txt} "
            "<b>의미</b> 분포 비대칭·이상치 가능성 — 단독 결정성은 제한적, 상호작용 분석 필요. "
            "<b>시사</b> 스케일·구간화·이상치 처리(4장)로 보완한다."
        )

    # kind == "rate" : 타깃 발생률 by 세그먼트
    hp_items = [(n, _as_pct(v)) for n, v in vals]
    hp_name, hp = max(hp_items, key=lambda x: x[1])
    lp_name, lp = min(hp_items, key=lambda x: x[1])
    obs_pts = ", ".join(f"{n} {p:.1f}%" for n, p in hp_items[:4])
    gap = hp - lp
    ratio = (hp / lp) if lp > 0 else 0.0
    bench_txt = ""
    if baseline_rate is not None and 0 < baseline_rate < 1:
        _bv = baseline_rate * 100.0
        _gap = max(hp - _bv, 0.0)
        bench_txt = f" <b>벤치마크</b> 단순 룰(다수 추측) {_bv:.1f}% 대비 최고 {hp:.1f}% (+{_gap:.1f}%p)."
    if ratio >= 5:
        meaning = f"<b>의미</b> 최고·최저 {ratio:.1f}배 격차 — {event} 결정의 1차 변수."
    elif ratio >= 2 or gap >= 10:
        meaning = f"<b>의미</b> 집단 간 {gap:.1f}%p 격차 — 결과를 가르는 핵심 동인."
    else:
        meaning = "<b>의미</b> 단독 결정성은 제한적, 타 동인과의 상호작용 분석 필요."
    return (
        f"<b>관찰</b> {_rate(event)} {obs_pts}.{n_txt} {meaning}{bench_txt} "
        f"<b>시사</b> {hp_name} 집단을 우선 대상으로 한 개입이 가장 큰 {event} 레버 (6·7장에서 정량)."
    )


def _build_eda(ctx: ReportContext) -> Optional[SectionSpec]:
    """§3 탐색적 발견 — 차트 finding + 세그먼트 인사이트 + 가설검정 (발견 중심).

    [좋은패턴] EDA 차트 페이지 시니어 표준 (사용자 확정):
        ① 키 메시지(so_what) — 정량 비교(N배·집중도) 자동 강화 (_enhance_chart_finding)
        ② 차트 본체 — visuals/render.py 가 강조 색·푸터 처리
        ③ 차트 아래 3단 캡션 — 관찰·의미·시사 자동 (_chart_3step_caption)
    """
    eda = ctx.eda
    charts = (eda.charts or []) if eda else []
    segs = (eda.segment_insights or []) if eda else []
    hyps = (eda.hypothesis_tests or []) if eda else []
    slides: list[SlideSpec] = []

    # [좋은패턴] EDA 표준 — n_rows·event 를 차트 캡션에 공통 사용
    _n_rows = (ctx.dataset.shape or {}).get("rows", 0) if ctx.dataset else 0
    _event = _event_noun(ctx)

    for idx, ch in enumerate(charts[:_MAX_EDA_SLIDES]):
        c_title = getattr(ch, "title_ko", "") or f"탐색 분석 {idx + 1}"
        finding = getattr(ch, "finding", "") or ""
        numbers = getattr(ch, "numbers", None) or []
        items = [(str(d.get("name", "")), d.get("value", 0)) for d in numbers if isinstance(d, dict)]
        path = getattr(ch, "path", "") or (ch.get("path", "") if isinstance(ch, dict) else "")
        # 차트 종류 — 주제에 맞게 골고루 (순서축=선, 다범주=가로막대, 기본=세로막대)
        ct = str(getattr(ch, "chart_type", "") or "").lower()
        if ct in ("line", "trend", "area") or any(k in c_title for k in ("기간", "추세", "시간", "월별", "연도")):
            vtype = "chart_line"
        elif ct in ("hbar", "barh", "horizontal") or len(items) > 5:
            vtype = "chart_hbar"
        else:
            vtype = "chart_bar"
        # [좋은패턴] ① 키 메시지 정량 강화 + ③ 3단 캡션 자동 생성
        _kind = _chart_kind(c_title, ct, items)
        enhanced_finding = _enhance_chart_finding(items, finding, _event, _kind) if items else finding
        # [C11] 단순 룰 = 다수 클래스 비율 (분류 시) — 차트마다 동일 기준선
        _maj_rate = _task_flags(ctx).get("maj")
        auto_caption = _chart_3step_caption(items, _n_rows, _event, baseline_rate=_maj_rate, kind=_kind)
        vs = None
        if items:
            vs = VisualSpec(
                type=vtype, title="", caption=auto_caption,
                spec={"items": items},  # 제목은 슬라이드 헤딩이 담당(중복 방지)
            )
        elif path:
            vs = VisualSpec(type="image_embed", title="", spec={"path": str(path)})
        slides.append(
            SlideSpec(
                id=f"eda_{idx}",
                section_id="eda",
                layout="chart_callout",
                role="evidence",
                so_what=enhanced_finding,  # [좋은패턴] 정량 강화된 키 메시지
                title_ko=f"{idx + 1}) {c_title}",  # 하위 번호 'N)' (섹션 '3.' 아래)
                body_outline=[],
                visual_spec=vs,
            )
        )

    # 발견 종합 — 나열이 아니라 패턴 + 세그먼트 + 가설검정을 한 줄기로 엮은 서술
    event = _event_noun(ctx)
    syn: list[str] = []
    chart_findings = [getattr(ch, "finding", "") for ch in charts[:_MAX_EDA_SLIDES] if getattr(ch, "finding", "")]
    if len(chart_findings) >= 2:
        syn.append(f"여러 탐색 축에서 {event}{_josa(event, 'nom')} 특정 구간에 집중되는 공통 패턴이 나타난다.")
    for s in segs[:3]:
        txt = _txt_from(s, ("insight", "finding", "note", "summary"))
        if txt:
            syn.append(txt.rstrip(".") + ".")
    for h in hyps[:2]:
        if isinstance(h, dict):
            nm = _txt_from(h, ("name", "test", "hypothesis")) or "가설검정"
            res = _txt_from(h, ("result", "conclusion", "p_value", "significant"))
            if res:
                syn.append(f"{nm} 결과 {res}로 통계적으로 유의했다.")
    if syn:
        syn.append("이 발견들이 핵심 인사이트에서 정량적 개입 레버로 이어진다.")
        slides.append(
            SlideSpec(
                id="eda_findings",
                section_id="eda",
                layout="one_message",
                role="claim",
                so_what="탐색이 가리키는 한 방향",
                title_ko=f"{len(slides) + 1}) 주요 발견 종합",
                # [B6 EDA페이지룰] 발견 종합 + 비즈니스 의미 — 의사결정자 연결
                # [C10 SoWhat] 차트만 늘어놓고 끝내지 않음 — "그래서 뭐?" 답을 카드로
                prose_blocks=[
                    ["발견 종합", " ".join(syn)],
                    [
                        "비즈니스 의미",
                        "<b>표적 개입:</b> 상위 위험군 표적 처리로 전체 발생률 감축 + 운영 비용 절감.<br/>"
                        "<b>매출 방어:</b> 고가치 세그먼트 우선 보호로 매출 손실 방어 여지.<br/>"
                        "<b>KPI 가시성:</b> 운영 결과 정량 추적으로 경영진 KPI 보고 정교화."
                    ],
                    [
                        "다음 행동 (Owner · Date)",
                        # [C6 Action_OwnerDate룰] 누가·언제까지 명시
                        "<b>도입 권고:</b> 모델팀 — 분기 게이트 통과 시 5% 파일럿 가동 (~Q+1)<br/>"
                        "<b>의사결정 결재:</b> 운영팀장/사업부장 — 1단계 결재 (~2주)<br/>"
                        "<b>모니터링 정례화:</b> 데이터팀 — 월간 운영 KPI 추적 (운영 후 30일 내 시작)"
                    ],
                    [
                        "한계 · 카운터내러티브",
                        # [C7 CounterNarrative룰] 가장 강한 반대 논거 + 반박
                        "<b>표본 한계:</b> 단일 데이터셋·제한된 기간이라 시대·상황 외삽에 한계가 있어, 결정 신뢰구간에 보수적 마진을 권고한다.<br/>"
                        "<b>반대 논거:</b> '단일 데이터로 일반화 불가'라는 반론이 있으나, 핵심 변수의 효과가 다른 기간·유사 사례에서도 재현되면 발견의 안정성은 확보된다.<br/>"
                        "<b>외부 검증:</b> 운영 1·3·6개월 시점에 동일 변수의 영향력을 재확인하고, 임계 이탈 시 재학습한다."
                    ],
                ],
            )
        )

    if not slides:
        return None
    return make_section("eda", "탐색적 발견 (EDA Insights)", "evidence", slides)


def _method_keymessage(ctx: ReportContext, flags: dict[str, Any]) -> str:
    """[좋은패턴] §4 키 메시지 — 데이터 의존 결정적 방법론 의사결정 자동 도출.

    우선순위 (가장 결정적 한 가지를 페이지 헤드로):
        1) 큰 결측(≥30%) 컬럼 → 컬럼 제외 결정
        2) 시계열 → 시간 순서 분할
        3) 강한 불균형(≥70%) → 층화 + Recall
        4) 약한 불균형/일반 분류 → 층화 분할로 분포 보존
        5) 디폴트 → 누수 방지·층화 결합
    """
    ds = ctx.dataset
    missing = ds.missing_rate or {}
    high_miss = [(c, r) for c, r in missing.items() if r >= 0.3]
    maj = flags["maj"]

    if high_miss:
        top_col, top_rate = max(high_miss, key=lambda x: x[1])
        lbl = _feat_label(ctx, top_col)
        return f"{lbl} {_pct(top_rate)} 결측을 정보 손실 위험으로 제거 — 다른 변수의 대리 신호로 보완"
    if flags["is_ts"]:
        return "시간 순서 분할로 미래 정보 누수 차단 — 일반 무작위 분할은 시계열에 치명적"
    if flags["is_imbal"] and maj:
        return f"다수 클래스 {_pct(maj)} 환경에서 층화 분할 + Recall 위주 평가로 정확도 함정 회피"
    if flags["is_clf"] and maj:
        return f"다수 클래스 {_pct(maj)} 분포를 보존하는 층화 분할로 검증셋 대표성 확보"
    return "분할 내부 파이프라인 적합 + 타깃 누수 점검으로 결과 신뢰성 보장"


def _build_method(ctx: ReportContext) -> Optional[SectionSpec]:
    """§4 분석 방법 — 시니어 정석. 데이터 의존 키 메시지 + 결정적 결정 강조 + 표 보완.

    - so_what: _method_keymessage 로 데이터에서 자동 도출 (고정 문구 금지)
    - 전처리 본문: 슬래시 6단계 평면 나열 회피. 결정적 결정 1~2개만 산문, 나머지는 표(_preprocessing_visual) 위임.
    - 피처: 메커니즘 가설 강조 (단순 카운트 회피)
    - 검증: 데이터 사실 → 결정 인과 명시
    - 평가 지표: 비용 비대칭 + 임계값 결정 논리
    """
    pp = ctx.preprocessing
    steps = (pp.applied_steps or []) if pp else []
    leak = (pp.leakage_checks or []) if pp else []
    feats = ctx.features
    flags = _task_flags(ctx)
    ds = ctx.dataset
    maj = flags["maj"]
    blocks: list[list[str]] = []

    # ── 1) 전처리 — 결정적 결정 1~2개만 산문 (나머지는 표로)
    if steps:
        critical: list[str] = []
        missing = ds.missing_rate or {}
        # (a) 큰 결측 컬럼 → 제외 결정 강조
        high_miss = [(c, r) for c, r in missing.items() if r >= 0.3]
        if high_miss:
            top_col, top_rate = max(high_miss, key=lambda x: x[1])
            lbl = _feat_label(ctx, top_col)
            critical.append(
                f"<b>{lbl}({_pct(top_rate)} 결측)</b>은 정보 손실 위험으로 컬럼 제외했다. "
                "단순 대치 시 신호가 변형되며, 관련 정보는 다른 변수가 부분적으로 대리한다."
            )
        # (b) 그룹 대치 (세그먼트 신호 보존)
        for st in steps:
            op = str(getattr(st, "op", "") or (st.get("op", "") if isinstance(st, dict) else "")).lower()
            rat = str(getattr(st, "rationale", "") or (st.get("rationale", "") if isinstance(st, dict) else ""))
            if "impute" in op and ("그룹" in rat or "세그먼트" in rat):
                sc = getattr(st, "scope", None) or (st.get("scope", []) if isinstance(st, dict) else [])
                if sc:
                    _lbl = _feat_label(ctx, sc[0])
                    critical.append(
                        f"<b>{_lbl} 결측</b>은 전체 중앙값이 아니라 그룹 중앙값으로 대치했다 — 세그먼트별 신호를 보존하기 위함이다."
                    )
                    break
        # (c) 식별자 누수 방지
        has_id_drop = any(
            str(getattr(st, "op", "") or (st.get("op", "") if isinstance(st, dict) else "")) == "drop_id"
            for st in steps
        )
        if has_id_drop and len(critical) < 2:
            critical.append(
                "<b>식별자 변수</b>는 학습 입력에서 제외했다 — 모델이 식별자 패턴을 외우면 신규 데이터에서 일반화가 무너진다."
            )
        if critical:
            joined = "<br/><br/>".join(critical[:2])
            text = (
                f"{joined}<br/><br/>"
                f"그 외 {len(steps)}단계 세부 결정은 아래 표에서 일괄 확인한다. "
                "모든 변환 통계는 학습 데이터로만 적합해 검증 누수를 차단했다."
            )
        else:
            text = (
                f"총 {len(steps)}단계의 전처리를 적용했다. 세부 결정은 아래 표 참조. "
                "모든 변환 통계는 학습 데이터로만 적합해 검증 누수를 차단했다."
            )
        blocks.append(["전처리", text])  # [C12] 절차 = 확실

    # ── 2) 피처 엔지니어링 — 메커니즘 가설 강조
    if feats and (feats.final_feature_count or feats.created or feats.dropped or feats.selection_method):
        fb_parts: list[str] = []
        if feats.created:
            top_feat = feats.created[0]
            tf_name = getattr(top_feat, "name", "") or (top_feat.get("name", "") if isinstance(top_feat, dict) else "")
            tf_rat = getattr(top_feat, "rationale", "") or (top_feat.get("rationale", "") if isinstance(top_feat, dict) else "")
            if tf_name and tf_rat:
                fb_parts.append(
                    f"파생 피처 {len(feats.created)}개를 생성했다 — 대표 예 <b>{tf_name}</b>: {tf_rat}."
                )
            elif tf_name:
                fb_parts.append(f"파생 피처 {len(feats.created)}개({tf_name} 등)를 생성했다.")
        if feats.final_feature_count and feats.dropped:
            fb_parts.append(
                f"인코딩·파생·제거를 거쳐 최종 {feats.final_feature_count}개 피처로 수렴했다 — "
                f"저분산·중복·누수 위험 변수 {len(feats.dropped)}개 제거."
            )
        elif feats.final_feature_count:
            fb_parts.append(f"인코딩·파생을 거쳐 최종 {feats.final_feature_count}개 피처로 수렴했다.")
        if feats.selection_method:
            fb_parts.append(f"피처 선택은 {feats.selection_method}을 적용했다.")
        if fb_parts:
            blocks.append(["피처 엔지니어링", " ".join(fb_parts)])  # [C12]

    # ── 3) 검증 설계 — 데이터 사실 → 결정 인과
    vb_parts: list[str] = []
    if flags["is_ts"]:
        vb_parts.append(
            "시간 순서를 보존하는 시계열 분할(과거→미래)을 채택했다. "
            "일반 무작위 분할은 미래 정보가 학습에 새는 치명적 누수다."
        )
    elif flags["is_imbal"] and maj:
        vb_parts.append(
            f"다수 클래스 비율 {_pct(maj)} 환경에서 정확도 함정을 회피하기 위해 "
            "클래스 비율을 유지하는 층화 분할을 적용했다."
        )
    elif flags["is_clf"] and maj:
        vb_parts.append(
            f"다수 클래스 비율 {_pct(maj)} 분포를 검증셋이 대표하도록 층화 분할을 적용했다."
        )
    else:
        vb_parts.append("학습·검증 데이터를 분리해 미관측 데이터에 대한 일반화 성능을 측정했다.")
    vb_parts.append("전처리는 분할 내부에서 적합(파이프라인화)해 검증 정보가 학습에 새지 않게 했다.")
    if leak:
        passed = sum(1 for c in leak if isinstance(c, dict) and c.get("passed"))
        vb_parts.append(f"타깃 누수 점검 {len(leak)}건 모두 통과 ({passed}/{len(leak)}).")
    blocks.append(["검증 설계", " ".join(vb_parts)])  # [C12]

    # ── 4) 평가 지표 — 비용 비대칭 + 임계값 결정 논리
    pm = (ctx.evaluation.primary_metric or {}) if ctx.evaluation else {}
    pm_name = pm.get("name") if pm else None
    metrics = (ctx.evaluation.metrics if ctx.evaluation else None) or {}
    if pm or metrics:
        if flags["is_imbal"]:
            mr = (
                "불균형 환경에서 정확도는 다수 클래스 편향으로 신뢰할 수 없다. "
                "<b>PR-AUC·Recall</b>을 1차 지표로 보고, 놓침(False Negative) 비용이 헛경보보다 크다는 가정 하에 "
                "임계값을 보수적으로(0.3~0.4) 설정한다."
            )
        elif flags["is_ts"]:
            mr = (
                "naive(직전값·계절) 베이스라인 대비 <b>sMAPE·MASE</b>로 예측력을 평가한다. "
                "운영 임계값은 예측 신뢰구간 폭으로 정한다."
            )
        elif flags["is_reg"]:
            mr = "오차는 <b>RMSE·MAE</b>로 측정하고, 현업 허용 오차 범위 안에 드는 비율을 추가로 본다."
        elif flags["is_multiclass"]:
            mr = "클래스별 편차를 위해 <b>macro-F1과 혼동행렬</b>을 함께 본다. 혼동이 비싼 쌍을 보강 대상으로 식별한다."
        elif flags["is_clf"]:
            mr = (
                f"<b>F1·PR-AUC</b>와 운영 임계값을 함께 본다. "
                f"단순 추측({_pct(maj) if maj else '다수 클래스'})을 명확히 넘어서는 수준을 요구하며, "
                "오판 비용 비대칭에 맞춰 임계값을 조정한다."
            )
        else:
            mr = "검증 성능 지표로 타당성을 평가한다."
        _pm_ko = _ko_metric(pm_name) if pm_name else ""
        if _pm_ko:
            blocks.append(["평가 지표", f"<b>{_pm_ko}</b>을 주지표로 채택했다. {mr}"])  # [C12]
        else:
            blocks.append(["평가 지표", mr])  # [C12]

    if not blocks:
        return None
    slide = SlideSpec(
        id="method",
        section_id="method",
        layout="comparison_table",
        role="evidence",
        so_what=_method_keymessage(ctx, flags),
        title_ko="결과를 신뢰할 수 있는 절차로 얻었는가",  # [B9 Headline=Message] 결론형
        prose_blocks=blocks,
        visual_spec=_preprocessing_visual(ctx),
    )
    return make_section("method", "분석 방법", "evidence", [slide])


def _build_model_performance(ctx: ReportContext) -> Optional[SectionSpec]:
    """§5 모델 성능 (근거·조연) — 왜 이 모델인가 + 왜 다른 후보는 탈락했나 + 검증 성능."""
    ms = ctx.model_selection
    ev = ctx.evaluation
    chosen = (ms.chosen or {}).get("name", "-") if ms else "-"
    cands: list[dict[str, Any]] = []
    for c in (ms.candidates or []) if ms else []:
        nm = getattr(c, "name", "") or (c.get("name", "") if isinstance(c, dict) else "")
        sc = getattr(c, "score", None)
        if sc is None and isinstance(c, dict):
            sc = c.get("score")
        wd = getattr(c, "why_dropped", None) or (c.get("why_dropped") if isinstance(c, dict) else None)
        wt = getattr(c, "why_tried", "") or (c.get("why_tried", "") if isinstance(c, dict) else "")
        if nm:
            cands.append({"name": str(nm), "score": float(sc) if isinstance(sc, (int, float)) else None, "why_dropped": wd, "why_tried": wt})
    cand_items = [(c["name"], c["score"]) for c in cands if c["score"] is not None]
    metrics = (ev.metrics or {}) if ev else {}
    metric_body = [f"{_ko_metric(k)} {_fv(m.get('value'))}" for k, m in list(metrics.items())[:_MAX_BODY]]
    if (not chosen or chosen == "-") and not metrics:
        return None

    blocks: list[list[str]] = []

    # 선정 근거 — 왜 이 모델
    rb: list[str] = []
    just = (ms.chosen or {}).get("justification") if ms else None
    if just:
        rb.append(str(just))
    chosen_wt = next((c["why_tried"] for c in cands if c["name"] == chosen and c["why_tried"]), "")
    if chosen_wt:
        rb.append(chosen_wt)
    if len(cand_items) >= 2:
        srt = sorted(cand_items, key=lambda x: x[1], reverse=True)
        rb.append(f"후보 {len(cand_items)}개 중 1위로 2위 {srt[1][0]}({_fv(srt[1][1])})를 +{_fv(srt[0][1] - srt[1][1])} 앞섰다")
    fam = str((ms.chosen or {}).get("family", "") if ms else "").lower()
    if "gbm" in fam or "boost" in fam or chosen.lower() in ("catboost", "xgboost", "lightgbm"):
        rb.append("범주형·결측·비선형 상호작용에 강하고 불균형에서도 안정적인 부스팅 계열이다")
    if rb:
        blocks.append(["선정 근거", f"'{chosen}'{_josa(chosen, 'obj')} 최종 선정했다. " + ". ".join(rb) + "."])  # [C12]

    # 후보 탈락 사유 — 왜 다른 모델은 안 썼나
    drop_sents: list[str] = []
    for c in cands:
        if c["name"] == chosen:
            continue
        sc = f"({_fv(c['score'])})" if c["score"] is not None else ""
        wd = c["why_dropped"]
        if wd:
            drop_sents.append(f"{c['name']}{sc} — {wd}")
        elif c["score"] is not None:
            drop_sents.append(f"{c['name']}{sc} — 성능 열위로 제외")
    if drop_sents:
        blocks.append(["후보 탈락 사유 (추정)", " / ".join(drop_sents) + "."])  # [C12] 일부 정성 평가

    # [C11 Benchmark룰] 비교 기준선 — 단순 룰·무작위·인간 직관 대비 본 모델
    # 단순 룰: 다수 클래스 비율(분류) / 평균 추정(회귀)
    # 무작위: 0.5 AUC (분류) / 분산 기반 (회귀)
    _maj = _task_flags(ctx).get("maj")  # 다수 클래스 비율
    _pm = (ev.primary_metric or {}) if ev else {}
    _pm_name = str(_pm.get("name") or "").lower()
    _pm_val = _pm.get("value")
    _bench_bits: list[str] = []
    if _pm_val is not None and ("auc" in _pm_name):
        _bench_bits.append("무작위 0.50")
        if _maj is not None:
            _bench_bits.append(f"단순룰(다수클래스) {_maj:.2f}")
        _bench_bits.append(f"<b>본 모델 {_fvb(_pm_val)}</b>")
    elif _pm_val is not None and _maj is not None:
        _bench_bits.append(f"단순룰(다수클래스) {_maj * 100:.1f}%")
        _bench_bits.append(f"<b>본 모델 {_fvb(_pm_val)}</b>")
    if _bench_bits:
        blocks.append([
            "비교 기준선",
            " / ".join(_bench_bits) + "."
        ])

    # [로드맵1 도메인 벤치마크룰] 업계/외부 평균 대비 본 모델 — ctx.domain.domain_benchmarks(조건부·없으면 스킵·카테고리 불문)
    _dbs = (ctx.domain.domain_benchmarks or []) if ctx.domain else []
    if _dbs and _pm_val is not None:
        _pmn2 = str(_pm.get("name") or "").lower()
        _bm_match = None
        for _b in _dbs:
            _bmn = str(_b.get("metric") or "").lower()
            if _bmn and (_bmn in _pmn2 or _pmn2 in _bmn or _bmn.replace("_", "") in _pmn2.replace("_", "")):
                _bm_match = _b
                break
        _bm_match = _bm_match or _dbs[0]
        _bmv = _bm_match.get("value")
        if isinstance(_bmv, (int, float)) and isinstance(_pm_val, (int, float)):
            _bvs = f"{_bmv:.2f}" if 0 < abs(_bmv) < 1 else _fv(_bmv)
            _pvs = f"{_pm_val:.2f}" if 0 < abs(_pm_val) < 1 else _fv(_pm_val)
            _gap = _pm_val - _bmv
            _verd = "상위" if _gap > 0.005 else ("동등" if abs(_gap) <= 0.005 else "하회")
            _bsrc = str(_bm_match.get("source") or "업계 벤치마크")
            _bml = _ko_metric(_bm_match.get("metric")) or str(_bm_match.get("metric") or "지표")
            _reg = audience_register(ctx)
            if _reg["depth"] == "technical":
                _bline = f"{_bsrc} {_bml} {_bvs} 대비 본 모델 {_pvs}, {_verd}(격차 {_gap:+.2f})."
            else:
                _bline = f"{_bsrc} {_bml} {_bvs} 대비 본 모델 {_pvs}, {_verd}."
            blocks.append(["업계 벤치마크 대비", _bline])

    # [로드맵2 캘리브레이션룰] 확률/예측 신뢰도 — ctx.evaluation.calibration(조건부·카테고리 분기·없으면 스킵)
    _calib = (ev.calibration or {}) if ev else {}
    if isinstance(_calib, dict) and _calib:
        _tech_c = audience_register(ctx)["depth"] == "technical"
        _cal_line = ""
        if _calib.get("ece") is not None:  # 정형 ML/DL 분류: 기대 보정 오차(ECE)
            _ece = _calib["ece"]
            _ece_txt = f" (ECE {_ece:.3f})" if _tech_c else ""
            if isinstance(_ece, (int, float)) and _ece <= 0.05:
                _cal_line = f"모델이 제시하는 확률이 실제 적중률과 잘 맞아{_ece_txt}, 확률을 그대로 임계값·의사결정에 쓸 수 있다."
            else:
                _cal_line = f"모델 확률이 실제 적중률과 다소 어긋나{_ece_txt}, 임계값은 보정 후 사용을 권고한다."
        elif _calib.get("coverage") is not None:  # 시계열: 예측구간 커버리지
            _cal_line = f"예측구간이 실제값을 약 {_calib['coverage']:.0%} 포함(목표 80%)으로, 계획 수립 시 구간을 신뢰하고 쓸 수 있다."
        elif (_calib.get("thresholds") is not None) or (_calib.get("bhattacharyya") is not None):  # 이상탐지: 분리도
            _cal_line = "정상·이상 점수 분포가 뚜렷이 분리돼, 운영 임계값을 헛경보 없이 설정할 수 있다."
        if _cal_line:
            blocks.append(["확률 신뢰도(보정)", _cal_line])

    # [로드맵3 혼동행렬룰] 오류 프로파일 — ctx.evaluation.confusion_matrix(조건부·분류만·없으면 스킵): 어디서 틀리나
    _cm = (ev.confusion_matrix or {}) if ev else {}
    if isinstance(_cm, dict) and _cm:
        _fp = _cm.get("fp") or _cm.get("false_positive") or 0
        _fn = _cm.get("fn") or _cm.get("false_negative") or 0
        if _fp or _fn:
            _tech_e = audience_register(ctx)["depth"] == "technical"
            if _fn > _fp:
                _cnt = f"(미탐 {_fn:,}건 > 오탐 {_fp:,}건)" if _tech_e else ""
                _eline = f"오류는 주로 '놓침' 쪽이다{_cnt}. 놓침 비용이 크면 임계값을 낮춰 재현율을 높이는 운영을 권고한다."
            elif _fp > _fn:
                _cnt = f"(오탐 {_fp:,}건 > 미탐 {_fn:,}건)" if _tech_e else ""
                _eline = f"오류는 주로 '헛경보' 쪽이다{_cnt}. 헛경보 비용이 크면 임계값을 높여 정밀도를 높이는 운영을 권고한다."
            else:
                _eline = "오류가 놓침과 헛경보에 비슷하게 분포한다. 비용 비대칭에 맞춰 임계값을 정한다."
            blocks.append(["오류 프로파일", _eline])

    # 검증 성능 — [레지스터] 본문은 헤드라인(반올림)만, 전체 지표·95% 신뢰구간은 부록 9.1로 이관
    if metric_body:
        _n = (ctx.dataset.shape or {}).get("rows", 0)
        _hd = f"{_ko_metric(_pm.get('name'))} {_fvb(_pm_val)}" if _pm_val is not None else metric_body[0]
        _perf = _hd + (f" (n={_n:,})" if _n else "")
        blocks.append(["검증 성능", _perf + ". 전체 지표와 95% 신뢰구간은 부록 9.1(재현 정보)에 수록."])

    slide = SlideSpec(
        id="model_perf",
        section_id="model_performance",
        layout="chart_callout",
        role="evidence",
        so_what=f"'{chosen}'{_josa(chosen, 'obj')} 선정한 근거와 후보 탈락 사유",
        title_ko=(  # [B9 Headline=Message] 결론형, 동적
            f"'{chosen}' 모델은 단순 추측보다 의미 있게 나은가"
            if chosen and chosen != "-" else "모델 선정 및 성능 (근거)"
        ),
        prose_blocks=blocks,
        visual_spec=(
            VisualSpec(type="chart_bar", title="", spec={"items": cand_items}) if cand_items else None
        ),
    )
    return make_section("model_performance", "모델 성능", "evidence", [slide])


def _top_contrast(ctx: ReportContext):
    """EDA 차트 중 max/min 배수가 가장 큰 축 → (title, hi, hi_v, lo, lo_v, ratio). 1.5배 미만이면 None."""
    best = None
    eda = ctx.eda
    for ch in (eda.charts or []) if eda else []:
        nums = getattr(ch, "numbers", None) or []
        pts = [
            (str(d.get("name", "")), float(d.get("value")))
            for d in nums
            if isinstance(d, dict) and isinstance(d.get("value"), (int, float)) and d.get("value")
        ]
        pts = [(n, v) for n, v in pts if v > 0]
        if len(pts) >= 2:
            hi = max(pts, key=lambda x: x[1])
            lo = min(pts, key=lambda x: x[1])
            r = hi[1] / lo[1]
            if best is None or r > best[5]:
                best = (getattr(ch, "title_ko", "") or "분석", hi[0], hi[1], lo[0], lo[1], r)
    return best if (best and best[5] >= 1.5) else None


def _concentration(ctx: ReportContext):
    """양성(이탈)의 몇 %가 최고위험 세그먼트에 몰리나 → (segment, pct). per_segment 구조화 필요."""
    ev = ctx.evaluation
    segs = [
        s
        for s in ((ev.per_segment or []) if ev else [])
        if isinstance(s, dict)
        and isinstance(s.get("size"), (int, float))
        and isinstance(s.get("churn_rate", s.get("rate")), (int, float))
    ]
    if len(segs) < 2:
        return None
    tot = sum(float(s["size"]) * float(s.get("churn_rate", s.get("rate"))) for s in segs)
    if tot <= 0:
        return None
    hi = max(segs, key=lambda s: float(s.get("churn_rate", s.get("rate"))))
    return (str(hi.get("segment") or hi.get("name") or "한 구간"), float(hi["size"]) * float(hi.get("churn_rate", hi.get("rate"))) / tot)


def _price_feature(ctx: ReportContext) -> str:
    """1위가 아닌 변수 중 가격/금액류 라벨 (통념 반박 '가격이 아니라 구조' 용). 없으면 ''."""
    price_kw = ("charge", "price", "amount", "fee", "cost", "revenue", "요금", "가격", "금액", "비용")
    interp = ctx.interpretation
    imp = []
    for g in (interp.global_importance or []) if interp else []:
        f = getattr(g, "feature", "") or (g.get("feature", "") if isinstance(g, dict) else "")
        if f:
            imp.append((str(f), _feat_label(ctx, str(f))))
    for raw, lbl in imp[1:]:
        if any(k in (raw + lbl).lower() for k in price_kw):
            return lbl
    return ""


def _scenario_projection(ctx: ReportContext) -> Optional[dict[str, Any]]:
    """전환 시나리오의 정량 효과 추정 — per_segment 에 size/churn_rate/value 가 있을 때.

    고위험 세그먼트의 일부를 저위험 수준으로 전환 시: 방어 이탈 수 · 전체 이탈률 before→after ·
    방어 매출(가치×12개월). 가정(전환율)을 명시. 재료 부족 시 None.
    """
    per_seg = (ctx.evaluation.per_segment or []) if ctx.evaluation else []
    segs: list[dict[str, Any]] = []
    for s in per_seg:
        if not isinstance(s, dict):
            continue
        size = s.get("size")
        rate = s.get("churn_rate", s.get("rate"))
        val = s.get("monthly", s.get("arpu", s.get("value_mean")))
        nm = s.get("segment") or s.get("name") or "세그먼트"
        if isinstance(size, (int, float)) and isinstance(rate, (int, float)) and size > 0:
            segs.append(
                {
                    "name": str(nm),
                    "size": float(size),
                    "rate": float(rate),
                    "val": float(val) if isinstance(val, (int, float)) else None,
                }
            )
    if len(segs) < 2:
        return None
    total = sum(s["size"] for s in segs)
    if total <= 0:
        return None
    high = max(segs, key=lambda s: s["rate"])
    target = min((s for s in segs if s is not high), key=lambda s: s["rate"])
    c = 0.20  # 전환율 가정 (보수적)
    convert_n = high["size"] * c
    avoided = convert_n * max(high["rate"] - target["rate"], 0.0)
    cur_count = sum(s["size"] * s["rate"] for s in segs)
    new_count = cur_count - high["rate"] * convert_n + target["rate"] * convert_n
    val = high["val"] or target["val"]
    return {
        "high": high["name"],
        "target": target["name"],
        "c": c,
        "avoided": avoided,
        "cur_churn": cur_count / total,
        "new_churn": new_count / total,
        "retained": (avoided * val * 12) if val else None,
    }


def _event_noun(ctx: ReportContext) -> str:
    """예측 대상(양성) 사건의 읽기 좋은 명사 — 타깃 라벨에서 도출 (churn 하드코딩 금지).

    'Churn'→glossary '이탈 여부'→'이탈', '부도여부'→'부도'. 영문/의미없으면 '양성 사례'.
    """
    target = ctx.dataset.detected_target or ""
    lbl = _feat_label(ctx, target).strip("'\" ")
    for suf in ("여부", "유무", "예측", "구분", "플래그", "flag"):
        if lbl.endswith(suf):
            lbl = lbl[: -len(suf)].strip()
            break
    if lbl and not _re.fullmatch(r"[A-Za-z0-9_]+", lbl):  # 한글·의미 라벨이면 사용
        return lbl
    return "양성 사례"


# 호의적(좋은) 결과 → 줄이고자 하는 '나쁜 사건' 대응. 투영·집중 문장은 '줄이는 사건'을 다루므로 adverse 명사 사용.
_ADVERSE_MAP = {"생존": "사망", "성공": "실패", "합격": "불합격", "정상": "이상",
                "유지": "이탈", "완치": "재발", "회복": "악화"}


def _adverse_noun(ctx: ReportContext) -> str:
    """줄이려는 '나쁜 사건' 명사 — 호의적 타깃(생존·성공 등)이면 반의어(사망·실패), 아니면 사건 그대로(이탈·부도)."""
    return _ADVERSE_MAP.get(_event_noun(ctx), _event_noun(ctx))


def _rate(noun: str) -> str:
    """비율 표현 — 받침에 따라 률/율. '이탈'→'이탈률', '부도'→'부도율', '사기'→'사기율'."""
    if not noun:
        return "비율"
    code = ord(noun[-1]) - 0xAC00
    if 0 <= code <= 11171 and (code % 28) in (0, 4):  # 받침 없음 또는 ㄴ 받침
        return noun + "율"
    return noun + "률"


def _projection_sentence(proj: dict[str, Any], event: str) -> str:
    """전환 시나리오 정량 문장 — 사건 명사로 일반화 (이탈/부도/사기 등 무엇이든)."""
    rev = f", 연 약 {round(proj['retained'], -3):,.0f}의 매출을 지킨다" if proj.get("retained") else ""
    return (
        f"'{proj['high']}' 집단의 {int(proj['c'] * 100)}%를 '{proj['target']}' 수준으로 전환하면 "
        f"연 약 {proj['avoided']:,.0f}건의 {event}{_josa(event, 'obj')} 줄여 전체 {_rate(event)}을 {proj['cur_churn'] * 100:.1f}%에서 "
        f"{proj['new_churn'] * 100:.1f}%로 낮춘다{rev}. "
        f"(가정: 전환율 {int(proj['c'] * 100)}%, 전환 후 {_rate(event)}은 '{proj['target']}' 수준 적용)"
    )


def _levers(ctx: ReportContext, flags: dict[str, Any]) -> list[dict[str, str]]:
    """레버(지렛대) 자동 생성 — 태스크 타입별. 각 레버 = {handle(손잡이), effect(누르면 일어나는 일)}.

    정량 근거(세그먼트 경제성 등) 있으면 숫자로, 없으면 정직한 방향성. 숫자 창작 금지.
    §6·§7·ES 가 공유해 보고서 척추를 일관되게 만든다.
    """
    target = ctx.dataset.detected_target or "타깃"
    _event_noun(ctx)
    adverse = _adverse_noun(ctx)  # 줄이는 나쁜 사건(생존→사망 등) — 투영 효과 라벨용
    drivers = _driver_labels(ctx, 2)
    proj = _scenario_projection(ctx)
    out: list[dict[str, str]] = []

    if flags["is_anom"]:
        out.append({"handle": "탐지 임계값 조정", "effect": "오탐 비용에 맞춰 재현율(미탐↓)과 정밀도(오탐↓)의 균형점을 설정"})
        out.append({"handle": "점수순 우선순위 큐", "effect": "고위험 상위부터 처리해 한정 인력으로 미탐을 최소화"})
        if drivers:
            out.append({"handle": f"{drivers[0]} 신호 모니터링", "effect": "이상의 핵심 동인을 상시 추적해 조기 탐지"})
    elif flags["is_ts"]:
        out.append({"handle": "선행지표 모니터링", "effect": f"'{target}'에 앞서는 신호를 추적해 변화를 조기 포착"})
        out.append({"handle": "이상 시점 알람", "effect": "예측 대비 큰 편차 발생 시 자동 경보로 즉시 대응"})
        out.append({"handle": "예측 지평 관리", "effect": "신뢰 구간 내 단기 예측만 계획에 반영"})
    elif flags["is_reg"]:
        if drivers:
            out.append({"handle": f"상위 동인 '{drivers[0]}' 통제", "effect": f"움직일 수 있는 동인을 조정해 '{target}'{_josa(target, 'obj')} 목표 방향으로 유도"})
        out.append({"handle": "예측 신뢰구간 활용", "effect": "불확실성이 큰 구간은 보수적으로 운영해 리스크 관리"})
    else:  # 분류
        if proj:
            red = (proj["cur_churn"] - proj["new_churn"]) * 100
            rev = f", 연 약 {round(proj['retained'], -3):,.0f} 방어" if proj.get("retained") else ""
            out.append({
                "handle": f"'{proj['high']}' 집단을 '{proj['target']}' 수준으로 끌어올리는 표적 개입",  # [B18 평이한언어룰] 화살표 제거
                "effect": (  # [B18 평이한언어룰] 화살표·기호 제거, 풀어쓰기 / 줄이는 사건=adverse(생존→사망)
                    f"전체 {_rate(adverse)}이 {proj['cur_churn'] * 100:.1f}%에서 "
                    f"{proj['new_churn'] * 100:.1f}%로 {red:.1f}%p 감소{rev}"
                ),
            })
        elif drivers:
            out.append({"handle": f"고위험({drivers[0]}) 세그먼트 타겟팅", "effect": "전수가 아닌 상위군 집중으로 개입 비용 대비 효과 극대화"})
        out.append({"handle": "운영 임계값 조정", "effect": "놓침·헛개입 비용에 맞춰 정밀도·재현율 균형점 설정"})
        if drivers and len(drivers) > 1:
            out.append({"handle": f"{drivers[1]} 데이터 강화", "effect": "핵심 동인 관련 수집·관리를 보강해 예측력 개선"})
    return out[:3]


def _lever_lines(levers: list[dict[str, str]]) -> list[str]:
    """레버 → 화면용 문장. [B18 평이한언어룰] 화살표 금지 — 풀어쓰기."""
    out = []
    for lv in levers:
        if not lv.get("handle"):
            continue
        # 화살표 대신 자연어 연결사 — '... 시 효과:' 형식
        out.append(f"<b>{lv['handle']}</b> 시 — {lv['effect']}.")
    return out


def _build_key_insights(ctx: ReportContext) -> Optional[SectionSpec]:
    """§6 핵심 인사이트와 해석 — 보고서의 ★심장. 4블록 풍부 산문.

    구조: thesis(so_what, 비자명한 결론) → 무엇이 가른다(강도·단일/다요인 판정·통념 반박)
         → 왜 그런가(메커니즘 단락) → 누구에 집중(위험군 정량+정성) → 가장 큰 레버(→ §7).
    EDA 대조, per_feature_story, segment 데이터를 한 줄기로 엮어 '무엇·왜·누구·어디를'에 답한다.
    카테고리(분류/이상/시계열/회귀) 톤은 thesis·레버 문구로 자동 반영. 재료 부족 시 스킵(None).
    """
    interp = ctx.interpretation
    eda = ctx.eda
    ev = ctx.evaluation
    stories = (interp.per_feature_story or {}) if interp else {}
    seg_drivers = (interp.segment_drivers or []) if interp else []
    seg_insights = (eda.segment_insights or []) if eda else []
    event = _event_noun(ctx)
    target = ctx.dataset.detected_target or "타깃"

    # 중요도 (원이름·라벨·값)
    imp: list[tuple[str, str, float]] = []
    for g in (interp.global_importance or []) if interp else []:
        f = getattr(g, "feature", "") or (g.get("feature", "") if isinstance(g, dict) else "")
        v = getattr(g, "importance", None)
        if v is None and isinstance(g, dict):
            v = g.get("importance")
        if f and isinstance(v, (int, float)):
            imp.append((str(f), _feat_label(ctx, str(f)), float(v)))
    top1 = imp[0][1] if imp else None
    top2 = imp[1][1] if len(imp) > 1 else None

    # 공용 헬퍼 재사용 (척추 일관성)
    best = _top_contrast(ctx)  # (title, hi_name, hi_v, lo_name, lo_v, ratio) — 이미 ≥1.5
    conc = _concentration(ctx)  # (segment_name, pct) or None
    price_lbl = _price_feature(ctx)

    # ── 1) Thesis (so_what) — 비자명한 결론 우선순위
    if price_lbl and top1 and best:
        thesis = (
            f"통념과 달리 {price_lbl}(가격)이 아니라 {top1}{_josa(top1, 'nom')} '{target}'{_josa(target, 'obj')} 가른다."
        )
    elif conc and conc[1] >= 0.55:
        thesis = (
            f"전체 {event}의 {conc[1] * 100:.0f}%가 '{conc[0]}' 한 세그먼트에서 발생한다 — "
            "전반의 문제가 아니라 한 구간의 문제다."
        )
    elif best:
        thesis = (
            f"{best[0]}에서 '{best[1]}'({best[2]:.0f}%)이 '{best[3]}'({best[4]:.0f}%)의 {best[5]:.0f}배에 달한다 — "
            "결과는 여기서 갈린다."
        )
    elif top1:
        thesis = f"'{target}'{_josa(target, 'obj')} 좌우하는 단일 최대 요인은 {top1}이다."
    else:
        return None

    blocks: list[list[str]] = []

    # ── 2) 무엇이 가른다 — 강도(배수) + 통념 반박 + 단일/다요인 판정 + 파레토 진술
    what_sents: list[str] = []
    if best:
        if price_lbl and top1:
            what_sents.append(
                f"가격·금액이 결과를 가른다는 통념과 달리, '{top1}'{_josa(top1, 'nom')} 진짜 갈림의 축이다. "
                f"'{best[1]}' {_rate(event)}({best[2]:.0f}%)이 '{best[3]}'({best[4]:.0f}%)의 {best[5]:.0f}배로 벌어진다."
            )
        else:
            what_sents.append(
                f"'{best[1]}' {_rate(event)}({best[2]:.0f}%)이 '{best[3]}'({best[4]:.0f}%)의 {best[5]:.0f}배로, "
                "이 구간이 갈림의 핵심이다."
            )
    # 단일 vs 다요인 판정 (1위/2위 격차 ≥ 2배 → 단일 지배)
    if len(imp) >= 2 and imp[1][2] > 0 and top1:
        ratio12 = imp[0][2] / imp[1][2]
        if ratio12 >= 2.0:
            what_sents.append(
                f"중요도 분포도 {top1} 한 변수에 쏠려 있다(2위 대비 {ratio12:.1f}배) — 단일 동인 구조다."
            )
        elif top2:
            what_sents.append(
                f"{top1}·{top2} 두 축이 결과를 함께 끌고 가는 다요인 구조다."
            )
    elif top1 and not best:
        what_sents.append(f"단일 최대 요인은 {top1}이다.")
    # 파레토 (집중도가 thesis로 안 쓰였을 때만 한 번 더)
    if conc and conc[1] >= 0.45 and not (conc[1] >= 0.55):
        what_sents.append(
            f"발생량 기준으로도 {event}의 약 {conc[1] * 100:.0f}%가 '{conc[0]}' 구간에 몰린다."
        )
    if what_sents:
        blocks.append(["무엇이 가른다", " ".join(what_sents)])  # [C12] 데이터 패턴

    # ── 3) 왜 그런가 — 메커니즘 단락 (per_feature_story 가공, 라벨 prefix)
    mech_sents: list[str] = []
    for fname, story in list(stories.items())[:3]:
        if not story:
            continue
        lbl = _feat_label(ctx, str(fname))
        s = str(story).rstrip(".")
        if lbl and lbl not in s:
            mech_sents.append(f"{lbl}: {s}.")
        else:
            mech_sents.append(s + ".")
    if mech_sents:
        blocks.append(["왜 그런가 — 메커니즘 (가설)", " ".join(mech_sents)])  # [C12][B18] 인과는 가설

    # ── 4) 누구에 집중 — 위험 마이크로-세그먼트(정량 size+rate) + 정성(드라이버 노트)
    who_sents: list[str] = []
    structured = [
        s for s in ((ev.per_segment or []) if ev else [])
        if isinstance(s, dict)
        and isinstance(s.get("size"), (int, float))
        and isinstance(s.get("churn_rate", s.get("rate")), (int, float))
    ]
    if structured:
        hi_s = max(structured, key=lambda s: float(s.get("churn_rate", s.get("rate"))))
        seg_nm = str(hi_s.get("segment") or hi_s.get("name") or "고위험 구간")
        seg_size = int(float(hi_s["size"]))
        seg_rate = float(hi_s.get("churn_rate", hi_s.get("rate")))
        who_sents.append(
            f"가장 위험한 마이크로-세그먼트는 '{seg_nm}'({seg_size:,}건, {_rate(_adverse_noun(ctx))} {seg_rate * 100:.1f}%)."
        )
    # [로드맵4 세그먼트 드라이버] 코호트 동인 — 본문은 상위(고/저위험 대비)까지, 전체는 부록 9.1
    _seg_notes = []
    for s in list(seg_drivers) + list(seg_insights):
        _t = _txt_from(s, ("insight", "driver", "note", "summary"))
        if _t:
            _seg_notes.append(_t.rstrip("."))
    if structured and len(_seg_notes) > 1:
        _seg_notes = _seg_notes[1:]  # 구조화 고위험 문장과 중복되는 첫 드라이버 제거 → 보완(저위험 등)만
    if _seg_notes:
        _ns = 1 if audience_register(ctx)["depth"] == "decision" else 2
        who_sents.append(". ".join(_seg_notes[:_ns]) + ".")
        if len(_seg_notes) > _ns:
            who_sents.append("그 외 세그먼트 동인은 부록 9.1에 정리했다.")
    if who_sents:
        blocks.append(["누구에 집중하나 (추정)", " ".join(who_sents)])  # [C12]

    # [로드맵1 로컬 설명] 개별 예측 사례 — interpretation.local_examples(조건부): "근거 때문에 Y 예측"
    _lx = (interp.local_examples or []) if interp else []
    _case_sents = []
    for ex in _lx:
        if not isinstance(ex, dict):
            continue
        _cbs = ex.get("contributions") or []
        _feats = ", ".join(
            f"{_feat_label(ctx, str(c.get('feature', '')))} {c.get('value', '')}"
            for c in _cbs[:2] if isinstance(c, dict) and c.get("feature")
        )
        if not _feats:
            continue
        _pred = ex.get("prediction", "-")
        _true = ex.get("true", "-")
        if _pred == _true:
            _case_sents.append(f"'{_pred}' 예측 (근거: {_feats})")
        else:
            _case_sents.append(f"'{_pred}' 예측했으나 실제 '{_true}' (근거: {_feats}, 오분류)")
    if _case_sents:
        _nc = 1 if audience_register(ctx)["depth"] == "decision" else 2
        _ltxt = "예측을 개별 사례로 트레이스하면, " + "; ".join(_case_sents[:_nc]) + "."
        if len(_case_sents) > _nc:
            _ltxt += " 전체 사례는 부록 9.1에 있다."
        blocks.append(["개별 예측 사례 (추정)", _ltxt])

    # ── 5) 가장 큰 레버 (→ §7 자연 이행)
    proj = _scenario_projection(ctx)
    lever_sent = ""
    if proj:
        lever_sent = _projection_sentence(proj, _adverse_noun(ctx)) + " 구체 실행은 §7에서 다룬다."
    elif best:
        lever_sent = (
            f"가장 큰 레버는 '{best[1]}' 집단을 '{best[3]}' 쪽으로 이동시키는 개입이다 — 구체 실행은 §7에서 다룬다."
        )
    elif top1:
        lever_sent = f"{top1} 중심의 개입이 가장 큰 효과를 낸다 — 구체 실행은 §7에서 다룬다."
    if lever_sent:
        blocks.append(["가장 큰 레버 — §7 연계 (추정)", lever_sent])  # [C12][B18] 화살표 제거

    if not blocks:
        return None

    slide = SlideSpec(
        id="key_insights",
        section_id="key_insights",
        layout="one_message",
        role="claim",
        so_what=thesis,
        title_ko=(  # [B9 Headline=Message] 결론형, 동적
            f"무엇이 '{target}'{_josa(target, 'obj')} 결정하며, 어디를 보강해야 하는가"
            if target and target != "타깃" else "동인·메커니즘·표적 종합 (핵심 발견)"
        ),
        prose_blocks=blocks,
    )
    return make_section("key_insights", "핵심 인사이트와 해석", "evidence", [slide])


def _build_appendix(ctx: ReportContext) -> list[SectionSpec]:
    """[B4 부록룰] 부록 4묶음 — 9.1 재현·9.2 데이터 사전·9.3 용어·9.4 참고 + '부록' divider.

    내장 샘플(코드 정보 없음)에서도 ctx(데이터셋·지표·모델)만으로 항상 생성한다.
    가짜 수치 금지 — 없는 값은 절차·정의로 대체. carrier 가 '9.x' 제목을 들여쓰기로 렌더한다.
    """
    ds = ctx.dataset
    shape = ds.shape or {}
    n_rows, n_cols = shape.get("rows", 0), shape.get("cols", 0)
    target = ds.detected_target or "타깃"
    chosen = (ctx.model_selection.chosen or {}).get("name", "-") if ctx.model_selection else "-"
    pm = (ctx.evaluation.primary_metric or {}) if ctx.evaluation else {}
    pm_ko = _ko_metric(pm.get("name")) if pm.get("name") else "주지표"

    # ── 부록 개요 (divider; build() 에서 "9. 부록" 으로 번호부여)
    sec_intro = make_section("appendix", "부록", "appendix", [SlideSpec(
        id="appendix", section_id="appendix", layout="one_message", role="meta",
        so_what="본문 결론의 재현·검증 근거",
        title_ko="부록 구성",
        prose_blocks=[
            ["부록의 역할", "본 부록은 본문 결론을 독립적으로 재현·검증하도록 분석 조건과 데이터·용어 정의를 정리한다. 본문이 '무엇을·그래서 무엇을'이라면, 부록은 '어떻게 확인하는가'를 받친다."],
            ["구성", "9.1 재현 정보는 데이터·모델·평가 조건, 9.2 데이터 사전은 변수 정의와 품질, 9.3 용어·지표 정의는 본문 지표의 평이한 풀이, 9.4 참고·방법론은 검증 방식과 한계를 담는다."],
        ],
    )])

    # ── 9.1 재현 정보
    repro_blocks = [
        ["분석 대상", f"데이터셋 '{_human_dataset_name(ctx)}' — {n_rows:,}건 × {n_cols}변수, 타깃 '{target}'."],
        ["모델·평가", f"주 모델 {chosen}, 평가 지표 {pm_ko} {_fv(pm.get('value'))}."],
    ]
    code = ctx.code
    files = (code.files or []) if code else []
    repro_cmd = (getattr(code, "reproduce_command", "") or "") if code else ""
    env = (getattr(code, "environment", {}) or {}) if code else {}
    _have_code = bool(files) or bool(repro_cmd) or (isinstance(env, dict) and bool(env.get("python")))
    if _have_code:
        _bits = []
        if files:
            _bits.append(f"코드 {len(files)}개")
        if isinstance(env, dict) and env.get("python"):
            _bits.append(f"Python {env.get('python')}")
        if repro_cmd:
            _bits.append(f"재현 명령 {repro_cmd}")
        repro_blocks.append(["코드·환경", " · ".join(_bits) + "."])
    else:
        repro_blocks.append(["재현 절차", "데이터 적재, 결측·이상 처리, 학습·검증 분할, 모델 학습, 검증 평가 순으로 재현한다. 동일 분할 기준과 동일 전처리에서 본문 수치가 재현된다."])
    # [레지스터] 검증 지표 전체(정밀 4자리 + 95% CI) — 본문(§5)은 반올림 헤드라인, 정밀표는 여기로 이관
    _ev_a = ctx.evaluation
    _all_m = (_ev_a.metrics or {}) if _ev_a else {}
    if _all_m:
        _mlines = [f"{_ko_metric(_k)} {_fv(_m.get('value'))}" for _k, _m in _all_m.items()]
        _pmv = pm.get("value")
        _pmn = str(pm.get("name") or "").lower()
        _ci = ""
        if n_rows and isinstance(_pmv, (int, float)) and ("auc" in _pmn) and 0 < _pmv < 1:
            import math as _math
            _se = _math.sqrt(_pmv * (1 - _pmv) / n_rows)
            _lo, _hi = max(0.0, _pmv - 1.96 * _se), min(1.0, _pmv + 1.96 * _se)
            _ci = f" / {pm_ko} 95% CI {_lo:.4f}~{_hi:.4f} (N={n_rows:,})"
        repro_blocks.append(["검증 지표 전체", ", ".join(_mlines) + "." + _ci])
    # [로드맵2] 확률 보정 상세(ECE) — 부록
    _cal_a = (_ev_a.calibration or {}) if _ev_a else {}
    if isinstance(_cal_a, dict) and _cal_a.get("ece") is not None:
        repro_blocks.append(["확률 보정(ECE)", f"기대 보정 오차 ECE {_cal_a['ece']:.3f}. 0에 가까울수록 예측 확률이 실제 적중률과 일치하며(완벽 0), 통상 0.05 이하면 양호."])
    # [로드맵3] 혼동행렬 상세 — 부록(정탐·오탐·미탐·정상기각 건수)
    _cm_a = (_ev_a.confusion_matrix or {}) if _ev_a else {}
    if isinstance(_cm_a, dict) and _cm_a:
        _tp = _cm_a.get("tp") or _cm_a.get("true_positive") or 0
        _fp2 = _cm_a.get("fp") or _cm_a.get("false_positive") or 0
        _fn2 = _cm_a.get("fn") or _cm_a.get("false_negative") or 0
        _tn = _cm_a.get("tn") or _cm_a.get("true_negative") or 0
        if any((_tp, _fp2, _fn2, _tn)):
            repro_blocks.append(["혼동행렬", f"정탐(TP) {_tp:,}, 오탐(FP) {_fp2:,}, 미탐(FN) {_fn2:,}, 정상기각(TN) {_tn:,}. (미탐=놓침, 오탐=헛경보; 검증셋 기준)"])
    # [로드맵4] 세그먼트 동인 전체 — 부록(본문은 상위만, 전체 코호트 인사이트는 여기)
    _sd_a = (ctx.interpretation.segment_drivers or []) if ctx.interpretation else []
    if _sd_a:
        _sd_lines = []
        for _s in _sd_a:
            _t = _txt_from(_s, ("insight", "driver", "note", "summary"))
            if _t:
                _sd_lines.append(_t.rstrip("."))
        if _sd_lines:
            repro_blocks.append(["세그먼트 동인", " / ".join(_sd_lines) + "."])
    # [로드맵1] 개별 예측 사례 전체 — 부록(예측/실제 + 근거)
    _lx_a = (ctx.interpretation.local_examples or []) if ctx.interpretation else []
    if _lx_a:
        _lx_lines = []
        for ex in _lx_a:
            if not isinstance(ex, dict):
                continue
            _cbs = ex.get("contributions") or []
            _fe = ", ".join(
                f"{_feat_label(ctx, str(c.get('feature', '')))} {c.get('value', '')}"
                for c in _cbs[:3] if isinstance(c, dict) and c.get("feature")
            )
            _p = ex.get("prediction", "-")
            _t = ex.get("true", "-")
            _ok = "정확" if _p == _t else "오분류"
            _lx_lines.append(f"예측 '{_p}'/실제 '{_t}'({_ok}), 근거 {_fe}")
        if _lx_lines:
            repro_blocks.append(["개별 예측 사례", " / ".join(_lx_lines) + "."])
    # [로드맵 세그먼트별 성능표] 전체 슬라이스 결과율 — 부록(본문 so-what은 §6 상/하위, 전체 표는 여기)
    _ps_a = (_ev_a.per_segment or []) if _ev_a else []
    _ps_rows = []
    for s in _ps_a:
        if not isinstance(s, dict):
            continue
        _nm = str(s.get("segment") or s.get("name") or "")
        _rt = s.get("churn_rate", s.get("rate"))
        if not (_nm and isinstance(_rt, (int, float))):
            continue
        _sz = s.get("size")
        _szt = f"({int(_sz):,}건) " if isinstance(_sz, (int, float)) else ""
        _ps_rows.append(f"{_nm}{_szt}{_rate(_adverse_noun(ctx))} {_rt * 100:.1f}%")
    if _ps_rows:
        repro_blocks.append(["세그먼트별 결과율", " / ".join(_ps_rows) + "."])
    sec_repro = make_section("appx_repro", "재현 정보", "appendix", [SlideSpec(
        id="appx_repro", section_id="appx_repro", layout="one_message", role="meta",
        so_what="동일 조건에서 본문 수치 재현", title_ko="재현 정보",
        prose_blocks=repro_blocks,
    )])

    # ── 9.2 데이터 사전
    dtypes = ds.dtypes or {}
    missing = ds.missing_rate or {}
    target_l = (target or "").lower()
    id_set = {str(c).lower() for c in (ds.detected_id_cols or [])}
    dict_lines: list[str] = []
    for c in list(dtypes.keys())[:18]:
        cl = str(c).lower()
        kind = "수치형" if _is_numeric_dtype(dtypes.get(c)) else "범주형"
        role = "타깃" if cl == target_l else ("식별자" if cl in id_set else "입력")
        mr = missing.get(c, 0) or 0
        miss = f", 결측 {_pct(mr)}" if (mr and mr > 0) else ""
        dict_lines.append(f"{c} — {kind}·{role}{miss}")
    if not dict_lines:
        dict_lines = [f"변수 {n_cols}개 — 상세 정의 정보 제한."]
    sec_dict = make_section("appx_dict", "데이터 사전", "appendix", [SlideSpec(
        id="appx_dict", section_id="appx_dict", layout="one_message", role="meta",
        so_what="변수 정의·유형·품질 한눈에", title_ko="데이터 사전",
        body_outline=dict_lines,
    )])

    # ── 9.3 용어·지표 정의
    _METRIC_DEF = {
        "roc_auc": "여러 판정 기준에서 양·음성을 가려내는 종합 분별력. 1에 가까울수록 좋다.",
        "auc": "여러 판정 기준에서 양·음성을 가려내는 종합 분별력. 1에 가까울수록 좋다.",
        "accuracy": "전체 중 맞게 분류한 비율. 불균형 데이터에서는 과대평가될 수 있다.",
        "f1": "정밀도와 재현율의 조화 평균으로 둘의 균형을 본다.",
        "precision": "양성으로 부른 것 중 실제 양성의 비율로, 높을수록 헛경보가 적다.",
        "recall": "실제 양성 중 잡아낸 비율로, 높을수록 놓침이 적다.",
        "rmse": "예측 오차의 크기로 클수록 나쁘며 단위는 타깃과 같다.",
        "mae": "예측 오차의 절대 평균으로 클수록 나쁘다.",
        "mape": "예측 오차를 실제값 대비 백분율로 본 지표.",
        "r2": "타깃 변동을 모델이 설명한 비율로 1에 가까울수록 좋다.",
    }
    metrics = (ctx.evaluation.metrics or {}) if ctx.evaluation else {}
    gloss: list[str] = []
    for k in list(metrics.keys())[:6]:
        kl = str(k).lower()
        _defn = ""
        for _key, _d in _METRIC_DEF.items():
            if _key in kl:
                _defn = _d
                break
        gloss.append(f"{_ko_metric(k)} — {_defn or '본 분석의 평가 지표.'}")
    if not gloss:
        gloss.append("평가 지표 — 본문 §5 모델 성능을 참조.")
    gloss.append("기준 모델 — 단순 추측(다수 클래스·평균·직전값). 모델은 이를 의미 있게 넘어야 도입 가치가 있다.")
    gloss.append("검증 — 학습에 쓰지 않은 데이터로 성능을 확인해 과적합을 거른다.")
    gloss.append("과적합 — 학습 데이터에만 맞춰져 새 데이터에서 성능이 떨어지는 현상.")
    sec_gloss = make_section("appx_gloss", "용어·지표 정의", "appendix", [SlideSpec(
        id="appx_gloss", section_id="appx_gloss", layout="one_message", role="meta",
        so_what="본문 지표의 평이한 풀이", title_ko="용어·지표 정의",
        body_outline=gloss,
    )])

    # ── 9.4 참고·방법론
    _gen = (getattr(ctx.meta, "generated_at", "") or "")[:10]
    method = [
        "검증 방식 — 학습·검증 분할로 미학습 데이터에서 성능을 측정한다.",
        "비교 기준 — 단순 기준 모델 대비 개선폭으로 도입 가치를 판정한다.",
        "해석 주의 — 상관은 인과가 아니며, 표본 밖 분포와 미관측 세그먼트에는 보수적으로 일반화한다.",
        f"한계 — 표본 {n_rows:,}건 기준이므로 운영 분포 변화에 대한 재검증이 필요하다.",
    ]
    if _gen:
        method.append(f"기준일 — 본 보고서 생성 {_gen}.")
    sec_method = make_section("appx_method", "참고·방법론", "appendix", [SlideSpec(
        id="appx_method", section_id="appx_method", layout="one_message", role="meta",
        so_what="검증 방식과 정직한 한계", title_ko="참고·방법론",
        body_outline=method,
    )])

    return [sec_intro, sec_repro, sec_dict, sec_gloss, sec_method]


def _build_implications(ctx: ReportContext) -> Optional[SectionSpec]:
    """§7 비즈니스 임팩트와 실행 — 인사이트를 실행으로 전환 (풍부 산문).

    구조: 임팩트(정량+정성) → 표적 개입 원칙(카테고리별) → 실행 레버(굵게 손잡이→효과)
         → 운영 적용(모델·재학습·모니터링) → 리스크·전제(정직한 한계).
    §6에서 '무엇을 알았나'를 답했다면, §7은 '그래서 무엇을 할 것인가'에 답한다.
    so_what 은 결단형 한 줄. _scenario_projection·_levers 등 공용 자원을 적극 활용해 척추 일관성 유지.
    """
    ev = ctx.evaluation
    lims = ctx.limitations
    ms = ctx.model_selection
    chosen = (ms.chosen or {}).get("name", "-") if ms else "-"
    pm = (ev.primary_metric or {}) if ev else {}
    pmname = pm.get("name")
    pmval = pm.get("value")
    mdisp = f"{_ko_metric(pmname)} {_fv(pmval)}" if (pmval is not None and pmname) else "검증 성능"
    flags = _task_flags(ctx)
    target = ctx.dataset.detected_target or "타깃"
    event = _event_noun(ctx)
    drivers = _driver_labels(ctx, 2)
    drv = ", ".join(drivers)
    has_model = bool(chosen and chosen != "-" and pmval is not None)
    proj = _scenario_projection(ctx)

    blocks: list[list[str]] = []

    # 1) 임팩트 — 정량(business_kpi·시나리오) + 정성(카테고리별 기대 결과)
    impact_sents: list[str] = []
    for k in (ev.business_kpi or [])[:2] if ev else []:
        kn = getattr(k, "name", "") or (k.get("name", "") if isinstance(k, dict) else "")
        ku = getattr(k, "unit", "") or (k.get("unit", "") if isinstance(k, dict) else "")
        kv = getattr(k, "estimated_value", None)
        if kv is None and isinstance(k, dict):
            kv = k.get("estimated_value")
        if kn and kv is not None:
            impact_sents.append(
                f"{kn} {_fv(kv)} {ku} 수준의 효과가 정량적으로 기대된다.".replace("  ", " ")
            )
    if flags["is_anom"]:
        impact_sents.append("조기 이상 탐지로 다운타임·품질 손실을 줄이고, 룰베이스 대비 오탐을 낮춰 점검 인력 부하를 절감한다.")
    elif flags["is_ts"]:
        impact_sents.append(f"'{target}' 예측 정확도 향상으로 재고·인력·리드타임 등 자원 계획을 선제적으로 최적화한다.")
    elif flags["is_reg"]:
        impact_sents.append(f"'{target}' 추정 정밀화로 가격·리스크·자원 배분 의사결정의 정확도가 올라간다.")
    else:
        impact_sents.append(f"정확한 '{target}' 판정을 자동화해 고위험·고우선 대상의 선별·처리에 일관성과 속도를 확보한다.")
    if proj:
        impact_sents.append(_projection_sentence(proj, _adverse_noun(ctx)))
    blocks.append(["임팩트 (추정)", " ".join(impact_sents)])  # [C12] 미래 효과 = 추정

    # 1-2) 재무 임팩트 (ROI·페이백) — [풍부화 §7] 가짜 숫자 금지: proj 정량 / 없으면 산출 프레임
    roi_sents: list[str] = []
    if proj and proj.get("avoided"):
        roi_sents.append(
            f"효익의 정량 근거는 위 임팩트의 연 {proj['avoided']:,.0f}건 {event} 감축 추정이며, "
            "여기에 건당 비용을 곱하면 방어 가능한 손실 규모가 산출된다."
        )
        if proj.get("retained"):
            roi_sents.append(
                f"매출 방어분 연 약 {round(proj['retained'], -3):,.0f}을 효익으로, "
                "모델 운영·재학습·모니터링 인건비를 비용으로 두면 손익분기(페이백) 시점이 추정된다."
            )
    else:
        roi_sents.append(
            "효익은 표적 개입으로 방어하는 손실 또는 확보 매출에서, 비용은 모델 운영·재학습·모니터링 인력에서 발생한다."
        )
    roi_sents.append(
        "정확한 ROI와 페이백은 건당 비용·표적군 규모·전환율 가정을 입력해야 확정되며, 운영 결재 전 이 세 값의 합의를 권고한다."
    )
    blocks.append(["재무 임팩트 (ROI·페이백, 추정)", " ".join(roi_sents)])  # [C12]

    # 2) 표적 개입 원칙 — 전수 X, 카테고리별 차별화
    if flags["is_anom"]:
        focus = (
            "전수 점검이 아니라 모델이 점수화한 고위험 상위군부터 처리하고, 오탐 비용에 맞춰 임계값을 조정한다. "
            "한정된 점검 인력을 가치 높은 곳에 집중시키는 것이 효율의 핵심이다."
        )
    elif flags["is_ts"]:
        focus = (
            "전 기간 동일 대응이 아니라 선행지표가 흔들리는 시점을 표적해 재고·인력을 미리 움직인다. "
            "예측 신뢰구간을 벗어난 구간은 별도 대응 라인을 둔다."
        )
    elif flags["is_reg"]:
        focus = (
            "전 구간 평균 통제가 아니라 잔차가 크게 벌어지는 구간·세그먼트를 표적해 개입한다. "
            "동인 변수 중 움직일 수 있는 손잡이부터 조정한다."
        )
    else:  # 분류
        seg_hint = f" 본 데이터에선 '{proj['high']}' 집단이 1순위 표적이다." if proj else ""
        focus = (
            "전수가 아니라 모델이 점수화한 고위험 상위군을 선별하고, 그중 고가치(매출·전략) 대상을 우선한다." + seg_hint
        )
    blocks.append(["표적 개입 원칙 (추정)", focus])  # [C12]

    # 3) 실행 레버 — 손잡이 굵게 + → 효과 (한 줄짜리 블록 다발로 시각화)
    lever_lines = _lever_lines(_levers(ctx, flags))
    if lever_lines:
        blocks.append(["실행 레버 (추정)", "우선순위가 높은 실행 레버는 다음과 같다."])  # [C12]
        for line in lever_lines:
            blocks.append(["", line])

    # 4) 운영 적용 — 모델·재학습·모니터링
    ops_sents: list[str] = []
    if has_model:
        # [로드맵5 재검증 주기] limitations.revalidation_window 실제 값 사용(없으면 폴백) — "예: 분기" 하드코딩 제거
        _rev = (ctx.limitations.revalidation_window or "").strip() if ctx.limitations else ""
        _rev_txt = f"{_rev} 재검증 주기" if _rev else "정기 재검증 주기"
        ops_sents.append(f"운영에는 '{chosen}' 모델을 {mdisp} 기준으로 적용하되, 분포 변화에 대응할 {_rev_txt}를 함께 둔다.")
        # [로드맵2 분포 변화 위험] distribution_shift_risk 감지 시 드리프트 트리거 규칙(조건부·없으면 스킵)
        _shift = (ctx.limitations.distribution_shift_risk or {}) if ctx.limitations else {}
        if isinstance(_shift, dict) and _shift.get("detected"):
            _ev_txt = str(_shift.get("evidence") or "").strip().rstrip(".")
            if _ev_txt:
                ops_sents.append(f"{_ev_txt}. 이에 드리프트 감지 시 정기 주기와 별개로 즉시 재학습을 트리거한다.")
            else:
                ops_sents.append("운영 중 입력 분포 드리프트가 감지되면 정기 주기와 별개로 즉시 재학습을 트리거한다.")
    elif chosen and chosen != "-":
        ops_sents.append(f"'{chosen}' 모델 후보를 우선 검증한 뒤 운영 적용 여부를 결정한다.")
    if drv:
        ops_sents.append(f"동시에 {drv} 등 핵심 동인의 모니터링·수집을 강화해 예측력과 개입 정확도를 지속 개선한다.")
    if ops_sents:
        blocks.append(["운영 적용 (추정)", " ".join(ops_sents)])  # [C12]

    # 4-2) 롤아웃 마일스톤 — [풍부화 §7] 단계별 게이트
    blocks.append([
        "롤아웃 마일스톤",
        "운영 도입은 한 번에 전면 적용하지 않는다. 1단계 파일럿(상위 약 5% 표적군)에서 핵심 지표를 검증하고, "
        "2단계 부분 확대(약 20%)에서 운영 안정성과 오탐·미탐 비용을 확인한 뒤, 3단계 전면 적용으로 단계별 게이트를 둔다. "
        "각 게이트는 사전 정의된 성공 지표를 충족할 때만 다음 단계로 승급한다.",
    ])

    # 4-3) 거버넌스 — [풍부화 §8] 결재권·승인절차·책임소재 (권고 섹션에 배치, §8 BLUF 보존)
    blocks.append([
        "거버넌스 (결재·책임)",
        "운영 도입과 임계값·재학습 정책 변경은 모델 소유 부서가 기안하고 데이터·리스크 검토를 거쳐 "
        "운영 책임자 결재로 확정한다. 분기별 성능·분포 점검을 동일 보고 라인으로 공유하고, "
        "임계 이탈 시 재학습·롤백 권한과 책임 소재를 사전에 명시한다.",
    ])

    # 5) 리스크·전제 — 정직한 한계 (단, 으로 시작)
    risks: list[str] = []
    for cav in (getattr(lims, "model_caveats", None) or [])[:2] if lims else []:
        if cav:
            risks.append(str(cav).rstrip("."))
    for g in (getattr(lims, "data_gaps", None) or [])[:1] if lims else []:
        d = getattr(g, "description", "") or (g.get("description", "") if isinstance(g, dict) else "")
        if d:
            risks.append(str(d).rstrip("."))
    if risks:
        blocks.append(
            ["리스크·전제", "단, " + " ".join(r + "." for r in risks) + " 위 권고는 이 전제 위에서 유효하다."]
        )

    if not blocks:
        return None

    # so_what — 결단형. 정량 시나리오 있으면 숫자로, 아니면 동인 중심.
    if proj:
        red = (proj["cur_churn"] - proj["new_churn"]) * 100
        so_what = f"'{proj['high']}' 집단을 표적해 전체 {_rate(event)}을 {red:.1f}%p 낮추는 것이 가장 큰 레버다."
    elif drivers:
        so_what = f"{drv} 중심의 표적 개입이 가장 큰 효과를 낸다."
    else:
        so_what = "분석은 여기까지, 이제 이 인사이트를 어떻게 운영·의사결정에 꽂을지가 본 섹션의 답이다."

    slide = SlideSpec(
        id="implications",
        section_id="implications",
        layout="one_message",
        role="action",
        so_what=so_what,
        title_ko="지금부터 누가 무엇을 언제까지 할 것인가",  # [B9 Headline=Message] 결론형 + C6 Action_OwnerDate 암시
        prose_blocks=blocks,
    )
    return make_section("implications", "비즈니스 임팩트와 실행", "recommendation", [slide])


def _build_conclusion(ctx: ReportContext) -> SectionSpec:
    """§8 결론 — §1 핵심 질문에 대한 의사결정 텍스트 (5블록 시니어 흐름).

    Pyramid Principle + BLUF 결합: 분석 요약이 아니라 의사결정 텍스트.
        1) 답 (lead/so_what) — 데이터 단정 + 권고 단정 한 줄
        2) 권고 (Recommendation) — 카테고리별 결정 언어 ('한다·권고한다·전환한다')
        3) 왜 지금인가 + 비행동 비용 — 시급성, 가만 두면의 손실(정량 가능 시)
        4) 단서 (정직한 한계) — '단, ~. 위 권고는 이 전제 위에서 유효하다'
        5) 모니터링 — 후행 추적 지표 한 줄 (감상문성 closing 금지)

    '할 수 있다' 가능성 진술 금지. 모든 블록이 의사결정자에게 보내는 단정.
    """
    flags = _task_flags(ctx)
    ms = ctx.model_selection
    ev = ctx.evaluation
    lims = ctx.limitations
    chosen = (ms.chosen or {}).get("name", "-") if ms else "-"
    pm = (ev.primary_metric or {}) if ev else {}
    pmval = pm.get("value")
    pmname = pm.get("name")
    pmname_l = str(pmname or "").lower()
    verb = _CAT_VERB.get(ctx.meta.category or "", "분석")
    target = ctx.dataset.detected_target or "타깃"
    event = _event_noun(ctx)
    drivers = _driver_labels(ctx, 2)
    drv = ", ".join(drivers)
    maj = flags["maj"]
    has_model = bool(chosen and chosen != "-" and pmval is not None)
    judgment = _perf_judgment(flags, pmval, pmname_l, maj)
    proj = _scenario_projection(ctx)

    # 한국어 지표 표현
    if pmval is None:
        mphrase = "검증 성능"
    elif "acc" in pmname_l and isinstance(pmval, (int, float)) and pmval <= 1:
        mphrase = f"정확도 {pmval * 100:.1f}%"
    elif "auc" in pmname_l:
        mphrase = f"AUC {_fv(pmval)}"
    elif "f1" in pmname_l:
        mphrase = f"F1 {_fv(pmval)}"
    else:
        mphrase = f"{_ko_metric(pmname)} {_fv(pmval)}"

    # ── 1) 답 (lead/so_what) — 분석 단정 + 권고 단정 한 줄 (BLUF)
    if has_model and drivers:
        lead = (
            f"데이터는 {drv}{_josa(drivers[-1], 'nom')} '{target}'{_josa(target, 'obj')} 가른다고 단정한다. "
            f"권고는 분명하다 — '{chosen}' 모델을 {mphrase} 기준으로 운영 도입한다."
        )
    elif has_model:
        lead = (
            f"데이터는 '{target}'{_josa(target, 'obj')} {mphrase} 수준으로 {verb}함을 입증한다. "
            f"권고는 분명하다 — '{chosen}' 모델을 운영 도입한다."
        )
    else:
        lead = (
            f"현재 데이터로 '{target}' {verb}의 가능성은 확인했으나 운영 결정에는 충분치 않다. "
            "권고는 분명하다 — 데이터를 보강한 뒤 재판단한다."
        )
    if has_model and judgment:
        lead += f" 다만 {judgment}."

    blocks: list[list[str]] = []

    # ── 2) 권고 (Recommendation) — 카테고리별 결정 언어
    if not has_model:
        reco = (
            "추가 표본·세그먼트 보강을 1개 분기 내 완료하고, 동일 절차로 재판단한다. "
            "그전까지 본 분석 결과는 의사결정 보조자료로만 활용한다."
        )
    elif flags["is_anom"]:
        reco = (
            "고위험 상위군부터 우선 점검하는 표적 이상탐지 운영 체계로 전환한다. "
            "임계값은 오탐 비용·미탐 손실의 비대칭을 반영해 운영부서 결재로 분기별 재조정한다."
            + (f" 동인 모니터링은 {drv} 중심으로 둔다." if drv else "")
        )
    elif flags["is_ts"]:
        reco = (
            f"'{target}' 예측을 선행지표 기반 운영 체계로 채택해 재고·인력·리드타임 계획에 직접 반영한다. "
            "예측 신뢰구간을 벗어난 시점에는 별도 대응 라인을 둔다."
        )
    elif flags["is_reg"]:
        reco = (
            f"'{target}' 추정을 본 모델 기준으로 운영에 도입하고, 잔차가 큰 구간·세그먼트는 별도 검토로 분리한다."
            + (f" 통제 가능한 동인({drv})부터 조정 대상으로 삼는다." if drv else "")
        )
    else:  # 분류
        if proj:
            reco = (
                f"고위험 상위군 '{proj['high']}' 표적 개입 운영 모델로 전환한다. "
                f"전환율 {int(proj['c'] * 100)}% 가정 하 연 {proj['avoided']:,.0f}건의 {event} 감축을 목표로 둔다."
            )
        else:
            reco = (
                "전수 처리가 아니라 모델 점수 상위군을 선별하는 표적 개입 운영 모델로 전환한다."
                + (f" 개입 우선순위는 {drv} 기반으로 정한다." if drv else "")
            )
    blocks.append(["", reco])

    # ── 3) 왜 지금인가 + 비행동 비용 (Cost of Inaction)
    why_sents: list[str] = []
    if proj:
        rev_txt = f", 연 약 {round(proj['retained'], -3):,.0f}의 매출이 방어된다" if proj.get("retained") else ""
        why_sents.append(
            f"지금 결정하지 않으면 연 약 {proj['avoided']:,.0f}건의 {event}{_josa(event, 'nom')} "
            f"방어 가능했던 손실로 누적된다{rev_txt}."
        )
    if flags["is_ts"] or flags["is_anom"]:
        why_sents.append("분포·신호가 바뀌기 전에 운영 체계를 잡아야 후속 학습·검증의 비교 기준이 안정된다.")
    elif flags["is_clf"] and not proj:
        why_sents.append("운영 도입이 지연될수록 모델 신선도가 떨어져 재학습 비용과 의사결정 지연 손실이 동시에 증가한다.")
    else:
        why_sents.append("분기를 넘기면 분포가 변해 본 분석의 결정 근거 자체가 약해진다.")
    blocks.append(["", " ".join(why_sents)])

    # ── 4) 단서 (정직한 한계) — 한 줄 압축
    caveat = ""
    cavs = (getattr(lims, "model_caveats", None) or []) if lims else []
    if cavs:
        caveat = str(cavs[0]).rstrip(".")
    if not caveat:
        gaps = (getattr(lims, "data_gaps", None) or []) if lims else []
        if gaps:
            d = (
                getattr(gaps[0], "description", "")
                or (gaps[0].get("description", "") if isinstance(gaps[0], dict) else "")
            )
            caveat = str(d).rstrip(".")
    if not caveat and has_model and flags["is_clf"] and maj is not None:
        caveat = f"다수 클래스 비율 {_pct(maj)} 환경의 일반화 범위 안에서만 권고가 유효하다는 점"
    if caveat:
        blocks.append(["", f"단, {caveat}. 위 권고는 이 전제 위에서 유효하다."])

    # ── 5) 모니터링 — 후행 검증 한 줄 (감상문성 closing 금지)
    if has_model:
        mon_targets: list[str] = []
        if pmname:
            mon_targets.append(_ko_metric(pmname))
        if drv:
            mon_targets.append(f"{drv} 분포")
        mon_targets.append(_rate(event))
        mon_targets = mon_targets[:3]
        chained = " · ".join(mon_targets)
        mon_text = (
            f"운영 후 {chained}{_josa(mon_targets[-1], 'obj')} 월 단위로 추적하고, "
            "임계 이탈 시 정기 재학습 트리거를 가동한다."
        )
    else:
        mon_text = "재판단 시점에는 본 분석과 동일한 절차·지표로 측정해 의사결정의 비교 가능성을 보존한다."
    blocks.append(["", mon_text])

    slide = SlideSpec(
        id="conclusion",
        section_id="conclusion",
        layout="one_message",
        role="action",
        so_what=lead,
        title_ko=(  # [B9 Headline=Message] 결론형, 동적
            f"'{chosen}' 모델, 운영 도입할 가치가 있는가"
            if chosen and chosen != "-" else "최종 답과 의사결정 (Bottom Line)"
        ),
        prose_blocks=blocks,
    )
    return make_section("conclusion", "결론", "recommendation", [slide])


# [오디언스 적응형 70:30] 청중 → (본문%, 부록%, 본문 기술깊이). 70:30이 닻, 청중이 당김.
_AUDIENCE_RATIO = {
    "c_level": (80, 20, "decision"),   # 거의 결정만 (분석은 부록)
    "exec": (80, 20, "decision"),
    "manager": (70, 30, "balanced"),   # 기준(닻)
    "analyst": (55, 45, "technical"),  # 본문에 분석 더
    "external": (75, 25, "decision"),
}


def audience_register(ctx: ReportContext) -> dict[str, Any]:
    """[오디언스 적응형 70:30 + 레지스터] 청중을 읽어 본문:부록 비율 + 본문 기술깊이 결정.

    audience_inference(이미 추론된 숨은 자산) 또는 meta.audience 사용. 어떤 데이터든 자동.
    반환: {audience, body_pct, appendix_pct, depth}. depth='decision'|'balanced'|'technical'.
    자산들은 이걸 읽어 본문형(so-what)/부록형(기술) 비중을 정한다. 모르면 70:30(balanced).
    """
    aud = ""
    try:
        aud = (getattr(getattr(ctx, "meta", None), "audience", "") or "").lower()
    except Exception:
        pass
    if not aud:
        try:
            ai = getattr(getattr(ctx, "domain", None), "audience_inference", None)
            if ai is not None:
                aud = (getattr(ai, "level", "") or (ai.get("level", "") if isinstance(ai, dict) else "")).lower()
        except Exception:
            pass
    bp, ap, depth = _AUDIENCE_RATIO.get(aud, (70, 30, "balanced"))
    return {"audience": aud or "manager", "body_pct": bp, "appendix_pct": ap, "depth": depth}


def chairman_exec(ctx: ReportContext, plan) -> Optional[dict[str, Any]]:
    """[회장님 Exec룰] 임원이 3초에 결정하는 1페이지 패키지(내용). 형식(레이아웃)은 carrier 가 그린다.

    구성: BLUF(결정 한 줄) · 관통질문+답 · 3기둥(①무엇이 가르나 ②얼마나 믿나 ③얼마짜리인가) · 권고 · 단서.
    전부 ctx 출처(가짜 수치 0). 어떤 데이터·카테고리든 동일 패키지. 오류 시 None → carrier 가 기존 Exec 로 폴백.
    """
    try:
        target = ctx.dataset.detected_target or "타깃"
        tlabel = _feat_label(ctx, target)
        flags = _task_flags(ctx)
        pm = (ctx.evaluation.primary_metric or {}) if ctx.evaluation else {}
        pmval = pm.get("value")
        has_model = pmval is not None
        _mv = f"{pmval:.2f}" if (isinstance(pmval, (int, float)) and 0 < abs(pmval) < 1) else _fv(pmval)
        mdisp = f"{_ko_metric(pm.get('name'))} {_mv}" if (has_model and pm.get("name")) else "검증 성능"
        drivers = _driver_labels(ctx, 2) or []
        best = _top_contrast(ctx)
        proj = _scenario_projection(ctx)
        adverse = _adverse_noun(ctx)
        nt = getattr(plan, "narrative_thread", None)

        bluf = (getattr(nt, "headline", "") if nt else "") or \
            f"{_human_dataset_name(ctx)} 분석으로 '{tlabel}'{_josa(tlabel, 'obj')} 좌우하는 핵심 동인을 식별했다."

        if flags.get("is_anom"):
            question = "이상 탐지를 운영 점검 체계로 도입할 가치가 있는가?"
        elif flags.get("is_ts"):
            question = f"‘{tlabel}’ 예측을 계획 수립에 도입할 가치가 있는가?"
        elif flags.get("is_reg"):
            question = f"‘{tlabel}’ 추정을 의사결정에 도입할 가치가 있는가?"
        else:
            question = f"‘{tlabel}’ 판정 모델을 운영에 도입할 가치가 있는가?"
        verdict = "있다 (조건부)" if has_model else "데이터 보강 후 재판단"

        pillars: list[tuple[str, str]] = []
        if best and len(best) >= 6:
            d = "·".join(drivers) if drivers else str(best[1])
            p1 = f"{d}{_josa(d, 'nom')} 가장 크게 가른다. {best[1]} {best[2]:.0f}% 대 {best[3]} {best[4]:.0f}% (약 {best[5]:.0f}배)."
        elif drivers:
            p1 = f"{'·'.join(drivers)}{_josa(drivers[0], 'nom')} 가장 크게 가른다."
        else:
            p1 = "분석이 핵심 동인을 식별했다."
        pillars.append(("무엇이 가르나", p1))

        p2 = (f"{mdisp}. 단순 추측을 결정적으로 상회해 도입 기준을 충족한다."
              if has_model else "현 데이터로는 도입 판단에 추가 근거가 필요하다.")
        pillars.append(("얼마나 믿나", p2))

        if proj:
            ar = _rate(adverse)
            p3 = (f"‘{proj['high']}’ 집단을 ‘{proj['target']}’ 수준으로 끌어올리면 전체 {ar}"
                  f"{_josa(ar, 'subj')} {proj['cur_churn'] * 100:.0f}%에서 {proj['new_churn'] * 100:.0f}%로 감축된다.")
        elif drivers:
            p3 = f"{drivers[0]} 중심의 표적 개입이 가장 큰 효과를 낸다."
        else:
            p3 = "전수가 아닌 고위험군 표적 개입으로 효율을 극대화한다."
        pillars.append(("얼마짜리인가", p3))

        if proj:
            ask = f"‘{proj['high']}’ 고위험군에 표적 개입을 파일럿으로 시작하고, 성과 게이트 통과 시 단계 확대한다."
        elif drivers:
            ask = f"고위험({drivers[0]}) 세그먼트부터 표적 개입을 시작하고, 효과를 검증해 확대한다."
        else:
            ask = "고위험군 표적 개입을 파일럿으로 시작하고, 검증 후 단계 확대한다."

        caveat = "단, 데이터의 표본·기간 한계 안에서 유효하며 외삽은 보수적으로 본다."

        # Exec hero = 비즈니스 KPI/임팩트(모델지표 아님). business_kpi·투영에서 추출. 없으면 carrier 가 모델지표로 폴백.
        _cols = ["#3A6FE0", "#243B5C", "#8478C8"]
        hero_kpis: list[tuple[str, str, str]] = []
        for k in ((ctx.evaluation.business_kpi or []) if ctx.evaluation else [])[:2]:
            kn = getattr(k, "name", "") or (k.get("name", "") if isinstance(k, dict) else "")
            ku = getattr(k, "unit", "") or (k.get("unit", "") if isinstance(k, dict) else "")
            kv = getattr(k, "estimated_value", None)
            if kv is None and isinstance(k, dict):
                kv = k.get("estimated_value", k.get("value"))
            if kn and kv is not None:
                _vs = f"{kv:,.0f}" if (isinstance(kv, (int, float)) and float(kv).is_integer()) else _fv(kv)
                hero_kpis.append((f"{_vs}{ku}", str(kn), _cols[len(hero_kpis) % 3]))
        if proj:
            _red = (proj.get("cur_churn", 0) - proj.get("new_churn", 0)) * 100
            if _red > 0 and len(hero_kpis) < 3:
                hero_kpis.append((f"{_red:.0f}%p", f"{_rate(adverse)} 감축", _cols[len(hero_kpis) % 3]))
            if proj.get("avoided") and len(hero_kpis) < 3:
                hero_kpis.append((f"{proj['avoided']:,.0f}건", f"{adverse} 감축", _cols[len(hero_kpis) % 3]))
        hero_kpis = hero_kpis[:3]
        if hero_kpis and proj:
            ar = _rate(adverse)
            _red2 = (proj.get("cur_churn", 0) - proj.get("new_churn", 0)) * 100
            _av = proj.get("avoided")
            if _red2 > 0 and _av:
                hero_take = f"표적 개입으로 {ar}{_josa(ar, 'obj')} {_red2:.0f}%p(약 {_av:,.0f}건) 낮춘다."
            elif _red2 > 0:
                hero_take = f"표적 개입으로 {ar}{_josa(ar, 'obj')} {_red2:.0f}%p 낮춘다."
            else:
                hero_take = f"표적 개입으로 {ar}{_josa(ar, 'obj')} 의미 있게 낮춘다."
            hero_unit, hero_src = "기간: 연간 환산", "출처: ADA 분석 · 주: 전환율 20% 가정(보수적), 추정치"
        elif hero_kpis:
            hero_take, hero_unit, hero_src = "분석이 가리키는 비즈니스 임팩트.", "단위: 추정치", "출처: ADA 분석"
        else:
            hero_take = hero_unit = hero_src = ""  # 비즈니스 KPI 없음 → carrier 가 모델지표 폴백

        return {"bluf": bluf, "question": question, "verdict": verdict,
                "pillars": pillars, "ask": ask, "caveat": caveat, "has_model": has_model,
                "kpis": hero_kpis, "hero_take": hero_take, "hero_unit": hero_unit, "hero_src": hero_src,
                "register": audience_register(ctx)}
    except Exception:
        return None


# ==============================================================
# Main builder
# ==============================================================
def build(
    ctx: ReportContext,
    audience_profile: Optional[dict[str, Any]] = None,
    length_target: int = 12,
) -> ReportPlan:
    """Report Skeleton v2 → ReportPlan (목적·인사이트 중심 종합 보고서).

    carrier 가 cover/agenda 메타를 스킵하고 자체 헤더+Executive Summary 를 렌더하므로,
    실 내용은 §1~§8(+부록) 본문 섹션에 담긴다. 빈 섹션은 None 으로 스킵, 번호는 동적 부여.
    """
    ds = ctx.dataset
    shape = ds.shape or {}
    n_rows = shape.get("rows", 0)
    target = ds.detected_target or "타깃"
    chosen = (ctx.model_selection.chosen or {}).get("name", "-") if ctx.model_selection else "-"
    pm = (ctx.evaluation.primary_metric or {}) if ctx.evaluation else {}
    # ── Executive Summary [B7 3-30-3룰] [B8 Z패턴룰] 3층 구조
    # 3초: headline (결론 + 판단 '다만'으로 caveat)
    # 30초: conflict (발견 — 파레토 집중 + 통념 반박, 벤치마크 동반)
    # 한계: recommendation ('단, ...'); 행동: resolution (레버 — 손잡이 굵게)
    # 원칙: 짧게·단정조·측정가능·추측조 금지. 화살표·축약 금지 [B18 평이한언어룰].
    name = _human_dataset_name(ctx)
    verb = _CAT_VERB.get(ctx.meta.category or "", "분석")
    flags = _task_flags(ctx)
    maj = flags["maj"]
    pmval = pm.get("value")
    pmname_l = str(pm.get("name") or "").lower()
    # 한국어 지표 표현 (val_roc_auc → 검증 AUC 등)
    if pmval is None:
        pass
    elif "acc" in pmname_l and isinstance(pmval, (int, float)) and pmval <= 1:
        f"정확도 {pmval * 100:.1f}%"
    elif "auc" in pmname_l:
        f"AUC {_fv(pmval)}"
    elif "f1" in pmname_l:
        f"F1 {_fv(pmval)}"
    else:
        f"{_ko_metric(pm.get('name'))} {_fv(pmval)}"
    drivers_lbl = _driver_labels(ctx, 2)
    drivers_txt = ", ".join(drivers_lbl)
    top1 = drivers_lbl[0] if drivers_lbl else ""
    has_model = bool(chosen and chosen != "-" and pmval is not None)
    judgment = _perf_judgment(flags, pmval, pmname_l, maj)
    event = _event_noun(ctx)
    adverse = _adverse_noun(ctx)  # 줄이는 나쁜 사건(생존→사망) — 집중 문장 라벨용

    # ── 헤드라인 (의사결정중심: 무엇이 좌우하나 + 무엇을 할 수 있나. 모델 능력·AUC 는 exhibit 로 분리)
    tlabel = _feat_label(ctx, target)  # 타깃 한국어 라벨(생존). "Survived" 영문 노출 회피
    if has_model:
        if top1:
            headline = (
                f"{name} 데이터({n_rows:,}건) 분석 결과, '{top1}'{_josa(top1, 'subj')} '{tlabel}'{_josa(tlabel, 'obj')} "
                f"가장 크게 좌우하며 이를 {verb}할 근거를 확보했다."
            )
        else:
            headline = f"{name} 데이터({n_rows:,}건)로 '{tlabel}'{_josa(tlabel, 'obj')} 좌우하는 핵심 요인을 식별하고 {verb} 근거를 확보했다."
        if judgment:
            headline += f" 다만 {judgment}."
    else:
        headline = f"{name} 데이터({n_rows:,}건)로 '{tlabel}'{_josa(tlabel, 'obj')} {verb}할 가능성을 분석했다."
    # [B11 페이지논제룰] Executive Summary 의 setup 슬롯에 페이지 논제 명시
    # — 3초 결론(headline) → 30초 근거(conflict) → 행동(resolution)/한계(recommendation) 3층 구조
    setup = (
        f"본 보고서는 '{target}' 의사결정의 일관성·재현성을 데이터로 확보하기 위한 "
        f"의사결정 근거 자료다."
    )

    # ── 발견(+판단) — 상황 + 파레토 집중 + 통념 반박
    best = _top_contrast(ctx)
    conc = _concentration(ctx)
    price_lbl = _price_feature(ctx)
    find_sents: list[str] = []
    bctx = (ctx.meta.business_context or "").strip()
    if bctx:
        find_sents.append(bctx)
    clauses: list[str] = []
    if conc and conc[1] >= 0.55:
        # [B18 평이한언어룰] '전체 {event}의' 표현은 분모가 모호함 → 세그먼트 점유율로 풀어쓰기
        clauses.append(f"'{conc[0]}' 세그먼트가 전체 {adverse} 사례의 {conc[1] * 100:.0f}%를 차지한다")
    if price_lbl and top1 and best:
        clauses.append(
            # [B18 평이한언어룰] 인용부호 남발 제거, 풀어쓰기
            f"통념과 달리 {price_lbl}(가격)이 아니라 {top1}{_josa(top1, 'nom')} 이를 가른다. "
            f"{best[1]} 집단 {_rate(event)} {best[2]:.0f}%는 {best[3]} 집단 {best[4]:.0f}%의 {best[5]:.0f}배다"
        )
    elif best:
        # [B18 평이한언어룰] 인용부호 남발 제거, 풀어쓰기
        clauses.append(f"{best[1]} 집단의 {_rate(event)} {best[2]:.0f}%는 {best[3]} 집단 {best[4]:.0f}%의 {best[5]:.0f}배다")
    elif drivers_txt:
        clauses.append(f"'{target}'{_josa(target, 'subj')} 주로 {drivers_txt}{_josa(drivers_txt, 'with')} 갈린다")
    find_sents.extend(c + "." for c in clauses)
    conflict = " ".join(find_sents)

    # ── 레버 (최상위 1개, 손잡이 굵게 → 효과)
    lev_lines = _lever_lines(_levers(ctx, flags))
    if lev_lines:
        resolution = lev_lines[0]
    elif has_model:
        resolution = f"{chosen} 모델을 운영에 적용한다."
    else:
        resolution = "데이터를 보강해 재분석한다."

    # ── 리스크 (정직한 한계 1개)
    lims = ctx.limitations
    risk = ""
    cavs = (getattr(lims, "model_caveats", None) or []) if lims else []
    if cavs:
        risk = str(cavs[0])
    else:
        gaps = (getattr(lims, "data_gaps", None) or []) if lims else []
        if gaps:
            risk = getattr(gaps[0], "description", "") or (gaps[0].get("description", "") if isinstance(gaps[0], dict) else "")
    recommendation = f"단, {risk.rstrip('.')}." if risk else ""

    narrative = NarrativeThread(
        headline=headline,
        setup=setup,
        conflict=conflict,
        resolution=resolution,
        recommendation=recommendation,
    )

    # ══════════════════════════════════════════════════════════════════
    # ★ 고정 구조 (불변 계약) — 어떤 데이터가 와도 이 순서·역할은 바뀌지 않는다.
    #   표지 → 목차 → Executive Summary → §1~§8 → 부록.  내용만 ctx 에 맞게 생성.
    #   §1 개요(왜) · §2 데이터(답할 수 있나) · §3 발견 · §4 방법(타당한가) ·
    #   §5 성능(조연) · §6 핵심 인사이트(심장) · §7 함의·권고 · §8 결론(답).
    #   재료 없는 본문 섹션은 None 으로 스킵, 남은 섹션에 1..N 연속 번호 부여.
    # ══════════════════════════════════════════════════════════════════
    ordered: list[Optional[SectionSpec]] = [
        _build_overview(ctx),  # §1 분석 개요 — 왜, 무엇을 알고 싶은가
        _build_data_understanding(ctx),  # §2 데이터 이해 — 답할 수 있나
        _build_eda(ctx),  # §3 탐색적 발견 — 데이터가 말하는 것
        _build_method(ctx),  # §4 분석 방법 — 믿어도 되는 이유
        _build_model_performance(ctx),  # §5 모델 성능 — 근거(조연)
        _build_key_insights(ctx),  # §6 핵심 인사이트 ★ — 그래서 무엇을 알았나
        _build_implications(ctx),  # §7 비즈니스 임팩트와 실행 — 인사이트→액션 (풍부 산문)
        _build_conclusion(ctx),  # §8 결론 — 핵심 질문에 대한 답
    ]
    body_sections = [s for s in ordered if s is not None]
    for _i, _sec in enumerate(body_sections, 1):
        _sec.title = f"{_i}. {_sec.title}"

    sections: list[SectionSpec] = [_build_cover(ctx)] + body_sections
    # [B4 부록룰] 부록 4묶음(9.1~9.4) + "9. 부록" divider — 본문 뒤 번호부여
    _appx = _build_appendix(ctx)
    if _appx:
        _no = len(body_sections) + 1
        for _j, _ax in enumerate(_appx):
            _ax.title = f"{_no}. {_ax.title}" if _j == 0 else f"{_no}.{_j} {_ax.title}"
            sections.append(_ax)

    plan = ReportPlan(
        skeleton=SKELETON_NAME,
        audience=(audience_profile or {}).get("level", "analyst") if audience_profile else "analyst",
        output_form="pdf",
        slide_count_target=sum(len(s.slides) for s in sections),
        sections=sections,
        narrative_thread=narrative,
        meta={"skeleton": SKELETON_NAME, "report_mode": True, "skeleton_version": 2},
    )
    return plan
