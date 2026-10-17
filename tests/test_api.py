"""API + worker tests with in-memory MongoDB and Redis."""
import json

from app import llm, worker


class BrokenProvider:
    name = "broken"

    async def complete(self, system, user):
        return "not json at all"


async def test_submit_process_and_fetch(env, sample):
    client, db, redis = env
    r = await client.post("/v1/calls", json=sample[0])
    assert r.status_code == 202 and r.json()["status"] == "queued"
    assert (await client.get(f"/v1/calls/{sample[0]['call_id']}")).json()["status"] == "queued"

    assert await worker.process_one(db, redis, llm.RulesProvider(), timeout=1) == sample[0]["call_id"]
    body = (await client.get(f"/v1/calls/{sample[0]['call_id']}")).json()
    assert body["status"] == "done" and body["insights"]["intent"] == "payment_reminder"
    assert body["insights"]["promise_to_pay"]["amount"] == 4500
    assert await redis.get(f"insights:{sample[0]['call_id']}")          # cached after first read


async def test_duplicate_and_validation(env, sample):
    client, *_ = env
    assert (await client.post("/v1/calls", json=sample[1])).status_code == 202
    assert (await client.post("/v1/calls", json=sample[1])).status_code == 409
    bad = dict(sample[2], turns=[])
    assert (await client.post("/v1/calls", json=bad)).status_code == 422
    assert (await client.post("/v1/calls", json=dict(sample[2], call_id="has space"))).status_code == 422
    assert (await client.get("/v1/calls/nope")).status_code == 404


async def test_failure_is_recorded_and_retry_works(env, sample):
    client, db, redis = env
    cid = sample[3]["call_id"]
    await client.post("/v1/calls", json=sample[3])
    await worker.process_one(db, redis, BrokenProvider(), timeout=1)
    body = (await client.get(f"/v1/calls/{cid}")).json()
    assert body["status"] == "failed" and "invalid output" in body["error"]
    assert (await client.post(f"/v1/calls/{cid}/retry")).status_code == 202
    await worker.process_one(db, redis, llm.RulesProvider(), timeout=1)
    assert (await client.get(f"/v1/calls/{cid}")).json()["status"] == "done"
    assert (await client.post(f"/v1/calls/{cid}/retry")).status_code == 409    # only failed calls


async def test_stats(env, sample):
    client, db, redis = env
    for c in sample[:6]:
        await client.post("/v1/calls", json=c)
    for _ in range(6):
        await worker.process_one(db, redis, llm.RulesProvider(), timeout=1)
    s = (await client.get("/v1/stats")).json()
    assert s["analysed"] == 6 and s["by_status"]["done"] == 6
    assert 0 < s["escalation_rate"] < 1 and sum(s["by_intent"].values()) == 6
