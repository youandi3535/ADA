# ADA v2.4 작업지시서 인덱스

> 갱신일: 2026-05-19
> 권위 순서: `TOOL_CATALOG_2026.md` > `RENEWAL_SPEC.md` (v2.4) > `Day00 마스터설계서` (부록 C·D 갱신) > 각 Day 파일 (📦 통합본 포함)
>
> **v2.4 변경**: v2.2~v2.3 의 신설 Day-A/B/C/D/E 5개 파일이 모두 기존 Day 안으로 흡수·삭제되었다. 본문은 보존, 권위 위치만 이전.

---

## 📚 일일 작업지시서 (Day00 + 21일 = 22 파일)

### 마스터
| 파일 | 내용 |
|---|---|
| `daily/Day00_마스터설계서_v2.md` | 전체 아키텍처 + 부록 C(v2.2 감사·v2.4 통합)·부록 D(v2.3 도구·v2.4 통합) |

### 1주차 — Foundations
| Day | 파일 | 핵심 + v2.4 통합본 |
|---|---|---|
| 01 | `Day01_환경설정.md` | Docker 8 서비스 + Vault Raft + Alembic |
| 02 | `Day02_DB및인프라.md` | Alembic 의무 + RLS 5테이블 + JSONB GIN |
| 03 | `Day03_공통모듈및CICD.md` | structlog + pybreaker + DI + SBOM + **📦 Langfuse (← Day-D §1)** |
| 04 | `Day04_LangGraph및Celery.md` | LangGraph 핀 + 플러그인 + Bulkhead + Redis Streams |
| 05 | `Day05_데이터처리에이전트.md` | LLM Guard PII 보강 + indirect injection + 멀티 포맷 |
| 06 | `Day06_Supervisor및FastAPI기본.md` | 회로차단기 + Rate limit + magic byte |
| 07 | `Day07_정형ML파이프라인및ModelSelection.md` | warm-start + 트랜스포머 완화 + **📦 FLAML (← Day-E §2)** |

### 2주차 — Modeling + Self-Learning
| Day | 파일 | 핵심 + v2.4 통합본 |
|---|---|---|
| 08 | `Day08_학습실행에이전트4종.md` | MLflow auth + 모델 SHA256 + PyOD/Ray 백로그 + **📦 StatsForecast (← Day-E §3)** |
| 09 | `Day09_HarnessEngineering.md` | KB 오염 방지 + confidence cap + 룰 충돌 |
| 10 | `Day10_전처리및EDA에이전트.md` | SSE 분리 + 시간 누설 + High-cardinality |
| 11 | `Day11_해석력및인사이트에이전트.md` | SHAP 층화 + Captum 백로그 + 재루프 캡 |
| 12 | `Day12_산출물생성및확장파이프라인.md` | python-docx 백로그 + NeuralForecast/SUOD + **📦 PyOD v3 (← Day-D §3)** |
| 13 | `Day13_오류처리및API완성.md` | 6 fallback + TTL cache + 다운그레이드 |
| 14 | `Day14_테스트검증및데모.md` | AT-1 트랙 분리 + KP7 자동 + Braintrust 백로그 |

### 3주차 — Outputs / Errors / Security / Dashboard / Test
| Day | 파일 | 핵심 + v2.4 통합본 |
|---|---|---|
| 15 | `Day15_산출물패밀리확장.md` | 버전 관리 + audit + **📦 python-docx (← Day-D §4)** + **📦 Chart.js/Plotly (← Day-E §4)** + Day-D/E 종합 테스트 |
| 16 | `Day16_자동오류처리및ClaudeCLI브리지.md` | subprocess→SDK + 회로차단기 + SWE-agent 백로그 |
| 17 | `Day17_보안풀스택.md` | JWT·RBAC·Vault·audit baseline + **📦 Day-A 백업·DR + 📦 Day-C 보안 보강 + 📦 LLM Guard (← Day-D §2) + 📦 Guardrails AI (← Day-E §1)** |
| 18 | `Day18_웹대시보드및에이전트현황판.md` | Backup Health + 토글 + SSE + Langfuse 위젯 |
| 19 | `Day19_API완성및SelfLearning통합.md` | KB 인용 매핑 + 삭제 권리 + Arize/Galileo 백로그 + **📦 Day-B 자가학습 폐쇄** |
| 20 | `Day20_통합테스트및침투테스트.md` | OWASP ZAP + IT-DR + KP7 view + Guardrails E2E |
| 21 | `Day21_인수테스트및데모및문서화.md` | backup_restore.md 콘텐츠 + ADR 10건 + Vault HA |

> 📦 표기는 v2.4에서 통합된 섹션. 원래 신설 Day-A/B/C/D/E 파일은 v2.4 부터 존재하지 않는다.

---

