# ADR-005 LangGraph 25노드 + 5게이트 인터럽트

## Status
Accepted

## Context
v1 17노드는 단방향. v2 는 HITL 5게이트 인터럽트 + 미니 게이트(PreprocessingChoice) + FineTune.

## Decision
25 노드 (END 외): supervisor → intent_elicitor → data_profiler → schema_validator → gate_direction → eda_agent → gate_methodology → preprocessing_strategist → feature_engineer → (preprocessing_choice) → gate_model_strategy → model_selection → hyperparameter_tuner → training_executor → training_monitor → metrics_aggregator → gate_best_model → (fine_tune_executor) → eval_agent → explainability → insight → gate_outputs → report_composer → self_learning_dispatch (+ error_recovery)

- `interrupt_after=[gate_direction, gate_methodology, gate_model_strategy, gate_best_model, gate_outputs]`
- thread_id = job_id, PostgresSaver checkpointer

## Consequences
- 5게이트마다 API resume 호출 필요
- KP11 (게이트 채택률) 측정 가능
