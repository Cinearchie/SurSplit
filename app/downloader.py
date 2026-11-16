"""YouTube audio download via yt-dlp."""

from __future__ import annotations

import re
import shutil
import tempfile
from pathlib import Path
from typing import Callable

import yt_dlp

YOUTUBE_URL_RE = re.compile(
    r"^(https?://)?((www|m|music)\.)?(youtube\.com|youtu\.be|youtube-nocookie\.com)/\S+$",
    re.IGNORECASE,
)


class DownloadError(RuntimeError):
    """Raised with a user-friendly message when a download fails."""


def is_youtube_url(url: str) -> bool:
    return bool(YOUTUBE_URL_RE.match(url.strip()))


def _friendly(exc: Exception) -> str:
    msg = str(exc)
    low = msg.lower()
    if "confirm you" in low and "bot" in low:
        return ("YouTube blocked this server (\"confirm you're not a bot\"). "
                "The server owner needs to set YTDLP_COOKIES — see README.")
    if "private video" in low:
        return "This video is private."
    if "video unavailable" in low or "not available" in low:
        return "This video is unavailable (removed, region-locked or age-restricted)."
    if "sign in to confirm your age" in low:
        return "This video is age-restricted and needs cookies to download."
    if any(s in low for s in ("unable to connect", "timed out", "connection", "proxy", "name resolution")):
        return "The server couldn't reach YouTube. Check its internet connection and try again."
    if "unsupported url" in low:
        return "That doesn't look like a valid YouTube video link."
    return "Could not download this video: " + msg.replace("ERROR: ", "")[:200]


def _base_opts(cookies: str) -> dict:
    opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "noprogress": True,
        "socket_timeout": 30,
        "retries": 3,
    }
    if cookies and Path(cookies).is_file():
        opts["cookiefile"] = _writable_copy(Path(cookies))
    return opts


def _writable_copy(src: Path) -> str:
    """yt-dlp rewrites its cookie file after every run, but secrets on Cloud Run, Docker and
    Kubernetes are mounted read-only. Work on a private temporary copy instead."""
    dest = Path(tempfile.gettempdir()) / "sursplit-cookies.txt"
    shutil.copyfile(src, dest)
    dest.chmod(0o600)
    return str(dest)


def fetch_info(url: str, cookies: str = "") -> dict:
    """Read video metadata without downloading."""
    try:
        with yt_dlp.YoutubeDL(_base_opts(cookies)) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as exc:  # yt-dlp raises many exception types
        raise DownloadError(_friendly(exc)) from exc
    if info is None:
        raise DownloadError("Could not read this video.")
    if info.get("_type") == "playlist":
        raise DownloadError("Please paste a single video link, not a playlist.")
    if info.get("is_live") or info.get("live_status") in {"is_live", "is_upcoming"}:
        raise DownloadError("Live streams can't be processed.")
    return info


def download_audio(url: str, out_dir: Path, cookies: str = "",
                   on_progress: Callable[[float], None] | None = None) -> tuple[Path, Path | None]:
    """Download the best available audio stream (no re-encoding).

    Returns (audio_path, thumbnail_path_or_None).
    """

    def hook(d: dict) -> None:
        if on_progress and d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            if total:
                on_progress(min(1.0, d.get("downloaded_bytes", 0) / total))

    opts = _base_opts(cookies) | {
        "format": "bestaudio/best",
        "outtmpl": str(out_dir / "source.%(ext)s"),
        "writethumbnail": True,
        "progress_hooks": [hook],
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
    except Exception as exc:
        raise DownloadError(_friendly(exc)) from exc

    audio, thumb = None, None
    for f in out_dir.glob("source.*"):
        if f.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}:
            thumb = f
        elif not f.name.endswith((".part", ".ytdl")):
            audio = f
    if audio is None:
        raise DownloadError("Download finished but no audio file was found.")
    return audio, thumb