## 📂 보조 문서
| 파일 | 내용 |
|---|---|
| `TOOL_CATALOG_2026.md` | 18종 도구 카탈로그 + 우선순위 + Day 매핑(v2.4 갱신) + 신규 룰 |
| `v3_backlog.md` | 중기 5종 + 장기 5종 도입 명세 + ADR 권고 |
| `RENEWAL_SPEC.md` | v2.4·v2.3·v2.2·v2.1 변경 요약 누적 |
| `DEV_SETUP_GUIDE.md` | WSL2 + Python 3.10 신규 개발자 가이드 |
| `DOCKER_ENV_INVENTORY.md` | Docker 이미지·패키지·환경변수 인벤토리 |
| `LINUX_DOCKER_SETUP_GUIDE.md` | Linux Docker 설정 |
| `ADA_v2_감사보고서.docx` | 프로덕션급 감사 보고서 |
| `INDEX_v2.3.md` | v2.3 시점 인덱스 (참고용 보관) |
| `INDEX_v2.4.md` | **본 인덱스 (현재)** |

---

## 🗺️ v2.4 통합 매핑 한눈

```
원래 Day-A (백업·DR)           ─→ Day17 📦 통합본
원래 Day-B (자가학습 폐쇄)      ─→ Day19 📦 통합본
원래 Day-C (보안 보강)          ─→ Day17 📦 통합본
원래 Day-D §1 Langfuse         ─→ Day03 📦 통합본
원래 Day-D §2 LLM Guard        ─→ Day17 📦 통합본
원래 Day-D §3 PyOD v3          ─→ Day12 📦 통합본
원래 Day-D §4 python-docx      ─→ Day15 📦 통합본
원래 Day-E §1 Guardrails AI    ─→ Day17 📦 통합본
원래 Day-E §2 FLAML            ─→ Day07 📦 통합본
원래 Day-E §3 StatsForecast    ─→ Day08 📦 통합본
원래 Day-E §4 Chart.js/Plotly  ─→ Day15 📦 통합본
Day-D/E 종합 테스트 부록        ─→ Day15 끝
```

---

## 🎯 룰 색인 (v2.4 — v2.2/v2.3 모두 유지)

### v2.2 룰
- R-403 완화 (트랜스포머 강제 조건부)
- R-501 (KB 인용 강제) / R-503 (record_outcome) / R-504 (자동 retraction) / R-505 (decay)
- R-601 보강 (Claude CLI SDK 비동기)
- R-703~709 (mTLS·MLflow·MFA·cosign·JWT RS256·indirect·pybreaker)
- R-901~903 (backup_catalog·SHA256·Vault Raft)

### v2.3 도구 룰
- R-1001 Langfuse (Day03 통합본)
- R-1002 LLM Guard (Day17 통합본)
- R-1003 PyOD v3 (Day12 통합본)
- R-1004 python-docx (Day15 통합본)
- R-1005 Guardrails AI (Day17 통합본)
- R-1006 FLAML (Day07 통합본)
- R-1007 StatsForecast (Day08 통합본)
- R-1008 Chart.js / Plotly (Day15 통합본)

### v3 백로그 룰
- R-1101 Ray Tune · R-1102 NeuralForecast · R-1103 Captum · R-1104 Phoenix · R-1105 SUOD

---

## 📊 KPI (v2.2부터 유지)

KP1 E2E≥85% · KP2 90s/180s · KP3 재루프≥75% · KP4 4/4 · KP5 p95<400ms · KP6 룰≥15 · KP7 회귀 기울기 · KP8 ≥40%+회로차단기 · KP9 ≥25% · KP10 0건 · KP11 shadow.matched · KP12 백업 RPO≥99% · KP13 Game Day 4/4

---

## 🛠️ 도구 18종 한눈 색인 (v2.4 통합 위치)

| 카테고리 | 도구 | 우선 | 위치 |
|---|---|---|---|
| 옵저버빌리티 | Langfuse | 🔴 | Day03 📦 |
| 옵저버빌리티 | Arize Phoenix | 🟢 | v3 백로그 |
| 벡터DB | Qdrant | ⚪ | v3 백로그 |
| AutoML | FLAML | 🟡 | Day07 📦 |
| 분산 HPO | Ray Tune | 🟢 | v3 백로그 |
| MLOps | ClearML | ⚪ | v3 백로그 |
| 시계열 통계 | StatsForecast | 🟡 | Day08 📦 |
| 시계열 DL | NeuralForecast | 🟢 | v3 백로그 |
| 이상탐지 | PyOD v3 | 🔴 | Day12 📦 |
| 이상탐지 가속 | SUOD | 🟢 | v3 백로그 |
| 보안 가드 | LLM Guard | 🔴 | Day17 📦 |
| 보안 스키마 | Guardrails AI | 🟡 | Day17 📦 |
| 산출물 Word | python-docx | 🔴 | Day15 📦 |
| 산출물 차트 | Chart.js/Plotly | 🟡 | Day15 📦 |
| 해석성 | Captum | 🟢 | v3 백로그 |
| 자가패치 | SWE-agent | ⚪ | v3 백로그 |
| LLM 평가 | Braintrust | ⚪ | v3 백로그 |
| 할루시네이션 | Galileo | ⚪ | v3 백로그 |
