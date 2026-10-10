"""Central settings: paths, AI model names and evidence thresholds."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent


@dataclass(frozen=True)
class Settings:
    """Application settings, read once from the environment at import time."""

    data_dir: Path
    customer_model: str = "claude-sonnet-5-5"
    report_model: str = "claude-opus-5-5"
    # A typed-fallback customer reply is under 45 words; the headroom covers the
    # model's thinking, which shares this budget.
    customer_max_tokens: int = 1024
    report_max_tokens: int = 8192
    max_upload_bytes: int = 80 * 1024 * 1024
    upload_chunk_bytes: int = 1024 * 1024

    @property
    def media_dir(self) -> Path:
        return self.data_dir / "media"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "shiftready.sqlite3"


def load_settings() -> Settings:
    return Settings(data_dir=Path(os.environ.get("SHIFTREADY_DATA_DIR", ROOT / "data")))


settings = load_settings()
