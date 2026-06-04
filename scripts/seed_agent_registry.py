#!/usr/bin/env python3
"""scripts.seed_agent_registry — agent_registry 27 행 + rules 시드 (Day02/Day21).

직접 실행: ``python -m scripts.seed_agent_registry`` 또는 ``./scripts/seed_agent_registry.py``
"""

from __future__ import annotations

import asyncio


def main() -> None:
    from ada.db.seeds import seed_all
    from ada.db.session import AsyncSessionLocal

    async def _run() -> None:
        async with AsyncSessionLocal() as s:
            result = await seed_all(s)
            print(result)

    asyncio.run(_run())


if __name__ == "__main__":
    main()
