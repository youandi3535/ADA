# Day 21 — 인수 테스트 + 데모 시나리오 4×5 매트릭스 + 풀 문서화
> 프로젝트: Adaptive AutoAI Pipeline Agent | 3주 스프린트 Day 21/21 (최종일)
> 본 문서는 v2 신규 작업이다. **v2.1 스코프 축소 적용** (RENEWAL_SPEC.md 권위).

---

## 📋 오늘의 목표

3주 스프린트 v2의 **최종 검증·시연·문서화** 일. 인수 테스트 4종(AT-1~AT-4) + 데모 시나리오 4 카테고리 × 산출물 5종 매트릭스 = 최대 20 데모 + 풀 문서화.

---

## 👤 담당자

전체

---

## ✅ 작업 목록

### 1. 인수 테스트 AT-1 ~ AT-4 (v2.1)

v1 인수 테스트를 v2 인터랙티브 흐름에 맞춰 갱신. v2.1에서 image/NLP 카테고리 제거에 따라 AT-3(image), AT-4(nlp) 삭제하고 노이즈 tabular 시나리오를 AT-4로 승격.

#### AT-1: Titanic (tabular_ml + 임원 의도 + OUT-01 + OUT-07)
- E2E ≤ 120s (사용자 응답 시간 제외)
- val_f1 ≥ 0.78 (트랜스포머 포함)
- OUT-01 (PPT) + OUT-07 (인사이트 MD) 생성 + 다운로드

#### AT-2: 월별 매출 (timeseries + Informer/TFT + OUT-04 대시보드)
- val_mape ≤ 0.20
- G4에서 TFT 또는 Informer 선택 가능
- OUT-04 단일 HTML 대시보드 < 5MB

#### AT-3: 네트워크 트래픽 (anomaly_detection + IsolationForest/AnomalyTransformer + OUT-02 + OUT-04)
- val_f1 ≥ 0.70 (라벨 있는 이상 샘플 기준)
- G4에서 AnomalyTransformer 또는 IsolationForest 선택 가능
- OUT-02 (PDF 리포트) + OUT-04 (대시보드)

#### AT-4: 노이즈 tabular (Self-Evolving + Auto-Error + Self-Learning, tabular_dl)
- 1차 실행 → 의도적 실패 유도 (val_f1 임계 미달)
- AutoErrorHandler가 error_kb에 lesson 저장
- HarnessAuditor가 새 룰 R-A0xx 제안 → AGENTS.md 머지
- SelfLearningAgent가 failure_lesson 임베딩
- 2차 실행 → KB warm start + 룰 반영 → val_f1 +15%p 향상

> v2.1 축소로 ~~AT-3 CIFAR-10 (image + ViT + GradCAM)~~, ~~AT-4 한국어 리뷰 (nlp + KLUE-BERT LoRA + OUT-13 팟캐스트)~~ 는 제거됨.

### 2. 데모 시나리오 4×5 매트릭스 (최대 20)

| 시나리오 \ 산출물 | OUT-01 (PPT) | OUT-02 (PDF) | OUT-03 (대본) | OUT-04 (대시보드) | OUT-07 (인사이트 MD) |
|---|---|---|---|---|---|
| **고객이탈 (tabular_ml)**     | ✓ 데모1 | ✓ 데모5 | ✓ 데모9  | ✓ 데모13 | ✓ 데모17 |
| **세그먼트 분류 (tabular_dl)** | ✓ 데모2 | ✓ 데모6 | ✓ 데모10 | ✓ 데모14 | ✓ 데모18 |
| **매출 예측 (timeseries)**     | ✓ 데모3 | ✓ 데모7 | ✓ 데모11 | ✓ 데모15 | ✓ 데모19 |
| **네트워크 이상 (anomaly)**    | ✓ 데모4 | ✓ 데모8 | ✓ 데모12 | ✓ 데모16 | ✓ 데모20 |

총 최대 20개 데모. 각 데모는:
- 사전 준비된 데이터셋 + 의도
- 인터랙티브 게이트 5단계 응답 스크립트
- 예상 결과 메트릭
- 산출물 인스턴스 (`{minio_path}/`)
- 5분 발표 대본 (`docs/demo_scripts/`)

