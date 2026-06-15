"""agents.gates.analysis_proposer -- G2 analysis direction gate.

Proposal structure:
  Option 1, 2 : LLM recommendations
  Option 3    : fixed user-custom-input placeholder (is_custom=True)

Frontend sends choice as:
  Custom input  -> {adopted_rank: 0, custom_intent: "text"}
  Select 1 or 2 -> {adopted_rank: 1}  or  {adopted_rank: 2}
"""

from __future__ import annotations

import json
import re
from typing import Any


def _strip_topic_subtitle(title: str) -> str:
    """CS 2026-06-10 — 주제 제목에서 ' — XXX' / ' – XXX' 부제 패턴 제거.
    Ollama 가 TOPIC_SYSTEM_PROMPT 의 '부제 금지' 지시를 안 지킬 때 안전망."""
    if not isinstance(title, str):
        return title
    # em-dash (—), en-dash (–), 또는 큰 하이픈 사이 공백 패턴 제거
    cleaned = re.sub(r"\s+[—–]\s+.*$", "", title).strip()
    return cleaned or title


from ada.core.lang_guard import looks_non_korean
from ada.core.state import CATEGORIES, PipelineState
from agents.gates._base_gate import BaseGate

# HJ 2026-06-09 G1 단축 U — system_prompt 압축 (1500t → ~500t).
# 핵심 규칙·enum·rationale 형식 모두 유지. 반복 강조·영어 중복 제거.
# rationale 은 사용자 요구대로 6줄 형식 (스크린샷 기준).
SYSTEM_PROMPT = (
    "당신은 데이터 전략 컨설턴트. 사용자 의도+프로파일 보고 서로 다른 분석 방향 2개를 JSON 으로 제안.\n\n"
    "[규칙]\n"
    "- Option 1=가장 확신 높은 방향, Option 2=의미 있게 다른 두 번째 방향.\n"
    "- 두 옵션은 반드시 서로 다른 category.\n"
    "- EDA·시각화는 방향 아님 (단계임).\n"
    "- 한국어만, 한자(漢字·汉字)·중국어 금지.\n"
    "- 카드 1장당 rationale 6줄, 각 줄 12~20자. 제목·각 줄 모두 완결된 한국어 구로 작성하고, "
    "단어·음절을 생략하거나 중간에서 끊지 말 것(예: '생존률'→'생', '분석'→'분' 으로 줄이기 금지):\n"
    "  • 목표: <분석 목표>\n"
    "  • 방법: <핵심 알고리즘>\n"
    "  • 결과: <산출 인사이트>\n"
    "  • 장점: <강점·차별성>\n"
    "  • 단점: <한계·주의>\n"
    "  • 기대: <기대 효과·지표>\n\n"
    "[각 카드 필드]\n"
    "  id, title(한국어 12~28자, 완결된 구·중간에 끊지 말 것), rationale(위 6줄), score(0~1),\n"
    "  category: tabular_ml|tabular_dl|timeseries|anomaly_detection,\n"
    "  approach: supervised_classification|supervised_regression|unsupervised_clustering"
    "|anomaly_detection|time_series_forecasting|supervised_other,\n"
    "  target_column: 지도학습이면 컬럼명, 아니면 null.\n\n"
    "JSON 배열 2개만 반환 (markdown·부연 금지):\n"
    '[{"id":1,"title":"...","rationale":"• 목표: ...\\n• 방법: ...\\n• 결과: ...\\n• 강점: ...\\n• 적합: ...\\n• 기대: ...",'
    '"score":0.85,"category":"tabular_ml","approach":"supervised_classification","target_column":"price"},'
    '{"id":2,...,"category":"anomaly_detection","approach":"unsupervised_clustering","target_column":null}]'
)

# Retry 시 더 강한 한국어 지시
KOREAN_RETRY_HINT = (
    "이전 응답에 한자(中文)가 포함되어 거부됩니다. "
    "반드시 한국어로만 다시 작성하세요. "
    "한자(漢字·汉字)·중국어·영어 문장 금지."
)

