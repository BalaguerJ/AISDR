from __future__ import annotations
import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from the project root (one level above this file)
env_path = Path(__file__).parent.parent / ".env"
load_dotenv(dotenv_path=env_path)

# ── AI Model Settings ──────────────────────────────────────────────────────────
_raw_keys = os.getenv("GEMINI_API_KEYS") or os.getenv("GEMINI_API_KEY", "")
# Split by comma and strip whitespace, filter out empty strings
GEMINI_API_KEYS: list[str] = [k.strip() for k in _raw_keys.split(",") if k.strip()]
GEMINI_MODEL: str = "gemini-2.5-flash"  # High free-tier quota, confirmed working on 8/9 keys

# ── Scraper Settings ───────────────────────────────────────────────────────────
DEFAULT_LEAD_LIMIT: int = 10
DEFAULT_QUERY_COUNT: int = 3      # 3 queries = optimal speed/coverage balance
SCRAPE_DELAY_SECONDS: float = 0.7 # Min safe delay — reduces per-lead time by ~30%

# ── Rate Limiting ──────────────────────────────────────────────────────────────
# Gemini free tier: 15 req/min per key. With multiple keys we distribute load.
# Safety buffer: Target 10-12 rpm per key instead of exactly 15 to avoid sliding window 429s.
AI_REQUEST_DELAY_SECONDS: float = max(0.5, 6.0 / max(1, len(GEMINI_API_KEYS)))

# ── Website Crawl Settings ─────────────────────────────────────────────────────
WEB_REQUEST_TIMEOUT: int = 8      # 8s timeout — fast fail for unresponsive sites
MAX_PAGE_TEXT_CHARS: int = 12000  # More context = higher AI extraction quality

if not GEMINI_API_KEYS or GEMINI_API_KEYS[0] == "your_gemini_api_key_here":
    raise EnvironmentError(
        "\n\n❌  GEMINI_API_KEY not set!\n"
        "    1. Open the '.env' file in the project root.\n"
        "    2. Replace 'your_gemini_api_key_here' with your real key.\n"
        "    3. Get a free key at: https://aistudio.google.com/\n"
    )
