# Day 10 — 전처리 + EDA 에이전트 + Streamlit UI
> 프로젝트: Adaptive AutoAI Pipeline Agent | 2주 스프린트 Day 10/14

---

## 📋 오늘의 목표

사용자 데이터가 파이프라인에 진입한 직후 수행되는 **전처리 전략 수립 → 피처 엔지니어링 실행 → EDA 시각화** 3단계를 완성한다.
PreprocessingStrategistAgent가 LLM으로 카테고리별 맞춤 전처리 계획을 수립하고,
FeatureEngineerAgent가 결정론적으로 계획을 실행하며,
EDAAgent가 카테고리별 시각화 차트를 MinIO에 저장한다.
병행하여 Streamlit 기반 사용자 UI를 구현한다.

- PreprocessingStrategist: Claude Sonnet 4.6 기반 전처리 계획 수립
- FeatureEngineer: sklearn 파이프라인 기반 결정론적 실행
- EDAAgent: Plotly 기반 5종 시각화
- Streamlit UI: 파일 업로드 → 파이프라인 시작 → 실시간 진행 표시

---

## 👤 담당자

- **D**: PreprocessingStrategistAgent, FeatureEngineerAgent, EDAAgent
- **A**: Streamlit UI (`ui/app.py`)

---

## ✅ 작업 목록

### 1. PreprocessingStrategistAgent 구현 (D)

- [ ] `agents/preprocessing_strategist.py` 파일 생성
  - `PreprocessingStrategistAgent(BaseAgent)` 클래스 정의
  - LLM 사용: Claude Sonnet 4.6
  - **STRATEGIST_PROMPT 정의:**
    ```
    당신은 데이터 전처리 전략 전문가입니다.
    아래 데이터 프로파일을 분석하여 최적의 전처리 단계를 순서대로 계획하세요.
    반드시 JSON 배열 형식으로만 응답하세요:
    [
      {
        "step": "단계명 (handle_missing/encode_categorical/scale_numeric/handle_outliers/
                  text_tokenize/image_normalize/timeseries_detrend/feature_creation 중 택1)",
        "method": "구체적 방법명",
        "params": {"파라미터명": 값},
        "applies_to": ["적용 컬럼 또는 데이터 타입 리스트"]
      }
    ]
    ```
  - **처리 단계 8종:**
    1. `handle_missing`: 결측값 처리
    2. `encode_categorical`: 범주형 인코딩
    3. `scale_numeric`: 수치형 스케일링
    4. `handle_outliers`: 이상치 처리
    5. `text_tokenize`: 텍스트 토크나이징
    6. `image_normalize`: 이미지 정규화
    7. `timeseries_detrend`: 시계열 추세 제거
    8. `feature_creation`: 파생 변수 생성
  - `load_skill(state.category, 'preprocessing')` 으로 도메인 컨텍스트 주입
  - 카테고리별 기본 전략 분기:
    - `tabular_ml`, `anomaly_detection`: handle_missing → encode_categorical → scale_numeric → handle_outliers
    - `timeseries`: handle_missing → timeseries_detrend → scale_numeric
    - `image`: image_normalize → (augmentation은 학습 시)
    - `nlp`: handle_missing → text_tokenize
    - `tabular_dl`: handle_missing → encode_categorical → scale_numeric
  - 출력: `list[dict]` 형식, `state.preprocessing_plan`에 저장

### 2. FeatureEngineerAgent 구현 (D)

