"""Lead Agent: IG Email Extractor CSV -> clean -> score -> verify -> first line -> Instantly -> master sheet.

Usage:
    python run.py                 test run: nothing is sent, no credits used, nothing written to the sheet
    python run.py --verify        test run that also checks emails on Bouncify (uses credits)
    python run.py --live          real run: Bouncify, Instantly and the master sheet
Options:
    --no-llm      skip Ollama: KEEP leads still go through, MAYBE leads go to the review file
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


def preflight(cfg: dict, args, marker: str) -> dict | None:
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
        campaign = sender.pick_campaign(cfg, marker)
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


REVIEW_COLUMNS = ["Decision", "Score", "Industry Tag", "Matched signals", "One-line reason", "AI note", "Username",
                  "Full name", "Email", "Followers", "Profile URL", "Bio"]


def write_review(leads, folder: Path, stamp: str) -> Path | None:
    """MAYBE leads that were not sent: saved for a person to check, never deleted."""
    maybe = [lead for lead in leads if lead.decision == "MAYBE" and lead.rejected]
    if not maybe:
        return None
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"review-{stamp}.csv"
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(REVIEW_COLUMNS)
        for lead in sorted(maybe, key=lambda l: -(l.rule_score or 0)):
            writer.writerow(["MAYBE", lead.rule_score, lead.industry, lead.signals, lead.rule_reason,
                             lead.reason.removeprefix("MAYBE: "), lead.username, lead.full_name, lead.email,
                             "" if lead.source == "podcast" else lead.followers,
                             lead.profile_url or f"https://www.instagram.com/{lead.username}", lead.biography])
    return path


def write_report(leads, out_dir: Path, stamp: str) -> Path:
    path = out_dir / f"run-{stamp}.csv"
    rows = [lead.to_row() for lead in leads]
    first = ["status", "reason", "decision", "rule_score", "industry", "signals", "rule_reason",
             "email", "first_name", "personalization", "niche", "fit_score", "tier",
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

    leads = []
    for path in files:
        try:
            leads += intake.read_file(path)
        except (ValueError, KeyError, csv.Error, UnicodeDecodeError) as problem:
            sys.exit(f"Could not read {path.name}: {problem}. Remove it from Lead files and try again.")
        log(f"Read {path.name}")
    if not leads:
        sys.exit("The lead files are empty.")

    # podcast leads can go to their own campaign; a run uses one campaign, so don't mix sources then
    markers = {cfg["podcasts"]["campaign_name_contains"] if lead.source == "podcast"
               else cfg["instantly"]["campaign_name_contains"] for lead in leads}
    if len(markers) > 1:
        sys.exit("Podcast and Instagram lead files go to different campaigns. Run them separately: "
                 "keep only one kind of file in Lead files.")
    campaign = preflight(cfg, args, markers.pop())
    podcasts = sum(lead.source == "podcast" for lead in leads)
    log(f"{len(leads)} leads loaded" + (f" ({podcasts} from podcasts)" if podcasts else ""))

    used_emails, used_usernames = (set(), set()) if args.ignore_sheet else clean.load_master_sheet(cfg)
    log(f"Master sheet: {len(used_emails):,} emails already used (duplicates checked by "
        f"{cfg['master_sheet'].get('dedupe_by', 'email').replace('_', ' ')})")
    clean.clean(leads, cfg, used_emails, used_usernames)
    decided = [lead for lead in leads if lead.decision]
    log(f"After clean & dedupe: {sum(not l.rejected for l in leads)} left (keyword rules: "
        f"{sum(l.decision == 'KEEP' for l in decided)} KEEP, {sum(l.decision == 'MAYBE' for l in decided)} MAYBE, "
        f"{sum(l.decision == 'REMOVE' for l in decided)} REMOVE)")

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
    log("First lines written" if cfg["personalisation"]["enabled"] else "First lines: off (fixed template), skipped")

    summary = sender.run(leads, cfg, campaign, dry_run=not args.live)
    log(f"Instantly: {summary}")

    if cfg["master_sheet"]["auto_write"]:
        rows = sheet_writer.run(leads, cfg, dry_run=not args.live)
        log(f"Master sheet: {len(rows)} rows {'added' if args.live else 'would be added'}")

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    report = write_report(leads, paths["output"], stamp)
    log(f"Report: {report}")
    review = write_review(leads, ROOT / cfg["classification"]["review_folder"], stamp)
    if review:
        log(f"Review file (MAYBE leads for a person to check): {review}")

    if args.live:
        for path in files:
            shutil.move(str(path), paths["processed"] / path.name)
        log("Input files moved to Processed")


if __name__ == "__main__":
    main()
