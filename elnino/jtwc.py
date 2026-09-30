"""The Joint Typhoon Warning Center: the storms NHC does not warn on.

NHC and CPHC cover the Atlantic and the Pacific east of 180. West of the
date line and south of the equator - west Pacific typhoons, Bay of Bengal
and Arabian Sea cyclones, the southern Indian Ocean and the south Pacific -
JTWC warns for US interests, beside the regional centres (JMA, IMD, Meteo-
France La Reunion, BoM, Fiji) that warn for everyone else. JTWC is the
source here because it publishes one open format across all of it, and
because its winds are one-minute means like NHC's: a Saffir-Simpson
category is then a like-for-like comparison, where a regional centre's
ten-minute wind reads lower for the same storm.

A warning is the ``.tcw`` file, the "JMV 3.0 data" link in the RSS feed.
Its third line is the warning time, the storm id and name and the warning
number. The ``T`` lines are the forecast, hour 0 being the warning
position, each with its 34, 50 and 64 kt radii by quadrant. Remarks after
``AMP`` say when the storm is forecast to become extratropical or
dissipate. After ``//`` come the storm's past positions, six-hourly, as
``NNYYMMDDHH LATLON WIND``.

Two traps. A southern-hemisphere season runs July to June and JTWC's ids
carry the year it ends, so a cyclone in October 2026 is ``sh0127``; the
year is taken from the file name when there is one and from the warning
time only when there is not. And a position is ``158S 0712E``: the letter
is the sign, and a reader that drops it puts a south Indian Ocean cyclone
in the Arabian Sea.

The advisories (``ABPW10`` for the west and south Pacific, ``ABIO10`` for
the Indian Ocean) are prose. Each suspect area is a numbered paragraph under
"TROPICAL DISTURBANCE SUMMARY", with where it is "now located near", its
potential for a significant tropical cyclone within 24 hours, and a
reference to the formation alert (``WTPN2x``, ``WTIO2x``, ``WTXS2x``) when
one is out.

The formation alert itself is a ``.tcw`` file too, linked from the RSS feed
beside the warnings (``wp9326.tcw`` for Invest 93W), but in ATCF's "ALERT"
format: a header of numbers, then the message in prose - formation "is
possible within 120 NM either side of a line from" one point to another,
where the system is and how it moves, its winds and pressure, and the time
by which the alert will be reissued, upgraded to a warning or cancelled -
and the invest's past positions. A cancellation comes in the same format.
The prose is read rather than the header, whose signs for the southern and
western hemispheres no sample shows.
"""

from __future__ import annotations

import math
import re
from dataclasses import replace
from datetime import datetime

from .cyclones import Fix, Storm, _tenths
from .outlook import Disturbance, FormationAlert, aor

# The id's letter is the ocean: W west Pacific, A and B the Arabian Sea and
# Bay of Bengal, S and P the south Indian Ocean and south Pacific.
_BASIN_OF_LETTER = {"W": "WP", "A": "IO", "B": "IO", "S": "SH", "P": "SH",
                    "E": "EP", "C": "CP", "L": "AL"}
# The warning files for the oceans NHC does not cover. JTWC also mirrors
# NHC's storms (``ep1526.tcw``); NHC is the authority on those.
_FILE = re.compile(r"\b((?:wp|io|sh)\d{4}\.tcw)\b", re.I)
_NAMED_FILE = re.compile(r"\b(?:wp|io|sh)(\d\d)(\d\d)\.tcw\b", re.I)

_HEADER = re.compile(r"^(?P<dtg>\d{10})\s+(?P<num>\d\d)(?P<letter>[A-Z])\s+"
                     r"(?P<name>.+?)\s+(?P<warning>\d{3})\b", re.M)
_WMO = re.compile(r"^[A-Z]{4}\d\d\s+[A-Z]{4}\s+(\d{6})", re.M)
_T_LINE = re.compile(r"^T(\d{3})\s+(\d{2,3}[NS])\s+(\d{3,4}[EW])\s+(\d{3})(.*)$", re.M)
_RADII = re.compile(r"R(\d{3})\s+(\d{3})\s+NE\s+QD\s+(\d{3})\s+SE\s+QD\s+"
                    r"(\d{3})\s+SW\s+QD\s+(\d{3})\s+NW\s+QD")
