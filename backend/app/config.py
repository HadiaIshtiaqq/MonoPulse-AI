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

# Amazon Bedrock (AWS Builder). When enabled, every model call uses the Bedrock Converse API.
# Credentials come from the standard AWS chain (AWS_ACCESS_KEY_ID/SECRET, profile or role).
AWS_REGION = _env("AWS_REGION", "us-east-1")
AWS_BEDROCK_ENABLED = _env("AWS_BEDROCK_ENABLED", "0") == "1"
# Amazon Nova models are available on-demand in us-east-1; other models may need an inference profile id.
AWS_BEDROCK_MODEL_ULTRA = _env("AWS_BEDROCK_MODEL_ULTRA", "amazon.nova-pro-v1:0")
AWS_BEDROCK_MODEL_NANO = _env("AWS_BEDROCK_MODEL_NANO", "amazon.nova-lite-v1:0")
# Where the web app lives, for links in MCP responses.
PUBLIC_APP_URL = _env("PUBLIC_APP_URL", "http://localhost:3000").rstrip("/")

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
# Bumped whenever post designs change, so campaigns drawn by an older version can offer a redraw.
DESIGN_VERSION = 7
# Your social sign-ins (MonoPlus's browser profile) live outside the project folder, so they're never
# copied, committed or backed up along with it.
BROWSER_PROFILE_DIR = Path(_env("MONOPLUS_BROWSER_PROFILE", str(Path(os.getenv("LOCALAPPDATA") or Path.home() / ".local" / "share")
                                                             / "MonoPlus" / "browser-profile")))
BROWSER_CHANNEL = _env("MONOPLUS_BROWSER", "auto")  # auto (installed Chrome, then Edge, then Playwright's), chrome, msedge, chromium
# Reels render in separate worker processes, so drawing frames never slows the API for everyone
# else (0 = threads, for tests and debugging). Campaigns: a few generate at once, a short queue
# waits, and more are turned away with "busy" instead of piling up.
REEL_PROCESSES = _env("MONOPLUS_REEL_PROCESSES", "1") not in ("0", "false", "no")
CAMPAIGNS_AT_ONCE = int(_env("MONOPLUS_CAMPAIGNS_AT_ONCE", "2") or 2)
CAMPAIGN_QUEUE = int(_env("MONOPLUS_CAMPAIGN_QUEUE", "8") or 8)
TRUST_PROXY = _env("MONOPLUS_TRUST_PROXY", "0") in ("1", "true", "yes")  # behind a proxy: read the client from X-Forwarded-For
RATE_LIMITS = _env("MONOPLUS_RATE_LIMITS", "1") not in ("0", "false", "no", "off")  # per-client limits on expensive calls
REEL_RENDERS = max(1, int(_env("MONOPLUS_REEL_RENDERS", "2") or 2))  # reels rendered at the same time

# --- Direct publishing (official APIs). A platform is "connected" when its values are set. ---
# Meta: one long-lived Page access token covers the Facebook Page and the Instagram
# professional account linked to it (permissions: pages_manage_posts, pages_read_engagement,
# instagram_basic, instagram_content_publish).
META_ACCESS_TOKEN = _env("META_ACCESS_TOKEN")
META_PAGE_ID = _env("META_PAGE_ID")
INSTAGRAM_ACCOUNT_ID = _env("INSTAGRAM_ACCOUNT_ID")
HEYGEN_API_KEY = _env("HEYGEN_API_KEY")  # AI presenters for UGC ads
HF_TOKEN = _env("HF_TOKEN")  # a free Hugging Face account: a bigger share of the free GPUs that film AI scenes
WHISPER_MODEL = _env("MONOPLUS_WHISPER_MODEL", "base")  # speech recognition for captions on real-person videos (base, small, medium)
META_PAGE_NAME = _env("META_PAGE_NAME")  # shown in the app; set by Connections
INSTAGRAM_USERNAME = _env("INSTAGRAM_USERNAME")
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
DB_PATH = DATA_DIR / "db.json"  # older JSON store, imported into SQLite once
SQLITE_PATH = DATA_DIR / "monoplus.db"
PUBLIC_API_URL = _env("PUBLIC_API_URL", "http://localhost:8000").rstrip("/")
CORS_ORIGINS = [o.strip() for o in _env("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",") if o.strip()]

# How many posts the strategist writes per Ultra call. Batches run concurrently.
COPY_BATCH_SIZE = int(_env("COPY_BATCH_SIZE", "6"))
LLM_TIMEOUT_S = float(_env("LLM_TIMEOUT_S", "60"))

MEDIA_DIR.mkdir(parents=True, exist_ok=True)


def llm_enabled() -> bool:
    return bool(NEBIUS_API_KEY) or AWS_BEDROCK_ENABLED


def tavily_enabled() -> bool:
    return bool(TAVILY_API_KEY)


# Free Google News / DuckDuckGo search when Tavily isn't configured. Tests turn this off.
FREE_SEARCH = _env("FREE_SEARCH", "1") == "1"


def search_enabled() -> bool:
    return tavily_enabled() or FREE_SEARCH
