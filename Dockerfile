# SurSplit — production image (works on Hugging Face Spaces, Render, Railway, any VPS)
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HOST=0.0.0.0 \
    PORT=7860 \
    TRUST_PROXY=true \
    DATA_DIR=/app/data \
    MODEL_DIR=/app/models

RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg \
 && rm -rf /var/lib/apt/lists/*

# Non-root user (required by Hugging Face Spaces, good practice everywhere)
RUN useradd -m -u 1000 app
WORKDIR /app

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY --chown=app:app . .
RUN mkdir -p /app/data /app/models && chown -R app:app /app
USER app

# Bake the default model into the image so the first request is fast
RUN python scripts/download_models.py hq

EXPOSE 7860
CMD ["sh", "-c", "uvicorn app.main:app --host ${HOST} --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
