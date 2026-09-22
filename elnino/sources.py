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
_EQ_STRIP = "[(-2):8:(2)][(120):8:(280)]"
_PACIFIC = "[(-30):4:(30)][(100):4:(300)]"
_WORLD = "[(-66):10:(66)][(0):10:(358)]"
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
        name="Oceanic Nino Index (ONI), 3-month running Nino-3.4 anomaly",
        url=f"{CPC}/oni.ascii.txt",
        agency="NOAA CPC",
        cadence="monthly",
        tier="core",
        note="Official index NOAA uses to declare El Nino / La Nina episodes.",
        critical=True,
    ),
    Source(
        key="roni",
        name="Relative ONI (RONI), ONI minus tropical-mean SST anomaly",
        url=f"{CPC}/RONI.ascii.txt",
        agency="NOAA CPC",
        cadence="monthly",
        tier="core",
        note="Removes the tropical-wide warming trend; better cross-era comparison.",
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
        name="TAO/TRITON monthly 20 C isotherm depth, equator",
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
        name="TAO/TRITON daily 20 C isotherm depth, whole array",
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
                payload = response.read()
                if response.headers.get("Content-Encoding") == "gzip":
                    payload = gzip.GzipFile(fileobj=io.BytesIO(payload)).read()
                return payload.decode("utf-8", errors="replace")
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
            text = _http_get(source.url)
            digest = hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()
            cache_path.write_text(text, encoding="utf-8")
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
    path.write_text(text, encoding="utf-8")


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
