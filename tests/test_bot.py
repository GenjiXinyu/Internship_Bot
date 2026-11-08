import json
from pathlib import Path

import pytest

from bot import sources
from bot.filters import is_engineering, is_internship, is_us, wanted
from bot.main import dedupe
from bot.models import Job, job_key

FIX = Path(__file__).parent / "fixtures"


class FakeResp:
    def __init__(self, data, status=200):
        self._data, self.status_code = data, status
        self.text = data if isinstance(data, str) else json.dumps(data)

    def json(self):
        return self._data if not isinstance(self._data, str) else json.loads(self._data)


def load(name):
    return json.loads((FIX / name).read_text())


# ------------------------------------------------------------------ keys
@pytest.mark.parametrize("a,b", [
    ("https://boards.greenhouse.io/spacex/jobs/8621740002",
     "https://job-boards.greenhouse.io/spacex/jobs/8621740002?gh_src=abc"),
    ("https://www.stokespace.com/careers/current-openings/?gh_jid=6175828004",
     "https://job-boards.greenhouse.io/stokespace/jobs/6175828004"),
    ("https://rocketlabcorp.com/careers/positions/fluid-systems-intern-summer-2027-long-beach-ca-7986794003/",
     "https://job-boards.greenhouse.io/rocketlab/jobs/7986794003"),
    ("https://jobs.ashbyhq.com/apex-technology-inc/31c57de3-6150-41c6-a632-ea193cf57218/application?utm_source=LinkedIn",
     "https://jobs.ashbyhq.com/apex-technology-inc/31c57de3-6150-41c6-a632-ea193cf57218"),
    ("https://www.astromecha.co/careers?ashby_jid=8406a0b9-d8d6-40ff-b3e1-081a3e68968f",
     "https://jobs.ashbyhq.com/astro-mechanica/8406a0b9-d8d6-40ff-b3e1-081a3e68968f"),
    ("https://jobs.lever.co/CesiumAstro/c7217acc-8eb4-4431-9e90-f426ccca8d1f/apply?source=LinkedIn",
     "https://jobs.lever.co/CesiumAstro/c7217acc-8eb4-4431-9e90-f426ccca8d1f"),
    ("https://blueorigin.wd5.myworkdayjobs.com/en-US/BlueOrigin/job/Greater-Seattle-Area/Summer-2027-Fluid-Systems---Propulsion-Engineering-Internship---Undergraduate_R71441?source=LinkedIn",
     "https://blueorigin.wd5.myworkdayjobs.com/blueorigin/job/Greater-Seattle-Area/Summer-2027-Fluid-Systems---Propulsion-Engineering-Internship---Undergraduate_R71441"),
])
def test_same_posting_same_key(a, b):
    assert job_key(a) == job_key(b)


def test_different_postings_different_keys():
    assert job_key("https://boards.greenhouse.io/x/jobs/111111") != job_key("https://boards.greenhouse.io/x/jobs/222222")


# ------------------------------------------------------------------ filters
@pytest.mark.parametrize("title", [
    "Summer 2027 Engineering Internship",
    "Propulsion Engineering Intern (Summer 2027)",
    "Fluid Systems Intern Summer 2027",
    "Vehicle Fluids Engineer Intern",
    "Communications/DSP Intern (Fall 2026)",
    "Internship - Test - Summer 2026",
    "GNC Intern",
    "Mechanical Engineering Co-op - Spring 2027",
    "Summer 2027 Internship - Engineering",
])
def test_engineering_internships_kept(title):
    assert is_internship(title) and is_engineering(title), title


@pytest.mark.parametrize("title", [
    "Finance Intern – US – Summer 2027",
    "Talent Acquisition Intern Summer 2027",
    "Supply Chain Intern Summer 2027",
    "Business Development Intern",
    "Legal Intern (Summer 2027)",
    "Marketing Intern",
    "Senior Propulsion Engineer",          # not an internship
    "Internal Audit Manager",              # "Internal" is not "intern"
    "Library Science Co-op",
    "Data Analytics Intern",
    "Military DoD SkillBridge Internship - Test Technician",
    "Material Planning- Summer Intern",
])
def test_others_dropped(title):
    assert not (is_internship(title) and is_engineering(title)), title


