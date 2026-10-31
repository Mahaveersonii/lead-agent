"""Check every connection the Lead Agent needs, without sending or writing anything."""
from __future__ import annotations

import os
import sys

import requests

from lead_agent import sender, sheet_writer, verifier
from lead_agent.common import ROOT, load_config, load_env

OK, FAIL = "  [OK]  ", "  [FIX] "


def check(label: str, fn) -> bool:
    try:
        detail = fn()
        print(f"{OK}{label}: {detail}")
        return True
    except Exception as error:  # show every problem in plain words, then continue
        print(f"{FAIL}{label}: {error}")
        return False


def main() -> None:
    load_env()
    cfg = load_config()
    print("\nChecking the Lead Agent setup...\n")

    def keys():
        missing = [k for k in ("INSTANTLY_API_KEY", "BOUNCIFY_API_KEY", "MASTER_SHEET_ID") if not os.environ.get(k)]
        if missing:
            raise RuntimeError(f"missing in .env: {', '.join(missing)}")
        return "Instantly key, Bouncify key and master sheet ID found"

    def ollama():
        url = cfg["scoring"]["ollama_url"].replace("/api/generate", "/api/tags")
        names = [m["name"] for m in requests.get(url, timeout=5).json()["models"]]
        if not any(n.startswith(cfg["scoring"]["ollama_model"]) for n in names):
            raise RuntimeError(f"Ollama is running but the model is missing. Run: ollama pull {cfg['scoring']['ollama_model']}")
        return f"running, {cfg['scoring']['ollama_model']} installed"

    def instantly():
        campaigns = sender.list_campaigns(cfg)
        try:
            ready = f'ready to use "{sender.pick_campaign(cfg)["name"]}"'
        except sender.NoCampaign as note:
            ready = f"OK (note: {note})"
        return f"{len(campaigns)} campaigns visible; {ready}"

    def bouncify():
        return f"{verifier.credits_remaining():,} credits left"

    def sheet():
        if not (ROOT / cfg["master_sheet"]["service_account_file"]).exists():
            raise RuntimeError("secrets/google_service_account.json not found")
        return f'can open tab "{sheet_writer.check_access(cfg)}"'

    results = [
        check("API keys", keys),
        check("Ollama (local AI)", ollama),
        check("Instantly", instantly) if os.environ.get("INSTANTLY_API_KEY") else False,
        check("Bouncify", bouncify) if os.environ.get("BOUNCIFY_API_KEY") else False,
        check("Google master sheet", sheet),
    ]
    print()
    if all(results):
        print("Everything is ready. Next: put an IG Email Extractor CSV in Leads/Incoming and double-click '2 - Test run'.\n")
    else:
        print("Fix the [FIX] lines above (see the setup guide), then run this check again.\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
