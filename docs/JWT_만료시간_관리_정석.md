# JWT 만료시간 관리 정석 (SSOT)

> 토큰 유효시간은 **시크릿이 아니라 설정값**이다. 따라서 코드 한 곳에서만 관리한다.

## 1. 단일 소스 (Single Source of Truth)

JWT 토큰 유효시간은 **`ada/core/config.py` 의 `jwt_expire_min` default 한 곳에서만** 관리한다.

```python
# ada/core/config.py
jwt_expire_min: int = Field(default=1440, validation_alias="JWT_EXPIRE_MIN")
```

- 현재 값: **1440분 = 24시간**
- 이 default 가 유일한 정답(SSOT)이다.

## 2. 절대 금지 — `.env` / `.env.sops` 에 `JWT_EXPIRE_MIN` 두지 말 것

`.env` 또는 `.env.sops` 에 `JWT_EXPIRE_MIN` 을 두면, **env 값이 코드 기본값을 덮어쓴다**(`validation_alias` 때문).
→ 코드(config.py)와 런타임 값이 어긋나는 **divergence** 가 발생한다.

- ❌ `.env` 에 `JWT_EXPIRE_MIN=...` 추가
- ❌ `.env.sops` 에 `JWT_EXPIRE_MIN=...` 추가
- ✅ 오직 `config.py` 의 default 만 수정

config.py 의 해당 줄 주석에도 이 규칙이 명시돼 있다.

## 3. 변경 절차 (값을 바꾸고 싶을 때)

1. `ada/core/config.py` 의 `jwt_expire_min` default 수정
2. PR 생성 (config.py 는 HJ 영역 → CODEOWNERS 가 HJ 리뷰 요구)
3. HJ 리뷰 → main 머지
4. main 머지 시 GitHub Actions `Deploy` 워크플로우가 자동 배포
   (이미지 재빌드 → VPS `git reset --hard origin/main` → api·worker·beat 재생성 → 헬스체크)

> config.py 는 api/worker **이미지에 포함되는 코드**라(frontend 만 라이브마운트),
> 자동배포의 컨테이너 재생성으로 VPS 런타임에 새 값이 반영된다.

## 4. 검증 방법

배포 후 런타임 실제 값 확인:

```bash
# VPS 에서
cd /opt/ada/docker
docker compose --env-file ../.env exec -T api \
  python -c "from ada.core.config import settings; print(settings.jwt_expire_min)"
# → 1440 이어야 정상 (env override 없이 config.py default 사용)

# 컨테이너 env 에 override 가 없어야 함
docker compose --env-file ../.env exec -T api sh -c 'echo ${JWT_EXPIRE_MIN:-<unset>}'
# → <unset> 이어야 정상
```

## 5. 적용 이력

- **2026-06-22**: 기본값 60분 → 1440분(24h) 영구 적용 (config.py SSOT)
  - A단계: `config.py` default 60→1440 (PR#146 머지 + VPS 자동배포)
  - B단계: VPS `.env` / git `.env.sops` 에서 `JWT_EXPIRE_MIN` 제거 → config.py 단일 소스 일원화
    - `.env.sops` 는 손편집 금지(MAC 깨짐). 반드시 `sops` 로만 편집한다:
      `EDITOR="sed -i '/^JWT_EXPIRE_MIN=/d'" sops --input-type dotenv --output-type dotenv .env.sops`
  - 검증: 런타임 `settings.jwt_expire_min = 1440` (env override `<unset>`), API health 200
