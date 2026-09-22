"""Where on Earth each teleconnection actually lands.

``impacts.py`` says what El Nino does to Southern Africa. It does not say where
Southern Africa is, because nothing needed it to until the globe: a reader who
can spin the planet and click a place needs the catalogue keyed by coordinate
rather than by name.

These footprints are deliberately coarse. A teleconnection is a shift in a
seasonal probability distribution over a broad region, and drawing it as a
precise polygon would imply a spatial precision the underlying composites do
not have. Boxes are honest about that: they say "this signal is about this
area", and the panel that opens on a click says the rest.

Longitudes are stored in -180..180, which is what the coastline uses. A region
that straddles the antimeridian is stored as two boxes rather than one box with
a wrapped edge, because every consumer of this module would otherwise have to
know about the wrap.
"""

from __future__ import annotations

from dataclasses import dataclass

from .impacts import CATALOGUE

# Scope changes how a footprint is treated on a click. A regional signal
# answers "what happens here". A basin signal is about activity over water
# that may be nowhere near where it makes landfall, and a global one is true
# everywhere, so neither should crowd out the local answer.
REGIONAL, BASIN, GLOBAL = "regional", "basin", "global"


@dataclass(frozen=True)
class Area:
    """One lon/lat box, west to east and south to north."""

    lon0: float
    lon1: float
    lat0: float
    lat1: float

    def contains(self, lon: float, lat: float) -> bool:
        return self.lon0 <= lon <= self.lon1 and self.lat0 <= lat <= self.lat1

    @property
    def centre(self) -> tuple[float, float]:
        return ((self.lon0 + self.lon1) / 2.0, (self.lat0 + self.lat1) / 2.0)


@dataclass(frozen=True)
class Footprint:
    region: str
    boxes: tuple[Area, ...]
    scope: str = REGIONAL

    def contains(self, lon: float, lat: float) -> bool:
        return any(box.contains(lon, lat) for box in self.boxes)

    @property
    def anchor(self) -> tuple[float, float]:
        """A representative point, for a label or a fly-to."""
        return self.boxes[0].centre


def _fp(region: str, *boxes: tuple[float, float, float, float],
        scope: str = REGIONAL) -> Footprint:
    return Footprint(region, tuple(Area(*b) for b in boxes), scope)


FOOTPRINTS: tuple[Footprint, ...] = (
    # -- Maritime Continent and Australasia ---------------------------------
    _fp("Indonesia and Malaysia", (95.0, 141.0, -11.0, 7.5)),
    _fp("Papua New Guinea highlands", (140.0, 151.0, -10.0, -2.5)),
    _fp("Eastern Australia", (138.0, 154.0, -39.0, -15.0)),
    _fp("Philippines", (116.5, 127.0, 4.5, 19.5)),
    _fp("Mekong basin and Thailand", (97.0, 110.0, 8.0, 23.0)),
    # -- South Asia ----------------------------------------------------------
    _fp("India and Pakistan", (66.0, 90.0, 7.0, 34.0)),
    # -- Africa --------------------------------------------------------------
    _fp("Southern Africa", (12.0, 41.0, -35.0, -15.0)),
    _fp("Equatorial East Africa", (32.0, 49.0, -6.0, 6.0)),
    _fp("Ethiopian highlands and Sudan", (23.0, 43.0, 6.0, 20.0)),
    _fp("Rift Valley fever risk, East Africa", (33.0, 52.0, -5.0, 12.0)),
    # Two disjoint highlands, which is the point of the entry: the same
    # mechanism - warmer nights at altitude - in two unconnected places.
    _fp("Highland malaria, East Africa and Andes",
        (28.0, 40.0, -5.0, 5.0), (-79.0, -65.0, -18.0, 8.0)),
    # -- South America -------------------------------------------------------
    _fp("Coastal Peru and Ecuador", (-82.0, -74.5, -18.0, 2.0)),
    _fp("Peruvian anchoveta fishery", (-84.0, -70.0, -20.0, -4.0), scope=BASIN),
    _fp("Northern South America", (-76.0, -58.0, -2.0, 12.5)),
    _fp("Northeast Brazil", (-45.0, -34.0, -16.0, -2.0)),
    _fp("Southern Brazil, Uruguay, northeast Argentina",
        (-60.0, -47.0, -35.0, -22.0)),
    # -- Central and North America -------------------------------------------
    _fp("Central American Dry Corridor", (-92.0, -83.0, 11.5, 17.5)),
    _fp("Caribbean", (-85.0, -60.0, 9.5, 23.5)),
    _fp("US Gulf Coast and Southeast", (-100.0, -76.0, 25.0, 36.5)),
    _fp("California and the US Southwest", (-124.5, -104.0, 31.0, 42.0)),
    _fp("US Pacific Northwest and Ohio Valley",
        (-125.0, -116.0, 42.0, 49.0), (-90.0, -78.0, 36.0, 42.5)),
    _fp("Canada and the northern United States", (-130.0, -60.0, 44.0, 62.0)),
    # -- Global systems ------------------------------------------------------
    # Hurricane and typhoon entries are about activity over the basin, not
    # about a place on the coast, so they are BASIN and say so when clicked.
    _fp("Atlantic hurricane season", (-90.0, -20.0, 8.0, 32.0), scope=BASIN),
    _fp("Eastern and central Pacific hurricanes",
        (-140.0, -90.0, 8.0, 22.0), scope=BASIN),
    _fp("Western North Pacific typhoons", (120.0, 170.0, 5.0, 25.0), scope=BASIN),
    _fp("Pacific and Indian Ocean coral reefs",
        (140.0, 180.0, -20.0, 6.0), (-180.0, -150.0, -20.0, 6.0),
        (40.0, 80.0, -15.0, 6.0), (145.0, 155.0, -24.0, -10.0), scope=BASIN),
    _fp("Global mean surface temperature",
        (-180.0, 180.0, -90.0, 90.0), scope=GLOBAL),
    # Straddles the antimeridian, so it is two boxes.
    _fp("Pacific island states",
        (155.0, 180.0, -25.0, 2.0), (-180.0, -155.0, -25.0, 2.0), scope=BASIN),
)

BY_REGION: dict[str, Footprint] = {f.region: f for f in FOOTPRINTS}


def wrap180(lon: float) -> float:
    """Any longitude convention into -180..180."""
    value = (lon + 180.0) % 360.0 - 180.0
    return 180.0 if value == -180.0 else value


def at(lon: float, lat: float, scopes: tuple[str, ...] = (REGIONAL, BASIN)):
    """Every footprint covering a point, nearest-first by box area.

    Smaller boxes are listed first because a specific claim about the Central
    American Dry Corridor is more useful than a general one about the
    Caribbean, and a click that lands in both should lead with the former.
    """
    lon = wrap180(lon)
    found = [f for f in FOOTPRINTS if f.scope in scopes and f.contains(lon, lat)]
    return sorted(found, key=lambda f: min(
        (b.lon1 - b.lon0) * (b.lat1 - b.lat0)
        for b in f.boxes if b.contains(lon, lat)
    ))


def missing() -> list[str]:
    """Catalogue entries with no footprint. Should always be empty."""
    return [link.region for link in CATALOGUE if link.region not in BY_REGION]


def orphaned() -> list[str]:
    """Footprints with no catalogue entry. Should always be empty."""
    known = {link.region for link in CATALOGUE}
    return [f.region for f in FOOTPRINTS if f.region not in known]
