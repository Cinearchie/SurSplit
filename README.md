<div align="center">

# 🎵 SurSplit

**Keep the *sur*, lose the vocals.**

A free, self-hosted AI vocal remover. Paste a YouTube link or upload a song and get a clean instrumental (and, if you want, the isolated vocals) as a **320 kbps MP3** and a **lossless 24-bit FLAC**.

![Python](https://img.shields.io/badge/python-3.10%E2%80%933.13-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688)
![FFmpeg](https://img.shields.io/badge/requires-FFmpeg-green)
![Docker](https://img.shields.io/badge/docker-ready-2496ED)

</div>

---

## ✨ Features

- **Two inputs:** a YouTube link (via yt-dlp) or a file upload (MP3, WAV, FLAC, M4A, AAC, OGG, Opus, WebM, MP4, WMA, AIFF).
- **State-of-the-art separation:** uses UVR models through [audio-separator](https://github.com/nomadkaraoke/python-audio-separator).
  - `hq`: **MDX-Net Inst HQ 4** (default; fast on a CPU, very good quality)
  - `best`: **BS-RoFormer** (SDR 12.98; the cleanest result, but needs a GPU to be practical)
- **Studio-grade output:** 320k MP3 and 24-bit FLAC, with the YouTube cover art embedded.
- **Optional vocals track:** tick a box to get the a cappella as well.
- **Live progress:** queue position and percentage are shown in the browser.
- **Safe to host publicly:** limits on song length, upload size, queue size and jobs per IP; one job runs at a time; files are deleted automatically.
- **No API keys and no paid services.** Everything runs on your own machine.

## 🧠 How it works

```
Browser ──POST /api/jobs──▶ FastAPI ──▶ job queue (1 worker by default)
   ▲                                       │
   │ poll GET /api/jobs/{id}               ├─ yt-dlp: best audio + thumbnail   (YouTube mode)
   │                                       ├─ ffprobe/ffmpeg: validate → 32-bit float WAV
   │                                       ├─ audio-separator subprocess → instrumental.wav (+ vocals.wav)
   └── download links ◀────────────────────└─ ffmpeg → MP3 320k + FLAC 24-bit, cover embedded
```

- Separation runs in a **subprocess**, so memory is released after every song. Progress is read from the model's progress bar.
- Large intermediate WAVs are deleted as soon as they have been exported. Results expire after `JOB_TTL_MINUTES` (2 hours by default).

---

## 🚀 Quick start

### Prerequisites

- **Python 3.10 – 3.13**
- **FFmpeg** on your `PATH`:
  - macOS: `brew install ffmpeg`
  - Windows: `winget install Gyan.FFmpeg`
  - Ubuntu/Debian: `sudo apt install ffmpeg`
- About **2 GB** of free disk space for packages, models and temporary files

### One command

```bash
git clone https://github.com/<your-username>/sursplit.git
cd sursplit

# macOS / Linux
chmod +x run.sh && ./run.sh

# Windows
run.bat
```

The script creates a virtual environment, installs the dependencies, downloads the default model (about 60 MB) and starts the server. Then open **http://127.0.0.1:8000**.

### Manual setup

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # Windows: copy .env.example .env
python scripts/download_models.py hq     # add "best" for BS-RoFormer (~640 MB)
python -m app.main
```

### NVIDIA GPU (much faster)

```bash
pip uninstall -y onnxruntime
pip install "audio-separator[gpu]"
# plus a CUDA build of PyTorch: https://pytorch.org/get-started/locally/
```

### VS Code

Open the folder, choose the `.venv` interpreter (**Ctrl/Cmd+Shift+P → Python: Select Interpreter**), then press **F5** and pick **"SurSplit: run server"**. It runs with auto-reload and breakpoints.

---

## ⚡ Speed and quality

| Model | Quality | 5-min song, 2-core CPU | 5-min song, GPU |
|---|---|---|---|
| `hq`: MDX-Net Inst HQ 4 | Very good | ~6–7 min | ~20 s |
| `best`: BS-RoFormer | Best available | ~2–3 hours ⚠️ | ~1 min |

> The output can never be better than the source. A YouTube stream is usually 128–160 kbps Opus/AAC, so for the cleanest instrumental, upload a lossless file.

---

## ⚙️ Configuration

All settings are optional. Copy `.env.example` to `.env` and edit it, or set them as environment variables.

| Variable | Default | Description |
|---|---|---|
| `HOST` / `PORT` | `127.0.0.1` / `8000` | Bind address. Use `0.0.0.0` to accept other devices |
| `DATA_DIR` / `MODEL_DIR` | `data` / `models` | Temporary job files / downloaded models |
| `ENABLE_YOUTUBE` | `true` | Allow YouTube links |
| `ENABLE_UPLOAD` | `true` | Allow file uploads |
| `ENABLED_MODELS` | `hq,best` | Models users can choose. Use `hq` on CPU-only hosts |
| `DEFAULT_MODEL` | `hq` | Model selected by default |
| `MAX_DURATION_SECONDS` | `600` | Longest song accepted |
| `MAX_UPLOAD_MB` | `100` | Largest upload accepted |
| `MAX_CONCURRENT_JOBS` | `1` | Separations running at the same time |
| `MAX_QUEUE_SIZE` | `20` | Jobs waiting plus jobs running |
| `MAX_ACTIVE_JOBS_PER_IP` | `2` | Per-visitor limit |
| `JOB_TTL_MINUTES` | `120` | How long results are kept |
| `TRUST_PROXY` | `false` | Set `true` behind Nginx, Cloudflare, Render or Hugging Face |
| `YTDLP_COOKIES` | *(empty)* | Path to a `cookies.txt` for YouTube on cloud servers |
| `NORMALIZATION` | `0.9` | Peak normalisation for the separator |
| `MP3_BITRATE` | `320k` | MP3 export bitrate |

---

## 🔌 API

| Method | Path | Notes |
|---|---|---|
| `GET` | `/api/health` | Liveness check |
| `GET` | `/api/config` | Enabled features, limits and models |
| `POST` | `/api/jobs` | Multipart form: `url` **or** `file`, plus `model` (`hq`/`best`) and `want_vocals` (`true`/`false`) |
| `GET` | `/api/jobs/{id}` | Status, progress %, queue position and download links |
| `GET` | `/api/jobs/{id}/download/{kind}` | `kind` is `instrumental_mp3`, `instrumental_flac`, `vocals_mp3` or `vocals_flac` |

Example:

```bash
curl -F file=@song.mp3 -F want_vocals=true http://127.0.0.1:8000/api/jobs
# → {"id":"8fe6…","status":"queued",…}
curl http://127.0.0.1:8000/api/jobs/8fe6…
```

---

## ☁️ Deployment

A production `Dockerfile` is included. It serves on port **7860**, runs as a non-root user and builds the `hq` model into the image.

### Hugging Face Spaces (free: 2 vCPU / 16 GB RAM)

1. **New Space** → SDK **Docker** → *Blank*.
2. Put this front-matter at the very top of the Space's `README.md`:
   ```yaml
   ---
   title: SurSplit
   emoji: 🎵
   colorFrom: yellow
   colorTo: purple
   sdk: docker
   app_port: 7860
   ---
   ```
3. Push this repo to the Space. It builds automatically.
4. Under **Settings → Variables**, set `ENABLED_MODELS=hq`.

### Any VPS

```bash
docker build -t sursplit .
docker run -d --name sursplit -p 80:7860 --restart unless-stopped \
  -e ENABLED_MODELS=hq -v sursplit-models:/app/models sursplit
```

Put Cloudflare in front of it for free HTTPS.

### Render / Railway

Create a **Web Service** from the repo with the **Docker** runtime. Free tiers (512 MB RAM) are too small for the model, so use an instance with at least 2 GB of RAM.

### YouTube on servers

YouTube often blocks datacenter IPs with *"Sign in to confirm you're not a bot"*. To get around this:

1. Export cookies from a browser that is logged in to a **spare** account, for example with *Get cookies.txt LOCALLY*.
2. Upload the file and set `YTDLP_COOKIES=/app/cookies.txt`.

Keep yt-dlp up to date (`pip install -U yt-dlp`, or rebuild the image) whenever downloads start failing.

---

## 🗂️ Project structure

```
sursplit/
├── app/
│   ├── main.py          # FastAPI routes + static frontend
│   ├── config.py        # all settings (env / .env)
│   ├── jobs.py          # queue, worker pipeline, cleanup
│   ├── downloader.py    # yt-dlp wrapper
│   ├── separator.py     # audio-separator subprocess + progress
│   └── audio.py         # ffmpeg/ffprobe helpers
├── static/              # index.html, styles.css, app.js, favicon.svg
├── scripts/
│   └── download_models.py
├── Dockerfile
├── requirements.txt
├── .env.example
├── run.sh / run.bat
└── .vscode/launch.json
```

---

## 🛠️ Troubleshooting

| Problem | Fix |
|---|---|
| `'ffmpeg' was not found on PATH` | Install FFmpeg and restart your terminal |
| `No module named 'audioread'` / `aifc` | Run `pip install -r requirements.txt` again (Python 3.13 needs the `standard-*` packages) |
| Stuck at "Removing vocals" ~20% | Normal: the model is loading. The first run also downloads it |
| YouTube "not a bot" error | See [YouTube on servers](#youtube-on-servers) |
| Port already in use | Set `PORT=8001` in `.env` |

---

## ⚖️ Legal notice

SurSplit is a tool. You are responsible for what you process with it. Downloading from YouTube may break YouTube's Terms of Service, and most commercial music is copyrighted. If you host SurSplit publicly, the safest setup is **upload-only** (`ENABLE_YOUTUBE=false`) with a clear notice that users may only process audio they have the rights to.

## 🙏 Credits

| Project | Role | License |
|---|---|---|
| [yt-dlp](https://github.com/yt-dlp/yt-dlp) | YouTube audio download | Unlicense |
| [audio-separator](https://github.com/nomadkaraoke/python-audio-separator) | Runs the UVR models | MIT |
| [Ultimate Vocal Remover](https://github.com/Anjok07/ultimatevocalremovergui) | MDX-Net and RoFormer models | MIT |
| [FFmpeg](https://ffmpeg.org) | Decoding, encoding and cover art | LGPL/GPL |
| [FastAPI](https://fastapi.tiangolo.com) | Web server | MIT |

## 📄 License

Released under the [MIT License](LICENSE).

<div align="center">Made with ❤️ in India</div>
