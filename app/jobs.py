"""In-memory job queue with a worker pool and automatic cleanup."""

from __future__ import annotations

import logging
import re
import shutil
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from . import audio, downloader, separator
from .config import settings

log = logging.getLogger("sursplit.jobs")

# Progress ranges for each stage (0–100 overall)
STAGES = {
    "queued": (0, 0),
    "downloading": (0, 15),
    "preparing": (15, 20),
    "separating": (20, 95),
    "exporting": (95, 100),
    "done": (100, 100),
    "error": (100, 100),
}

STAGE_LABELS = {
    "queued": "Waiting in queue",
    "downloading": "Downloading audio from YouTube",
    "preparing": "Preparing audio",
    "separating": "Removing vocals with AI",
    "exporting": "Exporting MP3 and FLAC",
    "done": "Done",
    "error": "Failed",
}


def safe_filename(name: str, fallback: str = "track") -> str:
    name = re.sub(r"[\\/:*?\"<>|\x00-\x1f]", " ", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    return (name[:120] or fallback)


@dataclass
class Job:
    id: str
    source: str  # "youtube" | "upload"
    model: str
    want_vocals: bool
    client_ip: str
    url: str = ""
    upload_path: Path | None = None
    title: str = ""
    duration: float = 0.0
    stage: str = "queued"
    progress: float = 0.0
    error: str = ""
    files: dict[str, Path] = field(default_factory=dict)
    created: float = field(default_factory=time.time)
    started: float = 0.0
    finished: float = 0.0

    @property
    def dir(self) -> Path:
        return settings.jobs_dir / self.id

    @property
    def active(self) -> bool:
        return self.stage not in {"done", "error"}

    def set_stage(self, stage: str, fraction: float = 0.0) -> None:
        self.stage = stage
        lo, hi = STAGES[stage]
        self.progress = round(lo + (hi - lo) * max(0.0, min(1.0, fraction)), 1)


class JobManager:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(
            max_workers=max(1, settings.max_concurrent_jobs), thread_name_prefix="sursplit-worker"
        )
        self._stop = threading.Event()
        threading.Thread(target=self._cleanup_loop, daemon=True, name="sursplit-cleanup").start()

    # ---------- public API ----------
    def new_job_id(self) -> str:
        return uuid.uuid4().hex

    def check_capacity(self, client_ip: str) -> str | None:
        """Return an error message if this request must be rejected."""
        with self._lock:
            active = [j for j in self._jobs.values() if j.active]
            if len(active) >= settings.max_queue_size:
                return "The server is busy right now. Please try again in a few minutes."
            mine = sum(1 for j in active if j.client_ip == client_ip)
            if mine >= settings.max_active_jobs_per_ip:
                return ("You already have a track processing. "
                        "Please wait for it to finish before starting another.")
        return None

    def submit(self, job: Job) -> Job:
        job.dir.mkdir(parents=True, exist_ok=True)
        with self._lock:
            self._jobs[job.id] = job
        self._pool.submit(self._run, job)
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def queue_position(self, job: Job) -> int:
        with self._lock:
            waiting = sorted(
                (j for j in self._jobs.values() if j.stage == "queued"), key=lambda j: j.created
            )
        for i, j in enumerate(waiting, start=1):
            if j.id == job.id:
                return i
        return 0

    def shutdown(self) -> None:
        self._stop.set()
        self._pool.shutdown(wait=False, cancel_futures=True)

    # ---------- worker ----------
    def _run(self, job: Job) -> None:
        job.started = time.time()
        work = job.dir
        try:
            cover: Path | None = None

            # 1. Get the source audio
            if job.source == "youtube":
                job.set_stage("downloading")
                info = downloader.fetch_info(job.url, settings.ytdlp_cookies)
                job.title = info.get("title") or "YouTube audio"
                job.duration = float(info.get("duration") or 0)
                self._check_duration(job.duration)
                src, thumb = downloader.download_audio(
                    job.url, work, settings.ytdlp_cookies,
                    on_progress=lambda f: job.set_stage("downloading", f),
                )
                if thumb:
                    cover = audio.image_to_cover(thumb, work / "cover.jpg")
            else:
                assert job.upload_path is not None
                src = job.upload_path
                if audio.probe(src)["has_cover"]:
                    cover = audio.extract_cover(src, work / "cover.jpg")

            # 2. Validate & convert to lossless WAV
            job.set_stage("preparing")
            meta = audio.probe(src)
            if not meta["has_audio"]:
                raise audio.AudioError("This file has no audio track.")
            job.duration = meta["duration"] or job.duration
            self._check_duration(job.duration)
            if not job.title:
                job.title = meta["title"] or "Uploaded track"
            wav = audio.to_wav(src, work / "input.wav")
            job.set_stage("preparing", 1)

            # 3. AI separation
            job.set_stage("separating")
            stems = separator.separate(
                wav, work, job.model, settings.model_dir, job.want_vocals,
                normalization=settings.normalization,
                on_progress=lambda f: job.set_stage("separating", f),
            )

            # 4. Export
            job.set_stage("exporting")
            base = safe_filename(job.title)
            outputs: dict[str, Path] = {}
            plan = [("instrumental", "Instrumental")]
            if "vocals" in stems:
                plan.append(("vocals", "Vocals"))
            steps = len(plan) * 2
            n = 0
            for stem, label in plan:
                for fmt in ("mp3", "flac"):
                    dst = work / f"{stem}.{fmt}"
                    audio.export(stems[stem], dst, fmt, f"{job.title} ({label})", cover,
                                 settings.mp3_bitrate)
                    outputs[f"{stem}_{fmt}"] = dst
                    n += 1
                    job.set_stage("exporting", n / steps)
            job.files = outputs
            job.title = base

            # Free disk: drop the big intermediate files
            for f in [wav, *stems.values(), src]:
                try:
                    f.unlink(missing_ok=True)
                except OSError:
                    pass
            for f in work.glob("source.*"):
                f.unlink(missing_ok=True)

            job.set_stage("done")
            log.info("Job %s done in %.0fs", job.id, time.time() - job.started)
        except (downloader.DownloadError, audio.AudioError, separator.SeparationError, ValueError) as exc:
            job.error = str(exc)
            job.set_stage("error")
            log.warning("Job %s failed: %s", job.id, exc)
        except Exception as exc:  # never let a worker die silently
            job.error = "Something went wrong while processing this track."
            job.set_stage("error")
            log.exception("Job %s crashed: %s", job.id, exc)
        finally:
            job.finished = time.time()

    @staticmethod
    def _check_duration(seconds: float) -> None:
        limit = settings.max_duration_seconds
        if limit and seconds and seconds > limit:
            raise ValueError(
                f"This track is {seconds / 60:.1f} minutes long. "
                f"The limit is {limit / 60:.0f} minutes."
            )

    # ---------- cleanup ----------
    def _cleanup_loop(self) -> None:
        ttl = settings.job_ttl_minutes * 60
        while not self._stop.wait(300):
            now = time.time()
            with self._lock:
                expired = [
                    j for j in self._jobs.values()
                    if not j.active and now - (j.finished or j.created) > ttl
                ]
                for j in expired:
                    self._jobs.pop(j.id, None)
            for j in expired:
                shutil.rmtree(j.dir, ignore_errors=True)
            # Remove orphaned folders (e.g. left over after a restart)
            for d in settings.jobs_dir.iterdir():
                if d.is_dir() and d.name not in self._jobs and now - d.stat().st_mtime > ttl:
                    shutil.rmtree(d, ignore_errors=True)


manager = JobManager()
