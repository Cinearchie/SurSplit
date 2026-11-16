"""FFmpeg / FFprobe helpers."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path


class AudioError(RuntimeError):
    """Raised when a file cannot be read or converted."""


def check_ffmpeg() -> None:
    for tool in ("ffmpeg", "ffprobe"):
        if shutil.which(tool) is None:
            raise RuntimeError(
                f"'{tool}' was not found on PATH. Install FFmpeg first "
                "(see README → Prerequisites)."
            )


def _run(cmd: list[str], timeout: int = 900) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=True)
    except subprocess.CalledProcessError as exc:
        tail = (exc.stderr or "").strip().splitlines()[-3:]
        raise AudioError("FFmpeg failed: " + " | ".join(tail)) from exc
    except subprocess.TimeoutExpired as exc:
        raise AudioError("FFmpeg timed out") from exc


def probe(path: Path) -> dict:
    """Return duration (s) and whether the file has an audio stream."""
    result = _run([
        "ffprobe", "-v", "error", "-print_format", "json",
        "-show_format", "-show_streams", str(path),
    ], timeout=60)
    info = json.loads(result.stdout or "{}")
    streams = info.get("streams", [])
    has_audio = any(s.get("codec_type") == "audio" for s in streams)
    has_cover = any(
        s.get("codec_type") == "video" and s.get("disposition", {}).get("attached_pic") == 1
        for s in streams
    )
    try:
        duration = float(info.get("format", {}).get("duration", 0) or 0)
    except (TypeError, ValueError):
        duration = 0.0
    tags = {k.lower(): v for k, v in info.get("format", {}).get("tags", {}).items()}
    return {
        "duration": duration,
        "has_audio": has_audio,
        "has_cover": has_cover,
        "title": tags.get("title", ""),
    }


def to_wav(src: Path, dst: Path) -> Path:
    """Decode any audio to 44.1 kHz stereo 32-bit float WAV (lossless working copy)."""
    _run([
        "ffmpeg", "-y", "-loglevel", "error", "-i", str(src),
        "-map", "0:a:0", "-vn", "-ac", "2", "-ar", "44100",
        "-c:a", "pcm_f32le", str(dst),
    ])
    return dst


def extract_cover(src: Path, dst: Path) -> Path | None:
    """Pull embedded cover art out of a file (best effort)."""
    try:
        _run([
            "ffmpeg", "-y", "-loglevel", "error", "-i", str(src),
            "-map", "0:v:0", "-frames:v", "1", str(dst),
        ], timeout=60)
        return dst if dst.exists() and dst.stat().st_size > 0 else None
    except AudioError:
        return None


def image_to_cover(src: Path, dst: Path) -> Path | None:
    """Convert a thumbnail (webp/png/jpg) into a centred square JPEG cover."""
    try:
        _run([
            "ffmpeg", "-y", "-loglevel", "error", "-i", str(src),
            "-vf", "crop='min(iw,ih)':'min(iw,ih)',scale=600:600",
            "-frames:v", "1", "-q:v", "2", str(dst),
        ], timeout=60)
        return dst if dst.exists() and dst.stat().st_size > 0 else None
    except AudioError:
        return None


def export(wav: Path, dst: Path, fmt: str, title: str, cover: Path | None,
           mp3_bitrate: str = "320k") -> Path:
    """Export the separated WAV as a high-quality MP3 or 24-bit FLAC."""
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav)]
    if cover:
        cmd += ["-i", str(cover), "-map", "0:a", "-map", "1:v",
                "-c:v", "mjpeg" if fmt == "mp3" else "copy",
                "-disposition:v", "attached_pic",
                "-metadata:s:v", "title=Album cover", "-metadata:s:v", "comment=Cover (front)"]
    else:
        cmd += ["-map", "0:a"]

    if fmt == "mp3":
        cmd += ["-c:a", "libmp3lame", "-b:a", mp3_bitrate, "-id3v2_version", "3"]
    elif fmt == "flac":
        cmd += ["-c:a", "flac", "-sample_fmt", "s32", "-bits_per_raw_sample", "24"]
    else:
        raise ValueError(f"Unsupported format: {fmt}")

    cmd += ["-metadata", f"title={title}", str(dst)]
    _run(cmd)
    return dst
