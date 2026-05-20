# ADA 인프라 셋업 가이드

> 대상: ADA 팀원 4명 (사무실 + 재택 포함)
> 작성: 인프라 담당
> 최종 갱신: 2026-05-20
> 기반 작업지시서: `work-orders/DOCKER_ENV_INVENTORY.md`, `work-orders/LINUX_DOCKER_SETUP_GUIDE.md`

이 문서는 ADA v2 의 협업·개발·운영 인프라가 어떻게 굴러가는지, 새 팀원이 첫 날 무엇을 해야 하는지를 한 페이지에서 끝낼 수 있게 정리한 것이다.

---

## 1. 전체 구조 한 장으로 보기

```
┌──────────────────────────────────────────────────────────────┐
│  팀원 4명 (사무실 + 재택)                                       │
│  - 각자 로컬 PC (Win+WSL2+Docker 또는 Linux+Docker)             │
│  - git clone → docker compose --profile core up -d              │
│  - GPU 있는 사람은 -f docker-compose.gpu.yml 추가                │
│  - 개발/디버깅/테스트 전부 본인 로컬에서 완료                       │
└──────────────────────────┬───────────────────────────────────┘
                           │  git push  (개발 완료된 코드)
                           ▼
┌──────────────────────────────────────────────────────────────┐
│  GitHub Repo  +  Actions                                       │
│  - PR: lint(ruff) + test(pytest) + Dockerfile 빌드 검증          │
│  - main 머지: GHCR 이미지 푸시 → VPS 자동 배포                    │
└──────────────────────────┬───────────────────────────────────┘
                           │  SSH (via Tailscale)
                           ▼
┌──────────────────────────────────────────────────────────────┐
│  VPS 웹서버  (iwinv hpa_2.8-g2 / 8GB / 100GB / CPU only)       │
│  - 운영 환경. 완성된 에이전트만 띄움                              │
│  - core profile 만 (학습은 안 돌림). 80/443 만 외부 공개          │
│  - 나머지 관리 포트는 Tailscale 안에서만 접근                     │
└──────────────────────────┬───────────────────────────────────┘
                           │  매일 03:00  pg_dump push + rsync
                           ▼
┌──────────────────────────────────────────────────────────────┐
│  로컬 리눅스 서버  (사무실, 저장소 전용)                          │
│  - /srv/backup/ada/postgres   : DB 일일 덤프 (14일 보존)         │
│  - /srv/backup/ada/datasets   : 대용량 데이터셋 원본              │
│  - 외부 노출 없음. Tailscale VPN 안에서만 접근                    │
└──────────────────────────────────────────────────────────────┘
```

핵심 원칙 4가지:

1. **개발은 각자 로컬, 운영은 VPS, 저장소는 로컬 리눅스 서버.** 세 역할이 명확히 분리된다.
2. **같은 코드·같은 이미지가 모든 환경에서 동작한다.** profile 로 켜고 끄는 차이만 있을 뿐.
3. **Tailscale 로 4명 + VPS + 로컬서버를 한 사설망에 묶는다.** 재택/사무실 차이 없음. 외부는 80/443 만 공개.
4. **비밀값은 GitHub Secrets + 각자 `.env`** 두 군데에만 존재. Git 에는 절대 안 들어감.

---

## 2. Compose Profile 4분리 — 이게 핵심

작업지시서 `LINUX_DOCKER_SETUP_GUIDE.md §6` 그대로 도입했다. 메모리 사양에 따라 띄울 그룹이 다르다.

| Profile | 포함 컨테이너 | 누적 메모리 | 누가 띄우나 |
|---|---|---:|---|
| **core** | postgres, redis, minio, mlflow, api, frontend, worker-pipeline, worker-harness, nginx | ~7.8GB | 모두 (개발·운영 기본) |
| **ml** | worker-training, worker-output, serving | +6.5GB | 16GB+ 로컬 PC, 학습 단계에만 |
| **sec** | vault, claude-cli-sidecar | +0.5GB | Day16~17부터, 필요할 때만 |
| **obs** | (예약) prometheus, grafana, otel | – | Day20 검증 세션에서만 |

기동 명령 패턴:

```bash
cd docker

# 개발/운영 기본 (8GB 환경에서도 OK)
docker compose --profile core up -d

# 16GB 로컬 PC 에서 학습 단계 진입
docker compose --profile core --profile ml up -d

# Day16~17 보안 작업 시
docker compose --profile core --profile ml --profile sec up -d

# 학습 끝났으면 ml 만 내리기 (메모리 회수)
docker compose --profile ml down

# 전부 내리기
docker compose down
```