# A three-digit longitude is padded with a space: "145N 997E".
_HISTORY = re.compile(r"^(\d\d)(\d{8})\s+(\d{2,3}[NS])\s*(\d{3,4}[EW])\s+(\d+)", re.M)
_REMARK = re.compile(r"^\s*(\d+)HR\s+(.*)$")
_MOTION = re.compile(r"MOVEMENT PAST SIX HOURS\s+-\s+(\d+)\s+DEGREES\s+AT\s+(\d+)\s+KTS")
_ACCURACY = re.compile(r"POSITION ACCURATE TO WITHIN\s+(\d+)\s+NM")
_PRESSURE = re.compile(r"MINIMUM\s+CENTRAL\s+PRESSURE\s+AT\s+(\d{4})\d\dZ\s+IS\s+(\d+)\s+MB")


def warning_files(rss: str) -> list[str]:
    """The ``.tcw`` warning files the RSS feed links, west Pacific, Indian
    Ocean and southern hemisphere only, in the order it lists them."""
    out: list[str] = []
    for match in _FILE.finditer(rss):
        name = match.group(1).lower()
        if name not in out:
            out.append(name)
    return out


def _stage(wind: int | None, basin: str) -> str:
    """JTWC's name for a stage, from the wind: TD, TS, then TY/ST or TC."""
    if wind is None or wind < 34:
        return "TD"
    if wind < 64:
        return "TS"
    if basin == "WP":
        return "ST" if wind >= 130 else "TY"
    return "TC"


def _radii(text: str) -> tuple:
    found = {}
    for match in _RADII.finditer(text):
        threshold = int(match.group(1))
        quadrants = tuple(int(match.group(i)) for i in range(2, 6))
        # As in ATCF, four zeros is no analysis rather than a calm storm.
        if threshold in (34, 50, 64) and any(quadrants):
            found.setdefault(threshold, quadrants)
    return tuple(sorted(found.items()))


def _remarks(text: str) -> dict[int, str]:
    """Forecast hour -> stage from the AMP remarks (extratropical, dissipating)."""
    out: dict[int, str] = {}
    lines = text.splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line.strip() == "AMP")
    except StopIteration:
        return out
    for line in lines[start + 1:]:
        if line.startswith("SUBJ") or line.startswith("//"):
            break
        found = _REMARK.match(line)
        if not found:
            continue
        words = found.group(2).upper()
        if "EXTRATROPICAL" in words:
            out[int(found.group(1))] = "EX"
        elif "DISSIPAT" in words:
            out[int(found.group(1))] = "DS"
    return out


def _issued(ddhhmm: str, dtg: str) -> str:
    """The WMO header's day and time as an ISO stamp, in the month of ``dtg``
    or the next one when the warning went out after the month turned."""
    base = datetime.strptime(dtg, "%Y%m%d%H")
    day, hour, minute = int(ddhhmm[:2]), int(ddhhmm[2:4]), int(ddhhmm[4:6])
    year, month = base.year, base.month
    if day < base.day:
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    try:
        return datetime(year, month, day, hour, minute).strftime("%Y-%m-%dT%H:%M:00Z")
    except ValueError:
        return ""