# CS 2026-06-10 — G2 Sub-1 (주제 선정) 신규 LLM prompt.
# 도메인 지식 (domain/dataset_summary/target_insight/column_meanings) 입력 →
# PPT/PDF 표지에 그대로 쓸 발표 제목 5개 생성.
# 방법론·알고리즘 단독 제목 금지 (G3 영역). 도메인 스토리·관점 중심.
TOPIC_SYSTEM_PROMPT = (
    "당신은 학회·기업 발표 자료 기획자.\n"
    "1단계 데이터 분석 자료(도메인 정보)와 데이터 원본 샘플을 함께 보고 "
    "PPT/PDF 표지에 그대로 들어갈 발표 제목 5개를 JSON 으로 제안.\n\n"
    "[입력 필드]\n"
    "- domain          : 데이터 산업·분야\n"
    "- dataset_summary : 데이터셋 1~2문장 요약\n"
    "- target_insight  : 예측 타겟의 의미·맥락\n"
    "- column_meanings : 컬럼명·의미 사전 (영문 키 유지)\n"
    "- data_structure  : 데이터 구조 힌트.\n"
    "    is_timeseries=시계열 여부, date_column=시간축,\n"
    "    segment_columns=비교 가능한 범주(성별·연령·지역·등급 등),\n"
    "    measure_columns=수치 측정값, row_count=행 수\n"
    "- sample_rows     : 데이터 원본 상위 행(실제 값 예시). 제목에 구체적 값·범주·"
    "스케일을 녹이는 근거로 활용 (단, 개별 값을 그대로 노출하지 말고 패턴·맥락으로 추상화)\n\n"
    "[규칙]\n"
    "- 학회 컨퍼런스·기업 발표·연구 보고 표지에 그대로 박힐 발표 제목.\n"
    "- 길이: 제목 전체 25~50자.\n"
    "- 형식: 다음 4가지 패턴 중 적절히 골라 사용. 5개 제목은 서로 다른 패턴/각도여야 함.\n"
    "  (A) 주제 명사 + 콜론(:) 또는 대시(—) + 구체화 부제\n"
    "  (B) 호기심·선언·질문 + 콜론(:) 또는 대시(—) + 방법·관점 명시 부제\n"
    "  (C) 메타 표현(데이터가 말하다·기록한다·남긴·찾아낸) + 콜론 + 인사이트 부제\n"
    "  (D) 회사·학회 발표 톤 (보고·프로젝트·개발·분석) + 콜론 + 핵심 메시지 부제\n"
    "- 방법론(ML / 예측 모델 / 클러스터링 / 전처리 / 파이프라인 등) 은 부제에서 명시 가능.\n"
    "  단, 본제·부제 어디에도 데이터셋명만 단순 반복하는 무의미한 부제 금지.\n"
    "- 청중이 발표를 듣고 싶게 만드는 구체적 가치 제안이 부제에 담겨야 함.\n"
    "- 5개 제목은 아래 5가지 '분석 관점'을 각각 하나씩 담당 (관점 중복 금지):\n"
    "  ① 시간·추이   : 기간 흐름·증감 추세·변곡점 (data_structure.is_timeseries=true 면 필수)\n"
    "  ② 세그먼트 비교: segment_columns 의 범주 간 차이·격차 (예: 성별·연령대 비교)\n"
    "  ③ 그룹·공간   : 지역·집단·카테고리별 분포·집중\n"
    "  ④ 리스크·취약 : 위험군·이상·취약 세그먼트·경고 신호\n"
    "  ⑤ 종합·메타   : 데이터 전체가 말하는 큰 그림·시사점\n"
    "  ※ 해당 관점 재료가 데이터에 없으면(예: 시계열 아님·segment 없음) 그 슬롯은\n"
    "    가장 가까운 다른 관점으로 대체하되, 5개가 서로 다른 각도가 되도록 한다.\n"
    "- 제목에는 data_structure 의 실제 축(date_column·segment_columns)·domain 을 구체 반영.\n"
    "- 한국어만. 한자 금지.\n\n"
    "[좋은 예시 — 그대로 따라할 톤]\n"
    '  "타이타닉 생존율 분석: 사회적 불평등과 생존의 상관관계"\n'
    '  "타이타닉 생존 예측 모델: 데이터 기반 의사결정 파이프라인 구축"\n'
    '  "생존을 예측하다: 타이타닉 데이터로 구현한 ML 예측 모델 성과 보고"\n'
    '  "누가 살아남는가? — ML 예측 모델로 검증한 타이타닉 생존 인자 분석"\n'
    '  "타이타닉이 남긴 데이터: 생존 예측 모델이 밝혀낸 112년 전의 패턴"\n'
    '  "숫자가 말하는 생존의 조건: 타이타닉 ML 분석에서 얻은 비즈니스 인사이트"\n'
    '  "예측 너머의 이야기: 타이타닉 생존 모델이 드러낸 구조적 불평등"\n'
    '  "데이터는 기억한다: 타이타닉 생존 패턴에서 발견한 의사결정의 단서"\n'
    '  "모델이 찾아낸 생존 법칙: 타이타닉 데이터가 주는 현실적 시사점"\n\n'
    "[나쁜 예시 — 절대 금지]\n"
    '  "생존자의 성별 분석 — 타이타닉 생존 데이터"  (부제가 데이터셋명 단순 반복)\n'
    '  "티켓 클래스별 생존률 비교"  (단순 분석명, 메시지·가치 제안 없음)\n'
    '  "성별과 객실 번호의 상관관계 분석"  (분석 자체가 제목, 표지 톤 아님)\n'
    '  "분석 모델"  (방법론만 적힘)\n\n'
    "[각 카드 필드]\n"
    "  id (1~5), title (한국어 25~50자, 위 4가지 패턴 중 적절히 활용)\n\n"
    "JSON 배열만 (markdown·부연 금지):\n"
    '[{"id":1,"title":"..."},{"id":2,"title":"..."},{"id":3,"title":"..."},'
    '{"id":4,"title":"..."},{"id":5,"title":"..."}]'
)

# 주제 LLM 실패 + data_profile 도 비었을 때만 쓰는 최종 정적 fallback (도메인 무관)
_TOPIC_FALLBACK_DEFAULTS: list[dict[str, Any]] = [
    {"id": 1, "title": "데이터로 보는 핵심 트렌드"},
    {"id": 2, "title": "주요 지표 심층 분석 보고서"},
    {"id": 3, "title": "비교 관점에서 본 데이터 인사이트"},
    {"id": 4, "title": "리스크 요인 분석"},
    {"id": 5, "title": "데이터 종합 회고"},
]


