"""Agent 5 - Email Verifier: check each email with the Bouncify single-validation API."""
from __future__ import annotations

import os
import time

import requests

from .common import Lead


class OutOfCredits(RuntimeError):
    pass


def credits_remaining() -> int:
    response = requests.get("https://api.bouncify.io/v1/info",
                            params={"apikey": os.environ["BOUNCIFY_API_KEY"]}, timeout=30)
    response.raise_for_status()
    return int(response.json()["credits_info"]["credits_remaining"])


def verify(email: str, cfg: dict) -> str:
    """Return Bouncify's result: deliverable, undeliverable, accept-all or unknown."""
    settings = cfg["verification"]
    for attempt in range(3):
        response = requests.get(settings["api_url"], timeout=200, params={
            "apikey": os.environ["BOUNCIFY_API_KEY"], "email": email,
        })
        if response.status_code == 429:  # rate limited: wait and retry
            time.sleep(30 * (attempt + 1))
            continue
        if response.status_code == 402:
            raise OutOfCredits("Bouncify: insufficient verification credits")
        response.raise_for_status()
        return str(response.json().get("result", "unknown")).lower().replace(" ", "-")
    return "unknown"


def run(leads: list[Lead], cfg: dict, enabled: bool = True) -> None:
    settings = cfg["verification"]
    allowed = set(settings["send_results"]) | ({"accept-all"} if settings["send_accept_all"] else set())
    pause = 60 / settings["requests_per_minute"]
    for lead in leads:
        if lead.rejected:
            continue
        if not enabled:
            lead.verification = "not checked (dry run)"
            continue
        try:
            lead.verification = verify(lead.email, cfg)
        except requests.RequestException as error:
            lead.verification = "error"
            lead.notes.append(f"Bouncify error: {error}")
        time.sleep(pause)
        if lead.verification not in allowed:
            lead.reject(f"email verification: {lead.verification}")
        else:
            lead.status = "Verified"
