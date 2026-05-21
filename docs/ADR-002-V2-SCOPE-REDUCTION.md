# ADR-002 v2 스코프 축소 (4 카테고리 / 5 산출물)

## Status
Accepted (2026-05-18)

## Context
하드웨어 제약 16GB RAM / GTX 1060 3GB / 144GB 디스크 + 비즈니스 활용폭 우선.

## Decision
- 카테고리: 6→4 (`image`, `nlp` 제거)
- 산출물: 13→5 (OUT-01/02/03/04/07 만)
- TRANSFORMER_REGISTRY: 14→8
- MLflow 실험: 6→4

## Consequences
- 이미지/NLP 코드는 작성하지 않음
- ReportComposerAgent GENERATORS = 5
- PPT 색상 테마 = 4색
