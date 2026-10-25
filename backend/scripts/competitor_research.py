"""Run MonoPlus's competitor research agent from the command line.

    python scripts/competitor_research.py https://www.bata.com.pk
    python scripts/competitor_research.py khaadi.com --json report.json
    python scripts/competitor_research.py khaadi.com --competitor sapphireonline.pk --competitor mariab.pk

It reads the brand's website, finds its competitors, reads their sites, compares them and writes
marketing advice: recommendations, a 4-week plan and content ideas. With NEBIUS_API_KEY set,
NVIDIA Nemotron picks the competitors and writes the advice; without it, rules do. Results print
as Markdown; --json also saves the structured report. Schedule it (cron, Task Scheduler) to
track competitors week by week.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents import competitors  # noqa: E402
from app.scraper.ingestor import ingest  # noqa: E402


async def main(url: str, json_path: str | None, known: list[str]) -> int:
    print(f"Reading {url} …", file=sys.stderr)
    kit = await ingest(url)
    print(f"Brand: {kit.name} ({kit.industry}, {kit.country or 'country unknown'})", file=sys.stderr)
    report = None
    async for ev in competitors.run(kit, competitor_urls=known):
        if ev["type"] == "progress":
            print(f"  · {ev['message']}", file=sys.stderr)
        elif ev["type"] == "report":
            report = ev["report"]
    if report is None:
        return 1
    print(competitors.to_markdown(kit.name, report))
    if json_path:
        Path(json_path).write_text(report.model_dump_json(indent=2), encoding="utf-8")
        print(f"Saved {json_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Competitor research and marketing strategy for a brand's website.")
    parser.add_argument("url", help="the brand's website, e.g. https://www.bata.com.pk")
    parser.add_argument("--json", dest="json_path", help="also save the structured report to this file")
    parser.add_argument("--competitor", action="append", default=[], metavar="URL",
                        help="a competitor you already know (repeatable); analysed before any found by search")
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args.url, args.json_path, args.competitor)))
