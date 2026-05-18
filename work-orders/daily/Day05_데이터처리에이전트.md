# Day 5 — 데이터 처리 에이전트
> 프로젝트: Adaptive AutoAI Pipeline Agent | 2주 스프린트 Day 5/14

---

## 📋 오늘의 목표

파이프라인의 첫 번째 관문인 `DataProfilerAgent`와 `SchemaValidatorAgent`를 완전히 구현한다. 데이터 프로파일러는 업로드된 CSV/Parquet/ZIP 파일을 MinIO에서 로딩하여 결측률·통계·기수성·메모리 사용량 등 상세 프로파일을 생성하고, 스키마 검증기는 6개 카테고리별 룰로 데이터 적합성을 판단한다. MinIO 공통 클라이언트(`tools/minio_tool.py`)도 완성하여 전체 팀이 재사용할 수 있도록 한다.

---

## 👤 담당자

- **C** 주도 (전체 작업)
- 코드 리뷰: A (에이전트 패턴 검토), B (시계열 분석 로직 검토)
- 단위 테스트 작성: C + D 협업

---

## ✅ 작업 목록

### 1. agents/data_profiler.py 구현

- [ ] `DataProfilerAgent(BaseAgent)` 클래스 작성
- [ ] `__call__(self, state: PipelineState) -> PipelineState` 구현:
  1. `MinIOClient.load_file(state.file_id, format=state.category)` 로 DataFrame 로딩
  2. `_profile_dataframe(df)` 호출하여 기본 프로파일 생성
  3. `state.category == "timeseries"` 시 `_analyze_timeseries(df, state.target_column)` 추가 호출
  4. `data_profile` 키에 병합된 결과 저장
  5. `state.model_copy(update={"data_profile": profile, "next_agent": "schema_validator"})` 반환

- [ ] `_profile_dataframe(self, df: pd.DataFrame) -> dict` 구현:
  ```python
  # 반환 구조
  {
      "rows": int,               # 행 수
      "cols": int,               # 열 수
      "columns": list[str],      # 컬럼명 목록
      "dtypes": dict,            # {컬럼명: dtype_str}
      "missing": dict,           # {컬럼명: 결측률(0.0~1.0)}
      "numeric_stats": dict,     # {컬럼명: {mean, std, min, max, p25, p75}}
      "cardinality": dict,       # {컬럼명: unique 수}
      "memory_mb": float,        # 데이터프레임 메모리 사용량(MB)
      "sample_rows": list[dict], # 상위 5개 행 (미리보기)
      "has_target": bool,        # target_column 존재 여부
      "target_dtype": str,       # target 컬럼 dtype
      "class_distribution": dict # 분류 시 클래스별 비율
  }
  ```
  - `df.dtypes` → string 변환 (JSON 직렬화 가능하도록)
  - 결측률: `df.isnull().mean()` 컬럼별 계산
  - numeric_stats: `df.describe().to_dict()` 에서 추출 (수치형만)
  - 기수성(cardinality): `df.nunique()` 컬럼별 계산
  - 메모리: `df.memory_usage(deep=True).sum() / 1024**2`

- [ ] `_analyze_timeseries(self, df: pd.DataFrame, target_col: str) -> dict` 구현:
  ```python
  # 반환 구조
  {
      "stationarity": {
          "adf_statistic": float,
          "adf_p_value": float,
          "is_stationary": bool    # p_value < 0.05
      },
      "seasonality": {
          "has_seasonality": bool,
          "period": Optional[int]
      },
      "trend": {
          "has_trend": bool,
          "direction": str          # "increasing" | "decreasing" | "none"
      },
      "date_col": str,              # 날짜 컬럼명 (자동 감지)
      "freq": str                   # 감지된 주기 (D/W/M/H 등)
  }
  ```
  - ADF 검정: `statsmodels.tsa.stattools.adfuller(series.dropna())`
  - 계절성 분해: `statsmodels.tsa.seasonal.seasonal_decompose(series, model="additive")`
  - 날짜 컬럼 자동 감지: dtype이 `datetime64` 이거나 컬럼명에 `date/time/ts` 포함
  - 예외 처리: 시계열 분석 실패 시 `{"error": str(e)}` 반환 (파이프라인 중단 방지)

