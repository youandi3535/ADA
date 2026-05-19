# ADA v2.3 작업지시서 인덱스

> 갱신일: 2026-05-19
> 권위 순서: `TOOL_CATALOG_2026.md` (도구 도입 단계) > `RENEWAL_SPEC.md` (v2.3 스코프) > `Day00 마스터설계서` (부록 C·D 포함) > 각 Day 파일

---

## 📚 일일 작업지시서 (26일 + 마스터)

### 마스터
| 파일 | 내용 |
|---|---|
| `daily/Day00_마스터설계서_v2.md` | 전체 아키텍처 + 부록 C(v2.2 감사) + 부록 D(v2.3 도구) |

### 1주차 — Foundations
| Day | 파일 | 핵심 |
|---|---|---|
| 01 | `Day01_환경설정.md` | Docker 8 서비스 + Vault Raft + Alembic |
| **A** | `Day-A_백업및DR인프라.md` | pgBackRest + MinIO mirror + Vault snapshot + 페일오버 |
| 02 | `Day02_DB및인프라.md` | Alembic 의무 + RLS 5테이블 + JSONB GIN |
| 03 | `Day03_공통모듈및CICD.md` | structlog + pybreaker + DI + SBOM/cosign + **Langfuse @traced** |
| 04 | `Day04_LangGraph및Celery.md` | LangGraph 핀 + 플러그인 + Bulkhead + Redis Streams |
| 05 | `Day05_데이터처리에이전트.md` | **LLM Guard PII** + 멀티 포맷 + indirect injection |
| 06 | `Day06_Supervisor및FastAPI기본.md` | 회로차단기 + Rate limit + magic byte |
| 07 | `Day07_정형ML파이프라인및ModelSelection.md` | warm-start + **FLAML 폴백** + 트랜스포머 완화 |

### 2주차 — Modeling + Self-Learning
| Day | 파일 | 핵심 |
|---|---|---|
| 08 | `Day08_학습실행에이전트4종.md` | MLflow auth + 모델 SHA256 + **StatsForecast/PyOD** + Ray Tune 백로그 |
| 09 | `Day09_HarnessEngineering.md` | KB 오염 방지 + confidence cap + 룰 충돌 |
| 10 | `Day10_전처리및EDA에이전트.md` | SSE 분리 + 시간 누설 + High-cardinality |
| 11 | `Day11_해석력및인사이트에이전트.md` | SHAP 층화 + 재루프 캡 + **Captum 백로그** |
| 12 | `Day12_산출물생성및확장파이프라인.md` | **PyOD** + **python-docx** + NeuralForecast/SUOD 백로그 |
| 13 | `Day13_오류처리및API완성.md` | 6 fallback + TTL cache + 다운그레이드 |
| 14 | `Day14_테스트검증및데모.md` | AT-1 트랙 분리 + KP7 자동 + **Braintrust 백로그** |

### 3주차 — Outputs / Errors / Security / Dashboard / Test
| Day | 파일 | 핵심 |
|---|---|---|
| 15 | `Day15_산출물패밀리확장.md` | 버전 관리 + audit + **python-docx** + **Chart.js/Plotly** |
| 16 | `Day16_자동오류처리및ClaudeCLI브리지.md` | subprocess→SDK + 회로차단기 + **SWE-agent 백로그** |
| 17 | `Day17_보안풀스택.md` | (Day-C 강결합) + **LLM Guard + Guardrails 3중 방어** |
| **C** | `Day-C_보안보강.md` | mTLS·MFA·SBOM·cosign·Falco·indirect·pybreaker |
| 18 | `Day18_웹대시보드및에이전트현황판.md` | Backup Health + 토글 + SSE + **Langfuse 위젯** |
| 19 | `Day19_API완성및SelfLearning통합.md` | KB 인용 매핑 + 삭제 권리 + **Arize/Galileo/Qdrant 백로그** |
| **B** | `Day-B_자가학습폐쇄.md` | KB lifecycle + Shadow eval + KP7 자동 + retraction |
| 20 | `Day20_통합테스트및침투테스트.md` | OWASP ZAP + IT-DR + KP7 view + Guardrails E2E |
| 21 | `Day21_인수테스트및데모및문서화.md` | backup_restore.md + ADR 10건 + Vault HA |

### v2.3 신설 (도구 카탈로그)
| Day | 파일 | 도구 4종 |
|---|---|---|
| **D** | `Day-D_도구즉시도입.md` | 🔴 Langfuse · LLM Guard · PyOD v3 · python-docx |
| **E** | `Day-E_도구단기도입.md` | 🟡 Guardrails AI · FLAML · StatsForecast · Chart.js/Plotly |

---

## 📂 보조 문서
| 파일 | 내용 |
|---|---|
| `TOOL_CATALOG_2026.md` | 🆕 18종 도구 카탈로그 + 우선순위 + Day 매핑 + 신규 룰 + 라이선스 |
| `v3_backlog.md` | 🆕 중기 5종 + 장기 5종 도구 도입 명세 + ADR 권고 |
| `RENEWAL_SPEC.md` | v2.3·v2.2·v2.1 변경 요약 누적 |
| `DEV_SETUP_GUIDE.md` | WSL2 + Python 3.10 신규 개발자 가이드 |
| `DOCKER_ENV_INVENTORY.md` | Docker 이미지·패키지·환경변수 인벤토리 |
| `LINUX_DOCKER_SETUP_GUIDE.md` | Linux Docker 설정 |
| `ADA_v2_감사보고서.docx` | 프로덕션급 감사 보고서 |
| `INDEX_v2.3.md` | 본 인덱스 (v2.3 갱신) |

