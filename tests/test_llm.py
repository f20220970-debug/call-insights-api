"""Prompt, parsing and the validate-repair loop."""
import json

import pytest

from app import llm, prompts
from app.schemas import CallIn


class FlakyProvider:
    """Returns invalid output first, valid output second: the repair prompt should fix it."""
    name = "flaky"

    def __init__(self):
        self.calls, self.prompts = 0, []

    async def complete(self, system, user):
        self.calls += 1
        self.prompts.append(user)
        if self.calls == 1:
            return '```json\n{"summary": "short", "intent": "unknown_intent"}\n```'
        return json.dumps({"summary": "Customer promised to pay the overdue EMI on Friday.", "intent": "payment_reminder",
                           "sentiment": "neutral", "promise_to_pay": {"amount": 4500, "due_date": "2026-10-16"},
                           "escalation_needed": False, "action_items": ["Send payment link"]})


def call(sample):
    return CallIn(**sample[0])


async def test_repair_loop(sample):
    p = FlakyProvider()
    ins, attempts = await llm.analyse(call(sample), p, "2026-10-14")
    assert attempts == 2 and ins.promise_to_pay.amount == 4500
    assert "Validation error" in p.prompts[1]                 # second prompt carries the error back


def test_extract_json_handles_fences_and_noise():
    assert prompts.extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert prompts.extract_json('Here you go: {"a": {"b": 2}} done') == {"a": {"b": 2}}
    with pytest.raises(ValueError):
        prompts.extract_json("no json here")


def test_prompt_contains_schema_and_transcript(sample):
    text = prompts.build(call(sample), "2026-10-14")
    assert "Call date: 2026-10-14" in text and "CUSTOMER:" in text
    assert "promise_to_pay" in prompts.SYSTEM and "ONLY a JSON object" in prompts.SYSTEM


async def test_rules_resolves_weekday_from_call_date(sample):
    ins, _ = await llm.analyse(call(sample), llm.RulesProvider(), "2026-10-14")   # Wednesday
    assert str(ins.promise_to_pay.due_date) == "2026-10-16"                        # "Friday"


def test_gemini_requires_key():
    with pytest.raises(llm.LLMError):
        llm.GeminiProvider(api_key="")