### 3. 발표 데모 시나리오 본 (대표 4종)

#### 데모-1 (고객이탈 tabular_ml → PPT)
- "이 고객 데이터를 받으셨다고 가정합니다. 그냥 시작 버튼만 누르면..."
- G0: "이탈 가능성 높은 고객을 식별해서 임원 보고용 PPT가 필요해요"
- G1: 시스템이 "전체 이탈 패턴 분석 / 세그먼트별 / 시간 흐름별" 3안 제시 → "세그먼트별" 선택
- G2: "tabular_ml (트리 앙상블 + TabTransformer 보조)" 추천 채택
- G3: "TabTransformer + LightGBM 비교" 채택
- G4: 비교표에서 더 해석가능한 LightGBM 선택
- G5: OUT-01만 체크
- → PPT 다운로드 및 슬라이드 시연

#### 데모-3 (매출 예측 timeseries → 대시보드)
- 24개월 월별 매출 csv
- G3: TFT + PatchTST 비교 채택, G4: TFT 선택
- G5: OUT-04 (정적 대시보드) 선택
- → 단일 HTML 인터랙티브 대시보드 시연 (메트릭 토글, 예측 구간 차트)

#### 데모-4 (네트워크 이상 anomaly_detection → 인사이트 MD)
- 네트워크 트래픽 로그 csv
- G3: AnomalyTransformer + IsolationForest 비교, G4: AnomalyTransformer 선택
- G5: OUT-07 (인사이트 MD) 선택
- → Markdown 인사이트 본문 + SHAP top10 표 시연

#### 데모-AT4 (Self-Evolving)
- 1차 실행 → 실패
- 시스템 현황판에서 "에러 KB +1, 자체학습 KB +1, 새 룰 R-A015 추가됨" 노출
- 2차 실행 → 성공, 메트릭 향상
- 현황판에서 "Claude CLI 호출 그래프 ↓, 자체 해결률 ↑" 시연

### 4. 풀 문서화

#### 4.1 에이전트 README × 27

- [ ] `docs/agents/{agent_name}.md`:
  - 역할 한 줄, 입력 state 필드, 출력 state 필드, LLM 사용 여부, 핵심 알고리즘, 의존성, 단위 테스트 경로

#### 4.2 시스템 아키텍처 문서

- [ ] `docs/architecture.md`:
  - 컨테이너 토폴로지 (마스터 §2.1)
  - 데이터 흐름 (마스터 부록 A)
  - LangGraph 노드/엣지 mermaid
  - DB ERD (29 테이블)
  - 의사결정 5게이트 흐름
  - 자체학습 3-Stack 다이어그램
  - 자동 오류 처리 시퀀스
  - 보안 위협 모델 (마스터 §10.1)

#### 4.3 API 레퍼런스

- [ ] Swagger `/docs` 풀 노출 + `/redoc` 정적 빌드 → `docs/api/index.html`
- [ ] OpenAPI v3 스펙 JSON export → `docs/api/openapi.json`

#### 4.4 운영 가이드

- [ ] `docs/operations/`:
  - `getting_started.md` — Docker Compose 실행
  - `environment_variables.md` — .env 전체 키 설명
  - `backup_restore.md` — Postgres/MinIO 백업
  - `secrets_rotation.md` — Vault 키 회전
  - `monitoring.md` — Prometheus/Grafana 대시보드 임포트
  - `troubleshooting.md` — 자주 발생하는 문제 5가지

#### 4.5 개발 가이드

- [ ] `docs/development/`:
  - `add_new_agent.md` — 새 에이전트 등록 (BaseAgent 상속 → registry seed → 그래프 등록)
  - `add_new_output.md` — 새 산출물 생성기 추가
  - `add_new_transformer.md` — TRANSFORMER_REGISTRY 등록
  - `extend_self_learning.md` — KB type 추가
  - `extend_security.md` — 새 PII 패턴 / 인젝션 패턴 등록
  - `agent_naming_conventions.md` — 명명 규칙

#### 4.6 사용자 매뉴얼

- [ ] `docs/user/`:
  - `quickstart.md` — 첫 분석 5분 가이드
  - `gates_guide.md` — 5게이트 각각 어떻게 선택할지
  - `outputs_catalog.md` — 5종 산출물 안내 (OUT-01/02/03/04/07)
  - `faq.md`

