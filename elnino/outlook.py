"""Where new storms may form: the official formation outlooks.

Nobody forecasts genesis better than the warning centres, and they say so
in the one product that exists for it. NHC and CPHC issue the Graphical
Tropical Weather Outlook four times a day for the Atlantic, the east
Pacific and the central Pacific: each area it watches, the chance a
tropical cyclone forms there within two days and within seven, a hatched
area where it may form and an arrow for where it is heading. JTWC's
significant tropical weather advisories do the same for the west and south
Pacific and the Indian Ocean in words - LOW, MEDIUM or HIGH potential in
the next 24 hours, and a formation alert when it is imminent: a box drawn
round the system's expected path where a significant tropical cyclone is
likely within a day, reissued, upgraded to a warning or cancelled by a stated
time. Invests are the systems a centre has started running models on
(numbers 90-99).

This module reports those judgements as issued; it does not make its own.
A disturbance two centres both list - CPHC and NHC both describe a low
straddling 140 W - is kept once, by the centre whose area of
responsibility it is in.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone

from . import kml

# The centre that issues each basin's outlook.
CENTRE = {"AL": "NHC", "EP": "NHC", "CP": "CPHC"}

# The Pacific shore of Central America, west to east, as the boundary
# between NHC's two basins: a point south of it is in the east Pacific.
ISTHMUS = ((-100.0, 17.0), (-95.0, 16.0), (-92.0, 14.5), (-88.0, 13.2),
           (-86.0, 11.8), (-84.0, 9.7), (-80.0, 7.5), (-77.2, 7.0))

_POTENTIAL_ORDER = {"high": 0, "medium": 1, "low": 2}
_BTK = re.compile(r"\bb(al|ep|cp)(\d\d)(\d{4})\.dat\b", re.I)


@dataclass(frozen=True)
class FormationAlert:
    """A JTWC tropical cyclone formation alert (TCFA), or its cancellation.

    ``box`` is the area JTWC expects a significant tropical cyclone to form
    in within a day: its line widened by the stated distance either side, or
    a circle round a point; a cancellation draws none. ``until`` is when JTWC
    says it will reissue the alert, upgrade it to a warning or cancel it.
    ``wind`` is the estimated maximum sustained wind as a (low, high) range
    in knots, and ``motion`` the system's own words ("west-northwest at 14
    kt"). ``key`` is the invest's id, as JTWC's advisories key it (``93w``).
    ``ref`` is the alert's WMO heading (``WTPN21 PGTW 291700``), the name a
    storm's first warning cancels it by. Past ``until``, with nothing newer
    read, the alert has lapsed: JTWC will have reissued, upgraded or
    cancelled it, and which is not known.
    """

    key: str
    label: str
    lon: float
    lat: float
    box: tuple
    issued: str
    until: str
    motion: str
    wind: tuple
    pressure: int | None
    potential: str
    text: str
    cancelled: bool = False
    ref: str = ""

    def facts(self) -> list[str]:
        """What the alert says of the system, as phrases for a sentence."""
        out = []
        if self.motion:
            out.append(moving(self.motion))
        if self.wind:
            out.append(f"winds {self.wind[0]} to {self.wind[1]} kt")
        if self.pressure:
            out.append(f"pressure near {self.pressure} mb")
        return out

    def lapsed(self, now) -> bool:
        """Whether ``until`` has come by ``now``, an ISO 8601 time."""
        return lapsed(self.until, now)


def _moment(text) -> datetime | None:
    """An ISO 8601 time, ``Z`` or offset, as an aware time; None if it is none."""
    try:
        when = datetime.fromisoformat(str(text or "").strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)


def lapsed(until, now) -> bool:
    """Whether a formation alert's ``until`` has come by ``now``, both ISO
    8601 times; never when either is not known."""
    ends, at = _moment(until), _moment(now)
    return ends is not None and at is not None and ends <= at


def moving(motion: str) -> str:
    """An alert's motion as a phrase: "moving west at 14 kt", "quasi-stationary"."""
    return motion if motion.endswith("stationary") else f"moving {motion}"


def utc(iso: str) -> str:
    """``2026-09-30T17:00:00Z`` as ``2026-09-30 17:00 UTC``; anything else as given."""
    iso = str(iso or "")
    return (f"{iso[:10]} {iso[11:16]} UTC"
            if re.match(r"^\d{4}-\d\d-\d\dT\d\d:\d\d", iso) else iso)


@dataclass(frozen=True)
class Disturbance:
    """One area a centre is watching for tropical cyclone formation.

    ``chance_2day`` and ``chance_7day`` are NHC's percentages (None from
    JTWC, which does not give them); ``potential`` is the category - low,
    medium or high - in the centre's own terms. ``key`` is stable within an
    outlook: NHC's area number (``ep1``) or JTWC's invest id (``97w``).
    ``formation`` is JTWC's formation alert for the area, when one is out;
    its box is then the area.
    """

    centre: str
    basin: str
    label: str
    lon: float
    lat: float
    chance_2day: int | None
    chance_7day: int | None
    potential: str
    text: str
    area: tuple
    arrow: tuple
    alert: bool
    issued: str
    key: str = ""
    formation: FormationAlert | None = None