- [ ] `agents/feature_engineer.py` 파일 생성
  - `FeatureEngineerAgent(BaseAgent)` 클래스 정의
  - LLM 미사용: `use_llm = False`
  - `state.preprocessing_plan` 리스트를 순서대로 실행
  - **단계별 구현:**

  - `handle_missing`:
    - `method='knn'` → `KNNImputer(n_neighbors=5)` (수치형)
    - `method='median'` → `SimpleImputer(strategy='median')` (수치형)
    - `method='most_frequent'` → `SimpleImputer(strategy='most_frequent')` (범주형)
    - `method='drop_column'` → 결측률 50% 초과 컬럼 제거

  - `encode_categorical`:
    - `method='ordinal'` → `OrdinalEncoder(handle_unknown='use_encoded_value', unknown_value=-1)`
    - `method='onehot'` → `OneHotEncoder(max_categories=50, handle_unknown='ignore', sparse_output=False)`
    - 고카디널리티 (unique > 50) → Target Encoding 또는 Hash Encoding

  - `scale_numeric`:
    - `method='standard'` → `StandardScaler()`
    - `method='minmax'` → `MinMaxScaler()`
    - `method='robust'` → `RobustScaler()` (이상치 많은 경우)

  - `handle_outliers`:
    - `method='iqr_clip'` → IQR 방식 (Q1-1.5*IQR, Q3+1.5*IQR 범위로 clip)
    - `method='isolation_forest'` → `IsolationForest(contamination=0.05)` 이상치 행 제거

  - `text_tokenize`:
    - `transformers.AutoTokenizer.from_pretrained(model_name)` 활용
    - 한국어: `'klue/bert-base'`, 영어: `'bert-base-uncased'`
    - `max_length=128`, `padding='max_length'`, `truncation=True`

  - `image_normalize`:
    - `torchvision.transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225])`
    - Resize to (224, 224)

  - `timeseries_detrend`:
    - Linear detrend: `scipy.signal.detrend(series)`
    - 계절성 분해: `statsmodels.tsa.seasonal.seasonal_decompose(series, period=12)`

  - `feature_creation`:
    - 날짜 컬럼 → 연/월/일/요일/시간 파생 변수
    - 수치형 조합: 교호작용 특성 (상위 상관 컬럼 쌍)

  - **데이터 분할:** 학습:검증 = 8:2
    - `train_test_split(X, y, test_size=0.2, random_state=42, stratify=y)` (분류)
    - `train_test_split(X, y, test_size=0.2, random_state=42)` (회귀/기타)
  - 전처리 완료 데이터 MinIO 저장: `minio_tool.save_file(data_dict, f"preprocessed/{job_id}.pkl")`
  - `state.preprocessed_data_id` 설정

### 3. EDAAgent 구현 (D)

- [ ] `agents/eda_agent.py` 파일 생성
  - `EDAAgent(BaseAgent)` 클래스 정의
  - LLM 미사용: `use_llm = False`
  - 카테고리별 시각화 로직 분기:

  - **tabular_ml / tabular_dl / anomaly_detection:**
    - 수치형 컬럼 히스토그램 (최대 5개): `plotly.express.histogram(df, x=col, nbins=30)`
    - 상관관계 히트맵: `plotly.express.imshow(df.corr(), color_continuous_scale='RdBu')`
    - 타겟 분포: `plotly.express.pie(df, names=target_col)` (분류) / `plotly.express.box(df, y=target_col)` (회귀)

  - **timeseries / forecasting:**
    - 시계열 라인 차트: `plotly.express.line(df, x=index_col, y=target_col)`
    - 이동 평균 오버레이: `rolling(window=30).mean()` 추가
    - 자기상관 함수 (ACF): `statsmodels.graphics.tsaplots.plot_acf`

  - **image:**
    - 클래스별 샘플 이미지 격자: PIL 이미지 로드 후 `plotly.figure_factory.create_annotated_heatmap` 또는 subplot grid
    - 클래스 분포 막대 그래프: `plotly.express.bar`
    - 이미지 크기 분포: `plotly.express.scatter(width vs height)`

  - **nlp:**
    - 텍스트 길이 분포: `plotly.express.histogram(df, x='text_length')`
    - 상위 단어 빈도: `Counter(words).most_common(20)` → `plotly.express.bar`
    - 감성/클래스별 텍스트 길이 비교: `plotly.express.box(df, x=target_col, y='text_length')`

  - 모든 차트: PNG 파일로 변환 (`fig.write_image(f"{chart_name}.png", scale=2)`)
  - MinIO 저장: `minio_tool.save_file(png_bytes, f"eda/{job_id}/{chart_name}.png")`
  - `state.eda_charts` 리스트에 MinIO 경로 추가

