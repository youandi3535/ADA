# ADA PDF — 숨은 자산 발굴 로드맵 (체크리스트)

> 전수조사 결과: PDF가 ctx 데이터의 **약 60%만** 사용 중. 나머지 40%는 **이미 파이프라인이 계산해 둔 자산** — 데이터 배선 신규 0, 보고서에 "서술·exhibit"만 추가하면 됨.

---

## 🎯 두 가지 대원칙 (이 로드맵을 관통)

### 원칙 1 — 데이터 불문 자동 연결 (Use-All-Assets, 조건부 노출)
- 어떤 데이터가 들어와도(10000명, 제각각, ML·DL정형·시계열·이상치) **ctx에 그 자산이 있으면 자동으로 보고서에 붙고, 없으면 조용히 스킵**(에러 0).
- 구현 패턴: `if ctx.<asset>: render(...)` + **카테고리 분기**(ML=혼동행렬, 시계열=계절성, 이상치=임계값…).
- 즉 보고서 = **"가능한 모든 자산을 presence-check로 다 켜 둔 superset 템플릿."** 타이타닉 하드코딩 0.

### 원칙 2 — 오디언스 적응형 70:30 + 본문/부록 레지스터 분리
- **비율은 70:30을 닻으로 청중 따라 자동:** C레벨 80:20, 부서장 70:30(기준), 분석가 55:45, 외부 75:25. `audience_inference`(이미 추론됨)가 정함.
- **본문(≈70% 비즈니스 의사결정):** 같은 로직이라도 *말로 풀어서* + so-what + 핵심 숫자 1개 + 결정. 쉬운 말.
- **부록(100% 데이터 분석):** *제대로 기술적으로* (통계·방법론·진단·전체 표·가정).
- **레지스터 분리는 청중 불문 항상 유지.** 같은 자산을 본문형(결정) + 부록형(검증) 쌍으로, 본문에 "상세: 부록 §9.x" 링크.

---

## ✅ 체크리스트 (우선순위 = 중요도 높음·노력 낮음 먼저)

### 🟢 즉시 (quick-win)
- [x] **도메인 벤치마크** → §5(성능, §8서 정밀화) · 중요도 9/노력 3 · `domain.domain_benchmarks` · "업계 평균 대비 본 모델, 상위/동등/하회" 조건부+적응형 깊이(audience_register). ✅ 2026-06-13 report_skeleton.py L1537~1561 + 기능테스트 3케이스
- [ ] **캘리브레이션·ECE** → §5 · 8/3 · `handlers/tabular` · 확률 신뢰도(임계값 근거), 차트 이미 생성됨
- [ ] **혼동행렬 에러 프로파일** → §5 · 9/4 · `output_extras` · "어디서 틀리나(FP·FN)" 도입 게이트 핵심
- [ ] **세그먼트 드라이버** → §6 · 8/4 · `interpretation.segment_drivers` · 코호트별 "무엇이 좌우"
- [ ] **재검증 주기** → §8 · 7/3 · `limitations.revalidation_window` · "30일·드리프트 시 재학습" 운영 정책

### 🟡 중간
- [ ] **로컬 설명(SHAP 사례)** → §6 · 8/5 · `interpretation.local_examples` · "이 건은 X 때문에 Y" 사례 3개 (현재 ML변형만)
- [ ] **분포 변화 위험** → §8 · 7/4 · `limitations.distribution_shift_risk` · 드리프트 시나리오 + 트리거
- [ ] **세그먼트별 성능표** → §5 · 7/4 · `evaluation.per_segment` · 슬라이스별 성능(현재 상위 2개만)
- [ ] **가설검정 유의성** → §3 · 6/3 · `eda.hypothesis_tests` · p-value 주석(기술→추론)
- [ ] **클래스 불균형 처리** → §4 · 6/3 · `handlers/tabular` · "소수 4:1 가중" 지표 선택 근거

### 🔴 큰 작업 (중요도 최고·노력 큼)
- [ ] **반사실(counterfactual)** → §7 · 9/8 · `interpretation.counterfactuals` · "테뉴어 1년 더면 이탈 멈췄나" 최고 액셔너블 (미구현, 생성기 필요)
- [ ] **부분 의존도 PDP** → §6.1 · 8/6 · `interpretation.partial_dependence` · "광고비↑ 시 매출 곡선" (필드 비어, 배선 필요)

### 🟣 카테고리 전용 (해당 데이터일 때 자동 노출)
- [ ] **계절성·추세 분해** (시계열) → §3/§6 · `explainability(ts)` · 신뢰구간 + 재학습 주기
- [ ] **이상 임계값 최적화** (이상치) → §5 · `handlers/anomaly/threshold_optimizer` · 운영점 + 오탐 비용
- [ ] **피처선택 근거** (전체) → §4 · `features.selection_method` · "왜 SHAP으로 골랐나"

### ⚪ 부록 (재현성)
- [ ] **학습 런 요약 / HPO 탐색공간 / 코드·환경(reproduce) / 데이터 리니지** → 부록 §9 · 4/4

---

## 📊 파이프라인 (자산이 어디서 만들어져 어디로 가나)
```
CSV → 분석 에이전트(profiler·eda·insight·model·eval·explainability·business_impact)
    → ctx (13단계: dataset·domain·preprocessing·features·eda·model·training·evaluation·interpretation·limitations·code·meta·citations)
    → [현재 60%만] → PDF (Exec·§1~§8·부록)
```
누락된 40% = 위 체크리스트. **전부 이미 계산됨** → skeleton/carrier에 조건부 서술/exhibit 추가만.

---
작성: NY · 출처: Explore 전수조사 (ctx schema·architect·content·agents) · 진행하며 [x] 체크
