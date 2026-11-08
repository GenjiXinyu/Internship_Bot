"""Read and write the Google Sheet tracker."""
from __future__ import annotations

import json
from typing import Dict, List, Set

import gspread
from google.oauth2.service_account import Credentials

from .filters import clean_location
from .models import Job, job_key

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
REQUIRED = ["Company", "Title", "Location", "Application Status", "Link",
            "Date Posted", "Date Found", "Date Applied"]
SEEN_HEADER = ["Key", "Company", "Title", "Link", "First Seen"]


def col_letter(index: int) -> str:
    """0-based column index -> A1 letter(s)."""
    s, n = "", index + 1
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


class Tracker:
    def __init__(self, service_account_json: str, sheet_id: str, tab: str, seen_tab: str):
        creds = Credentials.from_service_account_info(json.loads(service_account_json), scopes=SCOPES)
        self.book = gspread.authorize(creds).open_by_key(sheet_id)
        self.ws = self.book.worksheet(tab)
        self.seen_ws = self._seen_tab(seen_tab)
        self._load()

    # -- setup
    def _seen_tab(self, title: str):
        try:
            return self.book.worksheet(title)
        except gspread.WorksheetNotFound:
            ws = self.book.add_worksheet(title=title, rows=2000, cols=len(SEEN_HEADER))
            ws.update(range_name="A1", values=[SEEN_HEADER])
            return ws

    def _load(self) -> None:
        rows = self.ws.get_all_values()
        header = rows[0] if rows else []
        missing = [h for h in REQUIRED if h not in header]
        if missing:
            raise RuntimeError(f"Tracker is missing columns: {missing}. Header row is: {header}")
        self.col = {h: header.index(h) for h in REQUIRED}
        self.rows = rows[1:]
        # key -> sheet row number (1-based, header is row 1)
        self.row_by_key: Dict[str, int] = {}
        for i, row in enumerate(self.rows, start=2):
            link = row[self.col["Link"]] if len(row) > self.col["Link"] else ""
            k = job_key(link)
            if k:
                self.row_by_key.setdefault(k, i)
        seen_rows = self.seen_ws.get_all_values()[1:]
        self.seen: Set[str] = {r[0] for r in seen_rows if r}

    @property
    def first_run(self) -> bool:
        return not self.seen

    def known(self, job: Job) -> bool:
        return job.key in self.seen or job.key in self.row_by_key

    # -- writes
    def fill_posted_dates(self, jobs: List[Job]) -> int:
        """For rows you already logged, fill in an empty Date Posted."""
        c = self.col["Date Posted"]
        updates = []
        for job in jobs:
            r = self.row_by_key.get(job.key)
            if not r or not job.posted:
                continue
            row = self.rows[r - 2]
            if len(row) <= c or not row[c].strip():
                updates.append({"range": f"{col_letter(c)}{r}", "values": [[job.posted]]})
                row += [""] * (c + 1 - len(row))
                row[c] = job.posted
        if updates:
            self.ws.batch_update(updates, value_input_option="USER_ENTERED")
        return len(updates)

    def add_jobs(self, jobs: List[Job], found_date: str, status: str) -> None:
        if not jobs:
            return
        width = max(self.col.values()) + 1
        out = []
        for job in jobs:
            row = [""] * width
            row[self.col["Company"]] = job.company
            row[self.col["Title"]] = job.title
            row[self.col["Location"]] = clean_location(job.location)
            row[self.col["Application Status"]] = status
            row[self.col["Link"]] = job.url
            row[self.col["Date Posted"]] = job.posted or ""
            row[self.col["Date Found"]] = found_date
            out.append(row)
        # Write right below the last row that has any data in the Company..Link columns
        start = len(self.rows) + 2
        self.ws.update(range_name=f"A{start}", values=out, value_input_option="USER_ENTERED")
        self.rows.extend(out)

    def mark_seen(self, jobs: List[Job], found_date: str) -> None:
        new = [j for j in jobs if j.key and j.key not in self.seen]
        if not new:
            return
        self.seen_ws.append_rows(
            [[j.key, j.company, j.title, j.url, found_date] for j in new],
            value_input_option="RAW",
        )
        self.seen.update(j.key for j in new)
