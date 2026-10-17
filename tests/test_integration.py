"""End-to-end against real MongoDB and Redis (runs in GitHub Actions; skipped locally unless set)."""
import os
import uuid

import pytest

pytestmark = pytest.mark.integration

if not os.getenv("MONGO_URL") or not os.getenv("REDIS_URL"):
    pytest.skip("MONGO_URL and REDIS_URL not set", allow_module_level=True)

from httpx import ASGITransport, AsyncClient  # noqa: E402
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402
from redis.asyncio import Redis  # noqa: E402

from app import deps, llm, store, worker  # noqa: E402
from app.main import app  # noqa: E402


async def test_real_services_round_trip(sample):
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[f"it_{uuid.uuid4().hex[:6]}"]
    redis = Redis.from_url(os.environ["REDIS_URL"])
    deps.override(db=db, redis=redis)
    await store.ensure_indexes(db)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        assert (await client.get("/health")).json() == {"status": "ok"}
        for c in sample[:5]:
            assert (await client.post("/v1/calls", json=c)).status_code == 202
        for _ in range(5):
            await worker.process_one(db, redis, llm.RulesProvider(), timeout=2)
        s = (await client.get("/v1/stats")).json()
        assert s["analysed"] == 5
    await db.client.drop_database(db.name)
    await redis.aclose()
