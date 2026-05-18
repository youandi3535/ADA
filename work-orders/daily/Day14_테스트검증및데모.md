# Day 14 — 테스트 + 검증 + 데모 + 문서화
> 프로젝트: Adaptive AutoAI Pipeline Agent | 2주 스프린트 Day 14/14

---

## 📋 오늘의 목표

2주 스프린트의 최종일로, **시스템 전체 품질을 검증**하고 **데모 시나리오를 실행**하며 **문서화를 완성**한다.
단위/통합/인수 테스트를 실행하여 KPI를 수치로 확인하고,
Self-Evolving Harness의 AGENTS.md 자동 누적 룰 10개 이상 생성을 검증한다.

- 통합 테스트 25케이스 (6개 카테고리 E2E + 재루프 + 오류 복구 + 동시 요청)
- 에이전트 단위 테스트 커버리지 80% 이상
- 인수 테스트 5종 (Titanic, 매출예측, CIFAR-10, 한국어 리뷰, 노이즈 데이터)
- KPI 7개 항목 수치 검증
- 데모 시나리오 5종 서면 준비
- 전체 문서화 완성

---

## 👤 담당자

**전체** (A, B, C, D 공동)

---

## ✅ 작업 목록

### 1. 통합 테스트 25케이스 작성

- [ ] `tests/test_e2e/test_pipeline.py` 파일 생성

  **6개 카테고리별 E2E 테스트 (6케이스):**
  - `test_e2e_tabular_ml_classification`: Titanic CSV → 분류 → PPT/PDF 생성 확인
  - `test_e2e_tabular_ml_regression`: 보스턴 주택 CSV → 회귀 → val_r2 > 0.5 확인
  - `test_e2e_timeseries`: 월별 승객 수 CSV → 6개월 예측 → 신뢰구간 포함 확인
  - `test_e2e_image`: 소규모 이미지 ZIP → 분류 → GradCAM 이미지 생성 확인
  - `test_e2e_nlp`: 한국어 리뷰 CSV → 감성 분류 → 한국어 인사이트 생성 확인
  - `test_e2e_anomaly`: 노이즈 포함 tabular → 이상탐지 → val_auc > 0.6 확인

  **실패 → 재루프 → 성공 시나리오 (5케이스):**
  - `test_reloop_1_retry_success`: 1회 실패 후 2회째 성공
  - `test_reloop_2_consecutive_fails`: 3회 연속 실패 → error_recovery 라우팅
  - `test_reloop_3_hyperparams_adjust`: 재루프 시 탐색 공간 조정 확인
  - `test_reloop_4_model_switch`: 2회 실패 후 단순 모델로 자동 전환
  - `test_reloop_5_lr_reduction`: 발산 후 학습률 1/10 적용 재시도

  **오류 복구 시나리오 (5케이스):**
  - `test_error_data_error`: 잘못된 CSV 형식 → data_error 분류 → abort
  - `test_error_oom`: OOM 모의 → batch_size 절반 → 재시도
  - `test_error_divergence`: 발산 모의 → lr 감소 → 재시도
  - `test_error_rate_limit`: Rate Limit 모의 → 백오프 후 성공
  - `test_error_json_decode`: JSONDecodeError 모의 → 재호출 → 성공

  **동시 요청 처리 테스트 (4케이스):**
  - `test_concurrent_2_jobs`: 2개 job 동시 실행, 서로 간섭 없음 확인
  - `test_concurrent_5_jobs`: 5개 job 동시 실행, 모두 완료 확인
  - `test_concurrent_same_category`: 동일 카테고리 3개 동시, 결과 독립성 확인
  - `test_concurrent_mixed_categories`: 서로 다른 카테고리 4개 동시 실행

  **기타 통합 테스트 (5케이스):**
  - `test_harness_rule_accumulation`: 3회 실패 → AGENTS.md 3개 이상 룰 누적 확인
  - `test_websocket_progress`: WebSocket 연결 → progress_pct 0→100 증가 확인
  - `test_download_all_types`: PPT/PDF/모델/대본 4종 다운로드 정상 확인
  - `test_hitl_gate`: HITL 게이트에서 일시 정지 → 사용자 승인 → 재개 확인
  - `test_full_pipeline_time`: Titanic 기준 E2E 90초 이내 완료 확인

