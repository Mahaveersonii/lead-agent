# Lead Agent

IG Email Extractor CSV → clean & dedupe → keyword rules (KEEP / MAYBE / REMOVE) → website email finder →
AI check of MAYBE leads only (local AI) → Bouncify check → Instantly campaign → Cold Email sheet.

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

## Dashboard (easiest way)

Double-click **0 - Open Dashboard**. The browser opens `http://127.0.0.1:8765` with buttons for everything:
setup check, drop the CSV, Test run, LIVE run (type YES), live progress, and the history of every run with its leads.
Keep the Terminal window it opens running while you use the page; closing it stops the dashboard.
The page works only on this computer.

## Every campaign day (Mon, Tue, Wed, before 6 PM)

1. Instantly: duplicate a new `AS-XX (New-mails)` campaign and leave it as a **Draft**.
2. Double-click **0 - Open Dashboard** and drop the IG Email Extractor export(s) into **Lead files**
   (or save them into `Leads/Incoming`).
3. Press **LIVE run** and type `YES` (or double-click **3 - LIVE run**). Wait until it says the leads were added.
4. Check the campaign in Instantly (preview 2-3 leads), then start it.

The live run does every check itself: duplicates, filters, AI fit, Bouncify and first lines.
It stops without sending if there is no fresh Draft `(New-mails)` campaign, Ollama is not running,
Bouncify credits run out, or it is not Mon-Wed. A report of every lead is saved in `output/`.

**2 - Test run** is optional: use it once after setup, or after rules change. It sends nothing.

**1 - Check setup** re-tests all connections at any time.

## Podcast leads (extra lead source)

The dashboard's **Find podcast leads** button (or `python find_podcasts.py`) searches Apple Podcasts for
our niches, reads each show's public RSS feed and keeps hosts who posted in the last 60 days, use their own
email (not a hosting company address) and are not in the master sheet. It saves `Podcasts-....csv` into
`Leads/Incoming`; then run a Test run or LIVE run as usual. Free, no key, sends nothing by itself.

- Keywords: type them in the box, or leave it empty to use `target_niches`.
- Settings in `config.json` → `podcasts`: countries, active days, minimum episodes, skipped email domains,
  the campaign marker for podcast leads and the master-sheet label.
- If `podcasts.campaign_name_contains` differs from the Instagram marker, run podcast and Instagram files separately.

## Keyword rules (KEEP / MAYBE / REMOVE)

Every lead is scored on its bio, display name, username (and Instagram category, if the export has it) with the
word lists in `config.json` → `classification`. No AI is used for this, so it is instant.

- Strong words +3 each (max 6): offers, coaching, business, professional titles. Medium +2 (max 4): health,
  spiritual, funnel, a service category. Weak +1 (max 2).
- **KEEP**: score 3+ with at least one niche word. Goes straight on, no AI call.
- **MAYBE**: score 1-2, or only offer/business words, or a fan/meme page that also offers something. The AI
  checks these; the ones it doesn't approve are saved in `output/review/review-....csv` for a person to look at.
- **REMOVE**: no service word at all.

Each word belongs to one list only. Set `ai_reviews_maybe` to `false` to send every MAYBE lead to the review file.

## Updates

In Terminal / PowerShell inside the folder: `git pull`. Your keys, leads and reports are not affected.

## Changing the rules

Edit `config.json`: follower range, blocked words, keyword list, target niches, minimum fit score,
fallback first line, campaign name marker and the master sheet ID.

## For the owner: changing keys

Update `.env` or `secrets/google_service_account.json`, then run `.venv/bin/python keys_vault.py lock`,
commit `keys.vault` and push. On the team computer: `git pull`, then `VAULT_FORCE=1 .venv/bin/python keys_vault.py unlock`.
