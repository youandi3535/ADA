# Day 11 — 해석력 에이전트 + 인사이트 에이전트
> 프로젝트: Adaptive AutoAI Pipeline Agent | 2주 스프린트 Day 11/14

---

## 📋 오늘의 목표

학습이 완료된 최적 모델에 대해 **왜 이런 예측을 했는지** 설명하는 ExplainabilityAgent와,
분석 결과를 비즈니스 언어로 변환하는 InsightAgent를 완성한다.
더불어 LangGraph 재루프 동작(Eval 실패 → 재학습 → 재평가)을 실제 시뮬레이션으로 검증한다.

- ExplainabilityAgent: SHAP(표형/이상탐지) / GradCAM(이미지) / Attention(NLP) / 시계열 분해 4종 분기
- InsightAgent: Claude Opus 4.7 기반 비즈니스 인사이트 생성 (한국어 4~6단락)
- LangGraph 재루프 검증: retry_count 증가, max_retries 초과 시 error_recovery 라우팅

---

## 👤 담당자

- **C**: ExplainabilityAgent (`agents/explainability.py`)
- **A**: InsightAgent (`agents/insight.py`), LangGraph 재루프 검증

---

## ✅ 작업 목록

### 1. ExplainabilityAgent 구현 (C)

- [ ] `agents/explainability.py` 파일 생성
  - `ExplainabilityAgent(BaseAgent)` 클래스 정의
  - LLM 미사용: `use_llm = False`
  - 카테고리별 설명 방법 분기:
    - `tabular_ml`, `tabular_dl`, `anomaly_detection` → `_shap_explain()`
    - `image` → `_gradcam_explain()`
    - `nlp` → `_attention_explain()`
    - `timeseries`, `forecasting` → `_timeseries_explain()`

- [ ] `_shap_explain(model, X_val, top_k=5) -> dict` 구현
  - `shap.Explainer(model, X_val)` 생성 (모델 타입 자동 감지)
    - Tree 기반 (XGBoost/LightGBM/CatBoost/RandomForest): `shap.TreeExplainer`
    - 딥러닝 (MLP): `shap.DeepExplainer` 또는 `shap.KernelExplainer`
  - `shap_values = explainer(X_val)` 계산
  - Beeswarm plot 생성:
    - `shap.plots.beeswarm(shap_values, show=False)`
    - `plt.savefig(buf, format='png', dpi=150, bbox_inches='tight')`
    - MinIO 저장: `minio_tool.save_bytes(buf.getvalue(), f"explanations/{job_id}/shap_beeswarm.png")`
  - Top-K 특성 추출:
    - `mean_abs_shap = np.abs(shap_values.values).mean(axis=0)`
    - `top_features = [{'feature': col, 'importance': float(val)} for col, val in sorted_top_k]`
  - 반환: `{'top_features': list, 'beeswarm_path': str, 'shap_values_summary': dict}`

- [ ] `_gradcam_explain(model, images) -> dict` 구현
  - `captum.attr.LayerGradCam(model, model.layer4[-1])` (ResNet 기준)
  - 검증셋 이미지 중 클래스별 대표 이미지 5장 선택
  - GradCAM 히트맵 생성 후 원본 이미지에 오버레이
    - `captum.attr.visualization.visualize_image_attr(attr, original_image, method='heat_map')`
  - 오버레이 이미지 PNG 저장 (클래스별 1장)
  - MinIO 저장: `minio_tool.save_bytes(img_bytes, f"explanations/{job_id}/gradcam_{class_name}.png")`
  - 반환: `{'gradcam_paths': list[str], 'attention_regions': list[dict]}`