### 4. Streamlit UI 구현 (A)

- [ ] `ui/app.py` 파일 생성
  - **페이지 레이아웃:**
    - `st.set_page_config(page_title="ADA - AutoAI Pipeline", layout="wide")`
    - 좌측 사이드바: 설정 옵션
    - 메인: 파일 업로드 + 진행 상황 + 결과

  - **파일 업로드 섹션:**
    - `st.file_uploader("데이터 파일 업로드", type=['csv', 'parquet', 'zip', 'txt'], accept_multiple_files=False)`
    - 최대 100MB 제한 (`config.toml` 설정: `server.maxUploadSize = 100`)
    - 업로드 후 미리보기: `st.dataframe(df.head(10))`

  - **파이프라인 설정 섹션:**
    - `st.selectbox("분석 카테고리", options=['tabular_ml', 'timeseries', 'image', 'nlp', 'anomaly_detection', 'tabular_dl'])`
    - `st.text_input("타겟 컬럼명 (선택사항)", placeholder="target")`
    - `st.text_input("분석 질문 (선택사항)", placeholder="어떤 인사이트가 필요하신가요?")`
    - `st.slider("최대 재시도 횟수", min_value=1, max_value=5, value=3)`

  - **파이프라인 시작:**
    - `st.button("파이프라인 시작", type="primary")`
    - 클릭 시 POST `/jobs` API 호출, `job_id` 획득
    - `st.session_state['job_id'] = job_id`

  - **실시간 진행 상황:**
    - WebSocket 연결: `websocket.connect(f"ws://api/pipeline/ws/{job_id}")`
    - `st.progress(progress_pct)` 진행 바
    - `st.info(f"현재 실행 중: {current_agent}")` 에이전트 표시
    - `st.empty()` 컨테이너로 동적 업데이트

  - **결과 및 다운로드:**
    - 완료 후 EDA 차트 미리보기: `st.image(chart_path)`
    - 인사이트 텍스트: `st.markdown(state.insights)`
    - 다운로드 버튼:
      - `st.download_button("PPT 다운로드", data=ppt_bytes, file_name="report.pptx")`
      - `st.download_button("PDF 다운로드", data=pdf_bytes, file_name="report.pdf")`
      - `st.download_button("모델 다운로드", data=model_bytes, file_name="model.pkl")`

---

## 🏗️ 구현 명세

### PreprocessingStrategistAgent 핵심 구조

```python
class PreprocessingStrategistAgent(BaseAgent):
    llm_model = "claude-sonnet-4-6"

    STRATEGIST_PROMPT = """당신은 데이터 전처리 전략 전문가입니다.
아래 데이터 프로파일과 도메인 지식을 바탕으로 최적의 전처리 단계를 계획하세요.
반드시 JSON 배열 형식으로만 응답하세요.

도메인 지식:
{skill_context}

데이터 프로파일:
{data_profile}
"""

    def run(self, state: PipelineState) -> PipelineState:
        skill_context = skills_loader.load_skill(state.category, 'preprocessing')
        profile_str = json.dumps(state.data_profile, ensure_ascii=False, indent=2)
        prompt = self.STRATEGIST_PROMPT.format(
            skill_context=skill_context,
            data_profile=profile_str
        )
        response = llm_client.invoke(prompt, model=self.llm_model)
        plan = json.loads(response.content)
        state.preprocessing_plan = plan
        return state
```

### FeatureEngineerAgent 핵심 구조

