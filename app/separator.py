"""Vocal / instrumental separation using audio-separator (UVR models).

Runs in a subprocess so heavy model memory is released after every job and
so we can read live progress from its tqdm output.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable

from .config import MODELS

PROGRESS_RE = re.compile(r"(\d+)/(\d+)\s*\[")


class SeparationError(RuntimeError):
    pass


def _cli() -> list[str]:
    exe = shutil.which("audio-separator")
    if exe:
        return [exe]
    return [sys.executable, "-m", "audio_separator.utils.cli"]


def download_model(model_key: str, model_dir: Path) -> None:
    """Pre-download a model so the first user doesn't wait for it."""
    model_file = MODELS[model_key]["file"]
    subprocess.run(
        _cli() + ["-m", model_file, "--model_file_dir", str(model_dir), "--download_model_only"],
        check=True,
    )


def separate(wav: Path, out_dir: Path, model_key: str, model_dir: Path,
             want_vocals: bool, normalization: float = 0.9,
             on_progress: Callable[[float], None] | None = None) -> dict[str, Path]:
    """Separate `wav` and return {"instrumental": path, "vocals": path?}."""
    model_file = MODELS[model_key]["file"]
    names = {"Instrumental": "instrumental", "Vocals": "vocals"}

    cmd = _cli() + [
        str(wav),
        "-m", model_file,
        "--model_file_dir", str(model_dir),
        "--output_dir", str(out_dir),
        "--output_format", "WAV",
        "--normalization", str(normalization),
        "--custom_output_names", json.dumps(names),
    ]
    if not want_vocals:
        cmd += ["--single_stem", "Instrumental"]

    proc = subprocess.Popen(
        cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        bufsize=0, cwd=str(out_dir),
    )

    tail: list[str] = []
    buf = b""
    assert proc.stderr is not None
    while True:
        chunk = proc.stderr.read(512)
        if not chunk:
            break
        buf += chunk
        # tqdm uses \r to redraw; logs use \n.
        parts = re.split(rb"[\r\n]", buf)
        buf = parts.pop()
        for raw in parts:
            line = raw.decode("utf-8", "replace").strip()
            if not line:
                continue
            tail = (tail + [line])[-15:]
            m = PROGRESS_RE.search(line)
            if m and on_progress:
                done, total = int(m.group(1)), int(m.group(2))
                if total:
                    on_progress(done / total)
    code = proc.wait()

    results: dict[str, Path] = {}
    for key in ("instrumental", "vocals"):
        f = out_dir / f"{key}.wav"
        if f.exists():
            results[key] = f

    if code != 0 or "instrumental" not in results:
        detail = next((l for l in reversed(tail) if "error" in l.lower()), tail[-1] if tail else "")
        raise SeparationError(f"Separation failed. {detail[:300]}")
    return results