def parse_tcw(text: str, url: str = "") -> Storm | None:
    """One JTWC warning as a storm: its past positions, the warning position
    with its wind radii, and the forecast. None if the text is not one."""
    header = _HEADER.search(text)
    if header is None:
        return None
    dtg = header.group("dtg")
    basin = _BASIN_OF_LETTER.get(header.group("letter"))
    if basin is None:
        return None
    number = int(header.group("num"))
    named = _NAMED_FILE.search(url)
    year = 2000 + int(named.group(2)) if named else int(dtg[:4])
    name = header.group("name").strip().title()

    ends = _remarks(text)
    pressure = _PRESSURE.search(text)
    now_pressure = (int(pressure.group(2))
                    if pressure and pressure.group(1) == dtg[6:10] else None)

    history: dict[str, Fix] = {}
    for match in _HISTORY.finditer(text):
        lat, lon = _tenths(match.group(3)), _tenths(match.group(4))
        if lat is None or lon is None:
            continue
        stamp = "20" + match.group(2)
        wind = int(match.group(5))
        history[stamp] = Fix(stamp=stamp, tau=0, lat=lat, lon=lon, wind=wind,
                             pressure=None, stage=_stage(wind, basin), tech="JTWC")

    forecast: list[Fix] = []
    for match in _T_LINE.finditer(text):
        lat, lon = _tenths(match.group(2)), _tenths(match.group(3))
        if lat is None or lon is None:
            continue
        tau, wind = int(match.group(1)), int(match.group(4))
        stage = _stage(wind, basin)
        for hour in sorted(ends):
            if tau >= hour:
                stage = ends[hour]
        fix = Fix(stamp=dtg, tau=tau, lat=lat, lon=lon, wind=wind,
                  pressure=now_pressure if tau == 0 else None, stage=stage,
                  tech="JTWC", radii=_radii(match.group(5)))
        if tau == 0:
            history[dtg] = fix     # the warning position, radii and all
        else:
            forecast.append(fix)
    if not history:
        return None
    track = tuple(history[stamp] for stamp in sorted(history))
    now = track[-1]

    motion = _MOTION.search(text)
    accuracy = _ACCURACY.search(text)
    wmo = _WMO.search(text)
    page = url[:-len(".tcw")] if url.lower().endswith(".tcw") else ""
    advisory = {
        "name": name,
        "classification": now.stage,
        "wind": now.wind,
        "pressure": now.pressure,
        "lat": now.lat,
        "lon": now.lon,
        "movement_dir": int(motion.group(1)) if motion else None,
        "movement_kt": int(motion.group(2)) if motion else None,
        "accuracy_nm": int(accuracy.group(1)) if accuracy else None,
        "last_update": _issued(wmo.group(1), dtg) if wmo else "",
        "advisory": str(int(header.group("warning"))),
        "discussion": page + "prog.txt" if page else "",
        "public": page + "web.txt" if page else "",
    }
    return Storm(basin=basin, number=number, year=year, name=name,
                 track=track, forecast=tuple(forecast), advisory=advisory,
                 centre="JTWC")


_SUMMARY = re.compile(r"TROPICAL DISTURBANCE SUMMARY:(.*?)"
                      r"(?=\b[A-Z]\.\s+[A-Z ]*SUMMARY:|\b\d\.\s+[A-Z][A-Z ]+ AREA\b|NNNN|$)")
_LATLON = r"(\d{1,2}(?:\.\d+)?)([NS])\s+(\d{1,3}(?:\.\d+)?)([EW])"
_NOW = re.compile(r"NOW LOCATED NEAR\s+" + _LATLON)
_NEAR = re.compile(r"NEAR\s+" + _LATLON)
_INVEST = re.compile(r"INVEST\s+(\d\d[A-Z])\b")
_ALERT = re.compile(r"\bWT(?:PN|IO|XS)2\d\b")
_CHANCE = re.compile(r"POTENTIAL FOR THE DEVELOPMENT(.*?)\.(?:\s|$)")
# What JTWC writes of an area it has stopped watching: it dissipated, or it
# became a numbered storm, whose own warnings carry it on.
_GONE = re.compile(r"\b(?:DISSIPATED|NO LONGER SUSPECT|DEVELOPED INTO|CONSOLIDATED INTO|"
                   r"UPGRADED TO (?:A )?(?:TROPICAL (?:DEPRESSION|STORM|CYCLONE \d)|"
                   r"(?:SUPER )?TYPHOON|CYCLONE \d))")
_PERIOD = re.compile(r"/(\d\d)(\d\d)(\d\d)Z-(\d\d)\d{4}Z([A-Z]{3})(\d{4})")
_MONTHS = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN",
           "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")


def advisory_time(text: str) -> str:
    """When an advisory's validity starts, ``210600Z-220600ZSEP2026``, as ISO."""
    found = _PERIOD.search(" ".join(text.split()))
    if not found or found.group(5) not in _MONTHS:
        return ""
    day, hour, minute, end_day = (int(found.group(i)) for i in range(1, 5))
    month, year = _MONTHS.index(found.group(5)) + 1, int(found.group(6))
    if day > end_day:     # it began in the month before the one named
        year, month = (year - 1, 12) if month == 1 else (year, month - 1)
    try:
        return datetime(year, month, day, hour, minute).strftime("%Y-%m-%dT%H:%M:00Z")
    except ValueError:
        return ""


