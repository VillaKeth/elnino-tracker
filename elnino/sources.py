"""Live ENSO data sources: fetch, retry, and archive raw snapshots.

Every source is an authoritative NOAA/CPC, NOAA/PSL or NOAA/PMEL product.
Nothing here depends on third-party packages so the tracker keeps working on a
bare Python install.

Sources are grouped into tiers, which is how the rest of the system decides how
badly it is hurt when one goes dark:

    core        the indices NOAA declares episodes with - fatal if missing
    ocean       subsurface and basin-wide ocean state
    atmosphere  the coupled atmospheric response
    context     other basins, modulators, and narrative
"""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

USER_AGENT = "elnino-tracker/2.0 (+personal ENSO monitoring; contact: local user)"
TIMEOUT = 45
RETRIES = 3
BACKOFF = 2.5
MAX_PARALLEL = 6  # polite against CPC; the whole registry still lands in ~15s

CPC = "https://www.cpc.ncep.noaa.gov/data/indices"

# ERDDAP endpoints for the spatial tier. Two servers: CoastWatch carries the
# gridded satellite products and a monthly aggregate of the mooring array, PMEL
# carries the daily mooring data.
COASTWATCH = "https://coastwatch.pfeg.noaa.gov/erddap"
PMEL = "https://data.pmel.noaa.gov/pmel/erddap"

# How far back the rolling Hovmoller windows reach. Sixteen months is two
# boreal winters' worth of context without making the vertical axis unreadable.
HOVMOLLER_MONTHS = 16


def _since(months: int) -> str:
    """ISO date roughly ``months`` back, for a rolling request window."""
    today = date.today()
    year, month = today.year, today.month - months
    while month <= 0:
        month += 12
        year -= 1
    return f"{year:04d}-{month:02d}-01"


def erddap(base: str, query: str) -> str:
    """Percent-encode an ERDDAP subset expression.

    Brackets, parentheses and comparison operators have to be encoded; the
    ampersands and equals signs that separate tabledap constraints must not be.
    """
    return f"{base}?{urllib.parse.quote(query, safe=',:&=')}"


# The equatorial strip is requested a few rows wide and meaned when it is
# shaped, rather than sampled on one row of a quarter-degree product.
#
# The strides below are on OISST's native quarter degree. They are the single
# biggest control on how sharp this system looks, and they were all four times
# coarser until a reader zoomed the globe in and found square kilometres of
# ocean painted one colour. A globe that can be zoomed six times has about
# 0.02 degrees to a pixel at full zoom, so the globe takes the product at its
# own quarter degree and nothing is interpolated or invented; the flat maps are
# a fixed size and stay at a half degree, which is already about two pixels to
# a cell there. Every panel draws a decimated view when it is not zoomed in,
# which is cheaper than asking for the same field twice at two resolutions.
_EQ_STRIP = "[(-2):4:(2)][(120):4:(280)]"
_PACIFIC = "[(-30):2:(30)][(100):2:(300)]"
_WORLD = "[(-79):1:(79)][(0):1:(359.75)]"
_TAO_EQ = "&latitude>=-0.6&latitude<=0.6"


@dataclass(frozen=True)
class Source:
    key: str
    name: str
    url: str
    agency: str
    cadence: str
    tier: str = "context"
    note: str = ""
    critical: bool = False