**GPU 사용 (NVIDIA + nvidia-container-toolkit 설치된 팀원만)**:

```bash
docker compose \
  -f docker-compose.yml -f docker-compose.gpu.yml \
  --profile core --profile ml up -d worker-training
```

GPU override 파일 없이 그냥 띄우면 worker-training 은 CPU 모드로 동작한다.

---

## 3. 새 팀원 첫날 체크리스트 (로컬 개발 환경 세팅)

| 단계 | 무엇을 | 어디서 |
|---|---|---|
| 1 | GitHub 조직 invite 수락 + repo clone | 본인 PC |
| 2 | Docker Desktop 또는 Docker Engine 설치 확인 (`docker compose version` v2.27+) | 본인 PC |
| 3 | `cp .env.example .env` → 25개 키 채우기 (인프라 담당에게 비밀값 받기) | 본인 PC |
| 4 | `cd docker && docker compose --profile core build` | 본인 PC |
| 5 | `docker compose --profile core up -d postgres redis minio` | 본인 PC |
| 6 | 30초 대기 후 `docker compose --profile core ps` 로 healthy 확인 | 본인 PC |
| 7 | `docker compose --profile core run --rm api python tools/minio_setup.py` | 본인 PC |
| 8 | `docker compose --profile core up -d mlflow` + `python scripts/mlflow_init.py` | 본인 PC |
| 9 | `docker compose --profile core up -d` (나머지 코어 전부) | 본인 PC |
| 10 | `curl http://localhost:8000/health`, `http://localhost:8501` 으로 검증 | 본인 PC |
| 11 | SSH 키 생성, Tailscale 가입 (VPS 접근용) | 본인 PC |
| 12 | `feature/<이름>-warmup` 브랜치 만들어 README 수정 PR | 본인 PC |

이 12단계가 모두 통과되면 개발 환경 셋업 완료.

---

## 4. 일상 작업 흐름

```
본인 PC                       GitHub                      VPS
   │                            │                          │
   │ git checkout -b feat/X     │                          │
   │ docker compose --profile   │                          │
   │   core up -d (로컬 띄움)    │                          │
   │ 코드 작성/테스트            │                          │
   │ git commit / push          │─PR 생성──────────────►   │
   │                            │ CI: ruff + pytest +      │
   │                            │     3종 Dockerfile 빌드   │
   │                            │ (자동, ~10분)             │
   │                            │                          │
   │                            │ 코드 리뷰 + 머지 to main  │
   │                            │─Deploy 워크플로우 시작──►│
   │                            │                          │
   │                            │ api/frontend/worker      │
   │                            │ GHCR 푸시                │
   │                            │ ──SSH────────────────►   │ git pull
   │                            │                          │ docker compose pull
   │                            │                          │ docker compose up -d
   │                            │                          │ 헬스체크
   │                            │                          │
   │ ◄──── 배포 알림 (옵션) ────┤                          │
```

**규칙:**

- `main` 에 직접 push 금지. 무조건 PR.
- 같은 파일을 두 명이 동시에 만지지 않도록 PR 단위로 작게 자른다.
- 본인 PC 에서 `docker compose down -v` 는 함부로 치지 말 것 (DB 볼륨까지 날아간다).
- 데이터셋이 필요하면 인프라 담당에게 요청 (로컬 리눅스 서버에 보관된 원본).

---

## 5. VPS 1회 초기 셋업 (인프라 담당만)

