import json
import sys
from pathlib import Path

import pytest
from fakeredis import aioredis
from httpx import ASGITransport, AsyncClient
from mongomock_motor import AsyncMongoMockClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import deps, store  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture
async def env():
    db = AsyncMongoMockClient()["test"]
    redis = aioredis.FakeRedis()
    deps.override(db=db, redis=redis)
    await store.ensure_indexes(db)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, db, redis


@pytest.fixture
def sample():
    rows = json.loads((ROOT / "data" / "sample_calls.json").read_text())
    for r in rows:
        r.pop("label")
    return rows
