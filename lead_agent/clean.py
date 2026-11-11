"""Agent 2 - Clean & Dedupe: normalise emails, remove duplicates, apply hard filters."""
from __future__ import annotations

import csv
import io
import re

import requests

from .common import EMAIL_RE, Lead

OBFUSCATED_AT = re.compile(r"\s*[\[\(\{]\s*at\s*[\]\)\}]\s*", re.I)
OBFUSCATED_DOT = re.compile(r"\s*[\[\(\{]\s*dot\s*[\]\)\}]\s*", re.I)
IG_URL_RE = re.compile(r"instagram\.com/([A-Za-z0-9._]+)", re.I)


def normalise_email(raw: str) -> str:
    text = OBFUSCATED_DOT.sub(".", OBFUSCATED_AT.sub("@", raw or ""))
    match = EMAIL_RE.search(text)
    return match.group(0).lower().strip(".") if match else ""


def email_from_bio(bio: str) -> str:
    return normalise_email(bio)


def load_master_sheet(cfg: dict) -> tuple[set, set]:
    """Download the Cold Email tab (public CSV export) and return (emails, usernames) already used."""
    sheet = cfg["master_sheet"]
    response = requests.get(sheet["csv_export_url"], timeout=60)
    response.raise_for_status()
    rows = csv.reader(io.StringIO(response.content.decode("utf-8-sig")))
    emails, usernames = set(), set()
    for row in rows:
        for cell in row:  # emails appear in several side blocks, so scan every cell
            for match in EMAIL_RE.findall(cell):
                emails.add(match.lower())
            for match in IG_URL_RE.findall(cell):  # newer rows store the profile URL, not the username
                usernames.add(match.lower())
        idx = sheet["username_column"]
        if len(row) > idx and row[idx].strip():
            usernames.add(row[idx].strip().lstrip("@").lower())
    return emails, usernames


def keyword_pattern(words: list[str]) -> re.Pattern:
    """Whole-word match, so 'pr' does not hit 'product' and 'dr' does not hit 'drink'."""
    # a hyphen or space in a keyword matches either, so "makeup-artist" also hits "makeup artist"
    parts = sorted({re.escape(w).replace(r"\-", "[-\s]?").replace(r"\ ", "[-\s]") for w in words}, key=len, reverse=True)
    return re.compile(r"(?<![a-z0-9])(" + "|".join(parts) + r")(?![a-z0-9])", re.I)


def matched_keywords(lead: Lead, pattern: re.Pattern) -> list[str]:
    text = f"{lead.full_name} {lead.biography} {re.sub(r'[._]', ' ', lead.username)}"
    return sorted({m.lower() for m in pattern.findall(text)})


def clean(leads: list[Lead], cfg: dict, used_emails: set, used_usernames: set) -> list[Lead]:
    filters = cfg["filters"]
    reject_words = [w.lower() for w in filters["reject_bio_keywords"]]
    include = keyword_pattern([w for group in cfg["include_bio_keywords"].values() for w in group])
    seen_emails, seen_users = set(), set()
    # "email" follows the team's sheet rule; "email_and_username" also skips accounts already contacted on another email
    check_usernames = cfg["master_sheet"].get("dedupe_by", "email") == "email_and_username"

    for lead in leads:
        lead.email = normalise_email(lead.email)
        if not lead.email:
            from_bio = email_from_bio(lead.biography)
            if from_bio:
                lead.email, lead.email_source = from_bio, "bio"

        bio = lead.biography.lower()
        if check_usernames and lead.username in used_usernames:
            lead.reject("already in master sheet (username)")
        elif lead.email and lead.email in used_emails:
            lead.reject("already in master sheet (email)")
        elif lead.username in seen_users or (lead.email and lead.email in seen_emails):
            lead.reject("duplicate within this batch")
        elif lead.source != "podcast" and filters["skip_private"] and lead.is_private:
            lead.reject("private account")
        elif lead.source != "podcast" and lead.followers < filters["min_followers"]:
            lead.reject(f"followers below {filters['min_followers']}")
        elif lead.source != "podcast" and lead.followers > filters["max_followers"]:
            lead.reject(f"followers above {filters['max_followers']}")
        elif any(word in bio for word in reject_words):
            lead.reject("bio matches excluded type (agency / fan page / competitor)")
        elif cfg["include_keywords_required"] and not matched_keywords(lead, include):
            lead.reject("no target keyword in name or bio")
        else:
            lead.status = "Clean"

        seen_users.add(lead.username)
        if lead.email:
            seen_emails.add(lead.email)
    return leads


def recheck_emails(leads: list[Lead], used_emails: set) -> None:
    """Emails found on websites were not known at clean time; drop the ones already in the master sheet."""
    seen = set()
    for lead in leads:
        if lead.rejected or not lead.email:
            continue
        if lead.email in used_emails:
            lead.reject("already in master sheet (email)")
        elif lead.email in seen:
            lead.reject("duplicate within this batch")
        seen.add(lead.email)