- [ ] `_detect_category(self, df, filename) -> str` 구현:
  - filename 확장자가 `.jpg/.png/.zip` → `image`
  - text 컬럼(dtype=object, cardinality > rows * 0.8) 존재 시 → `nlp`
  - datetime 컬럼 존재 시 → `timeseries` 후보
  - 그 외 → `tabular_ml`

### 2. agents/schema_validator.py 구현

- [ ] `SchemaValidatorAgent(BaseAgent)` 클래스 작성
- [ ] `CATEGORY_RULES: dict` 정의 — 6개 카테고리별 검증 룰:
  ```python
  CATEGORY_RULES = {
      "tabular_ml": {
          "min_rows": 100,
          "max_cols": 1000,
          "requires_target": True,
          "min_target_classes": 2,
      },
      "tabular_dl": {
          "min_rows": 1000,
          "max_cols": 1000,
          "requires_target": True,
      },
      "timeseries": {
          "min_rows": 50,
          "requires_target": True,
          "requires_date_col": True,
      },
      "image": {
          "min_files": 50,
          "supported_formats": [".jpg", ".jpeg", ".png", ".bmp", ".tiff"],
      },
      "nlp": {
          "min_rows": 100,
          "requires_text_col": True,
          "min_avg_text_length": 10,
      },
      "anomaly": {
          "min_rows": 500,
          "requires_target": False,
      },
  }
  ```

- [ ] `__call__(self, state: PipelineState) -> PipelineState` 구현:
  1. `CATEGORY_RULES[state.category]` 로드
  2. `_validate(state.data_profile, rules)` 호출
  3. validation 결과를 `state.validation` 에 저장
  4. `is_valid=False` 시 `next_agent="error_recovery"`, `error="Validation failed: ..."` 설정
  5. `is_valid=True` 시 `next_agent="preprocessing_strategist"` 설정

- [ ] `_validate(self, profile: dict, rules: dict) -> dict` 구현:
  ```python
  def _validate(self, profile, rules) -> dict:
      errors = []
      warnings = []
      
      # rows 검사
      if "min_rows" in rules and profile["rows"] < rules["min_rows"]:
          errors.append(f"행 수 부족: {profile['rows']} < {rules['min_rows']}")
      
      # 컬럼 수 검사
      if "max_cols" in rules and profile["cols"] > rules["max_cols"]:
          errors.append(f"컬럼 수 초과: {profile['cols']} > {rules['max_cols']}")
      
      # target 컬럼 필수 검사
      if rules.get("requires_target") and not profile.get("has_target"):
          errors.append("target_column 지정 필수")
      
      # 날짜 컬럼 검사 (timeseries)
      if rules.get("requires_date_col") and not profile.get("date_col"):
          errors.append("시계열 카테고리: 날짜 컬럼 필수")
      
      # 텍스트 컬럼 검사 (nlp)
      if rules.get("requires_text_col") and not profile.get("text_col"):
          errors.append("NLP 카테고리: 텍스트 컬럼 필수")
      
      # 결측률 50% 초과 컬럼 경고
      for col, missing_rate in profile.get("missing", {}).items():
          if missing_rate > 0.5:
              warnings.append(f"컬럼 '{col}' 결측률 {missing_rate:.1%} — 제거 권장")
      
      return {
          "is_valid": len(errors) == 0,
          "errors": errors,
          "warnings": warnings,
      }
  ```

- [ ] `_detect_text_col(self, profile: dict) -> Optional[str]` 구현:
  - dtype=object 컬럼 중 평균 길이가 `min_avg_text_length` 초과인 컬럼 반환

