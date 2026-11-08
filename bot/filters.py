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
    r"economist|economics|strategy|product manag|program manag|project manag",
    re.I,
)

NON_US_RE = re.compile(
    r"canada|toronto|montr[eé]al|vancouver|ottawa|quebec|ontario|british columbia|"
    r"united kingdom|\buk\b|england|scotland|wales|ireland|bristol|london|filton|derby|"
    r"germany|deutschland|berlin|munich|m[uü]nchen|bremen|hamburg|france|toulouse|paris|marseille|"
    r"spain|madrid|getafe|italy|netherlands|belgium|kruibeke|switzerland|sweden|norway|denmark|"
    r"finland|poland|czech|romania|portugal|austria|india|bangalore|bengaluru|hyderabad|"
    r"china|japan|korea|singapore|australia|new zealand|auckland|brazil|mexico|morocco|tunisia|"
    r"philippines|israel|united arab emirates|\buae\b|saudi|qatar|turkey",
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


def wanted(title: str, location: str) -> bool:
    return is_internship(title) and is_engineering(title) and is_us(location)
