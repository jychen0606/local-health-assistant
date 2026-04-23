from __future__ import annotations

import json
import secrets
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any


class OuraConfigError(RuntimeError):
    pass


class OuraAPIError(RuntimeError):
    pass


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
        # Oura v2 collection endpoints accept date ranges. Using the next day as
        # the end keeps the request robust if the API treats end_date as exclusive.
        end_date = (target_date + timedelta(days=1)).isoformat()
        return {
            "target_date": start_date,
            "daily_sleep": self._get_collection("daily_sleep", start_date, end_date),
            "daily_readiness": self._get_collection("daily_readiness", start_date, end_date),
            "daily_activity": self._get_collection("daily_activity", start_date, end_date),
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
            with urllib.request.urlopen(req, timeout=45) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace").strip()
            raise OuraAPIError(f"Oura {collection} request failed with HTTP {e.code}: {detail}") from e
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
            with urllib.request.urlopen(req, timeout=45) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace").strip()
            raise OuraAPIError(f"Oura token exchange failed with HTTP {e.code}: {detail}") from e
        except urllib.error.URLError as e:
            raise OuraAPIError(f"Oura token exchange failed: {e}") from e
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as e:
            raise OuraAPIError(f"Oura token exchange returned non-JSON: {raw[:500]}") from e
        if not isinstance(parsed, dict):
            raise OuraAPIError("Oura token exchange returned an unexpected payload")
        return parsed


def compute_expires_at(expires_in: Any) -> str | None:
    if expires_in is None:
        return None
    try:
        seconds = int(expires_in)
    except (TypeError, ValueError):
        return None
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()


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
            or sleep.get("lowest_heart_rate")
        ),
        "hrv_balance": _float_or_none(
            readiness.get("hrv_balance")
            or readiness_contributors.get("hrv_balance")
            or sleep.get("average_hrv")
        ),
        "activity_score": _int_or_none(activity.get("score")),
        "active_calories": _int_or_none(activity.get("active_calories")),
        "steps": _int_or_none(activity.get("steps")),
        "snapshot_path": snapshot_path,
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
    for row in rows:
        if isinstance(row, dict):
            return row
    return {}


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