SOURCES: tuple[Source, ...] = (
    # -- core: the episode-defining indices ---------------------------------
    Source(
        key="oni",
        name="Oceanic Nino Index (ONI, legacy), 3-month running Nino-3.4 anomaly",
        url=f"{CPC}/oni.ascii.txt",
        agency="NOAA CPC",
        cadence="monthly",
        tier="core",
        note=("Legacy: CPC classified on it until February 2026, when RONI "
              "replaced it (NWS PIS 26-05). Kept for comparison with the record."),
    ),
    Source(
        key="roni",
        name=("Relative ONI (RONI), the official index: Nino-3.4 minus the "
              "tropical-mean anomaly, rescaled"),
        url=f"{CPC}/RONI.ascii.txt",
        agency="NOAA CPC",
        cadence="monthly",
        tier="core",
        note=("CPC's official ENSO index since February 2026. Removes the "
              "tropical-wide warming, so events compare across eras."),
        critical=True,
    ),
    Source(
        key="weekly_sst",
        name="Weekly Nino-region SST and anomalies (1991-2020 base)",
        url=f"{CPC}/wksst9120.for",
        agency="NOAA CPC",
        cadence="weekly",
        tier="core",
        note="The 1981-2010 file (wksst8110.for) stopped updating in 2021.",
        critical=True,
    ),
    Source(
        key="monthly_sst",
        name="Monthly Nino-region SST and anomalies",
        url=f"{CPC}/sstoi.indices",
        agency="NOAA CPC",
        cadence="monthly",
        tier="core",
    ),
    Source(
        key="rel_weekly_sst",
        name="Weekly relative Nino-region SST anomalies",
        url=f"{CPC}/rel_wksst9120.txt",
        agency="NOAA CPC",
        cadence="weekly",
        tier="core",
        note="Column order is 1+2, 3, 3.4, 4 - the monthly file puts 3.4 last.",
    ),
    Source(
        key="rel_monthly_sst",
        name="Monthly relative Nino-region SST anomalies",
        url=f"{CPC}/rel_mthsst9120.txt",
        agency="NOAA CPC",
        cadence="monthly",
        tier="core",
    ),
    Source(
        key="nino34_detrended",
        name="Detrended monthly Nino-3.4 anomaly",
        url=f"{CPC}/detrend.nino34.ascii.txt",
        agency="NOAA CPC",
        cadence="monthly",
        tier="core",
        note="Climatology adjusted for trend; a third view of the same region.",
    ),
    Source(
        key="nino34_relative",
        name="Relative monthly Nino-3.4 anomaly (long record)",
        url=f"{CPC}/Rnino34.ascii.txt",
        agency="NOAA CPC",
        cadence="monthly",
        tier="core",
    ),
    # -- ocean: subsurface heat and its redistribution ----------------------
    Source(
        key="wwv",
        name="Warm Water Volume, 5N-5S 120E-80W (full equatorial band)",
        url="https://www.pmel.noaa.gov/tao/wwv/data/wwv.dat",
        agency="NOAA PMEL",
        cadence="monthly",
        tier="ocean",
        note="Recharge-oscillator state variable; leads Nino-3.4 by 2-3 seasons.",
    ),
    Source(
        key="wwv_west",
        name="Warm Water Volume, western half (120E-155W)",
        url="https://www.pmel.noaa.gov/tao/wwv/data/wwv_west.dat",
        agency="NOAA PMEL",
        cadence="monthly",
        tier="ocean",
        note="West minus total shows whether heat has already moved east.",
    ),
    # -- atmosphere: is the Walker circulation actually responding? ---------
    Source(
        key="soi",
        name="Southern Oscillation Index (Tahiti-Darwin)",
        url=f"{CPC}/soi",
        agency="NOAA CPC",
        cadence="monthly",
        tier="atmosphere",
        note="Two stacked tables: raw anomaly, then standardized.",
    ),
    Source(
        key="eqsoi",
        name="Equatorial SOI (Indonesia vs eastern Pacific SLP)",
        url=f"{CPC}/reqsoi.for",
        agency="NOAA CPC",
        cadence="monthly",
        tier="atmosphere",
        note="No header and a POSITIVE 999.9 fill value.",
    ),
    Source(
        key="darwin",
        name="Darwin sea level pressure anomaly",
        url=f"{CPC}/darwin",
        agency="NOAA CPC",
        cadence="monthly",
        tier="atmosphere",
    ),
    Source(
        key="tahiti",
        name="Tahiti sea level pressure anomaly",
        url=f"{CPC}/tahiti",
        agency="NOAA CPC",
        cadence="monthly",
        tier="atmosphere",
    ),
    Source(
        key="olr",
        name="Outgoing longwave radiation, equator 160E-160W",
        url=f"{CPC}/olr",
        agency="NOAA CPC",
        cadence="monthly",
        tier="atmosphere",
        note="Negative anomaly = enhanced deep convection over the date line.",
    ),
    Source(
        key="olr_central",
        name="Outgoing longwave radiation, central Pacific (1991-2020)",
        url=f"{CPC}/cpolr.mth.91-20.ascii",
        agency="NOAA CPC",
        cadence="monthly",
        tier="atmosphere",
    ),
    Source(
        key="trade_central",
        name="850 hPa trade wind index, central Pacific (175W-140W)",
        url=f"{CPC}/cpac850",
        agency="NOAA CPC",
        cadence="monthly",
        tier="atmosphere",
        note="Negative anomaly = weakened trades / westerly wind anomaly.",
    ),
    Source(
        key="trade_west",
        name="850 hPa trade wind index, western Pacific (135E-180)",
        url=f"{CPC}/wpac850",
        agency="NOAA CPC",
        cadence="monthly",
        tier="atmosphere",
        note="Where westerly wind bursts fire before Kelvin waves cross.",
    ),
    Source(
        key="trade_east",
        name="850 hPa trade wind index, eastern Pacific (135W-120W)",
        url=f"{CPC}/epac850",
        agency="NOAA CPC",
        cadence="monthly",
        tier="atmosphere",
    ),
    Source(
        key="zwnd200",
        name="200 hPa zonal wind, equator 165W-110W",
        url=f"{CPC}/zwnd200",
        agency="NOAA CPC",
        cadence="monthly",
        tier="atmosphere",
        note="Upper-branch response; confirms a full Walker-cell reversal.",
    ),
    Source(
        key="mjo",
        name="MJO index, 200 hPa velocity potential by longitude (pentad)",
        url="https://www.cpc.ncep.noaa.gov/products/precip/CWlink/daily_mjo_index/proj_norm_order.ascii",
        agency="NOAA CPC",
        cadence="pentad",
        tier="atmosphere",
        note="Sub-seasonal modulator of westerly wind bursts.",
    ),
    # -- context: modulators, other basins, narrative ------------------------
    Source(
        key="qbo30",
        name="Quasi-Biennial Oscillation, 30 hPa zonal wind",
        url=f"{CPC}/qbo.u30.index",
        agency="NOAA CPC",
        cadence="monthly",
        tier="context",
    ),
    Source(
        key="qbo50",
        name="Quasi-Biennial Oscillation, 50 hPa zonal wind",
        url=f"{CPC}/qbo.u50.index",
        agency="NOAA CPC",
        cadence="monthly",
        tier="context",
    ),
    Source(
        key="atlantic",
        name="Atlantic SST indices (north, south, tropical)",
        url=f"{CPC}/sstoi.atl.indices",
        agency="NOAA CPC",
        cadence="monthly",
        tier="context",
        note="A warm tropical Atlantic opposes the Pacific Walker response.",
    ),
    Source(
        key="mei",
        name="Multivariate ENSO Index version 2 (MEI.v2)",
        url="https://psl.noaa.gov/enso/mei/data/meiv2.data",
        agency="NOAA PSL",
        cadence="bimonthly",
        tier="context",
        note="Five coupled variables in one index; the broadest single check.",
    ),
    Source(
        key="discussion",
        name="ENSO Diagnostic Discussion",
        url="https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/enso_advisory/ensodisc.shtml",
        agency="NOAA CPC / IRI",
        cadence="monthly",
        tier="context",
        note="The operational authority. Issued the second Thursday.",
    ),

    # -- spatial: the geometry, not the indices -----------------------------
    Source(
        key="sst_pacific",
        name="OISST v2.1 daily SST and anomaly, tropical Pacific",
        url=erddap(
            f"{COASTWATCH}/griddap/ncdcOisst21Agg.csv",
            f"anom[last][(0.0)]{_PACIFIC},sst[last][(0.0)]{_PACIFIC}",
        ),
        agency="NOAA NCEI via CoastWatch ERDDAP",
        cadence="daily",
        tier="spatial",
        note="The anomaly field the Nino indices are averaged out of.",
    ),
    Source(
        key="sst_global",
        name="OISST v2.1 daily SST anomaly, global",
        url=erddap(
            f"{COASTWATCH}/griddap/ncdcOisst21Agg.csv",
            f"anom[last][(0.0)]{_WORLD}",
        ),
        agency="NOAA NCEI via CoastWatch ERDDAP",
        cadence="daily",
        tier="spatial",
        note="Basin-wide context; the reason relative ONI exists.",
    ),
    Source(
        key="sst_hovmoller",
        name="OISST v2.1 equatorial SST anomaly, time by longitude",
        url=erddap(
            f"{COASTWATCH}/griddap/ncdcOisst21Agg.csv",
            f"anom[({_since(HOVMOLLER_MONTHS)}):7:last][(0.0)]{_EQ_STRIP}",
        ),
        agency="NOAA NCEI via CoastWatch ERDDAP",
        cadence="weekly samples",
        tier="spatial",
        note="Eastward propagation of the surface anomaly.",
    ),
    Source(
        key="tao_temperature",
        name="TAO/TRITON monthly subsurface temperature, equator",
        url=erddap(
            f"{COASTWATCH}/tabledap/pmelTaoMonT.csv",
            f"time,longitude,depth,T_20{_TAO_EQ}",
        ),
        agency="NOAA PMEL via CoastWatch ERDDAP",
        cadence="monthly",
        tier="spatial",
        note="The full record, so the depth section can be shown as an anomaly.",
    ),
    Source(
        key="tao_isotherm",
        name="TAO/TRITON monthly 20 °C isotherm depth, equator",
        url=erddap(
            f"{COASTWATCH}/tabledap/pmelTaoMonIso.csv",
            f"time,longitude,ISO_6{_TAO_EQ}",
        ),
        agency="NOAA PMEL via CoastWatch ERDDAP",
        cadence="monthly",
        tier="spatial",
        note="Thermocline depth; the clearest view of Kelvin wave propagation.",
    ),
    Source(
        key="tao_mesh",
        name="TAO/TRITON daily 20 °C isotherm depth, whole array",
        url=erddap(
            f"{PMEL}/tabledap/pmelTaoDyIso.csv",
            f"time,latitude,longitude,ISO_6&time>={_since(1)}",
        ),
        agency="NOAA PMEL",
        cadence="daily",
        tier="spatial",
        note="Off-equatorial rows too, for the thermocline surface.",
    ),
    Source(
        key="ssh_pacific",
        name="Sea surface height anomaly from altimetry, tropical Pacific",
        url=erddap(
            f"{COASTWATCH}/griddap/nesdisSSH1day_Lon0360.csv",
            "sla[last][(-25):10:(25)][(120):10:(290)]",
        ),
        agency="NOAA NESDIS via CoastWatch ERDDAP",
        cadence="daily, experimental",
        tier="spatial",
        note="Height stands in for upper-ocean heat content. Often weeks behind.",
    ),
    Source(
        key="ssh_hovmoller",
        name="Sea surface height anomaly, equatorial time by longitude",
        url=erddap(
            f"{COASTWATCH}/griddap/nesdisSSH1day_Lon0360.csv",
            f"sla[({_since(HOVMOLLER_MONTHS)}):7:last]{_EQ_STRIP}",
        ),
        agency="NOAA NESDIS via CoastWatch ERDDAP",
        cadence="weekly samples, experimental",
        tier="spatial",
        note="Kelvin and Rossby wave tracking, independent of the moorings.",
    ),

    # -- cyclones: what the boundary condition actually produced -------------
    Source(
        key="nhc_current",
        name="NHC active tropical cyclones",
        url="https://www.nhc.noaa.gov/CurrentStorms.json",
        agency="NOAA National Hurricane Center",
        cadence="every advisory cycle",
        tier="cyclone",
        note="The index of live storms. Names and ATCF ids for the deck fetches.",
    ),
    Source(
        key="atcf_index",
        name="ATCF best-track directory listing",
        url="https://ftp.nhc.noaa.gov/atcf/btk/",
        agency="NOAA National Hurricane Center",
        cadence="continuous",
        tier="cyclone",
        note="Every storm of the current season, live or finished.",
    ),
    Source(
        key="hurdat_index",
        name="HURDAT2 best-track archive index",
        url="https://www.nhc.noaa.gov/data/#hurdat",
        agency="NOAA National Hurricane Center",
        cadence="annual",
        tier="cyclone",
        note="Scraped for the current filenames, which are renamed every spring.",
    ),

    # -- formation outlooks and the storms NHC does not warn on --------------
    Source(
        key="nhc_outlook_at",
        name="NHC Graphical Tropical Weather Outlook, Atlantic",
        url="https://www.nhc.noaa.gov/xgtwo/gtwo_atl.kmz",
        agency="NOAA National Hurricane Center",
        cadence="four times a day",
        tier="cyclone",
        note="Areas NHC is watching, with the 2-day and 7-day chance of formation.",
    ),
    Source(
        key="nhc_outlook_ep",
        name="NHC Graphical Tropical Weather Outlook, eastern North Pacific",
        url="https://www.nhc.noaa.gov/xgtwo/gtwo_pac.kmz",
        agency="NOAA National Hurricane Center",
        cadence="four times a day",
        tier="cyclone",
        note="Areas NHC is watching, with the 2-day and 7-day chance of formation.",
    ),
    Source(
        key="nhc_outlook_cp",
        name="CPHC Graphical Tropical Weather Outlook, central North Pacific",
        url="https://www.nhc.noaa.gov/xgtwo/gtwo_cpac.kmz",
        agency="NOAA Central Pacific Hurricane Center",
        cadence="four times a day",
        tier="cyclone",
        note="Areas CPHC is watching, with the 2-day and 7-day chance of formation.",
    ),
    Source(
        key="jtwc_rss",
        name="JTWC tropical cyclone warnings index",
        url="https://www.metoc.navy.mil/jtwc/rss/jtwc.rss",
        agency="Joint Typhoon Warning Center",
        cadence="every warning",
        tier="cyclone",
        note="Live warnings for the west Pacific, Indian Ocean and southern hemisphere.",
    ),
    Source(
        key="jtwc_abpw",
        name="JTWC significant tropical weather advisory, west and south Pacific",
        url="https://www.metoc.navy.mil/jtwc/products/abpwweb.txt",
        agency="Joint Typhoon Warning Center",
        cadence="daily, and when a suspect area changes",
        tier="cyclone",
        note="Suspect areas with their potential for a significant tropical cyclone in 24 hours.",
    ),
    Source(
        key="jtwc_abio",
        name="JTWC significant tropical weather advisory, Indian Ocean",
        url="https://www.metoc.navy.mil/jtwc/products/abioweb.txt",
        agency="Joint Typhoon Warning Center",
        cadence="daily, and when a suspect area changes",
        tier="cyclone",
        note="Suspect areas with their potential for a significant tropical cyclone in 24 hours.",
    ),
)