def aor(lon: float, lat: float) -> str:
    """The basin whose warning centre is responsible for a point.

    NHC: the Atlantic, and the Pacific east of 140 W; CPHC from 140 W to
    the date line; between 100 W and 77.2 W the Pacific shore of Central
    America divides the two. JTWC's basins beyond: the west Pacific (the
    date line to 100 E), the north Indian Ocean and everything south of the
    equator.
    """
    lon = (lon + 180.0) % 360.0 - 180.0
    if lat < 0.0:
        return "SH"
    if lon >= 100.0:
        return "WP"
    if lon >= 40.0:
        return "IO"
    if lon < -140.0:
        return "CP"
    if lon < -100.0:
        return "EP"
    if lon < ISTHMUS[-1][0]:
        return "EP" if lat < _isthmus_lat(lon) else "AL"
    return "AL"


def _isthmus_lat(lon: float) -> float:
    for (x1, y1), (x2, y2) in zip(ISTHMUS, ISTHMUS[1:]):
        if x1 <= lon <= x2:
            return y1 + (y2 - y1) * (lon - x1) / (x2 - x1)
    return ISTHMUS[-1][1]


def _percent(text: str) -> int | None:
    found = re.search(r"\d+", text or "")
    return int(found.group()) if found else None


def _issued(text: str) -> str:
    """NHC's issue time, as NHC writes it in the document name."""
    try:
        name = kml.document_name(text)
    except ET.ParseError:
        return ""
    return name.rsplit(" - ", 1)[-1].strip() if " - " in name else ""


def nhc(text: str, basin: str) -> tuple[str, list[Disturbance]]:
    """One basin's Graphical Tropical Weather Outlook: its issue time and areas.

    Each area is a polygon placemark carrying the numbers, a point
    placemark with the same ``Disturbance`` number for where the system is
    now, and the data-less line placemark after them for its heading. An
    outlook with nothing to watch has only the words "formation is not
    expected" and gives an empty list.
    """
    issued = _issued(text)
    # A file that does not parse or is not KML raises: an outlook that could
    # not be read is not one with nothing expected.
    marks = kml.placemarks(text)
    found: dict[str, dict] = {}
    order: list[str] = []
    current = None
    for mark in marks:
        number = mark.data.get("Disturbance")
        if number:
            current = number
            entry = found.get(number)
            if entry is None:
                entry = found[number] = {"data": mark.data, "area": (), "point": None,
                                         "arrow": ()}
                order.append(number)
            if mark.polygons and not entry["area"]:
                entry["area"] = kml.continuous(mark.polygons[0])
            if mark.points and entry["point"] is None:
                entry["point"] = mark.points[0]
        elif mark.lines and current in found and not found[current]["arrow"]:
            found[current]["arrow"] = kml.continuous(mark.lines[0])
    out = []
    for number in order:
        entry = found[number]
        data = entry["data"]
        point = entry["point"]
        if point is None and entry["area"]:
            ring = entry["area"]
            point = (sum(p[0] for p in ring) / len(ring), sum(p[1] for p in ring) / len(ring))
        if point is None:
            continue
        words = " ".join(data.get("Discussion", "").split())
        heading = re.match(r"^\d+\.\s*([^:]+):", words)
        out.append(Disturbance(
            centre=CENTRE.get(basin, "NHC"),
            basin=basin,
            label=heading.group(1).strip() if heading else f"Area {number}",
            lon=point[0],
            lat=point[1],
            chance_2day=_percent(data.get("2day_percentage", "")),
            chance_7day=_percent(data.get("7day_percentage", "")),
            potential=data.get("7day_category", "").strip().lower(),
            text=words,
            area=entry["area"],
            arrow=entry["arrow"],
            alert=False,
            issued=issued,
            key=f"{basin.lower()}{number}",
        ))
    return issued, out


def _near(a: Disturbance, b: Disturbance) -> bool:
    east = abs((a.lon - b.lon + 180.0) % 360.0 - 180.0)
    return abs(a.lat - b.lat) <= 1.0 and east <= 1.0


def merge(*groups) -> list[Disturbance]:
    """Every outlook's areas as one list, each system once.

    Two groups listing a system within a degree of each other are one
    system, kept from the centre responsible for where it is; two areas of
    the same outlook are never merged, because the centre drew them apart.
    The likeliest first by seven-day chance, then JTWC's by potential.
    """
    tagged = [(index, item) for index, group in enumerate(groups) for item in group]
    tagged.sort(key=lambda pair: pair[1].basin != aor(pair[1].lon, pair[1].lat))
    kept: list[tuple[int, Disturbance]] = []
    for index, item in tagged:
        if any(other != index and _near(item, seen) for other, seen in kept):
            continue
        kept.append((index, item))
    out = [item for _, item in kept]
    out.sort(key=lambda d: (d.chance_7day is None, -(d.chance_7day or 0),
                            _POTENTIAL_ORDER.get(d.potential, 3)))
    return out


def invest_candidates(listing: str) -> list[str]:
    """The invests (numbers 90-99) of the season a best-track listing is for.

    The directory keeps an invest's deck after the system is dropped, so a
    candidate is only a system to look at: whether it is still being
    watched is for its latest fix to say.
    """
    found = [(m.group(1).lower(), int(m.group(2)), int(m.group(3)))
             for m in _BTK.finditer(listing)]
    if not found:
        return []
    season = max(year for _, _, year in found)
    return sorted({f"{basin}{number:02d}{year}" for basin, number, year in found
                   if year == season and 90 <= number <= 99})
