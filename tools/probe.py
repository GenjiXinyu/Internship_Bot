"""Find which job boards exist for a list of companies.

Tries likely Greenhouse / Lever / Ashby board names, a few Workday guesses and
career pages, and lists the company names SimplifyJobs uses. Prints what it
finds; nothing is written anywhere. Run on GitHub: Actions > Probe job boards.
"""
from __future__ import annotations

import re
import sys
from concurrent.futures import ThreadPoolExecutor

import yaml

from bot import sources
from bot.filters import is_internship

# name -> extra board-name guesses (the name itself is always tried in a few spellings)
CANDIDATES = {
    "Beta Technologies": ["beta", "flybeta", "betatechnologies"],
    "Electra.aero": ["electra", "electraaero", "electra-aero"],
    "Pivotal": ["pivotal", "flypivotal", "pivotalaero"],
    "Ampaire": ["ampaire"],
    "Reliable Robotics": ["reliablerobotics"],
    "Merlin Labs": ["merlinlabs", "merlin"],
    "Elroy Air": ["elroyair", "elroy"],
    "Natilus": ["natilus"],
    "Otto Aerospace": ["ottoaerospace", "otto", "ottoaviation"],
    "Regent": ["regent", "regentcraft"],
    "Skyryse": ["skyryse"],
    "ZeroAvia": ["zeroavia"],
    "Loft Orbital": ["loftorbital", "loft"],
    "Albedo": ["albedo", "albedospace"],
    "Umbra": ["umbra", "umbralab", "umbraspace"],
    "Turion Space": ["turionspace", "turion"],
    "True Anomaly": ["trueanomaly", "trueanomalyinc"],
    "Outpost Space": ["outpost", "outpostspace", "outposttechnologies"],
    "Katalyst Space": ["katalyst", "katalystspace", "katalystspacetechnologies"],
    "Portal Space Systems": ["portalspacesystems", "portal", "portalspace"],
    "Array Labs": ["arraylabs", "array"],
    "Hubble Network": ["hubblenetwork", "hubble"],
    "Starcloud": ["starcloud"],
    "Momentus": ["momentus", "momentusspace"],
    "Astroscale U.S.": ["astroscale", "astroscaleus", "astroscale-us"],
    "Agile Space Industries": ["agilespaceindustries", "agilespace"],
    "Phase Four": ["phasefour", "phase4"],
    "Benchmark Space Systems": ["benchmarkspacesystems", "benchmark", "benchmarkspace"],
    "X-Bow Systems": ["xbowsystems", "xbow", "xbowrockets"],
    "Firehawk Aerospace": ["firehawkaerospace", "firehawk"],
    "Radian Aerospace": ["radianaerospace", "radian"],
    "Castelion": ["castelion"],
    "Lunar Outpost": ["lunaroutpost"],
    "Interlune": ["interlune"],
    "Textron Aviation": ["textronaviation", "txtav"],
    "Cirrus Aircraft": ["cirrusaircraft", "cirrus"],
    "Gulfstream": ["gulfstream"],
    "Moog": ["moog"],
    "Garmin": ["garmin"],
    "NASA JPL": ["jpl"],
    "Hadrian": ["hadrian", "hadrianautomation"],
    "Machina Labs": ["machinalabs"],
    "Freeform": ["freeform", "freeformfuturecorp"],
    "Boston Dynamics": ["bostondynamics"],
    "Figure AI": ["figureai", "figure"],
    "Agility Robotics": ["agilityrobotics", "agility"],
    "Apptronik": ["apptronik"],
    "Tesla": ["tesla"],
    "Skydio": ["skydio"],
    "Gecko Robotics": ["geckorobotics", "gecko"],
}

WORKDAY_GUESSES = {
    "Moog": [("moog", w, s) for w in ("wd5", "wd1") for s in ("MoogCareers", "Moog_Careers", "moog", "External", "Moog")],
    "Boston Dynamics": [("bostondynamics", w, s) for w in ("wd1", "wd5", "wd3")
                        for s in ("Boston_Dynamics", "BostonDynamics", "External", "Careers", "bostondynamics")],
    "Garmin": [("garmin", w, s) for w in ("wd1", "wd5") for s in ("Garmin", "External", "GarminCareers", "Garmin_Careers", "garmin")],
    "Textron Aviation": [(t, w, s) for t in ("textron", "txtav") for w in ("wd1", "wd5")
                         for s in ("Textron", "TextronAviation", "External", "Careers", "textron")],
    "NASA JPL": [("jpl", w, s) for w in ("wd1", "wd5") for s in ("Jobs", "JPL", "External", "jpl")],
    "Tesla": [("tesla", w, s) for w in ("wd1", "wd5") for s in ("Tesla", "External")],
}

PAGE_GUESSES = {
    "Gulfstream": ["https://careers.gulfstream.com/search/?q=intern"],
    "Cirrus Aircraft": ["https://careers-cirrusaircraft.icims.com/jobs/search?ss=1&searchKeyword=intern"],
}


def spellings(name: str, extra):
    base = re.sub(r"[^a-z0-9 ]", "", name.lower())
    out = [base.replace(" ", ""), base.replace(" ", "-")] + list(extra)
    seen, res = set(), []
    for s in out:
        if s and s not in seen:
            seen.add(s)
            res.append(s)
    return res