### 2. 에이전트 단위 테스트 (커버리지 80% 이상)

- [ ] `tests/test_agents/test_supervisor.py`
  - 유효 입력 (CSV + tabular_ml + target_col) → `state.job_id` 생성 확인
  - 무효 입력 (빈 파일) → 에러 메시지 반환 확인
  - 지원 불가 카테고리 → 적절한 예외 확인
  - HITL 게이트: `require_approval=True` → `state.status='waiting_approval'` 확인

- [ ] `tests/test_agents/test_data_profiler.py`
  - tabular 데이터: `n_rows`, `n_cols`, `missing_ratio` 정확성
  - 전체 결측 컬럼 처리
  - 혼합 타입 컬럼 처리
  - 이미지 ZIP: 클래스별 파일 수 집계 확인
  - 텍스트 파일: 평균 텍스트 길이, 고유 토큰 수

- [ ] `tests/test_agents/test_schema_validator.py`
  - `tabular_ml`: target_col 존재 여부, 최소 2개 클래스
  - `timeseries`: datetime 인덱스 필수, 최소 30행
  - `image`: 클래스별 최소 10장
  - `nlp`: 텍스트 컬럼 존재, 레이블 컬럼 존재
  - `anomaly_detection`: 수치형 컬럼 2개 이상
  - `tabular_dl`: tabular_ml 동일 + 최소 200행

- [ ] `tests/test_agents/test_eval_agent.py`
  - 임계치 경계값 테스트:
    - `val_f1=0.599` → 실패 (경계 미달)
    - `val_f1=0.600` → 1차 통과 (LLM 2차 평가 진입)
    - `val_f1=0.601` → 1차 통과
  - `forecasting` max_below 모드:
    - `val_mape=0.31` → 실패 (임계 초과)
    - `val_mape=0.29` → 1차 통과
  - LLM 2차 평가 mock 처리 (실제 API 호출 없음)
  - `route_after_eval` 라우팅 로직 단위 테스트

- [ ] `tests/test_agents/test_auditor.py`
  - `audit_failure()` 반환 JSON 필드 검증: `category`, `root_cause`, `proposed_rule`, `confidence`, `applies_to_agents`
  - `confidence=0.9` → `is_active=True` (즉시 자동 적용) 확인
  - `confidence=0.5` → `is_active=False` (pending) 확인
  - AGENTS.md에 `R-A001` 형식 코드 추가 확인

### 3. 파이프라인 단위 테스트 (커버리지 60% 이상)

- [ ] `tests/test_pipelines/test_tabular_ml.py`
  - XGBoost, LightGBM, CatBoost, RandomForest 학습 후 메트릭 반환 확인
  - `val_f1`, `val_accuracy` 키 존재 확인 (분류)
  - `val_rmse`, `val_r2` 키 존재 확인 (회귀)

- [ ] `tests/test_pipelines/test_timeseries.py`
  - Prophet: `val_mape`, `val_rmse`, 신뢰구간 키 확인
  - ARIMA: `val_mape`, `val_rmse` 확인
  - LSTM: 최소 100행 데이터로 정상 학습 확인

- [ ] `tests/test_pipelines/test_image.py`
  - ResNet50: 데이터 <500 시 backbone freeze 확인
  - EfficientNetB0: `val_f1_macro` 반환 확인
  - DataLoader 배치 크기, shuffle 설정 확인

- [ ] `tests/test_pipelines/test_nlp.py`
  - klue/bert-base 토크나이저 정상 로드 확인
  - `max_length=128` padding 확인
  - `val_f1`, `val_accuracy` 반환 확인

- [ ] `tests/test_pipelines/test_anomaly.py`
  - IsolationForest: `-1`/`1` 예측 값 확인
  - AutoEncoder: `threshold` 계산 확인 (mean + 3*std)
  - `val_auc` 반환 확인

### 4. API 테스트