def _structure_hints_from_profile(dp: dict[str, Any]) -> dict[str, Any]:
    """HJ 2026-06-14 — data_profile 에서 주제 관점 다양화 재료를 가공.

    시계열 여부·세그먼트(저카디널리티 범주) 후보·수치 측정값 후보를 추출한다.
    propose_topics(LLM 입력)와 _build_topic_fallback(폴백) 이 공유한다.
    """
    cols = [str(c) for c in (dp.get("columns") or [])]
    dtypes = dp.get("dtypes") or {}
    card = dp.get("cardinality") or {}
    date_col = dp.get("date_col")
    detected_cat = (dp.get("category_detection") or {}).get("detected_category")

    seg_candidates: list[str] = []
    measure_candidates: list[str] = []
    for c in cols:
        if c == date_col:
            continue
        nun = card.get(c)
        dt = str(dtypes.get(c, ""))
        # 세그먼트 후보: 저카디널리티(2~30) 범주/정수 컬럼 (float 측정값 제외)
        if isinstance(nun, int) and 2 <= nun <= 30 and not dt.startswith("float"):
            seg_candidates.append(c)
        elif dt.startswith(("int", "float")):
            measure_candidates.append(c)

    return {
        "is_timeseries": bool(date_col) or detected_cat == "timeseries",
        "date_column": date_col,
        "segment_columns": seg_candidates[:8],
        "measure_columns": measure_candidates[:8],
        "row_count": dp.get("rows"),
    }


def _build_topic_fallback(data_profile: dict[str, Any] | None) -> list[dict[str, Any]]:
    """HJ 2026-06-14 — LLM 실패 시 data_profile 구조 메타 기반 동적 폴백.

    인코딩·도메인 분석이 살아 있으면 도메인명·시계열·세그먼트를 반영해
    generic 5개(_TOPIC_FALLBACK_DEFAULTS) 대신 데이터에 맞는 제목을 생성한다.
    도메인 정보가 전혀 없으면 정적 폴백으로 떨어진다.
    """
    dp = data_profile or {}
    domain_info = dp.get("domain_analysis") or {}
    domain = str(domain_info.get("domain") or "").strip()
    if not domain:
        return [dict(t) for t in _TOPIC_FALLBACK_DEFAULTS]

    hints = _structure_hints_from_profile(dp)
    is_ts = hints.get("is_timeseries")
    segs = hints.get("segment_columns") or []
    seg1 = segs[0] if segs else None
    seg2 = segs[1] if len(segs) > 1 else None

    titles: list[str] = []
    # ① 시간·추이 / 종합
    titles.append(f"{domain} 추이 분석: 기간별 변화와 변곡점" if is_ts else f"{domain} 핵심 지표 종합 분석 보고")
    # ② 세그먼트 비교
    if seg1:
        titles.append(f"{seg1}(으)로 본 {domain}: 세그먼트별 패턴 비교")
    # ③ 그룹·공간
    if seg2:
        titles.append(f"{seg2}별 분포로 읽는 {domain}의 집중과 격차")
    # ④ 리스크·취약
    titles.append(f"{domain} 리스크 진단: 취약 구간과 경고 신호")
    # ⑤ 종합·메타
    titles.append(f"데이터가 말하는 {domain}: 핵심 인사이트 종합")

    # 중복 제거 + generic 으로 5개 보장
    seen: set[str] = set()
    uniq: list[str] = []
    for t in titles:
        if t not in seen:
            seen.add(t)
            uniq.append(t)
    for g in _TOPIC_FALLBACK_DEFAULTS:
        if len(uniq) >= 5:
            break
        if g["title"] not in seen:
            uniq.append(g["title"])
            seen.add(g["title"])
    return [{"id": i, "title": t} for i, t in enumerate(uniq[:5], start=1)]


def _merge_llm_with_fallback(
    llm_topics: list[dict[str, Any]], data_profile: dict[str, Any] | None
) -> list[dict[str, Any]]:
    """HJ 2026-06-14 — 하이브리드: LLM 제목 N개(0~5) + 폴백 보충 → 항상 5개.

    LLM 이 format 조기종료 등으로 일부(예: 2개)만 만들어도 그 결과를 살리고,
    부족분(5-N)을 _build_topic_fallback 으로 채운다. 제목 중복은 제거하고 id 를 재부여한다.
    LLM 이 0개여도 폴백 5개로 안전(기존 동작 보존).
    """
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for t in (llm_topics or [])[:5]:
        title = str((t or {}).get("title") or "").strip()
        if title and title not in seen:
            out.append({"title": title})
            seen.add(title)
    if len(out) < 5:
        for f in _build_topic_fallback(data_profile):
            if len(out) >= 5:
                break
            ftitle = str(f.get("title") or "").strip()
            if ftitle and ftitle not in seen:
                out.append({"title": ftitle})
                seen.add(ftitle)
    for i, t in enumerate(out, start=1):
        t["id"] = i
    return out[:5]


_UNSUPERVISED_CATEGORIES: frozenset[str] = frozenset({"anomaly_detection"})

# (category, keywords) — 앞쪽 항목일수록 우선순위 높음
_CATEGORY_KEYWORDS: list[tuple[str, list[str]]] = [
    (
        "anomaly_detection",
        [
            "클러스터",
            "군집",
            "cluster",
            "비지도",
            "unsupervised",
            "이상탐지",
            "anomaly",
            "outlier",
            "이상치",
        ],
    ),
    ("timeseries", ["시계열", "예측", "forecast", "time series", "temporal"]),
    ("tabular_dl", ["딥러닝", "deep learning", "transformer", "neural", "embedding"]),
]


def _infer_category_from_text(text: str, fallback: str) -> str:
    """title/rationale 키워드로 category 를 추론. 매칭 없으면 fallback 반환."""
    t = text.lower()
    for cat, kws in _CATEGORY_KEYWORDS:
        if any(k in t for k in kws):
            return cat
    return fallback