@pytest.mark.parametrize("loc,expected", [
    ("Long Beach, CA", True),
    ("", True),
    ("Toronto, Canada", False),
    ("Bristol Area", False),
    ("Montreal Area", False),
    ("Long Beach, CA; Toronto, Canada", True),
    ("Remote - United States", True),
    ("Kruibeke, Belgium", False),
    ("Indianapolis", True),
])
def test_location(loc, expected):
    assert is_us(loc) == expected


# ------------------------------------------------------------------ fetchers
def test_greenhouse(monkeypatch):
    monkeypatch.setattr(sources.session, "get", lambda url, **kw: FakeResp(load("greenhouse.json")))
    jobs = sources.greenhouse("SpaceX", "spacex")
    assert len(jobs) == 2
    j = jobs[0]
    assert j.key == "gh:8621740002" and j.location == "Starbase, TX"
    assert j.posted == "2026-09-01"


def test_lever(monkeypatch):
    monkeypatch.setattr(sources.session, "get", lambda url, **kw: FakeResp(load("lever.json")))
    jobs = sources.lever("Hermeus", "hermeus")
    assert jobs[0].title == "Propulsion Engineer Intern - Fall 2026"
    assert jobs[0].key == "id:aaaaaaaa-1111-2222-3333-444444444444"
    assert jobs[0].posted == "2026-05-02"


def test_ashby(monkeypatch):
    monkeypatch.setattr(sources.session, "get", lambda url, **kw: FakeResp(load("ashby.json")))
    jobs = sources.ashby("Apex", "apex-technology-inc")
    assert len(jobs) == 1  # the unlisted posting is skipped
    assert jobs[0].posted == "2026-10-14"


def test_workday(monkeypatch):
    calls = []

    def fake_post(url, json=None, **kw):
        calls.append(json["searchText"])
        return FakeResp(load("workday.json") if json["searchText"] == "intern" else {"total": 0, "jobPostings": []})

    monkeypatch.setattr(sources.session, "post", fake_post)
    monkeypatch.setattr(sources, "today", lambda: __import__("datetime").date(2026, 11, 8))
    jobs = sources.workday("Blue Origin", "blueorigin", "wd5", "BlueOrigin")
    assert calls == ["intern", "internship", "co-op"]
    assert len(jobs) == 2
    assert jobs[0].url.startswith("https://blueorigin.wd5.myworkdayjobs.com/en-US/BlueOrigin/job/")
    assert jobs[0].key == "wd:R71441"
    assert jobs[0].posted == "2026-11-05"
    assert jobs[1].posted is None  # "Posted 30+ Days Ago"


def test_page(monkeypatch):
    html = ('<a href="/careers/fall-engineering-internship">Fall Engineering Internship</a>'
            '<a href="/about">About us</a>')
    monkeypatch.setattr(sources.session, "get", lambda url, **kw: FakeResp(html))
    jobs = sources.page("General Galactic", "https://www.gengalactic.com/careers")
    assert [j.url for j in jobs] == ["https://www.gengalactic.com/careers/fall-engineering-internship"]


def test_simplify_matches_exact_company_and_active_only():
    listings = load("simplify.json")
    jobs = sources.simplify_jobs(listings, "Planet Labs", ["Planet"])
    assert [j.title for j in jobs] == ["Spacecraft Systems Engineering Intern"]


# ------------------------------------------------------------------ dedupe
def test_dedupe_prefers_direct_source_and_keeps_date():
    a = Job("SpaceX", "Intern", "https://boards.greenhouse.io/spacex/jobs/1234567", posted="2026-09-01", source="simplify")
    b = Job("SpaceX", "Intern", "https://job-boards.greenhouse.io/spacex/jobs/1234567", source="greenhouse:spacex")
    out = dedupe([a, b])
    assert len(out) == 1 and out[0].source == "greenhouse:spacex" and out[0].posted == "2026-09-01"


