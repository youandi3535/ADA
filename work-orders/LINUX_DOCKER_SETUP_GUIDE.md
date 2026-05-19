# ADA — Linux + Docker 환경 구축 가이드 (재설계판)

> 대상 서버: **DESKTOP-TM619N0** (Ryzen 7 3800XT 8C/16T · 16GB RAM · GTX 1060 3GB · 477GB SSD/HDD)
> 기반: 작업지시서 Day00 마스터설계서 / Day01 환경설정 / Day02 DB·인프라
> 작성일: 2026-05-18

---

## 0. 결론부터 (TL;DR)

이 하드웨어로 ADA 21일 스프린트를 끝까지 돌리는 것은 **가능하지만 타이트**합니다. 구체적인 제약과 결론:

| 자원 | 보유 | 작업지시서 권장 | 결론 |
|---|---|---|---|
| CPU | Ryzen 7 3800XT (8C/16T) | – | ✅ **충분히 좋음**. 8 물리코어 → 워커 분리에 유리 |
| RAM | **16GB** | 16GB 최소 / 32GB 권장 | ⚠️ **빠듯함**. 메모리 한도를 엄격히 낮추고 스왑 16GB 확보 필수 |
| GPU | **GTX 1060 3GB VRAM** (Pascal) | 미정 / 트랜스포머 우선 정책 | ⚠️ **VRAM 3GB는 트랜스포머에 매우 부족**. CPU 학습을 기본으로, GPU는 소형 모델만 |
| 디스크 | 477GB 중 **144GB 여유** | 100GB+ | ⚠️ **딱 1 스프린트 분량**. 정리 정책 + Docker 데이터 디렉토리 격리 필수 |

핵심 전략은 세 가지입니다.

1. **풀세트 13~16 컨테이너를 한 번에 띄우지 않는다.** Compose `profiles` 로 "핵심(core)" / "관측(obs)" / "보안(sec)" 을 분리해 필요할 때만 띄운다.
2. **트랜스포머 우선 정책을 "GTX 1060 3GB 적합 모델 한정" 으로 다운스코프**한다. 마스터 §7의 정책은 유지하되 모델 크기 상한(파라미터 ≤ 30M, batch ≤ 8) 을 둔다.
3. **디스크 자동 청소 + Docker 데이터 디렉토리 분리** — `/var/lib/docker` 가 가득 차면 시스템 전체가 멈춘다.

---

## 1. 하드웨어 진단과 의미

### 1.1 CPU: Ryzen 7 3800XT (8C/16T, 4.7GHz boost) — ★★★★★

- 정형 ML(XGBoost / LightGBM / CatBoost)은 **GPU보다 CPU가 빠른 경우도 많다**. 이 CPU면 충분.
- 4종 Celery 워커(`pipeline=4, training=2, output=2, harness=1`)의 합산 동시성 9가 코어 8개에 잘 들어맞는다.
- Postgres·MinIO·MLflow의 백그라운드 부하도 흡수 가능.
- 결론: **CPU는 병목이 아니다.**

### 1.2 RAM: 16GB — ★★ (가장 큰 제약)

작업지시서 Day01의 기본 메모리 한도를 그대로 쓰면 합산이 16GB를 초과한다.

| 컨테이너 | Day01 기본 한도 | **재설계 한도** | 비고 |
|---|---|---|---|
| api | 2GB | **1.5GB** | uvloop + asyncpg 풀 20 |
| worker-pipeline | 4GB | **2.5GB** | concurrency 4 → 2로 하향 |
| worker-training | 8GB | **4GB** | concurrency 1, GPU 사용 시에만 |
| worker-output | 2GB | **1.5GB** | PPT/PDF 생성 일시 메모리 |
| worker-harness | 1GB | **0.5GB** | KB 증류 백그라운드 |
| postgres | 1GB | **1.5GB** | shared_buffers 256MB 유지 |
| redis | 0.5GB | **0.3GB** | maxmemory 256MB + LRU |
| minio | 1GB | **0.5GB** | 단일 노드 |
| mlflow | 0.5GB | **0.3GB** | – |
| frontend (streamlit) | 1GB | **0.5GB** | – |
| serving | 1GB | **on-demand** | 항상 안 띄움. 평가 단계에만 |
| vault | 0.2GB | **0.2GB** | dev 모드 |
| claude-cli-sidecar | 0.3GB | **0.3GB** | 호출 시에만 활성 |
| 합계(상시) | – | **~9.6GB** | 호스트 OS 2.5GB 제외하면 안전권 |
| 합계(학습 + 산출물 동시) | – | **~13.6GB** | 스왑 동원 |