### 3. tools/minio_tool.py 구현

- [ ] `MinIOClient` 클래스 작성 (boto3 기반, 싱글턴 패턴)
- [ ] `__init__` 에서 `boto3.client("s3", endpoint_url=..., aws_access_key_id=..., aws_secret_access_key=...)` 초기화
- [ ] `upload_file(self, local_path: str, object_name: str) -> str` 구현:
  - `s3.upload_file(local_path, BUCKET, object_name)`
  - 반환값: `f"s3://{BUCKET}/{object_name}"`
  - 업로드 실패 시 3회 재시도 (exponential backoff)

- [ ] `load_file(self, object_name: str, format: str = "csv") -> pd.DataFrame` 구현:
  ```python
  # 지원 형식
  # CSV: pd.read_csv(BytesIO(body))
  # Parquet: pd.read_parquet(BytesIO(body))
  # ZIP: ZipFile(BytesIO(body)) → 내부 CSV 추출
  ```
  - `s3.get_object(Bucket=BUCKET, Key=object_name)["Body"].read()` 로 바이트 로딩
  - 자동 인코딩 감지: chardet 사용 (UTF-8 실패 시)

- [ ] `save_model(self, model_obj: Any, object_name: str) -> str` 구현:
  - `joblib.dump(model_obj, tmp_file)` 후 MinIO 업로드
  - 반환값: MinIO 경로 문자열

- [ ] `save_artifact(self, local_path: str, artifact_type: str, job_id: str) -> str` 구현:
  - object_name 자동 생성: `f"{artifact_type}/{job_id}/{Path(local_path).name}"`
  - `upload_file()` 호출 후 경로 반환

- [ ] `save_dataframe(self, df: pd.DataFrame, object_name: str, format: str = "parquet") -> str` 구현:
  - Parquet 형식 기본 저장 (압축률 및 타입 보존)
  - `df.to_parquet(BytesIO())` 후 MinIO 업로드

- [ ] `list_objects(self, prefix: str) -> list[str]` 구현:
  - `s3.list_objects_v2(Bucket=BUCKET, Prefix=prefix)` 결과 파싱

- [ ] `get_presigned_url(self, object_name: str, expiry: int = 3600) -> str` 구현:
  - `s3.generate_presigned_url("get_object", ...)` 반환

- [ ] `BUCKET = settings.minio_bucket` 클래스 상수 정의

### 4. 단위 테스트 작성

- [ ] `tests/agents/test_data_profiler.py` 작성:
  - Titanic CSV 데이터 사용 (pytest fixture)
  - `_profile_dataframe()` 반환 키 검증
  - 결측률 계산 정확도 검증
  - 시계열 감지 테스트 (AirPassengers 데이터)
  - MinIO mock (moto 라이브러리 사용)

- [ ] `tests/agents/test_schema_validator.py` 작성:
  - 6개 카테고리별 CATEGORY_RULES 존재 확인
  - `min_rows` 미달 시 `is_valid=False` 반환 확인
  - 결측률 50% 초과 컬럼 warnings 포함 확인
  - `target_column` 없는 tabular_ml 오류 확인

- [ ] `tests/tools/test_minio_tool.py` 작성:
  - moto S3 모킹으로 `upload_file`, `load_file` 테스트
  - CSV, Parquet 형식 로딩 테스트

---

## 🏗️ 구현 명세

### agents/data_profiler.py 핵심 코드 구조

