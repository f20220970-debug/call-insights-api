"""REST API.

POST /v1/calls              submit a transcript -> 202, analysis queued
GET  /v1/calls              list calls, newest first (filters: status, intent, escalation)
GET  /v1/calls/{call_id}    status and insights (served from Redis cache when done)
POST /v1/calls/{id}/retry   re-queue a failed call
GET  /v1/stats              aggregate intents, sentiment, escalation and promise-to-pay rates
GET  /health                MongoDB and Redis connectivity
"""
import logging
import time
import uuid
from contextlib import asynccontextmanager

from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from pymongo.errors import DuplicateKeyError

from . import store
from .deps import get_db, get_redis
from .schemas import CallIn, CallOut, JobStatus

log = logging.getLogger("api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await store.ensure_indexes(get_db())
    yield


app = FastAPI(title="Call Insights API", version="1.0.0", lifespan=lifespan)


@app.middleware("http")
async def request_id(request: Request, call_next):
    rid = request.headers.get("x-request-id", uuid.uuid4().hex[:12])
    t0 = time.perf_counter()
    response = await call_next(request)
    response.headers["x-request-id"] = rid
    log.info("%s %s %s %.1fms rid=%s", request.method, request.url.path, response.status_code,
             1000 * (time.perf_counter() - t0), rid)
    return response


@app.post("/v1/calls", status_code=202, response_model=CallOut)
async def submit(call: CallIn, db=Depends(get_db), redis=Depends(get_redis)):
    doc = {"call_id": call.call_id, "call": call.model_dump(), "status": JobStatus.queued.value,
           "attempts": 0, "created_at": store.now(), "updated_at": store.now()}
    try:
        await store.insert_call(db, doc)
    except DuplicateKeyError:
        raise HTTPException(409, f"call_id {call.call_id} already exists")
    await store.enqueue(redis, call.call_id)
    return CallOut(call_id=call.call_id, status=JobStatus.queued)


class CallSummary(CallOut):
    domain: str
    created_at: str
    transcript_preview: str


@app.get("/v1/calls", response_model=list[CallSummary])
async def list_calls(status: Optional[JobStatus] = None, intent: Optional[str] = None,
                     escalation: Optional[bool] = None, limit: int = Query(20, ge=1, le=100),
                     skip: int = Query(0, ge=0), db=Depends(get_db)):
    docs = await store.list_calls(db, status.value if status else None, intent, escalation, limit, skip)
    out = []
    for d in docs:
        turns = d["call"]["turns"]
        cust = next((t["text"] for t in turns if t["speaker"].lower() == "customer"), turns[0]["text"])
        out.append(CallSummary(call_id=d["call_id"], status=d["status"], insights=d.get("insights"), error=d.get("error"),
                               attempts=d.get("attempts", 0), provider=d.get("provider"), domain=d["call"]["domain"],
                               created_at=d["created_at"].isoformat(), transcript_preview=cust[:140]))
    return out


@app.get("/v1/calls/{call_id}/transcript")
async def transcript(call_id: str, db=Depends(get_db)):
    doc = await store.get_call(db, call_id)
    if not doc:
        raise HTTPException(404, "call not found")
    return doc["call"]


@app.get("/v1/calls/{call_id}", response_model=CallOut)
async def get(call_id: str, db=Depends(get_db), redis=Depends(get_redis)):
    cached = await store.cache_get(redis, call_id)
    if cached:
        return CallOut(**cached)
    doc = await store.get_call(db, call_id)
    if not doc:
        raise HTTPException(404, "call not found")
    out = CallOut(call_id=call_id, status=doc["status"], insights=doc.get("insights"), error=doc.get("error"),
                  attempts=doc.get("attempts", 0), provider=doc.get("provider"))
    if out.status == JobStatus.done:
        await store.cache_set(redis, call_id, out.model_dump(mode="json"))
    return out


@app.post("/v1/calls/{call_id}/retry", status_code=202, response_model=CallOut)
async def retry(call_id: str, db=Depends(get_db), redis=Depends(get_redis)):
    doc = await store.get_call(db, call_id)
    if not doc:
        raise HTTPException(404, "call not found")
    if doc["status"] != JobStatus.failed.value:
        raise HTTPException(409, f"only failed calls can be retried (status is {doc['status']})")
    await store.update_call(db, call_id, status=JobStatus.queued.value, error=None)
    await store.cache_drop(redis, call_id)
    await store.enqueue(redis, call_id)
    return CallOut(call_id=call_id, status=JobStatus.queued)


@app.get("/v1/stats")
async def stats(db=Depends(get_db)):
    return await store.stats(db)


@app.get("/health")
async def health(db=Depends(get_db), redis=Depends(get_redis)):
    await db.command("ping")
    await redis.ping()
    return {"status": "ok"}
