"""The products a warning centre issues for one storm to protect people.

NHC and CPHC publish, with every advisory, four things that say who is at
risk and when: the coastal watches and warnings, the cone the centre is
forecast to stay inside two times in three, the peak storm surge above
ground where surge is a threat, and the wind speed probabilities - the
chance each named place gets 34, 50 and 64 kt winds, cumulatively, by each
forecast hour. The first three are KML (``kml.placemarks``); the fourth is
a fixed-width text product inside an HTML page. The public advisory, text
in a page too, says in the centre's own words where each watch and warning
is in effect - "Hawaii County" - which the lines of the first do not.

What is read here is exactly what was issued. Nothing is derived, smoothed
or extended, except that rings and lines are simplified below a pixel at
the scale they are drawn and kept continuous across 180 degrees.

Two traps. In the wind table the first column is the onset probability of
the first period only, which is also its cumulative probability; every
later column is ``onset(cumulative)``, and it is the cumulative figure a
person needs ("by Saturday morning, 29%"). And ``X`` is not zero: it is
"less than one percent", kept as 0 here and shown as "<1%".
"""

from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass

from . import kml

# Most severe first: the order they are drawn under one another and listed.
WW_ORDER = ("Hurricane Warning", "Hurricane Watch",
            "Tropical Storm Warning", "Tropical Storm Watch")

# NHC's style ids, for a file whose placemarks are not named.
_STYLE_KINDS = {"#HWR": "Hurricane Warning", "#HWA": "Hurricane Watch",
                "#TWR": "Tropical Storm Warning", "#TWA": "Tropical Storm Watch"}


@dataclass(frozen=True)
class WarningSegment:
    """One stretch of coast under one watch or warning, breakpoint to breakpoint."""

    kind: str
    coords: tuple


@dataclass(frozen=True)
class SurgeArea:
    """One area of forecast peak surge: where, and how many feet above ground."""

    label: str
    feet: str
    ring: tuple


@dataclass(frozen=True)
class WindProbability:
    """The cumulative chance, by forecast hour, of one wind threshold at one place."""

    place: str
    threshold: int
    cumulative: tuple[int, ...]

    @property
    def total(self) -> int:
        """The chance over the whole five days, in percent (0 is below 1%)."""
        return self.cumulative[-1] if self.cumulative else 0


@dataclass(frozen=True)
class WindTable:
    """A wind speed probabilities product: its issue time and every row."""

    issued: str
    advisory: str
    hours: tuple[int, ...]
    rows: tuple


@dataclass(frozen=True)
class Products:
    """Everything issued for one storm at one advisory.

    ``()`` means the centre issued none - no watches in effect, say - and
    ``None`` means the product was linked but could not be fetched or read;
    a note then says so. The two are different statements to a person
    deciding whether to leave.
    """

    watches: tuple | None = ()
    cone: tuple | None = ()
    surge: tuple | None = ()
    winds: WindTable | None = None
    # What the public advisory says is in effect, by kind, with the areas it
    # names: ``(("Hurricane Watch", ("Hawaii County",)), ...)``.
    in_effect: tuple | None = ()
    advisory: str = ""
    notes: tuple[str, ...] = ()
    # The products the index linked that could not be fetched or read, by
    # name: a failed feed, which makes the run a degraded one.
    unavailable: tuple[str, ...] = ()
    # Each product's own advisory number, by kind. They differ: under the
    # intermediate advisory 20A the watches are 20A's and the wind
    # probabilities still 20's, which are the latest issued.
    advisories: tuple[tuple[str, str], ...] = ()

    def own(self, kind: str) -> str:
        """The advisory one product was issued with, or "" if not known."""
        return dict(self.advisories).get(kind, "")


def _placemarks(text: str) -> list:
    # A file that does not parse or is not KML raises: it was not read, and
    # the caller says so. Read as empty, an error page served in place of the
    # watches said that none were in effect.
    return kml.placemarks(text)


def watches_warnings(text: str) -> list[WarningSegment]:
    """Every coastal segment under a watch or warning, most severe first."""
    out = []
    for mark in _placemarks(text):
        kind = mark.name if mark.name in WW_ORDER else _STYLE_KINDS.get(mark.style)
        if kind is None:
            if mark.lines or mark.polygons:
                # A stretch of coast under something this reader does not
                # know: the file is not read rather than the stretch dropped.
                raise ValueError(f"a watch or warning this reader does not know: "
                                 f"{mark.name or mark.style or 'unnamed'}")
            continue
        for line in mark.lines + mark.polygons:
            out.append(WarningSegment(kind, kml.continuous(line)))
    out.sort(key=lambda segment: WW_ORDER.index(segment.kind))
    return out


def cone(text: str, tolerance: float = 0.02) -> tuple[tuple[float, float], ...]:
    """The cone of uncertainty as one closed ring, or () if the file has none."""
    for mark in _placemarks(text):
        for ring in mark.polygons:
            ring = kml.simplify(kml.continuous(ring), tolerance)
            if ring[0] != ring[-1]:
                ring = ring + (ring[0],)
            return ring
    return ()


