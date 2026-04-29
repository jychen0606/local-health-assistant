from __future__ import annotations

import json
import os
import secrets
import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any


class OuraConfigError(RuntimeError):
    pass


class OuraAPIError(RuntimeError):
    pass


@dataclass(frozen=True)
class OuraProblem:
    status: int | None
    title: str
    detail: str
    error: str | None = None
    error_description: str | None = None


def _ssl_context() -> ssl.SSLContext:
    configured = (os.getenv("LHA_SSL_CERT_FILE", "") or "").strip()
    cafile = Path(configured) if configured else Path("/etc/ssl/cert.pem")
    if cafile.exists():
        return ssl.create_default_context(cafile=str(cafile))
    return ssl.create_default_context()


def _parse_problem(error: Exception) -> dict[str, Any] | None:
    try:
        parsed = json.loads(str(error))
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


@dataclass(frozen=True)
class OuraClient:
    access_token: str | None
    base_url: str = "https://api.ouraring.com"

    def fetch_daily_snapshot(self, target_date: date) -> dict[str, Any]:
        if not self.access_token:
            raise OuraConfigError(
                "Missing Oura access token. Set OURA_ACCESS_TOKEN, OURA_PERSONAL_ACCESS_TOKEN, or OURA_TOKEN."
            )

        start_date = target_date.isoformat()
        # Oura's collection endpoints return records by their `day` field. For
        # single-day syncs, request the same start and end day so we do not
        # accidentally normalize the following day's summary into target_date.
        end_date = target_date.isoformat()
        return {
            "target_date": start_date,
            "daily_sleep": self._get_collection("daily_sleep", start_date, end_date),
            "daily_readiness": self._get_collection("daily_readiness", start_date, end_date),
            "daily_activity": self._get_collection("daily_activity", start_date, end_date),
        }

    def fetch_activity_snapshot(self, target_date: date) -> dict[str, Any]:
        if not self.access_token:
            raise OuraConfigError(
                "Missing Oura access token. Set OURA_ACCESS_TOKEN, OURA_PERSONAL_ACCESS_TOKEN, or OURA_TOKEN."
            )
        start_date = target_date.isoformat()
        end_date = target_date.isoformat()
        warnings: list[dict[str, Any]] = []
        workout: dict[str, Any] = {"data": []}
        try:
            workout = self._get_collection("workout", start_date, end_date)
        except OuraAPIError as e:
            problem = _parse_problem(e)
            if not problem or problem.get("status") != 401:
                raise
            warnings.append(
                {
                    "collection": "workout",
                    "status": 401,
                    "detail": "Token is not authorized for workout scope; daily activity still synced.",
                }
            )
        return {
            "target_date": start_date,
            "daily_activity": self._get_collection("daily_activity", start_date, end_date),
            "workout": workout,
            "warnings": warnings,
        }

    def _get_collection(self, collection: str, start_date: str, end_date: str) -> dict[str, Any]:
        query = urllib.parse.urlencode({"start_date": start_date, "end_date": end_date})
        url = f"{self.base_url}/v2/usercollection/{collection}?{query}"
        req = urllib.request.Request(
            url=url,
            method="GET",
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {self.access_token}",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=45, context=_ssl_context()) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            raise _error_from_http_error(e, f"Oura {collection} request failed") from e
        except urllib.error.URLError as e:
            raise OuraAPIError(f"Oura {collection} request failed: {e}") from e

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as e:
            raise OuraAPIError(f"Oura {collection} returned non-JSON: {raw[:500]}") from e
        if not isinstance(parsed, dict):
            raise OuraAPIError(f"Oura {collection} returned an unexpected payload")
        return parsed


@dataclass(frozen=True)
class OuraOAuthClient:
    client_id: str | None
    client_secret: str | None
    redirect_uri: str | None
    authorize_url: str
    token_url: str

    def build_authorization_url(self, scopes: list[str] | None = None, state: str | None = None) -> tuple[str, str]:
        if not self.client_id or not self.redirect_uri:
            raise OuraConfigError("Missing OURA_CLIENT_ID or OURA_REDIRECT_URI.")
        actual_state = state or secrets.token_urlsafe(24)
        query = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "state": actual_state,
        }
        if scopes:
            query["scope"] = " ".join(scopes)
        return f"{self.authorize_url}?{urllib.parse.urlencode(query)}", actual_state

    def exchange_code(self, code: str) -> dict[str, Any]:
        if not self.client_id or not self.client_secret:
            raise OuraConfigError("Missing OURA_CLIENT_ID or OURA_CLIENT_SECRET.")
        if not self.redirect_uri:
            raise OuraConfigError("Missing OURA_REDIRECT_URI.")
        payload = urllib.parse.urlencode(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.redirect_uri,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            url=self.token_url,
            data=payload,
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        try:
            with urllib.request.urlopen(req, timeout=45, context=_ssl_context()) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            raise _error_from_http_error(e, "Oura token exchange failed") from e
        except urllib.error.URLError as e:
            raise OuraAPIError(f"Oura token exchange failed: {e}") from e
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as e:
            raise OuraAPIError(f"Oura token exchange returned non-JSON: {raw[:500]}") from e
        if not isinstance(parsed, dict):
            raise OuraAPIError("Oura token exchange returned an unexpected payload")
        return parsed

    def refresh_access_token(self, refresh_token: str) -> dict[str, Any]:
        if not self.client_id or not self.client_secret:
            raise OuraConfigError("Missing OURA_CLIENT_ID or OURA_CLIENT_SECRET.")
        payload = urllib.parse.urlencode(
            {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            url=self.token_url,
            data=payload,
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        try:
            with urllib.request.urlopen(req, timeout=45, context=_ssl_context()) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            raise _error_from_http_error(e, "Oura refresh token exchange failed") from e
        except urllib.error.URLError as e:
            raise OuraAPIError(f"Oura refresh token exchange failed: {e}") from e
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as e:
            raise OuraAPIError(f"Oura refresh token exchange returned non-JSON: {raw[:500]}") from e
        if not isinstance(parsed, dict):
            raise OuraAPIError("Oura refresh token exchange returned an unexpected payload")
        return parsed


def compute_expires_at(expires_in: Any) -> str | None:
    if expires_in is None:
        return None
    try:
        seconds = int(expires_in)
    except (TypeError, ValueError):
        return None
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()


def is_token_expired(expires_at: str | None, skew_seconds: int = 60) -> bool:
    if not expires_at:
        return False
    try:
        parsed = datetime.fromisoformat(expires_at)
    except ValueError:
        return False
    return parsed <= datetime.now(timezone.utc) + timedelta(seconds=skew_seconds)


def normalize_daily_metrics(snapshot: dict[str, Any], target_date: date, snapshot_path: str) -> dict[str, Any]:
    sleep = _first_for_day(snapshot.get("daily_sleep"), target_date)
    readiness = _first_for_day(snapshot.get("daily_readiness"), target_date)
    activity = _first_for_day(snapshot.get("daily_activity"), target_date)

    sleep_contributors = _dict_value(sleep, "contributors")
    readiness_contributors = _dict_value(readiness, "contributors")

    return {
        "date": target_date.isoformat(),
        "sleep_score": _int_or_none(sleep.get("score")),
        "total_sleep_minutes": _duration_minutes(
            sleep.get("total_sleep_duration")
            or sleep.get("total_sleep_time")
            or sleep.get("sleep_duration")
        ),
        "sleep_efficiency": _float_or_none(
            sleep.get("efficiency") or sleep_contributors.get("efficiency")
        ),
        "readiness_score": _int_or_none(readiness.get("score")),
        "resting_heart_rate": _float_or_none(
            readiness.get("resting_heart_rate")
            or readiness.get("lowest_resting_heart_rate")
        ),
        "hrv_balance": _float_or_none(
            readiness.get("hrv_balance")
            or sleep.get("average_hrv")
        ),
        "activity_score": _int_or_none(activity.get("score")),
        "active_calories": _int_or_none(activity.get("active_calories")),
        "steps": _int_or_none(activity.get("steps")),
        "sleep_contributors": sleep_contributors or None,
        "readiness_contributors": readiness_contributors or None,
        "activity_contributors": _dict_value(activity, "contributors") or None,
        "snapshot_path": snapshot_path,
    }


def normalize_activity_context(snapshot: dict[str, Any], target_date: date, snapshot_path: str) -> dict[str, Any]:
    activity = _first_for_day(snapshot.get("daily_activity"), target_date)
    workouts = _rows_for_day(snapshot.get("workout"), target_date)
    normalized_workouts: list[dict[str, Any]] = []
    for row in workouts:
        workout_key = str(
            row.get("id")
            or row.get("workout_id")
            or row.get("start_datetime")
            or row.get("day")
            or secrets.token_hex(8)
        )
        normalized_workouts.append(
            {
                "workout_key": workout_key,
                "day": str(row.get("day") or target_date.isoformat()),
                "start_datetime": row.get("start_datetime"),
                "end_datetime": row.get("end_datetime"),
                "sport": row.get("sport") or row.get("type"),
                "active_calories": _int_or_none(row.get("active_calories") or row.get("calories")),
                "payload": row,
            }
        )
    return {
        "date": target_date.isoformat(),
        "activity_score": _int_or_none(activity.get("score")),
        "active_calories": _int_or_none(activity.get("active_calories")),
        "steps": _int_or_none(activity.get("steps")),
        "activity_contributors": _dict_value(activity, "contributors") or None,
        "snapshot_path": snapshot_path,
        "workouts": normalized_workouts,
    }


def _first_for_day(payload: Any, target_date: date) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    rows = payload.get("data")
    if not isinstance(rows, list):
        return {}
    target = target_date.isoformat()
    for row in rows:
        if isinstance(row, dict) and row.get("day") == target:
            return row
    return {}


def _rows_for_day(payload: Any, target_date: date) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    rows = payload.get("data")
    if not isinstance(rows, list):
        return []
    target = target_date.isoformat()
    matched = [row for row in rows if isinstance(row, dict) and row.get("day") == target]
    return matched


def _dict_value(row: dict[str, Any], key: str) -> dict[str, Any]:
    value = row.get(key)
    return value if isinstance(value, dict) else {}


def _duration_minutes(value: Any) -> int | None:
    number = _float_or_none(value)
    if number is None:
        return None
    if number > 24 * 60:
        return int(round(number / 60))
    return int(round(number))


def _int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _error_from_http_error(error: urllib.error.HTTPError, prefix: str) -> OuraAPIError:
    raw = error.read().decode("utf-8", errors="replace").strip()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return OuraAPIError(f"{prefix} with HTTP {error.code}: {raw}")
    if isinstance(payload, dict):
        problem = OuraProblem(
            status=payload.get("status") if isinstance(payload.get("status"), int) else error.code,
            title=str(payload.get("title") or prefix),
            detail=str(payload.get("detail") or raw),
            error=str(payload.get("error")) if payload.get("error") is not None else None,
            error_description=(
                str(payload.get("error_description")) if payload.get("error_description") is not None else None
            ),
        )
        return OuraAPIError(json.dumps(problem.__dict__, ensure_ascii=False))
    return OuraAPIError(f"{prefix} with HTTP {error.code}: {raw}")
