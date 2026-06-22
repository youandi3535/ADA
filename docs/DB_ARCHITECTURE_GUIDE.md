# ADA 데이터 저장소 완전 교과서 (DB Architecture Guide)

> 이 문서는 ADA 프로젝트의 **모든 데이터 저장소(DB·캐시·오브젝트 스토리지·실험 추적·시크릿)** 를
> 신입도 따라올 수 있게 교과서처럼 풀어 쓴 자료입니다.
> 1~30장은 심층 설명, 31~35장은 발표 예상질문 Q&A 입니다.
>
> 근거 파일: [docker/docker-compose.yml](../docker/docker-compose.yml),
> [ada/db/models.py](../ada/db/models.py), [ada/db/session.py](../ada/db/session.py),
> [docker/init.sql](../docker/init.sql), [ada/core/config.py](../ada/core/config.py),
> [migrations/](../migrations/), [docs/server/backup.md](server/backup.md)

---

## 📖 목차

### 제1부 — 큰 그림 (1~5장)
- [1장. 왜 "DB"가 하나가 아닌가 — 폴리글랏 퍼시스턴스](#1장-왜-db가-하나가-아닌가--폴리글랏-퍼시스턴스)
- [2장. 5종 저장소 한눈에 — 역할·포트·볼륨](#2장-5종-저장소-한눈에--역할포트볼륨)
- [3장. 컨테이너·네트워크·볼륨의 3원소](#3장-컨테이너네트워크볼륨의-3원소)
- [4장. 데이터의 "수명" — 영구 vs 휘발 vs 파생](#4장-데이터의-수명--영구-vs-휘발-vs-파생)
- [5장. "어디에 무엇을 저장하는가" 결정 규칙](#5장-어디에-무엇을-저장하는가-결정-규칙)

### 제2부 — PostgreSQL 초심층 (6~16장)
- [6장. PostgreSQL이 본체인 이유](#6장-postgresql이-본체인-이유)
- [7장. 한 인스턴스, 두 데이터베이스 (autoai · mlflow)](#7장-한-인스턴스-두-데이터베이스-autoai--mlflow)
- [8장. init.sql과 5종 확장(extension)](#8장-initsql과-5종-확장extension)
- [9장. 테이블 지도 — 30여 개를 6그룹으로](#9장-테이블-지도--30여-개를-6그룹으로)
- [10장. 그룹① 인증·사용자 (users, oauth_accounts)](#10장-그룹-인증사용자-users-oauth_accounts)
- [11장. 그룹② 작업 흐름 (uploads~outputs)](#11장-그룹-작업-흐름-uploadsoutputs)
- [12장. 그룹③ ML·실험 (models~gate_decision_metrics)](#12장-그룹-ml실험-modelsgate_decision_metrics)
- [13장. 그룹④ 자가학습·KB와 pgvector](#13장-그룹-자가학습kb와-pgvector)
- [14장. 그룹⑤ 오류 자동수정 (failure_logs~circuit_breaker_events)](#14장-그룹-오류-자동수정-failure_logscircuit_breaker_events)
- [15장. 그룹⑥ 운영·메타 (agent_registry~conversation_logs)](#15장-그룹-운영메타-agent_registryconversation_logs)
- [16장. 외래키·관계·CASCADE 동작 원리](#16장-외래키관계cascade-동작-원리)

### 제3부 — 연결·운영·내부동작 (17~26장)
- [17장. 앱은 어떻게 DB에 연결되나 (config → session)](#17장-앱은-어떻게-db에-연결되나-config--session)
- [18장. 비동기 SQLAlchemy와 풀 전략의 비밀](#18장-비동기-sqlalchemy와-풀-전략의-비밀)
- [19장. Redis — 큐·캐시·회로차단기](#19장-redis--큐캐시회로차단기)
- [20장. MinIO — 우리만의 S3](#20장-minio--우리만의-s3)
- [21장. MLflow — Postgres와 MinIO를 빌려 쓰는 노트](#21장-mlflow--postgres와-minio를-빌려-쓰는-노트)
- [22장. Vault — 시크릿 금고](#22장-vault--시크릿-금고)
- [23장. 마이그레이션 — 스키마의 버전 관리](#23장-마이그레이션--스키마의-버전-관리)
- [24장. 백업과 복구 — Pull 방식의 이유](#24장-백업과-복구--pull-방식의-이유)
- [25장. 보안 — RLS·암호화·PII·네트워크 격리](#25장-보안--rls암호화pii네트워크-격리)
- [26장. 성능·용량·튜닝 포인트](#26장-성능용량튜닝-포인트)

### 제4부 — 실전 (27~30장)
- [27장. 확인·진단 명령어 치트시트](#27장-확인진단-명령어-치트시트)
- [28장. 장애 대응 플레이북](#28장-장애-대응-플레이북)
- [29장. 데이터 파이프라인 전체 흐름도](#29장-데이터-파이프라인-전체-흐름도)
- [30장. 하지 말아야 할 것 모음 (안전수칙)](#30장-하지-말아야-할-것-모음-안전수칙)

### 제5부 — 발표 예상질문 Q&A (31~35장)
- [31장. 발표 Q&A ① 설계·아키텍처](#31장-발표-qa--설계아키텍처)
- [32장. 발표 Q&A ② pgvector·AI 데이터](#32장-발표-qa--pgvectorai-데이터)
- [33장. 발표 Q&A ③ 안정성·장애·백업](#33장-발표-qa--안정성장애백업)
- [34장. 발표 Q&A ④ 보안·프라이버시](#34장-발표-qa--보안프라이버시)
- [35장. 발표 Q&A ⑤ 확장성·비용·운영](#35장-발표-qa--확장성비용운영)

---

# 제1부 — 큰 그림

## 1장. 왜 "DB"가 하나가 아닌가 — 폴리글랏 퍼시스턴스

대부분의 사람은 "DB" 하면 표 하나에 행과 열이 든 **하나의 데이터베이스**를 떠올립니다. 하지만 현대적인 시스템, 특히 AI 분석 플랫폼인 ADA는 **데이터의 성격마다 가장 잘 맞는 저장소를 따로 쓰는** 전략을 택했습니다. 이것을 업계 용어로 **폴리글랏 퍼시스턴스(Polyglot Persistence)** 라고 합니다. "여러 언어를 쓴다"는 뜻의 polyglot처럼, "여러 저장 기술을 동시에 쓴다"는 의미입니다.

왜 굳이 복잡하게 여러 개를 쓸까요? 한 가지 도구로 모든 걸 하려 하면 모든 면에서 어중간해지기 때문입니다. 예를 들어:

- **정형 데이터**(사용자, 작업 기록처럼 행/열 구조가 명확한 것)는 관계형 DB(PostgreSQL)가 압도적으로 잘합니다. 트랜잭션, 조인, 제약조건이 강력하죠.
- **큰 파일**(업로드한 CSV, 학습된 모델 가중치, 생성된 PDF)을 관계형 DB에 넣으면 DB가 비대해지고 느려집니다. 이건 **오브젝트 스토리지(MinIO)** 가 잘합니다.
- **빠르게 들어왔다 나가는 임시 데이터**(작업 대기열, 짧은 캐시)는 디스크에 영구 보관할 필요가 없습니다. 메모리 기반 **Redis** 가 적격입니다.
- **ML 실험 비교**(어떤 모델이 성능이 좋았나)는 전용 UI를 가진 **MLflow** 가 잘합니다.
- **비밀값**(API 키, 비밀번호)은 일반 DB가 아니라 **Vault** 같은 전용 금고가 안전합니다.

ADA는 이 다섯 가지를 모두 채택했습니다. 그래서 "우리 DB 구조"를 이해한다는 것은 사실 **다섯 개의 저장소가 어떻게 협력하는지**를 이해하는 것입니다. 이 문서 전체가 그 협력 구조를 한 장씩 벗겨내는 과정입니다.

> 핵심 한 줄: **ADA에서 "진짜 데이터베이스"는 PostgreSQL 하나지만, "데이터 저장소"는 다섯 개다.**

---

## 2장. 5종 저장소 한눈에 — 역할·포트·볼륨

아래 표가 이 문서 전체의 뼈대입니다. 막히면 항상 여기로 돌아오세요.

| # | 저장소 | 컨테이너명 | 한 줄 정의 | 비유 |
|---|---|---|---|---|
| 1 | 🐘 PostgreSQL | `ada-postgres` | 정형 데이터 본체 | 서류함·장부 |
| 2 | 🔴 Redis | `ada-redis` | 작업 큐 + 캐시(휘발성) | 주방 주문 전표 |
| 3 | 🪣 MinIO | `ada-minio` | 파일·모델·산출물(S3 호환) | 대형 창고 |
| 4 | 📊 MLflow | `ada-mlflow` | ML 실험 추적·비교 UI | 실험 노트 |
| 5 | 🔐 Vault | `ada-vault` | 시크릿 금고(sec 프로파일) | 금고 |

[docker-compose.yml](../docker/docker-compose.yml) 기준 네트워크 주소·포트·데이터 위치:

| 저장소 | Docker 내부 주소 | 호스트(VPS) 접근 포트 | 데이터 볼륨 |
|---|---|---|---|
| PostgreSQL | `postgres:5432` | `127.0.0.1:5433` | `postgres_data` |
| Redis | `redis:6379` | `127.0.0.1:6379` | (없음 — 메모리) |
| MinIO | `minio:9000` | `127.0.0.1:9100`(API), `9101`(콘솔) | `minio_data` |
| MLflow | `mlflow:5000` | `127.0.0.1:5000` | postgres+minio 사용 |
| Vault | `vault:8200` | `127.0.0.1:8200` | `vault_data` |

두 가지를 반드시 기억하세요.

1. **모든 포트가 `127.0.0.1`(localhost)에만 바인딩**되어 있습니다. 즉 인터넷에서 DB·Redis·MinIO에 **직접 접속할 수 없습니다.** 외부로 열린 건 nginx의 80/443뿐입니다. 이건 실수가 아니라 의도된 보안 설계입니다(25장).
2. "Docker 내부 주소"의 `postgres`, `redis` 같은 이름은 **같은 Docker 네트워크(`ada-net`) 안의 컨테이너 이름**입니다. 컨테이너끼리는 IP가 아니라 이름으로 서로를 찾습니다(3장).

---

## 3장. 컨테이너·네트워크·볼륨의 3원소

Docker 기반 시스템을 이해하려면 세 가지 개념이 필요합니다. DB도 전부 이 위에서 돕니다.

### (1) 컨테이너 (Container)
프로그램 하나가 격리된 작은 가상 환경 안에서 도는 것입니다. `ada-postgres`는 "PostgreSQL이 깔린 작은 리눅스 상자"라고 보면 됩니다. 상자를 부수고 새로 만들어도(재배포) 안의 프로그램은 동일하게 다시 뜹니다.

### (2) 네트워크 (Network)
[docker-compose.yml](../docker/docker-compose.yml)의 맨 위에 정의된 `ada-net`(bridge 드라이버)이 모든 컨테이너를 한 가상 랜으로 묶습니다. 같은 네트워크에 있으면 **컨테이너 이름이 곧 호스트명**이 됩니다. 그래서 api 컨테이너가 `postgres:5432`로 접속하면 Docker의 내장 DNS가 알아서 `ada-postgres` 컨테이너의 현재 IP로 연결해 줍니다.

> 이 점이 중요한 이유: 컨테이너를 재생성하면 내부 IP가 바뀌는데, **이름으로 접속하면 IP가 바뀌어도 문제가 없습니다.** (단 nginx는 startup 시점 IP를 캐시하는 예외가 있어 재배포 시 nginx를 재시작합니다 — deploy.yml 참고.)

### (3) 볼륨 (Volume)
컨테이너 안의 파일은 컨테이너를 지우면 함께 사라집니다. 그래서 **영구 보관할 데이터는 "볼륨"이라는 별도 저장 공간에 둡니다.** compose 상단의 `volumes:` 블록에 선언된 것들:

```yaml
volumes:
  postgres_data:   # PostgreSQL 실제 데이터 파일
  minio_data:      # MinIO 가 저장하는 파일 객체
  mlflow_data:     # MLflow 작업 파일
  vault_data:      # Vault 금고 데이터
  models_cache:    # HuggingFace 가중치 캐시(워커)
  hf_model_cache:  # HuggingFace 캐시(api)
```

볼륨은 컨테이너와 수명이 분리되어 있습니다. **컨테이너를 지워도(`down`) 볼륨은 남습니다.** 그래서 재배포해도 DB 데이터가 보존됩니다. 단 `down -v`처럼 `-v`를 붙이면 볼륨까지 삭제되어 **데이터가 영구 소멸**합니다(30장 금지사항).

---

## 4장. 데이터의 "수명" — 영구 vs 휘발 vs 파생

저장소를 이해하는 가장 좋은 축은 "이 데이터가 사라지면 큰일 나는가?"입니다. ADA의 데이터는 세 가지 수명으로 나뉩니다.

### (A) 영구 데이터 (사라지면 안 됨)
- PostgreSQL `autoai` DB의 모든 테이블 (사용자, 작업, KB 등)
- MinIO의 원본 업로드, 최종 모델, 산출물
- → **백업 대상**(24장). 이게 진짜 자산입니다.

### (B) 휘발 데이터 (사라져도 됨)
- Redis의 작업 큐, 캐시
- → 메모리에만 있고, 재시작하면 비워질 수 있습니다. 처리 중이던 작업이 날아가면 다시 돌리면 됩니다. **백업하지 않습니다.**

### (C) 파생 데이터 (재생성 가능)
- HuggingFace 모델 캐시(`models_cache`, `hf_model_cache`) — 지워도 다시 다운로드됨
- MLflow 메타의 일부 — 재현 가능한 실험은 다시 돌릴 수 있음
- → 백업하면 좋지만 필수는 아닙니다.

이 분류가 중요한 이유: **장애가 났을 때 "무엇을 살려야 하고 무엇은 버려도 되는지"** 를 즉시 판단할 수 있기 때문입니다. Redis가 날아가면 침착하게 작업만 다시 돌리면 되고, PostgreSQL이 날아가면 백업에서 복구해야 합니다(28장).

---

## 5장. "어디에 무엇을 저장하는가" 결정 규칙

새 기능을 만들 때 "이 데이터를 어디에 둘까?"는 자주 나오는 질문입니다. ADA의 암묵적 규칙은 이렇습니다.

```
이 데이터는...
├─ 구조가 있고(행/열), 조회·조인·제약이 필요한가?      → 🐘 PostgreSQL 테이블
├─ AI 임베딩 벡터인가? (유사도 검색 필요)              → 🐘 PostgreSQL + pgvector 컬럼
├─ 큰 파일/바이너리인가? (CSV, 모델, PDF)             → 🪣 MinIO (경로만 PostgreSQL에)
├─ 잠깐 쓰고 버리는 임시값/큐인가?                    → 🔴 Redis
├─ ML 실험 지표·파라미터인가?                        → 📊 MLflow (→ Postgres+MinIO)
└─ 비밀값(키/비번)인가?                              → 🔐 Vault (또는 .env)
```

여기서 가장 중요한 패턴이 **"큰 파일은 MinIO에, 그 파일의 위치(경로)는 PostgreSQL에"** 입니다. 예를 들어 사용자가 CSV를 올리면:

- 실제 CSV 바이트 → MinIO `autoai-artifacts/uploads/...`
- `uploads` 테이블에는 `minio_path`, `filename`, `sha256`, `size_bytes` 같은 **메타데이터만** 저장

이렇게 하면 DB는 가볍고 빠르게 유지되고, 큰 데이터는 창고에 안전하게 보관됩니다. 이 "포인터(경로)와 실체(파일)의 분리"는 11·20장에서 반복해서 보게 될 핵심 패턴입니다.

---

# 제2부 — PostgreSQL 초심층

## 6장. PostgreSQL이 본체인 이유

다섯 저장소 중 PostgreSQL이 "본체"인 이유는 명확합니다. **시스템의 진실(source of truth)이 여기 있기 때문**입니다. 사용자가 누구인지, 어떤 작업이 어디까지 진행됐는지, 무엇을 학습했는지가 전부 PostgreSQL에 기록됩니다. 다른 저장소는 이 진실을 보조합니다.

PostgreSQL을 택한 구체적 이유:

1. **ACID 트랜잭션** — 작업 상태를 갱신하다 중간에 실패해도 데이터가 깨지지 않습니다. "절반만 저장된" 상태가 없습니다.
2. **강력한 관계 모델** — 작업(job)과 그 작업의 에이전트 실행(agent_runs), 산출물(outputs)이 외래키로 단단히 연결됩니다(16장).
3. **JSONB** — 정형 + 비정형을 한 컬럼에 담습니다. 유연한 페이로드(`payload`, `metrics`)를 그대로 저장하면서도 인덱싱·쿼리가 됩니다.
4. **pgvector 확장** — AI 임베딩 벡터를 같은 DB 안에서 저장·검색합니다(13·32장). 별도 벡터 DB를 두지 않아도 됩니다.
5. **성숙도** — 수십 년 검증된 오픈소스. 확장·도구·인력이 풍부합니다.

> 우리가 쓰는 이미지는 평범한 `postgres:16`이 **아니라** `pgvector/pgvector:pg16`입니다. PostgreSQL 16에 pgvector가 미리 깔린 버전입니다. compose에도 "postgres:16-alpine 절대 X"라는 주석이 달려 있는데, 평범한 이미지로 바꾸면 임베딩 기능이 전부 깨지기 때문입니다.

---

## 7장. 한 인스턴스, 두 데이터베이스 (autoai · mlflow)

여기서 사람들이 가장 많이 헷갈립니다. **PostgreSQL "서버" 하나 안에 "데이터베이스"가 두 개** 있습니다.

```
ada-postgres (PostgreSQL 서버 컨테이너)
├── autoai   ← 우리 앱의 메인 DB (모든 앱 테이블 30여 개)
└── mlflow   ← MLflow 전용 메타 DB
```

"서버"와 "데이터베이스"는 다른 개념입니다. 한 PostgreSQL 서버는 여러 데이터베이스를 담을 수 있고, 각 데이터베이스는 서로 격리된 테이블 공간을 가집니다. 우리는:

- 앱 데이터는 `autoai`에
- MLflow가 실험 메타를 저장할 곳은 `mlflow`에

따로 둡니다. [init.sql](../docker/init.sql)이 컨테이너 첫 기동 시 `mlflow` DB를 자동 생성합니다(`autoai`는 `POSTGRES_DB` 환경변수로 자동 생성).

```sql
CREATE DATABASE mlflow;
GRANT ALL PRIVILEGES ON DATABASE autoai  TO autoai;
GRANT ALL PRIVILEGES ON DATABASE mlflow  TO autoai;
```

실무에서 이게 왜 중요하냐면, psql로 접속할 때 **`-d autoai`를 빠뜨리면 엉뚱한 DB를 보게 되기 때문**입니다. "테이블이 안 보여요"의 흔한 원인이 잘못된 DB 접속입니다.

```bash
# 앱 테이블을 보려면 반드시 -d autoai
docker exec -it ada-postgres psql -U autoai -d autoai -c "\dt"
# MLflow 메타를 보려면 -d mlflow
docker exec -it ada-postgres psql -U autoai -d mlflow -c "\dt"
```

---

## 8장. init.sql과 5종 확장(extension)

PostgreSQL은 "확장(extension)"으로 기능을 추가합니다. [init.sql](../docker/init.sql)이 `autoai` DB에 5종을 설치합니다.

```sql
\c autoai
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";   -- 1
CREATE EXTENSION IF NOT EXISTS "pg_trgm";     -- 2
CREATE EXTENSION IF NOT EXISTS "btree_gin";   -- 3
CREATE EXTENSION IF NOT EXISTS vector;        -- 4 (pgvector)
CREATE EXTENSION IF NOT EXISTS pgcrypto;      -- 5
```

| 확장 | 역할 | ADA에서 쓰는 곳 |
|---|---|---|
| `uuid-ossp` | UUID(고유 식별자) 자동 생성 | 모든 테이블의 `id`가 UUID |
| `pg_trgm` | 텍스트 유사도 검색(오타 허용, LIKE 가속) | 텍스트 검색·매칭 |
| `btree_gin` | 복합 인덱스 가속 | JSONB·배열 인덱싱 |
| `vector` (pgvector) | 임베딩 벡터 저장·유사도 검색 | KB·임베딩 테이블 4종(13장) |
| `pgcrypto` | 컬럼 단위 암호화 | 민감 데이터 암호화(25장) |

`init.sql`은 **컨테이너가 빈 볼륨으로 처음 뜰 때 딱 한 번만** 실행됩니다. 이미 데이터가 있는 볼륨에서는 실행되지 않습니다. 그래서 확장이 빠졌다면 보통 볼륨을 새로 만들거나 수동으로 `CREATE EXTENSION` 해야 합니다.

확인:
```bash
docker exec -it ada-postgres psql -U autoai -d autoai -c "\dx"
# vector, pgcrypto, pg_trgm 등이 목록에 보이면 정상
```

---

## 9장. 테이블 지도 — 30여 개를 6그룹으로

[ada/db/models.py](../ada/db/models.py)에 정의된 테이블은 30개가 넘습니다. 외우려 하지 말고 **역할별 6그룹**으로 묶어서 이해하세요.

```
🐘 autoai DB
├─ ① 인증·사용자        users, oauth_accounts
├─ ② 작업 흐름          uploads, jobs, agent_runs, interactive_sessions,
│                       decisions, outputs, output_recipes
├─ ③ ML·실험           models, experiments, artifacts,
│                       model_artifact_catalog, gate_decision_metrics
├─ ④ 자가학습·KB(벡터)  self_learning_kb, dataset_embeddings, intent_embeddings,
│                       lesson_embeddings, error_kb, success_patterns, rules
├─ ⑤ 오류 자동수정      failure_logs, pending_patches, patch_applications,
│                       circuit_breaker_events, job_distillation_log
└─ ⑥ 운영·메타          agent_registry, security_audit_log, conversation_logs,
                        backup_catalog
```

models.py 첫머리 docstring은 "v1 10 + v2 14 = 24 테이블"이라고 적혀 있지만, 이후 마이그레이션으로 conversation_logs, patch_applications, circuit_breaker_events 등이 추가되어 현재 30여 개입니다. 다음 장들에서 그룹별로 핵심 테이블의 컬럼까지 봅니다.

---

## 10장. 그룹① 인증·사용자 (users, oauth_accounts)

### users — 사용자 계정
시스템의 모든 행위 주체입니다. 핵심 컬럼:

| 컬럼 | 타입 | 의미 |
|---|---|---|
| `id` | UUID | 사용자 고유 ID (다른 테이블이 FK로 참조) |
| `email` | String, unique | 로그인 이메일 |
| `role` | String(16) | 권한: `analyst`(기본) / `admin` |
| `password_hash` | String | 비밀번호 해시 (구글 전용 사용자는 NULL) |
| `name` | String | 구글 프로필 이름(표시용) |
| `is_active` / `is_verified` | Boolean | 활성/이메일 인증 여부 |
| `mfa_secret` | Text | 2단계 인증 비밀 |
| `last_login_at` | DateTime | 마지막 로그인 |

`role`이 운영 콘솔 접근을 가릅니다. 관리자 기능은 `role='admin'`일 때만 노출됩니다.

### oauth_accounts — 소셜 로그인 연동
구글 OAuth(migration 0005)로 추가되었습니다. 한 사용자가 여러 소셜 계정을 연결할 수 있는 1:N 구조입니다.

| 컬럼 | 의미 |
|---|---|
| `user_id` | users.id FK (`ondelete=CASCADE` — 사용자 삭제 시 함께 삭제) |
| `provider` | `'google'` |
| `provider_account_id` | 구글 sub(고유 ID) — 이것으로 같은 구글 계정을 식별 |
| `(provider, provider_account_id)` | UNIQUE 제약 — 같은 구글 계정 중복 연결 방지 |

설계 철학: **인증은 구글에 위임하고 우리는 비밀번호를 저장하지 않습니다.** 구글 전용 사용자는 `users.password_hash`가 NULL입니다. 비밀번호를 안 갖고 있으니 유출 위험도 그만큼 줄어듭니다.

---

## 11장. 그룹② 작업 흐름 (uploads~outputs)

사용자가 "데이터 분석"을 한 번 요청하면 이 그룹의 테이블들이 차례로 채워집니다. 이 그룹이 ADA의 **본업**입니다.

### uploads — 업로드한 데이터셋 메타
```
실제 파일 → MinIO,  메타 → 이 테이블 (5장의 "포인터/실체 분리")
```
| 컬럼 | 의미 |
|---|---|
| `file_id` | 업로드 고유 ID |
| `filename`, `size_bytes`, `original_mime` | 파일 정보 |
| `sha256` | 파일 무결성 해시(중복·변조 탐지, 인덱스 있음) |
| `minio_path` | 실제 파일이 있는 MinIO 경로 ★ |
| `category` | 4분류: `tabular_ml` / `tabular_dl` / `timeseries` / `anomaly_detection` |
| `pii_scan_status`, `pii_columns` | 개인정보(PII) 스캔 결과(25장) |

### jobs — 분석 작업 1건
작업 하나 = 1 row. 진행 상태의 중심입니다.

| 컬럼 | 의미 |
|---|---|
| `status` | `pending` → `running` → `completed`/`failed` |
| `category`, `target_column`, `user_question` | 무엇을 분석할지 |
| `current_gate` | 현재 게이트 `G1`~`G6` (대화형 의사결정 단계) |
| `requested_outputs` | 요청 산출물 `["OUT-01","OUT-04"]` (JSONB) |
| `retry_count`, `error_message` | 재시도·오류 |

`jobs`는 `agent_runs`, `models`, `outputs`와 1:N 관계이며 `cascade="all, delete"` — **작업을 지우면 딸린 기록도 함께 삭제**됩니다(16장).

### agent_runs — 에이전트 실행 기록
작업 처리 중 각 에이전트(데이터 프로파일러, EDA 등)가 한 번 돌 때마다 1 row.

| 컬럼 | 의미 |
|---|---|
| `agent_name`, `gate` | 어떤 에이전트가 어느 게이트에서 |
| `status`, `duration_ms`, `error` | 결과·소요시간·오류 |
| `input_tokens`, `output_tokens` | LLM 토큰 사용량(비용 추적) |
| `payload` | Pydantic 직렬화 결과(JSONB) |

### interactive_sessions / decisions — 대화형 게이트
ADA는 중간중간 사용자에게 "이 방법들 중 뭘로 할까요?"를 묻습니다. 그 제안(`proposals`)과 사용자의 선택(`user_choice`), 자동 해결 여부(`auto_resolved`), 응답 지연시간을 기록합니다. `decisions`는 채택된 순위(`adopted_rank`)와 근거(`rationale`)를 남깁니다.

### outputs / output_recipes — 산출물
| `outputs` 컬럼 | 의미 |
|---|---|
| `output_code` | `OUT-01`~`OUT-04`, `OUT-07` (PPT/PDF/대시보드 등) |
| `minio_path` | 산출물 파일 위치(MinIO) |
| `file_size_bytes`, `generation_ms` | 크기·생성 시간 |

`output_recipes`는 "이런 의도(`intent_pattern`)면 이런 산출물(`recommended_outputs`)을 추천"이라는 학습된 추천 규칙입니다.

---

## 12장. 그룹③ ML·실험 (models~gate_decision_metrics)

학습이 일어나면 채워지는 테이블들입니다.

### models — 학습된 모델
| 컬럼 | 의미 |
|---|---|
| `model_name`, `framework` | 모델 종류·프레임워크 |
| `metrics` | 성능 지표(JSONB) |
| `minio_path` | 모델 가중치 파일 위치(MinIO) |
| `mlflow_run_id` | 연결된 MLflow 실험 run |
| `is_best` | 최고 성능 모델 표시 |
| `model_sha256` | 모델 무결성 해시(R-704 보안) |

여기서도 패턴이 동일합니다 — **모델 가중치(큰 파일)는 MinIO, 메타는 PostgreSQL.** 그리고 `mlflow_run_id`로 MLflow와 연결되어, PostgreSQL·MinIO·MLflow 세 저장소가 하나의 모델을 둘러싸고 협력합니다.

### experiments / artifacts
- `experiments` — MLflow 실험과 매핑(카테고리·상태)
- `artifacts` — 작업이 생성한 부가 산출물의 MinIO 경로

### model_artifact_catalog — 모델 무결성 카탈로그
`sha256`, `cosign_sig`(서명), `verified` — 배포된 모델이 변조되지 않았음을 검증하는 공급망 보안 장치입니다.

### gate_decision_metrics — 게이트 의사결정 품질
AI가 제안한 순위(`proposed_rank`)와 사용자가 실제 고른 순위(`adopted_rank`)가 일치(`match`)했는지를 기록합니다. **AI 추천이 얼마나 정확한지**를 측정하는 데이터로, 시스템 개선의 근거가 됩니다.

---

## 13장. 그룹④ 자가학습·KB와 pgvector

이 그룹이 ADA를 평범한 분석 도구와 구별 짓는 **"스스로 배우는"** 부분입니다. 핵심 기술은 pgvector를 이용한 **의미 기반 검색(semantic search)** 입니다.

### 임베딩이란?
텍스트나 데이터의 "의미"를 768개의 숫자(벡터)로 압축한 것입니다. 의미가 비슷하면 벡터도 가깝습니다. 그래서 "이 작업과 비슷했던 과거 작업"을 키워드가 아니라 **의미로** 찾을 수 있습니다. ADA는 모든 임베딩을 `Vector(768)` 타입 컬럼에 저장합니다.

### self_learning_kb — 자가학습 지식의 중심
"5종 KB를 통합한 단일 권위 테이블"입니다.

| 컬럼 | 의미 |
|---|---|
| `kb_type` | `success_pattern` / `recipe` / `eda_template` / `hpo_warm_start` / `failure_lesson` |
| `payload` | 지식 본문(JSONB) |
| `embedding` | `Vector(768)` — 유사도 검색용 ★ |
| `confidence` | 신뢰도(0~1). 시간이 지나거나 실패하면 감소(R-504/505) |
| `success_count` | 재사용 성공 횟수 |
| `source_job_ids` | 이 지식이 어느 작업들에서 추출됐는지(UUID 배열) |
| `created_by` | 작성자(RLS 격리용) |

### 임베딩 전용 테이블 3종
검색 대상별로 분리되어 있습니다.
- `dataset_embeddings` — 업로드 데이터셋의 임베딩
- `intent_embeddings` — 사용자 의도(질문)의 임베딩
- `lesson_embeddings` — KB 교훈의 임베딩 (`kb_id` UNIQUE — `ON CONFLICT DO UPDATE` 패턴, migration 0003)

### error_kb — 오류 해결 지식
| 컬럼 | 의미 |
|---|---|
| `error_hash` | 오류 지문(중복 제거) |
| `fingerprint` | stage/model/error_type (JSONB) |
| `resolution` | 해결 방법 |
| `patch_minio_path` | 자동 패치 위치 |
| `success_count`/`fail_count`/`confidence` | 이 해결책의 신뢰도 |

### rules / success_patterns
- `rules` — 시스템 규칙(R-코드). `pgvector_embedding`으로 규칙도 의미 검색 가능. `superseded_by`로 버전 교체 추적.
- `success_patterns` — v1 호환 테이블. v2에서는 `self_learning_kb`가 권위이므로 신규 INSERT 금지(주석에 명시).

### pgvector 유사도 검색은 어떻게?
```sql
-- 주어진 벡터와 가장 가까운(코사인 거리) KB 5건 찾기
SELECT id, payload, confidence
FROM self_learning_kb
ORDER BY embedding <=> '[0.12, -0.03, ...]'::vector   -- <=> : 코사인 거리 연산자
LIMIT 5;
```
`<=>`가 pgvector가 추가하는 거리 연산자입니다. 이 한 줄로 "의미가 가장 비슷한 과거 사례"를 즉시 찾습니다. RAG(검색증강생성)의 핵심이며, 룰 R-501에 따라 검색 결과는 인용이 강제됩니다.

---

## 14장. 그룹⑤ 오류 자동수정 (failure_logs~circuit_breaker_events)

ADA는 오류가 나면 **스스로 고치려 시도**합니다(self-healing). 이 그룹이 그 두뇌입니다.

### failure_logs — 실패 로그
오류가 나면 여기 기록됩니다. Celery **beat**가 30초마다 미처리 항목을 폴링해 자동수정을 트리거합니다.

| 컬럼 | 의미 |
|---|---|
| `error_hash` | 오류 지문(같은 오류 묶기, 인덱스) |
| `error_message`/`stack_trace` | **redactor 통과한** 평문(PII 제거됨) |
| `raw_error_encrypted` | AES-GCM 암호화된 원본(LargeBinary) — PII 보호+디버깅용 |
| `redaction_types` | 마스킹한 종류 `["EMAIL","PHONE"]`(감사용) |
| `classified_as` | 5종 분류(transient/code_bug/config/data/user_input) |
| `severity` | low/normal/high/critical (알림·SLA 우선순위) |
| `auto_handled_by_kb` | KB로 자동 처리됐는지 |

특이점: **부분 인덱스** `idx_failure_logs_hash_unhandled`가 `auto_handled_by_kb=False`인 행만 인덱싱합니다. 폴링 데몬이 "아직 안 고친 것"만 빠르게 찾기 위함입니다.

### pending_patches / patch_applications
- `pending_patches` — 제안된 패치. `review_status`: `pending`(검토대기) / `approved` / `rejected` / `auto_applied`(자동적용) / `apply_failed`.
- `patch_applications` — 패치 적용 시도 감사 로그. `applied_by`(봇 또는 사람), `git_commit_sha`, `rollback_commit_sha`, `sandbox_validation`(검증 결과), `status`.

### circuit_breaker_events — 회로차단기
외부 LLM(Ollama, Claude CLI) 호출이 연속 실패하면 잠시 호출을 끊어 시스템을 보호합니다. 그 상태 전이(`opened`/`half_open`/`closed`)를 영구 기록합니다(실시간 상태는 Redis에).

### job_distillation_log — 지식 증류 로그
끝난 작업에서 어떤 지식(KB)을 추출(distill)했는지 추적합니다.

---

## 15장. 그룹⑥ 운영·메타 (agent_registry~conversation_logs)

### agent_registry — 에이전트 레지스트리
시스템의 모든 에이전트 명세입니다.

| 컬럼 | 의미 |
|---|---|
| `agent_name`, `role`, `description` | 에이전트 정체성 |
| `llm_model` | 쓰는 모델(`claude-sonnet-4-6` 등 또는 `none`) |
| `persona`, `persona_version` | 페르소나(프롬프트 정체성)와 버전 |
| `inputs`/`outputs`/`capabilities` | 입출력·능력(JSONB) |

`persona`는 200자 제한 CheckConstraint가 걸려 있고, 변경 시 `persona_version`도 함께 올려야 합니다(R-007).

### security_audit_log — 보안 감사 로그
누가 언제 무엇에 접근했는지 전부 기록합니다.

| 컬럼 | 의미 |
|---|---|
| `event_type` | login/logout/api/agent/kb/output/security |
| `actor_user_id`, `actor_role` | 행위자 |
| `resource`, `action`, `result` | 대상·행위·결과(success/failure/blocked) |
| `ip_address`, `user_agent`, `details` | 맥락 |

### conversation_logs — 팀 Q&A 수집
팀원이 Claude Code로 나눈 대화(질문+답변)를 저장해 **KB 학습의 원천**으로 씁니다.
```
VS Code Stop 훅 → POST /kb/conversation → conversation_logs
   → 리눅스 서버 동기화 → 임베딩 → self_learning_kb → processed=True
```

### backup_catalog — 백업 카탈로그
백업 산출물(db/data/vault)의 위치·해시·크기·상태 기록입니다.

---

## 16장. 외래키·관계·CASCADE 동작 원리

테이블은 외래키(FK)로 연결됩니다. ADA는 두 가지 삭제 정책을 씁니다.

### ON DELETE CASCADE (함께 삭제)
부모가 사라지면 자식도 사라집니다.
```
jobs ──(CASCADE)──▶ agent_runs, models, outputs, experiments,
                     artifacts, interactive_sessions, ...
users ─(CASCADE)──▶ oauth_accounts
```
즉 **작업 하나를 지우면** 그 작업의 모든 실행 기록·모델·산출물이 자동으로 정리됩니다. 고아 데이터(부모 없는 자식)가 남지 않습니다.

### ON DELETE SET NULL (연결만 끊기)
```
users ─(SET NULL)─▶ uploads.user_id, jobs.user_id
```
사용자를 지워도 **업로드·작업 기록은 보존**하되 사용자 연결만 NULL로 만듭니다. 통계·감사를 위해 작업 이력 자체는 남겨야 하기 때문입니다.

### SQLAlchemy relationship
models.py에서 `relationship(..., back_populates=..., cascade="all, delete")`로 양방향 탐색을 정의합니다. 예: `job.agent_runs`로 작업의 실행들을, `agent_run.job`으로 역방향을 즉시 가져옵니다.

> 설계 의도: **삭제 정책 하나로 데이터 정합성을 DB가 강제**합니다. 앱 코드가 깜빡해도 DB가 고아·모순을 막습니다. 이것이 관계형 DB를 본체로 택한 핵심 이유 중 하나입니다(6장).

---

# 제3부 — 연결·운영·내부동작

## 17장. 앱은 어떻게 DB에 연결되나 (config → session)

연결 정보는 [ada/core/config.py](../ada/core/config.py)에 한곳으로 모입니다.

```python
database_url        = "postgresql://autoai:changeme@postgres:5432/autoai"  # 기본값
redis_url           = "redis://redis:6379/0"
minio_endpoint      = "minio:9000"
minio_bucket        = "autoai-artifacts"
mlflow_tracking_uri = "http://mlflow:5000"
```

실제 비밀값(비밀번호 등)은 코드에 박지 않고 **`.env`에서 주입**됩니다(룰 R-001: 시크릿 하드코딩 금지). `validation_alias`로 환경변수명과 매핑됩니다.

호스트명 `postgres`/`redis`/`minio`는 3장에서 본 Docker 네트워크 컨테이너 이름입니다. 그래서:
- **컨테이너 안**에서는 `postgres:5432`
- **VPS 호스트**에서 직접 붙을 땐 published 포트 `localhost:5433`

[migrations/env.py](../migrations/env.py) 주석에도 "도커 안: postgres:5432, 호스트: localhost:5433"이라고 명시되어 있습니다. 이 차이를 모르면 "연결이 안 돼요"의 절반이 발생합니다.

---

## 18장. 비동기 SQLAlchemy와 풀 전략의 비밀

[ada/db/session.py](../ada/db/session.py)는 ADA에서 가장 섬세한 코드 중 하나입니다.

### 비동기(async)
모든 DB 접근은 비동기입니다. `asyncpg` 드라이버를 쓰며, URL을 자동 변환합니다.
```python
postgresql://...  →  postgresql+asyncpg://...
```

### 풀 전략이 환경마다 다르다 ★
커넥션 풀(연결 재사용 주머니)을 **API와 워커가 다르게** 씁니다.

| 환경 | 풀 | 이유 |
|---|---|---|
| API(uvicorn) | `QueuePool` (재사용) | 단일 장수 이벤트루프 → 커넥션 재사용이 빠름 |
| Celery 워커/beat | `NullPool` (매번 새로) | 태스크마다 `asyncio.run()`으로 새 루프 생성 |

왜 워커는 NullPool인가? Celery 워커는 태스크마다 새 이벤트루프를 만듭니다. QueuePool에 캐시된 asyncpg 커넥션은 **그 커넥션을 만든 (이미 닫힌) 루프에 묶여** 있어서, 다음 태스크의 새 루프에서 재사용하면 `Event loop is closed` / `Future attached to a different loop` 오류가 납니다. 이게 과거 작업 상태 갱신이 간헐적으로 실패하던 근본 원인이었습니다.

→ 해결: 워커에서는 NullPool로 **매 세션마다 현재 루프에 묶인 새 커넥션을 만들고 세션 종료 시 즉시 닫아** 루프 간 재사용을 원천 차단합니다. 워커 태스크는 초·분 단위라 커넥션 생성 오버헤드(수 ms)는 무시할 수 있습니다.

감지는 자동입니다 — 프로세스 argv에 `celery`와 `worker`/`beat`가 있으면 NullPool. 환경변수 `ADA_DB_POOL=null|pool`로 강제 오버라이드도 가능합니다.

### 세션 사용 패턴
- FastAPI 라우터: `get_db()` 의존성 — yield 후 자동 commit, 예외 시 rollback
- 워커: `AsyncSessionLocal()` 직접 사용 (get_db 쓰지 말 것 — session.py 주석에 명시)

---

## 19장. Redis — 큐·캐시·회로차단기

Redis는 메모리 기반 초고속 저장소로, ADA에서 세 가지 일을 합니다.

1. **Celery 메시지 브로커** — 무거운 작업을 워커에게 전달하는 작업 대기열. api가 작업을 큐에 넣으면(`redis://redis:6379/0`) 워커들이 꺼내서 처리합니다. 우리 워커는 큐별로 분리되어 있습니다: `pipeline`, `training`, `output`, `harness`.
2. **결과 백엔드/캐시** — 짧은 캐시·중간 상태.
3. **회로차단기 실시간 상태** — 외부 LLM 차단 상태(영구 기록은 PostgreSQL `circuit_breaker_events`).

설정([compose:83](../docker/docker-compose.yml#L83)):
```yaml
command: ["redis-server", "--maxmemory", "256mb", "--maxmemory-policy", "allkeys-lru"]
```
- 최대 256MB. 넘으면 `allkeys-lru`로 **가장 오래 안 쓴 키부터 자동 삭제**.
- 볼륨이 없습니다 → **재시작하면 데이터가 비워질 수 있습니다.** 영구 데이터를 절대 Redis에만 두면 안 됩니다(4장).

beat가 거는 4개 주기 작업(compose 주석):
```
ada-error-handler-scan (30초)  — FailureLog 폴링 → 자동수정 승급
ada-kb-decay-daily     (24시간) — 60일 미사용 KB confidence 감쇠(R-505)
ada-kb-retract-daily   (24시간) — confidence<0.20 KB 철회(R-504)
ada-fixer-promote-daily(24시간) — 검증된 fixer 승급
```

---

## 20장. MinIO — 우리만의 S3

MinIO는 AWS S3와 **완전히 같은 API**를 쓰는 자체 호스팅 오브젝트 스토리지입니다. 즉 AWS 비용 없이 S3처럼 쓰고, 나중에 진짜 S3로 옮겨도 코드가 그대로입니다.

- 버킷: `autoai-artifacts` (`MINIO_BUCKET`)
- 저장물: 업로드 원본, 모델 가중치, 산출물(PPT/PDF), 백업, MLflow 아티팩트
- 포트: API `127.0.0.1:9100`(→내부 9000), 웹 콘솔 `127.0.0.1:9101`(→내부 9001)
- 자격증명: `.env`의 `MINIO_ACCESS_KEY`/`MINIO_SECRET_KEY` (MinIO 내부적으로 `MINIO_ROOT_USER/PASSWORD`로 매핑)

왜 파일을 DB가 아니라 여기에? (5장 복습) 큰 바이너리를 관계형 DB에 넣으면 DB가 비대해지고 백업·쿼리가 느려집니다. 오브젝트 스토리지는 대용량 파일에 최적화되어 있고, DB에는 **경로(`minio_path`)만** 저장해 둘을 연결합니다.

외부 PC에서 콘솔을 보려면 SSH 터널이 필요합니다(localhost 바인딩이라):
```bash
ssh -L 9101:127.0.0.1:9101 ada@115.68.216.191
# → 로컬 브라우저에서 http://localhost:9101
```

---

## 21장. MLflow — Postgres와 MinIO를 빌려 쓰는 노트

MLflow는 "어떤 모델을 어떤 설정으로 학습했고 성능이 얼마였나"를 기록·비교하는 실험 추적 도구입니다. 룰 R-201: **모든 학습은 MLflow run으로 기록.**

핵심은 **MLflow가 독립 저장소가 아니라는 점**입니다. 자기 데이터를 두 곳에 나눠 저장합니다([compose:137](../docker/docker-compose.yml#L137)):

```
mlflow server
  --backend-store-uri  postgresql://...@postgres:5432/mlflow   ← 메타(파라미터·지표)
  --default-artifact-root  s3://autoai-artifacts/mlflow         ← 아티팩트(모델 파일)
```

```
       ┌─────────── MLflow (UI/서버) ───────────┐
       │                                          │
   📊 실험 비교 화면        🐘 mlflow DB (지표)   🪣 MinIO (모델 파일)
```

그래서 **MLflow 문제는 사실 Postgres나 MinIO 문제일 때가 많습니다.** MLflow가 안 뜨면 의존하는 postgres/minio가 healthy인지 먼저 봐야 합니다(compose의 `depends_on`이 둘의 healthy를 기다립니다).

웹 UI: `127.0.0.1:5000` (외부는 SSH 터널).

---

## 22장. Vault — 시크릿 금고

Vault는 API 키·비밀번호 같은 민감값을 코드·`.env` 대신 안전하게 보관·배포하는 전용 금고입니다. `sec` 프로파일이라 항상 켜지지는 않습니다.

- 포트: `127.0.0.1:8200`
- 데이터: `vault_data` 볼륨
- `cap_add: IPC_LOCK` — 비밀을 메모리에 잠가 스왑(디스크 유출) 방지
- `no-new-privileges` 보안 옵션

현재 ADA의 1차 시크릿 관리는 `.env` + **SOPS(age) 암호화**입니다([docs/server/secrets.md](server/secrets.md)). `.env.sops`(암호화본)를 git에 버전관리하고 평문 `.env`는 권한 600으로 서버에만 둡니다. Vault는 더 본격적인 시크릿 관리로의 확장 경로입니다.

---

## 23장. 마이그레이션 — 스키마의 버전 관리

테이블 구조를 바꿀 때 **직접 `ALTER TABLE` 하지 않습니다.** 대신 **Alembic 마이그레이션**으로 변경을 코드로 남겨 버전 관리합니다. [migrations/versions/](../migrations/versions/):

```
001_initial_v2_schema.py        ← 최초 전체 스키마 + RLS 정책
002_conversation_log.py         ← conversation_logs 추가
003_lesson_embeddings_unique.py ← lesson_embeddings UNIQUE 제약
004_autofix_phase2_schema.py    ← 오류 자동수정 2단계 (암호화·분류 컬럼)
005_oauth_login.py              ← 구글 OAuth 컬럼/테이블
```

왜 이렇게? 마이그레이션은 **누가·언제·왜 스키마를 바꿨는지의 역사**이며, 어느 환경에서든 `upgrade`로 동일한 구조를 재현할 수 있게 합니다. 손으로 `ALTER`하면 환경마다 스키마가 달라져 재현 불가능해집니다.

명령(VPS api 컨테이너 안):
```bash
docker exec -it ada-api alembic current      # 현재 적용 버전
docker exec -it ada-api alembic history      # 전체 이력
docker exec -it ada-api alembic upgrade head # 최신까지 적용
```

> ⚠️ 새 마이그레이션 추가는 **HJ(인프라) 단독 영역**입니다. 다른 담당자는 직접 만들지 말고 HJ와 협의하세요. [ada/db/session.py](../ada/db/session.py)의 `init_db()`(부팅 시 `create_all`)는 개발/테스트용이고, **운영은 Alembic이 우선**입니다.

---

## 24장. 백업과 복구 — Pull 방식의 이유

[docs/server/backup.md](server/backup.md) 기준, ADA는 **Pull 백업**을 씁니다.

```
[학원 백업 서버] ──SSH──▶ [VPS ada-postgres] ──pg_dump──▶ [백업 서버에 저장]
```

- **VPS는 수동적**입니다. SSH 인가 키만 등록되어 있고, 백업 스케줄·제어권은 외부 백업 서버에 있습니다.
- **VPS에 백업 cron을 만들면 안 됩니다**(중복 실행). 실제로 2026-06-09에 VPS에 잘못 있던 push 백업 cron 3개를 제거했습니다.

왜 Pull인가? 백업 주체와 백업 대상을 분리하면, **VPS가 통째로 침해당해도 백업본은 별도 서버에 안전**합니다. VPS가 백업을 밀어내는(push) 구조라면 VPS를 장악한 공격자가 백업도 오염시킬 수 있습니다.

복구 절차:
```bash
# 1) 백업 서버에서 최신 덤프 확인
# 2) VPS ada-postgres 컨테이너에 복구
docker exec -i ada-postgres psql -U autoai autoai < backup_YYYYMMDD.sql
# 3) MinIO 아티팩트는 별도 MinIO 백업에서 복원
```

백업 대상(4장 복습): PostgreSQL `autoai`(필수), MinIO 객체(필수). Redis는 휘발성이라 제외.

---

## 25장. 보안 — RLS·암호화·PII·네트워크 격리

ADA의 데이터 보안은 여러 겹입니다.

### (1) 네트워크 격리
모든 저장소 포트가 `127.0.0.1`에만 바인딩 → 외부 직접 접속 불가. 외부 노출은 nginx 80/443뿐. DB 접근은 SSH 터널로만.

### (2) RLS (Row-Level Security, 행 단위 격리)
PostgreSQL이 사용자별로 **자기 행만 보게** 하는 기능입니다. migration 001에 정책이 있고, KB·임베딩 테이블의 `created_by` 컬럼이 격리 키입니다. [session.py](../ada/db/session.py)에 `set_rls_user()`로 세션 변수 `ada.current_user`를 설정하는 함수가 있습니다.

> ⚠️ 현황(코드 주석 기준): `set_rls_user`가 정의돼 있으나 `get_db` 체인에서 자동 호출되지는 않습니다. 즉 RLS는 **준비됐지만 전면 활성화 전** 상태입니다. 발표 때 이 점을 정확히 말하는 게 좋습니다(34장).

### (3) 컬럼 암호화 + PII 마스킹
- `failure_logs.raw_error_encrypted` — 오류 원본을 **AES-GCM으로 암호화**해 저장. 평문 컬럼(`error_message`/`stack_trace`)에는 redactor로 PII를 제거한 것만 들어갑니다.
- `redaction_types`로 무엇을 마스킹했는지 감사. 룰 R-103: PII 로그 출력 금지(자동 마스킹).
- `pgcrypto` 확장으로 컬럼 암호화 지원.

### (4) 무결성·공급망
- `uploads.sha256`, `models.model_sha256`, `model_artifact_catalog.cosign_sig` — 파일·모델 변조 탐지·서명.

### (5) 감사
- `security_audit_log`가 모든 접근을 기록(누가/언제/무엇을/결과/IP).

---

## 26장. 성능·용량·튜닝 포인트

### PostgreSQL 튜닝([compose:59](../docker/docker-compose.yml#L59))
```
max_connections=100   shared_buffers=256MB   work_mem=8MB
maintenance_work_mem=64MB   wal_keep_size=1GB   max_wal_size=2GB
```
메모리 한도 1500M, `shm_size=256mb`(병렬 쿼리용 공유 메모리).

### 인덱스 전략
- 자주 조회하는 컬럼에 인덱스: `agent_runs.agent_name`, `uploads.sha256`, `failure_logs.error_hash`, `security_audit_log.created_at` 등.
- **부분 인덱스**: `idx_failure_logs_hash_unhandled`는 미처리 행만 인덱싱해 폴링을 가속(14장).
- **pgvector 인덱스**: 벡터가 많아지면 ivfflat/hnsw 인덱스로 근사 검색을 가속할 수 있습니다(확장 여지).

### 커넥션 풀(18장 복습)
API는 `pool_size=20`, `max_overflow=10`, `pool_pre_ping=True`(죽은 커넥션 자동 감지). 워커는 NullPool.

### 메모리 한도(compose deploy.resources.limits)
postgres 1500M / redis 300M / minio 500M / mlflow 1G — 한도를 넘으면 컨테이너가 OOM으로 재시작될 수 있으니, 데이터·트래픽 증가 시 조정 대상입니다.

---

# 제4부 — 실전

## 27장. 확인·진단 명령어 치트시트

> 전부 VPS(`ssh ada@115.68.216.191`)에서 실행. 컨테이너 안으로 들어가 점검합니다.

### 전체 상태
```bash
docker ps                       # 모든 컨테이너 떠 있나(healthy 확인)
docker compose ps               # compose 기준 상태
```

### 🐘 PostgreSQL
```bash
# 접속
docker exec -it ada-postgres psql -U autoai -d autoai
#   psql 안에서:
\l                # DB 목록 (autoai, mlflow 보여야 정상)
\dt               # autoai 테이블 전체
\d jobs           # jobs 테이블 구조
\dx               # 설치된 확장 (vector, pgcrypto ...)
SELECT count(*) FROM users;
SELECT status, count(*) FROM jobs GROUP BY status;   # 작업 상태 분포
\q

# 한 줄 쿼리
docker exec -it ada-postgres psql -U autoai -d autoai -c "\dt"
docker exec -it ada-postgres psql -U autoai -d mlflow -c "\dt"
```

### 🔴 Redis
```bash
docker exec -it ada-redis redis-cli
#   PING        → PONG
#   DBSIZE      → 키 개수
#   INFO memory → 메모리 사용량
#   KEYS *      → (주의) 전체 키
#   exit
```

### 🪣 MinIO
```bash
docker exec -it ada-minio curl -f http://localhost:9000/minio/health/live
# 콘솔(외부): ssh -L 9101:127.0.0.1:9101 ada@... → http://localhost:9101
```

### 📊 MLflow
```bash
docker exec -it ada-mlflow curl -f http://localhost:5000/health
```

### 마이그레이션
```bash
docker exec -it ada-api alembic current
docker exec -it ada-api alembic history
```

### 로그
```bash
docker logs ada-postgres --tail 50
docker logs ada-redis    --tail 50
docker logs ada-minio    --tail 50
docker logs ada-mlflow   --tail 50
```

---

## 28장. 장애 대응 플레이북

증상별로 어디를 볼지 정리합니다.

| 증상 | 의심 저장소 | 점검 |
|---|---|---|
| 로그인/사용자 조회 실패 | 🐘 PostgreSQL | `docker ps`로 ada-postgres healthy? 로그 확인 |
| 작업이 큐에 쌓이고 안 돌아감 | 🔴 Redis / 워커 | redis PING, 워커 컨테이너 살아있나 |
| 파일 업로드/다운로드 실패 | 🪣 MinIO | health 체크, 디스크 여유 |
| 실험 화면이 안 뜸 | 📊 MLflow→🐘🪣 | mlflow 의존 postgres/minio 먼저 확인 |
| 전체 사이트 502 | nginx/업스트림 | nginx 재시작(IP 재해석) |

### 자주 쓰는 조치
```bash
# 특정 저장소만 재시작 (데이터 보존)
cd /opt/ada/docker
docker compose --env-file ../.env restart postgres   # redis / minio / mlflow 동일

# 디스크 부족 시 댕글링 이미지 정리
docker image prune -f
```

### 데이터 복구가 필요한 경우 → 24장 복구 절차

> 황금률: **`down -v`는 절대 금지.** 재시작은 `restart`로, 컨테이너 재생성이 필요하면 `up -d`(볼륨 보존)로. `-v`는 데이터를 지웁니다(30장).

---

## 29장. 데이터 파이프라인 전체 흐름도

분석 작업 1건이 도는 동안 5개 저장소가 어떻게 협력하는지 한 장에 담았습니다.

```
 ① CSV 업로드
    ├─▶ 🪣 MinIO        원본 파일 저장 (autoai-artifacts/uploads/...)
    └─▶ 🐘 uploads       메타 기록 (minio_path, sha256, category, pii_scan)

 ② "분석 시작"
    ├─▶ 🐘 jobs          job 생성 (status=pending, current_gate=G1)
    └─▶ 🔴 Redis         작업을 Celery 큐(pipeline)에 적재

 ③ 워커가 큐에서 작업 실행
    ├─▶ 🐘 agent_runs    에이전트별 실행/토큰/시간 기록
    ├─▶ 🐘 *_embeddings  pgvector로 유사 사례 검색 (self_learning_kb)
    ├─▶ 🐘 interactive_sessions / decisions  대화형 게이트 기록
    ├─▶ 🔴 Redis         진행률·중간상태 갱신
    └─▶ 📊 MLflow        (학습 시) run 기록 → 🐘 mlflow DB + 🪣 MinIO
                          모델 가중치 → 🪣 MinIO, 메타 → 🐘 models

 ④ 산출물 생성 (PPT/PDF/대시보드)
    ├─▶ 🪣 MinIO        산출물 파일 저장
    └─▶ 🐘 outputs       메타 기록 + jobs.status=completed

 ⑤ 사용자 다운로드
    └─ 🐘에서 경로 읽고 ◀── 🪣에서 파일 받음

 (백그라운드 상시 — Celery beat)
    ⏰ 30초:   🐘 failure_logs 폴링 → 오류 자동수정 트리거 → pending_patches
    ⏰ 24시간: 🐘 KB confidence 감쇠/철회 (R-504/505)
    ⏰ 상시:   🐘 security_audit_log 에 모든 접근 기록
```

이 그림이 이 문서 전체의 요약입니다. **PostgreSQL이 모든 단계의 "진실"을 기록하고, MinIO가 큰 파일을, Redis가 흐름을, MLflow가 실험을 담당**합니다.

---

## 30장. 하지 말아야 할 것 모음 (안전수칙)

1. **`docker compose down -v` 금지** — `-v`는 볼륨(데이터)을 삭제합니다. 영구 소멸.
2. **영구 데이터를 Redis에만 두지 말 것** — 재시작 시 사라질 수 있음.
3. **큰 파일을 PostgreSQL에 직접 넣지 말 것** — MinIO에 넣고 경로만 DB에.
4. **직접 `ALTER TABLE` 금지** — 마이그레이션(Alembic)으로만. 새 마이그레이션은 HJ 영역.
5. **psql 접속 시 `-d autoai` 빠뜨리지 말 것** — 엉뚱한 DB를 보게 됨.
6. **`postgres:16` 평범한 이미지로 교체 금지** — pgvector가 깨짐.
7. **VPS에 백업 cron 새로 만들지 말 것** — Pull 방식이라 중복.
8. **시크릿을 코드/평문으로 커밋 금지** — `.env`(권한 600) + SOPS 암호화.
9. **TLS 개인키·평문 .env를 서버 밖으로 복사 금지.**
10. **`--no-verify`/`--force`로 가드 우회 금지.**

---

# 제5부 — 발표 예상질문 Q&A

> 발표/심사에서 나올 법한 질문과 모범 답변, 그리고 꼬리질문 대비입니다.
> 답변은 "결론 → 이유 → 근거" 순서로 말하면 설득력이 높습니다.

## 31장. 발표 Q&A ① 설계·아키텍처

**Q1. DB를 왜 여러 개나 쓰나요? 하나로 하면 안 되나요?**
A. 데이터 성격마다 최적 저장소가 다르기 때문입니다(폴리글랏 퍼시스턴스). 정형 데이터는 PostgreSQL, 큰 파일은 MinIO, 임시 큐는 Redis, 실험은 MLflow가 각각 압도적으로 잘합니다. 하나로 다 하면 모든 면에서 어중간해지고, 특히 큰 파일을 관계형 DB에 넣으면 DB가 비대해져 백업·쿼리가 느려집니다. 역할 분리로 각 저장소를 가볍고 빠르게 유지합니다.
- 꼬리질문 "복잡도가 늘지 않나?" → 늘지만 Docker Compose로 한 번에 기동/관리하고, 연결 정보를 config 한곳에 모아 통제합니다.

**Q2. 그래서 "진짜 DB"는 무엇인가요?**
A. PostgreSQL입니다. 시스템의 진실(source of truth) — 사용자, 작업, 학습 지식 — 이 전부 여기 있습니다. 나머지는 보조입니다. 예컨대 MLflow조차 자기 데이터를 PostgreSQL과 MinIO에 저장합니다.

**Q3. 왜 PostgreSQL을 골랐나요?**
A. ① ACID 트랜잭션으로 데이터 정합성 보장, ② 강력한 관계·외래키, ③ JSONB로 유연한 비정형 수용, ④ pgvector로 AI 임베딩을 같은 DB에서 처리(별도 벡터 DB 불필요), ⑤ 수십 년 검증된 성숙도. 특히 ④가 AI 플랫폼인 우리에게 결정적이었습니다.

**Q4. 데이터를 어디 저장할지 어떻게 정하나요?**
A. 규칙이 있습니다(5장). 구조적·관계형이면 PostgreSQL, 임베딩이면 pgvector 컬럼, 큰 파일이면 MinIO(경로만 DB), 임시값이면 Redis, 실험이면 MLflow, 비밀값이면 Vault/SOPS. 핵심 패턴은 "큰 파일은 창고(MinIO)에, 위치표는 장부(DB)에"입니다.

**Q5. 한 PostgreSQL에 DB가 두 개라는 게 무슨 뜻인가요?**
A. PostgreSQL "서버" 하나가 `autoai`(앱)와 `mlflow`(실험 메타) 두 데이터베이스를 담습니다. 서버는 한 프로세스, 데이터베이스는 그 안의 격리된 테이블 공간입니다. init.sql이 첫 기동 때 mlflow DB를 만듭니다.

---

## 32장. 발표 Q&A ② pgvector·AI 데이터

**Q6. pgvector가 뭔가요? 왜 중요한가요?**
A. PostgreSQL에 "벡터(임베딩) 저장·유사도 검색" 기능을 더하는 확장입니다. 텍스트·데이터의 의미를 768차원 벡터로 표현해 두면, 키워드가 아니라 **의미로** 비슷한 과거 사례를 찾을 수 있습니다. ADA의 자가학습(과거 성공/실패에서 배우기)과 RAG의 핵심 엔진입니다.

**Q7. 임베딩으로 무엇을 검색하나요?**
A. 네 종류입니다 — 데이터셋(dataset_embeddings), 사용자 의도(intent_embeddings), 학습 교훈(lesson_embeddings), 그리고 통합 지식(self_learning_kb.embedding). 새 작업이 오면 "의미가 가장 가까운 과거 KB"를 찾아 방법론을 제안합니다.

**Q8. 검색은 어떻게 동작하나요?**
A. `ORDER BY embedding <=> 질의벡터 LIMIT k` 한 줄로 코사인 거리 기준 최근접 k개를 찾습니다. `<=>`가 pgvector의 거리 연산자입니다. 데이터가 많아지면 ivfflat/hnsw 인덱스로 근사 검색을 가속할 수 있습니다.

**Q9. 별도 벡터 DB(Pinecone, Weaviate)를 안 쓴 이유는?**
A. 운영 단순성과 정합성입니다. 별도 벡터 DB를 두면 인프라가 하나 더 늘고, 메타데이터(PostgreSQL)와 벡터(벡터 DB)가 따로 놀아 동기화 문제가 생깁니다. pgvector는 **같은 트랜잭션 안에서** 메타와 벡터를 함께 다룰 수 있어 정합성이 보장됩니다. 규모가 커지면 전용 벡터 DB로 분리하는 확장 경로도 열려 있습니다.

**Q10. 학습한 지식이 틀리면요? 오래되면요?**
A. confidence(신뢰도) 메커니즘이 있습니다. 재사용 성공하면 올라가고, 60일 미사용이면 감쇠(R-505), 0.20 미만이면 철회(R-504)됩니다. beat가 매일 이를 자동 관리해 낡은 지식이 계속 쓰이는 걸 막습니다.

---

## 33장. 발표 Q&A ③ 안정성·장애·백업

**Q11. 서버가 재부팅되면 데이터가 날아가나요?**
A. 아니요. 데이터는 Docker "볼륨"에 저장되어 컨테이너와 수명이 분리됩니다. 재부팅·재배포해도 볼륨은 보존됩니다. 게다가 모든 컨테이너가 `restart: unless-stopped`이고 도커 데몬이 부팅 자동시작이라, 재부팅 후 자동으로 다시 떠서 24시간 무인 운영됩니다.

**Q12. 백업은 어떻게 하나요?**
A. Pull 방식입니다 — 외부 백업 서버가 VPS에서 pg_dump로 데이터를 끌어갑니다. VPS는 SSH 키만 등록된 수동적 역할입니다. 이렇게 백업 주체와 대상을 분리하면 VPS가 침해당해도 백업본은 안전합니다.

**Q13. 처리 중이던 작업이 중간에 죽으면요?**
A. 작업 상태는 PostgreSQL jobs 테이블에 단계별로 기록되고 `retry_count`/`error_message`가 있습니다. Redis 큐의 작업이 날아가면 다시 큐잉하면 됩니다(Redis는 휘발성 임시 데이터라 유실돼도 치명적이지 않습니다). 정합성은 PostgreSQL의 트랜잭션이 지킵니다.

**Q14. 장애가 나면 어디부터 보나요?**
A. 증상별 플레이북이 있습니다(28장). 로그인 문제는 PostgreSQL, 작업 정체는 Redis/워커, 파일 문제는 MinIO, 실험 화면은 MLflow(그 뒤 postgres/minio). `docker ps`로 healthy 확인 후 해당 컨테이너 로그를 봅니다.

**Q15. MLflow가 죽으면 학습 기록이 사라지나요?**
A. 아니요. MLflow는 UI/서버일 뿐 데이터는 PostgreSQL(mlflow DB)과 MinIO에 있습니다. MLflow 컨테이너를 재시작해도 기록은 보존됩니다.

---

## 34장. 발표 Q&A ④ 보안·프라이버시

**Q16. DB가 외부에 노출되나요?**
A. 아니요. 모든 저장소 포트는 `127.0.0.1`(localhost)에만 바인딩되어 인터넷에서 직접 접속할 수 없습니다. 외부로 열린 건 nginx의 80/443뿐이고, DB 접근은 SSH 터널로만 가능합니다.

**Q17. 개인정보(PII)는 어떻게 보호하나요?**
A. 다층입니다. ① 로그에는 redactor가 PII를 자동 마스킹한 평문만 남깁니다(R-103). ② 오류 원본은 AES-GCM으로 암호화해 별도 컬럼(raw_error_encrypted)에 저장합니다. ③ 무엇을 마스킹했는지 redaction_types로 감사합니다. ④ 업로드 데이터는 PII 스캔(pii_scan_status)을 거칩니다.

**Q18. 사용자 간 데이터 격리는요?**
A. PostgreSQL RLS(행 단위 보안)를 설계에 반영했습니다 — KB·임베딩 테이블에 created_by 격리 키가 있고, 세션 변수로 사용자별 가시성을 제어하는 함수가 준비돼 있습니다. 다만 솔직히 말씀드리면 RLS의 전면 자동 활성화는 인증 미들웨어 연동을 마저 붙여야 하는 단계로, 현재는 준비된 상태입니다. (이 부분은 과장 없이 "준비됨"으로 답하는 게 신뢰를 줍니다.)

**Q19. 모델·파일 변조는 어떻게 막나요?**
A. SHA256 해시로 무결성을 검증합니다 — 업로드(uploads.sha256), 모델(models.model_sha256), 그리고 model_artifact_catalog의 서명(cosign_sig)으로 공급망 변조를 탐지합니다.

**Q20. 비밀값(키·비번)은 어디에 두나요?**
A. 코드에 절대 하드코딩하지 않습니다(R-001). 운영은 `.env`(파일 권한 600) + SOPS(age) 암호화로 관리하며, 암호화본(.env.sops)만 git에 버전관리합니다. 더 본격적인 관리를 위한 Vault도 sec 프로파일로 준비돼 있습니다.

---

## 35장. 발표 Q&A ⑤ 확장성·비용·운영

**Q21. 트래픽이 늘면 어떻게 확장하나요?**
A. 단계적 경로가 있습니다. ① 현재는 VPS 1대 + Docker Compose(단일 서버 정석). ② 워커는 큐별(pipeline/training/output/harness)로 이미 분리돼 있어 수평 확장이 쉽습니다. ③ DB는 커넥션 풀·인덱스·메모리 한도 조정으로 1차 대응, 이후 읽기 복제본 분리. ④ 더 커지면 Kubernetes로 오케스트레이션, MinIO→실제 S3, PostgreSQL→매니지드 DB로 이전. 코드가 S3 API·표준 SQL이라 이전 비용이 낮습니다.

**Q22. 비용은 어떻게 절감하나요?**
A. ① MinIO를 자체 호스팅해 S3 비용을 0으로(필요 시 S3 전환), ② Redis maxmemory+LRU로 메모리 상한 고정, ③ 컨테이너별 메모리 limit으로 자원 통제, ④ LLM 토큰 사용량을 agent_runs에 기록해 비용 가시화, ⑤ 댕글링 이미지 자동 정리로 디스크 절약.

**Q23. 스키마를 바꿔야 하면 어떻게 하나요?**
A. Alembic 마이그레이션으로만 변경합니다(직접 ALTER 금지). 변경이 코드로 버전 관리되어 모든 환경에서 동일 구조를 재현할 수 있습니다. 운영 반영은 `alembic upgrade head`로 무중단에 가깝게 적용합니다.

**Q24. 운영 부담이 크지 않나요?**
A. 자동화돼 있습니다. ① 매일 07:00 cron 헬스체크(컨테이너·DB·디스크·TLS 등), ② main 머지 시 GitHub Actions 자동 배포, ③ 컨테이너 자동 재시작, ④ beat의 KB·오류 자동 관리. 사람은 결과만 확인하면 됩니다.

**Q25. 이 구조의 가장 큰 강점을 한마디로?**
A. **"역할에 맞는 저장소를 쓰되, 진실은 PostgreSQL 하나로 통제한다"** 입니다. 덕분에 각 저장소는 가볍고 빠르며, 데이터 정합성은 관계형 DB가 트랜잭션으로 보장하고, AI 기능(pgvector)은 같은 DB 안에서 통합됩니다. 단순함과 강력함의 균형이 이 설계의 핵심입니다.

---

> 문서 끝. 갱신 시 근거 파일과 함께 변경 이력을 남기세요.
> 최초 작성: 2026-06-19.
