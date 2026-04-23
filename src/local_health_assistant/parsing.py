from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from local_health_assistant.models import ExtractedRecord


MEAL_KEYWORDS = ("早餐", "午餐", "晚餐", "夜宵", "加餐", "吃了", "喝了")
HUNGER_KEYWORDS = ("很饿", "饿死", "想吃", "嘴馋", "暴食", "控制不住", "好饿", "特别饿")
ADVICE_KEYWORDS = ("能不能吃", "可以吃", "该不该吃", "今天能不能", "要不要吃")

WEIGHT_PATTERN = re.compile(r"(?P<value>\d{2,3}(?:\.\d+)?)\s*(?P<unit>kg|KG|公斤|千克|斤)")


@dataclass(frozen=True)
class ParseResult:
    extracted: list[ExtractedRecord]
    is_advice_request: bool


def parse_message(text: str, occurred_at: datetime) -> ParseResult:
    extracted: list[ExtractedRecord] = []
    normalized = text.strip()

    weight_match = WEIGHT_PATTERN.search(normalized)
    if weight_match:
        raw_value = float(weight_match.group("value"))
        unit = weight_match.group("unit").lower()
        weight_kg = raw_value / 2 if unit == "斤" else raw_value
        extracted.append(
            ExtractedRecord(
                record_type="weight",
                summary=f"Weight log {weight_kg:.1f}kg",
                confidence=0.98,
                payload={"logged_at": occurred_at.isoformat(), "weight_kg": round(weight_kg, 2)},
            )
        )

    if any(keyword in normalized for keyword in HUNGER_KEYWORDS):
        extracted.append(
            ExtractedRecord(
                record_type="hunger",
                summary="Hunger signal detected",
                confidence=0.9,
                payload={
                    "logged_at": occurred_at.isoformat(),
                    "signal_type": "hunger",
                    "hunger_level": "high" if "很饿" in normalized or "特别饿" in normalized else "medium",
                    "description": normalized,
                },
            )
        )

    if any(keyword in normalized for keyword in MEAL_KEYWORDS):
        meal_slot = infer_meal_slot(normalized)
        extracted.append(
            ExtractedRecord(
                record_type="food",
                summary=f"Food log for {meal_slot}",
                confidence=0.82,
                payload={
                    "logged_at": occurred_at.isoformat(),
                    "meal_slot": meal_slot,
                    "description": normalized,
                },
            )
        )

    return ParseResult(
        extracted=extracted,
        is_advice_request=any(keyword in normalized for keyword in ADVICE_KEYWORDS),
    )


def infer_meal_slot(text: str) -> str:
    if "早餐" in text:
        return "breakfast"
    if "午餐" in text:
        return "lunch"
    if "晚餐" in text:
        return "dinner"
    if "夜宵" in text:
        return "late_night"
    if "加餐" in text:
        return "snack"
    return "unspecified"
