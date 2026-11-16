"""Pre-download the AI models so the first user doesn't wait.

Usage:
    python scripts/download_models.py          # downloads every enabled model
    python scripts/download_models.py hq       # just one
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import MODELS, settings  # noqa: E402
from app.separator import download_model  # noqa: E402

keys = sys.argv[1:] or settings.enabled_models
for key in keys:
    if key not in MODELS:
        print(f"Unknown model '{key}'. Choose from: {', '.join(MODELS)}")
        continue
    print(f"→ Downloading {MODELS[key]['label']} into {settings.model_dir} …")
    download_model(key, settings.model_dir)
print("Done.")
