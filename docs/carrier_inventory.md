# Carrier 사전 점검 인벤토리 (Step 6-0)

> 산출 PPT carrier (`pptx_designer`) 작업 전 자산 현황 점검 결과.
> 디자인 LLM 통합 (Step 6-1~) 의 *기반 인벤토리*.

## 자산 현황

| 영역 | 위치 | 상태 |
|---|---|---|
| **REGISTRY 엔진** | `outputs/carriers/template_registry.py` (163줄) | ✅ 잘 설계됨 |
| **템플릿 등록** | `outputs/carriers/templates_init.py` (729줄) | ✅ 42개 등록 |
| **그리기 카탈로그** | `outputs/carriers/pptx_infographics.py` (3564줄) | ✅ 38+ 함수 |
| **designer 분기** | `outputs/carriers/pptx_designer.py` (1434줄) | ✅ 28 hardcoded paths |
| **팔레트** | `outputs/style/palette.py` | ✅ 4 카테고리 + semantic |
| **아이콘** | `assets/icons/lucide/` | ✅ 1544 SVG |
| **카테고리 아이콘 매핑** | `outputs/style/iconography.py` | ✅ 6 × 4 카테고리 + 11 공통 |
| **스톡 사진 API** | `tools/visual/stock_image.py` | ⚠️ 코드만, 캐시 빈 (API 키 필요) |
| **일러스트** | `assets/illustrations/undraw/` | ❌ 빈 폴더 |

## REGISTRY 엔진 핵심 메서드

```python
class TemplateRegistry:
    def register(name, draw, fit, tags, min_score) -> None
    def all() -> list[TemplateSpec]
    def get(name) -> TemplateSpec | None
    def best_for(slide, ctx) -> TemplateSpec | None       # 점수 매겨 1개
    def all_scored(slide, ctx) -> list[(name, score)]      # 점수 매겨 전체 (★ 후보 추출에 활용)
```

점수 함수 빌더:
- `has_id("exec_summary", ...)` — 90점
- `has_layout("kpi_cards_4", ...)` — 70점
- `has_role("claim", ...)` — 55점
- `has_body_min(n)` — 50점
- `has_category("tabular_ml", ...)` — 50점
- `has_metrics(min_n)` — 60점
- `matches_keywords("trend", ...)` — 40점
- `combine(*fns, mode="max")` — 조합

## 팔레트

```python
CATEGORY_PALETTE = {
    "tabular_ml":        {"primary": "#2563eb", "accent": "#93c5fd", "secondary": "#1e40af"},   # 파랑
    "tabular_dl":        {"primary": "#0891b2", "accent": "#67e8f9", "secondary": "#155e75"},   # 청록
    "timeseries":        {"primary": "#16a34a", "accent": "#86efac", "secondary": "#15803d"},   # 초록
    "anomaly_detection": {"primary": "#dc2626", "accent": "#fca5a5", "secondary": "#991b1b"},   # 빨강
}

SEMANTIC_COLORS = {
    "success": "#16A34A", "warning": "#D97706", "danger": "#DC2626", "info": "#2563EB",
    "ink_900": "#0F172A", ... "ink_100": "#F1F5F9", "white": "#FFFFFF",
}
```

## 아이콘

- **풀**: lucide-static 1544 SVG (`assets/icons/lucide/`)
- **카테고리 매핑** (각 6개): tabular_ml = [table, cpu, bar-chart-3, git-branch, target, shield-check]
- **공통 매핑** (11개 개념): data → database, code → code, report → file-text, kpi → trending-up, ...

## 스톡 사진

- **모듈**: `tools/visual/stock_image.py`
- **API 우선순위**: Unsplash (50/h) > Pexels (200/h) > Pixabay (사실상 무제한)
- **캐시**: `assets/cache/stock_images/<hash>.jpg` — 한 번 받으면 영구 재사용
- **슬라이드 ID → 키워드** 매핑 이미 구비 (cover → "business meeting professional" 등)
- **현재 상태**: 캐시 비어있음 → 환경변수 (UNSPLASH_ACCESS_KEY 등) 설정 시 첫 사용 자동 다운로드

## 일러스트

- **풀**: 비어있음 (`assets/illustrations/undraw/` 디렉터리만)
- **계획**: 초기 carrier 작업은 *아이콘 + 스톡 사진* 만으로 진행.
  시뮬 검증 후 *진짜 필요하다* 판단되면 별도 sub-step 으로 undraw.co MIT
  라이선스 SVG 50~100개 큐레이션 다운로드 스크립트 추가.

## Carrier 작업 재계획 (5 sub-step)

기존 7 sub-step → **인벤토리 결과로 단축**:

- **6-1**: `REGISTRY.candidates_for(slide, ctx, top_n=7)` 신규 메서드 (사실상 `all_scored()` 래퍼)
- **6-2**: LLM 디자인 선택 메서드 (`pptx_designer` 내부 async `_pick_design()`)
- **6-3**: `_draw_slide` 통합 — `REGISTRY.best_for()` 호출을 LLM 분기로 교체
- **6-4**: 부족 신호 로깅 + 폴백
- **6-5**: 시뮬 (Titanic / 신용카드 / 전력) + 회귀 테스트 + 시각 검증

당초 *카탈로그 메타데이터 부여 (Step 6-1)* 는 **스킵** — 42개가 이미 `fit` 함수로
등록되어 있어 *후보 추출이 이미 가능*. `all_scored()` 만 활용하면 됨.

## 핵심 발견

1. **`REGISTRY.all_scored()` 가 후보 추출 인프라** — LLM 한테 넘길 후보 N개 가져오기가 한 줄
2. **42개 템플릿이 *이미 점수 함수* 로 등록됨** — 메타 신규 부여 불필요
3. **사진 풀은 *동적*** (API 호출 + 캐시) — 환경변수 설정만 하면 즉시 사용
4. **일러스트만 비어있음** — 초기 작업 영향 X, 나중에 별도 채움
