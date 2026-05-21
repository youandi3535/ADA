"""api.middleware — Rate limit + SSE 진행률 (Day13)."""
from __future__ import annotations

import asyncio
import json
import time
from collections import defaultdict
from typing import AsyncIterator

from fastapi import Request
from starlette.responses import StreamingResponse

from ada.core.config import settings


# --- Token bucket rate limit (in-memory; 운영은 Redis 사용 권장) ---------------
class TokenBucket:
    def __init__(self, capacity: int = 60, refill_per_sec: float = 1.0) -> None:
        self.capacity = capacity
        self.refill = refill_per_sec
        self._buckets: dict[str, tuple[float, float]] = defaultdict(
            lambda: (capacity, time.time())
        )

    def take(self, key: str, cost: float = 1.0) -> bool:
        tokens, last = self._buckets[key]
        now = time.time()
        tokens = min(self.capacity, tokens + (now - last) * self.refill)
        if tokens < cost:
            self._buckets[key] = (tokens, now)
            return False
        self._buckets[key] = (tokens - cost, now)
        return True


bucket = TokenBucket()


def rate_limit_dep(request: Request) -> None:
    from fastapi import HTTPException
    key = request.client.host if request.client else "anon"
    if not bucket.take(key):
        raise HTTPException(429, detail="rate limit")


# --- SSE 진행률 스트림 -------------------------------------------------------
async def progress_sse(job_id: str) -> AsyncIterator[bytes]:
    import redis.asyncio as redis_async  # type: ignore
    r = redis_async.Redis.from_url(settings.redis_url)
    pubsub = r.pubsub()
    await pubsub.subscribe(f"ada:pipeline:{job_id}")
    try:
        async for msg in pubsub.listen():
            if msg["type"] != "message":
                continue
            data = msg["data"]
            if isinstance(data, bytes):
                data = data.decode("utf-8")
            yield f"data: {data}\n\n".encode("utf-8")
    finally:
        await pubsub.unsubscribe(f"ada:pipeline:{job_id}")
        await pubsub.close()


def make_sse_response(job_id: str) -> StreamingResponse:
    return StreamingResponse(progress_sse(job_id),
                             media_type="text/event-stream",
                             headers={"X-Accel-Buffering": "no"})
