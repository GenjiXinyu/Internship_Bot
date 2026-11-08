"""Fetchers: one function per job board system. Each returns a list of Job."""
from __future__ import annotations

import html
import re
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Dict, List, Optional
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import requests

from .models import Job

TZ = ZoneInfo("America/Los_Angeles")
TIMEOUT = 30
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; personal-internship-alert/1.0)",
    "Accept": "application/json, text/html;q=0.9, */*;q=0.8",
}

session = requests.Session()
session.headers.update(HEADERS)


class SourceError(Exception):
    pass


def _get_json(url: str, **kw):
    r = session.get(url, timeout=TIMEOUT, **kw)
    if r.status_code != 200:
        raise SourceError(f"HTTP {r.status_code} from {url}")
    try:
        return r.json()
    except ValueError as e:
        raise SourceError(f"Not JSON from {url}") from e


def today() -> date:
    return datetime.now(TZ).date()


def _iso_to_date(value) -> Optional[str]:
    """ISO timestamp string, or epoch seconds/milliseconds, to a local YYYY-MM-DD."""
    if value in (None, ""):
        return None
    try:
        if isinstance(value, (int, float)):
            seconds = value / 1000 if value > 1e11 else value
            dt = datetime.fromtimestamp(seconds, tz=timezone.utc)
        else:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(TZ).date().isoformat()
    except (ValueError, OverflowError, OSError):
        return None


