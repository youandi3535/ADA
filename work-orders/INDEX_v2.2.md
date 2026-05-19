# ADA v2.2 작업지시서 인덱스

> 갱신일: 2026-05-19
> 권위 순서: `RENEWAL_SPEC.md` (v2.2) > `Day00 마스터설계서` (부록 C 포함) > 각 Day 파일

---

## 📚 일일 작업지시서 (24일 + 마스터)

### 마스터
| 파일 | 내용 |
|---|---|
| `daily/Day00_마스터설계서_v2.md` | 전체 아키텍처 + 부록 C (v2.2 감사 반영) |

### 1주차 — Foundations
| Day | 파일 | 핵심 |
|---|---|---|
| 01 | `Day01_환경설정.md` | Docker compose 8개 서비스 + Vault Raft + Alembic 베이스라인 (v2.2 보강) |
| **A** | `Day-A_백업및DR인프라.md` | pgBackRest + MinIO mirror + Vault snapshot + 페일오버 |
| 02 | `Day02_DB및인프라.md` | Alembic 의무화 + RLS 5테이블 + JSONB GIN |
| 03 | `Day03_공통모듈및CICD.md` | structlog correlation + pybreaker + DI + import-linter + SBOM/cosign |
| 04 | `Day04_LangGraph및Celery.md` | LangGraph 버전 고정 + 플러그인 + Bulkhead + Redis Streams |
| 05 | `Day05_데이터처리에이전트.md` | Indirect injection 차단 + 멀티 포맷 5종 + PII 미니 게이트 |
| 06 | `Day06_Supervisor및FastAPI기본.md` | 회로차단기 + Rate limit + magic byte |
| 07 | `Day07_정형ML파이프라인및ModelSelection.md` | warm-start + 트랜스포머 정책 완화 + KB 가중치 |

### 2주차 — Modeling + Self-Learning
| Day | 파일 | 핵심 |
|---|---|---|
| 08 | `Day08_학습실행에이전트4종.md` | MLflow 인증 + 모델 SHA256 + OpenLineage |
| 09 | `Day09_HarnessEngineering.md` | KB 오염 방지 + confidence cap + 룰 충돌 해결 |
| 10 | `Day10_전처리및EDA에이전트.md` | SSE 분리 + 시간 누설 + High-cardinality |
| 11 | `Day11_해석력및인사이트에이전트.md` | SHAP 층화 샘플링 + 재루프 캡 |
| 12 | `Day12_산출물생성및확장파이프라인.md` | 트랜스포머 라이선스 + GPU 폴백 + 한글 폰트 |
| 13 | `Day13_오류처리및API완성.md` | 6종 fallback + TTL cache + 다운그레이드 |
| 14 | `Day14_테스트검증및데모.md` | AT-1 트랙 분리 + KP7 자동 측정 + backup_check 통합 |

### 3주차 — Outputs / Errors / Security / Dashboard / Test
| Day | 파일 | 핵심 |
|---|---|---|
| 15 | `Day15_산출물패밀리확장.md` | 버전 관리 + 다운로드 audit + 재시도 큐 + 플러그인 |
| 16 | `Day16_자동오류처리및ClaudeCLI브리지.md` | subprocess → SDK + 회로차단기 + 한글 스택 + 재귀 가드 |
| 17 | `Day17_보안풀스택.md` | (Day-C와 강결합) JWT/RBAC/RLS/Vault/audit baseline |
| **C** | `Day-C_보안보강.md` | mTLS·MFA·SBOM·cosign·Falco·indirect injection·pybreaker |
| 18 | `Day18_웹대시보드및에이전트현황판.md` | Backup Health + 에이전트 토글 + SSE + 게스트 모드 |
| 19 | `Day19_API완성및SelfLearning통합.md` | KB 인용 매핑 + 삭제 권리 + job_cost_metrics |
| **B** | `Day-B_자가학습폐쇄.md` | KB lifecycle + Shadow eval + KP7 자동 + retraction |
| 20 | `Day20_통합테스트및침투테스트.md` | OWASP ZAP + IT-DR + KP7 view 검증 |
| 21 | `Day21_인수테스트및데모및문서화.md` | backup_restore.md 콘텐츠 + ADR 10건 + Vault HA |

---

## 📂 보조 문서
| 파일 | 내용 |
|---|---|
| `RENEWAL_SPEC.md` | v2.2 변경 요약 + v2.1 스코프 |
| `DEV_SETUP_GUIDE.md` | WSL2 + Python 3.10 신규 개발자 가이드 |
| `DOCKER_ENV_INVENTORY.md` | Docker 이미지·패키지·환경변수 인벤토리 |
| `LINUX_DOCKER_SETUP_GUIDE.md` | Linux Docker 설정 |
| `ADA_v2_감사보고서.docx` | 프로덕션급 감사 보고서 (작업지시서 검토 결과) |

---

## 🎯 신설 룰·KPI 색인 (v2.2)

### 새 룰
- **R-403 완화** — 트랜스포머 강제 조건부
- **R-501** — KB 인용 강제
- **R-503** — record_outcome 의무
- **R-504** — fail_rate ≥ 0.7 자동 retraction
- **R-505** — confidence decay
- **R-601 보강** — Claude CLI SDK 비동기
- **R-703** — mTLS 의무
- **R-704** — MLflow 인증
- **R-705** — admin/service MFA
- **R-706** — cosign 서명 + SBOM
- **R-707** — JWT RS256 (HS256 금지)
- **R-708** — indirect injection sanitize
- **R-709** — pybreaker + rate limit 의무
- **R-901** — backup_catalog 등록
- **R-902** — 모델 SHA256 검증
- **R-903** — Vault Dev 모드 금지

### 새 KPI
- **KP2 트랙 분리** — 90s(트리) / 180s(트랜스포머)
- **KP7 재정의** — 유사 데이터 군집 30일 회귀 기울기
- **KP11 자동화** — shadow.matched 비율
- **KP12 신설** — 백업 RPO 준수율 ≥ 99%
- **KP13 신설** — 분기 Game Day 4/4

---

## 🔗 빠른 참조: 신설 Day별 1줄 요약

- **Day-A**: pgBackRest·MinIO mirror·Vault snapshot·페일오버 + Game Day. RPO 5분, RTO 30분.
- **Day-B**: KB → 코드 인용 매핑·confidence lifecycle·shadow eval·자동 retraction. 자가학습 사이클 폐쇄.
- **Day-C**: mTLS·MLflow auth·MFA·SBOM/cosign·Falco·indirect injection·pybreaker. 단독 서버 외부 노출 대응.