```python
class FeatureEngineerAgent(BaseAgent):
    use_llm = False

    IMPUTERS = {
        'knn': lambda: KNNImputer(n_neighbors=5),
        'median': lambda: SimpleImputer(strategy='median'),
        'most_frequent': lambda: SimpleImputer(strategy='most_frequent'),
    }
    SCALERS = {
        'standard': StandardScaler,
        'minmax': MinMaxScaler,
        'robust': RobustScaler,
    }
    ENCODERS = {
        'ordinal': lambda: OrdinalEncoder(handle_unknown='use_encoded_value', unknown_value=-1),
        'onehot': lambda: OneHotEncoder(max_categories=50, handle_unknown='ignore', sparse_output=False),
    }

    def run(self, state: PipelineState) -> PipelineState:
        df = minio_tool.load_file(state.raw_data_id)
        X = df.drop(columns=[state.target_column])
        y = df[state.target_column]

        for step in state.preprocessing_plan:
            X = self._execute_step(step, X, y, state.category)

        X_train, X_val, y_train, y_val = train_test_split(
            X, y, test_size=0.2, random_state=42,
            stratify=y if state.category in ('classification', 'nlp') else None
        )
        data_dict = {'X_train': X_train, 'X_val': X_val, 'y_train': y_train, 'y_val': y_val}
        preprocessed_id = minio_tool.save_file(data_dict, f"preprocessed/{state.job_id}.pkl")
        state.preprocessed_data_id = preprocessed_id
        return state

    def _execute_step(self, step: dict, X, y, category: str):
        step_name = step['step']
        method = step['method']
        params = step.get('params', {})
        applies_to = step.get('applies_to', [])
        # 단계별 분기 실행
        ...
```

### EDAAgent 핵심 구조

```python
class EDAAgent(BaseAgent):
    use_llm = False

    CHART_DISPATCH = {
        'tabular_ml':        '_tabular_charts',
        'tabular_dl':        '_tabular_charts',
        'anomaly_detection': '_anomaly_charts',
        'timeseries':        '_timeseries_charts',
        'image':             '_image_charts',
        'nlp':               '_nlp_charts',
    }

    def run(self, state: PipelineState) -> PipelineState:
        df = minio_tool.load_file(state.raw_data_id)
        method_name = self.CHART_DISPATCH.get(state.category, '_tabular_charts')
        chart_paths = getattr(self, method_name)(df, state)
        state.eda_charts = chart_paths
        return state

    def _save_chart(self, fig, chart_name: str, job_id: str) -> str:
        img_bytes = fig.to_image(format='png', scale=2)
        path = f"eda/{job_id}/{chart_name}.png"
        minio_tool.save_bytes(img_bytes, path)
        return path

    def _tabular_charts(self, df: pd.DataFrame, state) -> list:
        paths = []
        numeric_cols = df.select_dtypes(include='number').columns[:5]
        for col in numeric_cols:
            fig = px.histogram(df, x=col, nbins=30, title=f'{col} 분포')
            paths.append(self._save_chart(fig, f'hist_{col}', state.job_id))
        corr = df.select_dtypes(include='number').corr()
        fig = px.imshow(corr, color_continuous_scale='RdBu', title='상관관계 히트맵')
        paths.append(self._save_chart(fig, 'correlation_heatmap', state.job_id))
        return paths
```

### Streamlit UI 핵심 구조

```python
# ui/app.py
import streamlit as st
import asyncio
import websockets
import json
import httpx

st.set_page_config(page_title="ADA - AutoAI Pipeline", layout="wide")
st.title("Adaptive AutoAI Pipeline Agent")

with st.sidebar:
    st.header("파이프라인 설정")
    category = st.selectbox("분석 카테고리", ['tabular_ml', 'timeseries', 'image', 'nlp', 'anomaly_detection', 'tabular_dl'])
    target_col = st.text_input("타겟 컬럼명", placeholder="target")
    user_question = st.text_input("분석 질문", placeholder="어떤 인사이트가 필요하신가요?")
    max_retries = st.slider("최대 재시도 횟수", 1, 5, 3)

uploaded_file = st.file_uploader("데이터 파일 업로드", type=['csv', 'parquet', 'zip', 'txt'])

if uploaded_file and st.button("파이프라인 시작", type="primary"):
    with st.spinner("파이프라인 시작 중..."):
        response = httpx.post("http://api:8000/jobs", files={"file": uploaded_file},
                              data={"category": category, "target_column": target_col, "user_question": user_question})
        job_id = response.json()['job_id']
        st.session_state['job_id'] = job_id

    progress_bar = st.progress(0)
    status_text = st.empty()

    async def listen_ws():
        async with websockets.connect(f"ws://api:8000/pipeline/ws/{job_id}") as ws:
            async for message in ws:
                data = json.loads(message)
                progress_bar.progress(data['progress_pct'] / 100)
                status_text.info(f"현재 실행 중: {data['current_agent']}")
                if data.get('status') == 'completed':
                    break

    asyncio.run(listen_ws())
```