**필수 조치**:
- **스왑 16GB 확보** (`/swapfile`) + `vm.swappiness=10`
- `serving`, `worker-output`, 옵저버빌리티 컨테이너는 **Compose profile로 분리** → 필요할 때만 기동
- 학습 잡 실행 중에는 `worker-output` / `worker-harness` 동시성 0으로 잠시 정지
- API의 `--workers 4` 를 **`--workers 2`** 로 하향

### 1.3 GPU: NVIDIA GTX 1060 3GB (Pascal, CC 6.1) — ★★

이게 진짜 까다로운 부분입니다.

**할 수 있는 것**:
- CUDA 12.x 지원됨 (Pascal은 sm_61, torch 2.3 정상 동작)
- 소형 모델 학습/추론 (≤30M 파라미터, batch 1~8)
- XGBoost GPU 모드 (작은 데이터에서만)
- SHAP / 전처리는 CPU로 충분

**할 수 없는 것**:
- **BERT-base 이상 사이즈 fine-tuning** (VRAM 3GB는 표준 batch에서 OOM)
- **ViT-Base 이상 이미지 트랜스포머**
- **Informer / TFT / TabTransformer 풀사이즈** (논문 기본 설정 시 OOM)
- FP8 / Flash Attention v2 (Hopper 이상 전용)
- 동시 GPU 사용 (워커 1개만 GPU 점유)

**작업지시서 정책 조정**:
- 마스터 §7의 "트랜스포머 우선 정책" 자체는 유지하되, **모델 레지스트리에 `vram_required` 컬럼 추가**해서 3GB 이하 모델만 등록
- TabTransformer 같은 정형 트랜스포머는 **embedding_dim 작게(≤32) + batch 8** 로 fine-tune 가능
- BERT 류는 **distilbert-base / KoMiniLM 같은 경량형으로 대체**
- Day12 트랜스포머 9종 중 GTX 1060 3GB에서 **실제 학습 가능한 것만 사용**:

| 모델 | 학습 가능? | 비고 |
|---|---|---|
| TabTransformer (소형) | ✅ | dim=32, depth=2, batch=8 |
| Informer (lite) | ⚠️ | seq_len ≤ 96 |
| TFT (lite) | ⚠️ | hidden_size ≤ 64 |
| ViT-Tiny | ✅ | – |
| ViT-Base | ❌ | OOM |
| BERT-base | ❌ | OOM. distilbert로 대체 |
| KoMiniLM / distilkobert | ✅ | – |
| TranAD | ✅ | 소형 |
| LoRA (rank ≤ 8) | ✅ | distilbert에 LoRA 적용은 가능 |

- **GPU는 `worker-training` 에만 노출**, 다른 워커는 CPU 강제 (`CUDA_VISIBLE_DEVICES=""`)
- 학습 시작 전 `nvidia-smi` 로 VRAM 점유 확인 자동화

### 1.4 디스크: 477GB SSD 중 144GB 여유 — ★★

ADA가 한 스프린트 진행하면 다음이 누적됩니다.

| 영역 | 추정 누적량 |
|---|---|
| Docker 이미지 (python:3.11-slim + ML 패키지) | 15~20GB |
| Postgres 데이터 + WAL | 2~5GB |
| MinIO artifacts (모델 + EDA 이미지 + SHAP) | 30~80GB |
| MLflow runs | 5~15GB |
| 컨테이너 로그 (회전 안 하면) | 5~30GB |
| 테스트 데이터셋 | 5~20GB |
| **합계** | **60~170GB** |

144GB는 빡빡합니다. 다음이 필수입니다.

- Docker 로그 회전 설정 (`/etc/docker/daemon.json` 의 `log-opts`)
- MinIO 라이프사이클 룰 — 30일 지난 임시 artifacts 자동 삭제
- 주 1회 `docker system prune -af --volumes` (테스트 환경 한정)
- `/var/lib/docker` 를 별도 마운트(가능하면)로 옮겨서 root fs 고갈 방지

---

## 2. 운영체제 — Ubuntu 22.04 LTS Server

데스크탑 환경 없이 Server 이미지를 권장합니다. 데스크탑은 800MB~1.5GB RAM을 그냥 잡아먹습니다 — 16GB 환경에서는 손실이 큽니다.

