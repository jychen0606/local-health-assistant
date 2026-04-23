from __future__ import annotations

import json
from pathlib import Path

from local_health_assistant.models import BaselineProfile, BaselineResponse, HealthMarker, ReportRecord
from local_health_assistant.storage import Storage


def import_baseline_json(storage: Storage, path: str) -> BaselineResponse:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    person = payload.get("person") or {}
    body = payload.get("body_metrics") or {}
    lifestyle = payload.get("lifestyle") or {}
    profile = BaselineProfile(
        age=person.get("age"),
        sex=person.get("sex"),
        height_cm=body.get("height_cm"),
        weight_kg=body.get("weight_kg"),
        bmi=body.get("bmi"),
        waist_cm=body.get("waist_cm"),
        hip_cm=body.get("hip_cm"),
        waist_hip_ratio=body.get("waist_hip_ratio"),
        smoking=lifestyle.get("smoking"),
        alcohol=lifestyle.get("alcohol"),
        exercise=lifestyle.get("exercise"),
    )
    storage.save_baseline_profile(profile.model_dump(mode="json"))
    storage.add_baseline_report(
        report_date=str(payload["report_date"]),
        source_type=str(payload["source_type"]),
        source_file=str(payload["source_file"]),
        anonymized=bool(payload.get("anonymized", True)),
    )

    markers = [
        HealthMarker(
            marker_key=str(item["key"]),
            label=str(item["label"]),
            value=str(item["value"]),
            unit=str(item.get("unit", "")),
            severity=str(item.get("severity", "info")),
            observed_on=payload["report_date"],
            source="baseline_report",
        )
        for item in payload.get("abnormal_findings", [])
    ]
    storage.replace_health_markers(
        [item.model_dump(mode="json") for item in markers],
        source="baseline_report",
    )
    return get_baseline(storage)


def get_baseline(storage: Storage) -> BaselineResponse:
    profile = BaselineProfile.model_validate(storage.get_baseline_profile())
    markers = [HealthMarker.model_validate(row_to_marker(item)) for item in storage.list_health_markers()]
    reports = [
        ReportRecord.model_validate(
            {
                "report_date": row["report_date"],
                "source_type": row["source_type"],
                "source_file": row["source_file"],
                "anonymized": bool(row["anonymized"]),
            }
        )
        for row in storage.list_baseline_reports()
    ]
    return BaselineResponse(profile=profile, markers=markers, reports=reports)


def row_to_marker(row: dict[str, object]) -> dict[str, object]:
    return {
        "marker_key": row["marker_key"],
        "label": row["label"],
        "value": row["value_text"],
        "unit": row.get("unit", "") or "",
        "severity": row["severity"],
        "observed_on": row["observed_on"],
        "source": row["source"],
    }
