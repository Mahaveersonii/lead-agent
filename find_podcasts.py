"""Find new leads among podcast hosts and save them as a lead file in Leads/Incoming.

    python find_podcasts.py                          all target niches, countries from config.json
    python find_podcasts.py --keywords "life coach,career coach" --countries US,GB

Free: uses Apple Podcasts search and public RSS feeds, no key or account. Sends nothing.
After it finishes, run a test run or a LIVE run as usual to score, verify and upload the leads.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime

from lead_agent import clean, podcast_finder
from lead_agent.common import ROOT, load_config, load_env


def log(message: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {message}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--keywords", help="comma separated; default: podcasts.keywords, or target_niches")
    parser.add_argument("--countries", help="comma separated Apple store codes, e.g. US,GB,AU,CA")
    args = parser.parse_args()

    load_env()
    cfg = load_config()
    settings = cfg["podcasts"]
    keywords = [k.strip() for k in (args.keywords.split(",") if args.keywords else
                                    settings["keywords"] or cfg["target_niches"]) if k.strip()]
    if args.countries:
        settings["countries"] = [c.strip().upper() for c in args.countries.split(",") if c.strip()]
    incoming = ROOT / cfg["paths"]["incoming"]
    processed = ROOT / cfg["paths"]["processed"]
    incoming.mkdir(parents=True, exist_ok=True)

    log(f"PODCAST SEARCH: {len(keywords)} keywords x {len(settings['countries'])} countries "
        f"({', '.join(settings['countries'])}), active in the last {settings['active_days']} days")
    try:
        used_emails, _ = clean.load_master_sheet(cfg)
        log(f"Master sheet: {len(used_emails):,} emails already used")
    except Exception as problem:  # the normal run checks the sheet again, so carry on
        used_emails = set()
        log(f"Note: could not read the master sheet now ({problem}). The run will still check it.")
    used_emails |= podcast_finder.previously_found(processed)

    rows, counts = podcast_finder.find(cfg, keywords, used_emails, log)
    log("Filter results: " + ", ".join(f"{k} {v}" for k, v in counts.items()))
    if not rows:
        sys.exit("No new podcast leads found. Try other keywords or a longer active period.")

    path = incoming / f"Podcasts-{datetime.now():%Y%m%d-%H%M%S}-{len(rows)}.csv"
    podcast_finder.write_lead_file(rows, path)
    log(f"Saved {len(rows)} new podcast leads to Lead files: {path.name}")
    log("Next: run a Test run or the LIVE run as usual.")


if __name__ == "__main__":
    main()
