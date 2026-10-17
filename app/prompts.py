"""Prompt templates. Versioned so results can be traced to the prompt that produced them."""
import json

from .schemas import CallIn, Intent, Sentiment

PROMPT_VERSION = "v1"

SYSTEM = (
    "You analyse customer-service phone call transcripts for an enterprise contact centre. "
    "Return ONLY a JSON object, no markdown, matching this schema exactly:\n"
    '{"summary": string (one or two sentences, max 400 chars), '
    f'"intent": one of {[i.value for i in Intent]}, '
    f'"sentiment": one of {[s.value for s in Sentiment]} (the customer\'s sentiment by the end of the call), '
    '"promise_to_pay": {"amount": number or null, "due_date": "YYYY-MM-DD" or null} or null, '
    '"escalation_needed": boolean (true if the customer asks for a supervisor, threatens to complain or cancel, or the issue is unresolved and urgent), '
    '"action_items": array of up to 5 short strings}\n'
    "Rules: use only facts stated in the transcript; if the customer does not commit to a payment, promise_to_pay is null; "
    "amounts are numbers without currency symbols; resolve relative dates using the call date given."
)


def build(call: CallIn, call_date: str) -> str:
    lines = "\n".join(f"{t.speaker.upper()}: {t.text}" for t in call.turns)
    return f"Call date: {call_date}\nDomain: {call.domain}\nLanguage: {call.language}\n\nTranscript:\n{lines}"


def repair(previous_output: str, error: str) -> str:
    return ("Your previous reply was not valid for the schema.\n"
            f"Validation error: {error}\nPrevious reply: {previous_output[:2000]}\n"
            "Reply again with ONLY the corrected JSON object.")


def extract_json(text: str) -> dict:
    """Pull the first JSON object out of a model reply (models sometimes add ```json fences)."""
    t = text.strip()
    if t.startswith("```"):
        t = t.strip("`")
        t = t[t.find("{"):]
    start, end = t.find("{"), t.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object found")
    return json.loads(t[start:end + 1])