```python
# agents/data_profiler.py
import pandas as pd
import numpy as np
from typing import Optional
from agents.base import BaseAgent
from shared.state import PipelineState
from tools.minio_tool import MinIOClient
from shared.logger import get_logger

logger = get_logger("DataProfilerAgent")


class DataProfilerAgent(BaseAgent):
    """데이터 프로파일링 에이전트 — 통계 분석 및 메타데이터 추출"""

    def __call__(self, state: PipelineState) -> PipelineState:
        with self.log_agent_run(state):
            minio = MinIOClient()
            df = minio.load_file(state.file_id)

            profile = self._profile_dataframe(df)

            if state.category == "timeseries" and state.target_column:
                ts_info = self._analyze_timeseries(df, state.target_column)
                profile.update({"timeseries": ts_info})

            return state.model_copy(update={
                "data_profile": profile,
                "next_agent": "schema_validator",
            })

    def _profile_dataframe(self, df: pd.DataFrame) -> dict:
        numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
        numeric_stats = {}
        for col in numeric_cols:
            s = df[col]
            numeric_stats[col] = {
                "mean": float(s.mean()),
                "std": float(s.std()),
                "min": float(s.min()),
                "max": float(s.max()),
                "p25": float(s.quantile(0.25)),
                "p75": float(s.quantile(0.75)),
            }

        return {
            "rows": len(df),
            "cols": len(df.columns),
            "columns": df.columns.tolist(),
            "dtypes": {col: str(dtype) for col, dtype in df.dtypes.items()},
            "missing": {col: float(rate) for col, rate in df.isnull().mean().items()},
            "numeric_stats": numeric_stats,
            "cardinality": {col: int(n) for col, n in df.nunique().items()},
            "memory_mb": round(df.memory_usage(deep=True).sum() / 1024**2, 3),
            "sample_rows": df.head(5).to_dict(orient="records"),
        }

    def _analyze_timeseries(self, df: pd.DataFrame, target_col: str) -> dict:
        try:
            from statsmodels.tsa.stattools import adfuller
            from statsmodels.tsa.seasonal import seasonal_decompose

            series = df[target_col].dropna()

            # ADF 정상성 검정
            adf_result = adfuller(series)
            adf_p_value = float(adf_result[1])

            # 계절성 분해 (최소 2주기 이상 필요)
            has_seasonality = False
            period = None
            if len(series) >= 24:
                try:
                    decomp = seasonal_decompose(series, model="additive", period=12)
                    seasonal_strength = decomp.seasonal.std() / series.std()
                    has_seasonality = seasonal_strength > 0.1
                    period = 12 if has_seasonality else None
                except Exception:
                    pass

            return {
                "stationarity": {
                    "adf_statistic": float(adf_result[0]),
                    "adf_p_value": adf_p_value,
                    "is_stationary": adf_p_value < 0.05,
                },
                "seasonality": {
                    "has_seasonality": has_seasonality,
                    "period": period,
                },
                "trend": {
                    "has_trend": True,
                    "direction": "increasing" if series.diff().mean() > 0 else "decreasing",
                },
            }
        except Exception as e:
            return {"error": str(e)}
```

### tools/minio_tool.py 핵심 코드 구조

```python
# tools/minio_tool.py
import boto3
import joblib
import pandas as pd
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile
from typing import Any
from shared.config import settings

BUCKET = settings.minio_bucket


class MinIOClient:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init_client()
        return cls._instance

    def _init_client(self):
        self.s3 = boto3.client(
            "s3",
            endpoint_url=f"http://{settings.minio_endpoint}",
            aws_access_key_id=settings.minio_access_key,
            aws_secret_access_key=settings.minio_secret_key,
        )

    def upload_file(self, local_path: str, object_name: str) -> str:
        self.s3.upload_file(local_path, BUCKET, object_name)
        return f"s3://{BUCKET}/{object_name}"

    def load_file(self, object_name: str, format: str = "csv") -> pd.DataFrame:
        body = self.s3.get_object(Bucket=BUCKET, Key=object_name)["Body"].read()

        if format == "parquet" or object_name.endswith(".parquet"):
            return pd.read_parquet(BytesIO(body))
        elif object_name.endswith(".zip"):
            with ZipFile(BytesIO(body)) as z:
                csv_files = [f for f in z.namelist() if f.endswith(".csv")]
                return pd.read_csv(z.open(csv_files[0]))
        else:
            return pd.read_csv(BytesIO(body))

    def save_model(self, model_obj: Any, object_name: str) -> str:
        buf = BytesIO()
        joblib.dump(model_obj, buf)
        buf.seek(0)
        self.s3.put_object(Bucket=BUCKET, Key=object_name, Body=buf.getvalue())
        return f"s3://{BUCKET}/{object_name}"

    def save_artifact(self, local_path: str, artifact_type: str, job_id: str) -> str:
        fname = Path(local_path).name
        object_name = f"{artifact_type}/{job_id}/{fname}"
        return self.upload_file(local_path, object_name)

    def save_dataframe(self, df: pd.DataFrame, object_name: str,
                       format: str = "parquet") -> str:
        buf = BytesIO()
        if format == "parquet":
            df.to_parquet(buf, index=False)
        else:
            df.to_csv(buf, index=False)
        buf.seek(0)
        self.s3.put_object(Bucket=BUCKET, Key=object_name, Body=buf.getvalue())
        return f"s3://{BUCKET}/{object_name}"
```

