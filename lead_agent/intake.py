"""Agent 1 - Intake: read IG Email Extractor CSV exports from Leads/Incoming."""
from __future__ import annotations

import csv
import re
import unicodedata
from pathlib import Path

from .common import Lead

EXPECTED_COLUMNS = [
    "User Id", "User Name", "Full Name", "Followers Count", "Following Count", "Post Count",
    "Public Email", "Public Phone", "City", "Address", "Is Private", "Is Verified", "Is Business",
    "External Url", "Biography", "Avatar Url", "Profile Url",
]
TITLES = {"dr", "dr.", "mr", "mr.", "mrs", "mrs.", "ms", "ms.", "coach", "the"}


def _bool(value: str) -> bool:
    return str(value).strip().lower() in {"true", "yes", "1"}


def _int(value: str) -> int:
    try:
        return int(float(str(value).replace(",", "").strip() or 0))
    except ValueError:
        return 0


def first_name_from(full_name: str) -> str:
    """Best-effort first name: drop emojis, titles and anything after | or -."""
    text = "".join(ch for ch in full_name if unicodedata.category(ch)[0] in "LZP" or ch in " .'-")
    text = re.split(r"[|,•·\-–—/]", text)[0].strip()
    words = [w for w in text.split() if w.lower() not in TITLES]
    if not words:
        return ""
    word = words[0].strip(".'")
    return word.capitalize() if word.isupper() or word.islower() else word


def _podcast_fields(row: dict) -> dict:
    """Extra columns written by the Podcast finder; Instagram exports don't have them."""
    if (row.get("Source") or "").strip().lower() != "podcast":
        return {}
    return {"source": "podcast", "email_source": "podcast_feed", "podcast": (row.get("Podcast Name") or "").strip(),
            "latest_episode": (row.get("Latest Episode Title") or "").strip()}


def find_new_files(incoming: Path) -> list[Path]:
    return sorted(p for p in incoming.glob("*.csv") if p.is_file())


def read_file(path: Path) -> list[Lead]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        missing = [c for c in EXPECTED_COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"{path.name} is missing IG Email Extractor columns: {', '.join(missing)}")
        leads = []
        for row in reader:
            full_name = (row["Full Name"] or "").strip()
            leads.append(Lead(
                user_id=(row["User Id"] or "").strip(),
                username=(row["User Name"] or "").strip().lstrip("@").lower(),
                full_name=full_name,
                first_name=first_name_from(full_name),
                followers=_int(row["Followers Count"]),
                email=(row["Public Email"] or "").strip(),
                phone=(row["Public Phone"] or "").strip(),
                website=(row["External Url"] or "").strip(),
                biography=(row["Biography"] or "").strip(),
                city=(row["City"] or "").strip(),
                is_private=_bool(row["Is Private"]),
                is_business=_bool(row["Is Business"]),
                is_verified=_bool(row["Is Verified"]),
                profile_url=(row["Profile Url"] or "").strip(),
                source_file=path.name,
                **_podcast_fields(row),
            ))
        return leads
