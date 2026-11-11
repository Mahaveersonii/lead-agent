"""Agents 6 + 7 - Personaliser and Quality Check: local Qwen3 (Ollama) writes and reviews a first line."""
from __future__ import annotations

import json
import random
import re

import requests

from .common import Lead, progress

WRITE_PROMPT = """Write the FIRST LINE of a cold email to an Instagram creator.
The rest of the email (written by us) pitches personal branding services, so do NOT pitch anything.

Rules:
- One sentence, 12 to 25 words, plain conversational English, like a real person typing.
- Mention ONE concrete detail that is written in their bio (what they help with, who they serve, their method or offer).
- Use ONLY facts written in the bio. Never invent audiences, results, places or numbers, and never
  describe their posts, videos or content, because you have not seen them.
- Never talk about yourself, your focus or personal branding, and do not judge their work ("looks effective").
- No greeting, no name at the start, no emojis, no exclamation marks, no hashtags, no follower counts.
- Never use these words: resonate, resonates, holistic, journey, deeply, truly, inspiring, passion.
- Do not start with "Your focus on". Do not use "I came across your profile" or "I love your content".

Start the sentence with: "{opener}"

Good examples (style only, do not copy the facts or the openings):
- Bio "Postpartum PT | rebuild your core after birth | 1:1 online coaching" ->
  "Saw that you coach new mums one to one online on rebuilding their core after birth, which is such a specific and needed niche."
- Bio "Tarot + career clarity readings for women in tech" ->
  "Tarot readings aimed specifically at career clarity for women in tech is a combination I have not seen before."

Creator:
- Name: {name}
- Niche: {niche}
- Bio: {bio}

Reply ONLY with JSON: {{"line": "<the sentence>"}}"""

OPENERS = ["Saw that", "Noticed you", "Really like that you", "Just read that you", "Love how you",
           "It is not every day I see", "Came across your work on", "Your bio mentions"]

PODCAST_WRITE_PROMPT = """Write the FIRST LINE of a cold email to a podcast host.
The rest of the email (written by us) pitches personal branding services, so do NOT pitch anything.

Rules:
- One sentence, 12 to 25 words, plain conversational English, like a real person typing.
- Mention ONE concrete detail: the topic of their latest episode, or what their podcast helps listeners with.
- Use ONLY facts written below. Never invent audiences, results, places or numbers.
- Do not claim you listened to an episode. Say you saw or came across it, never that you heard or listened.
- Never talk about yourself, your focus or personal branding, and do not judge their work.
- No greeting, no name at the start, no emojis, no exclamation marks, no hashtags.
- Never use these words: resonate, resonates, holistic, journey, deeply, truly, inspiring, passion.

Good examples (style only, do not copy the facts):
- Latest episode "Negotiating your first coaching contract" ->
  "Saw your recent episode on negotiating a first coaching contract, which is a question most new coaches get wrong."
- Podcast about career changes for nurses ->
  "Came across your podcast on helping nurses move into new careers, a niche I had not seen covered before."

Host:
- Name: {name}
- Podcast: {podcast}
- Niche: {niche}
- Latest episode title: {episode}
- About the podcast: {bio}

Reply ONLY with JSON: {{"line": "<the sentence>"}}"""

CHECK_PROMPT = """You review a cold-email first line before it is sent.

Creator bio (for podcast hosts: podcast description and latest episode): {bio}
Creator niche: {niche}
First line: "{line}"

Reject it if ANY is true: it misreads the bio (for example treats a personal detail as a service),
it is grammatically awkward, it mentions anything (audience, result, place, posts, content) that is
not written in the bio, it sounds fake or over-flattering, it talks about the sender, it pitches a
service, it is not one natural sentence, or it could offend.

Reply ONLY with JSON: {{"ok": true or false, "reason": "<max 10 words>"}}"""

BANNED = ("came across your profile", "hope this finds you", "love your content", "!", "#", "followers",
          "resonat", "holistic", "journey", "deeply", "truly", "inspiring", "passion", "your focus on",
          "personal brand", "my focus", "your posts", "your content", "your videos", "looks really")
EMOJI_RE = re.compile("[\U0001F300-\U0001FAFF☀-➿]")


def _ollama(prompt: str, model: str, cfg: dict, max_tokens: int) -> dict:
    response = requests.post(cfg["personalisation"]["ollama_url"], timeout=300, json={
        "model": model, "prompt": prompt, "stream": False,
        "format": "json", "think": False, "options": {"num_predict": max_tokens, "temperature": 0.7},
    })
    response.raise_for_status()
    return json.loads(response.json()["response"])


def rule_problems(line: str) -> str:
    words = len(line.split())
    if not 8 <= words <= 30:
        return f"length {words} words"
    if EMOJI_RE.search(line):
        return "contains emoji"
    lowered = line.lower()
    for phrase in BANNED:
        if phrase in lowered:
            return f"banned phrase '{phrase}'"
    return ""


def fallback_line(lead: Lead, cfg: dict) -> str:
    niche = lead.niche if lead.niche and lead.niche != "other" else "your space"
    settings = cfg["personalisation"]
    template = settings.get("podcast_fallback_line", settings["fallback_line"]) if lead.source == "podcast" else settings["fallback_line"]
    return template.format(niche=niche)


def personalise(lead: Lead, cfg: dict) -> None:
    settings = cfg["personalisation"]
    bio = lead.biography.replace("\n", " ")[:600] or "(empty)"
    for _ in range(2):  # one retry if the checker rejects the first draft
        if lead.source == "podcast":
            prompt = PODCAST_WRITE_PROMPT.format(name=lead.full_name, podcast=lead.podcast, niche=lead.niche,
                                                 episode=lead.latest_episode or "(unknown)", bio=bio)
        else:
            prompt = WRITE_PROMPT.format(name=lead.full_name, niche=lead.niche, bio=bio, opener=random.choice(OPENERS))
        line = str(_ollama(prompt,
                           settings["writer_model"], cfg, 80).get("line", "")).strip().strip('"')
        problem = rule_problems(line)
        if not problem:
            facts = f"{bio} Latest episode: {lead.latest_episode}" if lead.source == "podcast" else bio
            review = _ollama(CHECK_PROMPT.format(bio=facts, niche=lead.niche, line=line),
                             settings["checker_model"], cfg, 40)
            if review.get("ok") is True:
                lead.personalization = line if line.endswith((".", "?")) else line + "."
                return
            problem = f"checker: {review.get('reason', 'rejected')}"
        lead.notes.append(f"first line rejected ({problem}): {line}")
    lead.personalization = fallback_line(lead, cfg)
    lead.notes.append("used fallback first line")


def run(leads: list[Lead], cfg: dict, use_llm: bool = True) -> None:
    if not cfg["personalisation"]["enabled"]:
        return
    todo = [lead for lead in leads if not lead.rejected]
    for done, lead in enumerate(todo, 1):
        progress("First lines", done, len(todo))
        if not use_llm:
            lead.personalization = fallback_line(lead, cfg)
            continue
        try:
            personalise(lead, cfg)
        except requests.ConnectionError:
            raise SystemExit("Ollama stopped responding. Restart the Ollama app and run again.")
        except (requests.RequestException, ValueError, KeyError) as error:
            lead.personalization = fallback_line(lead, cfg)
            lead.notes.append(f"LLM personalisation failed, used fallback: {error}")