- [ ] `tests/test_api/test_endpoints.py` (12개 엔드포인트 전체)

  **Day 1~7 엔드포인트 (기존):**
  - `POST /jobs`: 파일 업로드 → `job_id` 반환
  - `GET /jobs/{job_id}`: 상태 조회
  - `GET /jobs/{job_id}/logs`: 로그 반환
  - `DELETE /jobs/{job_id}`: 취소 처리

  **Day 13 신규 엔드포인트:**
  - `GET /results/{job_id}`: 전체 결과 필드 검증
  - `GET /download/{job_id}/ppt`: Content-Type 확인
  - `GET /download/{job_id}/pdf`: 응답 크기 > 0 확인
  - `POST /predict/{model_id}`: `prediction` 필드 확인
  - `GET /models`: 리스트 타입 응답 확인
  - `GET /health`: 4개 서비스 키 모두 포함 확인
  - `GET /rules`: `rule_code` 형식 R-A001~ 확인
  - `GET /telemetry/stats`: `success_rate` 필드 확인

### 5. 인수 테스트 5종 실행

- [ ] **AT-1: Titanic CSV → tabular_ml 분류**
  - 입력: `titanic.csv` (891행, 12컬럼, target='Survived')
  - 카테고리: `tabular_ml`
  - 기준:
    - E2E 완료 시간 ≤ 90초
    - `val_f1 ≥ 0.75`
    - PPT/PDF 생성 및 다운로드 정상
  - 검증 방법: `pytest tests/acceptance/test_at1_titanic.py -v`

- [ ] **AT-2: 월별 매출 CSV → timeseries 6개월 예측**
  - 입력: `monthly_sales.csv` (최소 36개월, 컬럼: date, sales)
  - 카테고리: `timeseries`
  - 기준:
    - `val_mape ≤ 0.30`
    - 신뢰구간 하한/상한 값 포함 확인
    - 예측 차트 PNG MinIO 저장 확인
  - 검증 방법: `pytest tests/acceptance/test_at2_timeseries.py -v`

- [ ] **AT-3: CIFAR-10 일부 ZIP → image 학습 → /predict 호출**
  - 입력: `cifar10_sample.zip` (클래스당 100장, 10클래스)
  - 카테고리: `image`
  - 기준:
    - `val_accuracy ≥ 0.70`
    - `/predict/{model_id}` API 호출 시 유효 클래스명 반환
    - GradCAM 이미지 생성 확인
  - 검증 방법: `pytest tests/acceptance/test_at3_image.py -v`

- [ ] **AT-4: 한국어 리뷰 CSV → nlp 감성 분류 → 한국어 인사이트**
  - 입력: `korean_reviews.csv` (최소 1,000행, 컬럼: text, label)
  - 카테고리: `nlp`
  - 기준:
    - `val_f1 ≥ 0.70`
    - `state.insights` 한국어 4단락 이상 생성 확인
    - Attention map PNG 생성 확인
  - 검증 방법: `pytest tests/acceptance/test_at4_nlp.py -v`

- [ ] **AT-5: 노이즈 포함 tabular → 1회 실패 유도 → Auditor 룰 추가 → 재실행 성공**
  - 입력: `noisy_tabular.csv` (결측률 40%, 클래스 불균형 10:1)
  - 카테고리: `tabular_ml`
  - 시나리오:
    1. 1차 실행: `val_f1 < 0.6` 실패 유도 (threshold 임의 상향)
    2. HarnessAuditor가 클래스 불균형 관련 룰 제안
    3. AGENTS.md에 새 룰 추가 확인
    4. 2차 실행: SMOTE 적용 전처리로 `val_f1 ≥ 0.6` 달성
  - 기준:
    - AGENTS.md에 `R-A00X` 새 룰 추가 확인
    - 2차 실행 성공률 ≥ 1회
  - 검증 방법: `pytest tests/acceptance/test_at5_harness.py -v`

### 6. KPI 측정 (정량)

- [ ] **E2E 성공률 ≥ 80%**
  - 측정: `SELECT COUNT(*) FILTER (WHERE status='completed') * 100.0 / COUNT(*) FROM jobs`
  - 기준: 25케이스 중 20케이스 이상 성공

- [ ] **응답 속도 ≤ 90초 (Titanic 기준)**
  - 측정: `AT-1` 실행 시간 타이머
  - `time.time()` 기반 E2E 경과 시간 기록