```
설치 시 선택:
  - Ubuntu Server 22.04.4 LTS (최소 설치)
  - 파티션: /boot/efi 512MB, swap 16GB, / 나머지 (ext4)
  - OpenSSH server 체크 ✅
  - Docker / NVIDIA snap 자동 설치는 ❌ (수동 설치가 더 안정)
```

원격 작업이 편하므로 SSH로 들어가 작업하는 걸 기본으로 합니다.

---

## 3. 시스템 셋업 (Linux 설치 직후)

### 3.1 기본 패키지

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y \
    ca-certificates curl gnupg lsb-release \
    git build-essential libgomp1 libpq-dev \
    htop ncdu jq unzip tmux net-tools
```

### 3.2 스왑 16GB 확보 (필수)

설치 시 16GB 스왑 파티션을 만들었다면 이 단계는 건너뜁니다. 안 만들었다면:

```bash
sudo fallocate -l 16G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab

# 스왑 사용 적극도 낮추기 (학습 중 디스크 IO 폭주 방지)
echo 'vm.swappiness=10' | sudo tee -a /etc/sysctl.d/99-ada.conf
echo 'vm.vfs_cache_pressure=50' | sudo tee -a /etc/sysctl.d/99-ada.conf
echo 'vm.max_map_count=262144' | sudo tee -a /etc/sysctl.d/99-ada.conf
sudo sysctl --system

free -h     # Swap: 16G 확인
```

### 3.3 파일 디스크립터 한도

```bash
echo '* soft nofile 65536' | sudo tee -a /etc/security/limits.conf
echo '* hard nofile 65536' | sudo tee -a /etc/security/limits.conf
```

### 3.4 Docker 데이터 디렉토리 분리 (강력 권장)

`/var/lib/docker` 가 root fs 위에 있으면 이미지/볼륨이 root를 고갈시킵니다. 데이터용 별도 디렉토리로 옮깁니다(여유 디스크의 큰 파티션이 따로 있다면 그쪽으로, 없으면 적어도 `/data/docker` 로 격리).

```bash
sudo systemctl stop docker || true
sudo mkdir -p /data/docker
sudo rsync -aHAX /var/lib/docker/ /data/docker/ 2>/dev/null || true
```

이후 `/etc/docker/daemon.json` 에 `"data-root": "/data/docker"` 를 추가합니다(아래 3.6 참조).

---

## 4. Docker Engine 설치

### 4.1 설치

```bash
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io \
    docker-buildx-plugin docker-compose-plugin

sudo usermod -aG docker $USER
newgrp docker

docker version
docker compose version    # v2.27+ 확인
```

### 4.2 데몬 설정 — 16GB 환경 최적화

```bash
sudo tee /etc/docker/daemon.json >/dev/null <<'EOF'
{
  "data-root": "/data/docker",
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "20m",
    "max-file": "3"
  },
  "storage-driver": "overlay2",
  "default-address-pools": [
    {"base": "172.30.0.0/16", "size": 24}
  ],
  "default-runtime": "runc",
  "default-shm-size": "256M"
}
EOF
sudo systemctl restart docker
docker info | grep -E "Docker Root Dir|Storage Driver|Logging Driver"
```

> `max-size: 20m × 3 files` → 컨테이너당 로그 최대 60MB로 캡. 16개 컨테이너면 1GB 미만으로 유지됩니다.

---

## 5. NVIDIA GTX 1060 3GB 셋업

GTX 1060은 Pascal 아키텍처(sm_61)입니다. CUDA 12.x는 지원되지만 일부 신규 라이브러리(FP8 등)는 안 됩니다.

### 5.1 드라이버 설치

```bash
sudo apt install -y ubuntu-drivers-common
ubuntu-drivers devices
sudo apt install -y nvidia-driver-535-server   # 또는 ubuntu-drivers autoinstall
sudo reboot

# 재부팅 후
nvidia-smi
# GTX 1060 / 3072 MiB 표시 확인
```

> 535 시리즈가 Pascal + CUDA 12.4 조합으로 가장 안정적입니다. 550 이상도 동작은 하지만 굳이 갈 이유는 없습니다.

### 5.2 nvidia-container-toolkit

```bash
distribution=$(. /etc/os-release; echo $ID$VERSION_ID)
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
  | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/$distribution/libnvidia-container.list \
  | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
  | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
sudo apt update
sudo apt install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker

docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi
# 컨테이너 안에서 GTX 1060 3GB 표시되면 성공
```

### 5.3 PyTorch 빌드 선택 (워커 이미지)

`requirements/worker.txt` 의 torch 라인을 다음으로 고정합니다.

```
--extra-index-url https://download.pytorch.org/whl/cu121
torch==2.3.0+cu121
torchvision==0.18.0+cu121
```

> Pascal은 CUDA 12.1 빌드가 가장 안정적입니다. 12.4 빌드도 동작은 하지만 12.1 권장.

### 5.4 학습 시 메모리 절약 기본 옵션

워커가 사용하는 학습 설정에 다음을 기본값으로 박아둡니다.

```python
# config/training_defaults.py
GPU_DEFAULTS = {
    "mixed_precision": "fp16",          # VRAM 절반으로
    "gradient_checkpointing": True,     # activation 메모리 절감
    "batch_size": 8,                    # 트랜스포머 기본
    "gradient_accumulation_steps": 4,   # effective batch 32
    "max_seq_length": 256,              # 512는 OOM 잦음
    "pin_memory": False,                # 16GB RAM 보호
}
```

---

## 6. ADA Compose 재설계 — Profile 분리

작업지시서 Day01의 11~16 컨테이너를 **세 그룹**으로 나눕니다.

```
core    : postgres, redis, minio, api, frontend, worker-pipeline, worker-harness, mlflow
ml      : worker-training, worker-output, serving           ← 학습/산출 단계에만
sec     : vault, claude-cli-sidecar                         ← Day16~17부터
obs     : prometheus, grafana, otel-collector, qdrant       ← 16GB 환경에선 거의 안 띄움
```

`docker-compose.yml` 의 각 서비스에 `profiles:` 키를 추가합니다.

```yaml
services:
  postgres:
    profiles: ["core"]
    image: pgvector/pgvector:pg16
    shm_size: "256mb"
    deploy:
      resources:
        limits:
          memory: 1500m
    command: >
      postgres
      -c max_connections=100
      -c shared_buffers=256MB
      -c work_mem=8MB
      -c maintenance_work_mem=64MB
    healthcheck:
      test: ["CMD", "pg_isready", "-U", "autoai"]

  redis:
    profiles: ["core"]
    image: redis:7-alpine
    command: ["redis-server", "--maxmemory", "256mb", "--maxmemory-policy", "allkeys-lru"]
    deploy:
      resources:
        limits:
          memory: 300m

  minio:
    profiles: ["core"]
    image: minio/minio:RELEASE.2024-04-06T05-26-02Z
    deploy:
      resources:
        limits:
          memory: 500m

  mlflow:
    profiles: ["core"]
    image: ghcr.io/mlflow/mlflow:v2.13.0
    deploy:
      resources:
        limits:
          memory: 300m

  api:
    profiles: ["core"]
    build: { dockerfile: Dockerfile.api }
    command: ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000",
              "--workers", "2", "--loop", "uvloop"]
    deploy:
      resources:
        limits:
          memory: 1500m
    environment:
      - CUDA_VISIBLE_DEVICES=""

  frontend:
    profiles: ["core"]
    deploy:
      resources:
        limits:
          memory: 500m
    environment:
      - CUDA_VISIBLE_DEVICES=""

  worker-pipeline:
    profiles: ["core"]
    build: { dockerfile: Dockerfile.worker }
    command: celery -A orchestrator.runner worker -Q pipeline -c 2 -n pipeline@%h
    deploy:
      resources:
        limits:
          memory: 2500m
    environment:
      - CUDA_VISIBLE_DEVICES=""

  worker-harness:
    profiles: ["core"]
    command: celery -A orchestrator.runner worker -Q harness -c 1 -n harness@%h
    deploy:
      resources:
        limits:
          memory: 500m
    environment:
      - CUDA_VISIBLE_DEVICES=""

  worker-training:
    profiles: ["ml"]
    command: celery -A orchestrator.runner worker -Q training -c 1 -n training@%h
    deploy:
      resources:
        limits:
          memory: 4000m
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
    environment:
      - NVIDIA_VISIBLE_DEVICES=0
      - PYTORCH_CUDA_ALLOC_CONF=max_split_size_mb:128

  worker-output:
    profiles: ["ml"]
    command: celery -A orchestrator.runner worker -Q output -c 2 -n output@%h
    deploy:
      resources:
        limits:
          memory: 1500m
    environment:
      - CUDA_VISIBLE_DEVICES=""

  serving:
    profiles: ["ml"]
    deploy:
      resources:
        limits:
          memory: 1000m

  vault:
    profiles: ["sec"]
    image: hashicorp/vault:1.16
    cap_add: [IPC_LOCK]

  claude-cli-sidecar:
    profiles: ["sec"]
    build: { dockerfile: docker/claude-cli-sidecar.Dockerfile }
    volumes:
      - .:/workspace:ro
      - ./error_handler/patches:/error_handler/patches:rw

  prometheus:
    profiles: ["obs"]
  grafana:
    profiles: ["obs"]
  otel-collector:
    profiles: ["obs"]