def test_wanted_end_to_end():
    assert wanted("Propulsion Design Intern Summer 2027", "Long Beach, CA")
    assert not wanted("Mechanical Engineering Intern Summer 2027", "Toronto, Canada")


# ------------------------------------------------------------------ sheet + email
class FakeWS:
    def __init__(self, rows):
        self.rows = rows
        self.updates = []

    def get_all_values(self):
        return self.rows

    def batch_update(self, updates, value_input_option=None):
        self.updates.append(("batch", updates))

    def update(self, range_name=None, values=None, value_input_option=None):
        self.updates.append(("update", range_name, values))

    def append_rows(self, rows, value_input_option=None):
        self.updates.append(("append", rows))

    def add_rows(self, n):
        self.updates.append(("add_rows", n))


def make_tracker(main_rows, seen_rows):
    from bot.sheet import Tracker
    t = Tracker.__new__(Tracker)
    t.ws, t.seen_ws = FakeWS(main_rows), FakeWS(seen_rows)
    t._load()
    return t


HEADER = ["Company", "Title", "Location", "Application Status", "Link", "Date Posted", "Date Found", "Date Applied"]


def test_tracker_fills_dates_and_appends_below_data():
    rows = [HEADER,
            ["SpaceX", "Summer 2027 Engineering Internship", "Starbase, TX", "Waiting Response",
             "https://job-boards.greenhouse.io/spacex/jobs/8621740002"],
            ["Stoke Space", "Summer 2027 Internship - Engineering", "Kent, WA", "Waiting Response",
             "https://www.stokespace.com/careers/current-openings/?gh_jid=6175828004", "2026-10-01"]]
    t = make_tracker(rows, [["Key", "Company", "Title", "Link", "First Seen"]])
    assert t.first_run

    logged = Job("SpaceX", "x", "https://boards.greenhouse.io/spacex/jobs/8621740002", posted="2026-09-01")
    logged_dated = Job("Stoke Space", "x", "https://job-boards.greenhouse.io/stokespace/jobs/6175828004", posted="2026-09-15")
    new = Job("Vast", "Mechanical Intern", "https://job-boards.greenhouse.io/vast/jobs/4711400099", location="Long Beach, CA", posted="2026-11-07")

    assert t.known(logged) and t.known(logged_dated) and not t.known(new)
    assert t.fill_posted_dates([logged, logged_dated]) == 1        # Stoke already had a date
    assert t.ws.updates[0] == ("batch", [{"range": "F2", "values": [["2026-09-01"]]}])

    t.add_jobs([new], "2026-11-08", "Not yet Applied")
    kind, rng, values = t.ws.updates[1]
    assert rng == "A4"
    assert values[0][:7] == ["Vast", "Mechanical Intern", "Long Beach, CA", "Not yet Applied",
                             new.url, "2026-11-07", "2026-11-08"]

    t.mark_seen([new, logged], "2026-11-08")
    assert not t.first_run and t.known(new)


def test_tracker_rejects_missing_columns():
    with pytest.raises(RuntimeError):
        make_tracker([["Company", "Title"]], [])


def test_email_format():
    from bot.emailer import build_message
    jobs = [Job("Vast", "Mechanical/Aerospace Engineering Intern", "https://job-boards.greenhouse.io/vast/jobs/1234567"),
            Job("Apex", "Propulsion Internship", "https://jobs.ashbyhq.com/apex-technology-inc/1a4b78cb-f601-451c-ad27-e5e03324650e")]
    msg = build_message(jobs, "me@gmail.com", "you@example.com")
    assert msg["Subject"] == "2 new internships found"
    body = msg.get_body(preferencelist=("plain",)).get_content()
    assert body.startswith("Apex: Propulsion Internship\nApply: https://jobs.ashbyhq.com/")
    assert "Vast: Mechanical/Aerospace Engineering Intern\nApply: https://job-boards.greenhouse.io/vast/jobs/1234567" in body