---

## 📁 생성/수정 파일 목록

| 경로 | 작업 | 설명 |
|------|------|------|
| `agents/preprocessing_strategist.py` | 신규 생성 | LLM 기반 전처리 계획 수립 |
| `agents/feature_engineer.py` | 신규 생성 | sklearn 파이프라인 실행 |
| `agents/eda_agent.py` | 신규 생성 | Plotly 기반 EDA 시각화 |
| `ui/app.py` | 신규 생성 | Streamlit 메인 UI |
| `ui/config.toml` | 신규 생성 | `server.maxUploadSize = 100` |
| `ui/__init__.py` | 신규 생성 | 패키지 초기화 |
| `harness/skills/tabular_ml/preprocessing.md` | 신규 생성 | 전처리 도메인 지식 |
| `harness/skills/timeseries/preprocessing.md` | 신규 생성 | 시계열 전처리 지식 |
| `harness/skills/nlp/preprocessing.md` | 신규 생성 | NLP 전처리 지식 |
| `core/state.py` | 수정 | preprocessing_plan, preprocessed_data_id, eda_charts 필드 추가 |

---

## 🔗 의존성 & 선행 조건

### Day 9까지 완료되어야 하는 항목

- `SkillsLoader` (`harness/skills_loader.py`) 구현 완료
- `harness/skills/*/preprocessing.md` 파일 존재
- MinIO 연결 유틸리티 (`shared/minio_tool.py`) 구현 완료
- `DataProfilerAgent` (`agents/data_profiler.py`): `state.data_profile` 생성 완료
- `state.raw_data_id` 설정 (SchemaValidator 이후 MinIO 저장 완료)

### Python 패키지 의존성

```
scikit-learn>=1.4.0
transformers>=4.40.0
streamlit>=1.34.0
websockets>=12.0
httpx>=0.27.0
plotly>=5.22.0
kaleido>=0.2.1
scipy>=1.13.0
statsmodels>=0.14.2
pillow>=10.3.0
```

### Streamlit 설정 (`ui/.streamlit/config.toml`)

```toml
[server]
maxUploadSize = 100

[theme]
primaryColor = "#2563eb"
backgroundColor = "#f8fafc"
secondaryBackgroundColor = "#e2e8f0"
textColor = "#1e293b"
```

---

## ✔️ 완료 기준 (Done Criteria)

- [ ] `PreprocessingStrategistAgent`: 6개 카테고리 각각 다른 `preprocessing_plan` 생성 확인
- [ ] `FeatureEngineerAgent`: `KNNImputer`, `OneHotEncoder`, `StandardScaler` 3종 체이닝 실행 확인
- [ ] `FeatureEngineerAgent`: 분류 시 `stratify=y` 적용, 8:2 분할 확인
- [ ] `EDAAgent`: tabular_ml 히스토그램 최대 5개 + 히트맵 = 최대 6개 차트 MinIO 저장 확인
- [ ] `EDAAgent`: timeseries 라인 차트 + ACF 차트 MinIO 저장 확인
- [ ] `EDAAgent`: nlp 텍스트 길이 분포 + 단어 빈도 차트 MinIO 저장 확인
- [ ] Streamlit UI: 로컬에서 `streamlit run ui/app.py` 정상 실행 확인
- [ ] Streamlit UI: 파일 업로드 후 파이프라인 시작 → 진행 바 표시 확인

---

## ⚠️ 주의사항 & 제약

