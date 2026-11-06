"""Lead Agent: IG Email Extractor CSV -> clean -> score -> verify -> first line -> Instantly -> master sheet.

Usage:
    python run.py                 test run: nothing is sent, no credits used, nothing written to the sheet
    python run.py --verify        test run that also checks emails on Bouncify (uses credits)
    python run.py --live          real run: Bouncify, Instantly and the master sheet
Options:
    --no-llm      skip Ollama (keyword scoring + fallback first line), for quick tests
    --any-day     allow a live run outside the campaign days
    --ignore-sheet  test runs only: skip the master-sheet duplicate check (to test on old files)
"""
from __future__ import annotations

import argparse
import csv
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

import requests

from lead_agent import clean, intake, personaliser, scorer, sender, sheet_writer, verifier, website_finder
from lead_agent.common import ROOT, load_config, load_env


def log(message: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {message}", flush=True)


def preflight(cfg: dict, args) -> dict | None:
    """Check keys, campaign day, campaign and sheet access before touching any lead. Returns the campaign."""
    if args.live and not args.any_day:
        today = datetime.now().strftime("%A")
        if today not in cfg["instantly"]["campaign_days"]:
            sys.exit(f"Today is {today}. New campaigns run only on {', '.join(cfg['instantly']['campaign_days'])}. "
                     "Use --any-day to override.")
    for key in ("INSTANTLY_API_KEY",) + (("BOUNCIFY_API_KEY",) if args.live or args.verify else ()):
        if not os.environ.get(key):
            sys.exit(f"{key} is missing in .env")
    if not args.no_llm:
        try:
            requests.get(cfg["scoring"]["ollama_url"].replace("/api/generate", "/api/tags"), timeout=5).raise_for_status()
        except requests.RequestException:
            sys.exit("Ollama is not running. Open the Ollama app (or run `ollama serve`), then try again.")
    try:
        campaign = sender.pick_campaign(cfg)
        log(f"Instantly campaign: {campaign['name']}")
    except sender.NoCampaign as problem:
        if args.live:
            sys.exit(str(problem))
        log(f"Note (test run continues): {problem}")
        campaign = {"id": "", "name": "(none yet)"}
    if args.live or args.verify:
        log(f"Bouncify credits: {verifier.credits_remaining():,}")
    if args.live and cfg["master_sheet"]["auto_write"]:
        log(f"Master sheet tab: {sheet_writer.check_access(cfg)}")
    return campaign


def write_report(leads, out_dir: Path, stamp: str) -> Path:
    path = out_dir / f"run-{stamp}.csv"
    rows = [lead.to_row() for lead in leads]
    first = ["status", "reason", "email", "first_name", "personalization", "niche", "fit_score", "tier",
             "verification", "followers", "username", "full_name", "website", "email_source", "fit_reason", "notes"]
    fields = first + [k for k in rows[0] if k not in first]
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--no-llm", action="store_true")
    parser.add_argument("--any-day", action="store_true")
    parser.add_argument("--ignore-sheet", action="store_true")
    args = parser.parse_args()
    if args.live and args.ignore_sheet:
        sys.exit("--ignore-sheet is only allowed in test runs")

    load_env()
    cfg = load_config()
    paths = {k: ROOT / v for k, v in cfg["paths"].items()}
    for p in paths.values():
        p.mkdir(parents=True, exist_ok=True)

    files = intake.find_new_files(paths["incoming"])
    if not files:
        sys.exit(f"No CSV files in {paths['incoming']}")
    log("LIVE RUN" if args.live else "TEST RUN (nothing is sent)")
    campaign = preflight(cfg, args)

    leads = []
    for path in files:
        leads += intake.read_file(path)
        log(f"Read {path.name}")
    log(f"{len(leads)} leads loaded")

    used_emails, used_usernames = (set(), set()) if args.ignore_sheet else clean.load_master_sheet(cfg)
    log(f"Master sheet: {len(used_emails):,} emails already used (duplicates checked by "
        f"{cfg['master_sheet'].get('dedupe_by', 'email').replace('_', ' ')})")
    clean.clean(leads, cfg, used_emails, used_usernames)
    log(f"After clean & dedupe: {sum(not l.rejected for l in leads)} left")

    website_finder.run(leads, cfg)
    clean.recheck_emails(leads, used_emails)
    log(f"After website email finder: {sum(not l.rejected for l in leads)} left")

    scorer.run(leads, cfg, use_llm=not args.no_llm)
    log(f"After fit scoring: {sum(not l.rejected for l in leads)} left")

    try:
        verifier.run(leads, cfg, enabled=args.live or args.verify)
    except verifier.OutOfCredits as problem:
        sys.exit(str(problem))
    log(f"After email verification: {sum(not l.rejected for l in leads)} left")

    personaliser.run(leads, cfg, use_llm=not args.no_llm)
    log("First lines written")

    summary = sender.run(leads, cfg, campaign, dry_run=not args.live)
    log(f"Instantly: {summary}")

    if cfg["master_sheet"]["auto_write"]:
        rows = sheet_writer.run(leads, cfg, dry_run=not args.live)
        log(f"Master sheet: {len(rows)} rows {'added' if args.live else 'would be added'}")

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    report = write_report(leads, paths["output"], stamp)
    log(f"Report: {report}")

    if args.live:
        for path in files:
            shutil.move(str(path), paths["processed"] / path.name)
        log("Input files moved to Processed")


if __name__ == "__main__":
    main()