# -- dynamic sources ------------------------------------------------------
# Three feeds cannot live in the registry above because their URLs are not
# known until something else has been read: a storm's decks depend on which
# storms exist today, and the HURDAT2 filenames depend on what the index page
# currently lists. They are built on demand and handed to ``fetch``, which
# neither knows nor cares whether a Source came from the registry.

ATCF = "https://ftp.nhc.noaa.gov/atcf"
# Each deck lives in its own directory with its own naming rule, and the three
# rules disagree: the best track is prefixed and plain, the forecast is
# unprefixed with its own extension, and the guidance is prefixed and stored
# gzipped. Getting any of them wrong is a 404, not a parse error.
DECKS = {
    "b": (f"{ATCF}/btk/b{{id}}.dat", "best track", "every six hours"),
    "f": (f"{ATCF}/fst/{{id}}.fst", "official forecast", "every advisory"),
    "a": (f"{ATCF}/aid_public/a{{id}}.dat.gz", "model guidance", "every six hours"),
}


def deck_source(deck: str, storm_id: str, name: str = "") -> Source:
    """An ATCF deck for one storm. ``storm_id`` is lower-case, e.g. ep172026."""
    template, described, cadence = DECKS[deck]
    label = f"{name} ({storm_id.upper()})" if name else storm_id.upper()
    return Source(
        key=f"atcf_{deck}_{storm_id}",
        name=f"ATCF {deck}-deck, {described}: {label}",
        url=template.format(id=storm_id),
        agency="NOAA National Hurricane Center",
        cadence=cadence,
        tier="cyclone",
        note="Per-storm feed, discovered from the active-storm index.",
    )


