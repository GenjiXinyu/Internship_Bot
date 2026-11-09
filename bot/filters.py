"""Decide which postings count as US engineering internships."""
from __future__ import annotations

import re

INTERN_RE = re.compile(r"\bintern(ship)?s?\b|\bco-?op\b|\bco op\b", re.I)

# Titles with one of these are always engineering
STRONG_RE = re.compile(
    r"engineer|propulsion|\bgnc\b|guidance|avionics|\bdsp\b|fpga|\bcfd\b|\brf\b|turbomachinery|combustion",
    re.I,
)
# Titles with one of these are engineering unless an excluded word is also present
ENG_RE = re.compile(
    r"fluid|structur|thermal|aero|mechanic|electrical|electronic|manufactur|\btest|systems|"
    r"software|firmware|embedded|controls?\b|robotic|material|stress|analy[sz]|design|integration|"
    r"launch|mission|flight|hardware|physics|turbine|engine|vehicle|spacecraft|satellite|"
    r"optic|power|mechanism|reliability|quality|production|tooling|gse|machin|data scien|"
    r"machine learning|autonomy|perception|simulation|modeling|technical|r&d|research",
    re.I,
)
EXCLUDE_RE = re.compile(
    r"financ|accounting|marketing|sales|human resources|\bhr\b|legal|recruit|talent|"
    r"communications|public relations|business|procurement|purchasing|people|policy|government|"
    r"hospitality|graphic|brand|social media|supply chain|buyer|contracts|administrative|"
    r"office|facilities|ehs|safety specialist|it support|help ?desk|paralegal|tax|audit|"
    r"economist|economics|strategy|product manag|program manag|project manag|security|skillbridge|planning|planner",
    re.I,
)

NON_US_RE = re.compile(
    r"canada|toronto|montr[eé]al|vancouver|ottawa|quebec|ontario|british columbia|"
    r"united kingdom|\buk\b|england|scotland|wales|ireland|bristol|london|filton|derby|"
    r"germany|deutschland|berlin|munich|m[uü]nchen|bremen|hamburg|france|toulouse|paris|marseille|"
    r"spain|madrid|getafe|italy|netherlands|belgium|kruibeke|switzerland|sweden|norway|denmark|"
    r"finland|poland|czech|romania|portugal|austria|\bindia\b|bangalore|bengaluru|hyderabad|"
    r"d[uü]sseldorf|cologne|k[oö]ln|stuttgart|frankfurt|china|japan|korea|singapore|australia|new zealand|auckland|brazil|mexico|morocco|tunisia|"
    r"philippines|israel|united arab emirates|\buae\b|saudi|qatar|turkey|czechia|"
    r"\[country: (?!united states)[^\]]*\]",  # added by the Workday fetcher: "Gorgonzola [country: Italy]"
    re.I,
)
US_STATES = (
    "AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ "
    "NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC"
).split()
# State codes are matched case-sensitively so "in", "or", "me" in place names don't count
US_CODE_RE = re.compile(r"\b(US|USA|" + "|".join(US_STATES) + r")\b")
US_WORD_RE = re.compile(
    r"united states|\bu\.s\.|"
    r"california|texas|washington|colorado|florida|virginia|maryland|alabama|arizona|ohio|"
    r"michigan|massachusetts|new york|new mexico|georgia|utah|connecticut|illinois|indiana|"
    r"pennsylvania|tennessee|north carolina|kansas|oklahoma|louisiana|minnesota|wisconsin|vermont",
    re.I,
)


def is_internship(title: str) -> bool:
    return bool(INTERN_RE.search(title or ""))


def is_engineering(title: str) -> bool:
    title = title or ""
    if STRONG_RE.search(title):
        return True
    return bool(ENG_RE.search(title)) and not EXCLUDE_RE.search(title)


# ---------------------------------------------------------------- mech / aero
# A mechanical or aerospace discipline in the title: always kept, even next to
# "software" or "electrical" ("Avionics Mechanical Engineering", "GNC Software").
MECH_AERO_RE = re.compile(
    r"mechanic|aerospace|\baero|aerothermal|(?<!infra)structur|stress|\bloads?\b|thermal|propulsion|"
    r"turbomachin|turbine|combustion|fluid|feed system|cryogenic|\bgnc\b|guidance|navigation|"
    r"flight dynamics|flight sciences|mechanism|material|airframe|\bcfd\b|"
    r"\bengines?\b|launch vehicle|vehicle engineer",
    re.I,
)
# Software, electrical and other non-mech/aero work: dropped unless a discipline above is named.
NOT_MECH_RE = re.compile(
    r"software|firmware|electrical|electronic|\brf\b|fpga|\bdsp\b|embedded|harness|avionics|"
    r"\bit\b|infrastructure|\bdata\b|machine learning|\bai\b|artificial intelligence|computer|"
    r"silicon|radio|backend|enterprise|test automation|optical|nuclear|reactor|civil|product design|"
    r"sourcing|supplier|business|reliability|quality|forward deployed|inspector|logistics|"
    r"learning architecture|cyber|network|power",
    re.I,
)
# Broad engineering roles a mech/aero student does: kept when nothing above rules them out.
GENERAL_MECH_RE = re.compile(
    r"manufactur|production engineer|\btest|integration|\bai&t\b|\bi&t\b|systems? engineer|"
    r"mission operations|space operations|flight operations|operations engineer|industrial engineer|"
    r"additive|r&d|hardware|spacecraft|vehicle|design engineer|robotic|physics|tooling|\bgse\b|"
    r"\bcontrols?\b|airworthiness|mission systems|mission integration|mission architecture|autonomy",
    re.I,
)
_FILLER_RE = re.compile(
    r"\b(summer|spring|fall|20\d\d|intern(ship)?s?|co-?op|graduate|undergraduate|engineer(ing)?|"
    r"and|technology|emerging|talent|new|grad|student|program|usa|us)\b|[^a-z]+",
    re.I,
)


