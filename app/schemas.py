"""Request and response models. The LLM's output must validate against CallInsights."""
from datetime import date
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class Turn(BaseModel):
    speaker: str = Field(..., examples=["agent", "customer"])
    text: str = Field(..., min_length=1)


class CallIn(BaseModel):
    call_id: str = Field(..., min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_\-]+$")
    language: str = "en"
    domain: str = Field("banking", examples=["banking", "insurance", "ecommerce"])
    turns: list[Turn] = Field(..., min_length=1)


class Intent(str, Enum):
    payment_reminder = "payment_reminder"
    payment_dispute = "payment_dispute"
    policy_renewal = "policy_renewal"
    claim_status = "claim_status"
    order_issue = "order_issue"
    refund_request = "refund_request"
    general_query = "general_query"


class Sentiment(str, Enum):
    positive = "positive"
    neutral = "neutral"
    negative = "negative"


class PromiseToPay(BaseModel):
    amount: Optional[float] = Field(None, ge=0)
    due_date: Optional[date] = None


class CallInsights(BaseModel):
    summary: str = Field(..., min_length=10, max_length=400)
    intent: Intent
    sentiment: Sentiment
    promise_to_pay: Optional[PromiseToPay] = None
    escalation_needed: bool
    action_items: list[str] = Field(default_factory=list, max_length=5)

    @field_validator("action_items")
    @classmethod
    def strip_items(cls, v):
        return [s.strip() for s in v if s and s.strip()]


class JobStatus(str, Enum):
    queued = "queued"
    processing = "processing"
    done = "done"
    failed = "failed"


class CallOut(BaseModel):
    call_id: str
    status: JobStatus
    insights: Optional[CallInsights] = None
    error: Optional[str] = None
    attempts: int = 0
    provider: Optional[str] = None
