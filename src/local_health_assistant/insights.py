from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from local_health_assistant.models import DailyInsightsResponse, HypothesisScore


@dataclass(frozen=True)
class InsightInputs:
    target_date: date
    oura_metrics: dict[str, Any] | None
    food_logs: list[dict[str, Any]]
    hunger_logs: list[dict[str, Any]]
    latest_weight: dict[str, Any] | None
    baseline_markers: list[dict[str, Any]]


def generate_daily_insights(inputs: InsightInputs) -> DailyInsightsResponse:
    features = build_daily_features(inputs)
    hypotheses = [
        score_recovery_driven_appetite(features),
        score_plan_too_aggressive(features),
        score_tracking_gap(features),
        score_late_night_pattern(features),
        score_meal_structure_risk(features),
        score_urate_constraint(features),
        score_lipid_constraint(features),
    ]
    hypotheses = [item for item in hypotheses if item.score > 0]
    hypotheses.sort(key=lambda item: item.score, reverse=True)
    return DailyInsightsResponse(
        date=inputs.target_date,
        features=features,
        hypotheses=hypotheses,
    )


def build_daily_features(inputs: InsightInputs) -> dict[str, Any]:
    food_logs = inputs.food_logs
    hunger_logs = inputs.hunger_logs
    metrics = inputs.oura_metrics or {}
    meal_slots = {str(item.get("meal_slot") or "") for item in food_logs}
    high_hunger_count = sum(1 for item in hunger_logs if item.get("hunger_level") == "high")
    return {
        "food_log_count": len(food_logs),
        "hunger_count": len(hunger_logs),
        "high_hunger_count": high_hunger_count,
        "has_breakfast_log": "breakfast" in meal_slots,
        "has_late_night_food_log": "late_night" in meal_slots,
        "sleep_score": metrics.get("sleep_score"),
        "total_sleep_minutes": metrics.get("total_sleep_minutes"),
        "readiness_score": metrics.get("readiness_score"),
        "activity_score": metrics.get("activity_score"),
        "steps": metrics.get("steps"),
        "latest_weight_kg": inputs.latest_weight.get("weight_kg") if inputs.latest_weight else None,
        "baseline_marker_keys": [str(item.get("marker_key") or "") for item in inputs.baseline_markers],
    }


def score_recovery_driven_appetite(features: dict[str, Any]) -> HypothesisScore:
    readiness = _num(features.get("readiness_score"))
    sleep_minutes = _num(features.get("total_sleep_minutes"))
    hunger_count = int(features.get("hunger_count") or 0)
    score = 0.0
    evidence: list[str] = []

    if readiness is not None and readiness < 70:
        score += 0.35
        evidence.append(f"readiness_score is low ({readiness:g})")
    if sleep_minutes is not None and sleep_minutes < 390:
        score += 0.3
        evidence.append(f"total_sleep_minutes is short ({sleep_minutes:g})")
    if hunger_count > 0:
        score += min(0.25, hunger_count * 0.1)
        evidence.append(f"{hunger_count} hunger signal(s) logged")

    return HypothesisScore(
        hypothesis_key="recovery_driven_appetite",
        score=round(min(score, 1.0), 2),
        label="睡眠/恢复驱动食欲风险",
        evidence=evidence,
        recommendation="恢复差时不要硬控饮食，优先把选择做小、做早、做有边界。",
    )


def score_plan_too_aggressive(features: dict[str, Any]) -> HypothesisScore:
    hunger_count = int(features.get("hunger_count") or 0)
    high_hunger_count = int(features.get("high_hunger_count") or 0)
    score = 0.0
    evidence: list[str] = []
    if hunger_count >= 2:
        score += 0.45
        evidence.append(f"{hunger_count} hunger signals in one day")
    if high_hunger_count >= 1:
        score += 0.35
        evidence.append(f"{high_hunger_count} high-hunger signal(s)")

    return HypothesisScore(
        hypothesis_key="plan_too_aggressive",
        score=round(min(score, 1.0), 2),
        label="当前计划过硬风险",
        evidence=evidence,
        recommendation="如果强饥饿反复出现，先降低完美要求，增加可控加餐或提前补蛋白。",
    )


def score_tracking_gap(features: dict[str, Any]) -> HypothesisScore:
    food_log_count = int(features.get("food_log_count") or 0)
    hunger_count = int(features.get("hunger_count") or 0)
    if food_log_count > 0:
        return _zero("tracking_gap", "记录缺口")

    score = 0.7 if hunger_count > 0 else 0.5
    evidence = ["no food logs for the day"]
    if hunger_count > 0:
        evidence.append(f"{hunger_count} hunger signal(s) exist without meal context")
    return HypothesisScore(
        hypothesis_key="tracking_gap",
        score=score,
        label="记录缺口",
        evidence=evidence,
        recommendation="今天至少记录第一餐和一次饥饿信号，否则系统很难判断真正触发因素。",
    )


def score_late_night_pattern(features: dict[str, Any]) -> HypothesisScore:
    if not features.get("has_late_night_food_log"):
        return _zero("late_night_pattern", "晚间加餐模式")
    return HypothesisScore(
        hypothesis_key="late_night_pattern",
        score=0.7,
        label="晚间加餐模式",
        evidence=["late-night food log detected"],
        recommendation="晚间想吃时先预设份量，不要从包装或外卖入口开始吃。",
    )


def score_meal_structure_risk(features: dict[str, Any]) -> HypothesisScore:
    if features.get("has_breakfast_log") or int(features.get("hunger_count") or 0) == 0:
        return _zero("meal_structure_risk", "餐次结构风险")
    return HypothesisScore(
        hypothesis_key="meal_structure_risk",
        score=0.45,
        label="餐次结构风险",
        evidence=["hunger signals exist but no breakfast log was found"],
        recommendation="先观察早餐是否稳定和足量，尤其是蛋白来源，而不是直接归因到意志力。",
    )


def score_urate_constraint(features: dict[str, Any]) -> HypothesisScore:
    marker_keys = set(features.get("baseline_marker_keys") or [])
    if "high_uric_acid" not in marker_keys:
        return _zero("urate_constraint", "高尿酸约束")
    return HypothesisScore(
        hypothesis_key="urate_constraint",
        score=0.6,
        label="高尿酸约束",
        evidence=["baseline includes high_uric_acid"],
        recommendation="饮食建议应避免默认推高嘌呤方案，尤其在外食、海鲜、内脏和酒精场景下更要保守。",
    )


def score_lipid_constraint(features: dict[str, Any]) -> HypothesisScore:
    marker_keys = set(features.get("baseline_marker_keys") or [])
    if "high_total_cholesterol" not in marker_keys:
        return _zero("lipid_constraint", "血脂约束")
    return HypothesisScore(
        hypothesis_key="lipid_constraint",
        score=0.55,
        label="血脂约束",
        evidence=["baseline includes high_total_cholesterol"],
        recommendation="建议优先关注长期脂肪来源和加工食品负荷，而不是只盯体重波动。",
    )


def _num(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _zero(key: str, label: str) -> HypothesisScore:
    return HypothesisScore(
        hypothesis_key=key,
        score=0.0,
        label=label,
        evidence=[],
        recommendation="",
    )
