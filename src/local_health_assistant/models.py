from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class GoalPayload(BaseModel):
    current_phase: str
    target_weight_range_kg: dict[str, float]
    protein_min_g: int
    calorie_range: dict[str, int]
    weekly_training_target: int
    late_night_snack_limit: int


class GoalUpdateRequest(BaseModel):
    goals: GoalPayload


class MessageIngestRequest(BaseModel):
    source_channel: str = Field(..., examples=["telegram"])
    source_user_id: str
    source_chat_id: str
    source_message_id: str | None = None
    session_key: str
    text: str
    occurred_at: datetime | None = None


class ExtractedRecord(BaseModel):
    record_type: Literal["food", "hunger", "weight"]
    summary: str
    confidence: float
    payload: dict[str, Any]


class MessageIngestResponse(BaseModel):
    conversation_event_id: int
    extracted_records: list[ExtractedRecord]
    is_advice_request: bool


class ReviewGenerateRequest(BaseModel):
    target_date: date | None = None


class ReviewResponse(BaseModel):
    date: date
    review_text: str
    key_issue: str
    recommended_adjustment: str
    realism_note: str
    markdown_path: str


class AdviceRequest(BaseModel):
    source_channel: str
    source_user_id: str
    source_chat_id: str
    source_message_id: str | None = None
    session_key: str
    question_text: str
    requested_at: datetime | None = None


class AdviceResponse(BaseModel):
    advice_record_id: int
    conclusion: str
    why: str
    realistic_alternative: str
    advice_text: str


class OuraSyncRequest(BaseModel):
    target_date: date
    trigger_type: Literal["manual", "scheduled"] = "manual"


class OuraAuthStartResponse(BaseModel):
    authorization_url: str
    state: str


class OuraCallbackResponse(BaseModel):
    status: str
    detail: str
    scopes: list[str] = Field(default_factory=list)


class BaselineProfile(BaseModel):
    age: int | None = None
    sex: str | None = None
    height_cm: float | None = None
    weight_kg: float | None = None
    bmi: float | None = None
    waist_cm: float | None = None
    hip_cm: float | None = None
    waist_hip_ratio: float | None = None
    smoking: str | None = None
    alcohol: str | None = None
    exercise: str | None = None


class HealthMarker(BaseModel):
    marker_key: str
    label: str
    value: str
    unit: str = ""
    severity: str = "info"
    observed_on: date
    source: str = "baseline"


class ReportRecord(BaseModel):
    report_date: date
    source_type: str
    source_file: str
    anonymized: bool = True


class BaselineResponse(BaseModel):
    profile: BaselineProfile
    markers: list[HealthMarker]
    reports: list[ReportRecord]


class InsightsGenerateRequest(BaseModel):
    target_date: date | None = None


class HypothesisScore(BaseModel):
    hypothesis_key: str
    score: float
    label: str
    evidence: list[str]
    recommendation: str


class DailyInsightsResponse(BaseModel):
    date: date
    features: dict[str, Any]
    hypotheses: list[HypothesisScore]


class StatusResponse(BaseModel):
    app_name: str
    environment: str
    db_path: str
    goals_path: str
    reviews_dir: str
    snapshots_dir: str
