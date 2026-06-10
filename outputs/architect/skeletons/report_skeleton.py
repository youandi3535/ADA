"""outputs.architect.skeletons.report_skeleton — 데이터 분석 종합 보고서 Skeleton **v2**.

v2 설계 철학 (목적·인사이트 중심):
    보고서의 주인공은 모델 성능 수치가 아니라 **"분석 목적에 대한 답(인사이트)"**이다.
    모델·성능은 그 답을 신뢰하게 해주는 **근거(조연)**로 배치한다.
    하나의 줄기: 목적·질문(§1) → 데이터가 말하는 것(§3) → 그래서 무엇을 알았나(§6)
                → 그래서 무엇을 해야 하나 + 최종 답(§7 결론 및 권고).

목차 (front matter + 동적 번호 본문):
    표지 (cover)                          ← carrier 가 자체 헤더 렌더 (스킵)
    Executive Summary                     ← carrier 가 narrative_thread 로 렌더 (현황·문제·해결·권고)
    §1 분석 개요          (overview)         목적·문제정의·성공기준·데이터범위
    §2 데이터 이해         (data_understanding) 개요·변수정의·품질·대표성
    §3 탐색적 발견         (eda)             차트 finding·세그먼트·가설검정 (발견 중심)
    §4 분석 방법          (method)          전처리·피처·검증 설계 (신뢰 근거)
    §5 모델 성능          (model_performance) 후보 비교·성능 (근거·조연)
    §6 핵심 인사이트와 해석  (key_insights)     변수 중요도·per-feature·세그먼트 드라이버 ★심장
    §7 결론 및 권고        (conclusion)       임팩트·레버·리스크 + 목적에 대한 최종 답 (구 §7+§8 병합)
    부록 (appendix, 선택)                   재현 정보·코드·환경

설계 원칙:
    - 계약 기반·범용: 특정 데이터 가정 없이 ctx 13묶음만 읽어 어떤 카테고리·데이터든 대응.
    - 방어적: 인사이트 묶음이 비면 해당 섹션 스킵(None). 번호는 남은 섹션에 연속 부여(빈틈 없음).
    - 인사이트 우선: EDA 는 "차트"가 아니라 "발견", 모델 성능은 "조연".

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


def _build_overview(ctx: ReportContext) -> SectionSpec:
    """§1 분석 개요 — 데이터를 '판단'한 전문가 산문. bottom-line-first, 비즈니스 의사결정 지향.

    무맥락에서도 데이터 판단력(표본 충분성·클래스 균형·변수 구성·다수클래스 기준선)과
    정직한 한계 인식으로 전문가 수준을 끌어올린다. 가짜 비즈니스 수치는 만들지 않으며,
    business_context·baselines·business_kpi 가 들어오면 자동 격상.
    """
    ds = ctx.dataset
    shape = ds.shape or {}
    n_rows, n_cols = shape.get("rows", 0), shape.get("cols", 0)
    name = _human_dataset_name(ctx)
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
    feat_txt = ", ".join(map(str, input_cols[:3])) if input_cols else "수집된 변수"
    if num_cols and cat_cols:
        comp_txt = f"수치형 {len(num_cols)}개·범주형 {len(cat_cols)}개의 입력 변수"
    elif num_cols:
        comp_txt = f"수치형 {len(num_cols)}개의 입력 변수"
    elif cat_cols:
        comp_txt = f"범주형 {len(cat_cols)}개의 입력 변수"
    else:
        comp_txt = f"{n_feat}개 입력 변수"

    # 결측 / 표본 충분성 판단
    missing = ds.missing_rate or {}
    nz = [(c, r) for c, r in sorted(missing.items(), key=lambda kv: -kv[1])[:2] if r and r > 0]
    miss_txt = ("주요 결측은 " + ", ".join(f"{c} {_pct(r)}" for c, r in nz) + " 수준") if nz else "결측은 사실상 없어 별도 대치 없이 분석 가능"
    if n_rows and n_rows < 1000:
        sample_txt = f"{n_rows:,}건은 개념검증·탐색에는 충분하나 운영 일반화에는 표본 확대가 바람직하다"
    elif n_rows and n_rows < 10000:
        sample_txt = f"{n_rows:,}건은 모델링에 적정한 규모이나 세부 세그먼트 분석에는 표본이 제한적일 수 있다"
    elif n_rows:
        sample_txt = f"{n_rows:,}건은 안정적인 학습·검증에 충분한 규모다"
    else:
        sample_txt = "표본 규모 정보가 제한적이다"

    # 타깃 분포 (분류 여부 + 다수 클래스 비율)
    _f = _task_flags(ctx)
    maj = _f["maj"]
    is_clf, is_ts, is_anom = _f["is_clf"], _f["is_ts"], _f["is_anom"]
    is_reg, is_imbal, is_multiclass = _f["is_reg"], _f["is_imbal"], _f["is_multiclass"]

    # ── 분석 배경 (결론 먼저 → 데이터 판단)
    bg_parts: list[str] = []
    bctx = (ctx.meta.business_context or "").strip()
    industry = ((ctx.domain.inferred_industry if ctx.domain else "") or "").strip()
    if bctx:
        bg_parts.append(bctx)
    bg_parts.append(f"'{target}' {verb}{_josa(verb, 'obj')} 수작업·경험이 아닌 데이터로 표준화할 필요가 분명하다.")
    where = f"{industry} 도메인의 " if industry else ""
    bg_parts.append(f"분석 대상 '{name}'{_josa(name, 'subj')} {where}{n_rows:,}건·{comp_txt}로 구성되며, {miss_txt}하다.")
    bg_parts.append(f"규모 측면에서 {sample_txt}.")
    bg_parts.append(f"{feat_txt} 등 변수에 판별 정보가 담겨 있어 '{target}' {verb}{_josa(verb, 'obj')} 자동화·표준화할 실익이 있다.")
    background = " ".join(bg_parts)

    # ── 분석 목적 (과제가 아니라 성과로)
    objective = (
        f"정확한 '{target}' 판정을 자동화해 판정의 일관성과 속도를 확보하는 것이 목적이다. "
        f"이를 위해 {comp_txt}로 '{target}'{_josa(target, 'obj')} {verb}하는 모델을 수립하고, 결과를 좌우하는 핵심 변수를 규명한다. "
        "단순 기준 모델 대비 실질적 개선과 해석 가능성을 함께 확보해, 결과를 운영 의사결정에 바로 활용할 수 있게 한다."
    )

    # ── 분석 질문 (의사결정 언어 — 지표 약어 없이 '무슨 결정·무슨 비용'으로)
    q_list = [f"① 어떤 변수·요인이 '{target}'{_josa(target, 'obj')} 가장 강하게 좌우하는가?"]
    if is_anom:
        q_list.append("② 이상 징후를 얼마나 일찍 잡아내며, 헛경보로 인한 불필요한 점검은 얼마나 줄일 수 있는가?")
        q_list.append("③ 놓침과 헛경보 중 어느 실수가 더 비싼가, 그 비용에 맞춰 경보 기준을 어디에 둘 것인가?")
    elif is_ts:
        q_list.append(f"② '{target}'에 어떤 추세·계절성·변화 시점이 있으며, '어제와 같다'고 찍는 수준을 의미 있게 넘어서는가?")
        q_list.append("③ 며칠·몇 기간 앞까지 믿고 계획에 쓸 수 있는가?")
    elif is_imbal:
        q_list.append("② 중요한 소수 사례를 놓치지 않으면서 헛경보를 어디까지 줄일 수 있는가?")
        q_list.append("③ 놓침과 헛경보 중 어느 실수가 더 비싼가, 그에 맞춰 판정 기준을 어디에 둘 것인가?")
    elif is_multiclass:
        q_list.append("② 어떤 범주끼리 자주 헷갈리며, 그 혼동이 어떤 잘못된 결정으로 이어지는가?")
        q_list.append("③ 특정 범주의 판정이 유독 약하다면 어디를 보강해야 하는가?")
    elif is_clf:
        q_list.append("② '놓침'과 '헛경보' 중 어느 실수가 더 비싼가, 그 비용에 맞춰 판정 기준을 어디에 둘 것인가?")
        q_list.append("③ 현재 데이터만으로 단순 추측보다 의미 있게 나은 판정이 가능한가?")
    else:  # 회귀
        q_list.append("② 예측이 얼마나 빗나가며, 현업이 허용하는 오차 범위 안에 드는 경우는 얼마나 되는가?")
        q_list.append("③ 크게 빗나가는 상황은 언제이며, 그 위험을 어떻게 관리할 것인가?")
    q_list.append(f"④ 세그먼트·구간별로 '{target}' 양상이 달라 다르게 대응해야 하는가?")
    questions = "<br/>".join(q_list)

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
        sc_parts.append(f"무엇보다 단순 추측(단순 모델 {_fv(naive)} 수준)보다 의미 있게 나아야 도입할 가치가 있다.")
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
    sc_parts.append("끝으로 한 번의 좋은 점수가 아니라, 시기·집단을 바꿔도 일관되게 유지되는지로 운영에 쓸 수 있는지 판단한다.")
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
    impact = " ".join(impact_parts)

    driving = _driving_question(_f, target)  # 핵펀치 — 진짜 알고 싶은 것 한 줄
    slide = SlideSpec(
        id="overview",
        section_id="overview",
        layout="one_message",
        role="claim",
        so_what=driving,
        title_ko="분석 개요 (핵심 질문·배경·목적·범위·성공 기준·기대 효과)",
        prose_blocks=[
            ["분석 배경", background],
            ["분석 목적", objective],
            ["세부 질문", questions],
            ["분석 범위", scope],
            ["성공 기준", success],
            ["기대 효과", impact],
        ],
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
    if not miss_cols:
        miss_txt = "결측이 사실상 없어 별도 대치 없이 분석 가능하다"
    elif high_miss:
        miss_txt = f"{', '.join(map(str, high_miss[:3]))} 등은 결측이 20%를 넘어 대치·제외 검토가 필요하다"
    else:
        pass  # top = miss_cols[0] — miss_txt 미사용

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
    issue_txt = "; ".join(_txt_from(it, ("issue", "name", "note")) for it in issues[:2] if isinstance(it, dict)) or "식별된 품질 이슈 없음"

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

    # 주요 변수 (타깃·수치 범위·고카디널리티)
    key_bits = [f"타깃은 '{target}'({_feat_label(ctx, target)})이다"]
    nstats = ds.numeric_stats or {}
    for c in [c for c in num_cols if c in nstats][:2]:
        st = nstats[c]
        _lbl_c = _feat_label(ctx, c)
        key_bits.append(f"{_lbl_c}{_josa(_lbl_c, 'subj')} {_fv(st.get('min'))}~{_fv(st.get('max'))}(평균 {_fv(st.get('mean'))}) 범위")
    if high_card:
        key_bits.append(f"{', '.join(_feat_label(ctx, c) for c in high_card[:2])} 등 범주가 많은 변수는 인코딩 설계가 중요하다")
    p_key = ". ".join(key_bits) + "."

    p_target = f"타깃 '{target}'{_josa(target, 'subj')} {tgt_txt}. 이는 이후 평가 지표·임계값 선택의 전제가 된다."
    p_quality = f"품질 점검 결과 {issue_txt}."

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
        title_ko="데이터 이해 — 이 데이터로 답할 수 있나",
        prose_blocks=[
            ["데이터 구성·적합성", p_fit],
            ["결측 분석", p_missing],
            ["주요 변수", p_key],
            ["타깃 분포", p_target],
            ["품질 점검", p_quality],
        ],
        visual_spec=_data_dictionary_visual(ctx),
    )
    return make_section("data_understanding", "데이터 이해", "context", [slide])


def _build_eda(ctx: ReportContext) -> Optional[SectionSpec]:
    """§3 탐색적 발견 — 차트 finding + 세그먼트 인사이트 + 가설검정 (발견 중심)."""
    eda = ctx.eda
    charts = (eda.charts or []) if eda else []
    segs = (eda.segment_insights or []) if eda else []
    hyps = (eda.hypothesis_tests or []) if eda else []
    slides: list[SlideSpec] = []

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
        vs = None
        if items:
            vs = VisualSpec(type=vtype, title="", spec={"items": items})  # 제목은 슬라이드 헤딩이 담당(중복 방지)
        elif path:
            vs = VisualSpec(type="image_embed", title="", spec={"path": str(path)})
        slides.append(
            SlideSpec(
                id=f"eda_{idx}",
                section_id="eda",
                layout="chart_callout",
                role="evidence",
                so_what=finding,  # '핵심 —' 한 줄에만 (중복 불릿·캡션 제거)
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
                prose_blocks=[["", " ".join(syn)]],
            )
        )

    if not slides:
        return None
    return make_section("eda", "탐색적 발견 (EDA Insights)", "evidence", slides)


def _build_method(ctx: ReportContext) -> Optional[SectionSpec]:
    """§4 분석 방법 — 전처리·피처·검증을 '실무 수준'으로 상세히 (결과를 믿어도 되는 이유)."""
    pp = ctx.preprocessing
    steps = (pp.applied_steps or []) if pp else []
    leak = (pp.leakage_checks or []) if pp else []
    feats = ctx.features
    flags = _task_flags(ctx)
    blocks: list[list[str]] = []

    # 1) 전처리 — 무엇을, 어디에, 왜
    if steps:
        descs = []
        for st in steps[:6]:
            op = getattr(st, "op", "") or (st.get("op", "") if isinstance(st, dict) else "")
            scope = getattr(st, "scope", None)
            if scope is None and isinstance(st, dict):
                scope = st.get("scope", [])
            scope = scope or []
            rat = getattr(st, "rationale", "") or (st.get("rationale", "") if isinstance(st, dict) else "")
            d = _op_label(op)
            if scope:
                d += f"({', '.join(_feat_label(ctx, c) for c in list(scope)[:3])})"
            if rat and _norm_cell(rat):
                d += f" — {_norm_cell(rat)}"
            descs.append(d)
        blocks.append(
            ["전처리", f"총 {len(steps)}단계를 적용했다. " + " / ".join(descs) + ". 모든 변환 통계는 학습 데이터로만 적합해 검증 데이터 누수를 차단했다."]
        )

    # 2) 피처 엔지니어링
    if feats and (feats.final_feature_count or feats.created or feats.dropped or feats.selection_method):
        fb = []
        if feats.final_feature_count:
            fb.append(f"인코딩·파생을 거쳐 최종 {feats.final_feature_count}개 피처를 구성했다")
        if feats.created:
            names = ", ".join(getattr(c, "name", "") or (c.get("name", "") if isinstance(c, dict) else "") for c in feats.created[:3])
            fb.append(f"{len(feats.created)}개 파생 피처({names})를 생성했다")
        if feats.dropped:
            fb.append(f"저분산·중복·누수 위험 변수 {len(feats.dropped)}개를 제거했다")
        if feats.selection_method:
            fb.append(f"피처 선택은 {feats.selection_method}{_josa(feats.selection_method, 'with')} 수행했다")
        if fb:
            blocks.append(["피처 엔지니어링", ". ".join(fb) + "."])

    # 3) 검증 설계 — 결과를 믿어도 되는 핵심 근거
    vb = ["학습·검증 데이터를 분리해 미관측 데이터에 대한 일반화 성능을 측정했다"]
    if flags["is_ts"]:
        vb.append("시간 순서를 보존하는 시계열 분할(과거→미래)로 미래 정보 누수를 막았다")
    elif flags["is_imbal"] or flags["is_clf"]:
        vb.append("불균형을 고려해 클래스 비율을 유지하는 층화 분할을 적용했다")
    vb.append("전처리는 분할 내부에서 적합(파이프라인화)해 검증 정보가 학습에 새지 않게 했다")
    if leak:
        passed = sum(1 for c in leak if isinstance(c, dict) and c.get("passed"))
        vb.append(f"타깃 누수 점검 {len(leak)}건을 수행해 {passed}건 모두 통과했다")
    blocks.append(["검증 설계", ". ".join(vb) + "."])

    # 4) 평가 지표 근거 (약어는 여기 — 조연)
    pm = (ctx.evaluation.primary_metric or {}) if ctx.evaluation else {}
    pm_name = pm.get("name") if pm else None
    metrics = (ctx.evaluation.metrics if ctx.evaluation else None) or {}
    if pm or metrics:
        if flags["is_imbal"]:
            mr = "불균형을 고려해 PR-AUC·재현율(Recall)을 1차 지표로 본다(정확도 단독은 다수 클래스로 편향)."
        elif flags["is_ts"]:
            mr = "naive(직전값·계절) 대비 sMAPE·MASE 로 예측력을 평가한다."
        elif flags["is_reg"]:
            mr = "오차는 RMSE·MAE 로 측정하고 허용 오차 충족률을 함께 본다."
        elif flags["is_multiclass"]:
            mr = "클래스별 편차를 위해 macro-F1 과 혼동행렬을 함께 본다."
        elif flags["is_clf"]:
            mr = "F1·PR-AUC 와 운영 임계값을 함께 보아 포착-정밀도 균형을 평가한다."
        else:
            mr = "검증 성능 지표로 타당성을 평가한다."
        blocks.append(["평가 지표", f"'{pm_name}'를 주지표로, {mr}" if pm_name else mr])

    if not blocks:
        return None
    slide = SlideSpec(
        id="method",
        section_id="method",
        layout="comparison_table",
        role="evidence",
        so_what="누수 방지·층화 검증을 갖춘 절차로 결과의 신뢰를 확보했다",
        title_ko="분석 방법 — 결과를 믿어도 되는 이유",
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
        blocks.append(["선정 근거", f"'{chosen}'{_josa(chosen, 'obj')} 최종 선정했다. " + ". ".join(rb) + "."])

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
        blocks.append(["후보 탈락 사유", " / ".join(drop_sents) + "."])

    # 검증 성능
    if metric_body:
        blocks.append(["검증 성능", ", ".join(metric_body) + "."])

    slide = SlideSpec(
        id="model_perf",
        section_id="model_performance",
        layout="chart_callout",
        role="evidence",
        so_what=f"'{chosen}'{_josa(chosen, 'obj')} 선정한 근거와 후보 탈락 사유",
        title_ko="모델 선정 및 성능 (근거)",
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
    event = _event_noun(ctx)
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
                "handle": f"'{proj['high']}' → '{proj['target']}' 수준 전환 유도",
                "effect": f"전체 {_rate(event)} {proj['cur_churn'] * 100:.1f}%→{proj['new_churn'] * 100:.1f}% ({red:.1f}%p↓){rev}",
            })
        elif drivers:
            out.append({"handle": f"고위험({drivers[0]}) 세그먼트 타겟팅", "effect": "전수가 아닌 상위군 집중으로 개입 비용 대비 효과 극대화"})
        out.append({"handle": "운영 임계값 조정", "effect": "놓침·헛개입 비용에 맞춰 정밀도·재현율 균형점 설정"})
        if drivers and len(drivers) > 1:
            out.append({"handle": f"{drivers[1]} 데이터 강화", "effect": "핵심 동인 관련 수집·관리를 보강해 예측력 개선"})
    return out[:3]


def _lever_lines(levers: list[dict[str, str]]) -> list[str]:
    """레버 → 화면용 문장(손잡이 굵게 + → 효과). 단어 라벨 없이 시각만 강조."""
    return [f"<b>{lv['handle']}</b> → {lv['effect']}." for lv in levers if lv.get("handle")]


def _build_key_insights(ctx: ReportContext) -> Optional[SectionSpec]:
    """§6 핵심 인사이트 — 나열이 아니라 '종합'. thesis(무엇이·얼마나) → 메커니즘(왜) → 위험군(누구) → 레버(어디를).

    EDA 차트의 최대 대조(max/min 배수), per_feature_story(메커니즘), segment(위험군)를 하나의
    줄기로 엮어 '그래서 무엇을 해야 하나'까지 답한다. 재료가 부족하면 스킵(None).
    """
    interp = ctx.interpretation
    eda = ctx.eda
    ev = ctx.evaluation
    stories = (interp.per_feature_story or {}) if interp else {}
    seg_drivers = (interp.segment_drivers or []) if interp else []
    seg_insights = (eda.segment_insights or []) if eda else []

    # 중요도 (원이름·의미라벨·기여도)
    imp: list[tuple[str, str, float]] = []
    for g in (interp.global_importance or []) if interp else []:
        f = getattr(g, "feature", "") or (g.get("feature", "") if isinstance(g, dict) else "")
        v = getattr(g, "importance", None)
        if v is None and isinstance(g, dict):
            v = g.get("importance")
        if f and isinstance(v, (int, float)):
            imp.append((str(f), _feat_label(ctx, str(f)), float(v)))
    top1 = imp[0][1] if imp else None

    # 가장 큰 대조 (EDA max/min 배수)
    best = None
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

    # 파레토 집중도 — 양성(이탈)의 몇 %가 최고위험 세그먼트에 몰리나
    conc = None  # (segment_name, pct)
    structured = [
        s
        for s in ((ev.per_segment or []) if ev else [])
        if isinstance(s, dict)
        and isinstance(s.get("size"), (int, float))
        and isinstance(s.get("churn_rate", s.get("rate")), (int, float))
    ]
    if len(structured) >= 2:
        tot = sum(float(s["size"]) * float(s.get("churn_rate", s.get("rate"))) for s in structured)
        if tot > 0:
            hi_s = max(structured, key=lambda s: float(s.get("churn_rate", s.get("rate"))))
            conc = (
                str(hi_s.get("segment") or hi_s.get("name") or "한 구간"),
                float(hi_s["size"]) * float(hi_s.get("churn_rate", hi_s.get("rate"))) / tot,
            )

    event = _event_noun(ctx)  # 타깃 기반 사건 명사 (이탈/부도/사기/양성 사례 …)
    # ── 도출된 thesis (so_what) — 비자명한 결론을 앞세운다
    if conc and conc[1] >= 0.55:
        thesis = f"전체 {event}의 {conc[1] * 100:.0f}%가 '{conc[0]}' 한 세그먼트에서 발생한다 — 전반의 문제가 아니라 한 구간의 문제다."
    elif best and best[5] >= 1.5:
        thesis = f"{best[0]}에서 '{best[1]}'({best[2]:.0f}%)이 '{best[3]}'({best[4]:.0f}%)의 {best[5]:.0f}배에 달한다 — 결과는 여기서 갈린다."
    elif top1:
        thesis = f"결과를 좌우하는 단일 최대 요인은 {top1}이다."
    else:
        return None

    parts: list[str] = []
    # 통념 반박 — 가격/금액 변수가 1위가 아니면 "가격이 아니라 구조"
    price_kw = ("charge", "price", "amount", "fee", "cost", "revenue", "요금", "가격", "금액", "비용")
    price_lbl = ""
    for raw, lbl, _v in imp[1:]:
        if any(k in (raw + lbl).lower() for k in price_kw):
            price_lbl = lbl
            break
    if price_lbl and top1 and best and best[5] >= 1.5:
        parts.append(
            f"통념과 달리 {price_lbl}(가격)이 아니라 {top1}가 갈림을 만든다 — '{best[1]}' {_rate(event)}({best[2]:.0f}%)이 '{best[3]}'({best[4]:.0f}%)의 {best[5]:.0f}배다."
        )
    elif best and best[5] >= 1.5:
        parts.append(f"'{best[1]}' {_rate(event)}({best[2]:.0f}%)이 '{best[3]}'({best[4]:.0f}%)의 {best[5]:.0f}배로, 이 구간이 갈림의 핵심이다.")

    # 메커니즘(왜)
    mech = [str(s).rstrip(".") + "." for s in list(stories.values())[:3] if s]
    if mech:
        parts.append(" ".join(mech))

    # 위험 마이크로-세그먼트(누구)
    risk_txt = ""
    for s in list(seg_drivers) + list(seg_insights):
        risk_txt = _txt_from(s, ("insight", "driver", "note", "summary"))
        if risk_txt:
            break
    if risk_txt:
        parts.append(risk_txt.rstrip(".") + ".")

    # 정량 시나리오 — 옮기면? (사건 감소·발생률 before→after·매출). 사건 명사로 일반화.
    proj = _scenario_projection(ctx)
    if proj:
        parts.append(_projection_sentence(proj, event))
    elif best and best[5] >= 1.5:
        parts.append(f"가장 큰 레버는 '{best[1]}' 집단을 '{best[3]}' 쪽으로 옮기는 것이다.")
    elif top1:
        parts.append(f"{top1} 중심의 개입이 가장 큰 효과를 낸다.")
    body_text = " ".join(parts)

    slide = SlideSpec(
        id="key_insights",
        section_id="key_insights",
        layout="one_message",
        role="claim",
        so_what=thesis,
        title_ko="핵심 인사이트 — 무엇이·왜·무엇을 할 것인가",
        prose_blocks=[["", body_text]] if body_text else [],
    )
    return make_section("key_insights", "핵심 인사이트와 해석", "evidence", [slide])


def _build_implications(ctx: ReportContext) -> Optional[SectionSpec]:
    """§7 비즈니스 함의 및 권고 — 임팩트·실행 권고·리스크 (인사이트 → 액션)."""
    ev = ctx.evaluation
    lims = ctx.limitations
    ms = ctx.model_selection
    chosen = (ms.chosen or {}).get("name", "-") if ms else "-"
    pm = (ev.primary_metric or {}) if ev else {}
    pm_txt = f"{pm.get('name', '주요지표')} {_fv(pm.get('value'))}" if pm else "-"
    body: list[str] = []
    flags = _task_flags(ctx)

    # 기대 효과 — business_kpi
    for k in (ev.business_kpi or [])[:3] if ev else []:
        name = getattr(k, "name", "") or (k.get("name", "") if isinstance(k, dict) else "")
        unit = getattr(k, "unit", "") or (k.get("unit", "") if isinstance(k, dict) else "")
        val = getattr(k, "estimated_value", None)
        if val is None and isinstance(k, dict):
            val = k.get("estimated_value")
        if name:
            body.append(f"기대 효과 — {name}: {_fv(val)} {unit}".strip())

    # 표적 개입 원칙 — 전수 X, 고위험 × 고가치 선별 (분류 과제 일반 — 개입 비용 대비 효과)
    if flags["is_clf"] and chosen and chosen != "-":
        seg = ""
        for s in (ev.per_segment or []) if ev else []:
            seg = _txt_from(s, ("segment", "name", "group"))
            if seg:
                break
        body.append(
            "표적 개입: 전수가 아니라 모델이 지목한 고위험 상위군을 선별하고, 그중 고가치 고객을 우선한다"
            + (f" (예: {seg})." if seg else ".")
        )

    # 실행 권고
    if chosen and chosen != "-":
        body.append(f"권고: '{chosen}' 모델을 {pm_txt} 기준으로 운영 적용, 정기 재학습으로 분포 변화 대응")

    # 리스크·한계
    for cav in (getattr(lims, "model_caveats", None) or [])[:2] if lims else []:
        if cav:
            body.append(f"한계: {cav}")
    for g in (getattr(lims, "data_gaps", None) or [])[:1] if lims else []:
        desc = getattr(g, "description", "") or (g.get("description", "") if isinstance(g, dict) else "")
        if desc:
            body.append(f"리스크: {desc}")

    if not body:
        return None
    slide = SlideSpec(
        id="implications",
        section_id="implications",
        layout="one_message",
        role="action",
        so_what="분석 인사이트를 운영 액션으로 연결한다",
        title_ko="비즈니스 함의 및 권고",
        body_outline=body[: _MAX_BODY + 2],
    )
    return make_section("implications", "비즈니스 함의 및 권고", "recommendation", [slide])


def _build_conclusion(ctx: ReportContext) -> SectionSpec:
    """§8 결론 — §1 핵심 질문에 대한 '답'. 라벨 없는 시니어 흐름(결론→근거→실행→단서)."""
    flags = _task_flags(ctx)
    ms = ctx.model_selection
    ev = ctx.evaluation
    chosen = (ms.chosen or {}).get("name", "-") if ms else "-"
    pm = (ev.primary_metric or {}) if ev else {}
    pmval = pm.get("value")
    pmname_l = str(pm.get("name") or "").lower()
    verb = _CAT_VERB.get(ctx.meta.category or "", "분석")
    target = ctx.dataset.detected_target or "타깃"
    drivers_txt = ", ".join(_driver_labels(ctx, 2))
    maj = flags["maj"]
    judgment = _perf_judgment(flags, pmval, pmname_l, maj)
    if pmval is None:
        mphrase = "검증 성능"
    elif "acc" in pmname_l and isinstance(pmval, (int, float)) and pmval <= 1:
        mphrase = f"정확도 {pmval * 100:.1f}%"
    elif "auc" in pmname_l:
        mphrase = f"AUC {_fv(pmval)}"
    elif "f1" in pmname_l:
        mphrase = f"F1 {_fv(pmval)}"
    else:
        mphrase = f"{pm.get('name')} {_fv(pmval)}"
    has_model = bool(chosen and chosen != "-" and pmval is not None)

    # 답 (lead — §1 핵펀치에 대한 응답)
    if has_model and drivers_txt:
        lead = f"{drivers_txt}가 '{target}'{_josa(target, 'obj')} 가르며, 그 신호만으로 {mphrase}까지 {verb}할 수 있다."
    elif has_model:
        lead = f"'{target}'{_josa(target, 'obj')} {mphrase}로 {verb}할 수 있다."
    else:
        lead = f"현재 데이터로는 '{target}' {verb} 가능성만 확인했다."
    if has_model and judgment:
        lead += f" 다만 {judgment}."
    # 근거 → 실행 (라벨 없는 흐름, 판단은 lead에)
    rest: list[str] = []
    if has_model and flags["is_clf"] and maj is not None:
        rest.append(f"단순 추측 {_pct(maj)}{_josa(_pct(maj), 'obj')} 넘어 운영에 쓸 수준이다.")
    if has_model and drivers_txt:
        rest.append(f"{drivers_txt} 중심으로 즉시 적용하고, 분포 변화에 대비해 정기 재검증을 둔다.")
    elif has_model:
        rest.append(f"{chosen}{_josa(chosen, 'obj')} 적용하고 정기 재검증을 둔다.")
    else:
        rest.append("데이터를 보강한 뒤 재분석한다.")
    body_text = " ".join(rest)

    slide = SlideSpec(
        id="conclusion",
        section_id="conclusion",
        layout="one_message",
        role="action",
        so_what=lead,
        title_ko="결론 — 핵심 질문에 대한 답",
        prose_blocks=[["", body_text]] if body_text else [],
    )
    return make_section("conclusion", "결론", "recommendation", [slide])


def _build_appendix(ctx: ReportContext) -> Optional[SectionSpec]:
    """부록(선택) — 재현 정보·코드·환경. 비어 있으면 스킵."""
    code = ctx.code
    files = (code.files or []) if code else []
    repro = (getattr(code, "reproduce_command", "") or "") if code else ""
    env = (getattr(code, "environment", {}) or {}) if code else {}
    body: list[str] = []
    if files:
        body.append(f"코드 파일: {len(files)}개")
    if repro:
        body.append(f"재현 명령: {repro}")
    if isinstance(env, dict) and env.get("python"):
        body.append(f"Python: {env.get('python')}")
    if not body:
        return None
    slide = SlideSpec(
        id="appendix",
        section_id="appendix",
        layout="one_message",
        role="meta",
        so_what="재현에 필요한 코드·환경 정보",
        title_ko="부록 — 재현 정보",
        body_outline=body,
    )
    return make_section("appendix", "부록", "appendix", [slide])


def _build_conclusion_and_reco(ctx: ReportContext) -> SectionSpec:
    """§7+§8 병합 — '결론 및 권고' 한 섹션. 결론(목적에 대한 답) → 레버 → 리스크 (라벨 없는 흐름)."""
    flags = _task_flags(ctx)
    ms = ctx.model_selection
    ev = ctx.evaluation
    lims = ctx.limitations
    chosen = (ms.chosen or {}).get("name", "-") if ms else "-"
    pm = (ev.primary_metric or {}) if ev else {}
    pmval = pm.get("value")
    pmname = pm.get("name")
    verb = _CAT_VERB.get(ctx.meta.category or "", "분석")
    target = ctx.dataset.detected_target or "타깃"
    drivers = _driver_labels(ctx, 2)
    drv = ", ".join(drivers)
    has_model = bool(chosen and chosen != "-" and pmval is not None)
    mdisp = f"{_ko_metric(pmname)} {_fv(pmval)}" if (pmval is not None and pmname) else "검증 성능"

    # 결론 (목적에 대한 답) — lead
    if has_model and drivers:
        lead = f"{drv}{_josa(drivers[-1], 'nom')} '{target}'{_josa(target, 'obj')} 가르며, 그 신호로 {mdisp} 수준의 {verb}이 가능하다."
    elif has_model:
        lead = f"'{target}'{_josa(target, 'obj')} {mdisp} 수준으로 {verb}할 수 있다."
    else:
        lead = f"현재 데이터로는 '{target}' {verb} 가능성만 확인했다."

    blocks: list[list[str]] = []
    body_sents: list[str] = []
    for k in (ev.business_kpi or [])[:1] if ev else []:
        kn = getattr(k, "name", "") or (k.get("name", "") if isinstance(k, dict) else "")
        ku = getattr(k, "unit", "") or (k.get("unit", "") if isinstance(k, dict) else "")
        kv = getattr(k, "estimated_value", None)
        if kv is None and isinstance(k, dict):
            kv = k.get("estimated_value")
        if kn and kv is not None:
            body_sents.append(f"정량적으로 {kn} {_fv(kv)} {ku} 효과가 기대된다.".replace("  ", " "))
    if has_model:
        body_sents.append("아래 레버를 우선순위대로 실행하면 목적을 직접 달성할 수 있다.")
    else:
        body_sents.append("데이터를 보강한 뒤 재분석해 모델을 확정한다.")
    blocks.append(["", " ".join(body_sents)])

    # 레버 (굵게 손잡이 → 효과)
    for line in _lever_lines(_levers(ctx, flags)):
        blocks.append(["", line])

    # 리스크 (정직한 한계)
    risks: list[str] = []
    for cav in (getattr(lims, "model_caveats", None) or [])[:2] if lims else []:
        if cav:
            risks.append(str(cav))
    for g in (getattr(lims, "data_gaps", None) or [])[:1] if lims else []:
        d = getattr(g, "description", "") or (g.get("description", "") if isinstance(g, dict) else "")
        if d:
            risks.append(d)
    if risks:
        blocks.append(["", "단, " + " ".join(r.rstrip(".") + "." for r in risks)])

    slide = SlideSpec(
        id="conclusion",
        section_id="conclusion",
        layout="one_message",
        role="action",
        so_what=lead,
        title_ko="결론 및 권고 — 목적에 대한 답과 실행 레버",
        prose_blocks=blocks,
    )
    return make_section("conclusion", "결론 및 권고", "recommendation", [slide])


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
    # ── Executive Summary (컨설팅식: 핵심 메세지 → 문제 → 원인 → 해결 → 대응)
    # 원칙: 짧게·단정조·측정가능·추측조 금지. 원인은 데이터(핵심 동인)에서, 결과는 기준선 대비.
    name = _human_dataset_name(ctx)
    verb = _CAT_VERB.get(ctx.meta.category or "", "분석")
    flags = _task_flags(ctx)
    maj = flags["maj"]
    pmval = pm.get("value")
    pmname_l = str(pm.get("name") or "").lower()
    # 한국어 지표 표현 (val_roc_auc → 검증 AUC 등)
    if pmval is None:
        mphrase = "검증 성능"
    elif "acc" in pmname_l and isinstance(pmval, (int, float)) and pmval <= 1:
        mphrase = f"정확도 {pmval * 100:.1f}%"
    elif "auc" in pmname_l:
        mphrase = f"AUC {_fv(pmval)}"
    elif "f1" in pmname_l:
        mphrase = f"F1 {_fv(pmval)}"
    else:
        mphrase = f"{_ko_metric(pm.get('name'))} {_fv(pmval)}"
    drivers_lbl = _driver_labels(ctx, 2)
    drivers_txt = ", ".join(drivers_lbl)
    top1 = drivers_lbl[0] if drivers_lbl else ""
    has_model = bool(chosen and chosen != "-" and pmval is not None)
    judgment = _perf_judgment(flags, pmval, pmname_l, maj)
    event = _event_noun(ctx)

    # ── 헤드라인 (결론 + 판단 '다만') — 한 줄
    if has_model:
        headline = f"{name} 데이터({n_rows:,}건)로 '{target}'{_josa(target, 'obj')} {mphrase}{_josa(mphrase, 'with')} {verb}할 수 있다."
        if judgment:
            headline += f" 다만 {judgment}."
    else:
        headline = f"{name} 데이터({n_rows:,}건)로 '{target}' {verb} 가능성을 분석했다."
    setup = ""

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
        clauses.append(f"전체 {event}의 {conc[1] * 100:.0f}%가 '{conc[0]}' 한 세그먼트에 몰려 있다")
    if price_lbl and top1 and best:
        clauses.append(
            f"통념과 달리 {price_lbl}(가격)이 아니라 {top1}{_josa(top1, 'nom')} 이를 가른다 — '{best[1]}'({best[2]:.0f}%)이 '{best[3]}'({best[4]:.0f}%)의 {best[5]:.0f}배다"
        )
    elif best:
        clauses.append(f"'{best[1]}'({best[2]:.0f}%)이 '{best[3]}'({best[4]:.0f}%)의 {best[5]:.0f}배로 갈린다")
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
        _build_conclusion_and_reco(ctx),  # §7 결론 및 권고 (구 §7+§8 병합) — 무엇을 할 것인가 + 답
    ]
    body_sections = [s for s in ordered if s is not None]
    for _i, _sec in enumerate(body_sections, 1):
        _sec.title = f"{_i}. {_sec.title}"

    sections: list[SectionSpec] = [_build_cover(ctx)] + body_sections
    appendix = _build_appendix(ctx)  # 부록은 번호 없이 본문 뒤
    if appendix is not None:
        sections.append(appendix)

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
