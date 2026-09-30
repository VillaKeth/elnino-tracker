"""KML, as the warning centres write it.

NHC and CPHC publish every graphical product - the formation outlook, the
cone, the watches and warnings, the peak surge - as KML, most of it zipped
into KMZ (``sources.decode_payload`` unzips it). What is read here is small:
the placemarks in document order, their names and styles, the key-value
pairs in ExtendedData where NHC keeps the numbers, the folder each sits in,
and the coordinates. Everything else in the file is presentation for Google
Earth.

Two traps. Namespaces are stripped rather than matched: the same products
are published under the 2.1 namespace (``http://earth.google.com/kml/2.1``)
and the 2.2 one (``http://www.opengis.net/kml/2.2``), and a reader matching
one reads nothing from the other. And a description is raw HTML pasted into
the XML - well formed today, but one unclosed ``<br>`` would make the whole
file unreadable, so a file that will not parse is read again with its
descriptions removed rather than dropped.
"""

from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

Point = tuple[float, float]


@dataclass(frozen=True)
class Placemark:
    """One placemark: its name, style, data, geometry and folder."""

    name: str = ""
    style: str = ""
    description: str = ""
    data: dict = field(default_factory=dict)
    points: tuple[Point, ...] = ()
    lines: tuple[tuple[Point, ...], ...] = ()
    polygons: tuple[tuple[Point, ...], ...] = ()   # outer rings
    folder: str = ""


def _root(text: str):
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        root = ET.fromstring(re.sub(r"<description>.*?</description>", "",
                                    text, flags=re.S | re.I))
    for element in root.iter():
        if isinstance(element.tag, str):
            element.tag = element.tag.rsplit("}", 1)[-1]
    return root


def _text(element, path: str) -> str:
    found = element.find(path)
    if found is None:
        return ""
    return "".join(found.itertext()).strip()


def _coords(text: str | None) -> tuple[Point, ...]:
    """``lon,lat[,alt]`` tuples separated by any whitespace."""
    out = []
    for token in (text or "").split():
        parts = token.split(",")
        if len(parts) < 2:
            continue
        try:
            out.append((float(parts[0]), float(parts[1])))
        except ValueError:
            continue
    return tuple(out)


def _placemark(element, folder: str) -> Placemark:
    data = {}
    for item in element.iter("Data"):
        key = item.get("name")
        if key:
            data[key] = _text(item, "value")
    for item in element.iter("SimpleData"):
        key = item.get("name")
        if key:
            data[key] = "".join(item.itertext()).strip()
    points: list[Point] = []
    for point in element.iter("Point"):
        points.extend(_coords(_raw(point, "coordinates")))
    lines = [line for line in (_coords(_raw(ls, "coordinates"))
                               for ls in element.iter("LineString"))
             if len(line) >= 2]
    polygons = [ring for ring in (_coords(_raw(poly, "outerBoundaryIs/LinearRing/coordinates"))
                                  for poly in element.iter("Polygon"))
                if len(ring) >= 3]
    return Placemark(
        name=_text(element, "name"),
        style=_text(element, "styleUrl"),
        description=_text(element, "description"),
        data=data,
        points=tuple(points),
        lines=tuple(lines),
        polygons=tuple(polygons),
        folder=folder,
    )


def _raw(element, path: str) -> str:
    found = element.find(path)
    return found.text or "" if found is not None else ""


# What a KML file can be rooted at. Anything else - an HTML error page served
# with status 200, say - is not KML, and has no placemarks to give.
KML_ROOTS = ("kml", "Document", "Folder", "Placemark")


def placemarks(text: str) -> list[Placemark]:
    """Every placemark in the file, in document order.

    A file that does not parse raises ElementTree's ParseError, and one that
    parses but is not KML raises ValueError: neither is a file with nothing in
    it, and a caller must not read either as one.
    """
    out: list[Placemark] = []

    def walk(element, folder: str) -> None:
        for child in element:
            if child.tag == "Folder":
                walk(child, _text(child, "name") or folder)
            elif child.tag == "Document":
                walk(child, folder)
            elif child.tag == "Placemark":
                out.append(_placemark(child, folder))

    root = _root(text)
    if root.tag not in KML_ROOTS:
        raise ValueError(f"not a KML document: <{root.tag}>")
    if root.tag == "Placemark":
        return [_placemark(root, "")]
    walk(root, "")
    return out


def document_name(text: str) -> str:
    """The document's own name, which is where NHC puts the advisory."""
    root = _root(text)
    document = root if root.tag == "Document" else root.find("Document")
    return _text(document, "name") if document is not None else ""


def document_text(text: str) -> str:
    """The document description as plain words, tags and all removed."""
    root = _root(text)
    document = root if root.tag == "Document" else root.find("Document")
    if document is None:
        return ""
    found = document.find("description")
    if found is None:
        return ""
    return " ".join(" ".join(found.itertext()).split())


def continuous(points) -> tuple:
    """The points with each longitude within 180 degrees of the one before.

    A line crossing the date line is written 179 then -179; drawn as written
    it runs the long way round the world. Unwrapped it runs 179 then 181,
    which a map drawing whole-world copies puts in the right place.
    """
    out = []
    for lon, lat in points:
        if out:
            previous = out[-1][0]
            while lon - previous > 180.0:
                lon -= 360.0
            while lon - previous < -180.0:
                lon += 360.0
        out.append((lon, lat))
    return tuple(out)


def simplify(points, tolerance: float) -> tuple:
    """Douglas-Peucker in degrees, keeping both ends.

    A cone is published with 1,600 vertices and a surge area with more; at
    the scale they are drawn a few hundredths of a degree is below a pixel,
    and shipping every vertex would make the page heavier than the imagery.
    A closed ring stays closed, because its first and last points are kept.
    """
    points = list(points)
    if len(points) < 3 or tolerance <= 0:
        return tuple(points)
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        first, last = stack.pop()
        if last <= first + 1:
            continue
        ax, ay = points[first]
        bx, by = points[last]
        dx, dy = bx - ax, by - ay
        length = dx * dx + dy * dy
        worst, where = -1.0, first
        for index in range(first + 1, last):
            px, py = points[index]
            if length == 0.0:
                gap = math.hypot(px - ax, py - ay)
            else:
                t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length))
                gap = math.hypot(px - (ax + t * dx), py - (ay + t * dy))
            if gap > worst:
                worst, where = gap, index
        if worst > tolerance:
            keep[where] = True
            stack.append((first, where))
            stack.append((where, last))
    return tuple(point for point, kept in zip(points, keep) if kept)
