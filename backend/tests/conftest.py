import os
import sys
import tempfile
from pathlib import Path

import pytest

# Tests get their own data folder (database, rendered images, reels), set before the app is
# imported, so they never read or change the real campaigns and media.
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="monoplus-tests-")
os.environ["MONOPLUS_BROWSER_PROFILE"] = os.path.join(os.environ["DATA_DIR"], "signed-in-profile")  # never your real sign-ins
os.environ["MONOPLUS_RATE_LIMITS"] = "0"  # tests call the API far faster than a person; one test turns limits on

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