- [ ] **자동 재루프 성공률 ≥ 70%**
  - 측정: 재루프 발생 job 중 최종 성공 비율
  - `SELECT COUNT(*) FROM jobs WHERE retry_count > 0 AND status='completed'`

- [ ] **Harness 학습 효과: 2번째 실행 정확도 +15%p 이상**
  - 측정: AT-5 기준, 1차 실행 val_f1 대비 2차 실행 val_f1 차이
  - 예시: 1차 `0.48` → 2차 `0.65` (+17%p)

- [ ] **카테고리 커버 6/6**
  - 측정: 6개 카테고리 각 1회 이상 성공 완료 확인
  - `tabular_ml`, `timeseries`, `image`, `nlp`, `anomaly_detection`, `tabular_dl`

- [ ] **API p95 응답 < 500ms**
  - 측정: `GET /health`, `GET /results/{job_id}` 100회 호출 후 p95 계산
  - `pytest-benchmark` 또는 `locust` 활용

- [ ] **AGENTS.md 자동 누적 룰 10개 이상**
  - 측정: `SELECT COUNT(*) FROM rules WHERE is_active=TRUE AND created_at >= sprint_start`
  - AGENTS.md 파일 직접 확인 (`grep -c "^### R-A" AGENTS.md`)

### 7. Self-Evolving 검증

- [ ] AGENTS.md `R-A001`~`R-A010` 이상 자동 생성 확인
  - 각 규칙 형식 검증: `rule_code`, `category`, `root_cause`, `confidence` 포함
  - 신뢰도 ≥ 0.8 규칙 자동 적용, 미만 규칙 pending 상태 확인
  - AT-5 재실행에서 Harness 학습 효과(룰 적용으로 성능 향상) 검증

- [ ] `SELECT * FROM audit_history ORDER BY created_at` 감사 이력 10건 이상 확인
- [ ] `SELECT * FROM success_patterns` 성공 패턴 5건 이상 저장 확인

### 8. 데모 시나리오 5종 준비

- [ ] **시나리오 1: 고객 이탈 예측 (tabular_ml)**
  - 데이터: 통신사 고객 데이터 (계약기간, 요금제, 불만 횟수, 이탈여부)
  - 목표: 이탈 가능성 높은 고객 상위 100명 식별
  - 기대 결과: val_f1 ≥ 0.75, SHAP에서 "계약기간"이 top feature
  - 비즈니스 임팩트: 이탈 방지 대상 고객 1인당 연간 수익 X원 보전
  - 발표 스크립트: 5분 분량 ([Slide 1]~[Slide 10])

- [ ] **시나리오 2: 매출 예측 (timeseries)**
  - 데이터: 3년치 월별 매출 (계절성 포함)
  - 목표: 향후 6개월 매출 예측 + 신뢰구간
  - 기대 결과: val_mape ≤ 0.20, 계절 피크 패턴 포착
  - 비즈니스 임팩트: 재고/인력 계획 최적화 비용 절감
  - 발표 스크립트: 5분 분량

- [ ] **시나리오 3: 불량품 탐지 (image)**
  - 데이터: 제조 공정 제품 이미지 (정상/불량 2클래스)
  - 목표: 불량품 자동 탐지, val_accuracy ≥ 0.90
  - 기대 결과: GradCAM으로 불량 부위 하이라이트 시각화
  - 비즈니스 임팩트: 검수 인력 X명 → AI 자동화로 비용 절감
  - 발표 스크립트: 5분 분량

- [ ] **시나리오 4: 고객 리뷰 감성 분석 (nlp)**
  - 데이터: 쇼핑몰 한국어 리뷰 (5,000건, 긍정/중립/부정)
  - 목표: 3클래스 감성 분류, val_f1 ≥ 0.72
  - 기대 결과: Attention map에서 "별로", "최악" 등 부정 키워드 강조
  - 비즈니스 임팩트: 부정 리뷰 자동 알림 → 서비스 개선 사이클 단축
  - 발표 스크립트: 5분 분량