- [ ] `_attention_explain(model, tokenizer, texts) -> dict` 구현
  - `transformers` BERT attention weights 추출
    - `outputs = model(**inputs, output_attentions=True)`
    - `attentions = outputs.attentions[-1]` (마지막 레이어)
  - 토큰별 평균 attention 가중치 계산
    - `token_importance = attentions.mean(dim=1).mean(dim=1).squeeze()`
  - 상위 10개 중요 토큰 추출
  - Attention 시각화 이미지 생성 (색상 강도 표시)
  - MinIO 저장: `f"explanations/{job_id}/attention_map.png"`
  - 반환: `{'top_tokens': list[dict], 'attention_path': str}`

- [ ] `_timeseries_explain(model, series) -> dict` 구현
  - **구간별 기여도 분석:**
    - 시계열을 N개 구간으로 분할 (기본 12구간, 월별)
    - 각 구간 제거 후 예측 성능 변화로 기여도 계산
    - 막대 그래프로 구간별 기여도 시각화
  - **계절성 분해 시각화:**
    - `statsmodels.tsa.seasonal.seasonal_decompose(series, model='additive')`
    - trend, seasonal, residual 3개 subplot
    - `plotly.subplots.make_subplots(rows=3, cols=1)` 활용
  - MinIO 저장: `f"explanations/{job_id}/timeseries_decompose.png"`
  - 반환: `{'seasonal_path': str, 'segment_contributions': list[dict]}`

- [ ] 카테고리별 분기 로직 및 `state.explanations` 설정

  ```python
  def run(self, state: PipelineState) -> PipelineState:
      model = minio_tool.load_model(state.best_model['minio_path'])
      data = minio_tool.load_file(state.preprocessed_data_id)

      dispatch = {
          'tabular_ml':        lambda: self._shap_explain(model, data['X_val']),
          'tabular_dl':        lambda: self._shap_explain(model, data['X_val']),
          'anomaly_detection': lambda: self._shap_explain(model, data['X_val']),
          'image':             lambda: self._gradcam_explain(model, data['X_val']),
          'nlp':               lambda: self._attention_explain(model, state.tokenizer, data['X_val']),
          'timeseries':        lambda: self._timeseries_explain(model, data['y_val']),
      }
      state.explanations = dispatch[state.category]()
      return state
  ```

### 2. InsightAgent 구현 (A)

- [ ] `agents/insight.py` 파일 생성
  - `InsightAgent(BaseAgent)` 클래스 정의
  - LLM 사용: Claude Opus 4.7
  - **INSIGHT_PROMPT 정의:**
    ```
    당신은 데이터 분석 결과를 비즈니스 인사이트로 변환하는 전문가입니다.

    규칙:
    1. 단순 메트릭 나열 금지 — 의미와 비즈니스 영향 중심으로 서술
    2. 4~6단락 구성, 각 단락 3~5문장
    3. 의사결정자 관점에서 구체적인 비즈니스 임팩트 1개 이상 명시
    4. 한계점과 추가 분석 제안 포함
    5. 전문 용어 사용 시 괄호 안에 한국어 풀이 추가
    6. 반드시 한국어로 작성
    7. 마지막 단락은 즉시 실행 가능한 액션 아이템으로 마무리

    분석 결과:
    {context}
    ```

  - **`_build_context(state: PipelineState) -> str` 메서드:**
    - 모델 메트릭: `state.best_model['metrics']` (primary metric, 보조 메트릭)
    - SHAP Top Features: `state.explanations.get('top_features', [])` 상위 5개
    - Eval 결과: `state.eval_result` (pass, 재루프 횟수 등)
    - 사용자 질문: `state.user_question`
    - 데이터 개요: `state.data_profile` (행/열, 결측률)
    - 경고 사항: `state.training_warnings` 요약

  - **프롬프트 길이 관리:**
    - context 총 길이 4,000 토큰 이내로 제한
    - 초과 시 data_profile 및 warning 요약 축약

  - 결과를 `state.insights` (Markdown 텍스트)에 저장
  - 인사이트 품질 셀프 검증: 4단락 미만이면 "단락 수 부족" 경고 로그

### 3. LangGraph 재루프 동작 검증 (A)

