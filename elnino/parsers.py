"""Parsers for the fixed-width / whitespace ASCII products CPC and PSL publish.

Each parser is defensive: NOAA pads unreported months with -999 sentinels,
glues negative numbers onto the preceding column, and occasionally appends
explanatory prose to the bottom of a data file.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from datetime import date

MISSING = -99.0  # anything at or below this is a NOAA fill value

# Three-month overlapping seasons, in order. Index + 1 == centre month.
ONI_SEASONS = ["DJF", "JFM", "FMA", "MAM", "AMJ", "MJJ", "JJA", "JAS", "ASO", "SON", "OND", "NDJ"]
# Two-month seasons used by MEI.v2, in order.
MEI_SEASONS = ["DJ", "JF", "FM", "MA", "AM", "MJ", "JJ", "JA", "AS", "SO", "ON", "ND"]

MONTH_ABBR = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}

FLOAT_RE = re.compile(r"[-+]?\d+\.\d+")
WEEK_RE = re.compile(r"^\s*(\d{2})([A-Z]{3})(\d{4})\s+(.*)$")


@dataclass(frozen=True)
class SeasonValue:
    """One 3-month (ONI/RONI) or 2-month (MEI) season."""

    season: str
    year: int
    value: float

    @property
    def label(self) -> str:
        return f"{self.season} {self.year}"

    @property
    def centre(self) -> date:
        """Centre month of the season, used only for ordering and plotting."""
        if self.season in ONI_SEASONS:
            return date(self.year, ONI_SEASONS.index(self.season) + 1, 1)
        return date(self.year, MEI_SEASONS.index(self.season) + 1, 1)


@dataclass(frozen=True)
class MonthValue:
    year: int
    month: int
    value: float

    @property
    def label(self) -> str:
        return f"{date(self.year, self.month, 1):%b %Y}"


@dataclass(frozen=True)
class WeekObservation:
    week_ending: date
    nino12_sst: float
    nino12_anom: float
    nino3_sst: float
    nino3_anom: float
    nino34_sst: float
    nino34_anom: float
    nino4_sst: float
    nino4_anom: float

    @property
    def label(self) -> str:
        return f"{self.week_ending:%d %b %Y}"


def _valid(value: float) -> bool:
    return value > MISSING


def parse_oni(text: str) -> list[SeasonValue]:
    """oni.ascii.txt -- columns: SEAS YR TOTAL ANOM."""
    out: list[SeasonValue] = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) != 4 or parts[0] not in ONI_SEASONS:
            continue
        try:
            year, anomaly = int(parts[1]), float(parts[3])
        except ValueError:
            continue
        if _valid(anomaly):
            out.append(SeasonValue(parts[0], year, anomaly))
    out.sort(key=lambda s: s.centre)
    return out


def parse_roni(text: str) -> list[SeasonValue]:
    """RONI.ascii.txt -- columns: SEAS YR ANOM."""
    out: list[SeasonValue] = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) != 3 or parts[0] not in ONI_SEASONS:
            continue
        try:
            year, anomaly = int(parts[1]), float(parts[2])
        except ValueError:
            continue
        if _valid(anomaly):
            out.append(SeasonValue(parts[0], year, anomaly))
    out.sort(key=lambda s: s.centre)
    return out


def parse_weekly_sst(text: str) -> list[WeekObservation]:
    """wksst9120.for -- fixed width; negative anomalies glue to the SST column.

    A line looks like ' 30DEC2020     22.2-1.3     24.4-0.9 ...', which yields
    eight signed decimals once the date prefix is stripped.
    """
    out: list[WeekObservation] = []
    for line in text.splitlines():
        match = WEEK_RE.match(line)
        if not match:
            continue
        day, mon, year, rest = match.groups()
        if mon not in MONTH_ABBR:
            continue
        values = [float(v) for v in FLOAT_RE.findall(rest)]
        if len(values) != 8:
            continue
        try:
            when = date(int(year), MONTH_ABBR[mon], int(day))
        except ValueError:
            continue
        out.append(WeekObservation(when, *values))
    out.sort(key=lambda w: w.week_ending)
    return out


def parse_monthly_sst(text: str) -> dict[str, list[MonthValue]]:
    """sstoi.indices -- YR MON NINO1+2 ANOM NINO3 ANOM NINO4 ANOM NINO3.4 ANOM."""
    regions: dict[str, list[MonthValue]] = {"nino12": [], "nino3": [], "nino4": [], "nino34": []}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) != 10:
            continue
        try:
            year, month = int(parts[0]), int(parts[1])
            numbers = [float(p) for p in parts[2:]]
        except ValueError:
            continue
        if not 1 <= month <= 12:
            continue
        # anomalies sit at indices 1, 3, 5, 7 of the numeric tail
        for name, index in (("nino12", 1), ("nino3", 3), ("nino4", 5), ("nino34", 7)):
            if _valid(numbers[index]):
                regions[name].append(MonthValue(year, month, numbers[index]))
    for series in regions.values():
        series.sort(key=lambda m: (m.year, m.month))
    return regions


def parse_soi(text: str) -> dict[str, list[MonthValue]]:
    """CPC soi file -- two stacked tables: raw ANOMALY then STANDARDIZED DATA.

    The standardized table is the one normally quoted, so both are returned and
    the caller picks. Values run together ('-1.1-999.9'), so the year is taken
    from the line prefix and the remainder is regex-scanned.
    """
    tables: list[list[MonthValue]] = []
    current: list[MonthValue] = []
    started = False
    for line in text.splitlines():
        if re.match(r"^\s*YEAR\s+JAN", line):
            if started and current:
                tables.append(current)
            current, started = [], True
            continue
        if not started:
            continue
        match = re.match(r"^(\d{4})(.*)$", line)
        if not match:
            continue
        year = int(match.group(1))
        values = [float(v) for v in FLOAT_RE.findall(match.group(2))]
        if len(values) != 12:
            continue
        for month, value in enumerate(values, start=1):
            if _valid(value):
                current.append(MonthValue(year, month, value))
    if current:
        tables.append(current)

    for series in tables:
        series.sort(key=lambda m: (m.year, m.month))
    result = {"anomaly": tables[0] if tables else []}
    result["standardized"] = tables[1] if len(tables) > 1 else result["anomaly"]
    return result


def parse_mei(text: str) -> list[SeasonValue]:
    """meiv2.data -- first line is the year range, then YEAR + 12 bimonthly values."""
    out: list[SeasonValue] = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) != 13:
            continue
        try:
            year = int(parts[0])
            values = [float(p) for p in parts[1:]]
        except ValueError:
            continue
        if not 1900 < year < 2200:
            continue
        for season, value in zip(MEI_SEASONS, values):
            if _valid(value):
                out.append(SeasonValue(season, year, value))
    out.sort(key=lambda s: s.centre)
    return out


ALERT_PHRASE = re.compile(
    r"(?i)\b((?:Final\s+)?(?:El Nino|La Nina)\s+(?:Advisory|Watch))\b"
)
ALERT_STATUS = re.compile(
    r"(?i)not active|(?:final\s+)?(?:el nino|la nina)\s+(?:advisory|watch)"
    r"(?:\s*/\s*(?:final\s+)?(?:el nino|la nina)\s+(?:advisory|watch))*"
)


def parse_discussion(text: str) -> dict[str, str]:
    """Strip the CPC discussion page down to its issue date, status and prose."""
    body = re.sub(r"(?is)<(script|style).*?</\1>", " ", text)
    body = re.sub(r"(?s)<!--.*?-->", " ", body)
    body = re.sub(r"(?i)<br\s*/?>|</p>|</tr>|</div>", "\n", body)
    body = re.sub(r"<[^>]+>", " ", body)
    body = html.unescape(body)
    body = body.replace(" ", " ").replace("ñ", "n")
    body = re.sub(r"\s*°\s*C\b", "°C", body).replace("°", "°")
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in body.splitlines()]
    lines = [ln for ln in lines if ln]

    issued = ""
    for line in lines:
        match = re.match(r"^(\d{1,2} [A-Z][a-z]+ \d{4})$", line)
        if match:
            issued = match.group(1)
            break

    # The page ends with a standing boilerplate block (who writes the discussion,
    # the mailing-list address, the CPC postal address). It is long enough to look
    # like analysis, so drop it explicitly.
    boilerplate = re.compile(
        r"(?i)consolidated effort|mailing list|to receive an e-mail|university research court|"
        r"page last modified|freedom of information"
    )
    paragraphs = [ln for ln in lines if len(ln) > 180 and not boilerplate.search(ln)]

    # Page chrome (title bar, nav, mailing-list blurb) also mentions ENSO, so the
    # synopsis is taken as the first real sentence about the state of the system.
    chrome = re.compile(
        r"(?i)diagnostic discussion|prediction center:|site map|climate prediction|"
        r"^home$|noaa\.gov|e-mail|search"
    )
    synopsis = ""
    for line in lines:
        if not 40 < len(line) <= 500 or chrome.search(line):
            continue
        if re.match(r"(?i)^(el nin|la nin|enso|there is|transition|during)", line) and line.endswith("."):
            synopsis = line
            break

    next_update = ""
    for line in lines:
        match = re.search(r"(?i)next ENSO Diagnostics? Discussion is scheduled for ([^.]+)\.", line)
        if match:
            next_update = match.group(1).strip()
            break

    # CPC states the status on one labelled line, and it can say things a
    # keyword search reads wrongly: "Final El Nino Advisory" contains "El Nino
    # Advisory", "Not Active" contains nothing, and a transition carries two
    # statuses at once. So the labelled line is read first and whole.
    status = ""
    for index, line in enumerate(lines):
        match = re.search(r"(?i)ENSO Alert System Status:?\s*(.*)$", line)
        if not match:
            continue
        text = match.group(1).strip() or (
            lines[index + 1].strip() if index + 1 < len(lines) else "")
        if ALERT_STATUS.fullmatch(text):
            status = re.sub(r"\s*/\s*", " / ", text).title()
        break
    if not status:
        for line in lines:
            match = ALERT_PHRASE.search(line)
            if match:
                status = re.sub(r"\s+", " ", match.group(1)).title()
                break
    if not status and synopsis:
        lowered = synopsis.lower()
        if "el nin" in lowered:
            status = "El Nino conditions (per CPC synopsis)"
        elif "la nin" in lowered:
            status = "La Nina conditions (per CPC synopsis)"
        elif "neutral" in lowered:
            status = "ENSO-neutral (per CPC synopsis)"

    return {
        "issued": issued,
        "status": status,
        "synopsis": synopsis,
        "body": "\n\n".join(paragraphs[:4]),
        "next_update": next_update,
    }


# ---------------------------------------------------------------------------
# CPC stacked monthly grids
#
# A family of CPC files (olr, cpac850, qbo.u30.index, zwnd200, darwin, tahiti,
# soi, ...) share one layout: a title line, a section name, a blank, a
# "YEAR JAN FEB ..." header, then one row per year of twelve 6-character
# fields. The same file then repeats that structure two more times for the
# ANOMALY and STANDARDIZED versions of the same quantity.
#
# Two things make naive parsing wrong:
#   * negative values fill their whole field, so the year glues to the first
#     value ("2032-999.9-999.9...");
#   * the fill value is -999.9 in most files but +999.9 in reqsoi.for, so a
#     "greater than -99" test silently admits 999.9 as real data.
# ---------------------------------------------------------------------------

GRID_FILL = 900.0  # |value| >= this is a fill, whatever its sign
GRID_SECTION_RE = re.compile(r"\b(ORIGINAL|ANOMALY|STANDARDIZED|CLIMATOLOGY)\b", re.I)
GRID_HEADER_RE = re.compile(r"^\s*YEAR\s+JAN\s+FEB", re.I)
GRID_YEAR_RE = re.compile(r"^\s*(\d{4})(?=[-\s\d])")


def _grid_valid(value: float) -> bool:
    return abs(value) < GRID_FILL


def parse_cpc_grid(text: str) -> dict[str, list[MonthValue]]:
    """Split a stacked CPC monthly grid into its named sections.

    Returns an insertion-ordered mapping of section name (lowercased, e.g.
    ``"original"`` / ``"anomaly"`` / ``"standardized"``) to month values. Files
    with no headers at all (reqsoi.for) come back as a single ``"data"``
    section, so every caller can use the same shape.
    """
    sections: dict[str, list[MonthValue]] = {}
    pending_label: str | None = None
    current: list[MonthValue] | None = None

    for line in text.splitlines():
        if GRID_HEADER_RE.match(line):
            label = (pending_label or f"section_{len(sections) + 1}").lower()
            # A file may repeat a section name; keep the first, number the rest.
            if label in sections:
                label = f"{label}_{len(sections) + 1}"
            current = []
            sections[label] = current
            pending_label = None
            continue

        year_match = GRID_YEAR_RE.match(line)
        if year_match:
            year = int(year_match.group(1))
            if not 1800 < year < 2200:
                continue
            if current is None:
                current = sections.setdefault("data", [])
            values = FLOAT_RE.findall(line[year_match.end():])
            for index, token in enumerate(values[:12]):
                value = float(token)
                if _grid_valid(value):
                    current.append(MonthValue(year, index + 1, value))
            continue

        found = GRID_SECTION_RE.search(line)
        if found and not any(char.isdigit() for char in line):
            pending_label = found.group(1)

    return sections


def grid_section(
    sections: dict[str, list[MonthValue]], *preferred: str
) -> list[MonthValue]:
    """First matching section, else the last one in the file, else empty.

    The standardized table is normally the one to quote, but not every file
    ships one; falling back to the final section keeps callers simple because
    CPC always orders these coarse-to-derived.
    """
    for name in preferred:
        if sections.get(name):
            return sections[name]
    for values in reversed(list(sections.values())):
        if values:
            return values
    return []


# ---------------------------------------------------------------------------
# PMEL warm water volume
# ---------------------------------------------------------------------------

# PMEL writes Fortran-style floats, including "-.4883405E+14" with no leading
# zero. float() accepts those; the point is that they are not fixed-width.
WWV_ROW_RE = re.compile(r"^\s*(\d{4})(\d{2})\s+(\S+)\s+(\S+)\s*$")
WWV_SCALE = 1.0e14  # WWV anomalies are conventionally quoted in 10^14 m^3


@dataclass(frozen=True)
class WwvObservation:
    year: int
    month: int
    volume: float  # 10^14 m^3
    anomaly: float  # 10^14 m^3

    @property
    def label(self) -> str:
        return f"{date(self.year, self.month, 1):%b %Y}"

    @property
    def month_value(self) -> MonthValue:
        return MonthValue(self.year, self.month, self.anomaly)


def parse_wwv(text: str) -> list[WwvObservation]:
    """wwv.dat / wwv_west.dat -- 'YYYYMM volume anomaly' in m^3."""
    out: list[WwvObservation] = []
    for line in text.splitlines():
        match = WWV_ROW_RE.match(line)
        if not match:
            continue
        year, month = int(match.group(1)), int(match.group(2))
        if not (1800 < year < 2200 and 1 <= month <= 12):
            continue
        try:
            volume = float(match.group(3)) / WWV_SCALE
            anomaly = float(match.group(4)) / WWV_SCALE
        except ValueError:
            continue
        out.append(WwvObservation(year, month, volume, anomaly))
    out.sort(key=lambda obs: (obs.year, obs.month))
    return out


# ---------------------------------------------------------------------------
# Relative (tropical-mean-adjusted) SST products
# ---------------------------------------------------------------------------

# The weekly and monthly relative files do NOT use the same column order.
# Weekly: 1+2, 3, 3.4, 4.   Monthly: 1+2, 3, 4, 3.4.
REL_WEEKLY_ORDER = ("nino12", "nino3", "nino34", "nino4")
REL_MONTHLY_ORDER = ("nino12", "nino3", "nino4", "nino34")


def parse_rel_weekly(text: str) -> list[tuple[date, dict[str, float]]]:
    """rel_wksst9120.txt -- week-ending date then four relative anomalies."""
    out: list[tuple[date, dict[str, float]]] = []
    for line in text.splitlines():
        match = WEEK_RE.match(line)
        if not match:
            continue
        day, abbr, year, rest = match.groups()
        if abbr not in MONTH_ABBR:
            continue
        values = [float(token) for token in FLOAT_RE.findall(rest)]
        if len(values) < 4:
            continue
        week = date(int(year), MONTH_ABBR[abbr], int(day))
        regions = {
            name: value
            for name, value in zip(REL_WEEKLY_ORDER, values[:4])
            if _grid_valid(value)
        }
        out.append((week, regions))
    out.sort(key=lambda row: row[0])
    return out


def parse_rel_monthly(text: str) -> dict[str, list[MonthValue]]:
    """rel_mthsst9120.txt -- YEAR MON rNINO1+2 rNINO3 rNINO4 rNINO3.4.

    Note the column order: Nino-3.4 is last here and third in the weekly file.
    """
    regions: dict[str, list[MonthValue]] = {name: [] for name in REL_MONTHLY_ORDER}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) != 6:
            continue
        try:
            year, month = int(parts[0]), int(parts[1])
            values = [float(token) for token in parts[2:]]
        except ValueError:
            continue
        if not (1800 < year < 2200 and 1 <= month <= 12):
            continue
        for name, value in zip(REL_MONTHLY_ORDER, values):
            if _grid_valid(value):
                regions[name].append(MonthValue(year, month, value))
    return regions


def parse_yr_mon_anom(text: str, column: int = 2, width: int = 3) -> list[MonthValue]:
    """Rnino34.ascii.txt (YR MTH ANOM) and friends.

    ``column`` is the zero-based index of the anomaly and ``width`` the exact
    token count of a data row, so the same routine reads the detrended file
    (YR MON TOTAL ClimAdjust ANOM) by passing ``column=4, width=5``.
    """
    out: list[MonthValue] = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) != width:
            continue
        try:
            year, month = int(parts[0]), int(parts[1])
            value = float(parts[column])
        except ValueError:
            continue
        if not (1800 < year < 2200 and 1 <= month <= 12):
            continue
        if _grid_valid(value):
            out.append(MonthValue(year, month, value))
    return out


def parse_atlantic_indices(text: str) -> dict[str, list[MonthValue]]:
    """sstoi.atl.indices -- YR MON NATL ANOM SATL ANOM TROP ANOM.

    The tropical Atlantic matters here because a warm Atlantic opposes the
    Pacific Walker-cell response and is one reason ONI and RONI diverge.
    """
    regions: dict[str, list[MonthValue]] = {"natl": [], "satl": [], "trop": []}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) != 8:
            continue
        try:
            year, month = int(parts[0]), int(parts[1])
            values = [float(token) for token in parts[2:]]
        except ValueError:
            continue
        if not (1800 < year < 2200 and 1 <= month <= 12):
            continue
        for name, value in zip(("natl", "satl", "trop"), values[1::2]):
            if _grid_valid(value):
                regions[name].append(MonthValue(year, month, value))
    return regions


# ---------------------------------------------------------------------------
# CPC MJO index (200 hPa velocity potential projections, pentad)
# ---------------------------------------------------------------------------

MJO_FILL_RE = re.compile(r"\*+")


def parse_mjo(text: str) -> dict[str, list[tuple[date, float]]]:
    """proj_norm_order.ascii -- ten longitude bands, one row per pentad.

    Keys are the longitude labels from the file's second header line
    ('20E', '70E', ..., '120W', '40W', '10W'). Undefined pentads are '*****'.
    """
    lines = text.splitlines()
    longitudes: list[str] = []
    for line in lines[:5]:
        if "PENTAD" in line.upper():
            longitudes = line.split()[1:]
            break
    if not longitudes:
        return {}

    series: dict[str, list[tuple[date, float]]] = {name: [] for name in longitudes}
    for line in lines:
        parts = line.split()
        if len(parts) != len(longitudes) + 1 or len(parts[0]) != 8:
            continue
        try:
            stamp = date(int(parts[0][:4]), int(parts[0][4:6]), int(parts[0][6:]))
        except ValueError:
            continue
        for name, token in zip(longitudes, parts[1:]):
            if MJO_FILL_RE.fullmatch(token):
                continue
            try:
                series[name].append((stamp, float(token)))
            except ValueError:
                continue
    return {name: values for name, values in series.items() if values}