# ---------------------------------------------------------------- Greenhouse
def greenhouse(company: str, token: str) -> List[Job]:
    data = _get_json(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs")
    jobs = []
    for j in data.get("jobs", []):
        jobs.append(Job(
            company=company,
            title=j.get("title", ""),
            url=j.get("absolute_url", ""),
            location=(j.get("location") or {}).get("name", ""),
            # first_published is when the posting went live; updated_at is not a posting date
            posted=_iso_to_date(j.get("first_published")),
            source=f"greenhouse:{token}",
            key=f"gh:{j['id']}" if j.get("id") else "",
        ))
    return jobs


# ---------------------------------------------------------------- Lever
def lever(company: str, site: str) -> List[Job]:
    data = _get_json(f"https://api.lever.co/v0/postings/{site}?mode=json")
    if not isinstance(data, list):
        raise SourceError(f"Unexpected Lever response for {site}")
    jobs = []
    for j in data:
        cats = j.get("categories") or {}
        loc = cats.get("location") or ", ".join(cats.get("allLocations") or [])
        jobs.append(Job(
            company=company,
            title=j.get("text", ""),
            url=j.get("hostedUrl", ""),
            location=loc or "",
            posted=_iso_to_date(j.get("createdAt")),
            source=f"lever:{site}",
        ))
    return jobs


# ---------------------------------------------------------------- Ashby
def ashby(company: str, board: str) -> List[Job]:
    data = _get_json(f"https://api.ashbyhq.com/posting-api/job-board/{board}")
    jobs = []
    for j in data.get("jobs", []):
        if j.get("isListed") is False:
            continue
        loc = j.get("location") or ""
        extra = [s.get("location", "") for s in (j.get("secondaryLocations") or []) if isinstance(s, dict)]
        if extra:
            loc = "; ".join([loc] + extra)
        jobs.append(Job(
            company=company,
            title=j.get("title", ""),
            url=j.get("jobUrl", ""),
            location=loc,
            posted=_iso_to_date(j.get("publishedAt")),
            source=f"ashby:{board}",
        ))
    return jobs


# ---------------------------------------------------------------- Workday
def _workday_posted(text: str) -> Optional[str]:
    """'Posted Today' / 'Posted Yesterday' / 'Posted 3 Days Ago' -> date. '30+ Days' -> None."""
    t = (text or "").lower()
    if "today" in t:
        return today().isoformat()
    if "yesterday" in t:
        return (today() - timedelta(days=1)).isoformat()
    m = re.search(r"(\d+)\+?\s*days?", t)
    if m and "+" not in t:
        return (today() - timedelta(days=int(m.group(1)))).isoformat()
    return None


def workday(company: str, tenant: str, wd: str, site: str) -> List[Job]:
    base = f"https://{tenant}.{wd}.myworkdayjobs.com"
    api = f"{base}/wday/cxs/{tenant}/{site}/jobs"
    jobs: List[Job] = []
    seen = set()
    for search in ("intern", "co-op"):
        offset = 0
        while offset < 400:
            r = session.post(
                api,
                json={"appliedFacets": {}, "limit": 20, "offset": offset, "searchText": search},
                timeout=TIMEOUT,
            )
            if r.status_code != 200:
                raise SourceError(f"HTTP {r.status_code} from {api}")
            data = r.json()
            postings = data.get("jobPostings") or []
            for p in postings:
                path = p.get("externalPath", "")
                if not path or path in seen:
                    continue
                seen.add(path)
                jobs.append(Job(
                    company=company,
                    title=p.get("title", ""),
                    url=f"{base}/en-US/{site}{path}",
                    location=p.get("locationsText", ""),
                    posted=_workday_posted(p.get("postedOn", "")),
                    source=f"workday:{tenant}",
                ))
            offset += 20
            if len(postings) < 20 or offset >= (data.get("total") or 0):
                break
    return jobs


# ---------------------------------------------------------------- Pinpoint
def pinpoint(company: str, sub: str) -> List[Job]:
    data = _get_json(f"https://{sub}.pinpointhq.com/postings.json")
    items = data.get("data", data) if isinstance(data, dict) else data
    jobs = []
    for j in items or []:
        attrs = j.get("attributes", j) if isinstance(j, dict) else {}
        loc = attrs.get("location")
        if isinstance(loc, dict):
            loc = loc.get("name") or loc.get("city") or ""
        url = attrs.get("url") or j.get("url") or ""
        if url and url.startswith("/"):
            url = f"https://{sub}.pinpointhq.com{url}"
        jobs.append(Job(
            company=company,
            title=attrs.get("title", ""),
            url=url,
            location=loc or "",
            posted=_iso_to_date(attrs.get("published_at") or attrs.get("created_at")),
            source=f"pinpoint:{sub}",
        ))
    return jobs


# ---------------------------------------------------------------- Rippling
def rippling(company: str, slug: str) -> List[Job]:
    data = _get_json(f"https://ats.rippling.com/api/v2/board/{slug}/jobs?page=0&pageSize=200")
    items = data.get("items") or data.get("results") or data.get("jobs") if isinstance(data, dict) else data
    jobs = []
    for j in items or []:
        loc = j.get("locations") or j.get("location") or ""
        if isinstance(loc, list):
            loc = "; ".join(x.get("name", "") if isinstance(x, dict) else str(x) for x in loc)
        elif isinstance(loc, dict):
            loc = loc.get("name", "")
        url = j.get("url") or (f"https://ats.rippling.com/{slug}/jobs/{j['id']}" if j.get("id") else "")
        jobs.append(Job(
            company=company,
            title=j.get("name") or j.get("title", ""),
            url=url,
            location=loc,
            posted=_iso_to_date(j.get("createdOn") or j.get("created_at")),
            source=f"rippling:{slug}",
        ))
    return jobs


# ---------------------------------------------------------------- Amazon
def amazon(company: str, query: str) -> List[Job]:
    data = _get_json(
        "https://www.amazon.jobs/en/search.json",
        params={"base_query": query, "result_limit": 100, "sort": "recent", "country": "USA"},
    )
    jobs = []
    for j in data.get("jobs", []):
        posted = None
        try:
            posted = datetime.strptime(j.get("posted_date", ""), "%B %d, %Y").date().isoformat()
        except ValueError:
            pass
        jobs.append(Job(
            company=company,
            title=j.get("title", ""),
            url="https://www.amazon.jobs" + j.get("job_path", ""),
            location=j.get("normalized_location") or j.get("location", ""),
            posted=posted,
            source=f"amazon:{query}",
        ))
    return jobs


# ---------------------------------------------------------------- Plain careers page
LINK_RE = re.compile(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', re.I | re.S)
TAG_RE = re.compile(r"<[^>]+>")


def page(company: str, url: str) -> List[Job]:
    r = session.get(url, timeout=TIMEOUT)
    if r.status_code != 200:
        raise SourceError(f"HTTP {r.status_code} from {url}")
    jobs, seen = [], set()
    for href, inner in LINK_RE.findall(r.text):
        text = " ".join(html.unescape(TAG_RE.sub(" ", inner)).split())
        if not re.search(r"intern|co-?op", text, re.I) or len(text) > 200:
            continue
        full = urljoin(url, href)
        if full in seen:
            continue
        seen.add(full)
        jobs.append(Job(company=company, title=text, url=full, source=f"page:{url}"))
    return jobs


FETCHERS: Dict[str, Callable[..., List[Job]]] = {
    "greenhouse": greenhouse,
    "lever": lever,
    "ashby": ashby,
    "pinpoint": pinpoint,
    "rippling": rippling,
    "amazon": amazon,
    "page": page,
}


def run_source(company: str, spec: dict) -> List[Job]:
    """Run one source entry from companies.yaml."""
    if "workday" in spec:
        w = spec["workday"]
        return workday(company, w["tenant"], w["wd"], w["site"])
    for kind, fn in FETCHERS.items():
        if kind in spec:
            return fn(company, spec[kind])
    raise SourceError(f"Unknown source type: {spec}")


def describe(spec: dict) -> str:
    if "workday" in spec:
        w = spec["workday"]
        return f"workday:{w['tenant']}/{w['site']}"
    for kind in FETCHERS:
        if kind in spec:
            return f"{kind}:{spec[kind]}"
    return str(spec)


# ---------------------------------------------------------------- SimplifyJobs list
def load_simplify(url: str) -> list:
    r = session.get(url, timeout=60)
    if r.status_code != 200:
        raise SourceError(f"HTTP {r.status_code} from SimplifyJobs list")
    return r.json()


def simplify_jobs(listings: list, company: str, names: List[str]) -> List[Job]:
    wanted_names = {n.strip().lower() for n in names}
    jobs = []
    for x in listings:
        if (x.get("company_name") or "").strip().lower() not in wanted_names:
            continue
        if not x.get("active") or x.get("is_visible") is False:
            continue
        jobs.append(Job(
            company=company,
            title=x.get("title", ""),
            url=x.get("url", ""),
            location="; ".join(x.get("locations") or []),
            posted=_iso_to_date(x.get("date_posted")),
            source="simplify",
        ))
    return jobs