def disturbances(text: str) -> list[Disturbance]:
    """Every suspect area in a JTWC significant tropical weather advisory.

    Text that is not such an advisory - an error page served in its place -
    raises ValueError: it was not read, which is not an advisory with nothing
    suspect in it.
    """
    words = " ".join(text.split())
    if "SIGNIFICANT TROPICAL WEATHER ADVISORY" not in words.upper():
        raise ValueError("not a JTWC significant tropical weather advisory")
    issued = advisory_time(words)
    out: list[Disturbance] = []
    for section, summary in enumerate(_SUMMARY.finditer(words), start=1):
        paragraphs = re.split(r"\(\d+\)\s", summary.group(1))
        for number, paragraph in enumerate((p.strip() for p in paragraphs), start=1):
            where = _NOW.search(paragraph) or _NEAR.search(paragraph)
            if not paragraph or where is None:
                continue
            lat = float(where.group(1)) * (-1.0 if where.group(2) == "S" else 1.0)
            lon = float(where.group(3)) * (-1.0 if where.group(4) == "W" else 1.0)
            chance = _CHANCE.search(paragraph)
            levels = re.findall(r"\b(LOW|MEDIUM|HIGH)\b", chance.group(1)) if chance else []
            # Only an area JTWC still rates is being watched; the paragraph on
            # one it has stopped watching gives its last position, not a live one.
            if not levels or _GONE.search(paragraph):
                continue
            invest = _INVEST.search(paragraph)
            out.append(Disturbance(
                centre="JTWC",
                basin=aor(lon, lat),
                label=f"Invest {invest.group(1)}" if invest else "Area of convection",
                lon=lon,
                lat=lat,
                chance_2day=None,
                chance_7day=None,
                potential=levels[-1].lower() if levels else "",
                text=paragraph,
                area=(),
                arrow=(),
                alert=bool(_ALERT.search(paragraph)),
                issued=issued,
                key=invest.group(1).lower() if invest else f"jtwc{section}-{number}",
            ))
    return out


# An alert is known by its ATCF header ("ALERT ATCF MIL 93X ...") or its
# subject line, never by the word: a numbered storm's first warning says it
# "supersedes and cancels" the alert, is still a warning, and JTWC's wrap at
# 66 columns can start one of its lines with "ALERT".
_TCFA = re.compile(r"^(?:ALERT\s+ATCF\b|SUBJ/TROPICAL CYCLONE FORMATION ALERT)", re.M)
_CANCELLATION = re.compile(r"^SUBJ/TROPICAL CYCLONE FORMATION ALERT\b[^\n]*\bCANCELLATION\b",
                           re.M)
_CANCELS = re.compile(r"\bTHIS CANCELS REF\b")
_DTG = re.compile(r"^(20\d{8})\s*$", re.M)
_ALERT_ID = re.compile(r"^ALERT\s+ATCF\s+\S+\s+(\d\d)[A-Z]\b", re.M)
_ALERT_FILE = re.compile(r"\b(wp|io|sh)(\d\d)\d\d\.tcw\b", re.I)
_WMO_CODE = re.compile(r"^WT(PN|IO|XS|PS)\d\d\s", re.M)
_LINE = re.compile(r"(\d+)\s+NM\s+EITHER\s+SIDE\s+OF\s+A\s+LINE\s+FROM\s+" + _LATLON
                   + r"\s+TO\s+" + _LATLON)
_RADIUS = re.compile(r"(\d+)\s+NM\s+RADIUS\s+OF\s+" + _LATLON)
_LOCATED = re.compile(r"\bIS\s+LOCATED\s+NEAR\s+" + _LATLON)
_MOVING = re.compile(r"\b(MOVING|TRACKING|DRIFTING)\s+(SLOWLY\s+)?([A-Z-]+?)WARD\b"
                     r"(?:\s+AT\s+(\d+)\s+KNOTS)?")
_COMPASS = re.compile(r"(?:NORTH|SOUTH|EAST|WEST|-)+")
_STILL = re.compile(r"\b(QUASI-STATIONARY|STATIONARY)\b")
_WINDS = re.compile(r"(?:MAXIMUM SUSTAINED SURFACE WINDS ARE ESTIMATED AT|WINDS IN THE AREA "
                    r"ARE ESTIMATED TO BE)\s+(\d+)\s+TO\s+(\d+)\s+KNOTS")