- [ ] 재루프 경로 확인 (LangGraph 그래프 정의 검토)
  - **정상 경로:** `eval_agent` → (pass) → `explainability` → `insight` → `report_composer`
  - **실패 재루프 경로:** `eval_agent` → (fail, retry_count < max_retries) → `training_executor` → `training_monitor` → `metrics_aggregator` → `eval_agent`
  - **최대 재시도 초과:** `eval_agent` → (fail, retry_count >= max_retries) → `error_recovery`

- [ ] `retry_count` 증가 로직 확인
  - `EvalAgent.run()` 실패 시 `state.retry_count += 1` 코드 존재 확인
  - `state.max_retries` 기본값 = 3

- [ ] 재루프 시뮬레이션 테스트 작성 (`tests/test_integration/test_reloop.py`)
  - **케이스 1:** 1차 실패 → 재루프 → 2차 성공 시나리오
    - `val_f1=0.5` (실패) → 하이퍼파라미터 재조정 → `val_f1=0.65` (성공)
    - `retry_count == 1`, `eval_result == 'pass'` 검증
  - **케이스 2:** 3회 연속 실패 → `error_recovery` 라우팅
    - mock `EvalAgent.run()` → 항상 실패 반환
    - `retry_count == 3`, 다음 에이전트 == `error_recovery` 검증
  - **케이스 3:** 재루프 시 `HyperparameterTuner` 탐색 공간 축소 확인
    - 1차 실패 후 `n_trials=25` (절반)로 재탐색
    - learning_rate 범위 축소 확인

- [ ] `route_after_eval` 라우팅 함수 단위 테스트
  ```python
  def test_route_after_eval_retry():
      state = PipelineState(retry_count=1, max_retries=3, eval_result='fail_rule')
      assert route_after_eval(state) == 'training_executor'

  def test_route_after_eval_abort():
      state = PipelineState(retry_count=3, max_retries=3, eval_result='fail_llm')
      assert route_after_eval(state) == 'error_recovery'
  ```

---

## 🏗️ 구현 명세

### ExplainabilityAgent 전체 구조

```python
class ExplainabilityAgent(BaseAgent):
    use_llm = False

    CATEGORY_METHOD_MAP = {
        'tabular_ml':        '_shap_explain',
        'tabular_dl':        '_shap_explain',
        'anomaly_detection': '_shap_explain',
        'image':             '_gradcam_explain',
        'nlp':               '_attention_explain',
        'timeseries':        '_timeseries_explain',
        'forecasting':       '_timeseries_explain',
    }

    def run(self, state: PipelineState) -> PipelineState:
        model = minio_tool.load_model(state.best_model['minio_path'])
        data = minio_tool.load_file(state.preprocessed_data_id)
        method_name = self.CATEGORY_METHOD_MAP[state.category]
        method = getattr(self, method_name)
        if state.category in ('tabular_ml', 'tabular_dl', 'anomaly_detection'):
            state.explanations = method(model, data['X_val'], top_k=5)
        elif state.category == 'image':
            state.explanations = method(model, data['X_val'])
        elif state.category == 'nlp':
            state.explanations = method(model, state.tokenizer, data['X_val'])
        else:
            state.explanations = method(model, data['y_val'])
        return state

    def _shap_explain(self, model, X_val, top_k: int = 5) -> dict:
        explainer = shap.Explainer(model, X_val)
        shap_values = explainer(X_val)
        # Beeswarm plot 저장
        buf = io.BytesIO()
        fig, ax = plt.subplots(figsize=(10, 6))
        shap.plots.beeswarm(shap_values, show=False, ax=ax)
        fig.savefig(buf, format='png', dpi=150, bbox_inches='tight')
        plt.close(fig)
        beeswarm_path = minio_tool.save_bytes(buf.getvalue(),
            f"explanations/{self.job_id}/shap_beeswarm.png")
        # Top-K 특성
        mean_abs = np.abs(shap_values.values).mean(axis=0)
        indices = np.argsort(mean_abs)[::-1][:top_k]
        top_features = [
            {'feature': X_val.columns[i], 'importance': float(mean_abs[i])}
            for i in indices
        ]
        return {'top_features': top_features, 'beeswarm_path': beeswarm_path}
```

