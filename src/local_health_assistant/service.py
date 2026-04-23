from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from local_health_assistant.models import (
    AdviceRequest,
    AdviceResponse,
    MessageIngestRequest,
    MessageIngestResponse,
    ReviewResponse,
)
from local_health_assistant.parsing import parse_message
from local_health_assistant.storage import Storage


class HealthService:
    def __init__(self, storage: Storage):
        self.storage = storage

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

    def sync_oura(self, target_date: date, trigger_type: str) -> dict[str, Any]:
        run_id = self.storage.start_oura_sync(target_date, trigger_type)
        self.storage.finish_oura_sync(run_id, status="failed", error_message="Oura sync client is not implemented yet.")
        return {
            "run_id": run_id,
            "target_date": target_date.isoformat(),
            "status": "failed",
            "message": "Oura sync client is not implemented yet.",
        }

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