- [ ] **시나리오 5: 네트워크 이상 탐지 (anomaly)**
  - 데이터: 네트워크 트래픽 로그 (패킷 크기, 지연, 프로토콜 등)
  - 목표: 정상 패턴 학습 후 이상 트래픽 탐지, val_auc ≥ 0.80
  - 기대 결과: AutoEncoder 재구성 오차 기반 이상 점수 시각화
  - 비즈니스 임팩트: 보안 침해 사전 탐지, MTTD(평균 탐지 시간) 단축
  - 발표 스크립트: 5분 분량

### 9. 문서화 완성

- [ ] **에이전트별 README 17개** (`agents/*/README.md`):
  - 각 에이전트 역할, 입력/출력 state 필드, LLM 사용 여부, 주요 알고리즘

- [ ] **Swagger UI 정비** (`/docs`):
  - 12개 엔드포인트 summary, description, response_model 완성
  - 예시 request/response 추가 (FastAPI `examples` 파라미터)

- [ ] **전체 README.md** (프로젝트 루트):
  - 프로젝트 개요 (1단락)
  - 시스템 아키텍처 다이어그램 (ASCII 또는 이미지)
  - 빠른 시작 (Docker Compose 실행 방법)
  - 환경 변수 목록 (`.env.example`)
  - 6개 카테고리 사용 가이드
  - 기여 방법

- [ ] **설계 문서** (`docs/architecture.md`):
  - 전체 에이전트 플로우 다이어그램 (LangGraph 노드/엣지)
  - 데이터 흐름도 (사용자 → MinIO → 에이전트 → DB → 산출물)
  - Harness Self-Evolving 루프 설명
  - DB 스키마 ERD

- [ ] **`isolation_check.yml` CI 통과 확인**:
  - `pytest tests/` 전체 실행 → 실패 케이스 0개 (경고 허용)
  - `coverage report` agents/ 80% 이상, pipelines/ 60% 이상

---

## 🏗️ 구현 명세

### 인수 테스트 구조

```python
# tests/acceptance/test_at1_titanic.py
import pytest
import time
import httpx

BASE_URL = "http://localhost:8000"

class TestAT1Titanic:
    @pytest.fixture(scope="class")
    def job_id(self, titanic_csv_path):
        start = time.time()
        with open(titanic_csv_path, 'rb') as f:
            response = httpx.post(f"{BASE_URL}/jobs",
                files={"file": ("titanic.csv", f, "text/csv")},
                data={"category": "tabular_ml", "target_column": "Survived"}
            )
        assert response.status_code == 200
        return response.json()['job_id'], start

    def test_completion_time(self, job_id):
        jid, start_time = job_id
        # 완료 대기 (폴링)
        for _ in range(90):  # 90초
            time.sleep(1)
            resp = httpx.get(f"{BASE_URL}/jobs/{jid}")
            if resp.json()['status'] in ('completed', 'aborted', 'failed'):
                break
        elapsed = time.time() - start_time
        assert elapsed <= 90, f"E2E 시간 초과: {elapsed:.1f}s"
        assert resp.json()['status'] == 'completed'

    def test_val_f1_threshold(self, job_id):
        jid, _ = job_id
        results = httpx.get(f"{BASE_URL}/results/{jid}").json()
        assert results['model_metrics']['val_f1'] >= 0.75

    def test_ppt_download(self, job_id):
        jid, _ = job_id
        response = httpx.get(f"{BASE_URL}/download/{jid}/ppt")
        assert response.status_code == 200
        assert len(response.content) > 10000  # 최소 10KB

    def test_pdf_download(self, job_id):
        jid, _ = job_id
        response = httpx.get(f"{BASE_URL}/download/{jid}/pdf")
        assert response.status_code == 200
        assert response.headers['content-type'] == 'application/pdf'
```

### KPI 측정 스크립트

