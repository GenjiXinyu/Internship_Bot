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
from .filters import pick_location, same_role_key, wanted, is_california
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
            kept = sum(1 for j in got if wanted(j.title, j.location, j.terms))
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
            kept = sum(1 for j in got if wanted(j.title, j.location, j.terms))
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


class Role:
    """One role, possibly posted separately for several locations."""

    def __init__(self, members: List[Job]):
        self.members = members
        self.group_key = same_role_key(members[0].company, members[0].title)
        # Show the California posting if there is one, otherwise the first one
        ca = [j for j in members if is_california(j.location)]
        self.job = (ca or members)[0]
        dates = [j.posted for j in members if j.posted]
        self.job.posted = min(dates) if dates else None
        self.job.location = pick_location(self.job.location)

    @property
    def keys(self) -> List[str]:
        return [j.key for j in self.members]


def group_roles(jobs: List[Job]) -> List[Role]:
    groups: Dict[str, List[Job]] = {}
    for j in sorted(jobs, key=lambda j: (j.source == "simplify", j.url)):
        groups.setdefault(same_role_key(j.company, j.title), []).append(j)
    return [Role(m) for m in groups.values()]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="Fetch and print what would be added; don't touch the sheet or send email")
    ap.add_argument("--show", default="",
                    help="With --dry-run: also print every raw posting for companies whose name contains this text")
    args = ap.parse_args(argv)

    cfg = load_yaml("config.yaml")
    companies = load_yaml("companies.yaml")["companies"]
    sources.TZ = sources.ZoneInfo(cfg.get("timezone", "America/Los_Angeles"))
    found_date = sources.today().isoformat()

    all_jobs, report, problems = fetch_all(companies, cfg["simplify_url"])
    jobs = dedupe([j for j in all_jobs if wanted(j.title, j.location, j.terms)])
    roles = group_roles(jobs)
    print("Sources:")
    print("\n".join(report))
    print(f"\n{len(jobs)} US summer engineering internship postings open across {len(companies)} companies, "
          f"{len(roles)} after merging the same role offered in several locations.")

    if args.dry_run and args.show:
        needle = args.show.lower()
        print(f"\nEvery posting fetched for companies matching '{args.show}':")
        for j in sorted(all_jobs, key=lambda j: (j.company, j.source, j.title)):
            if needle in j.company.lower():
                print(f"  [{'keep' if wanted(j.title, j.location, j.terms) else 'drop'}] {j.company} | {j.source} | "
                      f"{j.title} | {j.location} | {j.url}")
        print()

    if args.dry_run:
        for r in sorted(roles, key=lambda r: (r.job.company, r.job.title)):
            j = r.job
            extra = f" (+{len(r.members) - 1} other locations)" if len(r.members) > 1 else ""
            print(f"  {j.company}: {j.title} | {j.location}{extra} | posted {j.posted or '?'} | {j.url}")
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
    # A role is new only if none of its postings (any location) has been seen or logged by you
    new_roles = [r for r in roles if not tracker.known_role(r.keys, r.group_key)]
    new = [r.job for r in new_roles]

    tracker.add_jobs(new, found_date, cfg["sheet"].get("new_status", "Not yet Applied"))
    tracker.mark_seen_role_keys(roles, found_date)
    print(f"Added {len(new)} new roles to the sheet; filled {filled} Date Posted cells.")

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
