import os
import sys
import tempfile
from pathlib import Path

import pytest

# Tests get their own data folder (database, rendered images, reels), set before the app is
# imported, so they never read or change the real campaigns and media.
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="monoplus-tests-")
os.environ["MONOPLUS_BROWSER_PROFILE"] = os.path.join(os.environ["DATA_DIR"], "signed-in-profile")  # never your real sign-ins
# Never your real keys: each is set blank before the app loads backend/.env (which doesn't override
# what's already set), so tests can't call a real service or post to a real account.
for _key in ("NEBIUS_API_KEY", "TAVILY_API_KEY", "PEXELS_API_KEY", "HEYGEN_API_KEY", "HF_TOKEN", "MONOPLUS_ACCESS_KEY", "ACCESS_KEY",
             "META_ACCESS_TOKEN", "META_PAGE_ID", "INSTAGRAM_ACCOUNT_ID", "META_PAGE_NAME", "INSTAGRAM_USERNAME", "META_USER_TOKEN",
             "META_APP_ID", "META_APP_SECRET", "LINKEDIN_ACCESS_TOKEN", "X_USER_ACCESS_TOKEN", "PUBLISH_WEBHOOK_URL", "MCP_TOKEN",
             "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
    os.environ[_key] = ""
os.environ["AWS_BEDROCK_ENABLED"] = "0"
os.environ["MONOPLUS_RATE_LIMITS"] = "0"  # tests call the API far faster than a person; one test turns limits on
os.environ["MONOPLUS_REEL_PROCESSES"] = "0"  # in-process, so tests can shrink the frame rate; one test uses a worker process

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    """Tests never hit the internet: free web search is off unless a test mocks it."""
    from app import config
    from app.scraper import ingestor

    monkeypatch.setattr(config, "FREE_SEARCH", False)
    from app.agents import wiki

    async def no_wikipedia(*args, **kwargs):
        return []

    monkeypatch.setattr(wiki, "brands_in", no_wikipedia)
    monkeypatch.setattr(wiki, "search", no_wikipedia)
    monkeypatch.setattr(ingestor, "_page_cache", {})
