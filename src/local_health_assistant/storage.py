from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

import yaml

from local_health_assistant.config import AppPaths, ensure_app_dirs
from local_health_assistant.models import AdviceRequest, GoalPayload, ReviewResponse


SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS conversation_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source_channel TEXT NOT NULL,
        source_user_id TEXT NOT NULL,
        source_chat_id TEXT NOT NULL,
        source_message_id TEXT,
        session_key TEXT NOT NULL,
        occurred_at TEXT NOT NULL,
        text TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS food_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        conversation_event_id INTEGER NOT NULL,
        logged_at TEXT NOT NULL,
        meal_slot TEXT NOT NULL,
        description TEXT NOT NULL,
        confidence REAL NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS hunger_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        conversation_event_id INTEGER NOT NULL,
        logged_at TEXT NOT NULL,
        hunger_level TEXT,
        signal_type TEXT NOT NULL,
        description TEXT NOT NULL,
        confidence REAL NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS weight_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        conversation_event_id INTEGER NOT NULL,
        logged_at TEXT NOT NULL,
        weight_kg REAL NOT NULL,
        confidence REAL NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS oura_daily_metrics (
        date TEXT PRIMARY KEY,
        sleep_score INTEGER,
        total_sleep_minutes INTEGER,
        sleep_efficiency REAL,
        readiness_score INTEGER,
        resting_heart_rate REAL,
        hrv_balance REAL,
        activity_score INTEGER,
        active_calories INTEGER,
        steps INTEGER,
        sleep_contributors_json TEXT,
        readiness_contributors_json TEXT,
        activity_contributors_json TEXT,
        snapshot_path TEXT,
        synced_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS oura_sync_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        target_date TEXT NOT NULL,
        trigger_type TEXT NOT NULL,
        status TEXT NOT NULL,
        error_message TEXT,
        started_at TEXT NOT NULL,
        finished_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS goals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        effective_from TEXT NOT NULL,
        goal_payload_json TEXT NOT NULL,
        source_version TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS advice_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        conversation_event_id INTEGER,
        requested_at TEXT NOT NULL,
        question_text TEXT NOT NULL,
        context_payload_json TEXT NOT NULL,
        advice_text TEXT NOT NULL,
        expected_behavior TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS advice_outcomes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        advice_record_id INTEGER NOT NULL,
        evaluation_window_end TEXT NOT NULL,
        outcome_status TEXT NOT NULL,
        outcome_note TEXT,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS daily_reviews (
        date TEXT PRIMARY KEY,
        review_text TEXT NOT NULL,
        markdown_path TEXT NOT NULL,
        key_issue TEXT NOT NULL,
        recommended_adjustment TEXT NOT NULL,
        realism_note TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS daily_features (
        date TEXT PRIMARY KEY,
        feature_payload_json TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS hypothesis_scores (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT NOT NULL,
        hypothesis_key TEXT NOT NULL,
        score REAL NOT NULL,
        label TEXT NOT NULL,
        evidence_json TEXT NOT NULL,
        recommendation TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS oauth_states (
        state TEXT PRIMARY KEY,
        provider TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS oauth_tokens (
        provider TEXT PRIMARY KEY,
        access_token TEXT NOT NULL,
        refresh_token TEXT,
        token_type TEXT,
        scope TEXT,
        expires_at TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS baseline_profile (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        payload_json TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS baseline_reports (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        report_date TEXT NOT NULL,
        source_type TEXT NOT NULL,
        source_file TEXT NOT NULL,
        anonymized INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS health_markers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        marker_key TEXT NOT NULL,
        label TEXT NOT NULL,
        value_text TEXT NOT NULL,
        unit TEXT,
        severity TEXT NOT NULL,
        observed_on TEXT NOT NULL,
        source TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
]


class Storage:
    def __init__(self, paths: AppPaths):
        self.paths = paths
        ensure_app_dirs(paths)
        self._initialize()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.paths.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _initialize(self) -> None:
        with self.connect() as conn:
            for statement in SCHEMA_STATEMENTS:
                conn.execute(statement)
            conn.commit()
        self.load_goals(snapshot_if_missing=True)

    def load_goals(self, snapshot_if_missing: bool = False) -> GoalPayload:
        payload = yaml.safe_load(self.paths.goals_path.read_text(encoding="utf-8")) or {}
        goals = GoalPayload.model_validate(payload)
        if snapshot_if_missing and not self._has_goal_snapshots():
            self.save_goals(goals, source_version="bootstrap")
        return goals

    def save_goals(self, goals: GoalPayload, source_version: str = "api") -> GoalPayload:
        serialized_yaml = yaml.safe_dump(
            goals.model_dump(mode="json"),
            sort_keys=False,
            allow_unicode=False,
        )
        self.paths.goals_path.write_text(serialized_yaml, encoding="utf-8")
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO goals (effective_from, goal_payload_json, source_version, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    now,
                    json.dumps(goals.model_dump(mode="json"), ensure_ascii=False),
                    source_version,
                    now,
                ),
            )
            conn.commit()
        return goals

    def create_conversation_event(self, payload: dict[str, Any]) -> int:
        now = utc_now()
        with self.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO conversation_events (
                    source_channel, source_user_id, source_chat_id, source_message_id,
                    session_key, occurred_at, text, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload["source_channel"],
                    payload["source_user_id"],
                    payload["source_chat_id"],
                    payload.get("source_message_id"),
                    payload["session_key"],
                    payload["occurred_at"],
                    payload["text"],
                    now,
                ),
            )
            conn.commit()
            return int(cursor.lastrowid)

    def save_food_log(self, conversation_event_id: int, extracted: dict[str, Any], confidence: float) -> None:
        self._insert_simple(
            """
            INSERT INTO food_logs (conversation_event_id, logged_at, meal_slot, description, confidence, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                conversation_event_id,
                extracted["logged_at"],
                extracted["meal_slot"],
                extracted["description"],
                confidence,
                utc_now(),
            ),
        )

    def save_hunger_log(self, conversation_event_id: int, extracted: dict[str, Any], confidence: float) -> None:
        self._insert_simple(
            """
            INSERT INTO hunger_logs (conversation_event_id, logged_at, hunger_level, signal_type, description, confidence, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                conversation_event_id,
                extracted["logged_at"],
                extracted.get("hunger_level"),
                extracted["signal_type"],
                extracted["description"],
                confidence,
                utc_now(),
            ),
        )

    def save_weight_log(self, conversation_event_id: int, extracted: dict[str, Any], confidence: float) -> None:
        self._insert_simple(
            """
            INSERT INTO weight_logs (conversation_event_id, logged_at, weight_kg, confidence, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                conversation_event_id,
                extracted["logged_at"],
                extracted["weight_kg"],
                confidence,
                utc_now(),
            ),
        )

    def start_oura_sync(self, target_date: date, trigger_type: str) -> int:
        with self.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO oura_sync_runs (target_date, trigger_type, status, started_at)
                VALUES (?, ?, ?, ?)
                """,
                (target_date.isoformat(), trigger_type, "started", utc_now()),
            )
            conn.commit()
            return int(cursor.lastrowid)

    def finish_oura_sync(self, run_id: int, status: str, error_message: str | None = None) -> None:
        self._insert_simple(
            """
            UPDATE oura_sync_runs
            SET status = ?, error_message = ?, finished_at = ?
            WHERE id = ?
            """,
            (status, error_message, utc_now(), run_id),
        )

    def save_oura_snapshot(self, target_date: date, snapshot: dict[str, Any]) -> Path:
        path = self.paths.snapshots_dir / f"{target_date.isoformat()}.json"
        path.write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return path

    def upsert_oura_daily_metrics(self, metrics: dict[str, Any]) -> None:
        self._insert_simple(
            """
            INSERT INTO oura_daily_metrics (
                date, sleep_score, total_sleep_minutes, sleep_efficiency,
                readiness_score, resting_heart_rate, hrv_balance,
                activity_score, active_calories, steps,
                sleep_contributors_json, readiness_contributors_json, activity_contributors_json,
                snapshot_path, synced_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(date) DO UPDATE SET
                sleep_score = excluded.sleep_score,
                total_sleep_minutes = excluded.total_sleep_minutes,
                sleep_efficiency = excluded.sleep_efficiency,
                readiness_score = excluded.readiness_score,
                resting_heart_rate = excluded.resting_heart_rate,
                hrv_balance = excluded.hrv_balance,
                activity_score = excluded.activity_score,
                active_calories = excluded.active_calories,
                steps = excluded.steps,
                sleep_contributors_json = excluded.sleep_contributors_json,
                readiness_contributors_json = excluded.readiness_contributors_json,
                activity_contributors_json = excluded.activity_contributors_json,
                snapshot_path = excluded.snapshot_path,
                synced_at = excluded.synced_at
            """,
            (
                metrics["date"],
                metrics.get("sleep_score"),
                metrics.get("total_sleep_minutes"),
                metrics.get("sleep_efficiency"),
                metrics.get("readiness_score"),
                metrics.get("resting_heart_rate"),
                metrics.get("hrv_balance"),
                metrics.get("activity_score"),
                metrics.get("active_calories"),
                metrics.get("steps"),
                _json_or_none(metrics.get("sleep_contributors")),
                _json_or_none(metrics.get("readiness_contributors")),
                _json_or_none(metrics.get("activity_contributors")),
                metrics.get("snapshot_path"),
                utc_now(),
            ),
        )

    def get_oura_daily_metrics(self, target_date: date) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM oura_daily_metrics
                WHERE date = ?
                """,
                (target_date.isoformat(),),
            ).fetchone()
        return dict(row) if row else None

    def record_advice(self, conversation_event_id: int | None, request: AdviceRequest, advice_text: str, expected_behavior: str, context_payload: dict[str, Any]) -> int:
        with self.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO advice_records (
                    conversation_event_id, requested_at, question_text, context_payload_json,
                    advice_text, expected_behavior, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    conversation_event_id,
                    (request.requested_at or datetime.now(timezone.utc)).isoformat(),
                    request.question_text,
                    json.dumps(context_payload, ensure_ascii=False),
                    advice_text,
                    expected_behavior,
                    utc_now(),
                ),
            )
            conn.commit()
            return int(cursor.lastrowid)

    def list_recent_metrics(self, days: int = 3) -> list[dict[str, Any]]:
        start = (date.today() - timedelta(days=days)).isoformat()
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM oura_daily_metrics
                WHERE date >= ?
                ORDER BY date DESC
                """,
                (start,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_food_logs_for_date(self, target_date: date) -> list[dict[str, Any]]:
        prefix = target_date.isoformat()
        return self._query_many(
            """
            SELECT * FROM food_logs
            WHERE logged_at LIKE ?
            ORDER BY logged_at ASC
            """,
            (f"{prefix}%",),
        )

    def list_hunger_logs_for_window(self, days: int = 3) -> list[dict[str, Any]]:
        start = (date.today() - timedelta(days=days)).isoformat()
        return self._query_many(
            """
            SELECT * FROM hunger_logs
            WHERE logged_at >= ?
            ORDER BY logged_at DESC
            """,
            (start,),
        )

    def list_hunger_logs_for_date(self, target_date: date) -> list[dict[str, Any]]:
        prefix = target_date.isoformat()
        return self._query_many(
            """
            SELECT * FROM hunger_logs
            WHERE logged_at LIKE ?
            ORDER BY logged_at ASC
            """,
            (f"{prefix}%",),
        )

    def latest_weight(self) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM weight_logs
                ORDER BY logged_at DESC
                LIMIT 1
                """
            ).fetchone()
        return dict(row) if row else None

    def save_review(self, target_date: date, review_text: str, key_issue: str, recommended_adjustment: str, realism_note: str) -> ReviewResponse:
        markdown_path = self.paths.reviews_dir / f"{target_date.isoformat()}.md"
        markdown_path.write_text(review_text + "\n", encoding="utf-8")
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO daily_reviews (date, review_text, markdown_path, key_issue, recommended_adjustment, realism_note, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(date) DO UPDATE SET
                    review_text = excluded.review_text,
                    markdown_path = excluded.markdown_path,
                    key_issue = excluded.key_issue,
                    recommended_adjustment = excluded.recommended_adjustment,
                    realism_note = excluded.realism_note,
                    created_at = excluded.created_at
                """,
                (
                    target_date.isoformat(),
                    review_text,
                    str(markdown_path),
                    key_issue,
                    recommended_adjustment,
                    realism_note,
                    now,
                ),
            )
            conn.commit()
        return ReviewResponse(
            date=target_date,
            review_text=review_text,
            key_issue=key_issue,
            recommended_adjustment=recommended_adjustment,
            realism_note=realism_note,
            markdown_path=str(markdown_path),
        )

    def get_review(self, target_date: date) -> ReviewResponse | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM daily_reviews
                WHERE date = ?
                """,
                (target_date.isoformat(),),
            ).fetchone()
        if not row:
            return None
        return ReviewResponse(
            date=target_date,
            review_text=row["review_text"],
            key_issue=row["key_issue"],
            recommended_adjustment=row["recommended_adjustment"],
            realism_note=row["realism_note"],
            markdown_path=row["markdown_path"],
        )

    def save_daily_insights(self, target_date: date, features: dict[str, Any], hypotheses: list[dict[str, Any]]) -> None:
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO daily_features (date, feature_payload_json, created_at)
                VALUES (?, ?, ?)
                ON CONFLICT(date) DO UPDATE SET
                    feature_payload_json = excluded.feature_payload_json,
                    created_at = excluded.created_at
                """,
                (target_date.isoformat(), json.dumps(features, ensure_ascii=False), now),
            )
            conn.execute("DELETE FROM hypothesis_scores WHERE date = ?", (target_date.isoformat(),))
            for item in hypotheses:
                conn.execute(
                    """
                    INSERT INTO hypothesis_scores (
                        date, hypothesis_key, score, label, evidence_json, recommendation, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        target_date.isoformat(),
                        item["hypothesis_key"],
                        item["score"],
                        item["label"],
                        json.dumps(item["evidence"], ensure_ascii=False),
                        item["recommendation"],
                        now,
                    ),
                )
            conn.commit()

    def get_daily_insights(self, target_date: date) -> dict[str, Any] | None:
        with self.connect() as conn:
            feature_row = conn.execute(
                """
                SELECT * FROM daily_features
                WHERE date = ?
                """,
                (target_date.isoformat(),),
            ).fetchone()
            if not feature_row:
                return None
            score_rows = conn.execute(
                """
                SELECT * FROM hypothesis_scores
                WHERE date = ?
                ORDER BY score DESC
                """,
                (target_date.isoformat(),),
            ).fetchall()
        return {
            "date": target_date,
            "features": json.loads(feature_row["feature_payload_json"]),
            "hypotheses": [
                {
                    "hypothesis_key": row["hypothesis_key"],
                    "score": row["score"],
                    "label": row["label"],
                    "evidence": json.loads(row["evidence_json"]),
                    "recommendation": row["recommendation"],
                }
                for row in score_rows
            ],
        }

    def save_oauth_state(self, provider: str, state: str) -> None:
        self._insert_simple(
            """
            INSERT INTO oauth_states (state, provider, created_at)
            VALUES (?, ?, ?)
            ON CONFLICT(state) DO UPDATE SET
                provider = excluded.provider,
                created_at = excluded.created_at
            """,
            (state, provider, utc_now()),
        )

    def consume_oauth_state(self, provider: str, state: str) -> bool:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT state FROM oauth_states
                WHERE state = ? AND provider = ?
                """,
                (state, provider),
            ).fetchone()
            if not row:
                return False
            conn.execute(
                """
                DELETE FROM oauth_states
                WHERE state = ? AND provider = ?
                """,
                (state, provider),
            )
            conn.commit()
        return True

    def save_oauth_token(
        self,
        provider: str,
        access_token: str,
        refresh_token: str | None,
        token_type: str | None,
        scope: str | None,
        expires_at: str | None,
    ) -> None:
        now = utc_now()
        self._insert_simple(
            """
            INSERT INTO oauth_tokens (
                provider, access_token, refresh_token, token_type, scope, expires_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(provider) DO UPDATE SET
                access_token = excluded.access_token,
                refresh_token = excluded.refresh_token,
                token_type = excluded.token_type,
                scope = excluded.scope,
                expires_at = excluded.expires_at,
                updated_at = excluded.updated_at
            """,
            (provider, access_token, refresh_token, token_type, scope, expires_at, now, now),
        )

    def get_oauth_token(self, provider: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM oauth_tokens
                WHERE provider = ?
                """,
                (provider,),
            ).fetchone()
        return dict(row) if row else None

    def save_baseline_profile(self, profile: dict[str, Any]) -> None:
        self._insert_simple(
            """
            INSERT INTO baseline_profile (id, payload_json, updated_at)
            VALUES (1, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                payload_json = excluded.payload_json,
                updated_at = excluded.updated_at
            """,
            (json.dumps(profile, ensure_ascii=False), utc_now()),
        )

    def get_baseline_profile(self) -> dict[str, Any]:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT payload_json FROM baseline_profile
                WHERE id = 1
                """
            ).fetchone()
        if not row:
            return {}
        return json.loads(row["payload_json"])

    def add_baseline_report(self, report_date: str, source_type: str, source_file: str, anonymized: bool) -> None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT id FROM baseline_reports
                WHERE report_date = ? AND source_file = ?
                """,
                (report_date, source_file),
            ).fetchone()
            if row:
                return
            conn.execute(
                """
                INSERT INTO baseline_reports (report_date, source_type, source_file, anonymized, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (report_date, source_type, source_file, 1 if anonymized else 0, utc_now()),
            )
            conn.commit()

    def replace_health_markers(self, markers: list[dict[str, Any]], source: str) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM health_markers WHERE source = ?", (source,))
            for marker in markers:
                conn.execute(
                    """
                    INSERT INTO health_markers (
                        marker_key, label, value_text, unit, severity, observed_on, source, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        marker["marker_key"],
                        marker["label"],
                        marker["value"],
                        marker.get("unit", ""),
                        marker.get("severity", "info"),
                        marker["observed_on"],
                        source,
                        utc_now(),
                    ),
                )
            conn.commit()

    def list_health_markers(self) -> list[dict[str, Any]]:
        return self._query_many(
            """
            SELECT marker_key, label, value_text, unit, severity, observed_on, source
            FROM health_markers
            ORDER BY observed_on DESC, id ASC
            """,
            (),
        )

    def list_baseline_reports(self) -> list[dict[str, Any]]:
        return self._query_many(
            """
            SELECT report_date, source_type, source_file, anonymized
            FROM baseline_reports
            ORDER BY report_date DESC, id DESC
            """,
            (),
        )

    def _has_goal_snapshots(self) -> bool:
        with self.connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS count FROM goals").fetchone()
        return bool(row["count"])

    def _insert_simple(self, sql: str, params: tuple[Any, ...]) -> None:
        with self.connect() as conn:
            conn.execute(sql, params)
            conn.commit()

    def _query_many(self, sql: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_or_none(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False)