### 5. AGENTS.md 최종 정리

- [ ] R-001~R-9xx 체계화 (마스터 §14)
- [ ] 자동 누적 룰 R-A001~R-Axxx 카운트 ≥ 15 (KP6)
- [ ] 룰별 적용 에이전트, confidence, 생성일 컬럼 정리

### 6. KPI v2 최종 보고서

- [ ] Day20 측정 결과 + Day21 인수테스트 결과 통합 → `docs/kpi_v2_final.md`
- [ ] 모든 KPI 11개 표로 정리, 기준/측정값/달성 여부

### 7. 데모 환경 시드 + 1-click 실행 스크립트

- [ ] `scripts/demo_seed.sh`:
  - 데이터셋 4종 다운로드 + MinIO 업로드 (v2.1: 4 카테고리 대표 데이터셋)
  - 테스트 사용자 3종 생성 (admin/analyst/viewer)
  - 자체학습 KB warm seed (사전 distill 결과 4건)
- [ ] `scripts/demo_run.sh <scenario_id>`:
  - 시나리오 ID로 자동 잡 실행 + 자동 게이트 응답 (시연 시 수동 응답 가능 옵션)

### 8. 최종 회고

- [ ] `docs/retrospective_v2.md`:
  - 잘 된 점, 개선할 점, 다음 스프린트 백로그

---

## 📁 생성/수정 파일 목록

| 경로 | 작업 |
|---|---|
| `tests/acceptance/test_at1_v2.py` ~ `test_at4_v2.py` | 신규/갱신 |
| `docs/agents/*.md` (27개) | 신규 |
| `docs/architecture.md` | 신규 |
| `docs/api/openapi.json` (자동) | 신규 |
| `docs/operations/*.md` (6개) | 신규 |
| `docs/development/*.md` (6개) | 신규 |
| `docs/user/*.md` (4개) | 신규 |
| `docs/demo_scripts/scenario_*.md` (4개 강화) | 갱신 |
| `docs/kpi_v2_final.md` | 신규 |
| `docs/retrospective_v2.md` | 신규 |
| AGENTS.md | 최종 정리 |
| `scripts/demo_seed.sh`, `scripts/demo_run.sh` | 신규 |
| README.md | v2 풀 갱신 (한 페이지 개요) |

---

## 🔗 의존성 & 선행 조건

- Day20 통합 테스트 모두 PASS
- 모든 KPI v2 측정 완료
- 데모용 데이터셋 (Day14 fixture에 더해 v2.1 4 카테고리 대표 4종) 준비

---

## ✔️ 완료 기준

- [ ] AT-1~AT-4 PASS
- [ ] 데모 시나리오 4×5 매트릭스 중 핵심 12개 데모 정상 실행 (4 카테고리 × 3 산출물 권장)
- [ ] docs/ 디렉토리 27 (agents) + 20 (demo×outputs) + 운영6 + 개발6 + 사용자4 + architecture/kpi/retrospective = 65+ 마크다운 파일 완성
- [ ] AGENTS.md 룰 총 15개 이상 + R-001~R-9xx + R-A0xx 형식 일치
- [ ] KPI v2 보고서 모든 항목 측정값 기록
- [ ] README.md 가 새 사용자가 5분 안에 첫 분석 시작 가능하도록 명확히 작성
- [ ] `scripts/demo_run.sh demo-1` 한 줄로 데모1 자동 실행

---

## ⚠️ 주의사항

- AT-4 (Self-Evolving) 노이즈 tabular_dl 시나리오는 1·2차 실행 시간이 길어질 수 있음 — fixture 크기 조정
- 데모 시연 중 LLM API rate limit 위험 — 데모 직전 Anthropic 한도 확인
- 문서화 코드 예시는 실제 동작 코드와 동기화 (drift 방지 — `pytest-doctest` 활용)
- AGENTS.md 자동 누적 룰이 15개 미달인 경우 AT-4 시나리오 추가 반복 실행으로 보충
- Vault dev 모드는 데모 재시작 시 시드 재실행 필요 — demo_seed.sh에 포함