---

## 🎯 신설 룰 색인 (v2.3)

### 즉시·단기 도구 룰 (R-1001~1008)
- R-1001 — Langfuse trace 자동 부착 (Day-D §1)
- R-1002 — LLM Guard → ADA 정규식 2단 폴백 (Day-D §2)
- R-1003 — PyOD v3 레지스트리 표준화 (Day-D §3)
- R-1004 — Word 초안(.docx) OUT-02 옵션 (Day-D §4)
- R-1005 — Guardrails schema 검증 의무 (Day-E §1)
- R-1006 — FLAML cost-aware 폴백 (Day-E §2)
- R-1007 — StatsForecast Top-3 베이스라인 의무 (Day-E §3)
- R-1008 — Chart.js 우선 / Plotly 폴백 (Day-E §4)

### v3 백로그 룰 (R-1101~1105)
- R-1101 — Ray Tune 분산 모드 권고 (≥ 10분 학습)
- R-1102 — NeuralForecast 단일 진입점
- R-1103 — Captum 트랜스포머 해석 우선
- R-1104 — Phoenix 임베딩 드리프트 알람
- R-1105 — SUOD 자동 활성화 (≥ 100k 행)

### v2.2 룰 (이전 인덱스 R-403/501/503/504/505/601/703~709/901~903 — 유지)

---

## 🔗 신설 Day 1줄 요약 (v2.2 + v2.3)

- **Day-A** (v2.2): pgBackRest·MinIO mirror·Vault snapshot·페일오버 + Game Day. RPO 5분, RTO 30분.
- **Day-B** (v2.2): KB → 코드 인용 매핑·confidence lifecycle·shadow eval·자동 retraction. 자가학습 사이클 폐쇄.
- **Day-C** (v2.2): mTLS·MLflow auth·MFA·SBOM/cosign·Falco·indirect injection·pybreaker. 단독 서버 외부 노출 대응.
- **Day-D** (v2.3): 🔴 Langfuse + LLM Guard + PyOD v3 + python-docx 4종 즉시 도입.
- **Day-E** (v2.3): 🟡 Guardrails AI + FLAML + StatsForecast + Chart.js/Plotly 4종 단기 도입.

---

## 📊 KPI v2.3 (v2.2에서 변경 없음)

| KPI | 목표 |
|---|---|
| KP1 | E2E 성공률 ≥ 85% |
| KP2 | 응답 ≤ 90s (트리) / ≤ 180s (트랜스포머) |
| KP3 | 자동 재루프 ≥ 75% |
| KP4 | 카테고리 4/4 |
| KP5 | API p95 < 400ms |
| KP6 | AGENTS.md 자동 룰 ≥ 15 |
| KP7 | 유사 데이터 30일 회귀 기울기 |
| KP8 | 오류 자체해결 ≥ 40% + 회로차단기 |
| KP9 | 트랜스포머 채택 ≥ 25% |
| KP10 | 보안 침해 0건 |
| KP11 | shadow.matched 자동 측정 |
| KP12 | 백업 RPO 준수율 ≥ 99% (월간) |
| KP13 | 분기 Game Day 4/4 |

---

## 🛠️ 도구 18종 한눈 색인

| 카테고리 | 도구 | 우선 | 도입 위치 |
|---|---|---|---|
| 옵저버빌리티 | Langfuse | 🔴 | Day-D §1 |
| 옵저버빌리티 | Arize Phoenix | 🟢 | v3 백로그 A.4 |
| 벡터DB | Qdrant | ⚪ | v3 백로그 B.1 |
| AutoML | FLAML | 🟡 | Day-E §2 |
| 분산 HPO | Ray Tune | 🟢 | v3 백로그 A.1 |
| MLOps | ClearML | ⚪ | v3 백로그 B.2 |
| 시계열 통계 | StatsForecast | 🟡 | Day-E §3 |
| 시계열 DL | NeuralForecast | 🟢 | v3 백로그 A.2 |
| 이상탐지 | PyOD v3 | 🔴 | Day-D §3 |
| 이상탐지 가속 | SUOD | 🟢 | v3 백로그 A.5 |
| 보안 가드 | LLM Guard | 🔴 | Day-D §2 |
| 보안 스키마 | Guardrails AI | 🟡 | Day-E §1 |
| 산출물 Word | python-docx | 🔴 | Day-D §4 |
| 산출물 차트 | Chart.js/Plotly | 🟡 | Day-E §4 |
| 해석성 | Captum | 🟢 | v3 백로그 A.3 |
| 자가패치 | SWE-agent | ⚪ | v3 백로그 B.3 |
| LLM 평가 | Braintrust | ⚪ | v3 백로그 B.4 |
| 할루시네이션 | Galileo | ⚪ | v3 백로그 B.5 |
