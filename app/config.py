"""Application settings, read from environment variables (or a .env file)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    value = os.getenv(name)
    try:
        return int(value) if value not in (None, "") else default
    except ValueError:
        return default


def _path(name: str, default: Path) -> Path:
    value = os.getenv(name)
    path = Path(value).expanduser() if value else default
    if not path.is_absolute():
        path = BASE_DIR / path
    return path


# Separation models users can choose from. Keys are what the UI sends.
# "hq" is exactly the model used for the original instrumental.
MODELS: dict[str, dict[str, str]] = {
    "hq": {
        "file": "UVR-MDX-NET-Inst_HQ_4.onnx",
        "label": "High quality (MDX-Net Inst HQ 4)",
        "note": "Great quality. Takes about a minute per minute of audio on a normal CPU.",
    },
    "best": {
        "file": "model_bs_roformer_ep_317_sdr_12.9755.ckpt",
        "label": "Best quality (BS-RoFormer)",
        "note": "Cleanest result, but very slow without a GPU.",
    },
}


@dataclass
class Settings:
    app_name: str = "SurSplit"
    host: str = field(default_factory=lambda: os.getenv("HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: _int("PORT", 8000))

    data_dir: Path = field(default_factory=lambda: _path("DATA_DIR", BASE_DIR / "data"))
    model_dir: Path = field(default_factory=lambda: _path("MODEL_DIR", BASE_DIR / "models"))

    # Feature switches
    enable_youtube: bool = field(default_factory=lambda: _bool("ENABLE_YOUTUBE", True))
    enable_upload: bool = field(default_factory=lambda: _bool("ENABLE_UPLOAD", True))
    enabled_models: list[str] = field(
        default_factory=lambda: [
            m.strip() for m in os.getenv("ENABLED_MODELS", "hq,best").split(",")
            if m.strip() in MODELS
        ] or ["hq"]
    )
    default_model: str = field(default_factory=lambda: os.getenv("DEFAULT_MODEL", "hq"))

    # Limits (protect your server when it is public)
    max_duration_seconds: int = field(default_factory=lambda: _int("MAX_DURATION_SECONDS", 600))
    max_upload_mb: int = field(default_factory=lambda: _int("MAX_UPLOAD_MB", 100))
    max_concurrent_jobs: int = field(default_factory=lambda: _int("MAX_CONCURRENT_JOBS", 1))
    max_queue_size: int = field(default_factory=lambda: _int("MAX_QUEUE_SIZE", 20))
    max_active_jobs_per_ip: int = field(default_factory=lambda: _int("MAX_ACTIVE_JOBS_PER_IP", 2))
    job_ttl_minutes: int = field(default_factory=lambda: _int("JOB_TTL_MINUTES", 120))

    # Running behind a reverse proxy (Nginx, Render, Hugging Face...)? Then trust X-Forwarded-For.
    trust_proxy: bool = field(default_factory=lambda: _bool("TRUST_PROXY", False))

    # When YouTube mode is off, the "From YouTube" tab sends people to this site to get
    # the audio themselves (then they upload it). Empty = hide the helper.
    youtube_helper_url: str = field(
        default_factory=lambda: os.getenv("YOUTUBE_HELPER_URL", "https://cobalt.tools/"))

    # Optional password for the whole site (browser login box; any username works).
    # Leave empty for no password.
    app_password: str = field(default_factory=lambda: os.getenv("APP_PASSWORD", ""))

    # Optional: path to a Netscape-format cookies.txt for YouTube
    # (needed on many cloud servers where YouTube asks to "confirm you're not a bot").
    ytdlp_cookies: str = field(default_factory=lambda: os.getenv("YTDLP_COOKIES", ""))

    # Separation tuning (defaults match the original run exactly)
    normalization: float = field(default_factory=lambda: float(os.getenv("NORMALIZATION", "0.9")))
    mp3_bitrate: str = field(default_factory=lambda: os.getenv("MP3_BITRATE", "320k"))

    def __post_init__(self) -> None:
        if self.default_model not in self.enabled_models:
            self.default_model = self.enabled_models[0]
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        self.model_dir.mkdir(parents=True, exist_ok=True)

    @property
    def jobs_dir(self) -> Path:
        return self.data_dir / "jobs"


settings = Settings()
