"""Agent 2b - Lead Classifier: KEEP / MAYBE / REMOVE from keyword signals, with no AI.

Every lead is scored on its bio, display name, username and Instagram category, using the word lists
in config.json -> classification. Python does the exact matching (whole words, caps, special cases),
so it is instant and gives the same answer every time. Only MAYBE leads go to the AI for a second look.
"""
from __future__ import annotations

import re
import unicodedata

from .common import Lead, keyword_pattern

# "dr" alone matches too much (drive, DR Congo, diastasis recti), so it only counts before a name
DR_TEXT = re.compile(r"(?<![A-Za-z])(?:Dr\.?|DR\.|dr\.)\s*[A-Z][a-z]+|(?<![A-Za-z])dr\.\s*[a-z]+")
DR_USERNAME = re.compile(r"^dr[._]")
MD_TEXT = re.compile(r"(?<![A-Za-z])M\.?D(?:\.|(?![A-Za-z]))")  # capital MD or M.D., never "md" inside words
BUSINESS_NAME = re.compile(r"(?<![a-z])(clinic|studio|academy|institute|company|pvt|ltd|llc|centre|center|salon|hospital|"
                           r"foundation|official)(?![a-z])", re.I)


def _plain(text: str) -> str:
    return unicodedata.normalize("NFKC", text or "")


class Classifier:
    def __init__(self, cfg: dict) -> None:
        self.cfg = cfg["classification"]
        self.groups = {name: (spec, keyword_pattern(spec["words"])) for name, spec in self.cfg["signals"].items()}
        self.page_types = keyword_pattern(self.cfg["page_types"])
        self.min_sub = self.cfg["username_substring_min_length"]
        self.all_words = {w.lower() for spec in self.cfg["signals"].values() for w in spec["words"]}

    def _fields(self, lead: Lead) -> dict:
        # NFKC turns styled letters (𝘾𝙤𝙖𝙘𝙝, ｃｏａｃｈ) back into plain ones
        fields = {"bio": _plain(lead.biography), "name": _plain(lead.full_name), "category": lead.category}
        if lead.source != "podcast":  # podcast "usernames" are made-up ids
            fields["username"] = re.sub(r"[._\d]+", " ", lead.username)
        return fields

    def _match(self, lead: Lead) -> dict:
        """{group: {word: [fields]}} for every list word found in the lead."""
        found: dict = {}

        def add(group: str, word: str, where: str) -> None:
            places = found.setdefault(group, {}).setdefault(word.lower(), [])
            if where not in places:
                places.append(where)

        for where, text in self._fields(lead).items():
            for group, (_, pattern) in self.groups.items():
                for word in pattern.findall(text or ""):
                    add(group, word, where)
        # usernames are often joined words (fitnesswithriya): look inside them for longer list words
        if lead.source != "podcast":
            joined = re.sub(r"[^a-z]", "", lead.username.lower())
            for group, (spec, _) in self.groups.items():
                if spec["level"] == "weak":
                    continue
                for word in spec["words"]:
                    plain = word.lower().replace(" ", "").replace("-", "")
                    if len(plain) >= self.min_sub and plain.isalpha() and plain in joined:
                        add(group, word, "username")
            if DR_USERNAME.search(lead.username.lower()):
                add("professional_clinic", "dr", "username")
        for where in ("name", "bio"):
            text = _plain(lead.full_name if where == "name" else lead.biography)
            if DR_TEXT.search(text or ""):
                add("professional_clinic", "dr", where)
            if MD_TEXT.search(text or ""):
                add("professional_clinic", "md", where)
        return found

    def classify(self, lead: Lead) -> None:
        found = self._match(lead)
        caps = self.cfg["level_caps"]
        points = {"strong": 0, "medium": 0, "weak": 0}
        signals = []

        # an Instagram category that names a service counts once (+2), not word by word
        category_hit = any("category" in places for words in found.values() for places in words.values())
        for group in list(found):
            for word in list(found[group]):
                found[group][word] = [p for p in found[group][word] if p != "category"]
                if not found[group][word]:
                    del found[group][word]
            if not found[group]:
                del found[group]
        # a word inside a longer matched phrase counts once ("book a session" is not also "session")
        phrases = [w for words in found.values() for w in words if " " in w]
        for group in list(found):
            for word in list(found[group]):
                if any(word != p and re.search(rf"(?<![a-z]){re.escape(word)}(?![a-z])", p) for p in phrases):
                    del found[group][word]
            if not found[group]:
                del found[group]

        others = any(self.groups[g][0]["level"] != "weak" for g in found) or category_hit
        for group, words in found.items():
            spec = self.groups[group][0]
            if spec.get("only_without_other_signals") and others:
                found[group] = {}
                continue
            points[spec["level"]] += spec["weight"] * len(words)
            signals += [f"{word} ({'/'.join(places)})" for word, places in words.items()]
        if category_hit:
            points["medium"] += 2
            signals.append(f"category: {lead.category}")
        score = sum(min(points[level], caps[level]) for level in points)

        found = {g: w for g, w in found.items() if w}
        groups = set(found) | ({"category"} if category_hit else set())
        niche = bool(groups & set(self.cfg["niche_groups"]))
        page = self.page_types.search(_plain(f"{lead.full_name} {lead.biography} {lead.username}"))

        if page and score == 0:
            decision, why = "REMOVE", f"looks like a {page.group(0).lower()} account with no service signal"
        elif page:
            decision, why = "MAYBE", f"service signal, but it mentions '{page.group(0).lower()}'"
        elif score == 0:
            decision, why = "REMOVE", "no service signal in bio, name or username"
        elif score >= self.cfg["keep_score"] and (niche or not self.cfg["keep_needs_niche_signal"]):
            decision, why = "KEEP", f"score {score}: " + ", ".join(sorted(g for g in groups if not g.startswith("weak"))).replace("_", " ")
        elif score >= self.cfg["keep_score"]:
            decision, why = "MAYBE", f"score {score} but no niche signal (only offer or business words)"
        else:
            decision, why = "MAYBE", f"weak signals only (score {score})"

        lead.decision, lead.rule_score, lead.signals, lead.rule_reason = decision, score, "; ".join(signals), why
        lead.industry = self._industry(found, category_hit, lead.category) if decision != "REMOVE" else ""

    def _industry(self, found: dict, category_hit: bool, category: str) -> str:
        words = {w for group in found.values() for w in group}
        if category_hit:
            words |= {w.lower() for w in re.findall(r"[a-z]+(?: [a-z]+)?", category.lower())}
        for rule in self.cfg["industry_tags"]:
            if words & {w.lower() for w in rule.get("words", [])} or set(found) & set(rule.get("groups", [])):
                return rule["tag"]
        return self.cfg["fallback_tag"]

    def tidy_first_name(self, lead: Lead) -> None:
        """Leads that skip the AI keep the first name from the display name; drop it when that is a
        brand or a keyword ("Glow Skin Clinic", "Healing Hands"), so the email says "Hi there" instead."""
        name = lead.first_name.lower()
        if name and (name in self.all_words or BUSINESS_NAME.search(lead.full_name or "")):
            lead.first_name = ""