```python
# scripts/measure_kpi.py
import psycopg2
import time
import httpx
import subprocess

def measure_e2e_success_rate(db_conn):
    cursor = db_conn.cursor()
    cursor.execute("""
        SELECT
            COUNT(*) FILTER (WHERE status='completed') * 100.0 / COUNT(*) AS success_rate
        FROM jobs
        WHERE created_at >= NOW() - INTERVAL '14 days'
    """)
    result = cursor.fetchone()
    success_rate = result[0]
    print(f"E2E 성공률: {success_rate:.1f}% (기준: ≥ 80%)")
    assert success_rate >= 80, f"E2E 성공률 미달: {success_rate:.1f}%"

def measure_agents_md_rules():
    result = subprocess.run(
        ['grep', '-c', r'^### R-A', 'AGENTS.md'],
        capture_output=True, text=True
    )
    rule_count = int(result.stdout.strip())
    print(f"AGENTS.md 자동 룰: {rule_count}개 (기준: ≥ 10개)")
    assert rule_count >= 10, f"룰 부족: {rule_count}개"

def measure_api_p95(base_url: str):
    latencies = []
    for _ in range(100):
        start = time.time()
        httpx.get(f"{base_url}/health")
        latencies.append((time.time() - start) * 1000)
    latencies.sort()
    p95 = latencies[int(len(latencies) * 0.95)]
    print(f"API p95 응답: {p95:.1f}ms (기준: < 500ms)")
    assert p95 < 500, f"API p95 초과: {p95:.1f}ms"

if __name__ == '__main__':
    conn = psycopg2.connect("postgresql://ada_user:ada_pass@localhost:5432/ada_db")
    measure_e2e_success_rate(conn)
    measure_agents_md_rules()
    measure_api_p95("http://localhost:8000")
    print("모든 KPI 검증 완료!")
```

### pytest 커버리지 실행 명령

```bash
# 전체 테스트 + 커버리지
pytest tests/ \
  --cov=agents \
  --cov=pipelines \
  --cov=harness \
  --cov=reports \
  --cov=shared \
  --cov-report=term-missing \
  --cov-report=html:htmlcov \
  --cov-fail-under=70 \
  -v \
  --tb=short \
  -n auto  # pytest-xdist 병렬 실행

# 에이전트 커버리지만 확인
pytest tests/test_agents/ --cov=agents --cov-fail-under=80

# 파이프라인 커버리지만 확인
pytest tests/test_pipelines/ --cov=pipelines --cov-fail-under=60
```

### 데모 시나리오 발표 대본 구조 (시나리오 1 예시)

```
[Slide 1] 표지
안녕하십니까. 오늘은 Adaptive AutoAI Pipeline Agent를 활용한 고객 이탈 예측 분석 결과를 말씀드리겠습니다.

[Slide 2] 데이터 개요
분석에 활용된 데이터는 총 10,000명의 고객 데이터로, 계약기간, 요금제, 월별 불만 횟수 등
12개 변수를 포함하고 있습니다. 전체 고객 중 약 18%가 이탈한 것으로 나타났습니다.

[Slide 3] EDA - 이탈률 분포
계약기간이 짧을수록 이탈률이 현저히 높게 나타났습니다.
특히 계약 1개월 미만 고객의 이탈률은 42%로, 전체 평균의 2.3배에 달합니다.

[Slide 4] EDA - 상관관계 분석
불만 횟수와 이탈 여부 간의 상관계수가 0.68로 가장 높게 나타났으며,
이는 고객 불만이 이탈의 핵심 선행 지표임을 시사합니다.

...

[Slide 10] 액션 아이템
첫째, 불만 횟수 2회 이상 고객에 대한 즉시 CS 연락 프로세스를 수립하십시오.
둘째, 계약기간 1개월 미만 신규 고객 대상 온보딩 프로그램을 강화하십시오.
셋째, 이 모델을 기반으로 매월 이탈 위험 고객 리스트를 CRM 시스템에 자동 반영하십시오.
감사합니다.
```

---

## 📁 생성/수정 파일 목록