### tests/agents/test_data_profiler.py 구조

```python
# tests/agents/test_data_profiler.py
import pytest
import pandas as pd
from unittest.mock import patch, MagicMock
from agents.data_profiler import DataProfilerAgent
from shared.state import PipelineState


@pytest.fixture
def titanic_df():
    return pd.read_csv("tests/fixtures/titanic.csv")


@pytest.fixture
def sample_state():
    return PipelineState(
        job_id="test-job-001",
        file_id="uploads/titanic.csv",
        category="tabular_ml",
        task="classification",
        target_column="Survived",
    )


class TestDataProfilerAgent:
    def test_profile_keys(self, titanic_df):
        agent = DataProfilerAgent()
        profile = agent._profile_dataframe(titanic_df)
        required_keys = ["rows", "cols", "columns", "dtypes", "missing",
                         "numeric_stats", "cardinality", "memory_mb"]
        for key in required_keys:
            assert key in profile

    def test_missing_rate_calculation(self, titanic_df):
        agent = DataProfilerAgent()
        profile = agent._profile_dataframe(titanic_df)
        # Age 컬럼은 결측 있음
        assert 0 < profile["missing"]["Age"] < 1

    @patch("agents.data_profiler.MinIOClient")
    def test_call_returns_updated_state(self, mock_minio, titanic_df, sample_state):
        mock_minio.return_value.load_file.return_value = titanic_df
        agent = DataProfilerAgent()
        result = agent(sample_state)
        assert result.data_profile is not None
        assert result.next_agent == "schema_validator"
```

---

## 📁 생성/수정 파일 목록

```
프로젝트 루트/
├── agents/
│   ├── data_profiler.py                # DataProfilerAgent 구현
│   └── schema_validator.py             # SchemaValidatorAgent 구현
├── tools/
│   └── minio_tool.py                   # MinIOClient (boto3 기반)
└── tests/
    ├── fixtures/
    │   └── titanic.csv                 # 테스트용 Titanic 데이터
    ├── agents/
    │   ├── test_data_profiler.py
    │   └── test_schema_validator.py
    └── tools/
        └── test_minio_tool.py
```

---

## 🔗 의존성 & 선행 조건

- **Day 3 완료 필수**: `agents/base.py`, `shared/state.py`, `shared/config.py` 완성
- **Day 4 완료 필수**: `orchestrator/graph.py` 에서 `data_profiler`, `schema_validator` 노드 등록
- statsmodels 설치 확인 (`pip show statsmodels`)
- boto3 설치 확인 (`pip show boto3`)
- joblib 설치 확인 (`pip show joblib`)
- moto 설치 확인 (`pip show moto`) — 단위 테스트용 S3 모킹
- chardet 설치 확인 (`pip show chardet`) — 인코딩 자동 감지
- MinIO 컨테이너 healthy 상태 및 `autoai-artifacts` 버킷 존재 확인

---