1. **OneHotEncoder 차원 폭발**: `max_categories=50` 제한 필수. 고카디널리티 컬럼은 Target Encoding 사용.
2. **대용량 데이터 처리**: 10만 행 이상 시 EDA는 샘플링(10,000행) 후 수행.
3. **이미지 EDA 메모리**: 이미지 격자 생성 시 최대 20장 제한 (OOM 방지).
4. **kaleido 의존성**: Plotly PNG 내보내기에 `kaleido` 필요. 미설치 시 `fig.write_html()` 폴백.
5. **Streamlit WebSocket**: Streamlit Cloud 환경에서 `asyncio.run()` 호환 이슈 있음. `st.experimental_connection` 또는 `threading` 대안 검토.
6. **타겟 누설 방지**: 전처리 fit은 반드시 X_train에만 수행, X_val은 transform만.
7. **PreprocessingStrategist JSON 실패**: LLM 응답이 JSON 파싱 실패 시, 카테고리별 하드코딩 기본 plan 폴백 적용.
8. **TimeSeries 분할**: 시계열 데이터는 `train_test_split` 미사용, 시간 순서 유지하여 마지막 20% 검증셋으로 사용.

---

## 🆕 v2 확장 작업 (마스터 설계서 §3.G3 · §5)

> Day10 의 v2 핵심: PreprocessingStrategist + FeatureEngineer 가 (a) G2 사용자 선택 반영, (b) 자체학습 KB에서 eda_templates 활용, (c) 필요시 미니 게이트(preprocessing_choice) 발동.

### 1. PreprocessingStrategistAgent v2

- [ ] `SelfLearningClient.fetch_recipes(category, kb_types=['recipe'])` 호출 결과를 system prompt에 컨텍스트로 주입
- [ ] G2 사용자 선택(`state.user_choice_g2.method`) 반영하여 방법론별 전처리 차별화
- [ ] PII 마스킹 정책(`state.pii_mask_policy`)을 plan 첫 단계에 강제 삽입

### 2. EDAAgent v2 — eda_templates 캐시

- [ ] `SelfLearningClient.fetch_recipes(category, kb_types=['eda_template'])` 로 도메인별 검증된 차트 셋 조회
- [ ] 신규 데이터셋이라도 유사 도메인의 EDA 템플릿을 자동 적용 (KP7 학습 효과 달성에 기여)

### 3. 미니 게이트 — preprocessing_choice (Day10 단독 소유)

> 이 미니 게이트는 G1~G5 정규 게이트와 달리 **조건부**로만 발동된다. 정상 흐름에서는 자동 결정되고 사용자에게 보이지 않는다.

- [ ] `agents/preprocessing_choice.py` — `PreprocessingChoiceAgent(BaseAgent)` 클래스
- [ ] **발동 조건** (둘 중 하나):
  - 결측 처리 방법 후보(KNN / Median / Drop) 사이 PreprocessingStrategist 의 자동 신뢰도 < 0.7
  - 불균형 데이터 처리(SMOTE / class_weight / undersampling) 사이 신뢰도 차이 Δ < 0.15
- [ ] 발동 시 `state.awaiting_decision = "PREPROC_CHOICE"` 로 설정 → 그래프 일시정지
- [ ] UI: G1~G5 카드와 동일 형식이되 보조 게이트라는 점을 표시 ("Optional decision — pre-filled by AI, click to override")
- [ ] 사용자가 24h 미응답 시 자동 결정값 채택 + `auto_resolved=true` 마킹

### 4. Streamlit UI 보강 — 게이트 카드 UI

- [ ] `ui/components/gate_card.py` — G1~G5 공용 카드 컴포넌트 (제목/이유/메트릭/추천 배지)
- [ ] G2 응답 표 형식 UI
- [ ] 사용자가 선택할 때 추천 1순위가 아닌 안을 고르면 `decisions.adopted_rank` 가 2,3 등으로 저장 (KP11 측정)

### 5. 완료 기준 (v2 추가)

- [ ] eda_templates 적용 시 EDA 시간 ≥ 20% 단축
- [ ] preprocessing_choice 미니 게이트 발동 케이스 단위 테스트
- [ ] G2 응답 표 UI 스크린샷 확보