def peak_surge(text: str, tolerance: float = 0.005) -> list[SurgeArea]:
    """Each area of forecast peak surge, named as NHC names it."""
    out = []
    for mark in _placemarks(text):
        if not mark.polygons:
            continue
        label, _, rest = mark.name.partition("...")
        feet = mark.data.get("peak_surge_range") or rest.strip()
        for ring in mark.polygons:
            out.append(SurgeArea(label.strip() or mark.name, feet,
                                 kml.simplify(kml.continuous(ring), tolerance)))
    return out


def advisory_of(text: str) -> str:
    """The advisory number a product belongs to, or "" if it does not say.

    KML carries it in every placemark's ``advisoryNum`` and in the document
    name, "(Advisory #20)", which is all an empty watch/warning file has;
    the text products say "NUMBER  20".
    """
    try:
        for mark in kml.placemarks(text):
            if mark.data.get("advisoryNum"):
                return mark.data["advisoryNum"].strip()
        found = re.search(r"Advisory #\s*(\w+)", kml.document_name(text))
        if found:
            return found.group(1)
    except (ET.ParseError, ValueError):
        pass
    found = re.search(r"\b(?:NUMBER|Advisory Number)\s+(\w+)", text)
    return found.group(1) if found else ""


# "A Hurricane Watch is in effect for..." - one line of a public advisory's
# summary of watches and warnings, the areas it covers following as bullets.
_IN_EFFECT = re.compile(r"^An? (?P<kind>[A-Z][A-Za-z ]*?) is in effect for\.\.\.$")
_NONE_IN_EFFECT = re.compile(r"no coastal watches or warnings in effect", re.I)


def in_effect(text: str) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """What a public advisory says is in effect, in its own words.

    Each watch and warning in its "SUMMARY OF WATCHES AND WARNINGS IN EFFECT"
    with the areas listed under it, ``(("Hurricane Watch", ("Hawaii
    County",)), ...)``, or ``()`` where the advisory says there are none.
    Text that is not a public advisory, or one whose watches and warnings
    cannot be read, raises ValueError: an error page is not an advisory
    with nothing in effect.
    """
    plain = html.unescape(re.sub(r"<[^>]+>", "", text))
    if not re.search(r"\bAdvisory Number\s+\w+", plain) or "WATCHES AND WARNINGS" not in plain:
        raise ValueError("not a tropical cyclone public advisory")
    start = plain.find("SUMMARY OF WATCHES AND WARNINGS IN EFFECT:")
    if start < 0:
        # With nothing in effect the advisory has no summary, only the line
        # saying so.
        if _NONE_IN_EFFECT.search(plain, plain.find("WATCHES AND WARNINGS")):
            return ()
        raise ValueError("the advisory's watches and warnings could not be read")
    out: dict[str, list[str]] = {}
    areas: list[str] | None = None
    for line in plain[start:].splitlines()[1:]:
        line = line.strip()
        found = _IN_EFFECT.match(line)
        if found:
            areas = out.setdefault(found.group("kind"), [])
        elif areas is None:
            if line:
                break  # what the watches mean, after the last of them
        elif line.startswith("*"):
            areas.append(line.lstrip("*").strip())
        elif line and areas:
            areas[-1] += " " + line  # an area wrapped onto the next line
        elif line:
            areas.append(line)
        elif areas:
            areas = None  # a blank line ends the list
    if any(not areas for areas in out.values()):
        raise ValueError("a watch or warning in the advisory names no area")
    if not out and not _NONE_IN_EFFECT.search(plain, start):
        raise ValueError("the advisory's watches and warnings could not be read")
    return tuple((kind, tuple(areas)) for kind, areas in out.items())


_ROW = re.compile(r"^(?P<name>\S.*?)\s+(?P<kt>34|50|64)\s+(?P<first>X|\d+)\s+(?P<rest>.*)$")
_CELL = re.compile(r"(X|\d+)\(\s*(X|\d+)\)")
_ISSUED = re.compile(r"^\s*(\d{3,4} UTC \w{3} \w{3} \d{1,2} \d{4})\s*$", re.M)


def _percent(text: str) -> int:
    return 0 if text == "X" else int(text)


def wind_probabilities(text: str) -> WindTable | None:
    """The wind speed probabilities table, or None if the page has none."""
    plain = html.unescape(re.sub(r"<[^>]+>", "", text))
    lines = plain.splitlines()
    start = next((i for i, line in enumerate(lines)
                  if line.strip().startswith("FORECAST HOUR")), None)
    if start is None:
        return None
    hours = tuple(int(h) for h in re.findall(r"\((\d+)\)", lines[start]))
    if not hours:
        return None
    rows = []
    for line in lines[start + 1:]:
        if line.startswith("$$"):
            break
        found = _ROW.match(line.rstrip())
        if not found:
            continue
        cells = _CELL.findall(found.group("rest"))
        cumulative = (_percent(found.group("first")),) + tuple(
            _percent(cp) for _, cp in cells)
        if len(cumulative) != len(hours):
            continue
        rows.append(WindProbability(found.group("name").strip(),
                                    int(found.group("kt")), cumulative))
    issued = _ISSUED.search(plain)
    return WindTable(issued=issued.group(1) if issued else "",
                     advisory=advisory_of(plain), hours=hours, rows=tuple(rows))
