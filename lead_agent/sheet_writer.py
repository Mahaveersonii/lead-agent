"""Agent 9 - Sheet Writer: add the leads that reached Instantly to the Cold Email tab."""
from __future__ import annotations

from datetime import date

import gspread

from .common import ROOT, Lead


def _worksheet(cfg: dict):
    sheet = cfg["master_sheet"]
    client = gspread.service_account(filename=str(ROOT / sheet["service_account_file"]))
    return client.open_by_key(sheet["spreadsheet_id"]).get_worksheet_by_id(sheet["worksheet_gid"])


def check_access(cfg: dict) -> str:
    """Return the tab title, or raise if the service account can't open the sheet."""
    return _worksheet(cfg).title


def build_rows(leads: list[Lead], label: str) -> list[list]:
    """Same layout as the Cold Email tab: A label, B Name, C Niche, D Email, E Followers, F Profile URL."""
    rows = []
    for i, lead in enumerate(leads):
        rows.append([
            label if i == 0 else "",
            lead.first_name or lead.full_name,
            lead.niche,
            lead.email,
            lead.followers,
            lead.profile_url or f"https://www.instagram.com/{lead.username}",
        ])
    return rows


def run(leads: list[Lead], cfg: dict, dry_run: bool = True) -> list[list]:
    sent = [lead for lead in leads if lead.status == "Sent"]
    label = cfg["master_sheet"]["row_label"].format(date=date.today().strftime("%d/%b"))
    rows = build_rows(sent, label)
    if dry_run or not rows:
        return rows
    ws = _worksheet(cfg)
    next_row = len(ws.col_values(cfg["master_sheet"]["email_column"] + 1)) + 1  # first empty row in column D
    ws.update(rows, f"A{next_row}:F{next_row + len(rows) - 1}", value_input_option="USER_ENTERED")
    return rows