_SLP = re.compile(r"MINIMUM SEA LEVEL PRESSURE IS ESTIMATED TO BE NEAR\s+(\d{3,4})\s*MB")
_UNTIL = re.compile(r"\bCANCELLED\s+BY\s+(\d{6})Z")
_RMKS = re.compile(r"RMKS/(.*?)(?://|NNNN|$)")
NM_KM = 1.852


def _point(match, i: int) -> tuple[float, float]:
    """``(lon, lat)`` from four groups of ``_LATLON`` starting at group ``i``."""
    lat = float(match.group(i)) * (-1.0 if match.group(i + 1) == "S" else 1.0)
    lon = float(match.group(i + 2)) * (-1.0 if match.group(i + 3) == "W" else 1.0)
    return lon, lat


def _destination(lon: float, lat: float, bearing: float, km: float) -> tuple[float, float]:
    """The point ``km`` along a great circle leaving at ``bearing``, its
    longitude kept beside the start's across the date line."""
    d = km / 6371.0
    p1, t = math.radians(lat), math.radians(bearing)
    p2 = math.asin(math.sin(p1) * math.cos(d) + math.cos(p1) * math.sin(d) * math.cos(t))
    dl = math.atan2(math.sin(t) * math.sin(d) * math.cos(p1),
                    math.cos(d) - math.sin(p1) * math.sin(p2))
    return round(lon + math.degrees(dl), 3), round(math.degrees(p2), 3)


def _bearing(a: tuple[float, float], b: tuple[float, float]) -> float:
    """The initial great-circle bearing from ``a`` to ``b``, degrees from north."""
    p1, p2 = math.radians(a[1]), math.radians(b[1])
    dl = math.radians(b[0] - a[0])
    return math.degrees(math.atan2(math.sin(dl) * math.cos(p2),
                                   math.cos(p1) * math.sin(p2)
                                   - math.sin(p1) * math.cos(p2) * math.cos(dl)))


def _widened(start: tuple, end: tuple, nm: float) -> tuple:
    """The line from ``start`` to ``end`` widened ``nm`` either side: the box
    JTWC draws, as a closed ring."""
    end = ((end[0] - start[0] + 180.0) % 360.0 - 180.0 + start[0], end[1])
    ahead = _bearing(start, end)
    # The bearing the line arrives at its end with, not the one it left on.
    arriving = (_bearing(end, start) + 180.0) % 360.0
    km = nm * NM_KM
    ring = (_destination(*start, ahead - 90.0, km), _destination(*end, arriving - 90.0, km),
            _destination(*end, arriving + 90.0, km), _destination(*start, ahead + 90.0, km))
    return ring + ring[:1]


def _circle(centre: tuple, nm: float, sides: int = 36) -> tuple:
    ring = tuple(_destination(*centre, 360.0 * i / sides, nm * NM_KM) for i in range(sides))
    return ring + ring[:1]


def _letter(prefix: str, lon: float) -> str:
    """The ocean's letter in an invest's id, from the file's prefix or the
    heading's area: W the west Pacific, A the Arabian Sea and B the Bay of
    Bengal, S the south Indian Ocean and P the south Pacific, east of 135 E."""
    east = lon % 360.0
    return {"wp": "W", "pn": "W", "ps": "P",
            "io": "A" if east < 78.0 else "B",
            "sh": "S" if east < 135.0 else "P",
            "xs": "S" if east < 135.0 else "P"}.get(prefix, "")


