"""Agent 0b - Podcast Finder: new leads from podcast hosts, using free public data only.

Apple Podcasts search (official, free, no key) gives each show's RSS feed address. The RSS feed is the
public file every podcast publishes for directories, and most list the owner's name and contact email.
We keep shows that are still active, use the host's own email and are not already in the master sheet,
and save them as a lead file in the IG Email Extractor layout so the normal run can process them.
"""
from __future__ import annotations

import csv
import html
import re
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import requests

from .common import EMAIL_RE
from .intake import EXPECTED_COLUMNS

SEARCH_URL = "https://itunes.apple.com/search"
ITUNES = "{http://www.itunes.com/dtds/podcast-1.0.dtd}"
HEADERS = {"User-Agent": "LeadAgent-PodcastFinder/1.0 (reads public podcast RSS feeds)"}
EXTRA_COLUMNS = ["Source", "Podcast Name", "Episode Count", "Latest Episode Date", "Latest Episode Title", "Feed Url"]
TAG_RE = re.compile(r"<[^>]+>")


def _search(term: str, country: str, limit: int, log) -> list[dict]:
    params = {"term": term, "media": "podcast", "entity": "podcast", "limit": limit, "country": country}
    for attempt in range(4):
        try:
            response = requests.get(SEARCH_URL, params=params, headers=HEADERS, timeout=30)
            if response.status_code == 200:
                return response.json().get("results", [])
            if response.status_code in (403, 429, 503):  # Apple asks us to slow down
                log(f"Apple asked us to slow down, waiting {30 * (attempt + 1)} seconds")
                time.sleep(30 * (attempt + 1))
                continue
            log(f"Search '{term}' in {country} failed (HTTP {response.status_code}). Check the country code.")
            return []
        except (requests.RequestException, ValueError):
            time.sleep(5)
    log(f"Search '{term}' in {country} failed after 4 tries. Check the internet connection.")
    return []


def _text(value: str, limit: int = 600) -> str:
    return re.sub(r"\s+", " ", TAG_RE.sub(" ", html.unescape(value or ""))).strip()[:limit]


def _read_feed(show: dict) -> dict | None:
    """Return the show's details from its RSS feed, or None when the feed can't be read."""
    feed = show.get("feedUrl", "")
    if not feed:
        return None
    try:
        response = requests.get(feed, headers=HEADERS, timeout=20)
        response.raise_for_status()
        channel = ET.fromstring(response.content).find("channel")
    except Exception:  # broken or unreachable feeds are common; skip them
        return None
    if channel is None:
        return None

    owner = channel.find(f"{ITUNES}owner")
    owner_name = (owner.findtext(f"{ITUNES}name") if owner is not None else "") or ""
    email = (owner.findtext(f"{ITUNES}email") if owner is not None else "") or ""
    if not EMAIL_RE.search(email):
        email = ""
        for tag in ("managingEditor", "webMaster", "description"):
            match = EMAIL_RE.search(channel.findtext(tag) or "")
            if match:
                email = match.group(0)
                break

    items = channel.findall("item")
    dates = []
    for item in items[:25]:
        try:
            date = parsedate_to_datetime(item.findtext("pubDate"))
            dates.append(date if date.tzinfo else date.replace(tzinfo=timezone.utc))
        except Exception:
            pass
    latest = max(dates) if dates else None
    newest_item = max(zip(dates, items), key=lambda pair: pair[0])[1] if dates else (items[0] if items else None)
    return {
        "id": str(show.get("collectionId", "")),
        "podcast": _text(show.get("collectionName", ""), 200),
        "host": _text(owner_name or show.get("artistName", ""), 120),
        "email": EMAIL_RE.search(email).group(0).lower() if email else "",
        "website": (channel.findtext("link") or "").strip(),
        "description": _text(channel.findtext(f"{ITUNES}summary") or channel.findtext("description") or ""),
        "episodes": len(items) or int(show.get("trackCount") or 0),
        "latest_date": latest.date().isoformat() if latest else "",
        "days_since": (datetime.now(timezone.utc) - latest).days if latest else None,
        "latest_title": _text(newest_item.findtext("title") if newest_item is not None else "", 200),
        "apple_url": (show.get("collectionViewUrl") or "").split("?")[0],
        "feed": feed,
        "genre": show.get("primaryGenreName", ""),
        "language": (channel.findtext("language") or "").strip().lower(),
    }