```bash
# 0) 사용자 + docker 그룹
sudo adduser ada
sudo usermod -aG docker ada

# 1) Docker Engine 설치 (Docker 공식 가이드)
#    https://docs.docker.com/engine/install/ubuntu/

# 2) 데몬 설정 (LINUX_DOCKER_SETUP_GUIDE §4.2)
sudo tee /etc/docker/daemon.json >/dev/null <<'EOF'
{
  "log-driver": "json-file",
  "log-opts": { "max-size": "20m", "max-file": "3" },
  "storage-driver": "overlay2",
  "default-shm-size": "256M"
}
EOF
sudo systemctl restart docker

# 3) 코드 배치
sudo mkdir -p /opt/ada && sudo chown ada:ada /opt/ada
sudo -u ada git clone git@github.com:<org>/ADA.git /opt/ada
cd /opt/ada
cp .env.example .env && chmod 600 .env       # 값 채우기

# 4) 첫 기동 (core만 - VPS 8GB 한계)
cd docker
docker compose --profile core build
docker compose --profile core up -d postgres redis minio
sleep 30
docker compose --profile core run --rm api python tools/minio_setup.py
docker compose --profile core up -d mlflow
docker compose --profile core run --rm api python scripts/mlflow_init.py
docker compose --profile core up -d
docker compose --profile core ps                # 9개 모두 healthy 확인
cd ..

# 5) Tailscale (외부 공개는 80/443 만)
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up --ssh

# 6) UFW 방화벽
sudo ufw default deny incoming
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw allow from 100.64.0.0/10            # Tailscale 대역 - 관리 포트
sudo ufw enable

# 7) 백업 cron 등록 (매일 03:00 → 로컬 리눅스 서버로 DB 덤프 push)
sudo cp /opt/ada/scripts/backup_postgres.sh /usr/local/bin/
sudo chmod +x /usr/local/bin/backup_postgres.sh
(sudo crontab -l 2>/dev/null; echo "0 3 * * * /usr/local/bin/backup_postgres.sh >> /var/log/ada-backup.log 2>&1") | sudo crontab -

# 8) 주간 도커 청소
sudo tee /etc/cron.weekly/ada-docker-cleanup >/dev/null <<'EOF'
#!/bin/bash
docker system prune -af --filter "until=168h"
docker builder prune -af --filter "until=168h"
EOF
sudo chmod +x /etc/cron.weekly/ada-docker-cleanup

# 9) GitHub Secrets 등록 (브라우저)
#   VPS_HOST       : <VPS의 Tailscale hostname 또는 공인 IP>
#   VPS_USER       : ada
#   VPS_SSH_KEY    : ada 계정의 ~/.ssh/id_ed25519 내용
#   VPS_DEPLOY_DIR : /opt/ada
```

---

## 6. 로컬 리눅스 서버 1회 초기 셋업 (백업 전용)

```bash
# 백업 전용 계정 (shell 제한)
sudo adduser --disabled-password --gecos "" ada-backup
sudo mkdir -p /srv/backup/ada/{postgres,datasets}
sudo chown -R ada-backup:ada-backup /srv/backup/ada

# VPS 의 ada 계정 공개키를 authorized_keys 에 등록
sudo -u ada-backup mkdir -p /home/ada-backup/.ssh
sudo -u ada-backup vi /home/ada-backup/.ssh/authorized_keys

# Tailscale (외부 접근 절대 차단)
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up --ssh

# UFW
sudo ufw default deny incoming
sudo ufw allow from 100.64.0.0/10    # Tailscale CGNAT 대역만
sudo ufw enable
```

---

## 7. 자주 묻는 운영 시나리오

**Q. 로컬 PC 메모리 부족해서 학습이 자꾸 OOM 난다.**
- core 만 띄우고 ml 은 필요할 때만: `docker compose --profile ml up -d` → 끝나면 `--profile ml down`
- worker-output 동시성을 잠시 0으로: `docker compose pause worker-output`
- 그래도 부족하면 `docker stats` 로 누가 먹는지 확인, 메모리 한도 조정

**Q. GPU 가 있는데 워커가 CPU 만 쓴다.**
- override 파일 빠뜨림. `-f docker-compose.gpu.yml` 추가하고 다시 띄움
- `docker exec ada-worker-training nvidia-smi` 로 컨테이너 안에서 GPU 보이는지 확인

**Q. VPS 가 멈췄을 때 복구 절차는?**
1. iwinv 콘솔에서 VPS 재부팅
2. `cd /opt/ada/docker && docker compose --profile core up -d`
3. 헬스체크: `docker compose ps`, `curl localhost:8000/health`
4. DB 복구가 필요하면: 로컬 리눅스 서버에서 최신 `ada_*.sql.gz` 가져와
   `gunzip -c | docker exec -i ada-postgres psql -U autoai -d autoai`

**Q. 배포가 실패했을 때 롤백은?**
- GHCR 에 `:이전_sha` 태그가 남아있음. VPS 에서 `docker compose pull` 대신 명시적 태그로 띄우거나, GitHub Actions 에서 직전 성공 커밋으로 `workflow_dispatch` 재실행.

**Q. 재택근무자가 VPS 에 접속이 안 될 때?**
1. `tailscale status` 로 본인 노드가 active 인지 확인
2. VPN 끊고 다시 `tailscale up`
3. 그래도 안 되면 인프라 담당이 admin 콘솔에서 노드 재인증

---

## 8. 디렉토리 구조

