"""Agent 8 - Sender: add the final leads to the newest Draft "(New-mails)" campaign in Instantly."""
from __future__ import annotations

import os
from datetime import datetime, timezone

import requests

from .common import Lead


class NoCampaign(RuntimeError):
    pass


def _headers() -> dict:
    return {"Authorization": f"Bearer {os.environ['INSTANTLY_API_KEY']}"}


def list_campaigns(cfg: dict) -> list[dict]:
    base, items, after = cfg["instantly"]["api_base"], [], None
    while True:
        params = {"limit": 100, **({"starting_after": after} if after else {})}
        response = requests.get(f"{base}/api/v2/campaigns", params=params, headers=_headers(), timeout=30)
        response.raise_for_status()
        data = response.json()
        items += data.get("items", [])
        after = data.get("next_starting_after")
        if not after or not data.get("items"):
            return items


def pick_campaign(cfg: dict) -> dict:
    """Newest campaign matching the name marker; it must be a Draft created recently."""
    settings = cfg["instantly"]
    matches = [c for c in list_campaigns(cfg) if settings["campaign_name_contains"].lower() in c["name"].lower()]
    if not matches:
        raise NoCampaign(f'No campaign name contains "{settings["campaign_name_contains"]}".')
    newest = max(matches, key=lambda c: c.get("timestamp_created", ""))
    created = datetime.fromisoformat(newest["timestamp_created"].replace("Z", "+00:00"))
    age_hours = (datetime.now(timezone.utc) - created).total_seconds() / 3600
    if settings["campaign_must_be_draft"] and newest.get("status") != 0:
        raise NoCampaign(f'Newest campaign "{newest["name"]}" is already started or finished. '
                         "Duplicate a new campaign first, then run again.")
    if age_hours > settings["campaign_max_age_hours"]:
        raise NoCampaign(f'Newest campaign "{newest["name"]}" was created {age_hours:.0f} hours ago. '
                         "Duplicate a new campaign first, then run again.")
    return newest


def _payload(lead: Lead, cfg: dict) -> dict:
    return {
        "email": lead.email,
        "first_name": lead.first_name or cfg["first_name_fallback"],
        "personalization": lead.personalization,
        "website": lead.website,
        "company_name": lead.full_name,
        "custom_variables": {"niche": lead.niche, "instagram": lead.profile_url, "tier": lead.tier},
    }


def run(leads: list[Lead], cfg: dict, campaign: dict, dry_run: bool = True) -> dict:
    settings = cfg["instantly"]
    ready = [lead for lead in leads if not lead.rejected]
    summary = {"campaign": campaign["name"], "ready": len(ready), "uploaded": 0, "duplicates": 0, "blocklisted": 0}
    if dry_run:
        for lead in ready:
            lead.status = "Ready (dry run)"
        return summary
    for start in range(0, len(ready), settings["batch_size"]):
        batch = ready[start:start + settings["batch_size"]]
        response = requests.post(f"{settings['api_base']}/api/v2/leads/add", headers=_headers(), timeout=120, json={
            "campaign_id": campaign["id"],
            "skip_if_in_workspace": settings["skip_if_in_workspace"],
            "leads": [_payload(lead, cfg) for lead in batch],
        })
        response.raise_for_status()
        data = response.json()
        summary["uploaded"] += int(data.get("leads_uploaded", 0))
        summary["duplicates"] += int(data.get("duplicated_leads", 0))
        summary["blocklisted"] += int(data.get("in_blocklist", 0))
        created = {item["index"] for item in data.get("created_leads", [])}  # index = position in this batch
        for i, lead in enumerate(batch):
            if i in created:
                lead.status = "Sent"
            else:
                lead.reject("Instantly skipped it (already in workspace, blocklisted or invalid)")
    return summary