def hurdat_source(basin: str, filename: str) -> Source:
    """A HURDAT2 best-track file, whose name is read off the index page."""
    return Source(
        key=f"hurdat_{basin.lower()}",
        name=f"HURDAT2 best track, {basin}",
        url=f"https://www.nhc.noaa.gov/data/hurdat/{filename}",
        agency="NOAA National Hurricane Center",
        cadence="annual",
        tier="cyclone",
        note="The climatology this season is measured against.",
    )


# The products NHC issues per storm to protect people, as CurrentStorms.json
# links them. Their URLs change every advisory, so each is fetched through a
# source built from the link, and cached under a key that does not.
PRODUCTS = {
    "watches": "coastal watches and warnings",
    "cone": "forecast cone",
    "surge": "peak storm surge",
    "winds": "wind speed probabilities",
    "in_effect": "public advisory",
}


def product_source(kind: str, storm_id: str, url: str, name: str = "") -> Source:
    """One of a storm's protective products, at the URL the index gives."""
    label = f"{name} ({storm_id.upper()})" if name else storm_id.upper()
    return Source(
        key=f"nhc_{kind}_{storm_id}",
        name=f"NHC {PRODUCTS[kind]}: {label}",
        url=url,
        agency="NOAA National Hurricane Center",
        cadence="every advisory",
        tier="cyclone",
        note="Per-storm product, linked from the active-storm index.",
    )