## ✔️ 완료 기준 (Done Criteria)

- [ ] `pytest tests/agents/test_data_profiler.py -v` 전체 통과
- [ ] `pytest tests/agents/test_schema_validator.py -v` 전체 통과
- [ ] `pytest tests/tools/test_minio_tool.py -v` 전체 통과
- [ ] `DataProfilerAgent().CATEGORY_RULES` 존재하지 않음 (SchemaValidator에 있음) — 분리 확인
- [ ] `SchemaValidatorAgent.CATEGORY_RULES` 6개 카테고리 키 존재 확인
- [ ] Titanic CSV 기준 DataProfilerAgent 실행 결과: `rows=891`, `cols=12` 확인
- [ ] 결측률 50% 초과 컬럼(`Cabin`) → SchemaValidator에서 warning 포함 확인
- [ ] `MinIOClient()` 싱글턴 패턴 확인: 두 번 인스턴스화 시 동일 객체 반환

---

## ⚠️ 주의사항 & 제약

### AGENTS.md 룰 (Day 5 적용)

- **R-101**: MinIO 저장 경로는 `{category}/{job_id}/{파일명}` 형식 고정. 임의 경로 생성 금지
- **R-102**: 사용자 업로드 파일 내용을 로그에 출력하지 않음 (개인정보 포함 가능)
- **R-103**: `load_file()` 에서 인코딩 오류 시 UTF-8 → latin-1 순서로 폴백 시도

### 아키텍처 제약

- `DataProfilerAgent` 는 LLM을 호출하지 않는 룰 기반 에이전트 (`_call_llm()` 미사용)
- `SchemaValidatorAgent` 는 LLM을 호출하지 않는 룰 기반 에이전트
- MinIOClient 싱글턴 패턴 유지 (Celery 워커 내 커넥션 재사용)
- 대용량 파일(>50MB) 처리 시 `pd.read_csv(chunksize=...)` 또는 Parquet 사용 권장
- 시계열 분석(`_analyze_timeseries`) 실패 시 예외를 삼키고 `{"error": str(e)}` 반환 — 파이프라인 중단 방지

### 테스트 데이터 규칙

- 테스트 fixture는 `tests/fixtures/` 디렉토리에만 저장
- 실제 사용자 데이터를 테스트 fixture로 사용 금지 (개인정보 보호)
- 대용량 테스트 데이터(>1MB)는 Git LFS 또는 pytest 다운로드 fixture 사용

### 성능 주의사항

- `_profile_dataframe()` 은 동기 처리. 100MB 이상 파일 시 프로파일링 시간 증가 (10초 이상 예상)
- 카디널리티 계산(`nunique()`)은 고카디널리티 컬럼에서 메모리 집약적 — 1M+ rows 시 샘플링 고려
- `memory_usage(deep=True)` 는 실제 메모리를 정확히 측정하나 느릴 수 있음 → 대용량 시 `deep=False`

---

## 🆕 v2 확장 작업 (마스터 설계서 §1.2 · §10.3)

> v1 은 csv/parquet/zip 중심이었으나 v2는 **xlsx · json · pdf · txt · html · 이미지 · 음성**까지 모두 처리해야 한다. 또한 데이터 진입 직후 **PII 스캔 + 미니 게이트**를 발동한다.

### 1. 멀티 포맷 로더 확장 (`tools/loaders/`)