| 경로 | 작업 | 설명 |
|------|------|------|
| `tests/test_e2e/test_pipeline.py` | 신규 생성 | 통합 테스트 25케이스 |
| `tests/test_agents/test_supervisor.py` | 신규 생성 | Supervisor 단위 테스트 |
| `tests/test_agents/test_data_profiler.py` | 신규 생성 | DataProfiler 단위 테스트 |
| `tests/test_agents/test_schema_validator.py` | 신규 생성 | SchemaValidator 단위 테스트 |
| `tests/test_agents/test_eval_agent.py` | 신규 생성 | EvalAgent 임계치 경계값 테스트 |
| `tests/test_agents/test_auditor.py` | 신규 생성 | Auditor proposed_rule 형식 검증 |
| `tests/test_pipelines/test_tabular_ml.py` | 신규 생성 | tabular_ml 파이프라인 테스트 |
| `tests/test_pipelines/test_timeseries.py` | 신규 생성 | timeseries 파이프라인 테스트 |
| `tests/test_pipelines/test_image.py` | 신규 생성 | image 파이프라인 테스트 |
| `tests/test_pipelines/test_nlp.py` | 신규 생성 | nlp 파이프라인 테스트 |
| `tests/test_pipelines/test_anomaly.py` | 신규 생성 | anomaly 파이프라인 테스트 |
| `tests/test_api/test_endpoints.py` | 신규 생성 | API 12개 엔드포인트 테스트 |
| `tests/acceptance/test_at1_titanic.py` | 신규 생성 | 인수 테스트 AT-1 |
| `tests/acceptance/test_at2_timeseries.py` | 신규 생성 | 인수 테스트 AT-2 |
| `tests/acceptance/test_at3_image.py` | 신규 생성 | 인수 테스트 AT-3 |
| `tests/acceptance/test_at4_nlp.py` | 신규 생성 | 인수 테스트 AT-4 |
| `tests/acceptance/test_at5_harness.py` | 신규 생성 | 인수 테스트 AT-5 (Self-Evolving) |
| `scripts/measure_kpi.py` | 신규 생성 | KPI 정량 측정 스크립트 |
| `docs/architecture.md` | 신규 생성 | 아키텍처/데이터 흐름 설계 문서 |
| `docs/demo_scripts/scenario_1_churn.md` | 신규 생성 | 데모 대본 시나리오 1 |
| `docs/demo_scripts/scenario_2_sales.md` | 신규 생성 | 데모 대본 시나리오 2 |
| `docs/demo_scripts/scenario_3_defect.md` | 신규 생성 | 데모 대본 시나리오 3 |
| `docs/demo_scripts/scenario_4_sentiment.md` | 신규 생성 | 데모 대본 시나리오 4 |
| `docs/demo_scripts/scenario_5_network.md` | 신규 생성 | 데모 대본 시나리오 5 |
| `.github/workflows/isolation_check.yml` | 수정 | pytest --cov 실행 확인 |

---

## 🔗 의존성 & 선행 조건

### Day 13까지 완료되어야 하는 항목

- 17개 에이전트 전체 구현 완료
- 6개 파이프라인 전체 구현 완료
- FastAPI 12개 엔드포인트 전체 구현 완료
- Docker Compose 전체 서비스 실행 가능 (PostgreSQL, Redis, MinIO, MLflow, FastAPI, Celery, Streamlit)
- AGENTS.md 기본 구조 존재

### 테스트 데이터 준비

```
tests/fixtures/
├── titanic.csv                  # 891행, AT-1용
├── monthly_sales.csv            # 36개월, AT-2용
├── cifar10_sample.zip           # 10클래스×100장, AT-3용
├── korean_reviews.csv           # 1,000행, AT-4용
├── noisy_tabular.csv            # 결측률 40%, AT-5용
└── small_tabular.csv            # 50행, 단위 테스트용
```

### Python 패키지 의존성 (테스트)

```
pytest>=8.2.0
pytest-asyncio>=0.23.6
pytest-cov>=5.0.0
pytest-xdist>=3.5.0
pytest-mock>=3.14.0
httpx>=0.27.0
locust>=2.29.0
```

---

## ✔️ 완료 기준 (Done Criteria)

- [ ] `pytest tests/test_agents/ --cov=agents --cov-fail-under=80` → PASS
- [ ] `pytest tests/test_pipelines/ --cov=pipelines --cov-fail-under=60` → PASS
- [ ] 인수 테스트 AT-1 ~ AT-5 모두 PASS
- [ ] E2E 성공률 ≥ 80% (KPI 스크립트 확인)
- [ ] AT-1 Titanic E2E ≤ 90초 (타이머 측정)
- [ ] AT-2 val_mape ≤ 0.30
- [ ] AT-3 val_accuracy ≥ 0.70
- [ ] AT-4 val_f1 ≥ 0.70
- [ ] AT-5 AGENTS.md 새 룰 R-A00X 추가 확인
- [ ] AGENTS.md 자동 룰 총 10개 이상 생성 (`grep -c "^### R-A" AGENTS.md` ≥ 10)
- [ ] 데모 시나리오 5종 서면 준비 완료 (`docs/demo_scripts/` 5개 파일)
- [ ] Swagger UI `/docs` 12개 엔드포인트 설명 완성 확인
- [ ] `isolation_check.yml` CI 모든 PR 통과 확인