# 카테고리별 최소 행 수 — schema_validator.CATEGORY_RULES 와 동기화.
# 직접 import 하면 순환 의존 가능성이 있으므로 여기서 독립 선언.
_CATEGORY_MIN_ROWS: dict[str, int] = {
    "tabular_ml": 100,
    "tabular_dl": 1000,
    "timeseries": 50,
    "anomaly_detection": 500,
}


def _category_feasible(category: str, data_profile: dict | None) -> bool:
    """데이터셋이 category 의 최소 요건(행 수·필수 컬럼)을 충족하는지 확인.

    data_profile 이 없거나 rows 정보가 없으면 True 반환(보수적 허용).
    """
    if not data_profile:
        return True
    rows = int(data_profile.get("rows", 0) or 0)
    if rows == 0:
        return True
    # 최소 행 수 검사
    if rows < _CATEGORY_MIN_ROWS.get(category, 0):
        return False
    # timeseries: datetime 컬럼이 없으면 불가
    if category == "timeseries":
        dtypes = data_profile.get("dtypes") or {}
        has_datetime = any("datetime" in str(v).lower() for v in dtypes.values())
        if not has_datetime:
            return False
    return True


_CUSTOM_OPTION: dict[str, Any] = {
    "id": 3,
    "title": "직접 입력",
    "rationale": "원하는 분석 방향을 직접 입력하세요.",
    "score": None,
    "is_custom": True,
}

# HJ 2026-06-14 — rationale 6줄(목표/방법/결과/장점/단점/기대) 보장 유틸.
#   Ollama(qwen2.5:7b)가 형식을 덜 지켜 줄이 모자라거나 한 줄로 합쳐 보내도,
#   프론트 카드 본문이 1줄로 깨지지 않도록 항상 6줄 글머리로 정규화한다.
_RATIONALE_SKELETON: tuple[str, ...] = (
    "목표: 분석의 핵심 목표",
    "방법: 적용할 주요 기법",
    "결과: 도출할 인사이트",
    "장점: 이 방향의 강점",
    "단점: 유의할 한계",
    "기대: 기대 효과·지표",
)
# 줄머리 기호(•·-*▪◦ 등)·번호(1. 1)) 접두 제거용.
_BULLET_RE = re.compile(r"^[\s•·\-\*▪◦‣>]+")
_NUMBERED_RE = re.compile(r"^\d+[.)]\s*")


def _r6(*lines: str) -> str:
    """6줄 글머리 rationale 문자열 생성 (각 줄 '• ' 접두)."""
    return "\n".join(f"• {ln}" for ln in lines)


def _normalize_rationale(raw: Any) -> str:
    r"""rationale 을 '• 라벨: 내용' 6줄로 정규화 — 항상 6줄을 보장한다.

    - str  : 줄바꿈 단위로 분해. 리터럴 '\n' 도 실제 개행으로 처리.
    - list : 각 항목을 한 줄로.
    6줄 초과면 앞 6줄, 미만이면 _RATIONALE_SKELETON 으로 부족분을 보충.
    """
    if isinstance(raw, list):
        candidates = [str(x) for x in raw]
    else:
        candidates = str(raw or "").replace("\\n", "\n").splitlines()
    lines: list[str] = []
    for ln in candidates:
        s = _BULLET_RE.sub("", ln).strip()
        s = _NUMBERED_RE.sub("", s).strip()
        if s:
            lines.append(s)
    if len(lines) >= 6:
        lines = lines[:6]
    else:
        lines.extend(_RATIONALE_SKELETON[len(lines) :])
    return "\n".join(f"• {ln}" for ln in lines)


_FALLBACK_DEFAULTS: dict[str, list[dict[str, Any]]] = {
    "tabular_ml": [
        {
            "id": 1,
            "title": "분류/회귀 예측",
            "rationale": _r6(
                "목표: 타깃 값 예측 모델 구축",
                "방법: 지도학습 분류·회귀 적용",
                "결과: 예측 성능 지표 산출",
                "장점: 해석·운영이 용이",
                "단점: 라벨 품질에 의존",
                "기대: 의사결정 자동화 지원",
            ),
            "score": 0.8,
        },
        {
            "id": 2,
            "title": "피처 중요도 분석",
            "rationale": _r6(
                "목표: 핵심 영향 변수 규명",
                "방법: 중요도·SHAP 분석 수행",
                "결과: 변수 영향도 순위 도출",
                "장점: 인사이트 설명력 우수",
                "단점: 상관·인과 혼동 주의",
                "기대: 데이터 전략 수립 지원",
            ),
            "score": 0.6,
        },
    ],
    "tabular_dl": [
        {
            "id": 1,
            "title": "TabTransformer 학습",
            "rationale": _r6(
                "목표: 복잡 패턴 표현 학습",
                "방법: TabTransformer 딥러닝",
                "결과: 고차원 예측 모델 확보",
                "장점: 비선형 관계 포착 우수",
                "단점: 학습 비용·시간 증가",
                "기대: 정밀 예측 성능 향상",
            ),
            "score": 0.8,
        },
        {
            "id": 2,
            "title": "FTTransformer 비교",
            "rationale": _r6(
                "목표: 임베딩 방식 성능 비교",
                "방법: FTTransformer 벤치마크",
                "결과: 모델별 성능 비교표 도출",
                "장점: 수치형 처리에 강점",
                "단점: 소규모 데이터엔 과적합",
                "기대: 최적 구조 선택 근거 확보",
            ),
            "score": 0.7,
        },
    ],
    "timeseries": [
        {
            "id": 1,
            "title": "단기 예측",
            "rationale": _r6(
                "목표: 향후 1~30일 값 예측",
                "방법: 추세·계절성 분해 학습",
                "결과: 미래 수요 예측치 산출",
                "장점: 단기 의사결정에 직결",
                "단점: 장기 예측은 정확도 저하",
                "기대: 재고·운영 비용 절감",
            ),
            "score": 0.8,
        },
        {
            "id": 2,
            "title": "이상 시점 탐지",
            "rationale": _r6(
                "목표: 비정상 변동 시점 식별",
                "방법: 잔차·변동성 기반 탐지",
                "결과: 이상 구간 타임라인 제공",
                "장점: 조기 경보로 대응 가능",
                "단점: 임계값 설정에 민감",
                "기대: 장애·리스크 사전 차단",
            ),
            "score": 0.6,
        },
    ],
    "anomaly_detection": [
        {
            "id": 1,
            "title": "이상치 점수화",
            "rationale": _r6(
                "목표: 샘플별 이상 점수 산출",
                "방법: anomaly score 모델 학습",
                "결과: 위험도 순위 리스트 제공",
                "장점: 라벨 없이도 적용 가능",
                "단점: 임계값 튜닝이 필요",
                "기대: 이상 징후 신속 포착",
            ),
            "score": 0.85,
        },
        {
            "id": 2,
            "title": "정상 분포 학습",
            "rationale": _r6(
                "목표: 정상 패턴 분포 학습",
                "방법: 밀도·재구성 기반 탐지",
                "결과: 이탈 여부 판정 결과",
                "장점: 미지 이상에도 견고",
                "단점: 정상 정의에 민감",
                "기대: 오탐·미탐 균형 확보",
            ),
            "score": 0.7,
        },
    ],
}

