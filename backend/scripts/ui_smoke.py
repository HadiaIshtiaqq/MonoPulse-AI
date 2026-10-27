"""Browser smoke test: open every page of a running MonoPlus in Chromium and fail on any page
error. With campaigns in the store it also opens one, its post editor and each editor tab.

    pip install playwright && python -m playwright install chromium
    python scripts/ui_smoke.py [--app http://localhost:3000] [--api http://localhost:8000]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request


def wait_for(url: str, seconds: int = 90) -> None:
    for _ in range(seconds):
        try:
            urllib.request.urlopen(url, timeout=3)
            return
        except Exception:  # noqa: BLE001 - not up yet
            time.sleep(1)
    raise SystemExit(f"{url} didn't come up")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--app", default="http://localhost:3000")
    ap.add_argument("--api", default="http://localhost:8000")
    args = ap.parse_args()
    wait_for(f"{args.api}/api/health")
    wait_for(args.app)

    from playwright.sync_api import sync_playwright

    errors: list[str] = []
    checked: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for viewport in ({"width": 1440, "height": 900}, {"width": 390, "height": 844}):
            page = browser.new_page(viewport=viewport)
            page.on("pageerror", lambda e: errors.append(f"{page.url}: {e}"))
            for path in ("/", "/campaigns", "/research", "/humanizer"):
                page.goto(args.app + path, wait_until="networkidle")
                checked.append(f"{path} @ {viewport['width']}px")
            campaigns = json.load(urllib.request.urlopen(f"{args.api}/api/campaigns"))
            ready = [c for c in campaigns if c.get("status") != "GENERATING" and c.get("posts")]
            if ready and viewport["width"] > 1000:
                page.goto(f"{args.app}/campaign/{ready[0]['id']}", wait_until="networkidle")
                page.wait_for_timeout(1000)
                cards = page.locator("div[role=button][draggable=true]")
                if cards.count():
                    cards.first.click()
                    page.wait_for_timeout(800)
                    for tab in ("Caption", "Reel", "Post", "Design"):
                        page.get_by_role("button", name=tab, exact=True).click()
                        page.wait_for_timeout(500)
                    checked.append("campaign + post editor tabs")
            page.close()
        browser.close()
    print("checked:", ", ".join(checked))
    if errors:
        print("page errors:\n  " + "\n  ".join(errors))
        return 1
    print("no page errors")
    return 0


if __name__ == "__main__":
    sys.exit(main())