JTWC_PRODUCTS = "https://www.metoc.navy.mil/jtwc/products"


def jtwc_source(filename: str) -> Source:
    """A JTWC warning's machine-readable file, ``wp2526.tcw``."""
    return Source(
        key=f"jtwc_{filename.rsplit('.', 1)[0].lower()}",
        name=f"JTWC warning {filename}",
        url=f"{JTWC_PRODUCTS}/{filename}",
        agency="Joint Typhoon Warning Center",
        cadence="every six hours",
        tier="cyclone",
        note="Per-storm warning, discovered from the JTWC index.",
    )


SOURCES_BY_KEY = {s.key: s for s in SOURCES}
CRITICAL_KEYS = tuple(s.key for s in SOURCES if s.critical)


@dataclass
class Fetched:
    source: Source
    text: str
    fetched_at: str
    from_cache: bool
    sha256: str
    error: str | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.error is None and bool(self.text)


def decode_payload(payload: bytes, content_encoding: str | None = None) -> str:
    """The text a download stands for, whatever it was wrapped in.

    Content-Encoding covers a server that compressed the transfer; the magic
    bytes cover a file that is *stored* gzipped, which is how NHC publishes
    the a-decks. Without the second check those arrive as binary and parse as
    nothing. A zip is how NHC publishes its outlooks, cones and warnings - a
    KMZ, one KML beside its icons - and the KML is the only part read, so it
    is what the cache keeps, as text like every other feed.
    """
    if content_encoding == "gzip" or payload[:2] == b"\x1f\x8b":
        payload = gzip.GzipFile(fileobj=io.BytesIO(payload)).read()
    if payload[:4] == b"PK\x03\x04":
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            for name in archive.namelist():
                if name.lower().endswith(".kml"):
                    return archive.read(name).decode("utf-8", errors="replace")
        raise ValueError("zip carries no KML")
    return payload.decode("utf-8", errors="replace")


