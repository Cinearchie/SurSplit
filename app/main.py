"""SurSplit web server (FastAPI)."""

from __future__ import annotations

import logging
import shutil
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__, audio
from .config import BASE_DIR, MODELS, settings
from .downloader import is_youtube_url
from .jobs import STAGE_LABELS, Job, manager

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("sursplit")

ALLOWED_UPLOAD_EXT = {".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".webm", ".mp4", ".wma", ".aiff", ".aif"}
DOWNLOAD_KINDS = {
    "instrumental_mp3": ("Instrumental", "mp3", "audio/mpeg"),
    "instrumental_flac": ("Instrumental", "flac", "audio/flac"),
    "vocals_mp3": ("Vocals", "mp3", "audio/mpeg"),
    "vocals_flac": ("Vocals", "flac", "audio/flac"),
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    audio.check_ffmpeg()
    log.info("SurSplit %s ready — models in %s", __version__, settings.model_dir)
    yield
    manager.shutdown()


app = FastAPI(title="SurSplit", version=__version__, lifespan=lifespan)


def client_ip(request: Request) -> str:
    if settings.trust_proxy:
        fwd = request.headers.get("x-forwarded-for")
        if fwd:
            return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def job_to_dict(job: Job) -> dict:
    data = {
        "id": job.id,
        "status": job.stage,
        "stage_label": STAGE_LABELS.get(job.stage, job.stage),
        "progress": job.progress,
        "title": job.title,
        "duration": round(job.duration, 1),
        "model": job.model,
        "error": job.error or None,
        "queue_position": manager.queue_position(job) if job.stage == "queued" else 0,
        "files": {},
    }
    if job.stage == "done":
        data["files"] = {k: f"/api/jobs/{job.id}/download/{k}" for k in job.files}
        data["elapsed"] = round(job.finished - job.started)
    return data


# ---------------- API ----------------
@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "version": __version__}


@app.get("/api/config")
def public_config() -> dict:
    return {
        "app_name": settings.app_name,
        "youtube": settings.enable_youtube,
        "upload": settings.enable_upload,
        "max_duration_seconds": settings.max_duration_seconds,
        "max_upload_mb": settings.max_upload_mb,
        "file_ttl_minutes": settings.job_ttl_minutes,
        "default_model": settings.default_model,
        "models": [
            {"key": k, "label": MODELS[k]["label"], "note": MODELS[k]["note"]}
            for k in settings.enabled_models
        ],
    }


@app.post("/api/jobs")
async def create_job(
    request: Request,
    url: str = Form(default=""),
    model: str = Form(default=""),
    want_vocals: bool = Form(default=False),
    file: UploadFile | None = File(default=None),
) -> JSONResponse:
    ip = client_ip(request)
    model = model or settings.default_model
    if model not in settings.enabled_models:
        raise HTTPException(400, "Unknown quality option.")

    busy = manager.check_capacity(ip)
    if busy:
        raise HTTPException(429, busy)

    url = url.strip()
    has_file = file is not None and (file.filename or "") != ""

    if url and has_file:
        raise HTTPException(400, "Send either a YouTube link or a file, not both.")
    if not url and not has_file:
        raise HTTPException(400, "Paste a YouTube link or choose an audio file.")

    job_id = manager.new_job_id()

    if url:
        if not settings.enable_youtube:
            raise HTTPException(403, "YouTube links are disabled on this server. Please upload a file.")
        if not is_youtube_url(url):
            raise HTTPException(400, "That doesn't look like a YouTube link.")
        if not url.lower().startswith("http"):
            url = "https://" + url
        job = Job(id=job_id, source="youtube", url=url, model=model,
                  want_vocals=want_vocals, client_ip=ip)
        return JSONResponse(job_to_dict(manager.submit(job)), status_code=202)

    # ---- file upload ----
    if not settings.enable_upload:
        raise HTTPException(403, "File uploads are disabled on this server.")
    assert file is not None
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_UPLOAD_EXT:
        raise HTTPException(400, f"Unsupported file type '{ext or '?'}'.")

    job_dir = settings.jobs_dir / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    dest = job_dir / f"upload{ext}"
    limit = settings.max_upload_mb * 1024 * 1024
    size = 0
    try:
        with dest.open("wb") as out:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > limit:
                    raise HTTPException(413, f"File is larger than {settings.max_upload_mb} MB.")
                out.write(chunk)
    except HTTPException:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise
    finally:
        await file.close()

    title = Path(file.filename or "").stem
    job = Job(id=job_id, source="upload", upload_path=dest, model=model,
              want_vocals=want_vocals, client_ip=ip, title=title)
    return JSONResponse(job_to_dict(manager.submit(job)), status_code=202)


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    job = manager.get(job_id)
    if not job:
        raise HTTPException(404, "This job doesn't exist or has expired.")
    return job_to_dict(job)


@app.get("/api/jobs/{job_id}/download/{kind}")
def download(job_id: str, kind: str, inline: bool = False):
    job = manager.get(job_id)
    if not job or job.stage != "done":
        raise HTTPException(404, "File not available.")
    if kind not in DOWNLOAD_KINDS or kind not in job.files:
        raise HTTPException(404, "File not available.")
    path = job.files[kind]
    if not path.exists():
        raise HTTPException(410, "This file has expired.")
    label, ext, mime = DOWNLOAD_KINDS[kind]
    filename = f"{job.title} - {label}.{ext}"
    return FileResponse(
        path, media_type=mime, filename=filename,
        content_disposition_type="inline" if inline else "attachment",
    )


# ---------------- Frontend ----------------
app.mount("/", StaticFiles(directory=BASE_DIR / "static", html=True), name="static")


def run() -> None:
    import uvicorn
    uvicorn.run("app.main:app", host=settings.host, port=settings.port)


if __name__ == "__main__":
    run()
