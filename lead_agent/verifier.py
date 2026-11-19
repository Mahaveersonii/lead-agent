"""Agent 5 - Email Verifier: check each email with the Bouncify single-validation API."""
from __future__ import annotations

import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

import requests

from .common import ROOT, Lead, progress

CACHE_FILE = ROOT / "output" / "verify_cache.json"
CACHE_DAYS = 30                                   # a result older than this is checked again
CACHEABLE = {"deliverable", "undeliverable"}      # clear answers only; unknown/accept-all are re-checked
WORKERS = 4                                       # emails checked at the same time


class OutOfCredits(RuntimeError):
    pass


def _say(message: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {message}", flush=True)


def credits_remaining() -> int:
    for attempt in range(3):
        try:
            response = requests.get("https://api.bouncify.io/v1/info",
                                    params={"apikey": os.environ["BOUNCIFY_API_KEY"]}, timeout=30)
            response.raise_for_status()
            return int(response.json()["credits_info"]["credits_remaining"])
        except (requests.ConnectionError, requests.Timeout):
            if attempt == 2:
                raise
            time.sleep(5 * (attempt + 1))


class _Throttle:
    """Keeps all threads together under the requests-per-minute limit."""

    def __init__(self, per_minute: int):
        self.gap, self.next_at, self.lock = 60 / per_minute, 0.0, threading.Lock()

    def wait(self) -> None:
        with self.lock:
            now = time.monotonic()
            start = max(now, self.next_at)
            self.next_at = start + self.gap
        time.sleep(max(0.0, start - now))


def verify(email: str, cfg: dict, throttle: _Throttle | None = None) -> str:
    """Return Bouncify's result: deliverable, undeliverable, accept-all, unknown or error."""
    settings = cfg["verification"]
    for attempt in range(4):
        if throttle:
            throttle.wait()
        try:
            # 10 s to connect, 60 s for the answer: a slow mail server must not hold the whole run
            response = requests.get(settings["api_url"], timeout=(10, 60), params={
                "apikey": os.environ["BOUNCIFY_API_KEY"], "email": email,
            })
        except (requests.ConnectionError, requests.Timeout):
            time.sleep(5 * (attempt + 1))
            continue
        if response.status_code == 402:
            raise OutOfCredits("Bouncify: insufficient verification credits. Top up at bouncify.io")
        if response.status_code == 429 or response.status_code >= 500:
            wait = 20 * (attempt + 1)
            _say(f"Bouncify is busy (HTTP {response.status_code}), waiting {wait} s and trying again")
            time.sleep(wait)
            continue
        response.raise_for_status()
        return str(response.json().get("result", "unknown")).lower().replace(" ", "-")
    return "error"


def _load_cache() -> dict:
    try:
        cache = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    cutoff = (datetime.now() - timedelta(days=CACHE_DAYS)).isoformat()
    return {email: entry for email, entry in cache.items() if entry.get("checked", "") >= cutoff}


def _save_cache(cache: dict) -> None:
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(json.dumps(cache, indent=0), encoding="utf-8")


def run(leads: list[Lead], cfg: dict, enabled: bool = True) -> None:
    settings = cfg["verification"]
    allowed = set(settings["send_results"]) | ({"accept-all"} if settings["send_accept_all"] else set())
    todo = [lead for lead in leads if not lead.rejected]
    if not enabled:
        for lead in todo:
            lead.verification = "not checked (dry run)"
        return

    cache = _load_cache()
    to_check = []
    for lead in todo:
        hit = cache.get(lead.email.lower())
        if hit:
            lead.verification = hit["result"]
        else:
            to_check.append(lead)
    _say(f"Bouncify: {len(todo)} emails, {len(todo) - len(to_check)} already checked in the last "
         f"{CACHE_DAYS} days (no credits used), {len(to_check)} to check now")

    if to_check:
        credits = credits_remaining()
        if credits < len(to_check):
            raise OutOfCredits(f"Bouncify: {credits} credits left but {len(to_check)} emails to check. "
                               "Top up at bouncify.io or run a smaller file")

    throttle, done, stop = _Throttle(settings["requests_per_minute"]), 0, None
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(verify, lead.email, cfg, throttle): lead for lead in to_check}
        for future in as_completed(futures):
            lead = futures[future]
            try:
                lead.verification = future.result()
            except OutOfCredits as error:
                stop = error
                lead.verification = "error"
            except requests.RequestException as error:
                lead.verification = "error"
                lead.notes.append(f"Bouncify error: {error}")
            if lead.verification in CACHEABLE:
                cache[lead.email.lower()] = {"result": lead.verification, "checked": datetime.now().isoformat()}
            done += 1
            progress("Email check (Bouncify)", done, len(to_check))
            if stop:
                for pending in futures:
                    pending.cancel()
    _save_cache(cache)
    if stop:
        raise stop

    for lead in todo:
        if lead.verification not in allowed:
            lead.reject(f"email verification: {lead.verification}"
                        + (" (network problem, will be checked again next run)" if lead.verification == "error" else ""))
        else:
            lead.status = "Verified"
