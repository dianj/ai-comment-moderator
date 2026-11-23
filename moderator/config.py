"""Settings, read once at import from environment variables.

A local .env file (git-ignored, see .env.example) fills in the ones that are not set.
Tests set MODERATOR_SKIP_DOTENV so a developer's .env cannot change their results.
"""
import os
import secrets
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
if not os.environ.get("MODERATOR_SKIP_DOTENV"):
    load_dotenv(ROOT / ".env")

INDEX_HTML = ROOT / "index.html"

# LLM (any OpenAI-compatible server; LM Studio by default)
LLM_BASE_URL = os.environ.get("LMSTUDIO_URL", "http://localhost:1235/v1")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "lm-studio")
MODEL_NAME = os.environ.get("MODERATION_MODEL", "gemma-4-26b-a4b-it")
# "none" skips the model's hidden reasoning (seconds instead of a minute per comment);
# an empty value leaves the model's default. See evals/results for the measured trade-off.
REASONING_EFFORT = os.environ.get("LLM_REASONING_EFFORT", "none")
LLM_TIMEOUT_S = float(os.environ.get("LLM_TIMEOUT_S", "120"))

# Decision gate: a calibrated second opinion before anything is published or rejected automatically
# (docs/DECISIONS.md). 0 = the policy decides from the main verdict alone, as before.
DECISION_GATE = os.environ.get("DECISION_GATE", "1") == "1"
CALIBRATION_DIR = ROOT / os.environ.get("CALIBRATION_DIR", "evals/decisions/calibration")  # relative to the repo

# Storage
DB_PATH = os.environ.get("MODERATION_DB", str(ROOT / "moderation.db"))

# Abuse limits
MAX_AUTHOR_CHARS = 80
MAX_COMMENT_CHARS = int(os.environ.get("MAX_COMMENT_CHARS", "2000"))
RATE_LIMIT_PER_MINUTE = int(os.environ.get("RATE_LIMIT_PER_MINUTE", "10"))

# Policy: a comment the model calls Clean but scores at least this toxic goes to a human.
REVIEW_TOXICITY_THRESHOLD = int(os.environ.get("REVIEW_TOXICITY_THRESHOLD", "40"))

# Admin endpoints need this token in the X-Admin-Token header. Without a configured token a random
# one is generated at start-up and printed to the console, so the admin panel is never left open.
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN") or secrets.token_urlsafe(16)
if not os.environ.get("ADMIN_TOKEN"):
    _banner = "=" * 64
    print(f"\n{_banner}\n  Admin token for this run: {ADMIN_TOKEN}\n"
          f"  Set ADMIN_TOKEN in .env to keep the same token between restarts.\n{_banner}\n", flush=True)
