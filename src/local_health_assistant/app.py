from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import date

from fastapi import FastAPI, HTTPException, Query

from local_health_assistant.config import Settings
from local_health_assistant.models import (
    AdviceOutcomeRequest,
    AdviceRequest,
    GoalUpdateRequest,
    InsightsGenerateRequest,
    MessageIngestRequest,
    OuraSyncRequest,
    ReviewGenerateRequest,
    StatusResponse,
)
from local_health_assistant.oura import OuraClient, OuraOAuthClient
from local_health_assistant.scheduler import MorningBriefingScheduler
from local_health_assistant.service import HealthService
from local_health_assistant.storage import Storage


settings = Settings.load()
storage = Storage(settings.app_paths)
oura_client = OuraClient(settings.oura_access_token, settings.oura_api_base_url)
oura_oauth_client = OuraOAuthClient(
    client_id=settings.oura_client_id,
    client_secret=settings.oura_client_secret,
    redirect_uri=settings.oura_redirect_uri,
    authorize_url=settings.oura_authorize_url,
    token_url=settings.oura_token_url,
)
service = HealthService(storage, oura_client, oura_oauth_client)
morning_scheduler = MorningBriefingScheduler(
    service=service,
    hour=settings.morning_briefing_hour,
    minute=settings.morning_briefing_minute,
    poll_seconds=settings.morning_briefing_poll_seconds,
    activity_sync_enabled=settings.activity_sync_enabled,
    activity_sync_interval_minutes=settings.activity_sync_interval_minutes,
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    should_start_scheduler = settings.morning_briefing_enabled or settings.activity_sync_enabled
    if should_start_scheduler:
        morning_scheduler.start()
    try:
        yield
    finally:
        if should_start_scheduler:
            morning_scheduler.stop()


app = FastAPI(title="Local Health Assistant", version="0.1.0", lifespan=lifespan)


@app.get("/health/status", response_model=StatusResponse)
def health_status() -> StatusResponse:
    return StatusResponse(
        app_name=settings.app_name,
        environment=settings.app_env,
        db_path=str(settings.app_paths.db_path),
        goals_path=str(settings.app_paths.goals_path),
        reviews_dir=str(settings.app_paths.reviews_dir),
        snapshots_dir=str(settings.app_paths.snapshots_dir),
        morning_briefing_enabled=settings.morning_briefing_enabled,
        morning_briefing_time=f"{settings.morning_briefing_hour:02d}:{settings.morning_briefing_minute:02d}",
        activity_sync_enabled=settings.activity_sync_enabled,
        activity_sync_interval_minutes=settings.activity_sync_interval_minutes,
    )


@app.get("/health/goals")
def get_goals() -> dict[str, object]:
    return {"goals": storage.load_goals().model_dump(mode="json")}


@app.get("/health/baseline")
def get_baseline() -> dict[str, object]:
    return service.get_baseline().model_dump(mode="json")


@app.get("/auth/oura/login")
def auth_oura_login() -> dict[str, object]:
    try:
        result = service.start_oura_oauth()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    return result.model_dump(mode="json")


@app.get("/auth/oura/callback")
def auth_oura_callback(
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    error_description: str | None = Query(default=None),
) -> dict[str, object]:
    if error:
        raise HTTPException(
            status_code=400,
            detail={
                "error": error,
                "error_description": error_description or "",
            },
        )
    if not code or not state:
        raise HTTPException(
            status_code=400,
            detail="Missing code or state in Oura callback.",
        )
    try:
        result = service.complete_oura_oauth(code, state)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    return result.model_dump(mode="json")


@app.put("/health/goals")
def put_goals(request: GoalUpdateRequest) -> dict[str, object]:
    saved = storage.save_goals(request.goals)
    return {"goals": saved.model_dump(mode="json")}


@app.post("/health/ingest/message")
def ingest_message(request: MessageIngestRequest) -> dict[str, object]:
    result = service.ingest_message(request)
    return result.model_dump(mode="json")


@app.post("/health/reviews/generate")
def generate_review(request: ReviewGenerateRequest) -> dict[str, object]:
    result = service.generate_review(request.target_date)
    return result.model_dump(mode="json")


@app.get("/health/reviews/{target_date}")
def get_review(target_date: date) -> dict[str, object]:
    review = service.get_review(target_date)
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")
    return review.model_dump(mode="json")


@app.get("/health/weights/anomaly/{target_date}")
def get_weight_anomaly_review(target_date: date) -> dict[str, object]:
    result = service.get_abnormal_weight_review(target_date)
    if not result:
        raise HTTPException(status_code=404, detail="Weight anomaly review not found")
    return result.model_dump(mode="json")


@app.post("/health/insights/generate")
def generate_insights(request: InsightsGenerateRequest) -> dict[str, object]:
    result = service.generate_insights(request.target_date)
    return result.model_dump(mode="json")


@app.get("/health/insights/{target_date}")
def get_insights(target_date: date) -> dict[str, object]:
    insights = service.get_insights(target_date)
    if not insights:
        raise HTTPException(status_code=404, detail="Insights not found")
    return insights.model_dump(mode="json")


@app.post("/health/advice/respond")
def advice_respond(request: AdviceRequest) -> dict[str, object]:
    result = service.respond_to_advice(request)
    return result.model_dump(mode="json")


@app.post("/health/advice/outcomes")
def advice_outcomes(request: AdviceOutcomeRequest) -> dict[str, object]:
    result = service.record_advice_outcome(request)
    return result.model_dump(mode="json")


@app.post("/health/oura/sync")
def oura_sync(request: OuraSyncRequest) -> dict[str, object]:
    return service.sync_oura(request.target_date, request.trigger_type)


@app.post("/health/oura/activity-sync")
def oura_activity_sync(request: OuraSyncRequest) -> dict[str, object]:
    return service.run_activity_sync(request.target_date, request.trigger_type)


@app.get("/health/oura/daily/{target_date}")
def get_oura_daily(target_date: date) -> dict[str, object]:
    metrics = storage.get_oura_daily_metrics(target_date)
    if not metrics:
        raise HTTPException(status_code=404, detail="Oura metrics not found")
    return {"metrics": metrics}


@app.post("/health/jobs/morning")
def run_morning_briefing(request: ReviewGenerateRequest) -> dict[str, object]:
    return service.run_morning_briefing(request.target_date)


service.import_baseline_report(
    "/Users/cjyyyyy/Documents/Playground/local-health-assistant/docs/examples/baseline-2026-01-24.json"
)
