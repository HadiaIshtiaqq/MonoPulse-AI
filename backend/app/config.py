import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
load_dotenv(BACKEND_DIR / ".env")


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


NEBIUS_API_KEY = _env("NEBIUS_API_KEY")
NEBIUS_BASE_URL = _env("NEBIUS_BASE_URL", "https://api.tokenfactory.nebius.com/v1/")

# Heavy tier: strategy, copywriting, humanizer rephrasing.
MODEL_ULTRA = _env("MODEL_ULTRA", "nvidia/NVIDIA-Nemotron-3-Ultra")
# Light tier: JSON formatting, hashtag clustering, SEO tagging, classification.
MODEL_NANO = _env("MODEL_NANO", "nvidia/NVIDIA-Nemotron-Nano-9B-v2")

TAVILY_API_KEY = _env("TAVILY_API_KEY")
# Optional: Pexels for fast, free-to-use stock photos. Without it we fall back to Openverse (CC-licensed, no key).
PEXELS_API_KEY = _env("PEXELS_API_KEY")
# Allows publish webhooks to private addresses (e.g. a local n8n). Only for local testing.
ALLOW_PRIVATE_WEBHOOKS = _env("ALLOW_PRIVATE_WEBHOOKS", "0") == "1"
# Allows the website reader to fetch private/internal addresses. Only for local testing.
ALLOW_PRIVATE_URLS = _env("ALLOW_PRIVATE_URLS", "0") == "1"
# When set, every /api call must send this key (X-Access-Key header or ?key=). Strongly
# recommended once social accounts are connected, or anyone who can reach the API can post.
ACCESS_KEY = _env("MONOPLUS_ACCESS_KEY")

# --- Direct publishing (official APIs). A platform is "connected" when its values are set. ---
# Meta: one long-lived Page access token covers the Facebook Page and the Instagram
# professional account linked to it (permissions: pages_manage_posts, pages_read_engagement,
# instagram_basic, instagram_content_publish).
META_ACCESS_TOKEN = _env("META_ACCESS_TOKEN")
META_PAGE_ID = _env("META_PAGE_ID")
INSTAGRAM_ACCOUNT_ID = _env("INSTAGRAM_ACCOUNT_ID")
GRAPH_API_VERSION = _env("GRAPH_API_VERSION", "v21.0")
# LinkedIn: token with w_member_social (person) or w_organization_social (company page).
LINKEDIN_ACCESS_TOKEN = _env("LINKEDIN_ACCESS_TOKEN")
LINKEDIN_AUTHOR_URN = _env("LINKEDIN_AUTHOR_URN")  # urn:li:person:... or urn:li:organization:...
LINKEDIN_VERSION = _env("LINKEDIN_VERSION", "202405")
# X: OAuth 2.0 user-context token with tweet.write, media.write, users.read.
X_USER_ACCESS_TOKEN = _env("X_USER_ACCESS_TOKEN")
# Optional: also/alternatively send posts to a Zapier / Make / n8n webhook.
PUBLISH_WEBHOOK_URL = _env("PUBLISH_WEBHOOK_URL")

DATA_DIR = Path(_env("DATA_DIR", str(BACKEND_DIR / "data")))
MEDIA_DIR = DATA_DIR / "media"
DB_PATH = DATA_DIR / "db.json"
PUBLIC_API_URL = _env("PUBLIC_API_URL", "http://localhost:8000").rstrip("/")
CORS_ORIGINS = [o.strip() for o in _env("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",") if o.strip()]

# How many posts the strategist writes per Ultra call. Batches run concurrently.
COPY_BATCH_SIZE = int(_env("COPY_BATCH_SIZE", "6"))
LLM_TIMEOUT_S = float(_env("LLM_TIMEOUT_S", "60"))

MEDIA_DIR.mkdir(parents=True, exist_ok=True)


def llm_enabled() -> bool:
    return bool(NEBIUS_API_KEY)


def tavily_enabled() -> bool:
    return bool(TAVILY_API_KEY)