```
ADA/                                  repo root (= VPS의 /opt/ada/)
├── .env                              (gitignore, 각자 직접 배치)
├── .env.example                      (25개 키 템플릿)
├── .dockerignore                     (※ Docker가 빌드 컨텍스트 루트에서 자동 인식 - 여기 위치 필수)
├── .gitignore
├── README.md
│
├── docker/                           ★ 도커 관련 전부 여기
│   ├── docker-compose.yml            (profile 4분리: core/ml/sec/obs)
│   ├── docker-compose.gpu.yml        (GPU override - 있는 사람만)
│   ├── Dockerfile.api                (FastAPI)
│   ├── Dockerfile.frontend           (Streamlit)
│   ├── Dockerfile.worker             (Celery - 가장 무거움)
│   ├── Dockerfile.serving            (모델 서빙, CPU)
│   ├── claude-cli-sidecar.Dockerfile (Day16~)
│   ├── init.sql                      (postgres 첫 기동 시 자동)
│   └── nginx.conf                    (리버스 프록시)
│
├── requirements/                     ★ Python 패키지 정의 (6개)
│   ├── base.txt                      (공통)
│   ├── api.txt
│   ├── worker.txt                    (ML 풀스택)
│   ├── frontend.txt
│   ├── serving.txt
│   └── dev.txt                       (이미지에는 안 들어감)
│
├── .streamlit/
│   └── config.toml                   (테마, 업로드 한도)
│
├── scripts/                          (운영 스크립트)
│   ├── backup_postgres.sh            (VPS → 로컬서버 DB 덤프)
│   ├── sync_datasets.sh              (로컬서버 ↔ VPS rsync)
│   ├── mlflow_init.py                (실험 6개 생성)
│   └── vault_seed.sh                 (Vault KV 시드)
│
├── tools/
│   └── minio_setup.py                (버킷 + prefix 생성)
│
├── .github/workflows/
│   ├── ci.yml                        (lint + test + 빌드 검증)
│   └── deploy.yml                    (main 머지 → GHCR → VPS)
│
├── docs/
│   └── INFRA_SETUP.md                (이 문서)
│
├── work-orders/                      (작업지시서 - 코드 작성 시 참조)
│   ├── DOCKER_ENV_INVENTORY.md
│   ├── LINUX_DOCKER_SETUP_GUIDE.md
│   └── ...
│
├── migrations/                       (Day02 작성 예정 - 비어있음)
├── agents/                           (Day03~Day11 작성 예정)
├── orchestrator/                     (Day04)
├── api/                              (Day06/Day13)
├── frontend/                         (Day10/Day18)
├── serving/                          (Day12)
├── pipelines/                        (Day07/Day12)
├── reports/                          (Day12/Day15 - 13종 생성기)
├── error_handler/                    (Day16)
└── tests/
```

> **`.dockerignore` 가 docker/ 안이 아니라 루트에 있는 이유**
> Docker 는 빌드 컨텍스트 루트에서 `.dockerignore` 를 자동 인식한다. 우리는
> compose 에서 `context: ..` (repo root) 로 빌드하므로, `.dockerignore` 는 반드시
> 그 루트(`/opt/ada/.dockerignore`)에 있어야 효과를 본다. docker/ 안에 두면
> Docker 가 무시한다.

---

## 9. 첫 기동 검증 체크리스트

설치/세팅 후 다음을 확인:

- [ ] `.env` 25개 키가 모두 실제 값으로 채워져 있다
- [ ] `python:3.10-slim` 베이스 (5종 Dockerfile 전부)
- [ ] postgres 이미지가 `pgvector/pgvector:pg16` (절대 `postgres:16-alpine` X)
- [ ] worker 컨테이너에 `libgomp1`, `libsndfile1`, `libgl1`, `ffmpeg`, `poppler-utils` apt 설치 완료
- [ ] GPU 사용 시 torch 휠이 `+cu121` (Pascal GTX 1060 호환)
- [ ] `requirements/worker.txt` 에 transformers/accelerate/peft 포함
- [ ] `requirements/api.txt` 에 hvac, python-jose, passlib 포함
- [ ] `requirements/frontend.txt` 에 streamlit-aggrid 포함
- [ ] `docker/init.sql` 에 `CREATE EXTENSION vector;` 포함
- [ ] MinIO 콘솔(`http://localhost:9101`)에 `autoai-artifacts` 버킷 + 6개 prefix
- [ ] MLflow UI(`http://localhost:5000`)에 6개 실험
- [ ] `.env` 가 `git status` 에 안 보임 (`.gitignore` 동작)
- [ ] `docker compose --profile core down && up -d` 재기동 후 DB 데이터 유지
- [ ] 비루트 사용자(USER 1001)로 컨테이너 실행 (`docker exec ada-api id` → uid=1001)

---

문제 생기면 #ada-infra 채널 또는 인프라 담당에게 바로 핑.