### InsightAgent 전체 구조

```python
class InsightAgent(BaseAgent):
    llm_model = "claude-opus-4-7"

    INSIGHT_PROMPT = """당신은 데이터 분석 결과를 비즈니스 인사이트로 변환하는 전문가입니다.

규칙:
1. 단순 메트릭 나열 금지 — 의미와 비즈니스 영향 중심으로 서술
2. 4~6단락 구성, 각 단락 3~5문장
3. 의사결정자 관점에서 구체적인 비즈니스 임팩트 1개 이상 명시
4. 한계점과 추가 분석 제안 포함
5. 전문 용어 사용 시 괄호 안에 한국어 풀이 추가
6. 반드시 한국어로 작성
7. 마지막 단락은 즉시 실행 가능한 액션 아이템으로 마무리

분석 결과:
{context}
"""

    def run(self, state: PipelineState) -> PipelineState:
        context = self._build_context(state)
        prompt = self.INSIGHT_PROMPT.format(context=context)
        response = llm_client.invoke(prompt, model=self.llm_model)
        insights = response.content
        # 품질 검증
        paragraphs = [p for p in insights.split('\n\n') if p.strip()]
        if len(paragraphs) < 4:
            logger.warning(f"InsightAgent: 단락 수 부족 ({len(paragraphs)}개)")
        state.insights = insights
        return state

    def _build_context(self, state: PipelineState) -> str:
        metrics = state.best_model['metrics']
        top_features = state.explanations.get('top_features', [])[:5]
        context_parts = [
            f"## 모델 성능\n- 모델: {state.best_model['model_name']}",
            "\n".join([f"- {k}: {v:.4f}" for k, v in metrics.items()]),
            f"\n## 주요 영향 요인 (SHAP 기반)",
            "\n".join([f"- {f['feature']}: {f['importance']:.4f}" for f in top_features]),
            f"\n## 평가 결과\n- 결과: {state.eval_result}\n- 재시도 횟수: {state.retry_count}",
            f"\n## 사용자 질문\n{state.user_question or '(없음)'}",
            f"\n## 데이터 개요\n- 행: {state.data_profile.get('n_rows')}\n- 열: {state.data_profile.get('n_cols')}",
        ]
        return "\n".join(context_parts)
```

### LangGraph 그래프 라우팅 정의

```python
# core/graph.py (수정)
from langgraph.graph import StateGraph

def route_after_eval(state: PipelineState) -> str:
    if state.eval_result == 'pass':
        return 'explainability'
    if state.retry_count < state.max_retries:
        return 'training_executor'
    return 'error_recovery'

def build_graph() -> StateGraph:
    graph = StateGraph(PipelineState)
    # 노드 등록
    graph.add_node('supervisor', supervisor_agent.run)
    graph.add_node('data_profiler', data_profiler_agent.run)
    graph.add_node('schema_validator', schema_validator_agent.run)
    graph.add_node('preprocessing_strategist', preprocessing_strategist_agent.run)
    graph.add_node('feature_engineer', feature_engineer_agent.run)
    graph.add_node('eda_agent', eda_agent.run)
    graph.add_node('hyperparameter_tuner', hp_tuner_agent.run)
    graph.add_node('training_executor', training_executor_agent.run)
    graph.add_node('training_monitor', training_monitor_agent.run)
    graph.add_node('metrics_aggregator', metrics_aggregator_agent.run)
    graph.add_node('eval_agent', eval_agent.run)
    graph.add_node('explainability', explainability_agent.run)
    graph.add_node('insight', insight_agent.run)
    graph.add_node('report_composer', report_composer_agent.run)
    graph.add_node('error_recovery', error_recovery_agent.run)
    # 조건부 엣지 (재루프)
    graph.add_conditional_edges('eval_agent', route_after_eval, {
        'explainability': 'explainability',
        'training_executor': 'training_executor',
        'error_recovery': 'error_recovery',
    })
    return graph.compile()
```

