#!/usr/bin/env python
"""scripts/dev/verify_oauth_db.py — 구글 로그인의 DB 반영을 '눈으로' 확인하는 점검 스크립트.

무엇을 하나
-----------
구글 로그인 v1 이 DB 에 제대로 쌓이는지 한 번에 확인한다:
  1) DB 연결 OK?
  2) users / oauth_accounts / security_audit_log 테이블 존재? (= 마이그레이션 적용됨?)
  3) 사용자 수 · 구글 연동 수 · 로그인 기록 수 (성공/실패/차단) 집계
  4) 최근 연동 계정 5건 (이메일은 마스킹해서 표시 — PII 보호)

언제 쓰나
---------
  • 마이그레이션(alembic upgrade head) 직후 — 테이블이 잘 생겼는지
  • 팀원이 구글 로그인을 한 뒤 — DB 에 행이 실제로 쌓였는지

실행 방법 (호스트, 프로젝트 루트에서)
-------------------------------------
  # (권장) 운영/로컬 컨테이너 안에서 — DATABASE_URL 이 이미 세팅돼 있음:
  docker compose -f docker/docker-compose.yml exec api python scripts/dev/verify_oauth_db.py

  # 또는 로컬 venv 에서 (DATABASE_URL 환경변수가 DB 를 가리켜야 함):
  python scripts/dev/verify_oauth_db.py

종료 코드: 0=정상 · 1=DB 연결 실패 · 2=테이블 누락(마이그레이션 미적용)
"""
from __future__ import annotations

import asyncio
import sys

from sqlalchemy import func, select, text

from ada.db.models import OAuthAccount, SecurityAuditLog, User
from ada.db.session import AsyncSessionLocal

LINE = "=" * 62
THIN = "-" * 62


def _mask(email: str | None) -> str:
    """이메일 마스킹 — ab***@domain.com (PII 보호)."""
    if not email or "@" not in email:
        return "(없음)"
    name, dom = email.split("@", 1)
    head = name[:2] if len(name) > 2 else name[:1]
    return f"{head}***@{dom}"


async def _main() -> int:
    print(LINE)
    print(" ADA 구글 로그인 — DB 반영 점검")
    print(LINE)

    # [1] DB 연결 -----------------------------------------------------------
    try:
        async with AsyncSessionLocal() as s:
            await s.execute(text("SELECT 1"))
        print(" [1] DB 연결                 : OK")
    except Exception as e:  # noqa: BLE001
        print(f" [1] DB 연결                 : 실패 — {e}")
        print("\n  → DB 가 떠 있는지(docker compose ps), DATABASE_URL 이 맞는지 확인하세요.")
        return 1

    # [2] 테이블 존재 + 집계 -------------------------------------------------
    try:
        async with AsyncSessionLocal() as s:
            n_users = await s.scalar(select(func.count()).select_from(User))
            n_oauth = await s.scalar(select(func.count()).select_from(OAuthAccount))
            n_google = await s.scalar(
                select(func.count())
                .select_from(OAuthAccount)
                .where(OAuthAccount.provider == "google")
            )
            n_login_ok = await s.scalar(
                select(func.count())
                .select_from(SecurityAuditLog)
                .where(SecurityAuditLog.event_type == "login", SecurityAuditLog.result == "success")
            )
            n_login_fail = await s.scalar(
                select(func.count())
                .select_from(SecurityAuditLog)
                .where(SecurityAuditLog.event_type == "login", SecurityAuditLog.result != "success")
            )
    except Exception as e:  # noqa: BLE001
        print(f" [2] 테이블 조회             : 실패 — {e}")
        print("\n  → oauth_accounts 가 없으면 마이그레이션 미적용입니다: alembic upgrade head")
        return 2

    print(" [2] users 테이블            : OK")
    print(" [3] oauth_accounts 테이블   : OK")
    print(" [4] security_audit_log 테이블: OK")
    print(THIN)
    print(f"   • 전체 사용자(users)              : {n_users} 명")
    print(f"   • 소셜 연동(oauth_accounts)       : {n_oauth} 건  (구글: {n_google})")
    print(f"   • 로그인 성공 기록(audit)         : {n_login_ok} 건")
    print(f"   • 로그인 실패/차단 기록(audit)    : {n_login_fail} 건")
    print(THIN)

    # [3] 최근 연동 계정 5건 (마스킹) ----------------------------------------
    try:
        async with AsyncSessionLocal() as s:
            rows = (
                await s.execute(
                    select(
                        OAuthAccount.provider,
                        OAuthAccount.email,
                        OAuthAccount.created_at,
                    )
                    .order_by(OAuthAccount.created_at.desc())
                    .limit(5)
                )
            ).all()
        if rows:
            print("   최근 연동 계정 (마스킹):")
            for prov, email, created in rows:
                when = created.strftime("%Y-%m-%d %H:%M") if created else "-"
                print(f"     - [{prov}] {_mask(email)}   {when}")
        else:
            print("   아직 구글 로그인한 사용자가 없습니다.")
            print("   → 웹에서 구글 로그인 1회 후 이 스크립트를 다시 실행하면 숫자가 늘어납니다.")
    except Exception:  # noqa: BLE001 — 표시용이라 실패해도 점검 자체는 통과
        pass

    print(LINE)
    print(" 점검 완료 — 로그인할 때마다 위 숫자가 늘어나면 DB 저장 성공입니다. ✅")
    print(LINE)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
