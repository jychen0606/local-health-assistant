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
            app_paths=paths,
        )


def ensure_app_dirs(paths: AppPaths) -> None:
    paths.data_root.mkdir(parents=True, exist_ok=True)
    paths.reviews_dir.mkdir(parents=True, exist_ok=True)
    paths.snapshots_dir.mkdir(parents=True, exist_ok=True)
    paths.goals_dir.mkdir(parents=True, exist_ok=True)
    if not paths.goals_path.exists():
        paths.goals_path.write_text(DEFAULT_GOALS_YAML, encoding="utf-8")
