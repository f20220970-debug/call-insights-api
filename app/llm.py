"""LLM providers behind one interface, plus the analyse-validate-repair loop.

  RulesProvider  - offline keyword/regex baseline; needs no API key, used in tests and CI
  GeminiProvider - Google Gemini over its REST API (async httpx), JSON output mode
A provider returns raw text; `analyse` parses it, validates it against CallInsights and,
if it fails, sends a repair prompt (up to max_llm_attempts in total).
"""
import asyncio
import json
import re
from datetime import date, timedelta

import httpx
from pydantic import ValidationError

from . import prompts
from .config import settings
from .schemas import CallIn, CallInsights


class LLMError(RuntimeError):
    pass


class RulesProvider:
    name = "rules"

    INTENTS = [("payment_dispute", r"\b(wrong charge|dispute|not my transaction|charged twice|didn't make)\b"),
               ("refund_request", r"\brefund\b"),
               ("order_issue", r"\b(order|delivery|parcel|damaged|not delivered)\b"),
               ("claim_status", r"\bclaim\b"),
               ("policy_renewal", r"\b(renew|renewal|premium|policy)\b"),
               ("payment_reminder", r"\b(emi|due|overdue|outstanding|payment|instal?ment)\b")]
    NEG = r"\b(angry|upset|frustrated|terrible|worst|ridiculous|unacceptable|not happy|fed up|complain)\w*"
    POS = r"\b(thank you|thanks|great|helpful|perfect|appreciate|happy)\b"
    ESC = r"\b(supervisor|manager|complaint|complain|cancel|consumer court|escalate|ombudsman)\w*"
    DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

    async def complete(self, system: str, user: str) -> str:
        call_date = date.fromisoformat(re.search(r"Call date: (\d{4}-\d{2}-\d{2})", user).group(1))
        text = user.split("Transcript:", 1)[1]
        cust = " ".join(l.split(":", 1)[1] for l in text.splitlines() if l.upper().startswith("CUSTOMER:")).lower()
        low = text.lower()
        intent = next((i for i, rx in self.INTENTS if re.search(rx, low)), "general_query")
        neg, pos = len(re.findall(self.NEG, cust)), len(re.findall(self.POS, cust))
        sentiment = "negative" if neg > pos else "positive" if pos > neg else "neutral"
        escalate = bool(re.search(self.ESC, cust))
        promise = None
        if re.search(r"\b(i will|i'll|i can|will pay|will transfer|will clear)\b", cust):
            amt = re.search(r"(?:rs\.?|₹|inr)\s?([\d,]+(?:\.\d+)?)|([\d,]{3,})\s?(?:rupees|rs)", cust)
            amount = float((amt.group(1) or amt.group(2)).replace(",", "")) if amt else None
            due = None
            if "tomorrow" in cust:
                due = call_date + timedelta(days=1)
            else:
                for k, d in enumerate(self.DAYS):
                    if re.search(rf"\b{d}\b", cust):
                        due = call_date + timedelta(days=(k - call_date.weekday()) % 7 or 7)
                        break
            if amount or due:
                promise = {"amount": amount, "due_date": due.isoformat() if due else None}
        actions = []
        if promise:
            actions.append("Send payment link and confirm promised payment")
        if escalate:
            actions.append("Escalate to supervisor within 24 hours")
        if intent == "payment_dispute":
            actions.append("Raise a dispute ticket and share reference number")
        out = {"summary": f"Customer call about {intent.replace('_', ' ')}; customer sentiment {sentiment}.",
               "intent": intent, "sentiment": sentiment, "promise_to_pay": promise,
               "escalation_needed": escalate, "action_items": actions}
        return json.dumps(out)


class GeminiProvider:
    name = "gemini"

    def __init__(self, api_key: str = settings.gemini_api_key, model: str = settings.gemini_model):
        if not api_key:
            raise LLMError("GEMINI_API_KEY is not set")
        self.url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        self.key = api_key

    async def complete(self, system: str, user: str) -> str:
        body = {"systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": user}]}],
                "generationConfig": {"temperature": 0, "responseMimeType": "application/json"}}
        r = None
        async with httpx.AsyncClient(timeout=settings.llm_timeout_seconds) as client:
            for wait in (0, 5, 15, 40):          # back off on timeouts, rate limits (429) and server errors
                await asyncio.sleep(wait)
                try:
                    r = await client.post(self.url, params={"key": self.key}, json=body)
                except httpx.TransportError:     # timeout or dropped connection: try again
                    r = None
                    continue
                if r.status_code not in (429, 500, 502, 503, 504):
                    break
        if r is None:
            raise LLMError("Gemini did not respond (timeouts after retries)")
        if r.status_code != 200:
            raise LLMError(f"Gemini HTTP {r.status_code}: {r.text[:200]}")
        try:
            return r.json()["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError) as e:
            raise LLMError(f"unexpected Gemini response: {e}")


def get_provider(name: str = settings.llm_provider):
    return GeminiProvider() if name == "gemini" else RulesProvider()


async def analyse(call: CallIn, provider, call_date: str) -> tuple:
    """Return (CallInsights, attempts). Retries with a repair prompt if output is invalid."""
    user = prompts.build(call, call_date)
    last_err = None
    for attempt in range(1, settings.max_llm_attempts + 1):
        raw = await provider.complete(prompts.SYSTEM, user)
        try:
            return CallInsights.model_validate(prompts.extract_json(raw)), attempt
        except (ValueError, ValidationError) as e:
            last_err = str(e).splitlines()[0]
            user = prompts.build(call, call_date) + "\n\n" + prompts.repair(raw, last_err)
    raise LLMError(f"invalid output after {settings.max_llm_attempts} attempts: {last_err}")
