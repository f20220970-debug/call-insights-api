"""Background worker: takes call ids from the Redis queue and analyses them with the LLM.

Run with:  python -m app.worker
Each job: mark processing -> build prompt -> call LLM -> validate (repair and retry if needed)
-> store insights or the error -> refresh the cache.
"""
import asyncio
import logging

from . import llm, store
from .deps import get_db, get_redis
from .schemas import CallIn, JobStatus

log = logging.getLogger("worker")


async def process_one(db, redis, provider, timeout: int = 5) -> str | None:
    call_id = await store.dequeue(redis, timeout=timeout)
    if not call_id:
        return None
    doc = await store.get_call(db, call_id)
    if not doc or doc["status"] == JobStatus.done.value:
        return call_id                                     # deleted or already done: skip safely
    await store.update_call(db, call_id, status=JobStatus.processing.value)
    call = CallIn(**doc["call"])
    try:
        insights, attempts = await llm.analyse(call, provider, doc["created_at"].date().isoformat())
        await store.update_call(db, call_id, status=JobStatus.done.value, insights=insights.model_dump(mode="json"),
                                attempts=attempts, provider=provider.name, error=None)
    except Exception as e:                                 # record any failure on the job, never crash the worker
        await store.update_call(db, call_id, status=JobStatus.failed.value, error=str(e)[:300], provider=provider.name)
        log.warning("call %s failed: %s", call_id, e)
    await store.cache_drop(redis, call_id)
    return call_id


async def main():
    logging.basicConfig(level=logging.INFO)
    db, redis, provider = get_db(), get_redis(), llm.get_provider()
    await store.ensure_indexes(db)
    log.info("worker started, provider=%s", provider.name)
    while True:
        await process_one(db, redis, provider)


if __name__ == "__main__":
    asyncio.run(main())