---

## 📁 생성/수정 파일 목록

| 경로 | 작업 | 설명 |
|------|------|------|
| `agents/explainability.py` | 신규 생성 | SHAP/GradCAM/Attention/시계열 해석 |
| `agents/insight.py` | 신규 생성 | Claude Opus 4.7 비즈니스 인사이트 |
| `core/graph.py` | 수정 | 조건부 엣지(재루프) 정의 추가 |
| `tests/test_integration/test_reloop.py` | 신규 생성 | 재루프 시뮬레이션 통합 테스트 |
| `tests/test_agents/test_eval_agent.py` | 신규 생성 | 임계치 경계값, 라우팅 단위 테스트 |
| `tests/test_agents/test_insight.py` | 신규 생성 | 인사이트 단락 수 검증 테스트 |
| `core/state.py` | 수정 | explanations, insights, retry_count, max_retries 필드 추가 |

---

## 🔗 의존성 & 선행 조건

### Day 10까지 완료되어야 하는 항목

- `EvalAgent` (`agents/eval_agent.py`) 구현 완료
- `state.best_model['minio_path']` 설정 (TrainingExecutor 완료)
- `state.preprocessed_data_id` 설정 (FeatureEngineer 완료)
- `state.eval_result`, `state.retry_count`, `state.max_retries` PipelineState 필드 존재
- LangGraph 그래프 기본 구조 (`core/graph.py`) 존재
- MinIO 모델 로드 유틸리티 (`minio_tool.load_model`) 구현 완료

### Python 패키지 의존성

```
shap>=0.45.0
captum>=0.7.0
matplotlib>=3.8.4
statsmodels>=0.14.2
transformers>=4.40.0
torch>=2.2.0
```

### SHAP 버전 호환성

- `shap.Explainer` 자동 dispatch: XGBoost → TreeExplainer, MLP → KernelExplainer
- PyTorch 모델: `shap.DeepExplainer` 사용, baseline 설정 필요 (X_val 무작위 100행)

---

## ✔️ 완료 기준 (Done Criteria)

- [ ] `ExplainabilityAgent._shap_explain()`: beeswarm plot PNG MinIO 저장 확인 (`explanations/{job_id}/shap_beeswarm.png`)
- [ ] `ExplainabilityAgent._shap_explain()`: `top_features` 리스트 5개 반환 확인
- [ ] `ExplainabilityAgent._gradcam_explain()`: 클래스별 GradCAM 히트맵 PNG 저장 확인
- [ ] `ExplainabilityAgent._attention_explain()`: `top_tokens` 10개 포함 dict 반환 확인
- [ ] `InsightAgent`: 한국어 4~6단락 인사이트 생성 (단락 수 `assert` 검증)
- [ ] `InsightAgent`: 비즈니스 임팩트 문장 포함 확인 (수동 검토)
- [ ] 재루프 시뮬레이션 케이스 1, 2, 3 모두 PASS
- [ ] `route_after_eval` 단위 테스트 통과
- [ ] LangGraph 그래프에서 `eval_agent` → `training_executor` 재루프 엣지 확인

---

## ⚠️ 주의사항 & 제약