def previously_found(processed_dir: Path) -> set:
    """Emails from podcast lead files that already went through a live run."""
    emails = set()
    for path in processed_dir.glob("Podcasts-*.csv"):
        with open(path, encoding="utf-8-sig", newline="") as f:
            emails |= {(row.get("Public Email") or "").lower() for row in csv.DictReader(f)}
    return emails - {""}


def find(cfg: dict, keywords: list[str], used_emails: set, log) -> tuple[list[dict], dict]:
    settings = cfg["podcasts"]
    skip_domains = [d.lower() for d in settings["skip_email_domains"]]
    shows, seen_ids = [], set()
    searches = [(k, c) for k in keywords for c in settings["countries"]]
    for n, (keyword, country) in enumerate(searches, 1):
        for show in _search(keyword, country, settings["results_per_search"], log):
            if show.get("collectionId") not in seen_ids:
                seen_ids.add(show.get("collectionId"))
                show["_keyword"] = keyword
                shows.append(show)
        if n == 1 or n % 10 == 0 or n == len(searches):
            log(f"Podcast search: {n}/{len(searches)} searches done, {len(shows)} shows so far")
        time.sleep(settings["seconds_between_searches"])

    log(f"Reading {len(shows)} podcast feeds...")
    with ThreadPoolExecutor(12) as pool:
        details = list(pool.map(_read_feed, shows))

    languages = [l.lower() for l in settings.get("languages", [])]
    counts = {"shows": len(shows), "feed unreadable": 0, "other language": 0, "no email": 0, "hosting company email": 0,
              "inactive": 0, "too few episodes": 0, "already in master sheet": 0, "duplicate": 0, "kept": 0}
    kept, seen_emails = [], set()
    for show, info in zip(shows, details):
        if info is None:
            counts["feed unreadable"] += 1
            continue
        email = info["email"]
        domain = email.split("@")[-1]
        if languages and info["language"] and not info["language"].startswith(tuple(languages)):
            counts["other language"] += 1
        elif not email:
            counts["no email"] += 1
        elif any(d in domain for d in skip_domains):
            counts["hosting company email"] += 1
        elif info["days_since"] is None or info["days_since"] > settings["active_days"]:
            counts["inactive"] += 1
        elif info["episodes"] < settings["min_episodes"]:
            counts["too few episodes"] += 1
        elif email in used_emails:
            counts["already in master sheet"] += 1
        elif email in seen_emails:
            counts["duplicate"] += 1
        else:
            seen_emails.add(email)
            info["keyword"] = show["_keyword"]
            kept.append(info)
    counts["kept"] = len(kept)
    kept.sort(key=lambda r: r["days_since"])  # most recently active first
    return kept, counts


def write_lead_file(rows: list[dict], path: Path) -> None:
    """IG Email Extractor layout plus podcast columns, so the dashboard and run.py accept it."""
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=EXPECTED_COLUMNS + EXTRA_COLUMNS)
        writer.writeheader()
        for r in rows:
            bio = f"Podcast host of {r['podcast']} ({r['genre']}). {r['description']}"
            writer.writerow({
                "User Id": f"podcast-{r['id']}", "User Name": f"podcast_{r['id']}", "Full Name": r["host"],
                "Followers Count": "", "Following Count": "", "Post Count": r["episodes"],
                "Public Email": r["email"], "Public Phone": "", "City": "", "Address": "",
                "Is Private": "false", "Is Verified": "false", "Is Business": "true",
                "External Url": r["website"], "Biography": bio[:1500], "Avatar Url": "", "Profile Url": r["apple_url"],
                "Source": "podcast", "Podcast Name": r["podcast"], "Episode Count": r["episodes"],
                "Latest Episode Date": r["latest_date"], "Latest Episode Title": r["latest_title"], "Feed Url": r["feed"],
            })
