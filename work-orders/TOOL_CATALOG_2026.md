# 🧰 ADA 추가 추천 도구 카탈로그 2026

> 저장일: 2026-05-19 (v2.3)
> 원본: [Notion 페이지](https://www.notion.so/365545ab947d8100b8c7fa0165da49b4)
> 권위: 본 문서는 ADA v2.1 / v2.2 명세에 **추가**되는 외부 도구를 정의한다. 도입 단계는 §10 우선순위 표를 따른다.
> 충돌 규칙: 본 문서가 도입을 강제하는 도구는 신설 Day-D / Day-E / v3 백로그 문서가 단일 권위.

본 카탈로그는 ADA v2 에이전트 시스템 구축에 추가 도입을 권장하는 **18개 도구**를 카테고리별로 정리한다. 각 도구의 선택 이유, 주요 기능, ADA 적용 포인트를 포함.

- **기준일**: 2026-05-19
- **대상 버전**: ADA v2.1 + v2.2 감사 보강 + v2.3 도구 카탈로그
- **범위**: 정형ML / 정형DL / 시계열 / 이상탐지 + 5종 산출물

---

## 1. 📡 옵저버빌리티 (LLM 관찰 및 추적)

| 도구 | 선택 이유 | 주요 기능 | ADA 적용 포인트 | 우선순위 |
|---|---|---|---|---|
| **Langfuse** | LLM 호출 전 계층 추적 + 비용/레이턴시 분석에 최적화된 오픈소스. 프롬프트 버전 관리 통합 | Trace/Span 계층, 비용 대시보드, 프롬프트 A/B, 세션 재현, 평가 파이프라인 | 27개 에이전트 호출 전체 추적, G0~G5 게이트 레이턴시, 프롬프트 회귀 감지 | 🔴 즉시 |
| **Arize Phoenix** | 로컬 실행 가능한 OSS LLM 옵저버빌리티. 임베딩 드리프트 + RAG 품질 평가 특화 | OTel 트레이싱, 임베딩 드리프트 시각화, RAG 청크 품질, 환각 스코어링 | pgvector RAG 품질 모니터링, Self-Learning 3-Stack 임베딩 드리프트 자동 감지 | 🟢 중기 |

## 2. 🗄️ 벡터 DB / RAG 고도화

| 도구 | 선택 이유 | 주요 기능 | ADA 적용 포인트 | 우선순위 |
|---|---|---|---|---|
| **Qdrant** | pgvector 대비 전용 벡터 DB. 고성능 ANN + 하이브리드 검색 | HNSW, 페이로드 필터링, 희소+밀집 하이브리드, 스냅샷, gRPC | Self-Learning 3-Stack 벡터 엔진 보완, 대용량 임베딩 시 pgvector 병행 | ⚪ 장기 |

## 3. ⚙️ ML / HPO / AutoML

| 도구 | 선택 이유 | 주요 기능 | ADA 적용 포인트 | 우선순위 |
|---|---|---|---|---|
| **FLAML** | Microsoft 저비용 AutoML. 비용 인식 탐색 | 비용 인식 HPO, LightGBM/XGBoost/RF 자동 선택, 시계열 지원 | MethodologyProposer(G2) 자동화, HPTuner warm-start 초기화 | 🟡 단기 |
| **Ray Tune** | 분산 HPO 업계 표준. Optuna/HyperOpt 통합 | ASHA/PBT, 분산 탐색, MLflow/W&B 통합, 조기 종료 | TrainingExecutor 분산 학습, Celery training 큐 활용 | 🟢 중기 |
| **ClearML** | MLflow 보완재. 실험·데이터·파이프라인 단일 플랫폼 | 자동 추적, 데이터 버전, 파이프라인 오케스트, 모델 레지스트리 | MLflow 4종 실험과 병행, 데이터 버전 강화, MinIO 연동 | ⚪ 장기 |

## 4. 📈 시계열 예측

| 도구 | 선택 이유 | 주요 기능 | ADA 적용 포인트 | 우선순위 |
|---|---|---|---|---|
| **Nixtla NeuralForecast** | NHITS·TiDE·TimesNet 등 최신 딥러닝 시계열 40+ 통합 | 40+ 신경망 시계열, GPU 가속, 확률적 예측, CV, 계층 조정 | TimeseriesPipeline 확장, TRANSFORMER_REGISTRY 후보 | 🟢 중기 |
| **Nixtla StatsForecast** | ARIMA/ETS/Theta 등 통계 베이스라인 초고속. NeuralForecast 조합 | ARIMA, ETS, Theta, CES, 자동 선택, 앙상블, CPU 병렬 | 베이스라인 자동 생성, 통계 vs 딥러닝 자동 비교 리포트 | 🟡 단기 |

## 5. 🔍 이상탐지

| 도구 | 선택 이유 | 주요 기능 | ADA 적용 포인트 | 우선순위 |
|---|---|---|---|---|
| **PyOD v3** | 이상탐지 40+ 알고리즘 통합, sklearn 호환, 딥러닝 포함 | IF/LOF/HBOS/COPOD/ECOD/AE 등 40+, 앙상블 결합기 | AnomalyPipeline 풀 확장, TranAD/AnomalyTransformer 보완 | 🔴 즉시 |
| **SUOD** | PyOD 기반 대규모 가속화. 다중 탐지기 병렬 + 근사 | 병렬 실행, 근사 예측, PyOD 완전 호환, 앙상블 집계 | 대용량 이상탐지 속도 개선, Celery training 큐 부하 감소 | 🟢 중기 |

## 6. 🛡️ 보안 / 가드레일

| 도구 | 선택 이유 | 주요 기능 | ADA 적용 포인트 | 우선순위 |
|---|---|---|---|---|
| **LLM Guard** | 프롬프트 인젝션 방어, PII 스캐닝, 입출력 검증 전문 | 인젝션 감지, PII 익명화, 독성 필터, 코드 인젝션, 출력 관련성 | Day17/Day-C 강화, G0_PII + Presidio 이중 방어, JWT 연동 | 🔴 즉시 |
| **Guardrails AI** | LLM 출력 구조화 강제 + 스키마 검증. 실패 시 자동 재시도 | 출력 스키마 검증, 자동 재시도, 커스텀 검증기, RAIL 명세 | 27개 에이전트 출력 구조 강제, 할루시네이션 필터, G1~G5 결정 검증 | 🟡 단기 |

## 7. 📄 산출물 생성

| 도구 | 선택 이유 | 주요 기능 | ADA 적용 포인트 | 우선순위 |
|---|---|---|---|---|
| **python-docx** | Word 문서 프로그래매틱 생성. OUT-01(PPTX) 보완 | 단락/표/이미지, 스타일, 헤더/푸터, 목차, 템플릿 | OUT-02(PDF) 전 Word 초안, 비즈니스 보고서 템플릿 | 🔴 즉시 |
| **Chart.js / Plotly** | OUT-04 인터랙티브 차트. 두 라이브러리 조합 | 30+ 차트, 인터랙티브, 반응형, 애니메이션, WebGL | OUT-04 시각화 엔진, SHAP 시각화, 시계열/이상탐지 차트 | 🟡 단기 |

## 8. 🔬 모델 해석성

| 도구 | 선택 이유 | 주요 기능 | ADA 적용 포인트 | 우선순위 |
|---|---|---|---|---|
| **Captum** | PyTorch 전용 해석성. TRANSFORMER_REGISTRY 8개 딥러닝 해석 | IG, Layer Attribution, SHAP, LIME, Neuron, Feature Importance | ExplainabilityAgent 딥러닝 확장, TabTransformer/FTTransformer attention | 🟢 중기 |

## 9. 🔧 자가치유 / 디버깅 / 평가

| 도구 | 선택 이유 | 주요 기능 | ADA 적용 포인트 | 우선순위 |
|---|---|---|---|---|
| **SWE-agent** | 코드 버그 자동 탐색·수정 에이전트 | GitHub 이슈 자동 해결, 코드 탐색/수정/테스트 루프 | AutoErrorHandlerAgent + cli_bridge 자동 패치 강화, error_kb 연동 | ⚪ 장기 |
| **Braintrust** | LLM 평가 프레임워크. 프롬프트 회귀 자동 감지 | 실험 추적, A/B 평가, 데이터셋 관리, 자동 스코어링, GH Actions | 27개 에이전트 프롬프트 자동 평가, AT 테스트 연동, 릴리즈 전 회귀 | ⚪ 장기 |
| **Galileo** | LLM 출력 품질 + 할루시네이션 감지 특화 | 할루시네이션 스코어, RAG 청크 관련성, 드리프트 알림 | InsightAgent 품질 감시, RAG 신뢰도 관리, Arize Phoenix 이중 커버 | ⚪ 장기 |

---

## 10. 도입 우선순위 가이드

| 우선순위 | 도구 (개수) | 도입 시점 | 근거 |
|---|---|---|---|
| 🔴 **즉시 도입** | Langfuse · LLM Guard · PyOD v3 · python-docx (4) | **Day03/12/15/17 분산 통합** (v2.4) | v2.1 핵심 기능과 직결, 구현 복잡도 낮음 |
| 🟡 **단기 도입** | Guardrails AI · FLAML · StatsForecast · Chart.js/Plotly (4) | **Day07/08/15/17 분산 통합** (v2.4) | 산출물 품질 + 모델 다양성 향상 |
| 🟢 **중기 도입** | Ray Tune · NeuralForecast · Captum · Arize Phoenix · SUOD (5) | **v3.0** 백로그 | 성능 최적화 + 설명 가능성 강화 |
| ⚪ **장기 검토** | Qdrant · ClearML · SWE-agent · Braintrust · Galileo (5) | **v3.1+** 백로그 | 인프라 전환 또는 운영 단계 필요 |

---

## 11. ADA Day 매핑 (도구 → 적용 Day)

| 도구 | 도입 Day | 기존 Day 영향 |
|---|---|---|
| Langfuse | **Day03 (← Day-D §1 통합)** | Day03 logger·Day04 LangGraph·Day18 대시보드 |
| LLM Guard | **Day17 (← Day-D §2 통합)** | Day05 PII 스캔·Day17 보안 |
| PyOD v3 | **Day12 (← Day-D §3 통합)** | Day08·Day12 AnomalyPipeline |
| python-docx | **Day15 (← Day-D §4 통합)** | Day12·Day15 OUT-02 산출물 |
| Guardrails AI | **Day17 (← Day-E §1 통합)** | Day03 BaseAgent·Day17 |
| FLAML | **Day07 (← Day-E §2 통합)** | Day07 ModelSelection·Day19 HPO warm-start |
| StatsForecast | **Day08 (← Day-E §3 통합)** | Day08 TimeseriesPipeline |
| Chart.js/Plotly | **Day15 (← Day-E §4 통합)** | Day15 OUT-04·Day18 대시보드 |
| Ray Tune | v3 백로그 §1 | Day08 분산 HPO |
| NeuralForecast | v3 백로그 §2 | Day08·Day12 TRANSFORMER_REGISTRY 확장 |
| Captum | v3 백로그 §3 | Day11 ExplainabilityAgent |
| Arize Phoenix | v3 백로그 §4 | Day19 SelfLearning·Day-B Shadow eval |
| SUOD | v3 백로그 §5 | Day08·Day12 대용량 AnomalyPipeline |
| Qdrant | v3 백로그 §6 | Day02 pgvector 병행 |
| ClearML | v3 백로그 §7 | Day08 MLflow 보완 |
| SWE-agent | v3 백로그 §8 | Day16 AutoErrorHandler |
| Braintrust | v3 백로그 §9 | Day14·Day20 테스트 회귀 |
| Galileo | v3 백로그 §10 | Day11·Day19 InsightAgent 품질 감시 |

---

## 12. 신규 룰 (v2.3)

- **R-1001** — 모든 LLM 호출은 Langfuse trace 자동 첨부 (`@trace` 데코레이터 의무, Day-D §1).
- **R-1002** — 사용자 입력 sanitize 경로에 LLM Guard 우선 적용 후 ADA INJECTION_PATTERNS fallback (Day-D §2).
- **R-1003** — AnomalyPipeline 알고리즘 선택은 PyOD v3 레지스트리에서 수행 (Day-D §3).
- **R-1004** — OUT-02 PDF 생성 전 Word 초안 산출이 옵션 산출물(.docx)로 보존 (Day-D §4).
- **R-1005** — 모든 게이트 LLM 응답은 Guardrails AI 스키마 검증 통과 후에만 state 반영 (Day-E §1).
- **R-1006** — HPO warm-start 시 KB 추천이 없으면 FLAML cost-aware HPO 로 자동 폴백 (Day-E §2).
- **R-1007** — TimeseriesPipeline 은 StatsForecast 베이스라인 1개 + 딥러닝 1개를 항상 Top-3 후보에 포함 (Day-E §3).
- **R-1008** — OUT-04 단일 HTML 은 Chart.js 우선, 인터랙티브 필요 시 Plotly 폴백 (Day-E §4).

---

## 13. 카테고리별 진입 비용 / 운영 비용 / 라이선스 요약

| 도구 | 라이선스 | 진입 비용 (도입 1주 기준) | 운영 비용 | 위험 |
|---|---|---|---|---|
| Langfuse | MIT | 낮음 (self-host docker compose 1개) | 낮음 | 데이터 잔존 정책 정의 필요 |
| LLM Guard | MIT | 낮음 | 낮음 | 정규식 룰 유지보수 |
| PyOD v3 | BSD | 낮음 | 낮음 | 알고리즘 수가 많아 선택 기준 정의 필요 |
| python-docx | MIT | 매우 낮음 | 매우 낮음 | 한글 폰트 사전 패키징 |
| Guardrails AI | Apache 2 | 중간 (RAIL 스펙 학습) | 낮음 | 잘못된 스키마는 재시도 폭주 가능 |
| FLAML | MIT | 중간 | 낮음 | Optuna 와 중복 영역 |
| StatsForecast | Apache 2 | 낮음 | 낮음 | 시계열 빈도 가정 명확화 |
| Chart.js | MIT / Plotly MIT | 낮음 | 낮음 | CDN vs 인라인 정책 |
| Ray Tune | Apache 2 | 높음 (클러스터 셋업) | 중간 | GPU 인프라 필수 |
| NeuralForecast | Apache 2 | 중간 | 중간 (GPU) | 라이브러리 의존 충돌 |
| Captum | BSD | 중간 | 중간 (GPU) | PyTorch 전용 |
| Arize Phoenix | Apache 2 | 낮음 | 낮음 | Langfuse 와 기능 중복 일부 |
| SUOD | BSD | 중간 | 낮음 | PyOD 버전 호환성 |
| Qdrant | Apache 2 | 높음 (별도 컨테이너) | 중간 | pgvector 와 이중 운영 비용 |
| ClearML | Apache 2 | 높음 | 중간 | MLflow 와 책임 영역 분리 필요 |
| SWE-agent | MIT | 매우 높음 (자율 패치 거버넌스) | 중간 (LLM 호출) | 자동 코드 변경 위험 — 인간 검토 필수 |
| Braintrust | Commercial / OSS 일부 | 중간 | 유료 등급 가능 | 데이터 외부 전송 |
| Galileo | Commercial | 중간 | 유료 | 데이터 외부 전송 |

---

## 14. 본 문서와 다른 권위 문서의 관계

- 본 문서가 도입 단계를 정의 — 실제 산출물·테이블·스크립트·완료 기준은 (v2.4 부터):
  - Langfuse → Day03 통합본
  - LLM Guard / Guardrails AI → Day17 통합본
  - PyOD v3 → Day12 통합본
  - python-docx / Chart.js·Plotly → Day15 통합본
  - FLAML → Day07 통합본
  - StatsForecast → Day08 통합본
  - 중기 5종 + 장기 5종 → `v3_backlog.md`
- 도구별 룰(R-1001~R-1008)은 AGENTS.md 누적 + Day-D / Day-E 안에서 검증.
- 우선순위 변경 시 본 문서 + RENEWAL_SPEC v2.3 §0 동시 갱신.