def test_workday_country_tag():
    from bot.filters import clean_location
    assert not is_us("Gorgonzola [country: Italy]")
    assert not is_us("Noida Berger Tower [country: India]")
    assert is_us("Plantation [country: United States of America]")
    assert is_us("Los Angeles (HQ)")
    assert clean_location("Plantation [country: United States of America]") == "Plantation"
    assert clean_location("[country: United States of America]") == "United States of America"


def test_security_analyst_dropped():
    assert not is_engineering("Security Analyst Intern Summer 2027")
    assert is_engineering("Cybersecurity Engineer Intern")


def test_tracker_grows_tab_when_full():
    t = make_tracker([HEADER, ["A", "B", "C", "D", "https://boards.greenhouse.io/x/jobs/1111111"]], [])
    t.ws.row_count = 2
    t.add_jobs([Job("Vast", "Intern", "https://job-boards.greenhouse.io/vast/jobs/2222222")], "2026-11-08", "Not yet Applied")
    assert t.ws.updates[0] == ("add_rows", 201)


# ------------------------------------------------------------------ summer + locations
import datetime as _dt
from bot.filters import is_summer, pick_location
from bot.main import group_roles

NOV_2026 = _dt.date(2026, 11, 8)


@pytest.mark.parametrize("title,terms,expected", [
    ("Propulsion Design Intern Summer 2027", [], True),
    ("Mechanical Engineering Internship (Spring or Summer 2027)", [], True),
    ("Propulsion Engineering Intern", [], True),                      # no season -> keep
    ("Electrical Systems Engineer Co-op - Fixed Term", [], True),
    ("Spring 2027 Engineering Internship/Co-op", [], False),
    ("Internship - Electrical Engineering - Fall 2026", [], False),
    ("FPGA Intern - Winter 2027", [], False),
    ("Flight Software Engineering Intern - (Summer/Fall 2026)", [], False),  # summer already over
    ("Software Engineer Intern", ["Fall 2026"], False),               # season only in SimplifyJobs terms
    ("Software Engineer Intern", ["Summer 2027"], True),
])
def test_summer_only(title, terms, expected):
    assert is_summer(title, terms, today=NOV_2026) == expected


@pytest.mark.parametrize("loc,expected", [
    ("Seattle, WA; LA; Denver, CO", "LA"),
    ("Greater Seattle Area; Los Angeles, CA; Space Coast, FL [country: United States of America]", "Los Angeles, CA"),
    ("Boston, MA; Seattle, WA; Reston, VA", "Boston, MA"),
    ("Kent, WA", "Kent, WA"),
    ("Flexible - Any SpaceX Site", "Flexible - Any SpaceX Site"),
])
def test_pick_location(loc, expected):
    assert pick_location(loc) == expected


def test_same_role_in_several_places_becomes_one_row():
    jobs = [
        Job("Rocket Lab", "Manufacturing Engineering Intern Summer 2027", "https://job-boards.greenhouse.io/rocketlab/jobs/7996623003",
            location="Wallops Island, VA", posted="2026-09-17"),
        Job("Rocket Lab", "Manufacturing Engineering Intern Summer 2027", "https://job-boards.greenhouse.io/rocketlab/jobs/7984564003",
            location="Long Beach, CA", posted="2026-09-16"),
        Job("Rocket Lab", "Fluid Systems Intern Summer 2027", "https://job-boards.greenhouse.io/rocketlab/jobs/7986794003",
            location="Long Beach, CA"),
    ]
    roles = group_roles(jobs)
    assert len(roles) == 2
    mfg = next(r for r in roles if "Manufacturing" in r.job.title)
    assert mfg.job.location == "Long Beach, CA" and mfg.job.posted == "2026-09-16" and len(mfg.keys) == 2


