"""MongoDB storage, Redis queue and Redis cache."""
import json
from datetime import datetime, timezone

from .config import settings

CALLS = "calls"


def now():
    return datetime.now(timezone.utc)


async def ensure_indexes(db):
    await db[CALLS].create_index("call_id", unique=True)
    await db[CALLS].create_index([("status", 1), ("created_at", -1)])


async def insert_call(db, doc: dict):
    await db[CALLS].insert_one(doc)


async def get_call(db, call_id: str):
    return await db[CALLS].find_one({"call_id": call_id}, {"_id": 0})


async def update_call(db, call_id: str, **fields):
    fields["updated_at"] = now()
    await db[CALLS].update_one({"call_id": call_id}, {"$set": fields})


async def enqueue(redis, call_id: str):
    await redis.lpush(settings.queue_key, call_id)


async def dequeue(redis, timeout: int = 5):
    item = await redis.brpop(settings.queue_key, timeout=timeout)
    return item[1].decode() if item and isinstance(item[1], bytes) else (item[1] if item else None)


def cache_key(call_id: str) -> str:
    return f"insights:{call_id}"


async def cache_get(redis, call_id: str):
    v = await redis.get(cache_key(call_id))
    return json.loads(v) if v else None


async def cache_set(redis, call_id: str, payload: dict):
    await redis.set(cache_key(call_id), json.dumps(payload, default=str), ex=settings.cache_ttl_seconds)


async def cache_drop(redis, call_id: str):
    await redis.delete(cache_key(call_id))


async def stats(db) -> dict:
    """Aggregation pipeline: counts by status, intent and sentiment, plus escalation and promise rates."""
    pipeline = [{"$facet": {
        "by_status": [{"$group": {"_id": "$status", "n": {"$sum": 1}}}],
        "by_intent": [{"$match": {"status": "done"}}, {"$group": {"_id": "$insights.intent", "n": {"$sum": 1}}}],
        "by_sentiment": [{"$match": {"status": "done"}}, {"$group": {"_id": "$insights.sentiment", "n": {"$sum": 1}}}],
        "rates": [{"$match": {"status": "done"}}, {"$group": {
            "_id": None, "done": {"$sum": 1},
            "escalations": {"$sum": {"$cond": ["$insights.escalation_needed", 1, 0]}},
            "promises": {"$sum": {"$cond": [{"$ne": ["$insights.promise_to_pay", None]}, 1, 0]}}}}],
    }}]
    res = (await db[CALLS].aggregate(pipeline).to_list(1))[0]
    flat = lambda rows: {r["_id"]: r["n"] for r in rows if r["_id"] is not None}
    r = res["rates"][0] if res["rates"] else {"done": 0, "escalations": 0, "promises": 0}
    return {"by_status": flat(res["by_status"]), "by_intent": flat(res["by_intent"]),
            "by_sentiment": flat(res["by_sentiment"]), "analysed": r["done"],
            "escalation_rate": round(r["escalations"] / r["done"], 3) if r["done"] else 0.0,
            "promise_to_pay_rate": round(r["promises"] / r["done"], 3) if r["done"] else 0.0}
