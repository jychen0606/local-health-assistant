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
    GeneratedFeedback,
    GoalPayload,
    HealthContextKnown,
    HealthContextOuraStatus,
    HealthContextResponse,
    HealthContextStrategy,
    MealFeedbackResponse,
    MessageIngestRequest,
    MessageIngestResponse,
    OnboardingProfile,
    OnboardingResponse,
    OuraAuthStartResponse,
    OuraCallbackResponse,
    ReviewResponse,
    WeightAnomalyReviewResponse,
)
from local_health_assistant.oura import (
    OuraAPIError,
    OuraClient,
    OuraOAuthClient,
    compute_expires_at,
    is_token_expired,
    normalize_activity_context,
    normalize_daily_metrics,
)
from local_health_assistant.parsing import parse_message
from local_health_assistant.storage import Storage

SUGARY_KEYWORDS = ("可乐", "奶茶", "果汁", "甜点", "蛋糕", "冰淇淋", "糖", "甜")
PROCESSED_KEYWORDS = ("炸", "薯条", "汉堡", "香肠", "火腿", "饼干", "零食", "泡面", "加工")
PROTEIN_KEYWORDS = ("鸡", "蛋", "牛肉", "鱼", "虾", "豆腐", "酸奶", "牛奶", "羊肉", "猪肉")
VEGETABLE_KEYWORDS = ("菜", "西兰花", "沙拉", "番茄", "黄瓜", "青菜", "胡萝卜", "蔬菜")


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
        generated_feedback: list[GeneratedFeedback] = []
        for record in parsed.extracted:
            if record.record_type == "food":
                food_log_id = self.storage.save_food_log(event_id, record.payload, record.confidence)
                meal_feedback = self._evaluate_meal_record(
                    conversation_event_id=event_id,
                    food_log_id=food_log_id,
                    meal_payload=record.payload,
                )
                generated_feedback.append(
                    GeneratedFeedback(
                        feedback_type="meal_feedback",
                        payload=meal_feedback.model_dump(mode="json"),
                    )
                )
            elif record.record_type == "hunger":
                self.storage.save_hunger_log(event_id, record.payload, record.confidence)
            elif record.record_type == "weight":
                weight_log_id = self.storage.save_weight_log(event_id, record.payload, record.confidence)
                if record.payload.get("measurement_context") == "morning":
                    anomaly_review = self._evaluate_weight_anomaly(
                        weight_log_id=weight_log_id,
                        weight_kg=float(record.payload["weight_kg"]),
                        logged_at=record.payload["logged_at"],
                    )
                    generated_feedback.append(
                        GeneratedFeedback(
                            feedback_type="weight_anomaly_review",
                            payload=anomaly_review.model_dump(mode="json"),
                        )
                    )
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
            generated_feedback=generated_feedback,
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

    def get_onboarding(self) -> OnboardingResponse:
        stored = self.storage.get_onboarding_profile()
        if stored:
            profile = OnboardingProfile.model_validate(stored)
            goals, notes = self._derive_goals_from_profile(profile)
            return OnboardingResponse(profile=profile, goals=goals, derived_notes=notes)
        goals = self.storage.load_goals()
        midpoint = (goals.target_weight_range_kg["min"] + goals.target_weight_range_kg["max"]) / 2
        profile = OnboardingProfile(
            current_weight_kg=round(midpoint, 1),
            target_weight_kg=round(midpoint, 1),
            primary_activities=[],
            weekly_activity_sessions=goals.weekly_training_target,
            average_session_minutes=None,
            dietary_preferences=None,
        )
        return OnboardingResponse(
            profile=profile,
            goals=goals,
            derived_notes=[
                "还没有保存基础信息，当前显示由已有 goals 反推的默认值。",
                "保存后系统会根据基础信息重新推导内部目标。",
            ],
        )

    def save_onboarding(self, profile: OnboardingProfile) -> OnboardingResponse:
        goals, notes = self._derive_goals_from_profile(profile)
        self.storage.save_onboarding_profile(profile.model_dump(mode="json"))
        saved_goals = self.storage.save_goals(goals, source_version="onboarding")
        return OnboardingResponse(profile=profile, goals=saved_goals, derived_notes=notes)

    def get_context(self) -> HealthContextResponse:
        onboarding_payload = self.storage.get_onboarding_profile()
        onboarding_profile = (
            OnboardingProfile.model_validate(onboarding_payload)
            if onboarding_payload
            else None
        )
        goals = self.storage.load_goals()
        goal_payload = goals.model_dump(mode="json")
        baseline_reports = self.storage.list_baseline_reports()
        baseline_markers = self.storage.list_health_markers()
        baseline_keys = sorted({str(item.get("marker_key") or "") for item in baseline_markers if item.get("marker_key")})
        recent_foods = self.storage.list_food_logs_for_window(days=7)
        recent_weights = self.storage.list_recent_weight_logs(limit=7)
        recent_hunger = self.storage.list_hunger_logs_for_window(days=7)
        recent_metrics = self.storage.list_recent_metrics(days=7)
        recent_outcomes = self.storage.list_recent_advice_outcomes(days=7)
        latest_daily_sync = self.storage.latest_oura_sync_run()
        latest_activity_sync = self.storage.latest_oura_activity_sync_run()
        oura_token = self.storage.get_oauth_token("oura")

        known = HealthContextKnown(
            onboarding_profile=onboarding_profile is not None,
            baseline_report=bool(baseline_reports),
            oura_token=bool(oura_token and oura_token.get("access_token")),
            latest_oura_sync_date=_date_or_none(latest_daily_sync.get("target_date") if latest_daily_sync else None),
            latest_activity_sync_date=_date_or_none(
                latest_activity_sync.get("target_date") if latest_activity_sync else None
            ),
            recent_food_logs=len(recent_foods),
            recent_weight_logs=len(recent_weights),
            recent_hunger_logs=len(recent_hunger),
            recent_oura_days=len(recent_metrics),
            recent_advice_outcomes=len(recent_outcomes),
        )
        strategy = self._build_context_strategy(
            goals=goal_payload,
            onboarding_profile=onboarding_profile,
            baseline_keys=baseline_keys,
            recent_metrics=recent_metrics,
            recent_hunger=recent_hunger,
            recent_foods=recent_foods,
        )
        missing = self._build_context_missing(
            known=known,
            recent_weights=recent_weights,
            recent_foods=recent_foods,
            recent_hunger=recent_hunger,
            recent_outcomes=recent_outcomes,
        )
        next_question = self._build_context_next_question(missing, baseline_keys, recent_hunger, recent_foods)
        return HealthContextResponse(
            known=known,
            current_strategy=strategy,
            oura_status=HealthContextOuraStatus(
                token_present=known.oura_token,
                latest_daily_sync=_sync_summary(latest_daily_sync),
                latest_activity_sync=_sync_summary(latest_activity_sync),
                recent_metrics=[_metric_summary(item) for item in recent_metrics],
            ),
            missing=missing,
            next_question=next_question,
        )

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

    def get_abnormal_weight_review(self, target_date: date) -> WeightAnomalyReviewResponse | None:
        return self.storage.get_abnormal_weight_review(target_date)

    def _derive_goals_from_profile(self, profile: OnboardingProfile) -> tuple[GoalPayload, list[str]]:
        target_weight = round(profile.target_weight_kg, 1)
        tolerance = max(0.8, round(target_weight * 0.015, 1))
        target_min = round(target_weight - tolerance, 1)
        target_max = round(target_weight + tolerance, 1)
        current_weight = profile.current_weight_kg
        weight_delta = current_weight - target_weight
        phase = "maintenance"
        if weight_delta > 1.0:
            phase = "fat_loss"
        elif weight_delta < -1.0:
            phase = "muscle_gain"

        protein_factor = 1.6 if phase == "fat_loss" else 1.4
        if any(activity in profile.primary_activities for activity in ("strength", "boxing", "tennis")):
            protein_factor += 0.1
        protein_min = int(round(current_weight * protein_factor / 5) * 5)

        estimated_bmr = current_weight * 22
        activity_minutes = (profile.average_session_minutes or 45) * profile.weekly_activity_sessions
        activity_factor = 1.25
        if activity_minutes >= 240:
            activity_factor = 1.45
        elif activity_minutes >= 120:
            activity_factor = 1.35
        maintenance = int(round(estimated_bmr * activity_factor / 50) * 50)
        if phase == "fat_loss":
            calorie_min = max(1200, maintenance - 450)
            calorie_max = max(calorie_min + 150, maintenance - 200)
        elif phase == "muscle_gain":
            calorie_min = maintenance + 100
            calorie_max = maintenance + 300
        else:
            calorie_min = maintenance - 150
            calorie_max = maintenance + 150

        late_night_limit = 2
        preferences = (profile.dietary_preferences or "").lower()
        if "夜宵" in preferences or "late" in preferences or "snack" in preferences:
            late_night_limit = 1

        goals = GoalPayload(
            current_phase=phase,
            target_weight_range_kg={"min": target_min, "max": target_max},
            protein_min_g=protein_min,
            calorie_range={"min": int(calorie_min), "max": int(calorie_max)},
            weekly_training_target=profile.weekly_activity_sessions,
            late_night_snack_limit=late_night_limit,
        )
        notes = [
            f"目标体重按 {target_weight:.1f}kg 自动生成 {target_min:.1f}-{target_max:.1f}kg 的观察区间。",
            f"蛋白下限按当前体重和活动结构估算为 {protein_min}g，不需要手填。",
            f"热量区间按体重、目标方向和每周活动量粗估为 {calorie_min}-{calorie_max} kcal。",
            f"训练目标保留为每周 {profile.weekly_activity_sessions} 次，用来描述可执行频率，不代表所有运动强度等价。",
        ]
        baseline_keys = {str(item.get("marker_key") or "") for item in self.storage.list_health_markers()}
        if "high_uric_acid" in baseline_keys:
            notes.append("已读到尿酸偏高基线，饮食建议会避免默认高嘌呤和极端补偿路线。")
        if "high_total_cholesterol" in baseline_keys:
            notes.append("已读到总胆固醇偏高基线，后续建议会更关注脂肪来源和加工食品负担。")
        if "high_waist_hip_ratio" in baseline_keys:
            notes.append("已读到腰臀比偏高基线，策略会更重视体脂分布、餐次稳定和晚间边界。")
        if "low_diastolic_blood_pressure" in baseline_keys or "sinus_bradycardia" in baseline_keys:
            notes.append("已读到恢复/循环相关基线，系统会避免把节食、脱水和高强度训练叠在同一天。")
        return goals, notes

    def _build_context_strategy(
        self,
        goals: dict[str, Any],
        onboarding_profile: OnboardingProfile | None,
        baseline_keys: list[str],
        recent_metrics: list[dict[str, Any]],
        recent_hunger: list[dict[str, Any]],
        recent_foods: list[dict[str, Any]],
    ) -> HealthContextStrategy:
        target_range = goals.get("target_weight_range_kg") or {}
        target_min = float(target_range["min"]) if target_range.get("min") is not None else None
        target_max = float(target_range["max"]) if target_range.get("max") is not None else None
        target_weight = onboarding_profile.target_weight_kg if onboarding_profile else None
        if target_weight is None and target_min is not None and target_max is not None:
            target_weight = round((target_min + target_max) / 2, 1)
        risk_constraints = [key for key in baseline_keys if key in {
            "high_uric_acid",
            "high_total_cholesterol",
            "high_waist_hip_ratio",
            "low_diastolic_blood_pressure",
            "sinus_bradycardia",
            "high_urea",
        }]
        nutrition_strategy = "优先稳定餐次结构，避免把单次波动升级成极端限制或补偿性进食。"
        if "high_uric_acid" in risk_constraints:
            nutrition_strategy = "优先稳定餐次结构，避免默认高嘌呤和极端补偿路线。"
        if "high_total_cholesterol" in risk_constraints:
            nutrition_strategy += " 同时关注脂肪来源和加工食品负担。"
        activity_strategy = "把运动当作补充和恢复的上下文，不把运动量当作放开吃或过度限制的理由。"
        if recent_metrics and (recent_metrics[0].get("readiness_score") or 0) < 70:
            activity_strategy += " 最近恢复偏弱时，建议会更保守。"
        evidence = [
            f"最近 7 天食物记录 {len(recent_foods)} 条",
            f"最近 7 天饥饿/想吃信号 {len(recent_hunger)} 条",
            f"最近 Oura 指标 {len(recent_metrics)} 天",
        ]
        if risk_constraints:
            evidence.append("已读取健康基线约束：" + ", ".join(risk_constraints))
        return HealthContextStrategy(
            phase=str(goals.get("current_phase") or "unknown"),
            target_weight_kg=target_weight,
            target_observation_range_kg=[
                round(target_min, 1) if target_min is not None else 0.0,
                round(target_max, 1) if target_max is not None else 0.0,
            ],
            nutrition_strategy=nutrition_strategy,
            activity_strategy=activity_strategy,
            risk_constraints=risk_constraints,
            evidence=evidence,
        )

    def _build_context_missing(
        self,
        known: HealthContextKnown,
        recent_weights: list[dict[str, Any]],
        recent_foods: list[dict[str, Any]],
        recent_hunger: list[dict[str, Any]],
        recent_outcomes: list[dict[str, Any]],
    ) -> list[str]:
        missing: list[str] = []
        if not known.onboarding_profile:
            missing.append("保存基础信息：当前体重、目标体重、身高和运动结构")
        if not known.baseline_report:
            missing.append("导入健康基线报告，用来约束饮食和恢复建议")
        if not known.oura_token:
            missing.append("确认 Oura 授权或明确暂时不使用 Oura")
        if len(recent_weights) < 3:
            missing.append("至少 3 条最近晨起体重记录")
        if len(recent_foods) < 6:
            missing.append("更多完整餐食记录，尤其是晚餐、饮料、甜食和夜宵")
        if not recent_hunger:
            missing.append("记录一次明显饥饿或想吃东西的场景")
        if not recent_outcomes:
            missing.append("记录一次建议是否做到，用来校准建议难度")
        return missing

    def _build_context_next_question(
        self,
        missing: list[str],
        baseline_keys: list[str],
        recent_hunger: list[dict[str, Any]],
        recent_foods: list[dict[str, Any]],
    ) -> str:
        if any("基础信息" in item for item in missing):
            return "你现在的当前体重、目标体重、身高和每周主要运动大概是什么？"
        if any("晨起体重" in item for item in missing):
            return "明早方便记录一次起床后体重吗？连续几天后我才能判断趋势。"
        if any("餐食记录" in item for item in missing):
            return "下一餐可以用“早餐/午餐/晚餐：吃了什么”这种轻格式发我吗？"
        if any("饥饿" in item for item in missing):
            return "下次明显想吃东西时，告诉我发生在饭后多久、是真的饿还是嘴馋。"
        if "high_uric_acid" in baseline_keys:
            return "你运动后最常想补充的是正餐、甜食、饮料，还是高蛋白/肉类？"
        if any(item.get("meal_slot") == "late_night" for item in recent_foods):
            return "夜间想吃东西通常是在晚餐后多久出现？"
        if len(recent_hunger) >= 2:
            return "最近这些想吃东西的时刻，更像没吃够、运动后需要补充，还是情绪性想吃？"
        return "今天如果有运动，结束后告诉我运动类型、时长和饥饿程度。"

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
        if recent_metrics and (
            (recent_metrics[0].get("active_calories") or 0) >= 300
            or (recent_metrics[0].get("steps") or 0) >= 8000
        ):
            why += " 今天已经有一定活动量，判断时不建议再用过度限制去做补偿。"
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

    def run_activity_sync(self, target_date: date | None = None, trigger_type: str = "scheduled") -> dict[str, Any]:
        sync_date = target_date or date.today()
        run_id = self.storage.start_oura_activity_sync(sync_date, trigger_type)
        effective_client = self._oura_client_with_stored_token()
        if effective_client is None:
            message = "Oura client is not configured."
            self.storage.finish_oura_activity_sync(run_id, status="failed", error_message=message)
            return {"run_id": run_id, "target_date": sync_date.isoformat(), "status": "failed", "message": message}
        try:
            snapshot = effective_client.fetch_activity_snapshot(sync_date)
            snapshot_path = self.storage.save_oura_activity_snapshot(sync_date, snapshot)
            context = normalize_activity_context(snapshot, sync_date, str(snapshot_path))
            self.storage.patch_oura_activity_metrics(
                target_date=sync_date,
                activity_score=context.get("activity_score"),
                active_calories=context.get("active_calories"),
                steps=context.get("steps"),
                activity_contributors=context.get("activity_contributors"),
                snapshot_path=str(snapshot_path),
            )
            new_workouts = self.storage.save_workouts(context.get("workouts") or [])
        except Exception as e:
            message = str(e)
            self.storage.finish_oura_activity_sync(run_id, status="failed", error_message=message)
            result = {"run_id": run_id, "target_date": sync_date.isoformat(), "status": "failed", "message": message}
            problem = self._structured_oura_problem(e)
            if problem:
                result["oura_error"] = problem
            return result
        self.storage.finish_oura_activity_sync(run_id, status="success")
        return {
            "run_id": run_id,
            "target_date": sync_date.isoformat(),
            "status": "success",
            "activity_score": context.get("activity_score"),
            "active_calories": context.get("active_calories"),
            "steps": context.get("steps"),
            "new_workout_count": len(new_workouts),
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

    def _evaluate_meal_record(
        self,
        conversation_event_id: int,
        food_log_id: int,
        meal_payload: dict[str, Any],
    ) -> MealFeedbackResponse:
        logged_at = str(meal_payload["logged_at"])
        meal_slot = str(meal_payload["meal_slot"])
        description = str(meal_payload["description"])
        baseline_keys = {str(item.get("marker_key") or "") for item in self.storage.list_health_markers()}
        recent_metrics = self.storage.list_recent_metrics(days=3)
        adherence_summary = self._summarize_recent_adherence()
        recent_foods = self.storage.list_food_logs_for_window(days=7)
        today_foods = self.storage.list_food_logs_for_date(date.fromisoformat(logged_at[:10]))

        sugary = _contains_any(description, SUGARY_KEYWORDS)
        processed = _contains_any(description, PROCESSED_KEYWORDS)
        protein = _contains_any(description, PROTEIN_KEYWORDS)
        vegetable = _contains_any(description, VEGETABLE_KEYWORDS)
        late_night_recent = sum(1 for item in recent_foods if item.get("meal_slot") == "late_night")
        dessert_like_recent = sum(1 for item in recent_foods if _contains_any(str(item.get("description") or ""), SUGARY_KEYWORDS))

        evaluation_summary = "这顿先算可用，但还不够稳。"
        biggest_issue = "当前最大问题还不明显。"
        positive_note: str | None = None

        if sugary and processed:
            evaluation_summary = "这顿能量密度和加工度都偏高。"
            biggest_issue = "甜饮/甜品和高加工内容叠在一起，下一顿别再补偿性乱收。"
        elif sugary:
            evaluation_summary = "这顿最需要注意的是糖和液体热量。"
            biggest_issue = "如果这是正餐，再叠甜饮或甜品会让下一顿更难判断。"
        elif not protein:
            evaluation_summary = "这顿的核心短板是蛋白不够明确。"
            biggest_issue = "如果这一顿蛋白偏少，下一顿更容易靠嘴馋来补。"
        elif processed:
            evaluation_summary = "这顿有点偏加工食品导向。"
            biggest_issue = "加工度偏高时，饱腹感和后续决策通常都更差。"
        else:
            evaluation_summary = "这顿整体还算稳。"
            biggest_issue = "没有明显爆点，但也别因此把下一顿放飞。"

        if protein:
            positive_note = "至少蛋白来源是明确的。"
        elif vegetable:
            positive_note = "至少有一些蔬菜或低能量密度内容。"

        next_meal_suggestion = "下一顿优先把蛋白和蔬菜补齐，主食正常吃，不要因为这一顿有波动就故意不吃。"
        if sugary and protein:
            next_meal_suggestion = "下一顿清一点就够，先补蛋白和蔬菜，别再叠甜饮或甜品，也别补偿性挨饿。"
        elif sugary:
            next_meal_suggestion = "下一顿优先稳定血糖波动：蛋白正常、蔬菜优先、主食正常吃，不要再叠甜饮。"
        elif not protein:
            next_meal_suggestion = "下一顿最重要的是把蛋白补明确，再决定主食和加餐，不要靠零食补回来。"
        elif processed:
            next_meal_suggestion = "下一顿尽量回到低加工一点的组合：明确蛋白、正常主食、少包装零食。"

        if late_night_recent >= 2:
            next_meal_suggestion += " 最近晚间进食偏多，今晚尽量提前把份量边界定好。"
        if dessert_like_recent >= 3:
            next_meal_suggestion += " 最近 7 天甜口/饮料频率偏高，下一顿别再用“奖励自己”当理由。"
        if adherence_summary["not_followed"] >= 2:
            next_meal_suggestion += " 这次先做最小可执行版本，不要一口气把标准拉太满。"
        if baseline_keys.intersection({"high_uric_acid", "high_urea"}):
            next_meal_suggestion += " 结合你的基线，下一顿尽量别走重口、高嘌呤、过激进补偿路线。"
        if "high_total_cholesterol" in baseline_keys:
            next_meal_suggestion += " 也要顺手把脂肪来源收干净一点。"
        if "high_waist_hip_ratio" in baseline_keys:
            next_meal_suggestion += " 重点还是稳住结构和晚间边界，不是靠下一顿极端补救。"
        if "low_diastolic_blood_pressure" in baseline_keys:
            next_meal_suggestion += " 不要把下一顿省掉，也不要用过度限制来纠错。"
        if recent_metrics and (recent_metrics[0].get("readiness_score") or 0) < 70:
            next_meal_suggestion += " 今天恢复一般，下一顿更应该求稳，不要一边累一边硬控。"
        if recent_metrics and (
            (recent_metrics[0].get("active_calories") or 0) >= 300
            or (recent_metrics[0].get("steps") or 0) >= 8000
        ):
            next_meal_suggestion += " 今天已经有一定活动量，下一顿别再走过度限制式补偿。"
        if len(today_foods) >= 3:
            next_meal_suggestion += " 今天已经吃了不少次，下一顿更要简短清楚，不要再加散碎加餐。"

        evaluation_text = f"{evaluation_summary} 最大问题是：{biggest_issue}"
        if positive_note:
            evaluation_text += f" 但也有一个优点：{positive_note}"

        feedback = MealFeedbackResponse(
            logged_at=datetime.fromisoformat(logged_at),
            meal_slot=meal_slot,
            evaluation_summary=evaluation_summary,
            biggest_issue=biggest_issue,
            positive_note=positive_note,
            evaluation_text=evaluation_text,
            next_meal_suggestion=next_meal_suggestion,
        )
        self.storage.save_meal_feedback(
            conversation_event_id=conversation_event_id,
            food_log_id=food_log_id,
            logged_at=logged_at,
            meal_slot=meal_slot,
            evaluation_summary=evaluation_summary,
            biggest_issue=biggest_issue,
            positive_note=positive_note,
            evaluation_text=evaluation_text,
            next_meal_suggestion=next_meal_suggestion,
        )
        return feedback

    def _evaluate_weight_anomaly(
        self,
        weight_log_id: int,
        weight_kg: float,
        logged_at: str,
    ) -> WeightAnomalyReviewResponse:
        target_date = date.fromisoformat(logged_at[:10])
        previous_morning_weights = self.storage.list_recent_weight_logs(
            limit=3,
            measurement_context="morning",
            before_logged_at=logged_at,
        )
        reference_weight = self._build_weight_reference(previous_morning_weights, logged_at)
        delta_kg = round(weight_kg - reference_weight, 2) if reference_weight is not None else None
        is_abnormal = bool(delta_kg is not None and abs(delta_kg) >= 1.0)

        yesterday = target_date - timedelta(days=1)
        recent_metrics = self.storage.list_recent_metrics(days=3)
        yesterday_metrics = self.storage.get_oura_daily_metrics(yesterday)
        yesterday_foods = self.storage.list_food_logs_for_date(yesterday)
        yesterday_hunger = self.storage.list_hunger_logs_for_date(yesterday)
        baseline_markers = self.storage.list_health_markers()

        suspected_drivers = self._weight_anomaly_drivers(
            delta_kg=delta_kg,
            yesterday_metrics=yesterday_metrics,
            yesterday_foods=yesterday_foods,
            yesterday_hunger=yesterday_hunger,
            baseline_markers=baseline_markers,
            recent_metrics=recent_metrics,
        )
        review_text, recommended_action = self._weight_anomaly_message(
            weight_kg=weight_kg,
            reference_weight=reference_weight,
            delta_kg=delta_kg,
            is_abnormal=is_abnormal,
            suspected_drivers=suspected_drivers,
        )

        return self.storage.save_abnormal_weight_review(
            target_date=target_date,
            weight_log_id=weight_log_id,
            weight_kg=weight_kg,
            reference_weight_kg=reference_weight,
            delta_kg=delta_kg,
            is_abnormal=is_abnormal,
            suspected_drivers=suspected_drivers,
            review_text=review_text,
            recommended_action=recommended_action,
        )

    def _build_weight_reference(self, previous_morning_weights: list[dict[str, Any]], logged_at: str) -> float | None:
        if len(previous_morning_weights) >= 3:
            values = [float(item["weight_kg"]) for item in previous_morning_weights[:3]]
            return round(sum(values) / len(values), 2)
        previous_any = self.storage.list_recent_weight_logs(limit=1, before_logged_at=logged_at)
        if previous_any:
            return round(float(previous_any[0]["weight_kg"]), 2)
        return None

    def _weight_anomaly_drivers(
        self,
        delta_kg: float | None,
        yesterday_metrics: dict[str, Any] | None,
        yesterday_foods: list[dict[str, Any]],
        yesterday_hunger: list[dict[str, Any]],
        baseline_markers: list[dict[str, Any]],
        recent_metrics: list[dict[str, Any]],
    ) -> list[str]:
        drivers: list[str] = []
        baseline_keys = {str(item.get("marker_key") or "") for item in baseline_markers}
        if delta_kg is not None:
            if delta_kg >= 1.0:
                drivers.append("更像短期上浮，先按水分、节奏或前一天结构变化看。")
            elif delta_kg <= -1.0:
                drivers.append("更像短期下探，先不要直接当成脂肪变化。")
        if yesterday_metrics and (yesterday_metrics.get("readiness_score") or 0) < 70:
            drivers.append("昨天恢复一般，短期体重和食欲都更容易波动。")
        if not yesterday_foods:
            drivers.append("昨天饮食记录缺口较大，解释可信度会下降。")
        if any(item.get("meal_slot") == "late_night" for item in yesterday_foods):
            drivers.append("昨天有晚间进食，容易带来第二天体重短期波动。")
        if len(yesterday_hunger) >= 2:
            drivers.append("昨天强饥饿信号偏多，说明前一天节奏可能已经不稳。")
        if "low_diastolic_blood_pressure" in baseline_keys:
            drivers.append("你有低舒张压基线，不适合看到波动就立刻加大限制。")
        if "high_uric_acid" in baseline_keys:
            drivers.append("你有高尿酸基线，调整时不要走极端补偿路线。")
        if recent_metrics and len(recent_metrics) >= 2:
            latest_steps = recent_metrics[0].get("steps") or 0
            older_steps = recent_metrics[1].get("steps") or 0
            if latest_steps and older_steps and abs(latest_steps - older_steps) >= 3000:
                drivers.append("最近活动量变化不小，体重波动未必只是吃出来的。")
        return drivers[:4]

    def _weight_anomaly_message(
        self,
        weight_kg: float,
        reference_weight: float | None,
        delta_kg: float | None,
        is_abnormal: bool,
        suspected_drivers: list[str],
    ) -> tuple[str, str]:
        if reference_weight is None or delta_kg is None:
            return (
                f"今天记录了 {weight_kg:.1f}kg，但参考体重数据还不够，先继续稳定记录。",
                "先连续记录几天晨起体重，再判断这次变化是不是异常。",
            )
        if not is_abnormal:
            return (
                f"今天体重 {weight_kg:.1f}kg，和参考值 {reference_weight:.1f}kg 的差异是 {delta_kg:+.1f}kg，暂时不算异常波动。",
                "先正常记录，按原计划执行，不要因为单日小波动临时加码。",
            )
        driver_text = " ".join(suspected_drivers) if suspected_drivers else "先按短期波动处理，不直接下结论。"
        return (
            f"今天体重 {weight_kg:.1f}kg，相比参考值 {reference_weight:.1f}kg 变化 {delta_kg:+.1f}kg，已达到异常波动阈值。{driver_text}",
            "今天先把饮食结构、补水和节奏做稳，不要立刻走补偿性节食或报复性放开吃。",
        )

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


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)


def _date_or_none(value: Any) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _sync_summary(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    return {
        "target_date": row.get("target_date"),
        "trigger_type": row.get("trigger_type"),
        "status": row.get("status"),
        "error_message": row.get("error_message"),
        "started_at": row.get("started_at"),
        "finished_at": row.get("finished_at"),
    }


def _metric_summary(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "date": row.get("date"),
        "sleep_score": row.get("sleep_score"),
        "readiness_score": row.get("readiness_score"),
        "activity_score": row.get("activity_score"),
        "active_calories": row.get("active_calories"),
        "steps": row.get("steps"),
    }
