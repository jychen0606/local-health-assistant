from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from local_health_assistant.baseline import get_baseline, import_baseline_json
from local_health_assistant.insights import InsightInputs, generate_daily_insights
from local_health_assistant.models import (
    AdviceOutcomeRequest,
    AdviceOutcomeResponse,
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
        if parsed.advice_outcome_status:
            latest_advice = self.storage.latest_advice_record_for_session(request.session_key)
            if latest_advice:
                self.storage.record_advice_outcome(
                    advice_record_id=int(latest_advice["id"]),
                    outcome_status=parsed.advice_outcome_status,
                    outcome_note=parsed.advice_outcome_note,
                    evaluation_window_end=occurred_at.isoformat(),
                )
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
        baseline_markers = self.storage.list_health_markers()
        adherence_summary = self._summarize_recent_adherence()

        key_issue = self._determine_key_issue(
            foods, recent_hunger, recent_metrics, baseline_markers, adherence_summary
        )
        recommended_adjustment = self._determine_adjustment(
            foods, recent_hunger, goals.model_dump(mode="json"), baseline_markers, adherence_summary
        )
        realism_note = self._determine_realism_note(
            recent_hunger, recent_metrics, baseline_markers, adherence_summary
        )

        review_text = "\n".join(
            [
                f"# 每日复盘 - {review_date.isoformat()}",
                "",
                f"- 昨天最关键的问题：{key_issue}",
                f"- 今天最值得调整的一件事：{recommended_adjustment}",
                f"- 这条建议是否现实：{realism_note}",
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
                baseline_markers=self.storage.list_health_markers(),
                adherence_summary=self._summarize_recent_adherence(),
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
        baseline_markers = self.storage.list_health_markers()
        baseline_keys = {str(item.get("marker_key") or "") for item in baseline_markers}
        adherence_summary = self._summarize_recent_adherence()

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

        if adherence_summary["not_followed"] >= 2:
            conclusion = "可以吃，但只建议做你最近能稳定执行的小版本。"
            why += " 最近几次建议执行落差偏大，当前更重要的是降低方案摩擦，而不是追求更硬。"
            realistic_alternative = "把选择缩成最小可执行版本，比如提前定份量、只买单份、不要再叠加补偿式运动。"

        if latest_weight and goals.get("target_weight_range_kg", {}).get("max") is not None:
            if latest_weight["weight_kg"] > float(goals["target_weight_range_kg"]["max"]):
                why += " 当前体重也在目标上沿之外，建议优先保住节奏。"
        if "high_uric_acid" in baseline_keys:
            why += " 你有高尿酸基线，后续饮食选择应避免默认走高嘌呤补偿路线。"
        if "high_urea" in baseline_keys:
            why += " 你还有尿素偏高记录，当天恢复一般时不适合再走过干、过激进的补偿路线。"
        if "high_total_cholesterol" in baseline_keys:
            why += " 你的基线血脂也提示需要更关注脂肪来源和长期饮食结构。"
        if "high_waist_hip_ratio" in baseline_keys:
            why += " 体脂分布也提示要更看重长期稳定和晚间边界，而不是只盯体重数字。"
        if "low_diastolic_blood_pressure" in baseline_keys:
            realistic_alternative += " 如果今天状态一般，不要把节食、脱水和高强度训练叠在同一天。"
        if "sinus_bradycardia" in baseline_keys:
            realistic_alternative = (
                realistic_alternative + " 如果当天恢复一般，也不要把补偿方案和运动量一起拉太高。"
            )

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
                "recent_adherence_summary": adherence_summary,
                "baseline_marker_keys": sorted(baseline_keys),
            },
        )
        return AdviceResponse(
            advice_record_id=advice_record_id,
            conclusion=conclusion,
            why=why,
            realistic_alternative=realistic_alternative,
            advice_text=advice_text,
        )

    def record_advice_outcome(self, request: AdviceOutcomeRequest) -> AdviceOutcomeResponse:
        return self.storage.record_advice_outcome(
            advice_record_id=request.advice_record_id,
            outcome_status=request.outcome_status,
            outcome_note=request.outcome_note,
            evaluation_window_end=(request.evaluation_window_end.isoformat() if request.evaluation_window_end else None),
        )

    def run_morning_briefing(self, target_date: date | None = None) -> dict[str, Any]:
        briefing_date = target_date or (date.today() - timedelta(days=1))
        sync_result = self.sync_oura(briefing_date, trigger_type="scheduled")
        review = self.generate_review(briefing_date)
        insights = self.generate_insights(briefing_date)
        return {
            "target_date": briefing_date.isoformat(),
            "sync_result": sync_result,
            "review": review.model_dump(mode="json"),
            "insights": insights.model_dump(mode="json"),
        }

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
        baseline_markers: list[dict[str, Any]],
        adherence_summary: dict[str, int],
    ) -> str:
        baseline_keys = {str(item.get("marker_key") or "") for item in baseline_markers}
        if recent_metrics and (recent_metrics[0].get("readiness_score") or 0) < 70:
            return "最近恢复偏弱，今天更容易从想吃一点滑到补偿性进食。"
        if len(recent_hunger) >= 2:
            return "最近强饥饿信号偏多，说明当前计划对你来说有点太硬。"
        if adherence_summary["not_followed"] >= 2:
            return "最近建议执行落差偏多，真正的问题不是懂不懂，而是方案摩擦太大。"
        if "high_uric_acid" in baseline_keys:
            return "你有高尿酸基线，饮食选择要优先避免滑向高嘌呤的补偿路线。"
        if "high_waist_hip_ratio" in baseline_keys:
            return "当前更值得盯的是体脂分布和晚间边界，而不是只看体重有没有立刻下降。"
        if "high_total_cholesterol" in baseline_keys:
            return "你的基线血脂已经在提醒长期食物质量，而不只是体重波动。"
        if not foods:
            return "昨天记录太少，当前最大的缺口还是缺少足够上下文来判断。"
        return "没有明显失控点，但吃的结构还可以更稳一点。"

    def _determine_adjustment(
        self,
        foods: list[dict[str, Any]],
        recent_hunger: list[dict[str, Any]],
        goals: dict[str, Any],
        baseline_markers: list[dict[str, Any]],
        adherence_summary: dict[str, int],
    ) -> str:
        baseline_keys = {str(item.get("marker_key") or "") for item in baseline_markers}
        if len(recent_hunger) >= 2:
            return "把蛋白和正餐重心前置，先降低晚上临时起意的概率。"
        if adherence_summary["not_followed"] >= 2:
            return "今天先把计划缩成最小可执行版本，只保留你大概率能做到的那一步。"
        if "high_uric_acid" in baseline_keys:
            return "今天尽量走稳定、偏低嘌呤的默认餐次，而不是晚上再靠奖励型进食补回来。"
        if "high_waist_hip_ratio" in baseline_keys:
            return "优先收紧晚间加餐边界和餐次稳定性，这比再去追更低的体重数字更重要。"
        if "high_total_cholesterol" in baseline_keys:
            return "今天最值得调整的是减少加工和高饱和脂肪选择，而不是追求更硬的短期限制。"
        if "low_diastolic_blood_pressure" in baseline_keys:
            return "今天别把节食、脱水和高强度训练叠在一起，先保住稳定感和恢复。"
        if not foods:
            return "今天至少把第一餐和一次明显饥饿记下来，先把可判断的数据补齐。"
        if goals.get("late_night_snack_limit", 0) <= 2:
            return "如果晚上想吃，先把份量定死，再开始吃。"
        return "重复昨天最容易做到的部分，不要额外加码。"

    def _determine_realism_note(
        self,
        recent_hunger: list[dict[str, Any]],
        recent_metrics: list[dict[str, Any]],
        baseline_markers: list[dict[str, Any]],
        adherence_summary: dict[str, int],
    ) -> str:
        baseline_keys = {str(item.get("marker_key") or "") for item in baseline_markers}
        if recent_metrics and (recent_metrics[0].get("readiness_score") or 0) < 70:
            return "现实，因为恢复差的时候本来就更难靠意志力扛住，今天放软一点更像能做到的方案。"
        if len(recent_hunger) >= 2:
            return "现实，但前提是不是追求完美，而是接受一个可控的小版本。"
        if adherence_summary["not_followed"] >= 2:
            return "现实，但只有在你愿意先做小、先做稳时才现实；继续加码大概率还是做不到。"
        if "sinus_bradycardia" in baseline_keys:
            return "现实，因为你的基线更适合恢复优先、节奏保守的方案，不适合硬上强度。"
        if "low_diastolic_blood_pressure" in baseline_keys:
            return "现实，但要避免空腹太久、脱水或训练拉太猛，不然执行体验会很差。"
        return "现实，前提是你在很饿之前就把决定做掉。"

    def _weight_context_line(self, latest_weight: dict[str, Any] | None) -> str:
        if not latest_weight:
            return "- 最新体重：还没有记录。"
        return f"- 最新体重：{latest_weight['weight_kg']:.1f}kg。"

    def _summarize_recent_adherence(self, days: int = 7) -> dict[str, int]:
        summary = {"followed": 0, "partially_followed": 0, "not_followed": 0}
        for row in self.storage.list_recent_advice_outcomes(days=days):
            status = str(row.get("outcome_status") or "")
            if status in summary:
                summary[status] += 1
        return summary
