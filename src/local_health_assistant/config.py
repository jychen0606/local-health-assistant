from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


DEFAULT_GOALS_YAML = """\
current_phase: fat_loss
target_weight_range_kg:
  min: 70.0
  max: 72.0
protein_min_g: 140
calorie_range:
  min: 1900
  max: 2200
weekly_training_target: 4
late_night_snack_limit: 2
"""


@dataclass(frozen=True)
class AppPaths:
    repo_root: Path
    data_root: Path
    db_path: Path
    reviews_dir: Path
    snapshots_dir: Path
    goals_dir: Path
    goals_path: Path


@dataclass(frozen=True)
class Settings:
    app_name: str
    app_env: str
    oura_access_token: str | None
    oura_api_base_url: str
    oura_client_id: str | None
    oura_client_secret: str | None
    oura_redirect_uri: str | None
    oura_authorize_url: str
    oura_token_url: str
    app_paths: AppPaths

    @classmethod
    def load(cls) -> "Settings":
        repo_root = Path(__file__).resolve().parents[2]
        data_root = Path(os.getenv("LHA_DATA_DIR", repo_root / "data" / "health")).expanduser()
        paths = AppPaths(
            repo_root=repo_root,
            data_root=data_root,
            db_path=data_root / "health.db",
            reviews_dir=data_root / "daily_reviews",
            snapshots_dir=data_root / "oura_snapshots",
            goals_dir=data_root / "goals",
            goals_path=data_root / "goals" / "current.yaml",
        )
        return cls(
            app_name="local-health-assistant",
            app_env=os.getenv("LHA_ENV", "development").strip() or "development",
            oura_access_token=_read_oura_token(),
            oura_api_base_url=os.getenv("OURA_API_BASE_URL", "https://api.ouraring.com").rstrip("/"),
            oura_client_id=_read_env("OURA_CLIENT_ID"),
            oura_client_secret=_read_env("OURA_CLIENT_SECRET"),
            oura_redirect_uri=_read_env("OURA_REDIRECT_URI"),
            oura_authorize_url=os.getenv("OURA_AUTHORIZE_URL", "https://cloud.ouraring.com/oauth/authorize").rstrip("/"),
            oura_token_url=os.getenv("OURA_TOKEN_URL", "https://api.ouraring.com/oauth/token").rstrip("/"),
            app_paths=paths,
        )


def ensure_app_dirs(paths: AppPaths) -> None:
    paths.data_root.mkdir(parents=True, exist_ok=True)
    paths.reviews_dir.mkdir(parents=True, exist_ok=True)
    paths.snapshots_dir.mkdir(parents=True, exist_ok=True)
    paths.goals_dir.mkdir(parents=True, exist_ok=True)
    if not paths.goals_path.exists():
        paths.goals_path.write_text(DEFAULT_GOALS_YAML, encoding="utf-8")


def _read_oura_token() -> str | None:
    for name in ("OURA_ACCESS_TOKEN", "OURA_PERSONAL_ACCESS_TOKEN", "OURA_TOKEN"):
        value = _read_env(name)
        if value:
            return value
    return None


def _read_env(name: str) -> str | None:
    value = (os.getenv(name, "") or "").strip()
    return value or None
