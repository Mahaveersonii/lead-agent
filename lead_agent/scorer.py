"""Agent 4 - Fit Scorer. KEEP leads (from the keyword rules) pass straight through with no AI call.
MAYBE leads get a second look from the local Qwen3 8B (Ollama); the ones it doesn't approve go to the
review file instead of being deleted."""
from __future__ import annotations

import json
from datetime import datetime
import re

import requests

from .classifier import Classifier
from .common import Lead, keyword_pattern, progress

PROMPT = """You qualify leads (Instagram accounts or podcast hosts) for a PERSONAL BRANDING agency.
Good leads are experts, practitioners and small businesses in the target niches who sell
something: coaching, consulting, therapy, classes, treatments, professional services or their own
products. Solo experts and small clinics, studios and practices both count.

Target niches: {niches}

Reject: marketing or personal-branding agencies (our competitors), large corporations,
fan/meme/news/quote pages, and accounts with nothing to sell. For podcast hosts, also reject
media companies, networks and news, sports or entertainment shows.

Lead:
- Source: {source}
- Name: {name}
- Username: @{username}
- Followers: {followers}
- Business account: {business}
- Website: {website}
- Bio: {bio}

Reply ONLY with JSON:
{{"score": <0-10 integer>, "niche": "<closest target niche, or 'other' if none fits>",
  "is_person": <true if the account is run by one named individual, false for clinics, studios, brands, schools>,
  "first_name": "<the individual's real first name if you can see it in the name, username or bio, else empty>",
  "reason": "<max 15 words>"}}
Scoring: 9-10 clear target niche + sells a service (booking link/program); 6-8 likely fit;
3-5 unclear; 0-2 not a fit."""


def _keyword_niche(lead: Lead, niches: list[str]) -> str:
    """The target niche named in the bio or display name (whole phrase), or "" when none is."""
    match = keyword_pattern(niches).search(f"{lead.full_name} {lead.biography}")
    return match.group(0).lower() if match else ""


def _ask_ollama(lead: Lead, cfg: dict) -> dict:
    scoring = cfg["scoring"]
    prompt = PROMPT.format(
        niches=", ".join(cfg["target_niches"]), name=lead.full_name, username=lead.username,
        source=f'podcast host of "{lead.podcast}"' if lead.source == "podcast" else "Instagram account",
        followers="unknown (podcast)" if lead.source == "podcast" else lead.followers, business=lead.is_business, website=lead.website or "none",
        bio=lead.biography.replace("\n", " ")[:600] or "(empty)",
    )
    response = requests.post(scoring["ollama_url"], timeout=300, json={
        "model": scoring["ollama_model"], "prompt": prompt, "stream": False,
        "format": "json", "think": False, "options": {"num_predict": 120},
    })
    response.raise_for_status()
    data = json.loads(response.json()["response"])
    return {"score": max(0, min(10, int(data.get("score", 0)))),
            "niche": str(data.get("niche", "")), "reason": str(data.get("reason", "")),
            "is_person": data.get("is_person") is not False, "first_name": str(data.get("first_name", "")).strip()}


def _accept(lead: Lead, cfg: dict, score: int, niche: str, reason: str) -> None:
    scoring = cfg["scoring"]
    lead.fit_score, lead.niche, lead.fit_reason = score, niche, reason
    lead.status = "Scored"
    lead.tier = "A" if score >= scoring["tier_a_score"] else "B"


def run(leads: list[Lead], cfg: dict, use_llm: bool = True) -> None:
    scoring = cfg["scoring"]
    classifier = Classifier(cfg)
    todo = [lead for lead in leads if not lead.rejected]
    keep = [lead for lead in todo if lead.decision == "KEEP"]
    maybe = [lead for lead in todo if lead.decision != "KEEP"]
    ai_on = use_llm and scoring["use_local_llm"] and cfg["classification"]["ai_reviews_maybe"]
    print(f"[{datetime.now():%H:%M:%S}] Keyword rules: {len(keep)} KEEP (no AI needed), {len(maybe)} MAYBE"
          + (" (the AI checks these)" if ai_on and maybe else " (go to the review file)" if maybe else ""), flush=True)

    for lead in keep:
        score = min(10, max(scoring["min_score"], lead.rule_score or 0))
        niche = _keyword_niche(lead, cfg["target_niches"]) or lead.industry
        classifier.tidy_first_name(lead)
        _accept(lead, cfg, score, niche, lead.rule_reason)

    for done, lead in enumerate(maybe, 1):
        if not ai_on:
            lead.reject("MAYBE: needs a human look (see the review file)")
            continue
        progress("AI check of MAYBE leads", done, len(maybe))
        try:
            result = _ask_ollama(lead, cfg)
        except requests.ConnectionError:
            raise SystemExit("Ollama stopped responding. Restart the Ollama app and run again.")
        except (requests.RequestException, ValueError, KeyError) as error:
            lead.notes.append(f"AI check failed: {error}")
            lead.reject("MAYBE: AI check failed (see the review file)")
            continue

        name = result["first_name"]  # the model reads names better; accept only a whole word from the name or bio
        lead.first_name = name if name and len(name.split()) == 1 and name.lower() in re.findall(r"\w+", f"{lead.full_name} {lead.biography}".lower()) else ""
        lead.fit_score, lead.fit_reason = result["score"], result["reason"]
        if result["score"] < scoring["min_score"]:
            lead.reject(f"MAYBE: AI score {result['score']}: {result['reason']}")
        elif scoring["require_person"] and not result["is_person"]:
            lead.reject(f"MAYBE: business page, not a person: {result['reason']}")
        elif scoring["reject_other_niche"] and result["niche"].lower() in ("", "other"):
            lead.reject("MAYBE: AI found no target niche")
        else:
            lead.decision = "KEEP (AI)"
            _accept(lead, cfg, result["score"], result["niche"], result["reason"])