def try_board(company, kind, slug):
    fn = {"greenhouse": sources.greenhouse, "lever": sources.lever, "ashby": sources.ashby,
          "rippling": sources.rippling, "pinpoint": sources.pinpoint}[kind]
    try:
        jobs = fn(company, slug)
    except Exception:
        return None
    if kind in ("lever", "rippling", "pinpoint") and not jobs:
        return None  # Lever answers [] for names that don't exist
    interns = [j.title for j in jobs if is_internship(j.title)]
    return (f"{kind}:{slug}", len(jobs), interns)


def try_workday(company, tenant, wd, site):
    url = f"https://{tenant}.{wd}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs"
    try:
        r = sources.session.post(url, json={"limit": 20, "offset": 0, "searchText": "intern", "appliedFacets": {}},
                                 timeout=20)
        if r.status_code != 200:
            return None
        d = r.json()
        titles = [p.get("title", "") for p in d.get("jobPostings", [])]
        return (f"workday:{tenant}/{wd}/{site}", d.get("total", 0), [t for t in titles if is_internship(t)])
    except Exception:
        return None


def try_page(company, url):
    try:
        jobs = sources.page(company, url)
    except Exception as e:
        return (f"page:{url} FAILED {type(e).__name__}", 0, [])
    return (f"page:{url}", len(jobs), [j.title for j in jobs])


SECOND_PASS = {
    "Beta Technologies": ["beta-technologies", "betatech", "flybeta", "beta-tech"],
    "Ampaire": ["ampaire", "ampaire-inc"], "Natilus": ["natilus", "natilus-inc"],
    "Otto Aerospace": ["otto-aerospace", "ottoaerospace", "otto-aviation"],
    "ZeroAvia": ["zeroavia", "zero-avia"], "Starcloud": ["starcloud", "starcloud-inc", "starcloudinc"],
    "Agile Space Industries": ["agile-space-industries", "agilespaceindustries", "agile-space"],
    "Phase Four": ["phase-four", "phasefour", "phase-four-inc"],
    "Benchmark Space Systems": ["benchmark-space-systems", "benchmarkspacesystems", "benchmark-space"],
    "X-Bow Systems": ["x-bow-systems", "xbow-systems", "xbowsystems", "x-bow"],
    "Firehawk Aerospace": ["firehawk-aerospace", "firehawkaerospace", "firehawk"],
    "Radian Aerospace": ["radian-aerospace", "radianaerospace", "radian"],
    "Castelion": ["castelion", "castelion-corp", "castelioncorp"],
    "Lunar Outpost": ["lunar-outpost", "lunaroutpost", "lunaroutpostinc"],
    "Interlune": ["interlune", "interlune-inc"], "Hadrian": ["hadrian", "hadrian-automation"],
    "Umbra": ["umbra", "umbra-lab", "umbralab", "umbra-space"],
}


def second_pass():
    found = {n: [] for n in SECOND_PASS}
    with ThreadPoolExecutor(16) as ex:
        futs = [(n, ex.submit(try_board, n, kind, slug)) for n, slugs in SECOND_PASS.items()
                for slug in slugs for kind in ("greenhouse", "lever", "ashby", "rippling", "pinpoint")]
        for n, f in futs:
            r = f.result()
            if r:
                found[n].append(r)
    for n, hits in found.items():
        print(f"== {n}")
        for src, total, interns in hits:
            print(f"   {src}: {total} jobs, {len(interns)} intern titles {interns[:4]}")
        if not hits:
            print("   (no board found)")


def main():
    if "--second" in sys.argv:
        return second_pass()
    cfg = yaml.safe_load(open("config.yaml"))
    listings = sources.load_simplify(cfg["simplify_url"])
    simplify_names = {}
    for l in listings:
        simplify_names[l.get("company_name", "")] = simplify_names.get(l.get("company_name", ""), 0) + 1

    tasks = []
    for name, extra in CANDIDATES.items():
        for slug in spellings(name, extra):
            for kind in ("greenhouse", "lever", "ashby"):
                tasks.append((name, try_board, (name, kind, slug)))
        for t, w, s in WORKDAY_GUESSES.get(name, []):
            tasks.append((name, try_workday, (name, t, w, s)))
        for url in PAGE_GUESSES.get(name, []):
            tasks.append((name, try_page, (name, url)))

    found = {n: [] for n in CANDIDATES}
    with ThreadPoolExecutor(16) as ex:
        futs = [(n, ex.submit(fn, *args)) for n, fn, args in tasks]
        for n, f in futs:
            r = f.result()
            if r:
                found[n].append(r)

    for name in CANDIDATES:
        print(f"== {name}")
        for src, total, interns in found[name]:
            print(f"   {src}: {total} jobs, {len(interns)} intern titles {interns[:4]}")
        if not found[name]:
            print("   (no board found)")
        word = re.sub(r"[^a-z0-9 ]", "", name.lower()).split()[0]
        if word in {"the"}:
            word = name.lower().split()[1]
        matches = sorted((n, c) for n, c in simplify_names.items() if n and word in n.lower())
        print(f"   Simplify names: {matches[:6]}")
    sys.stdout.flush()


if __name__ == "__main__":
    main()
