# ADA 시크릿 / env 관리 — VPS

> 운영 서버의 비밀번호·API키(`.env`)와 SOPS 암호화를 다룬다.
> ⚠️ **이 문서엔 실제 비밀 값은 절대 적지 않는다.** 위치·절차·공개키만 기록.
> 변경 시 이 문서 + [_서버관리메뉴얼.md](_서버관리메뉴얼.md) 변경이력 갱신.

---

## 0. 핵심 위치 지도

| 파일/키 | 위치 | 성격 |
|---|---|---|
| 평문 `.env` | VPS `/opt/ada/.env` (권한 `600`, `ada:ada`) | 서비스가 실제로 읽음. **git 금지** |
| 암호화 `.env.sops` | repo 루트 `/opt/ada/.env.sops` (git 추적) | 암호문. 백업/버전관리. **커밋 OK** |
| SOPS 설정 | repo 루트 `.sops.yaml` | age 공개키 + dotenv 규칙 |
| age **개인키** | VPS `~/.config/sops/age/keys.txt` (권한 `600`) + 비번관리자(현재 Notion) | **복호화 유일 열쇠. git 절대 금지** |
| age **공개키** | `age1xvnp7fzdcrc8efrqra4lmtlt32dqaf2gl3plvt7ztt00n2swrq2sx8r8ce` | 암호화용. 공개 OK |

---

## 1. 현재 상태 (2026-06-17 하드닝 완료, 약 8/10)

- 핵심 비번(postgres · minio · vault · jwt · secret) → **강한 랜덤 고유값**으로 교체 (로컬 dev 값과 다름)
- `GITHUB_TOKEN` → **제거** (런타임 앱은 불필요. CI는 GitHub 자동 토큰 사용)
- `.env` 권한 `600`, `ENVIRONMENT=production` 확인
- 평문 백업(`.env.bak*`) 삭제 → **SOPS 암호화 백업(`.env.sops`)으로 대체**

---

## 2. 황금 규칙 (3개만 기억)

1. **평문 `.env` → git 금지** (`.gitignore`로 차단됨)
2. **암호 `.env.sops` → 커밋 OK** (값이 `ENC[...]` 암호문이라 안전)
3. **age 개인키 → git 절대 금지** (VPS + 비번관리자에만)

---

## 3. env 수정 → 반영 절차 (★ 매번)

```bash
# 🖥️ VPS에서
nano /opt/ada/.env                         # ① 평문 편집
AGEPUB=$(grep 'public key' ~/.config/sops/age/keys.txt | sed 's/.*: //')
sops -e --input-type dotenv --output-type dotenv /opt/ada/.env > /opt/ada/.env.sops   # ② 암호화 백업 갱신(잊지 말기)
cd /opt/ada/docker && docker compose --env-file ../.env --profile core --profile ml up -d   # ③ 적용
```

> 핵심: **"편집 → 다시 암호화 → 재시작"**. ②를 빠뜨리면 암호 백업만 옛 버전(서비스엔 무해).

---

## 4. 비밀번호 교체(로테이션) 런북

> 운영 중(데이터 있음) 시스템이라, 시크릿마다 부작용이 다름. 백업 먼저: `cp /opt/ada/.env /opt/ada/.env.bak.$(date +%F-%H%M)`

### 4-1. PostgreSQL — "자물쇠 + 메모 3곳" 둘 다 바꿔야 함
`.env`의 옛 비번은 3곳(`POSTGRES_PASSWORD`, `DATABASE_URL`, `KB_SYNC_DATABASE_URL`)에 있고, mlflow는 `${POSTGRES_PASSWORD}` 참조로 자동 추종.
```bash
OLDPG=$(grep '^POSTGRES_PASSWORD=' /opt/ada/.env | cut -d= -f2-); NEWPG=$(openssl rand -hex 24)
docker exec ada-postgres psql -U autoai -d autoai -c "ALTER USER autoai WITH PASSWORD '$NEWPG';"   # 자물쇠(실제 DB)
sed -i "s|$OLDPG|$NEWPG|g" /opt/ada/.env                                                            # 메모 3곳 일괄
cd /opt/ada/docker && docker compose --env-file ../.env --profile core --profile ml up -d           # 재연결
curl -fsS http://localhost:8000/health                                                              # 검증
```

### 4-2. MinIO — `.env`만 바꾸고 재시작 (ALTER 불필요)
MinIO는 켤 때마다 `MINIO_ROOT_USER/PASSWORD`(= `MINIO_ACCESS_KEY`/`MINIO_SECRET_KEY`)를 적용. 키는 4곳(`MINIO_*` 2 + `AWS_*` 2).
```bash
NEWAK=$(openssl rand -hex 8); NEWSK=$(openssl rand -hex 24)
sed -i "s|^MINIO_ACCESS_KEY=.*|MINIO_ACCESS_KEY=$NEWAK|"           /opt/ada/.env
sed -i "s|^MINIO_SECRET_KEY=.*|MINIO_SECRET_KEY=$NEWSK|"           /opt/ada/.env
sed -i "s|^AWS_ACCESS_KEY_ID=.*|AWS_ACCESS_KEY_ID=$NEWAK|"         /opt/ada/.env
sed -i "s|^AWS_SECRET_ACCESS_KEY=.*|AWS_SECRET_ACCESS_KEY=$NEWSK|" /opt/ada/.env
cd /opt/ada/docker && docker compose --env-file ../.env --profile core --profile ml up -d
```

> ⚠️ 로테이션 후 **3절차 ②(재암호화)**로 `.env.sops`도 갱신할 것.

---

## 5. 복구 (서버 재구축 / .env 분실 시)

1. age **개인키** 복원 → `~/.config/sops/age/keys.txt` (비번관리자에서)
2. `.env.sops`에서 평문 복원:
   ```bash
   sops -d --input-type dotenv --output-type dotenv /opt/ada/.env.sops > /opt/ada/.env
   chmod 600 /opt/ada/.env
   ```
3. `docker compose ... up -d`

---

## 6. 아직 안 한 것 / 다음 (TODO)

- [ ] age 개인키 **Notion → Bitwarden**(전용 비번관리자)로 이전 + 오프라인 1부
- [ ] **Vault(Phase 2)** 런타임 주입 — 평문 `.env` 자체 제거 + 접근 감사 (8 → 9+)
- [ ] **JWT RS256** 전환 (R-707) — Vault에 `jwt/rs256` 키쌍 넣고 `JWT_ALGO=RS256`. 코드는 이미 지원([ada/security/jwt.py](../../ada/security/jwt.py))
- [ ] `.env.sops` **git push + PR** (현재 `feat/NY` 로컬 커밋만 — 원격 버전관리 미완)
- [ ] 배포 시 **자동 복호화**(`deploy.yml`에 sops 단계 + age키 GitHub Secret) — 풀 GitOps

---

## 변경 이력

- **2026-06-17** — env 시크릿 하드닝 + SOPS 도입
  - postgres·minio·vault·jwt·secret → 강한 고유값 교체, `GITHUB_TOKEN` 제거, `.env` 권한 600 확인
  - SOPS(age) 암호화 도입: `.sops.yaml` + `.env.sops`(암호화 백업) git 버전관리
  - 평문 `.env.bak*` 삭제, 점수 3.5 → 8