```

### 6.1 일상 기동 패턴

```bash
# 개발 시작: core만 (RAM ~8GB)
docker compose --profile core up -d

# 학습 단계 진입: ml 추가 (RAM ~13GB)
docker compose --profile core --profile ml up -d

# Day16 이후 Vault/Claude CLI 필요해지면
docker compose --profile core --profile ml --profile sec up -d

# 학습 끝났으면 ml 내리기 (메모리 회수)
docker compose --profile ml down

# 옵저버빌리티는 별도 검증 세션에서만
docker compose --profile obs up -d
```

> `docker compose down` 은 모든 profile 컨테이너를 내립니다. 특정 profile만 내리려면 `docker compose --profile ml down`.

---

## 7. Postgres / Redis / MinIO 16GB 튜닝 요약

| 항목 | Day01 기본 | 재설계 값 | 이유 |
|---|---|---|---|
| `postgres max_connections` | 200 | **100** | API workers=2 + Celery c=2+1+1+2 → 풀 충분 |
| `postgres shared_buffers` | 256MB | 256MB 유지 | – |
| `postgres work_mem` | 16MB | **8MB** | 동시 쿼리 메모리 폭주 방지 |
| `postgres shm_size` | 256mb | 256mb 유지 | – |
| `redis maxmemory` | 무제한 | **256MB** | LRU evict, 폭주 방지 |
| `minio` 멀티 노드 | 4-node | **단일 노드** | 16GB 환경에서는 단일이 합리 |
| API `--workers` | 4 | **2** | – |
| Celery `pipeline` 동시성 | 4 | **2** | – |
| Celery `training` 동시성 | 2 | **1** | GPU VRAM 3GB 단일 점유 |

---

## 8. 모델/데이터 정책 (3GB VRAM 현실)

작업지시서 Day07/Day08/Day12 와 마스터 §7 트랜스포머 우선 정책을 다음과 같이 보정합니다.

### 8.1 모델 레지스트리에 `vram_mb_required` 컬럼 추가

```sql
ALTER TABLE agent_registry
  ADD COLUMN IF NOT EXISTS hw_profile JSONB DEFAULT '{}'::jsonb;

-- 예시: TabTransformer 소형은 VRAM 1.5GB 정도면 충분
UPDATE agent_registry
SET hw_profile = '{"min_vram_mb": 1500, "recommended_batch": 8}'::jsonb
WHERE agent_name = 'FineTuneExecutorAgent';
```

### 8.2 `TRANSFORMER_REGISTRY` 변형

Day07의 `TRANSFORMER_REGISTRY` 에 `gtx1060_3gb_ok: bool` 플래그를 추가하고 ModelSelectionAgent가 이 플래그가 True인 모델만 자동 후보로 올립니다. False인 모델은 사용자가 명시적으로 선택할 때만 사용.

### 8.3 정형 ML 우선 (Day07)

- `xgboost`, `lightgbm`, `catboost` 는 **CPU 모드 기본**. GPU 모드는 데이터 < 100MB일 때만 켭니다.
- Optuna trials 수를 50~100으로 제한해 학습 시간 폭주 방지.

### 8.4 데이터 크기 가드레일

- 업로드 파일 100MB 상한(Day01 `MAX_UPLOAD_SIZE_MB=100` 그대로)
- DataProfiler가 1M 행 초과 시 자동 샘플링 + 사용자 알림
- 학습 데이터 RAM 로드 한도 4GB → 초과 시 batch streaming 모드 강제

---

## 9. 디스크 운영 (144GB로 한 스프린트 버티기)

### 9.1 MinIO 라이프사이클 룰

```bash
docker compose exec minio mc alias set local http://localhost:9000 minioadmin minioadmin
docker compose exec minio mc ilm rule add \
  --expire-days 30 \
  --prefix "self_learning/prompts/" \
  local/autoai-artifacts
docker compose exec minio mc ilm rule add \
  --expire-days 14 \
  --prefix "eda/" \
  local/autoai-artifacts
