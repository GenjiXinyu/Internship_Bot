"""The Job record and the key used to recognize the same posting across sources."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import parse_qs, urlparse

UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
WORKDAY_REQ_RE = re.compile(r"_((?:JR|R)?\d{3,}(?:-\d+)?)/?$", re.I)


@dataclass
class Job:
    company: str
    title: str
    url: str
    location: str = ""
    posted: Optional[str] = None  # YYYY-MM-DD, or None when the source doesn't say
    source: str = ""
    key: str = field(default="")
    terms: list = field(default_factory=list)  # e.g. ["Summer 2027"], when the source says
    dept: str = ""  # team/department, when the source says ("Engineering and Systems")

    def __post_init__(self) -> None:
        if not self.key:
            self.key = job_key(self.url)


def job_key(url: str) -> str:
    """A short ID that stays the same however a posting's link is written.

    The same Greenhouse job can appear as boards.greenhouse.io/x/jobs/123,
    company.com/careers?gh_jid=123 or a LinkedIn-tagged link, so matching on the
    raw URL would add duplicates to the sheet.
    """
    if not url:
        return ""
    url = url.strip()
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    path = parsed.path.rstrip("/")

    # Greenhouse job ID in a query string (company-hosted boards)
    if "gh_jid" in query:
        return "gh:" + query["gh_jid"][0]
    # Ashby job ID in a query string
    if "ashby_jid" in query:
        return "id:" + query["ashby_jid"][0].lower()
    # Lever, Ashby, Pinpoint, Rippling, Simplify: the posting ID is a UUID
    m = UUID_RE.search(path)
    if m:
        return "id:" + m.group(0).lower()
    # Workday: requisition number at the end of the path (..._R71441)
    if "myworkdayjobs.com" in parsed.netloc:
        m = WORKDAY_REQ_RE.search(path)
        if m:
            return "wd:" + m.group(1).upper()
    # Greenhouse-style numeric ID: /jobs/123456 or a trailing -7986794003
    m = re.search(r"/jobs?/(\d{5,})", path)
    if m:
        return "gh:" + m.group(1)
    m = re.search(r"[-_/](\d{7,})$", path)
    if m:
        return "gh:" + m.group(1)
    # Anything else: the URL without its query string
    return "url:" + (parsed.netloc + path).lower()
