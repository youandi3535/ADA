"""scripts.seed_agent_registry — agent_registry 27 행 + rules 시드 (Day02/Day21)."""
from __future__ import annotations

import asyncio


def main() -> None:
    from ada.db.session import AsyncSessionLocal
    from ada.db.seeds import seed_all

    async def _run() -> None:
        async with AsyncSessionLocal() as s:
            result = await seed_all(s)
            print(result)

    asyncio.run(_run())


if __name__ == "__main__":
    main()
