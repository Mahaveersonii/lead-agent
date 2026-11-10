"""Agent 4 - Fit Scorer: local Qwen3 8B (Ollama) rates personal-branding fit 0-10. Free, data stays local."""
from __future__ import annotations

import json
import re

import requests

from .common import Lead, progress

PROMPT = """You qualify Instagram leads for a PERSONAL BRANDING agency.
Good leads are experts, practitioners and small businesses in the target niches who sell
something: coaching, consulting, therapy, classes, treatments, professional services or their own
products. Solo experts and small clinics, studios and practices both count.

Target niches: {niches}

Reject: marketing or personal-branding agencies (our competitors), large corporations,
fan/meme/news/quote pages, and accounts with nothing to sell.

Lead:
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
    text = f"{lead.biography} {lead.full_name}".lower()
    for niche in niches:
        head = niche.split()[0].rstrip("'s")
        if niche in text or (len(head) > 4 and head in text):
            return niche
    return ""


def _ask_ollama(lead: Lead, cfg: dict) -> dict:
    scoring = cfg["scoring"]
    prompt = PROMPT.format(
        niches=", ".join(cfg["target_niches"]), name=lead.full_name, username=lead.username,
        followers=lead.followers, business=lead.is_business, website=lead.website or "none",
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


def run(leads: list[Lead], cfg: dict, use_llm: bool = True) -> None:
    scoring = cfg["scoring"]
    todo = [lead for lead in leads if not lead.rejected]
    for done, lead in enumerate(todo, 1):
        progress("AI fit", done, len(todo))
        keyword = _keyword_niche(lead, cfg["target_niches"])
        if use_llm and scoring["use_local_llm"]:
            try:
                result = _ask_ollama(lead, cfg)
            except requests.ConnectionError:
                raise SystemExit("Ollama stopped responding. Restart the Ollama app and run again.")
            except (requests.RequestException, ValueError, KeyError) as error:
                lead.notes.append(f"LLM scoring failed, used keywords: {error}")
                result = {"score": 7 if keyword else 4, "niche": keyword or "other", "reason": "keyword match only"}
        else:
            result = {"score": 7 if keyword else 4, "niche": keyword or "other", "reason": "keyword match only"}

        lead.fit_score, lead.niche, lead.fit_reason = result["score"], result["niche"], result["reason"]
        if "first_name" in result:  # the model reads names better; accept only a whole word from the name or bio
            name = result["first_name"]
            lead.first_name = name if name and len(name.split()) == 1 and name.lower() in re.findall(r"\w+", f"{lead.full_name} {lead.biography}".lower()) else ""
        if lead.fit_score < scoring["min_score"]:
            lead.reject(f"low fit score {lead.fit_score}: {lead.fit_reason}")
        elif scoring["require_person"] and not result.get("is_person", True):
            lead.reject(f"business page, not a person: {lead.fit_reason}")
        elif scoring["reject_other_niche"] and lead.niche.lower() in ("", "other"):
            lead.reject("niche not in target list")
        else:
            lead.status = "Scored"
            lead.tier = "A" if lead.fit_score >= scoring["tier_a_score"] else "B"