def test_role_counts_as_known_if_any_location_was_logged():
    rows = [HEADER, ["Rocket Lab", "x", "Wallops", "Waiting Response", "https://job-boards.greenhouse.io/rocketlab/jobs/7996623003"]]
    t = make_tracker(rows, [["Key"]])
    jobs = [Job("Rocket Lab", "Mfg Intern Summer 2027", "https://job-boards.greenhouse.io/rocketlab/jobs/7996623003", location="Wallops Island, VA"),
            Job("Rocket Lab", "Mfg Intern Summer 2027", "https://job-boards.greenhouse.io/rocketlab/jobs/7984564003", location="Long Beach, CA")]
    r = group_roles(jobs)[0]
    assert t.known_role(r.keys, r.group_key)


def test_company_title_beats_backup_copy_for_season():
    from bot.main import dedupe
    backup = Job("Rocket Lab", "Flight Software Intern", "https://boards.greenhouse.io/rocketlab/jobs/7989724003",
                 location="Littleton, CO", source="simplify", terms=["Summer 2027"])
    direct = Job("Rocket Lab", "Flight Software Intern Spring 2027", "https://job-boards.greenhouse.io/rocketlab/jobs/7989724003",
                 location="Littleton, CO", source="greenhouse:rocketlab")
    out = [j for j in dedupe([backup, direct]) if wanted(j.title, j.location, j.terms)]
    assert out == []


def test_workday_city_from_link():
    from bot.sources import _workday_city_from_path
    assert _workday_city_from_path("/job/Minneapolis-MN/Summer-2027-Machine-Learning-Intern_8389") == "Minneapolis, MN"
    assert _workday_city_from_path("/job/Greater-Seattle-Area/X_R1") == "Greater Seattle Area"


@pytest.mark.parametrize("loc,expected", [
    ("Derby; Indianapolis, IN", "Indianapolis, IN"),
    ("Düsseldorf; Houston, TX", "Houston, TX"),
    ("Franklin, LA; Austin, TX", "Franklin, LA"),      # Louisiana is not Los Angeles: no CA, first US one
    ("LA; Austin, TX", "LA"),                           # bare "LA" is Los Angeles
])
def test_pick_location_prefers_us_and_reads_LA_right(loc, expected):
    assert pick_location(loc) == expected


def test_workday_detail_path_when_host_matches_site(monkeypatch):
    seen_paths = []

    def fake_post(url, json=None, **kw):
        if json["searchText"] != "intern":
            return FakeResp({"total": 0, "jobPostings": []})
        return FakeResp({"total": 1, "jobPostings": [{"title": "Summer 2027 GNC Intern",
                         "externalPath": "/job/Simi-Valley-CA/Summer-2027-GNC-Intern_8610", "locationsText": "14 Locations"}]})

    def fake_get(url, **kw):
        seen_paths.append(url)
        return FakeResp({"jobPostingInfo": {"location": "Simi Valley, CA", "additionalLocations": ["Huntsville, AL"],
                                            "country": {"descriptor": "United States of America"}}})

    monkeypatch.setattr(sources.session, "post", fake_post)
    monkeypatch.setattr(sources.session, "get", fake_get)
    jobs = sources.workday("AeroVironment", "avav", "wd1", "avav")
    assert seen_paths == ["https://avav.wd1.myworkdayjobs.com/wday/cxs/avav/avav/job/Simi-Valley-CA/Summer-2027-GNC-Intern_8610"]
    assert pick_location(jobs[0].location) == "Simi Valley, CA"


def test_country_in_title_dropped():
    assert not wanted("Engineering and Technology Summer Internship - UK", "Rotherham")
    assert wanted("Propulsion Engineering Intern (Summer 2027)", "Long Beach, CA")


def test_start_month_counts_as_season():
    import datetime
    from bot.filters import is_summer
    today = datetime.date(2026, 11, 8)
    assert not is_summer("Structures / Mechanical Test Co-op - January 2027 Co-op", today=today)
    assert not is_summer("Electrical Engineering Co-op - January 2027", today=today)
    assert is_summer("June 2027 Co-op - Software Engineer Intern", today=today)
    assert is_summer("Software Intern", today=today)
    assert is_summer("May the best intern win", today=today)