- [ ] `tools/loaders/__init__.py` — 디스패처: 확장자/MIME으로 적절한 로더 선택
- [ ] `tools/loaders/csv_loader.py` — chardet 인코딩 감지 + 구분자 자동 추론
- [ ] `tools/loaders/xlsx_loader.py` — `openpyxl` 기반 다중 시트 처리. 각 시트를 DataFrame 으로 반환하거나 사용자가 G0 단계에서 시트 선택
- [ ] `tools/loaders/json_loader.py` — JSON Lines / 중첩 JSON 모두. 중첩일 때 `pd.json_normalize` 자동 적용
- [ ] `tools/loaders/pdf_loader.py` — `pypdf` + `pdfplumber` 폴백. 텍스트 추출 + 표 탐지 (Camelot/Tabula)
- [ ] `tools/loaders/txt_loader.py` — 라인 단위 분할, 인코딩 자동 감지
- [ ] `tools/loaders/html_loader.py` — BeautifulSoup 으로 `<table>` 추출 + 텍스트 추출
- [ ] `tools/loaders/image_loader.py` — 단일 이미지 / ZIP / 디렉토리 모두 지원. EXIF 메타데이터 추출
- [ ] `tools/loaders/audio_loader.py` — `librosa` 로 wav/mp3 로딩, MFCC 추출 (옵션, 음성 카테고리)
- [ ] `MinIOClient.load_file` 확장: 위 로더 디스패처 사용

### 2. 자동 카테고리 추론 강화

`DataProfilerAgent._detect_category` 확장:

- xlsx + 시계열 시그니처 → `timeseries`
- pdf/html/txt → 텍스트 추출 후 `nlp`
- 이미지 ZIP/디렉토리 → `image`
- 음성 → `audio` (신규 카테고리, v2 옵션)
- json 중첩 → `tabular_ml` (평탄화 후)

### 3. PII 스캔 + 미니 게이트 (G0의 일부)

- [ ] `DataProfilerAgent` 안에서 `SecurityGuard.scan_pii(df)` 호출 (Day03에서 만든 모듈)
- [ ] PII 컬럼 발견 시:
  ```python
  state.pii_columns = ["email", "phone"]
  state.awaiting_decision = "G0_PII"
  # 그래프 일시정지 → 사용자에게 마스킹/제거/유지 선택 묻기
  ```
- [ ] 사용자 응답을 `pii_mask_policy` 로 받아 `FeatureEngineerAgent` 가 적용

### 4. 데이터 프로파일 v2 — 자체학습 KB 임베딩

- [ ] `_profile_dataframe` 결과를 자연어 요약으로 압축 (`_summarize_profile_for_embedding`):
  ```python
  summary_text = f"""
  카테고리: {category}, 행 {rows}, 열 {cols}.
  수치형 {n_num}, 범주형 {n_cat}, 텍스트 {n_text}.
  주요 컬럼: {top_columns}.
  결측률 평균: {avg_missing:.1%}.
  타겟 분포: {target_summary}.
  """
  ```
- [ ] 임베딩 → `dataset_embeddings` 테이블에 저장 (sentence-transformers/all-mpnet-base-v2)
- [ ] G1 단계에서 `SelfLearningClient.fetch_similar_cases(intent_emb + profile_emb)` 로 검색

### 5. 보안 가드 통합

- [ ] 업로드 파일에 대해 `python-magic` 으로 실제 MIME 검증 (확장자 위조 방지)
- [ ] zip bomb 방어: 압축 해제 전 압축률·내부 파일 개수 상한 (1000개) 확인
- [ ] `tools/loaders/safe_unzip.py` 유틸 작성

### 6. 완료 기준 (v2 추가)

- [ ] `pytest tests/tools/test_loaders.py` — 8개 포맷 모두 통과
- [ ] PII 컬럼 포함 데이터 업로드 후 `state.awaiting_decision == 'G0_PII'` 발동 확인
- [ ] 임의 잡 종료 후 `SELECT count(*) FROM dataset_embeddings;` ≥ 1
- [ ] zip bomb 테스트 파일 업로드 시 413 또는 422 응답

### 7. 주의사항 (v2)

- pdf 로더에서 추출된 텍스트는 OCR 미적용 (스캔 PDF는 별도 경로 — Day12에서 OCR 옵션)
- 임베딩 생성은 CPU도 가능하나 GPU 있으면 6배 빠름
- xlsx 다중 시트는 사용자가 시트 선택할 때까지 모든 시트 메타만 보여줌
