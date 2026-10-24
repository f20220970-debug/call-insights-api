"""Evaluate a provider on the labelled sample calls (data/sample_calls.json).

    python scripts/evaluate.py                 # offline rules baseline
    LLM_PROVIDER=gemini GEMINI_API_KEY=... python scripts/evaluate.py

Reports accuracy for intent, sentiment, escalation and promise-to-pay detection, exact match
for promised amounts, average attempts (repairs) and failures, and writes reports/eval_<provider>.md.
"""
import asyncio
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import llm  # noqa: E402
from app.config import settings  # noqa: E402
from app.schemas import CallIn  # noqa: E402

CALL_DATE = "2026-10-14"   # a Wednesday; relative dates in transcripts resolve from here


async def evaluate(rows, provider):
    res, fails, attempts = [], 0, []
    for k, r in enumerate(rows, start=1):
        lab = r.pop("label")
        t0 = time.time()
        try:
            ins, a = await llm.analyse(CallIn(**r), provider, CALL_DATE)
            attempts.append(a)
            print(f"  [{k}/{len(rows)}] {r['call_id']}: {ins.intent.value}, {ins.sentiment.value} ({time.time() - t0:.0f}s, attempts {a})", flush=True)
        except llm.LLMError as e:
            fails += 1
            print(f"  [{k}/{len(rows)}] {r['call_id']}: FAILED ({time.time() - t0:.0f}s) {str(e)[:120]}", flush=True)
            continue
        p = ins.promise_to_pay
        res.append({"intent": ins.intent.value == lab["intent"], "sentiment": ins.sentiment.value == lab["sentiment"],
                    "escalation": ins.escalation_needed == lab["escalation"], "promise": (p is not None) == lab["promise"],
                    "amount": lab["amount"] is None or (p is not None and p.amount == lab["amount"])})
    n = len(res)
    acc = {k: sum(x[k] for x in res) / n for k in res[0]} if n else {}
    return acc, n, fails, sum(attempts) / max(len(attempts), 1)


async def main():
    provider = llm.get_provider(settings.llm_provider)
    lines = [f"# Evaluation: provider = {provider.name}", "",
             "The core set was written alongside the rules baseline, so the baseline's core score is not meaningful;",
             "the held-out 'hard' set (paraphrases, Hinglish, indirect wording) is the fairer test.", ""]
    sets = [("core", "sample_calls.json"), ("hard", "hard_calls.json"), ("heldout-50", "heldout_50.json")]
    only = __import__("os").getenv("EVAL_SET")
    if only:
        sets = [x for x in sets if x[0] == only]
    for label, fname in sets:
        rows = json.loads((ROOT / "data" / fname).read_text())
        acc, n, fails, avg_att = await evaluate(rows, provider)
        lines += [f"## {label} set ({len(rows)} calls): {n} analysed, {fails} failed, average attempts {avg_att:.2f}", "",
                  "| field | accuracy |", "| --- | --- |"] + [f"| {k} | {100 * v:.0f}% |" for k, v in acc.items()] + [""]
    out = ROOT / "reports" / f"eval_{provider.name}.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    asyncio.run(main())
