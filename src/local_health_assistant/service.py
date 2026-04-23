from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from local_health_assistant.baseline import get_baseline, import_baseline_json
from local_health_assistant.insights import InsightInputs, generate_daily_insights
from local_health_assistant.models import (
    AdviceRequest,
    AdviceResponse,
    BaselineResponse,
    DailyInsightsResponse,
    MessageIngestRequest,
    MessageIngestResponse,
    OuraAuthStartResponse,
    OuraCallbackResponse,
    ReviewResponse,
)
from local_health_assistant.oura import (
    OuraAPIError,
    OuraClient,
    OuraOAuthClient,
    compute_expires_at,
    is_token_expired,
    normalize_daily_metrics,
)
from local_health_assistant.parsing import parse_message
from local_health_assistant.storage import Storage


class HealthService:
    def __init__(
        self,
        storage: Storage,
        oura_client: OuraClient | None = None,
        oura_oauth_client: OuraOAuthClient | None = None,
    ):
        self.storage = storage
        self.oura_client = oura_client
        self.oura_oauth_client = oura_oauth_client

    def ingest_message(self, request: MessageIngestRequest) -> MessageIngestResponse:
        occurred_at = request.occurred_at or datetime.now(timezone.utc)
        event_id = self.storage.create_conversation_event(
            {
                "source_channel": request.source_channel,
                "source_user_id": request.source_user_id,
                "source_chat_id": request.source_chat_id,
                "source_message_id": request.source_message_id,
                "session_key": request.session_key,
                "occurred_at": occurred_at.isoformat(),
                "text": request.text,
            }
        )
        parsed = parse_message(request.text, occurred_at)
        for record in parsed.extracted:
            if record.record_type == "food":
                self.storage.save_food_log(event_id, record.payload, record.confidence)
            elif record.record_type == "hunger":
                self.storage.save_hunger_log(event_id, record.payload, record.confidence)
            elif record.record_type == "weight":
                self.storage.save_weight_log(event_id, record.payload, record.confidence)
        return MessageIngestResponse(
            conversation_event_id=event_id,
            extracted_records=parsed.extracted,
            is_advice_request=parsed.is_advice_request,
        )

    def generate_review(self, target_date: date | None = None) -> ReviewResponse:
        review_date = target_date or (date.today() - timedelta(days=1))
        foods = self.storage.list_food_logs_for_date(review_date)
        recent_hunger = self.storage.list_hunger_logs_for_window(days=3)
        latest_weight = self.storage.latest_weight()
        recent_metrics = self.storage.list_recent_metrics(days=3)
        goals = self.storage.load_goals()

        key_issue = self._determine_key_issue(foods, recent_hunger, recent_metrics)
        recommended_adjustment = self._determine_adjustment(foods, recent_hunger, goals.model_dump(mode="json"))
        realism_note = self._determine_realism_note(recent_hunger, recent_metrics)

        review_text = "\n".join(
            [
                f"# Daily Review - {review_date.isoformat()}",
                "",
                f"- Yesterday's key issue: {key_issue}",
                f"- Best adjustment for today: {recommended_adjustment}",
                f"- Realism check: {realism_note}",
                "",
                self._weight_context_line(latest_weight),
            ]
        ).strip()
        return self.storage.save_review(review_date, review_text, key_issue, recommended_adjustment, realism_note)

    def get_review(self, target_date: date) -> ReviewResponse | None:
        return self.storage.get_review(target_date)

    def import_baseline_report(self, path: str) -> BaselineResponse:
        return import_baseline_json(self.storage, path)

    def get_baseline(self) -> BaselineResponse:
        return get_baseline(self.storage)

    def generate_insights(self, target_date: date | None = None) -> DailyInsightsResponse:
        insight_date = target_date or (date.today() - timedelta(days=1))
        result = generate_daily_insights(
            InsightInputs(
                target_date=insight_date,
                oura_metrics=self.storage.get_oura_daily_metrics(insight_date),
                food_logs=self.storage.list_food_logs_for_date(insight_date),
                hunger_logs=self.storage.list_hunger_logs_for_date(insight_date),
                latest_weight=self.storage.latest_weight(),
            )
        )
        self.storage.save_daily_insights(
            insight_date,
            result.features,
            [item.model_dump(mode="json") for item in result.hypotheses],
        )
        return result

    def get_insights(self, target_date: date) -> DailyInsightsResponse | None:
        stored = self.storage.get_daily_insights(target_date)
        if not stored:
            return None
        return DailyInsightsResponse.model_validate(stored)

    def respond_to_advice(self, request: AdviceRequest) -> AdviceResponse:
        occurred_at = request.requested_at or datetime.now(timezone.utc)
        event_id = self.storage.create_conversation_event(
            {
                "source_channel": request.source_channel,
                "source_user_id": request.source_user_id,
                "source_chat_id": request.source_chat_id,
                "source_message_id": request.source_message_id,
                "session_key": request.session_key,
                "occurred_at": occurred_at.isoformat(),
                "text": request.question_text,
            }
        )
        recent_hunger = self.storage.list_hunger_logs_for_window(days=3)
        recent_metrics = self.storage.list_recent_metrics(days=3)
        latest_weight = self.storage.latest_weight()
        goals = self.storage.load_goals().model_dump(mode="json")

        low_recovery = bool(recent_metrics and (recent_metrics[0].get("readiness_score") or 0) < 70)
        frequent_hunger = len(recent_hunger) >= 2
        conclusion = "可以吃，但要有边界。"
        why = "最近没有明显的数据提示需要完全禁止这次选择。"
        realistic_alternative = "把份量收成一个小份，并和正餐或高蛋白食物放在一起吃。"
        expected_behavior = "Have a bounded portion and avoid turning it into an open-ended snack."

        if low_recovery or frequent_hunger:
            conclusion = "可以吃，但不建议放任式吃。"
            why = "最近恢复或饥饿信号不稳，更容易把一次想吃变成补偿性进食。"
            realistic_alternative = "如果现在就想吃，先定小份量；如果是情绪性嘴馋，先延后 20 分钟再决定。"

        if latest_weight and goals.get("target_weight_range_kg", {}).get("max") is not None:
            if latest_weight["weight_kg"] > float(goals["target_weight_range_kg"]["max"]):
                why += " 当前体重也在目标上沿之外，建议优先保住节奏。"

        advice_text = f"{conclusion}\n原因：{why}\n更现实的做法：{realistic_alternative}"

        advice_record_id = self.storage.record_advice(
            event_id,
            request,
            advice_text,
            expected_behavior,
            {
                "recent_hunger_count": len(recent_hunger),
                "recent_oura_days": len(recent_metrics),
                "latest_weight": latest_weight,
            },
        )
        return AdviceResponse(
            advice_record_id=advice_record_id,
            conclusion=conclusion,
            why=why,
            realistic_alternative=realistic_alternative,
            advice_text=advice_text,
        )

    def start_oura_oauth(self) -> OuraAuthStartResponse:
        if self.oura_oauth_client is None:
            raise RuntimeError("Oura OAuth is not configured.")
        authorization_url, state = self.oura_oauth_client.build_authorization_url(
            scopes=["daily", "personal"]
        )
        self.storage.save_oauth_state("oura", state)
        return OuraAuthStartResponse(authorization_url=authorization_url, state=state)

    def complete_oura_oauth(self, code: str, state: str) -> OuraCallbackResponse:
        if self.oura_oauth_client is None:
            raise RuntimeError("Oura OAuth is not configured.")
        if not self.storage.consume_oauth_state("oura", state):
            raise RuntimeError("Invalid or expired OAuth state.")
        payload = self.oura_oauth_client.exchange_code(code)
        access_token = str(payload.get("access_token") or "").strip()
        if not access_token:
            raise RuntimeError("Oura token exchange did not return access_token.")
        scope_value = str(payload.get("scope") or "").strip()
        scopes = [item for item in scope_value.split() if item]
        self.storage.save_oauth_token(
            provider="oura",
            access_token=access_token,
            refresh_token=str(payload.get("refresh_token") or "").strip() or None,
            token_type=str(payload.get("token_type") or "").strip() or None,
            scope=scope_value or None,
            expires_at=compute_expires_at(payload.get("expires_in")),
        )
        return OuraCallbackResponse(
            status="ok",
            detail="Oura OAuth connection stored locally.",
            scopes=scopes,
        )

    def sync_oura(self, target_date: date, trigger_type: str) -> dict[str, Any]:
        run_id = self.storage.start_oura_sync(target_date, trigger_type)
        effective_client = self._oura_client_with_stored_token()
        if effective_client is None:
            message = "Oura client is not configured."
            self.storage.finish_oura_sync(run_id, status="failed", error_message=message)
            return {"run_id": run_id, "target_date": target_date.isoformat(), "status": "failed", "message": message}

        try:
            snapshot = effective_client.fetch_daily_snapshot(target_date)
            snapshot_path = self.storage.save_oura_snapshot(target_date, snapshot)
            metrics = normalize_daily_metrics(snapshot, target_date, str(snapshot_path))
            self.storage.upsert_oura_daily_metrics(metrics)
        except Exception as e:
            message = str(e)
            self.storage.finish_oura_sync(run_id, status="failed", error_message=message)
            result = {"run_id": run_id, "target_date": target_date.isoformat(), "status": "failed", "message": message}
            problem = self._structured_oura_problem(e)
            if problem:
                result["oura_error"] = problem
            return result

        self.storage.finish_oura_sync(run_id, status="success")
        return {
            "run_id": run_id,
            "target_date": target_date.isoformat(),
            "status": "success",
            "metrics": metrics,
        }

    def _oura_client_with_stored_token(self) -> OuraClient | None:
        token_row = self.storage.get_oauth_token("oura")
        if token_row and token_row.get("access_token"):
            token_row = self._refresh_oura_token_if_needed(token_row)
            return OuraClient(
                str(token_row["access_token"]),
                self.oura_client.base_url if self.oura_client else "https://api.ouraring.com",
            )
        return self.oura_client

    def _refresh_oura_token_if_needed(self, token_row: dict[str, Any]) -> dict[str, Any]:
        if not is_token_expired(token_row.get("expires_at")):
            return token_row
        refresh_token = str(token_row.get("refresh_token") or "").strip()
        if not refresh_token or self.oura_oauth_client is None:
            return token_row
        payload = self.oura_oauth_client.refresh_access_token(refresh_token)
        access_token = str(payload.get("access_token") or "").strip()
        if not access_token:
            raise RuntimeError("Oura refresh token exchange did not return access_token.")
        new_refresh_token = str(payload.get("refresh_token") or "").strip() or refresh_token
        scope_value = str(payload.get("scope") or token_row.get("scope") or "").strip() or None
        token_type = str(payload.get("token_type") or token_row.get("token_type") or "").strip() or None
        expires_at = compute_expires_at(payload.get("expires_in")) or token_row.get("expires_at")
        self.storage.save_oauth_token(
            provider="oura",
            access_token=access_token,
            refresh_token=new_refresh_token,
            token_type=token_type,
            scope=scope_value,
            expires_at=expires_at,
        )
        refreshed = self.storage.get_oauth_token("oura")
        return refreshed or {
            **token_row,
            "access_token": access_token,
            "refresh_token": new_refresh_token,
            "token_type": token_type,
            "scope": scope_value,
            "expires_at": expires_at,
        }

    def _structured_oura_problem(self, error: Exception) -> dict[str, Any] | None:
        if not isinstance(error, OuraAPIError):
            return None
        try:
            parsed = __import__("json").loads(str(error))
        except Exception:
            return None
        return parsed if isinstance(parsed, dict) else None

    def _determine_key_issue(
        self,
        foods: list[dict[str, Any]],
        recent_hunger: list[dict[str, Any]],
        recent_metrics: list[dict[str, Any]],
    ) -> str:
        if recent_metrics and (recent_metrics[0].get("readiness_score") or 0) < 70:
            return "Recovery is trending low, so appetite control is likely harder than usual."
        if len(recent_hunger) >= 2:
            return "Frequent recent hunger signals suggest your current plan may be too aggressive."
        if not foods:
            return "Yesterday has too little logged diet data, so consistency of tracking is the main gap."
        return "Nothing stands out as a crisis, but eating decisions still need tighter structure."

    def _determine_adjustment(
        self,
        foods: list[dict[str, Any]],
        recent_hunger: list[dict[str, Any]],
        goals: dict[str, Any],
    ) -> str:
        if len(recent_hunger) >= 2:
            return "Front-load protein earlier in the day so evening decisions are less reactive."
        if not foods:
            return "Log at least your first meal and any hunger spike today to restore a usable data trail."
        if goals.get("late_night_snack_limit", 0) <= 2:
            return "Keep late-night eating bounded and pre-decide the portion before you start."
        return "Repeat the parts of yesterday that were easiest to execute instead of tightening the plan."

    def _determine_realism_note(
        self,
        recent_hunger: list[dict[str, Any]],
        recent_metrics: list[dict[str, Any]],
    ) -> str:
        if recent_metrics and (recent_metrics[0].get("readiness_score") or 0) < 70:
            return "A softer target is more realistic today because low recovery usually reduces restraint."
        if len(recent_hunger) >= 2:
            return "The plan should bias toward controlled flexibility, not a perfect day."
        return "The recommendation is realistic if you make the decision before hunger gets strong."

    def _weight_context_line(self, latest_weight: dict[str, Any] | None) -> str:
        if not latest_weight:
            return "- Latest weight: no weight log yet."
        return f"- Latest weight: {latest_weight['weight_kg']:.1f}kg."
