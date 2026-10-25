import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    """Tests never hit the internet: free web search is off unless a test mocks it."""
    from app import config
    from app.scraper import ingestor

    monkeypatch.setattr(config, "FREE_SEARCH", False)
    monkeypatch.setattr(ingestor, "_page_cache", {})