1. **SHAP 계산 시간**: 대용량 데이터셋에서 KernelExplainer는 매우 느림. X_val 샘플링 (최대 500행) 필수.
2. **GradCAM 레이어 지정**: 모델 아키텍처별 마지막 Conv 레이어 이름이 다름 (ResNet: `layer4[-1]`, EfficientNet: `features[-1]`). 모델명 기반 레이어 자동 선택 로직 구현 필요.
3. **Attention 가중치 다중 헤드**: BERT attention은 12헤드 × 12레이어. 마지막 레이어의 평균값 사용 권장.
4. **InsightAgent Opus 비용**: Opus 4.7은 비용이 높음. `_build_context()`에서 토큰 수 관리 필수 (4,000 토큰 이내).
5. **재루프 무한 루프 방지**: `max_retries` 하드코딩 상한(5회) 설정. 그래프 정의에서 `recursion_limit` 파라미터 설정.
6. **GradCAM requires_grad**: PyTorch 모델은 `model.eval()` 상태에서 `requires_grad=True` 설정 필요. Captum 사용 시 자동 처리됨.
7. **InsightAgent 프롬프트 안전성**: 사용자 질문(`user_question`)이 프롬프트 인젝션 가능. 최대 200자 제한 및 특수문자 이스케이프 처리.

---

## 🆕 v2 확장 작업 (마스터 설계서 §3.G3-G4 · §4-B)

> Day11 의 v2 핵심: **ModelStrategyProposerAgent (G3)** + **ModelComparisonReporterAgent (G4)** 신설. 두 게이트가 모델링 사이클을 감싸 사용자가 두 번 의사결정한다.

### 1. `agents/proposers/model_strategy_proposer.py` — ModelStrategyProposerAgent (G3)

- [ ] BaseGateAgent 상속, gate_code='G3', Claude Opus 4.7
- [ ] EDA + 전처리 결과 + G2 선택을 입력으로 받아 "왜 이 모델 전략인가" 비교
- [ ] 시스템 프롬프트 핵심:
  ```
  데이터 특성, 사용자 의도, G2 방법론을 기반으로 최종 모델 전략 3개를 비교표로 제시.
  각 전략에 대해:
  - title (예: "TabTransformer + LightGBM 앙상블")
  - why ("왜 딥러닝이 이 데이터에 우월한가" 등)
  - architecture_sketch
  - expected_metrics
  - interpretability_strategy ("SHAP+Attention map")
  - training_budget_min
  - fallback_strategy
  - rank
  반드시 1개 이상은 트랜스포머 활용.
  ```

### 2. `agents/proposers/model_comparison_reporter.py` — ModelComparisonReporterAgent (G4)

- [ ] BaseGateAgent 상속, gate_code='G4'
- [ ] state.trained_models (Top-3) 의 메트릭을 정규화하여 비교표 + 차트 데이터 반환
- [ ] G4 UI는 막대 차트(메트릭), 라인 차트(학습 곡선), SHAP 상위 5개 비교를 표시
- [ ] 시스템 추천 1순위(`recommended_index`)와 사용자 선택을 비교하여 KP11 측정

### 3. fine_tune_executor 노드 (옵션, G4 후)

- [ ] 사용자가 G4 에서 트랜스포머 모델을 선택한 경우 진입
- [ ] LoRA 또는 full fine-tuning 으로 최종 1회 더 학습 (epoch ≥ 추가 3)
- [ ] MLflow에 별도 run으로 기록 (parent_run = 원래 학습 run)

### 4. ExplainabilityAgent v2 — 트랜스포머 attention 별도 처리

- [ ] tabular_transformer 인 경우 self-attention weights → feature importance 변환
- [ ] timeseries Informer/TFT 인 경우 attention temporal heatmap

### 5. InsightAgent v2 — RAG로 과거 유사 사례 인사이트 참조

- [ ] 인사이트 생성 시 `SelfLearningClient.fetch_similar_cases` 결과의 인사이트 텍스트를 컨텍스트로 주입
- [ ] "참고한 과거 분석" 메타데이터로 인사이트 끝에 첨부 (감사 추적)

### 6. 완료 기준 (v2 추가)

- [ ] G3 → G4 → fine_tune (트랜스포머 시) → eval 흐름 E2E 통과
- [ ] G4 비교표 데이터에 학습 곡선, SHAP top5, 학습 시간 모두 포함
- [ ] 트랜스포머 attention 시각화 PNG MinIO 저장