def formation_alert(text: str, url: str = "") -> FormationAlert | None:
    """One JTWC formation alert or its cancellation; None if the text is neither.

    The invest's id is the one the message names, else the file's number and
    ocean. The system's place is where the message says it now is, else its
    last past position.
    """
    if not _TCFA.search(text):
        return None
    words = " ".join(text.split())
    line, radius = _LINE.search(words), _RADIUS.search(words)
    # A cancellation says so in its subject; failing that, one that cancels
    # the alert it refers to and draws no area of its own is one.
    cancelled = bool(_CANCELLATION.search(text)
                     or (_CANCELS.search(words) and not line and not radius))
    dtg = _DTG.search(text)
    wmo = _WMO.search(text)
    issued = _issued(wmo.group(1), dtg.group(1)) if wmo and dtg else ""
    until = _UNTIL.search(words)

    where = _NOW.search(words) or _LOCATED.search(words)
    if where is not None:
        lon, lat = _point(where, 1)
    else:
        past = list(_HISTORY.finditer(text))
        if not past:
            return None
        lat, lon = _tenths(past[-1].group(3)), _tenths(past[-1].group(4))
        if lat is None or lon is None:
            return None

    if cancelled:
        box = ()
    elif line:
        box = _widened(_point(line, 2), _point(line, 6), int(line.group(1)))
    elif radius:
        box = _circle(_point(radius, 2), int(radius.group(1)))
    else:
        box = ()

    named = _INVEST.search(words)
    if named:
        key = named.group(1).lower()
    else:
        found, header, code = _ALERT_FILE.search(url), _ALERT_ID.search(text), _WMO_CODE.search(text)
        number = found.group(2) if found else header.group(1) if header else ""
        prefix = found.group(1).lower() if found else code.group(1).lower() if code else ""
        letter = _letter(prefix, lon)
        key = f"{number}{letter}".lower() if number and letter else ""

    moving, still = _MOVING.search(words), _STILL.search(words)
    # The system's motion is stated before any forecast of it ("WILL BEGIN
    # TRACKING NORTHWESTWARD").
    if moving and (still is None or moving.start() < still.start()):
        # A system drifting moves slowly; a heading that is no compass point
        # keeps its "-ward" (poleward).
        heading = moving.group(3)
        if not _COMPASS.fullmatch(heading):
            heading += "WARD"
        motion = (("slowly " if moving.group(2) or moving.group(1) == "DRIFTING" else "")
                  + heading.lower()
                  + (f" at {int(moving.group(4))} kt" if moving.group(4) else ""))
    else:
        motion = still.group(1).lower() if still else ""
    wind = _WINDS.search(words)
    pressure = _SLP.search(words)
    chance = _CHANCE.search(words)
    levels = re.findall(r"\b(LOW|MEDIUM|HIGH)\b", chance.group(1)) if chance else []
    remarks = _RMKS.search(words)
    return FormationAlert(
        key=key,
        label=f"Invest {key.upper()}" if key else "Formation alert area",
        lon=lon,
        lat=lat,
        box=box,
        issued=issued,
        until=_issued(until.group(1), dtg.group(1)) if until and dtg else "",
        motion=motion,
        wind=(int(wind.group(1)), int(wind.group(2))) if wind else (),
        pressure=int(pressure.group(1)) if pressure else None,
        potential=levels[-1].lower() if levels else "",
        text=remarks.group(1).strip() if remarks else words,
        cancelled=cancelled,
        ref=" ".join(wmo.group(0).split()) if wmo else "",
    )


# A storm's first warning ends the alert it grew from, naming it by its WMO
# heading: "THIS WARNING SUPERSEDES AND CANCELS REF A, JOINT TYPHOON WRNCEN
# PEARL HARBOR HI 291700Z SEP 26 TROPICAL CYCLONE FORMATION ALERT (WTPN21
# PGTW 291700)".
_SUPERSEDES = re.compile(r"\bSUPERSEDES\s+AND\s+CANCELS\b[^.]*?\bFORMATION\s+ALERT\b"
                         r"(?:\s*\((WT[A-Z]{2}\d\d\s+[A-Z]{4}\s+\d{6})\))?")


def superseding(text: str, storm) -> FormationAlert | None:
    """The cancellation a storm's first warning makes of the formation alert
    it grew from, dated at the warning and placed at the storm; None for any
    other warning."""
    found = _SUPERSEDES.search(" ".join(text.split()))
    now = storm.latest if storm is not None else None
    if found is None or now is None:
        return None
    return FormationAlert(
        key="", label=storm.title, lon=now.lon, lat=now.lat, box=(),
        issued=(storm.advisory or {}).get("last_update", ""), until="", motion="",
        wind=(), pressure=None, potential="", text=found.group(0), cancelled=True,
        ref=" ".join((found.group(1) or "").split()))


# An advisory's area this close to an alert is the alert's system, whatever
# the advisory numbered it: the two are hours apart at most.
ALERT_NEAR_DEG = 2.0