```

### 9.2 Postgres WAL 관리

```sql
ALTER SYSTEM SET wal_keep_size = '1GB';
ALTER SYSTEM SET max_wal_size = '2GB';
SELECT pg_reload_conf();
```

### 9.3 주간 청소 cron (서버 한정)

```bash
sudo tee /etc/cron.weekly/ada-docker-cleanup >/dev/null <<'EOF'
#!/bin/bash
docker system prune -af --filter "until=168h"
docker builder prune -af --filter "until=168h"
EOF
sudo chmod +x /etc/cron.weekly/ada-docker-cleanup
```

### 9.4 디스크 알람 (옵션)

```bash
sudo apt install -y monit
# /etc/monit/conf.d/disk.cfg
#   check filesystem rootfs with path /
#     if space usage > 85% then alert
```

---

## 10. 첫 기동 순서 (16GB 환경)

```bash
# 1) 코드 클론
cd ~ && git clone git@github.com:youandi3535/ADA.git && cd ADA

# 2) .env 작성
cp .env.example .env
chmod 600 .env
# 에디터로 ANTHROPIC_API_KEY, LANGSMITH_API_KEY, POSTGRES_PASSWORD,
# SECRET_KEY, JWT_SECRET 채우기

# 3) 빌드 — core만 먼저
docker compose --profile core build

# 4) 인프라부터 단계 기동
docker compose --profile core up -d postgres redis minio
sleep 30
docker compose --profile core ps

# 5) 마이그레이션
docker compose exec postgres psql -U autoai -d autoai \
  -f /docker-entrypoint-initdb.d/init.sql
docker compose exec postgres psql -U autoai -d autoai \
  -f /migrations/001_initial.sql
docker compose exec postgres psql -U autoai -d autoai \
  -f /migrations/002_v2_schema.sql

# 6) 나머지 core
docker compose --profile core up -d
sleep 20

# 7) 검증
free -h                         # 사용 메모리 8~10GB 이내인지 확인
curl -fs http://localhost:8000/health
curl -fs http://localhost:8501/_stcore/health
curl -fs http://localhost:5000      # MLflow
nvidia-smi                          # 호스트에서 GPU idle 확인

# 8) 학습 단계 진입 시
docker compose --profile core --profile ml up -d worker-training
docker exec $(docker compose ps -q worker-training) nvidia-smi
```

---

## 11. 모니터링 (가벼운 버전)

풀세트 Prometheus+Grafana는 16GB에서 부담입니다. 다음 가벼운 조합으로 대체합니다.

```bash
# 호스트에서 직접 보는 방법
watch -n 2 'free -h; echo; docker stats --no-stream'

# tmux split으로 항상 보기
tmux new -s ada
# pane1: htop
# pane2: docker stats
# pane3: nvidia-smi -l 2
# pane4: docker compose logs -f --tail=20
```

옵저버빌리티가 정말 필요해지는 Day20 통합 테스트 즈음에만 `--profile obs` 로 잠깐 켭니다.

---

## 12. 한계가 닥칠 때의 비상 카드

학습 도중 OOM이 나거나 디스크가 차면 다음 순서로 대응합니다.

1. `docker compose --profile ml stop worker-output worker-harness` — 메모리 회수
2. `docker compose exec worker-training python -c "import torch; torch.cuda.empty_cache()"` — VRAM 회수
3. `docker system prune -af` — 디스크 회수
4. PostgreSQL `VACUUM FULL` — DB 디스크 회수 (점검 시간에만)
5. MinIO 오래된 prefix 수동 삭제
6. 그래도 부족하면 — **데이터셋 다운샘플링 + batch 절반 + max_seq_length 절반**
7. 그래도 부족하면 — 해당 모델을 GPU에서 CPU로 강제 (느려도 끝까지 돕니다)

---

## 13. 한 줄 요약 (재설계판)

> **Ubuntu 22.04 Server / 스왑 16GB / Docker Engine + data-root=/data/docker / NVIDIA 535 + CUDA 12.1 torch / Compose profile 4그룹(core·ml·sec·obs) / pgvector:pg16 / 워커는 동시성 다이어트(pipeline=2, training=1, output=2, harness=1) / GPU는 worker-training 전용 + FP16 + grad-checkpointing / MinIO·Docker 로그 자동 청소.**

이 구성으로 16GB / GTX 1060 3GB / 144GB 여유에서도 21일 스프린트를 끝까지 끌고 갈 수 있습니다. 단, **Day12의 풀사이즈 트랜스포머 일부는 모델 다운스코프 또는 클라우드 GPU(Colab/RunPod) 외부 호출로 우회**해야 한다는 점은 기억해 두세요.
