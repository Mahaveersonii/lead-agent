"""Shared lead record, config and .env loading."""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")


@dataclass
class Lead:
    user_id: str
    username: str
    full_name: str
    first_name: str
    followers: int
    email: str
    phone: str
    website: str
    biography: str
    city: str
    is_private: bool
    is_business: bool
    is_verified: bool
    profile_url: str
    source_file: str
    email_source: str = "ig_contact"
    status: str = "New"
    reason: str = ""
    niche: str = ""
    fit_score: Optional[int] = None
    fit_reason: str = ""
    tier: str = ""
    verification: str = ""
    personalization: str = ""
    notes: list = field(default_factory=list)

    def reject(self, reason: str) -> None:
        self.status = "Rejected"
        self.reason = reason

    @property
    def rejected(self) -> bool:
        return self.status == "Rejected"

    def to_row(self) -> dict:
        row = asdict(self)
        row["notes"] = "; ".join(self.notes)
        return row


def load_config() -> dict:
    """Read config.json; the master sheet ID comes from .env so it never lands in git."""
    with open(ROOT / "config.json", encoding="utf-8") as f:
        cfg = json.load(f)
    sheet = cfg["master_sheet"]
    sheet_id = os.environ.get("MASTER_SHEET_ID", "")
    sheet["spreadsheet_id"] = sheet_id
    sheet["csv_export_url"] = sheet["csv_export_url"].format(sheet_id=sheet_id, gid=sheet["worksheet_gid"])
    return cfg


def load_env() -> None:
    """Load KEY=value lines from .env into the environment (existing vars win)."""
    path = ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip().strip('"').strip("'")
        if value:
            os.environ.setdefault(key.strip(), value)
