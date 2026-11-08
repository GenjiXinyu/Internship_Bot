"""Entry point: python -m bot.main [--dry-run]

Each run:
  1. reads every company's job boards (plus the SimplifyJobs list as a backup),
  2. keeps US engineering internships,
  3. adds postings it hasn't seen before to the Google Sheet,
  4. fills in "Date Posted" for rows you logged yourself,
  5. emails you the new postings.
"""
from __future__ import annotations

import argparse
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Dict, List, Tuple

import yaml

from . import sources
from .filters import wanted
from .models import Job

ROOT = Path(__file__).resolve().parent.parent


def load_yaml(name: str) -> dict:
    with open(ROOT / name) as f:
        return yaml.safe_load(f)


def fetch_all(companies: List[dict], simplify_url: str) -> Tuple[List[Job], List[str], List[str]]:
    """Returns (jobs, report lines, problems)."""
    tasks = []
    for c in companies:
        for spec in c.get("sources") or []:
            tasks.append((c["name"], spec))

    def run(task):
        name, spec = task
        try:
            return name, spec, sources.run_source(name, spec), None
        except Exception as e:  # one broken board must not stop the others
            return name, spec, [], f"{type(e).__name__}: {e}"

    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(run, tasks))

    jobs: List[Job] = []
    report, problems = [], []
    direct_ok: Dict[str, bool] = {}
    for name, spec, got, err in results:
        label = sources.describe(spec)
        if err:
            if spec.get("optional"):
                report.append(f"  [skip] {name:24s} {label}: {err}")
            else:
                report.append(f"  [FAIL] {name:24s} {label}: {err}")
                problems.append(f"{name} ({label}): {err}")
        else:
            direct_ok[name] = True
            kept = sum(1 for j in got if wanted(j.title, j.location))
            report.append(f"  [ok]   {name:24s} {label}: {len(got)} jobs, {kept} engineering internships")
        jobs.extend(got)

    try:
        listings = sources.load_simplify(simplify_url)
        report.append(f"  [ok]   SimplifyJobs list: {len(listings)} listings")
    except Exception as e:
        listings = []
        report.append(f"  [FAIL] SimplifyJobs list: {e}")
        problems.append(f"SimplifyJobs list: {e}")
    for c in companies:
        got = sources.simplify_jobs(listings, c["name"], c.get("simplify") or [c["name"]])
        if got:
            kept = sum(1 for j in got if wanted(j.title, j.location))
            report.append(f"         {c['name']:24s} simplify: {len(got)} active, {kept} engineering internships")
        jobs.extend(got)

    # Companies with no working direct source rely on the SimplifyJobs list only
    for c in companies:
        if not direct_ok.get(c["name"]):
            report.append(f"  [note] {c['name']}: no direct feed, using SimplifyJobs list only")

    return jobs, report, problems


def dedupe(jobs: List[Job]) -> List[Job]:
    """Same posting from two sources -> keep one, preferring a direct source and a known date."""
    best: Dict[str, Job] = {}
    for j in jobs:
        if not j.key:
            continue
        cur = best.get(j.key)
        if cur is None:
            best[j.key] = j
            continue
        if cur.source == "simplify" and j.source != "simplify":
            j.posted = j.posted or cur.posted
            best[j.key] = j
        elif not cur.posted and j.posted:
            cur.posted = j.posted
    return list(best.values())


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="Fetch and print what would be added; don't touch the sheet or send email")
    args = ap.parse_args(argv)

    cfg = load_yaml("config.yaml")
    companies = load_yaml("companies.yaml")["companies"]
    sources.TZ = sources.ZoneInfo(cfg.get("timezone", "America/Los_Angeles"))
    found_date = sources.today().isoformat()

    all_jobs, report, problems = fetch_all(companies, cfg["simplify_url"])
    jobs = dedupe([j for j in all_jobs if wanted(j.title, j.location)])
    print("Sources:")
    print("\n".join(report))
    print(f"\n{len(jobs)} US engineering internships open across {len(companies)} companies.")

    if args.dry_run:
        for j in sorted(jobs, key=lambda j: (j.company, j.title)):
            print(f"  {j.company}: {j.title} | {j.location} | posted {j.posted or '?'} | {j.url}")
        return 0

    from .emailer import build_message, send
    from .sheet import Tracker

    missing = [k for k in ("SHEET_ID", "EMAIL_TO", "GMAIL_APP_PASSWORD", "GOOGLE_SERVICE_ACCOUNT_JSON")
               if not os.environ.get(k)]
    if missing:
        print(f"Missing repository secrets: {', '.join(missing)}. See README.md, 'One-time setup'.")
        return 1
    email_to = os.environ["EMAIL_TO"]

    tracker = Tracker(
        os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"],
        os.environ["SHEET_ID"], cfg["sheet"]["tab"], cfg["sheet"]["seen_tab"],
    )
    catch_up = tracker.first_run
    filled = tracker.fill_posted_dates(jobs)
    new = [j for j in jobs if not tracker.known(j)]
    # Postings you already logged count as seen, so they're never emailed
    already_logged = [j for j in jobs if j.key in tracker.row_by_key]

    tracker.add_jobs(new, found_date, cfg["sheet"].get("new_status", "Not yet Applied"))
    tracker.mark_seen(new + already_logged, found_date)
    print(f"Added {len(new)} new postings to the sheet; filled {filled} Date Posted cells.")

    if new:
        sender = os.environ.get("GMAIL_ADDRESS") or email_to
        msg = build_message(new, sender, email_to, catch_up=catch_up)
        send(msg, sender, os.environ["GMAIL_APP_PASSWORD"])
        print(f"Emailed {len(new)} postings.")  # no address: run logs are public
    else:
        print("Nothing new; no email sent.")

    if problems:
        print("\nSources that failed this run (the SimplifyJobs list still covers these companies):")
        for p in problems:
            print("  " + p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