def _http_get(url: str) -> str:
    """GET a URL, transparently handling gzip and flaky NOAA endpoints."""
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/plain,text/html,*/*",
            "Accept-Encoding": "gzip, identity",
        },
    )
    context = ssl.create_default_context()
    last: Exception | None = None
    for attempt in range(1, RETRIES + 1):
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT, context=context) as response:
                return decode_payload(response.read(),
                                      response.headers.get("Content-Encoding"))
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
            last = exc
            if attempt < RETRIES:
                time.sleep(BACKOFF * attempt)
    raise RuntimeError(f"{type(last).__name__}: {last}")


def fetch(source: Source, raw_dir: Path, offline: bool = False) -> Fetched:
    """Fetch one source, archiving the raw payload and falling back to cache."""
    raw_dir.mkdir(parents=True, exist_ok=True)
    cache_path = raw_dir / f"{source.key}.cache"
    meta_path = raw_dir / f"{source.key}.meta.json"
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    if not offline:
        try:
            # One line ending from here on, and the cache written without
            # translation. In text mode on Windows every "\n" was written as
            # "\r\n" and every CRLF a feed sent became "\r\r\n", which read
            # back as two lines; and the archive's digest, taken over the
            # text, never matched the translated file, so it was rewritten on
            # every run.
            text = _http_get(source.url).replace("\r\n", "\n")
            digest = hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()
            cache_path.write_text(text, encoding="utf-8", newline="")
            meta_path.write_text(
                json.dumps(
                    {"url": source.url, "fetched_at": now, "sha256": digest, "bytes": len(text)},
                    indent=2,
                ),
                encoding="utf-8",
            )
            _archive(raw_dir, source.key, text, digest)
            return Fetched(source, text, now, from_cache=False, sha256=digest)
        except Exception as exc:  # noqa: BLE001 - surfaced to the user in the report
            network_error = str(exc)
    else:
        network_error = "offline mode requested"

    if cache_path.exists():
        text = cache_path.read_text(encoding="utf-8")
        meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
        stamp = meta.get("fetched_at", "unknown")
        return Fetched(
            source,
            text,
            stamp,
            from_cache=True,
            sha256=meta.get("sha256", ""),
            warnings=[f"live fetch failed ({network_error}); using cache from {stamp}"],
        )

    return Fetched(source, "", now, from_cache=False, sha256="", error=network_error)


def _archive(raw_dir: Path, key: str, text: str, digest: str) -> None:
    """Keep one dated snapshot per day so the record can be audited later."""
    archive_dir = raw_dir / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    path = archive_dir / f"{key}_{stamp}.txt"
    if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() == digest:
        return
    path.write_text(text, encoding="utf-8", newline="")


def fetch_all(
    raw_dir: Path, offline: bool = False, progress=None
) -> dict[str, Fetched]:
    """Fetch the whole registry, a few at a time.

    Serially this is ~25 round trips to servers that are occasionally slow;
    in parallel the run finishes in the time of the slowest one. ``progress``,
    if given, is called with (done, total, key) after each source lands.
    """
    raw_dir.mkdir(parents=True, exist_ok=True)
    results: dict[str, Fetched] = {}
    workers = 1 if offline else MAX_PARALLEL
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(fetch, source, raw_dir, offline): source for source in SOURCES
        }
        done = 0
        for future in futures:
            source = futures[future]
            try:
                results[source.key] = future.result()
            except Exception as exc:  # noqa: BLE001 - never let one feed kill the run
                results[source.key] = Fetched(
                    source, "", "", from_cache=False, sha256="", error=str(exc)
                )
            done += 1
            if progress:
                progress(done, len(SOURCES), source.key)
    return {source.key: results[source.key] for source in SOURCES}