---

## ⚠️ 주의사항 & 제약

1. **인수 테스트 실행 환경**: AT-1~AT-5는 반드시 Docker Compose 전체 서비스 실행 상태에서 수행.
2. **테스트 데이터 저작권**: Titanic, CIFAR-10은 공개 데이터셋이나 한국어 리뷰 데이터는 별도 수집 또는 합성 데이터 사용.
3. **병렬 테스트 격리**: `pytest-xdist` 사용 시 각 테스트가 고유한 `job_id`를 사용하도록 `faker` 또는 `uuid` 활용.
4. **AT 실행 시간**: AT-3(image), AT-4(nlp)는 GPU 없이 CPU만으로 실행 시 90초 초과 가능. GPU 환경 또는 `max_epochs=3` 제한으로 조정.
5. **AGENTS.md 버전 관리**: 테스트 실행 중 AGENTS.md 동시 수정 방지를 위해 AT-5는 단독 실행 권장.
6. **커버리지 제외 파일**: `__init__.py`, `conftest.py`, `scripts/` 디렉토리는 커버리지 측정 제외 (`.coveragerc` 설정).
7. **데모 시나리오 데이터 보안**: 실제 고객 데이터 대신 공개 데이터 또는 합성 데이터만 사용. 데모 환경에서 실 데이터 노출 금지.
8. **Self-Evolving 10룰 검증**: 스프린트 기간 중 실패 케이스가 충분하지 않을 경우, AT-5 반복 실행 또는 실패 케이스 시뮬레이션으로 룰 누적 가능.
9. **문서화 최종 검토**: 에이전트 README 17개는 코드 완성 후 실제 함수 시그니처와 일치 여부 최종 확인.
10. **CI isolation_check 최종**: 모든 PR 병합 전 `isolation_check.yml` 통과 필수. 직접 main 브랜치 push 금지.

---

## 🆕 v2 변경 사항

> v2 에서는 **Day14가 끝이 아니다**. Day14는 v1의 "기본 14일 작업이 끝나는 분기점"이며, Day15~Day21이 이어진다. 따라서 Day14의 KPI/인수 테스트는 **v1 기준 + v2 기본 골격** 까지만 검증한다. 풀스택 v2 검증은 Day20~Day21에서 수행.

### 1. Day14 v2 검증 범위 (필수)

- [ ] LangGraph v2 (25 노드) 컴파일 + 5게이트 PostgresSaver 체크포인트
- [ ] 인터랙티브 흐름 1회 E2E: 업로드 → G0 → G1 → G2 → G3 → G4 → G5 → 산출물 (mock proposers)
- [ ] 자체학습 KB INSERT 동작 + dataset_embedding 생성
- [ ] AutoErrorHandler 스텁이 BaseAgent try/except로 호출되는지 확인 (실제 패치 적용은 Day16 후)
- [ ] agent_registry **27개** INSERT + heartbeat 업데이트 동작 확인 (마스터 §4.1 합계표 권위)

### 2. Day14 → Day15 전환 핸드오프 체크리스트

- [ ] Day1~Day14의 v2 확장 섹션이 모두 완료됨을 PR 머지로 확인
- [ ] Day15~Day21 작업의 의존성 (DB v2 마이그레이션, 게이트 노드 등)이 모두 GREEN
- [ ] AGENTS.md v2 룰(R-401~R-799) 추가 PR 머지 완료
- [ ] 데모 시나리오 5종은 Day21에서 **5 카테고리 × 5 산출물** 매트릭스로 확장됨을 인지

### 3. KPI v1 시점 측정 (Day20에서 v2 KPI 재측정)

- [ ] 기존 KPI 7개 측정 + 기록 (스냅샷)
- [ ] v2 KPI 4개(KP7~KP11)는 Day20에서 정식 측정