# LLM·카테고리 폴백 모두 미해당 시 최종 기본(도메인 무관) — 6줄 보장.
_GENERIC_FALLBACK: list[dict[str, Any]] = [
    {"id": 1, "title": "기본 분석", "rationale": _r6(*_RATIONALE_SKELETON), "score": 0.5},
]


class AnalysisProposerAgent(BaseGate):
    """G2 -- LLM 2 proposals + fixed custom option 3."""

    gate_code = "G2"
    model_name = "claude-opus-4-6"
    n_proposals = 2  # LLM generates 2; option 3 is always _CUSTOM_OPTION

    # CS 2026-06-10 — G2 흐름 재설계.
    # BaseGate.__call__ 오버라이드: 첫 진입 시 propose_topics 호출 (메인 흐름, 마일스톤 sync).
    # topic_proposals 를 gate_responses[G2] 에 저장 → _save_gate_data 가 Redis 로 forward.
    # 분석 방향(proposals) 은 endpoint /pipeline/gate/G2/directions/{job_id} 에서 채움.
    async def __call__(self, state: PipelineState) -> PipelineState:
        async with self.log_agent_run(state):
            existing = (state.gate_responses or {}).get(self.gate_code, {})
            # 사용자 응답 있으면 _apply_choice (재진입 보호)
            if existing.get("user_choice") is not None:
                updated = self._apply_choice(
                    state,
                    existing.get("user_choice"),
                    existing.get("proposals") or [],
                )
                return updated.with_update(current_gate=None)

            # 첫 진입: 주제 5개 생성 (도메인 지식 + 각도 다양성)
            try:
                topics = await self.propose_topics(state)
            except Exception as e:
                self.logger.warning("g2_topics_main_flow_failed", error=str(e))
                topics = _build_topic_fallback(state.data_profile)

            gate_responses = dict(state.gate_responses or {})
            gate_responses[self.gate_code] = {
                **(gate_responses.get(self.gate_code) or {}),
                "proposals": [],  # 분석 방향은 endpoint 후에 채워짐
                "topic_proposals": topics,
                "awaiting_decision": True,
                "auto_resolved": False,
            }
            return state.with_update(
                gate_responses=gate_responses,
                current_gate=self.gate_code,
            )

    async def _propose(self, state: PipelineState) -> list[dict[str, Any]]:
        # CS 2026-06-10 — G2 Sub-1 (주제 선정) 도입에 따라 흐름 변경:
        # 분석 방향 LLM 은 사용자가 주제 선택 후 신규 endpoint
        # POST /pipeline/gate/G2/directions/{job_id} 에서 호출 (propose_directions_with_topic).
        # 첫 진입 시점 (selected_topic 없음) 에는 빈 proposals 반환 → BaseGate interrupt 후
        # frontend 팝업이 표시되고 endpoint 가 proposals 를 채움.
        has_topic = bool((state.gate_responses or {}).get("G2", {}).get("topic"))
        if not has_topic:
            return []
        # 이하 기존 LLM 호출 로직 — topic 이 이미 set 된 상태에서 _propose 가 다시 불릴 때만 사용 (방어).
        # HJ 2026-06-09 G1 단축 V — user_payload 압축 (data_profile 전체 → 핵심 필드만).
        # gate_direction 결정에 필요한 정보: 카테고리, target, 컬럼명, dtype, 분포, 도메인 요약.
        # 입력 토큰 ~3000t → ~500t. 입력 처리 시간 -15~20s.
        # sample_rows·numeric_stats 등 무거운 필드는 제외 (gate 결정에 영향 없음).
        dp = state.data_profile or {}
        domain = dp.get("domain_analysis") or {}
        missing = dp.get("missing") or {}
        # missing 5% 초과 컬럼만 (작은 잡음 제거)
        missing_hi = {k: round(float(v), 3) for k, v in missing.items() if isinstance(v, (int, float)) and v > 0.05}

        payload: dict[str, Any] = {
            "user_intent": (state.user_intent or state.user_question or "")[:500],
            "category": state.category,
            "target_column": state.target_column,
            "rows": dp.get("rows"),
            "cols": dp.get("cols"),
            "columns": (dp.get("columns") or [])[:30],
            "dtypes": {k: v for k, v in list((dp.get("dtypes") or {}).items())[:30]},
            "target_dtype": dp.get("target_dtype"),
            "class_distribution": dp.get("class_distribution"),
            "date_col": dp.get("date_col"),
            "missing_hi_cols": missing_hi,
            "domain": domain.get("domain"),
            "dataset_summary": (domain.get("dataset_summary") or "")[:300],
        }
        # 안전 cap — 30MB·컬럼 100 worst case 도 4000자 이내로 들어옴.
        # default=str — class_distribution·target_dtype 등에 numpy 타입 섞여도 TypeError 안 나도록.
        user_payload = json.dumps(payload, ensure_ascii=False, default=str)[:4000]
        try:
            raw = await self._call_llm(
                system_prompt=SYSTEM_PROMPT,
                user_prompt=user_payload,
                # HJ 2026-06-13 — 글자 잘림 수정: 완결 구 강제로 줄·제목이 길어져 800 cap 에서
                #   마지막 줄(기대)·제목이 절단되던 문제 → 1100 으로 상향(프리페치라 대기시간 영향 0).
                max_tokens=1100,
                temperature=0.3,
                json_mode=True,
            )
            arr = self._safe_parse_json_array(raw)

            # 한자 감지 → 강한 한국어 지시로 1회 retry
            if arr and self._has_non_korean(arr):
                self.logger.warning("g2_cjk_detected_retry")
                retry_user = KOREAN_RETRY_HINT + "\n\n다시 작성할 데이터:\n" + user_payload
                try:
                    raw2 = await self._call_llm(
                        system_prompt=SYSTEM_PROMPT,
                        user_prompt=retry_user,
                        max_tokens=900,
                        temperature=0.2,
                        json_mode=True,
                    )
                    arr2 = self._safe_parse_json_array(raw2)
                    if arr2 and not self._has_non_korean(arr2):
                        arr = arr2
                    elif arr2:
                        # 둘 다 한자 → 폴백 사용 (아래로 fall-through)
                        self.logger.warning("g2_cjk_persist_after_retry")
                        arr = []
                except Exception as e:
                    self.logger.warning("g2_retry_failed", error=str(e))
                    arr = []

            if arr:
                finalized = self._finalize_llm_options(arr)
                if finalized:
                    return finalized + [_CUSTOM_OPTION]
        except Exception as e:
            self.logger.warning("g2_llm_failed", error=str(e))

        return self._fallback_options(state.category)

    @staticmethod
    def _has_non_korean(options: list[dict[str, Any]]) -> bool:
        """옵션의 title/rationale 중 한자가 포함된 항목이 있으면 True."""
        for opt in options:
            if not isinstance(opt, dict):
                continue
            for key in ("title", "rationale"):
                v = opt.get(key)
                if isinstance(v, str) and looks_non_korean(v):
                    return True
        return False

    def _finalize_llm_options(self, arr: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """HJ 2026-06-14 — LLM 결과 옵션 정리: id 재부여 + rationale 6줄 정규화.

        Ollama 가 6줄을 다 안 줘도 _normalize_rationale 로 6줄을 보장한다.
        dict 가 아닌 잡항목은 버린다(빈 리스트면 호출처가 폴백으로 전환).
        """
        out: list[dict[str, Any]] = []
        for opt in arr[: self.n_proposals]:
            if not isinstance(opt, dict):
                continue
            opt["id"] = len(out) + 1
            opt["rationale"] = _normalize_rationale(opt.get("rationale"))
            out.append(opt)
        return out

    def _fallback_options(self, category: str | None) -> list[dict[str, Any]]:
        """HJ 2026-06-14 — 카테고리 폴백(6줄) + custom. rationale 6줄 정규화 보장."""
        base = _FALLBACK_DEFAULTS.get(category or "", _GENERIC_FALLBACK)
        opts = [dict(o) for o in base]
        for o in opts:
            o["rationale"] = _normalize_rationale(o.get("rationale"))
        return opts + [_CUSTOM_OPTION]

    # ------------------------------------------------------------------
    # CS 2026-06-10 — G2 Sub-1 (주제 선정) LLM 호출.
    # schema_validator 백그라운드 task 에서 호출됨.
    # 도메인 지식만 입력 → PPT 표지용 발표 제목 5개 생성.
    # ------------------------------------------------------------------
    async def propose_topics(self, state: PipelineState) -> list[dict[str, Any]]:
        """G2 Sub-1 — 1단계 도메인 분석 자료 + 데이터 원본 샘플 기반 PPT 표지 제목 5개 생성."""
        dp = state.data_profile or {}
        domain = dp.get("domain_analysis") or {}
        # HJ 2026-06-14 — 구조 힌트 주입 (관점 다양화 재료: 시계열·세그먼트·측정값).
        hints = _structure_hints_from_profile(dp)
        if getattr(state, "category", None) == "timeseries":
            hints["is_timeseries"] = True
        # HJ 2026-06-14 — 데이터 원본 샘플 주입(사용자 요구): 1단계 도메인 분석 자료뿐 아니라
        #   실제 데이터 값(상위 행)을 함께 보고 제목을 짓도록 한다.
        #   넓은 데이터 대비 3행·행당 25컬럼으로 제한해 프롬프트 비용·한자 리스크를 관리한다.
        sample_rows = [
            {k: r[k] for k in list(r)[:25]} for r in (dp.get("sample_rows") or [])[:3] if isinstance(r, dict)
        ]
        payload = {
            "domain": domain.get("domain"),
            "dataset_summary": (domain.get("dataset_summary") or "")[:400],
            "target_insight": (domain.get("target_insight") or "")[:400],
            "column_meanings": dict(list((domain.get("column_meanings") or {}).items())[:20]),
            "data_structure": hints,
            "sample_rows": sample_rows,
        }
        # sample_rows 가 잘려나가지 않도록 상한을 3000→4500 으로 확대.
        user_payload = json.dumps(payload, ensure_ascii=False)[:4500]
        # HJ 2026-06-14 — 하이브리드: LLM 이 만든 N개(0~5)를 살리고 부족분만 폴백 보충(전부 버리지 않음).
        llm_topics: list[dict[str, Any]] = []
        try:
            raw = await self._call_llm(
                system_prompt=TOPIC_SYSTEM_PROMPT,
                user_prompt=user_payload,
                # HJ 2026-06-14 — 관점축 5슬롯 반영으로 출력이 약간 길어짐 → 500→600. 다양성 위해 0.6.
                max_tokens=600,
                temperature=0.6,
                json_mode=True,
                # HJ 2026-06-14 — format=json 미강제: format=json 이 'valid JSON 이면 조기 종료'를
                #   유발해 qwen 이 5개 중 2개만 만들고 배열을 닫던 문제 해소(5개 지시를 따르게 함).
                #   펜스제거·한국어가드는 json_mode=True 라 유지. 부족분은 _merge_llm_with_fallback 보충.
                force_json=False,
            )
            arr = self._safe_parse_json_array(raw)
            if arr and not self._has_non_korean(arr):
                llm_topics = [t for t in arr[:5] if isinstance(t, dict) and t.get("title") and str(t["title"]).strip()]
        except Exception as e:
            self.logger.warning("g2_topics_llm_failed", error=str(e))
        # LLM N개 + 폴백 보충(중복 제거) → 항상 5개. LLM 0개여도 폴백 5개로 안전.
        return _merge_llm_with_fallback(llm_topics, dp)

    # ------------------------------------------------------------------
    # CS 2026-06-10 — G2 Sub-2 (분석 방향) LLM 호출, selected_topic 입력.
    # api/routes/pipeline.py 의 신규 endpoint 에서 호출됨.
    # _propose 와 prompt 동일 (SYSTEM_PROMPT). user_payload prefix 만 다름.
    # ------------------------------------------------------------------
    async def propose_directions_with_topic(self, state: PipelineState, topic: str) -> list[dict[str, Any]]:
        """G2 분석 방향 LLM 호출 — selected_topic + 도메인 지식 입력."""
        dp = state.data_profile or {}
        domain = dp.get("domain_analysis") or {}
        missing = dp.get("missing") or {}
        missing_hi = {k: round(float(v), 3) for k, v in missing.items() if isinstance(v, (int, float)) and v > 0.05}
        # success_pattern KB — 동일 카테고리 과거 성공 사례를 방향 제안 컨텍스트로 인용(best-effort).
        _past = []
        try:
            from ada.harness.rag import KBRAG

            if self.session is not None:
                _sp = await KBRAG(self.session).fetch_success_patterns(state.category, top_k=3)
                _past = [
                    {
                        "intent": (pp.get("user_intent") or "")[:120],
                        "target": pp.get("target"),
                        "outputs": pp.get("requested_outputs") or [],
                    }
                    for pp in _sp
                ]
        except Exception:
            _past = []
        payload: dict[str, Any] = {
            "past_success_patterns": _past,
            "selected_topic": topic,
            "user_intent": (state.user_intent or state.user_question or "")[:500],
            "category": state.category,
            "target_column": state.target_column,
            "rows": dp.get("rows"),
            "cols": dp.get("cols"),
            "columns": (dp.get("columns") or [])[:30],
            "dtypes": {k: v for k, v in list((dp.get("dtypes") or {}).items())[:30]},
            "target_dtype": dp.get("target_dtype"),
            "class_distribution": dp.get("class_distribution"),
            "date_col": dp.get("date_col"),
            "missing_hi_cols": missing_hi,
            "domain": domain.get("domain"),
            "dataset_summary": (domain.get("dataset_summary") or "")[:300],
        }
        user_payload = (
            f"[발표 주제: {topic}]\n"
            f"위 주제의 도메인 관점에 맞춰 서로 다른 분석 방향 2개를 제안.\n\n"
            + json.dumps(payload, ensure_ascii=False)[:4000]
        )
        try:
            raw = await self._call_llm(
                system_prompt=SYSTEM_PROMPT,
                user_prompt=user_payload,
                # HJ 2026-06-13 — 글자 잘림 수정: 완결 구 강제로 800 cap 절단 방지 (프리페치라 영향 0).
                max_tokens=1100,
                temperature=0.3,
                json_mode=True,
            )
            arr = self._safe_parse_json_array(raw)
            if arr and self._has_non_korean(arr):
                self.logger.warning("g2_dir_cjk_detected_retry")
                try:
                    retry_user = KOREAN_RETRY_HINT + "\n\n다시 작성할 데이터:\n" + user_payload
                    raw2 = await self._call_llm(
                        system_prompt=SYSTEM_PROMPT,
                        user_prompt=retry_user,
                        max_tokens=900,
                        temperature=0.2,
                        json_mode=True,
                    )
                    arr2 = self._safe_parse_json_array(raw2)
                    if arr2 and not self._has_non_korean(arr2):
                        arr = arr2
                    else:
                        arr = []
                except Exception:
                    arr = []
            if arr:
                finalized = self._finalize_llm_options(arr)
                if finalized:
                    return finalized + [_CUSTOM_OPTION]
        except Exception as e:
            self.logger.warning("g2_directions_with_topic_failed", error=str(e))
        return self._fallback_options(state.category)

    def _apply_choice(
        self,
        state: PipelineState,
        user_choice: Any,
        proposals: list[dict[str, Any]],
    ) -> PipelineState:
        """Apply G2 user selection to state.

        Frontend sends:
          Custom input  -> {adopted_rank: 0, custom_intent: "text"}
          Select 1 or 2 -> {adopted_rank: 1}  or  {adopted_rank: 2}
        CS 2026-06-10 — Sub-1 주제 선정 결과(topic) 도 같이 들어옴.
        """
        uc = user_choice if isinstance(user_choice, dict) else {}
        updates: dict[str, Any] = {}

        # optional category / target override
        cat = uc.get("category")
        if isinstance(cat, str) and cat in CATEGORIES and cat != state.category:
            updates["category"] = cat

        tgt = uc.get("target_column") or uc.get("target")
        if isinstance(tgt, str) and tgt:
            updates["target_column"] = tgt

        # custom_intent 우선 확인 (adopted_rank=0 + custom_intent 조합)
        custom = uc.get("custom_intent")
        chosen = None
        if isinstance(custom, str) and custom.strip():
            updates["user_intent"] = custom.strip()
            # Method B: 키워드 휴리스틱으로 category 추론 (데이터셋 요건 충족 시만)
            if "category" not in updates:
                inferred = _infer_category_from_text(custom.strip(), state.category)
                if inferred != state.category and _category_feasible(inferred, state.data_profile):
                    updates["category"] = inferred
            if updates.get("category") in _UNSUPERVISED_CATEGORIES and "target_column" not in updates:
                updates["target_column"] = None
            self.logger.info("g2_custom_intent_applied", intent=custom.strip()[:120])
        else:
            # adopted_rank 로 선택한 LLM 제안 반영
            rank = uc.get("adopted_rank")
            chosen = next(
                (p for p in (proposals or []) if isinstance(p, dict) and p.get("id") == rank),
                None,
            )
            if chosen and isinstance(chosen.get("title"), str) and chosen["title"].strip():
                direction = chosen["title"].strip()
                base = (state.user_intent or "").strip()
                # HJ 2026-06-11 (jh 대행) — 멱등 부착 (resume 누적 오염 수정)
                from agents.gates._intent import append_intent_tag

                updates["user_intent"] = append_intent_tag(base, "분석 방향", direction)

                # Method A: LLM 이 proposal 에 category 를 채워줬으면 그대로 반영
                if "category" not in updates:
                    new_cat = chosen.get("category")
                    if isinstance(new_cat, str) and new_cat in CATEGORIES and new_cat != state.category:
                        if _category_feasible(new_cat, state.data_profile):
                            updates["category"] = new_cat
                            self.logger.info("g2_category_changed", old=state.category, new=new_cat)
                        else:
                            self.logger.info(
                                "g2_category_change_blocked",
                                reason="min_rows_not_met",
                                blocked_cat=new_cat,
                                kept_cat=state.category,
                            )

                # Method B: LLM 이 category 를 안 채웠을 때 키워드 fallback
                if "category" not in updates:
                    inferred = _infer_category_from_text(direction, state.category)
                    if inferred != state.category and _category_feasible(inferred, state.data_profile):
                        updates["category"] = inferred
                        self.logger.info("g2_category_inferred", direction=direction, category=inferred)

                # 비지도 계열이면 target_column 무효화, 지도학습이면 LLM 제안 target 반영
                if "target_column" not in updates:
                    if updates.get("category", state.category) in _UNSUPERVISED_CATEGORIES:
                        updates["target_column"] = None
                    else:
                        new_tgt = chosen.get("target_column")
                        if isinstance(new_tgt, str) and new_tgt.strip():
                            updates["target_column"] = new_tgt.strip()

                self.logger.info(
                    "g2_proposal_adopted",
                    rank=rank,
                    title=direction,
                    category=updates.get("category"),
                    target_column=updates.get("target_column"),
                )

        # CS 2026-06-10 — Sub-1 주제 보존. user_intent prefix 로 반영해
        # 다음 노드(eda_agent 등)가 topic 도메인 인지하도록.
        topic = uc.get("topic") or (state.gate_responses or {}).get("G2", {}).get("topic")
        if isinstance(topic, str) and topic.strip():
            base = updates.get("user_intent") or state.user_intent or ""
            if topic.strip() not in (base or ""):
                from agents.gates._intent import append_intent_tag

                updates["user_intent"] = append_intent_tag(base, "주제", topic)
            self.logger.info("g2_topic_adopted", topic=topic.strip()[:80])

        self.logger.info(
            "g2_apply_done",
            old_category=state.category,
            new_category=updates.get("category", state.category),
            chosen_has_category=bool(chosen.get("category")) if chosen else False,
        )
        return state.with_update(**updates) if updates else state