def is_mech_aero(title: str) -> bool:
    """Mechanical / aerospace relevant: propulsion, structures, aero, thermal, GNC, test, manufacturing...

    Purely software or electrical roles are dropped. A title with no discipline at all
    ("Summer 2027 Engineering Intern") is kept, since it could be any of them.
    """
    title = title or ""
    if MECH_AERO_RE.search(title):
        return True
    if NOT_MECH_RE.search(title):
        return False
    if GENERAL_MECH_RE.search(title):
        return True
    return not _FILLER_RE.sub("", title).strip()


def is_us(location: str) -> bool:
    """Keep a posting unless its location is clearly outside the US.

    Multi-site postings ("Long Beach, CA; Toronto, Canada") are kept.
    """
    loc = (location or "").strip()
    if not loc:
        return True
    if not NON_US_RE.search(loc):
        return True
    return bool(US_CODE_RE.search(loc) or US_WORD_RE.search(loc))


def clean_location(location: str) -> str:
    """Drop the "[country: ...]" tag the Workday fetcher adds, keeping the readable part."""
    loc = re.sub(r"\s*\[country: [^\]]*\]", "", location or "").strip()
    m = re.search(r"\[country: ([^\]]*)\]", location or "")
    return loc or (m.group(1) if m else "")


TITLE_COUNTRY_RE = re.compile(
    r"[-–(,]\s*(uk|united kingdom|canada|germany|france|india|australia|japan|singapore|netherlands|belgium|italy|spain)\b",
    re.I,
)


# Postings aimed only at graduate students. A title that also says "undergraduate" is kept.
GRAD_ONLY_RE = re.compile(
    r"(?<!under)graduate\b|\bgrad(uate)? student|master'?s\b|\bm\.?s\.? (student|candidate)|"
    r"\bph\.?\s?d\b|doctoral|\bmba\b",
    re.I,
)


def is_grad_only(title: str) -> bool:
    title = title or ""
    return bool(GRAD_ONLY_RE.search(title)) and not re.search(r"undergrad", title, re.I)


def wanted(title: str, location: str, terms=()) -> bool:
    if TITLE_COUNTRY_RE.search(title or ""):  # "... Summer Internship - UK"
        return False
    if is_grad_only(title):
        return False
    return (is_internship(title) and is_engineering(title) and is_mech_aero(title)
            and is_us(location) and is_summer(title, terms))


# ---------------------------------------------------------------- season
SEASON_RE = re.compile(r"\b(summer|spring|fall|autumn|winter)\b", re.I)
# A start month with a year ("January 2027 Co-op") counts as a season too.
MONTH_SEASON = {
    "january": "winter", "february": "winter", "march": "spring", "april": "spring",
    "may": "summer", "june": "summer", "july": "summer", "august": "summer",
    "september": "fall", "october": "fall", "november": "fall", "december": "winter",
}
MONTH_RE = re.compile(r"\b(" + "|".join(MONTH_SEASON) + r")\s+20\d\d\b", re.I)


def is_summer(title: str, terms=(), today=None) -> bool:
    """Keep summer internships and ones that don't name a season.

    Drop a posting only when it names seasons and none of them is summer
    ("Spring 2027", "Fall 2026"), or when it's for a summer that has already passed.
    """
    import datetime as _dt
    today = today or _dt.date.today()
    text = " ".join([title or ""] + list(terms or []))
    seasons = {m.lower() for m in SEASON_RE.findall(text)}
    seasons |= {MONTH_SEASON[m.lower()] for m in MONTH_RE.findall(text)}
    if seasons and "summer" not in seasons:
        return False
    if "summer" in seasons:
        years = [int(y) for y in re.findall(r"20\d\d", text)]
        if years and max(years) < today.year or (years and max(years) == today.year and today.month > 8):
            return False
    return True


# ---------------------------------------------------------------- location
CA_RE = re.compile(
    r"\bCA\b|california|los angeles|(?<!, )\bLA\b|san francisco|\bSF\b|south sf|bay area|long beach|hawthorne|"
    r"el segundo|torrance|irvine|costa mesa|newport beach|huntington beach|santa ana|san diego|carlsbad|"
    r"san jose|mountain view|sunnyvale|palo alto|santa clara|fremont|pasadena|redondo|playa vista|"
    r"culver city|mojave|vandenberg|simi valley|moorpark|petaluma|san luis obispo|marina|santa cruz|"
    r"goleta|seal beach|victorville|lancaster|palmdale",
    re.I,
)


def split_locations(location: str) -> list:
    loc = clean_location(location)
    parts = [p.strip() for p in re.split(r";|\||\n| / ", loc) if p.strip()]
    return parts or ([loc] if loc else [])


def pick_location(location: str) -> str:
    """One location to show: a California one if offered there, otherwise the first one."""
    parts = split_locations(location)
    if not parts:
        return ""
    for p in parts:
        if CA_RE.search(p):
            return p
    for p in parts:  # otherwise the first US location, so a US role never shows "Derby" or "Düsseldorf"
        if not NON_US_RE.search(p):
            return p
    return parts[0]


def is_california(location: str) -> bool:
    return any(CA_RE.search(p) for p in split_locations(location))


def same_role_key(company: str, title: str) -> str:
    """Postings with this same key are the same role offered in different places."""
    t = re.sub(r"[^a-z0-9]+", " ", (title or "").lower()).strip()
    return f"grp:{company.lower()}|{t}"