def _near(a, b) -> bool:
    """Whether two positions are within ALERT_NEAR_DEG of each other."""
    east = abs((a.lon - b.lon + 180.0) % 360.0 - 180.0)
    return abs(a.lat - b.lat) <= ALERT_NEAR_DEG and east <= ALERT_NEAR_DEG


def superseded(alerts, ends) -> list:
    """The alerts with each one a first warning ends taken out, and those
    endings added, so an older advisory's alert is cleared too. A warning
    ends the alert its heading names; one that names none ends an older
    alert beside it. The feed may link an alert after its storm's first
    warning, and the two would be drawn as one system twice."""
    def ended(alert) -> bool:
        return any(end.ref == alert.ref if end.ref
                   else alert.issued < end.issued and _near(alert, end)
                   for end in ends)
    return [alert for alert in alerts if not ended(alert)] + list(ends)


def advisory_code(lon: float, lat: float) -> str:
    """The JTWC advisory whose area holds a point: ABIO10 the north Indian
    Ocean and the south Indian Ocean to 135 E, ABPW10 the Pacific."""
    basin = aor(lon, lat)
    if basin == "IO" or (basin == "SH" and lon % 360.0 < 135.0):
        return "ABIO"
    return "ABPW"


def _owner(groups, alert: FormationAlert) -> tuple[int, int] | None:
    """Where in the outlooks the advisory's area for an alert's system is."""
    spots = [(g, i) for g, group in enumerate(groups) for i, area in enumerate(group)
             if area.centre == "JTWC"]
    for g, i in spots:
        if alert.key and groups[g][i].key == alert.key:
            return g, i
    for g, i in spots:
        if _near(groups[g][i], alert):
            return g, i
    return None


def _place_key(alert: FormationAlert) -> str:
    """A key for an alert that names no invest, from where it is, to the
    degree: ``tcfa-16n153e``. Two such alerts are two areas, and two alerts."""
    return (f"tcfa-{abs(round(alert.lat))}{'n' if alert.lat >= 0 else 's'}"
            f"{round(alert.lon) % 360}e")


def alerted(groups, alerts, issued: dict) -> list[list[Disturbance]]:
    """The outlooks' areas with JTWC's formation alerts laid on them.

    An alert goes to the advisory's area for its system: the area takes the
    alert's box and facts, and the alert's place and time when the alert is
    the newer. An advisory reissued since that cites no alert any more says
    it is over, and one reissued since that lists no such system says the
    system is gone; otherwise an alert no advisory lists yet is an area of
    its own, keyed by where it is when it names no invest. An alert that
    gives no time cannot be put before or after an advisory, so none ends
    it: it is kept, in the advisory's place and time. A cancellation newer
    than the advisory clears the advisory's alert and draws nothing.
    ``issued`` is each advisory's time, by code.
    """
    groups = [list(group) for group in groups]
    own: list[Disturbance] = []
    for alert in alerts:
        spot = _owner(groups, alert)
        if spot is None:
            later = issued.get(advisory_code(alert.lon, alert.lat), "")
            if not alert.cancelled and (not alert.issued or not later > alert.issued):
                own.append(Disturbance(
                    centre="JTWC", basin=aor(alert.lon, alert.lat), label=alert.label,
                    lon=alert.lon, lat=alert.lat, chance_2day=None, chance_7day=None,
                    potential=alert.potential or "high", text=alert.text, area=alert.box,
                    arrow=(), alert=True, issued=alert.issued,
                    key=alert.key or _place_key(alert), formation=alert))
            continue
        g, i = spot
        area = groups[g][i]
        newer = alert.issued > area.issued
        if alert.cancelled:
            if newer:
                groups[g][i] = replace(area, alert=False)
            continue
        if alert.issued and not newer and not area.alert:
            continue
        changes = {"area": alert.box or area.area, "alert": True, "formation": alert}
        if alert.key and area.key != alert.key:
            changes.update(key=alert.key, label=alert.label)
        if newer:
            changes.update(lon=alert.lon, lat=alert.lat, issued=alert.issued,
                           potential=alert.potential or area.potential)
        groups[g][i] = replace(area, **changes)
    if own:
        groups.append(own)
    return groups
