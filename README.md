# Lead Agent

IG Email Extractor CSV → clean & dedupe → website email finder → fit score (local AI) →
Bouncify check → personalised first line (local AI) → Instantly campaign → Cold Email sheet.

Full guide: `docs/Lead Agent - Team Setup and Dry Run Guide.docx`

## Setup: one command

You need: a computer with 16 GB RAM, an internet connection, and the `keys.vault` file + passphrase from Mahaveer (given privately, never by chat).

**Mac**: open Terminal and paste:
```
git clone https://github.com/Mahaveersonii/lead-agent.git ~/Desktop/lead-gen-agent && bash ~/Desktop/lead-gen-agent/install.sh
```

**Windows**: open PowerShell and paste:
```
winget install -e --id Git.Git; git clone https://github.com/Mahaveersonii/lead-agent.git $HOME\Desktop\lead-gen-agent; powershell -ExecutionPolicy Bypass -File $HOME\Desktop\lead-gen-agent\install.ps1
```

The installer:
1. checks Python (Mac: asks to install Apple's developer tools if missing; Windows: installs Python)
2. installs the agent's libraries
3. installs Ollama and downloads the AI model (about 5 GB, first time only)
4. asks for the passphrase and unlocks the API keys (Instantly, Bouncify, Google)
5. tests every connection and shows `[OK]` or `[FIX]` for each

Running it again is safe. It skips anything already done.

No GitHub account is needed. Put `keys.vault` into the lead-gen-agent folder, then run `.venv/bin/python keys_vault.py unlock` (Windows: `.venv\Scripts\python keys_vault.py unlock`).

## Every campaign day (Mon, Tue, Wed, before 6 PM)

1. Instantly: duplicate a new `AS-XX (New-mails)` campaign and leave it as a **Draft**.
2. Save the IG Email Extractor export(s) into `Leads/Incoming`.
3. Double-click **3 - LIVE run** and type `YES`. Wait until it says the leads were added.
4. Check the campaign in Instantly (preview 2-3 leads), then start it.

The live run does every check itself: duplicates, filters, AI fit, Bouncify and first lines.
It stops without sending if there is no fresh Draft `(New-mails)` campaign, Ollama is not running,
Bouncify credits run out, or it is not Mon-Wed. A report of every lead is saved in `output/`.

**2 - Test run** is optional: use it once after setup, or after rules change. It sends nothing.

**1 - Check setup** re-tests all connections at any time.

## Updates

In Terminal / PowerShell inside the folder: `git pull`. Your keys, leads and reports are not affected.

## Changing the rules

Edit `config.json`: follower range, blocked words, keyword list, target niches, minimum fit score,
fallback first line, campaign name marker and the master sheet ID.

## For the owner: changing keys

Update `.env` or `secrets/google_service_account.json`, then run `.venv/bin/python keys_vault.py lock`,
commit `keys.vault` and push. On the team computer: `git pull`, then `VAULT_FORCE=1 .venv/bin/python keys_vault.py unlock`.
