"""Agent 3 - Website Email Finder: for leads without an email, read their own public website."""
from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

import requests

from .common import EMAIL_RE, Lead

SKIP_HOSTS = (
    "instagram.com", "facebook.com", "fb.me", "youtube.com", "youtu.be", "wa.me", "whatsapp.com",
    "t.me", "twitter.com", "x.com", "tiktok.com", "linkedin.com", "threads.net", "spotify.com",
    "apple.com", "amzn.to", "amazon.", "bit.ly",
)
IGNORE_EMAIL_PARTS = ("example.", "sentry", "wixpress", "domain.com", "@2x", ".png", ".jpg", ".webp", "godaddy")
MAILTO_RE = re.compile(r"mailto:([^\"'?>\s]+)", re.I)
HEADERS = {"User-Agent": "Mozilla/5.0 (contact-email lookup; respects robots)"}


def _candidate_emails(html: str) -> list[str]:
    found = [m.lower() for m in MAILTO_RE.findall(html)] + [m.lower() for m in EMAIL_RE.findall(html)]
    clean = []
    for email in found:
        email = email.strip(".")
        if any(part in email for part in IGNORE_EMAIL_PARTS) or email in clean:
            continue
        clean.append(email)
    return clean


def _pick(emails: list[str], site_host: str) -> str:
    """Prefer an address on the site's own domain, then personal-looking ones, then anything."""
    host = site_host.removeprefix("www.")
    own = [e for e in emails if e.split("@")[1].endswith(host)]
    return (own or emails)[0] if emails else ""


def find_email(lead: Lead, cfg: dict) -> None:
    settings = cfg["website_finder"]
    url = lead.website
    if not url:
        return
    if not url.startswith("http"):
        url = "https://" + url
    host = urlparse(url).netloc.lower()
    if not host or any(skip in host for skip in SKIP_HOSTS):
        return
    for page in settings["pages"]:
        target = urljoin(url if url.endswith("/") else url + "/", page.lstrip("/")) if page else url
        try:
            response = requests.get(target, headers=HEADERS, timeout=settings["timeout_seconds"])
        except requests.RequestException:
            continue
        if response.status_code != 200 or "text/html" not in response.headers.get("content-type", ""):
            continue
        email = _pick(_candidate_emails(response.text[:500_000]), urlparse(response.url).netloc.lower())
        if email:
            lead.email, lead.email_source = email, f"website ({target})"
            return


def run(leads: list[Lead], cfg: dict) -> None:
    if not cfg["website_finder"]["enabled"]:
        return
    for lead in leads:
        if not lead.rejected and not lead.email:
            find_email(lead, cfg)
            if not lead.email:
                lead.reject("no email found (profile, bio or website)")
