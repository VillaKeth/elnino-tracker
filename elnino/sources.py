"""Live ENSO data sources: fetch, retry, and archive raw snapshots.

Every source is an authoritative product: NOAA's, from CPC (with IRI for the
diagnostic discussion), PSL, PMEL, NCEI, CoastWatch and the National and
Central Pacific Hurricane Centers; the Queensland Government's LongPaddock's
daily SOI, on the Bureau of Meteorology's definition; Remote Sensing Systems'
CCMP ocean winds, from NOAA PIFSC's OceanWatch; and the Joint Typhoon Warning
Center's warnings. Nothing here depends on third-party packages so the
tracker keeps working on a bare Python install.

Sources are grouped into tiers, which is how the rest of the system decides how
badly it is hurt when one goes dark:

    core        the indices NOAA declares episodes with - fatal if missing
    ocean       subsurface and basin-wide ocean state
    atmosphere  the coupled atmospheric response
    context     other basins, modulators, and narrative
"""

from __future__ import annotations

import contextlib
import gzip
import hashlib
import io
import json
import os
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import NamedTuple

USER_AGENT = "elnino-tracker/2.0 (+personal ENSO monitoring; contact: local user)"
TIMEOUT = 45
RETRIES = 3
BACKOFF = 2.5
MAX_PARALLEL = 6  # polite against CPC; the whole registry still lands in ~15s
# How long a copy of an ERDDAP table serves before the table is asked for
# again. ERDDAP makes each table afresh for each request, so it cannot say
# whether one changed: its Last-Modified is the moment it answered, and it
# answers a conditional request in full. TAO's moorings, the tables read here,
# are averaged by the day and the month.
TABLE_REST = timedelta(hours=1)
# How long a server's word that a file has not changed serves a copy, from the
# copy's download; after it the file is asked for whole. A file put back from
# a backup keeps the backup's older date, so a copy of what it replaced would
# be told it has not changed until the file next did, a month for ONI.
WHOLE_AFTER = timedelta(days=1)

CPC = "https://www.cpc.ncep.noaa.gov/data/indices"

# ERDDAP endpoints for the spatial tier. CoastWatch's West Coast node carries
# OISST and a monthly aggregate of the mooring array, PMEL the daily mooring
# data; NCEI's own ERDDAP and CoastWatch's central one come in below.
COASTWATCH = "https://coastwatch.pfeg.noaa.gov/erddap"
PMEL = "https://data.pmel.noaa.gov/pmel/erddap"

# OISST comes as two products of one analysis. The final is about two weeks
# behind; the preliminary is a day or two behind. NOAA's own files replace
# each preliminary day with the final's once it lands, but CoastWatch's
# preliminary dataset keeps its days, so the two overlap by about two weeks,
# which is what lets the run measure what the final changed. CPC's weekly
# index, out on the Monday after the week it means, can only be built from
# the preliminary for its latest weeks. So the maps take whichever of the two
# has the later day, and the Hovmoller and the daily boxes keep the final for
# their record and take from the preliminary only the days since the final
# ends. The preliminary has gaps (eleven days at the turn of 2026), which is
# why its days are never picked by a stride.
OISST_FINAL = f"{COASTWATCH}/griddap/ncdcOisst21Agg.csv"
OISST_NRT = f"{COASTWATCH}/griddap/ncdcOisst21NrtAgg.csv"

# NCEI, which makes OISST, serves both products from its own ERDDAP too, and
# stands behind CoastWatch: a product CoastWatch fails is asked there for the
# same subset. Its preliminary dataset keeps only the days its final has not
# yet replaced, about two weeks, so a run it serves cannot measure what the
# final changed. It names the depth axis "depth" where CoastWatch has "zlev",
# and its units "Celsius" for "degree_C"; the cells and their values are
# CoastWatch's.
NCEI = "https://www.ncei.noaa.gov/erddap"
NCEI_FINAL = f"{NCEI}/griddap/ncdc_oisst_v2_avhrr_by_time_zlev_lat_lon.csv"
NCEI_NRT = f"{NCEI}/griddap/ncdc_oisst_v2_avhrr_prelim_by_time_zlev_lat_lon.csv"

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


def is_preliminary(url: str) -> bool:
    """Whether an address asks OISST's preliminary analysis, of either server."""
    return url.partition("?")[0] in (OISST_NRT, NCEI_NRT)


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
# The four Nino boxes' cells, every day: half a degree on the very points the
# Pacific map samples (29.875S and 100.125E onward), so a day both carry has
# the same box means on the map as in the day-by-day series.
_NINO_CELLS = "[(-9.875):2:(4.625)][(160.125):2:(279.625)]"
# The Indian Ocean Dipole's poles' cells, every day: half a degree as the Nino
# boxes' are, over 10S-10N and 50-110E, which holds the west pole and the east
# (grids.IOD_BOXES). One degree put the DMI 0.027 degC off the full grid on 13
# October 2026, half a degree 0.009.
_IOD_CELLS = "[(-9.875):2:(9.625)][(50.125):2:(109.625)]"
# Days asked for: the final's last 90, and the preliminary's last 28, which
# covers the final's two weeks behind it with room for the final to slip.
_RECORD_DAYS = "[last-89:1:last]"
_RECENT_DAYS = "[last-27:1:last]"
# NCEI's preliminary holds only the days its final has not reached, and
# refuses a window that reaches back past its first: all of them, then all
# but the oldest when that fails. The oldest day's file is taken away when
# the final replaces it, hours before NCEI's ERDDAP stops listing the day,
# and asking for it meanwhile is an error (29 September's, on 14 October).
_NCEI_RECENT_DAYS = ("[0:1:last]", "[1:1:last]")
# A Hovmoller's record: a row every seventh of the dataset's days back from
# its latest for sixty-nine of them, about sixteen months, a week apart where
# the dataset has every day and a step longer across a day it lacks. Ending on
# the latest day, the SST record leaves the preliminary only the days the
# final has not reached; the sea-level strip asks the same.
_RECORD_WEEKS = "[last-483:7:last]"
_TAO_EQ = "&latitude>=-0.6&latitude<=0.6"

# Sea level, from NOAA CoastWatch's own ERDDAP: its blend of the altimeters'
# near-real-time passes, a day or two behind, with the West Coast node's
# experimental product of the altimeters' passes, weeks behind, behind it. Both
# run their longitudes from -180 to 180, so the tropical Pacific, which
# crosses the date line, is asked for whole circles of latitude on the very
# points the earlier requests sampled east of Greenwich, and the grids keep
# the Pacific's longitudes, 0 to 360: the map's 120E to 70W and the strip's
# 120E to 80W.
SSH = "https://coastwatch.noaa.gov/erddap/griddap/noaacwBLENDEDsshDaily.csv"
SSH_EXPERIMENTAL = f"{COASTWATCH}/griddap/nesdisSSH1day.csv"
_SSH_MAP = "[(-24.875):10:(25.125)][(-179.875):10:(179.875)]"
_SSH_STRIP = "[(-1.875):4:(2.125)][(-179.875):4:(179.875)]"
SSH_MAP_LONS = (120.125, 290.125)
SSH_STRIP_LONS = (120.125, 280.125)
# What each is, as the panels say it of the field it served. How far behind
# the field is, the panels' chips say from its own day: a copy serving through
# an outage is as far behind as it is, whatever its product usually is.
SSH_PRODUCTS = {
    SSH: "NOAA CoastWatch's blend of the altimeters' near-real-time passes",
    SSH_EXPERIMENTAL: ("the West Coast node's experimental product of the altimeters' passes, "
                       "serving while CoastWatch's own ERDDAP fails"),
}

# Ocean winds, from NOAA PIFSC's OceanWatch ERDDAP: Remote Sensing Systems'
# Cross-Calibrated Multi-Platform (CCMP) 10 m winds, version 2.1 near real
# time, an analysis of satellite radiometer and scatterometer winds over NCEP's
# GFS, six-hourly on a quarter degree, a day or two behind. CoastWatch's copy
# stopped on 2 June 2026. The westerly wind events (``winds``) take the last
# 360 analyses, every other one back from the latest: 180 days twice a day, 12
# hours apart. The cells are every ninth, 2.25 degrees apart and symmetric
# about the equator, 14.625S to 14.625N by 120.125E to 279.875E: the cells of
# the vendored base (``windclim``).
CCMP_NRT = "https://oceanwatch.pifsc.noaa.gov/erddap/griddap/ccmp-daily-v2-1-NRT.csv"
_WIND_DAYS = "[last-718:2:last]"
_WIND_CELLS = "[(-14.625):9:(14.625)][(120.125):9:(279.875)]"


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
    # The same subset of OISST's final analysis, for a feed whose ``url`` asks
    # the preliminary. Both are asked their latest day and the later serves;
    # on a day both carry, the final's, which is the better analysis of it.
    final: str = ""
    # The same subsets on a second server, asked in turn when the first fails
    # its product: NCEI's own ERDDAP for OISST, the West Coast node's for sea
    # level; ``fallback`` for ``url``'s, ``final_fallback`` for ``final``'s.
    fallback: tuple[str, ...] = ()
    final_fallback: tuple[str, ...] = ()
    # Whether each day's download is kept in the archive as well. Not for a
    # rolling window of days, each day's of which repeats all but a day of the
    # day before's, of a product NOAA keeps every day of itself.
    archive: bool = True
    # Whether the feed is markup itself, a web page, an RSS feed or a KML
    # file. Any other feed's answer that is markup is a page where its file
    # should be, as a server down for maintenance or a file moved can send
    # with a 200, and is no answer.
    markup: bool = False


# The SOI on the Bureau of Meteorology's definition, Troup's against
# 1933-1992, worked out day by day from the day's Tahiti and Darwin pressures
# by the Queensland Government's LongPaddock: every day since 1999 in one
# file. The Bureau's own daily SOI data have been unavailable since January
# 2025, when Meteo-France changed its Tahiti data service.
LONGPADDOCK_SOI = ("https://data.longpaddock.qld.gov.au/SeasonalClimateOutlook/"
                   "SouthernOscillationIndex/SOIDataFiles/DailySOI1933-1992Base.txt")


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
        key="soi_daily",
        name=("Daily SOI on the Bureau of Meteorology's definition "
              "(Troup's, Tahiti-Darwin, 1933-1992 base)"),
        url=LONGPADDOCK_SOI,
        agency="Queensland Government (LongPaddock)",
        cadence="daily, a day behind",
        tier="atmosphere",
        archive=False,
        note=("A day is its year and its day of the year; -999.9 is a missing pressure. "
              "The 30- and 90-day SOI are the means of the days'."),
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
        markup=True,
        note="The operational authority. Issued the second Thursday.",
    ),

    # -- spatial: the geometry, not the indices -----------------------------
    Source(
        key="sst_pacific",
        name="OISST v2.1 daily SST and anomaly, tropical Pacific (preliminary)",
        url=erddap(OISST_NRT, f"anom[last][(0.0)]{_PACIFIC},sst[last][(0.0)]{_PACIFIC}"),
        final=erddap(OISST_FINAL, f"anom[last][(0.0)]{_PACIFIC},sst[last][(0.0)]{_PACIFIC}"),
        fallback=(
            erddap(NCEI_NRT, f"anom[last][(0.0)]{_PACIFIC},sst[last][(0.0)]{_PACIFIC}"),
        ),
        final_fallback=(
            erddap(NCEI_FINAL, f"anom[last][(0.0)]{_PACIFIC},sst[last][(0.0)]{_PACIFIC}"),
        ),
        agency="NOAA NCEI, via CoastWatch's ERDDAP or its own",
        cadence="daily, a day or two behind",
        tier="spatial",
        note=("The anomaly field the Nino indices are averaged out of. The final "
              "analysis, two weeks behind, if the preliminary fails."),
    ),
    Source(
        key="sst_global",
        name="OISST v2.1 daily SST anomaly, global (preliminary)",
        url=erddap(OISST_NRT, f"anom[last][(0.0)]{_WORLD}"),
        final=erddap(OISST_FINAL, f"anom[last][(0.0)]{_WORLD}"),
        fallback=(erddap(NCEI_NRT, f"anom[last][(0.0)]{_WORLD}"),),
        final_fallback=(erddap(NCEI_FINAL, f"anom[last][(0.0)]{_WORLD}"),),
        agency="NOAA NCEI, via CoastWatch's ERDDAP or its own",
        cadence="daily, a day or two behind",
        tier="spatial",
        note=("Basin-wide context; the reason relative ONI exists. The final "
              "analysis if the preliminary fails."),
    ),
    Source(
        key="sst_hovmoller",
        name="OISST v2.1 equatorial SST anomaly, time by longitude",
        url=erddap(OISST_FINAL, f"anom{_RECORD_WEEKS}[(0.0)]{_EQ_STRIP}"),
        fallback=(erddap(NCEI_FINAL, f"anom{_RECORD_WEEKS}[(0.0)]{_EQ_STRIP}"),),
        agency="NOAA NCEI, via CoastWatch's ERDDAP or its own",
        cadence="weekly samples",
        tier="spatial",
        note="Eastward propagation of the surface anomaly.",
    ),
    Source(
        key="sst_hovmoller_recent",
        name="OISST v2.1 equatorial SST anomaly, the last four weeks (preliminary)",
        url=erddap(OISST_NRT, f"anom{_RECENT_DAYS}[(0.0)]{_EQ_STRIP}"),
        fallback=tuple(erddap(NCEI_NRT, f"anom{days}[(0.0)]{_EQ_STRIP}")
                       for days in _NCEI_RECENT_DAYS),
        agency="NOAA NCEI, via CoastWatch's ERDDAP or its own",
        cadence="daily, a day or two behind",
        tier="spatial",
        archive=False,
        note="The Hovmoller's rows since the final analysis ends, to the latest day.",
    ),
    Source(
        key="nino_daily",
        name="OISST v2.1 SST anomaly over the Nino boxes, the last 90 days",
        url=erddap(OISST_FINAL, f"anom{_RECORD_DAYS}[(0.0)]{_NINO_CELLS}"),
        fallback=(erddap(NCEI_FINAL, f"anom{_RECORD_DAYS}[(0.0)]{_NINO_CELLS}"),),
        agency="NOAA NCEI, via CoastWatch's ERDDAP or its own",
        cadence="daily, about two weeks behind",
        tier="spatial",
        archive=False,
        note="The four boxes' means day by day, from the final analysis.",
    ),
    Source(
        key="nino_daily_recent",
        name="OISST v2.1 SST anomaly over the Nino boxes, the last four weeks (preliminary)",
        url=erddap(OISST_NRT, f"anom{_RECENT_DAYS}[(0.0)]{_NINO_CELLS}"),
        fallback=tuple(erddap(NCEI_NRT, f"anom{days}[(0.0)]{_NINO_CELLS}")
                       for days in _NCEI_RECENT_DAYS),
        agency="NOAA NCEI, via CoastWatch's ERDDAP or its own",
        cadence="daily, a day or two behind",
        tier="spatial",
        archive=False,
        note="The boxes' days since the final analysis ends, to the latest day.",
    ),
    Source(
        key="iod_daily",
        name="OISST v2.1 SST anomaly over the Indian Ocean Dipole's poles, the last 90 days",
        url=erddap(OISST_FINAL, f"anom{_RECORD_DAYS}[(0.0)]{_IOD_CELLS}"),
        fallback=(erddap(NCEI_FINAL, f"anom{_RECORD_DAYS}[(0.0)]{_IOD_CELLS}"),),
        agency="NOAA NCEI, via CoastWatch's ERDDAP or its own",
        cadence="daily, about two weeks behind",
        tier="spatial",
        archive=False,
        note="The poles' means and the Dipole Mode Index day by day, from the final analysis.",
    ),
    Source(
        key="iod_daily_recent",
        name=("OISST v2.1 SST anomaly over the Indian Ocean Dipole's poles, the last four "
              "weeks (preliminary)"),
        url=erddap(OISST_NRT, f"anom{_RECENT_DAYS}[(0.0)]{_IOD_CELLS}"),
        fallback=tuple(erddap(NCEI_NRT, f"anom{days}[(0.0)]{_IOD_CELLS}")
                       for days in _NCEI_RECENT_DAYS),
        agency="NOAA NCEI, via CoastWatch's ERDDAP or its own",
        cadence="daily, a day or two behind",
        tier="spatial",
        archive=False,
        note="The poles' days since the final analysis ends, to the latest day.",
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
        url=erddap(SSH, f"sla[last]{_SSH_MAP}"),
        fallback=(erddap(SSH_EXPERIMENTAL, f"sla[last]{_SSH_MAP}"),),
        agency="NOAA CoastWatch, at its own ERDDAP or its West Coast node's",
        cadence="daily, a day or two behind",
        tier="spatial",
        note="Height stands in for upper-ocean heat content.",
    ),
    Source(
        key="ssh_hovmoller",
        name="Sea surface height anomaly, equatorial time by longitude",
        url=erddap(SSH, f"sla{_RECORD_WEEKS}{_SSH_STRIP}"),
        fallback=(erddap(SSH_EXPERIMENTAL, f"sla{_RECORD_WEEKS}{_SSH_STRIP}"),),
        agency="NOAA CoastWatch, at its own ERDDAP or its West Coast node's",
        cadence="weekly samples, a day or two behind",
        tier="spatial",
        note="Kelvin and Rossby wave tracking, independent of the moorings.",
    ),
    Source(
        key="wind_daily",
        name="CCMP v2.1 10 m zonal wind, tropical Pacific, the last 180 days (near real time)",
        url=erddap(CCMP_NRT, f"uwnd{_WIND_DAYS}{_WIND_CELLS}"),
        agency="Remote Sensing Systems' CCMP, via NOAA PIFSC's OceanWatch ERDDAP",
        cadence="six-hourly, a day or two behind",
        tier="spatial",
        archive=False,
        note="Westerly wind events, Harrison and Vecchi's, as they happen.",
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
        markup=True,
        note="Every storm of the current season, live or finished.",
    ),
    Source(
        key="hurdat_index",
        name="HURDAT2 best-track archive index",
        url="https://www.nhc.noaa.gov/data/#hurdat",
        agency="NOAA National Hurricane Center",
        cadence="annual",
        tier="cyclone",
        markup=True,
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
        markup=True,
        note="Areas NHC is watching, with the 2-day and 7-day chance of formation.",
    ),
    Source(
        key="nhc_outlook_ep",
        name="NHC Graphical Tropical Weather Outlook, eastern North Pacific",
        url="https://www.nhc.noaa.gov/xgtwo/gtwo_pac.kmz",
        agency="NOAA National Hurricane Center",
        cadence="four times a day",
        tier="cyclone",
        markup=True,
        note="Areas NHC is watching, with the 2-day and 7-day chance of formation.",
    ),
    Source(
        key="nhc_outlook_cp",
        name="CPHC Graphical Tropical Weather Outlook, central North Pacific",
        url="https://www.nhc.noaa.gov/xgtwo/gtwo_cpac.kmz",
        agency="NOAA Central Pacific Hurricane Center",
        cadence="four times a day",
        tier="cyclone",
        markup=True,
        note="Areas CPHC is watching, with the 2-day and 7-day chance of formation.",
    ),
    Source(
        key="jtwc_rss",
        name="JTWC tropical cyclone warnings index",
        url="https://www.metoc.navy.mil/jtwc/rss/jtwc.rss",
        agency="Joint Typhoon Warning Center",
        cadence="every warning",
        tier="cyclone",
        markup=True,
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
        markup=True,
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
    # Where the text came from: the source's own address, its final analysis's,
    # either one's on the second server, or the one the cached copy was
    # downloaded from.
    url: str = ""
    # The copy downloaded at ``fetched_at`` is current, and was not downloaded
    # again: its dataset had no new day, its server said the file had not
    # changed since, or the product's own address is behind the copy the
    # second server made.
    unchanged: bool = False
    # The copy downloaded at ``fetched_at``, under an hour before, of an ERDDAP
    # table, which cannot say whether it changed: it serves without the table
    # being asked for (``TABLE_REST``).
    rested: bool = False

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


class Answer(NamedTuple):
    """What an address answered: its text, and the tag and the date its server
    gave that version of it (``ETag``, ``Last-Modified``), with which the next
    run asks whether it has changed. A server that gives neither is asked for
    the whole file each time."""

    text: str
    etag: str = ""
    modified: str = ""


def _http_get(url: str, headers: dict[str, str] | None = None) -> Answer | None:
    """GET a URL, transparently handling gzip and flaky NOAA endpoints.

    ``headers`` are the ones that ask whether the file has changed since a copy
    (``If-None-Match``, ``If-Modified-Since``): a server that says it has not
    answers 304, and this None. A 304 to a request that asked nothing is no
    answer, and fails as any other would.
    """
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/plain,text/html,*/*",
            "Accept-Encoding": "gzip, identity",
            **(headers or {}),
        },
    )
    context = ssl.create_default_context()
    last: Exception | None = None
    for attempt in range(1, RETRIES + 1):
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT, context=context) as response:
                return Answer(decode_payload(response.read(), response.headers.get("Content-Encoding")),
                              response.headers.get("ETag") or "",
                              response.headers.get("Last-Modified") or "")
        except urllib.error.HTTPError as exc:
            if exc.code == 304 and headers:
                return None
            last = exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last = exc
        if attempt < RETRIES:
            time.sleep(BACKOFF * attempt)
    raise RuntimeError(f"{type(last).__name__}: {last}")


def _asking(meta: dict) -> dict[str, str]:
    """The header that asks a server whether a file has changed since the copy
    ``meta`` records: the date it gave the copy, as it gave it, or with none,
    the tag. A server weighs a tag over a date, and a tag can be one it never
    matches again: PSL's, which Apache's compression ends in "-gzip", was
    answered in full when asked by both, and 304 by its date alone (16 October
    2026), as every server here that gives a date answers."""
    for field, header in (("modified", "If-Modified-Since"), ("etag", "If-None-Match")):
        if isinstance(meta.get(field), str) and meta[field]:
            return {header: meta[field]}
    return {}


def rests(url: str) -> bool:
    """Whether a copy of ``url``'s answer rests (``TABLE_REST``) before it is
    asked for again: an ERDDAP table's, which ERDDAP cannot say has changed."""
    return "/tabledap/" in url.partition("?")[0]


def probe_url(url: str) -> str:
    """Where to ask whether a griddap subset has changed: its dataset's latest
    time, a few bytes, where the subset can be tens of megabytes (the global
    field is forty). A dataset with no new day has nothing new in any subset
    of it ending at its last. Any other feed has no such question to ask."""
    base, sep, _query = url.partition("?")
    if not sep or "/griddap/" not in base:
        return ""
    return f"{base}?{urllib.parse.quote('time[last]', safe='')}"


@dataclass(frozen=True)
class _Product:
    """One product a feed is served from, at its own address or a second
    server's, and the copy kept of it: ``<name>.cache`` beside
    ``<name>.meta.json``, the record of where and when the copy was downloaded,
    the latest day its dataset said it had then, or the copy's last day with
    values when its last day has none, and the digest of the bytes written."""

    name: str
    url: str
    raw_dir: Path
    final: bool = False
    # The same subset on the second server, its addresses asked in turn when
    # ``url`` fails.
    fallback: tuple[str, ...] = ()

    @property
    def addresses(self) -> tuple[str, ...]:
        return (self.url, *self.fallback)

    @property
    def cache(self) -> Path:
        return self.raw_dir / f"{self.name}.cache"

    @property
    def record(self) -> Path:
        return self.raw_dir / f"{self.name}.meta.json"

    def meta(self) -> dict:
        return _read_meta(self.record)

    def kept(self, meta: dict) -> str:
        """The copy's text. Raises when there is none, or when it is not the
        text its record was written for, as after a run stopped between the two."""
        data = self.cache.read_bytes()
        if not data.strip():
            raise ValueError("the copy kept of it is empty")
        if meta.get("sha256") and hashlib.sha256(data).hexdigest() != meta["sha256"]:
            raise ValueError("the copy kept of it does not match its record")
        return data.decode("utf-8", errors="replace")

    def keep(self, data: bytes, meta: dict) -> None:
        """Write the copy and then its record, each whole or not at all."""
        for path, payload in ((self.cache, data),
                              (self.record, json.dumps(meta, indent=2).encode("utf-8"))):
            part = path.with_name(path.name + ".part")
            try:
                part.write_bytes(payload)
                os.replace(part, path)
            except OSError:
                part.unlink(missing_ok=True)
                raise

    def served(self, source: Source, current: bool = False) -> Fetched:
        """The copy, served for want of a live answer, or as ``current`` while
        the product's own address answers behind it."""
        meta = self.meta()
        return Fetched(source, self.kept(meta), meta.get("fetched_at", "unknown"),
                       from_cache=not current, sha256=meta.get("sha256", ""),
                       url=meta.get("url", ""), unchanged=current)


class _Bid(NamedTuple):
    """A product's claim to serve: the latest day an address of it says its
    dataset has, or the day its copy was downloaded at, with the address that
    said the day or that the copy came from."""

    day: str
    live: bool
    product: _Product
    url: str
    # Whether the answer is the second server's for the very day of a copy
    # the product's own address made, which is no reason to download the day
    # again, and CoastWatch's window of the preliminary's days reaches
    # further back than NCEI's.
    echo: bool = False

    def rank(self) -> tuple:
        # The later day first; on a day, a live answer before a copy, and the
        # copy before an echo of its day. A day both products carry is the
        # final's, the better analysis of it; with no day said, the
        # preliminary's, which is as a rule the later.
        standing = 0 if self.echo else 2 if self.live else 1
        first = self.product.final if self.day else not self.product.final
        return (self.day, standing, first)


def _copy_bid(product: _Product) -> list[_Bid]:
    """The product's copy as a bid, when it has one."""
    if not product.cache.exists():
        return []
    meta = product.meta()
    return [_Bid(meta.get("probe", ""), False, product, meta.get("url") or product.url)]


def _beside(answer: _Bid, copy: list[_Bid]) -> bool:
    """Whether the product's copy claims beside an answer of it: beside the
    second server's, which may be days behind it, and beside the day the
    product's own address says when the second server made the copy, which
    CoastWatch back from an outage may be behind."""
    product = answer.product
    return answer.url != product.url or (
        bool(answer.day) and any(made.url in product.fallback for made in copy))


def _live_bids(product: _Product, urls: tuple[str, ...], problems: list[str],
               copied: bool = False) -> list[_Bid]:
    """The product's claim from the first of ``urls`` to say its dataset's latest
    day, and its copy's beside it, unless the copy claims already; with none
    answering, the copy claims alone."""
    copy = _copy_bid(product)
    for url in urls:
        try:
            bid = _Bid(_latest_day(url), True, product, url)
        except Exception as exc:  # noqa: BLE001 - surfaced to the user in the report
            problems.append(_failure(exc, url))
            continue
        if url != product.url:
            bid = bid._replace(echo=bool(bid.day) and any(
                made.url == product.url and made.day == bid.day for made in copy))
        return [bid, *copy] if not copied and _beside(bid, copy) else [bid]
    return [] if copied else copy


def fetch(source: Source, raw_dir: Path, offline: bool = False) -> Fetched:
    """Fetch one source, archiving the raw payload and falling back to cache.

    A feed with OISST's final analysis behind its preliminary has two
    products, and each keeps its own copy. Both are asked their latest day and
    the later serves; when it fails, its copy stands in for it against the
    other. A product whose address fails, there or on the way to its subset, is
    asked of the second server's addresses in turn, and its copy claims beside
    the answer, and ahead of it on the copy's own day when the product's own
    address made the copy. A copy the second server made claims beside the
    product's own address as well, and serves as current while that is behind
    it. A gridded product
    keeps its copy, without downloading the subset again, while its dataset's
    latest day is the one the copy was downloaded at and has values for.
    """
    raw_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    products = [_Product(source.key, source.url, raw_dir, fallback=source.fallback)]
    if source.final:
        products.append(_Product(f"{source.key}.final", source.final, raw_dir, final=True,
                                 fallback=source.final_fallback))

    problems: list[str] = ["offline mode requested"] if offline else []
    bids: list[_Bid] = []
    for product in products:
        bids += _copy_bid(product) if offline else _live_bids(product, product.addresses, problems)

    while bids:
        bid = max(bids, key=_Bid.rank)
        bids.remove(bid)
        # A copy chosen over an answer of the product's own address, which is
        # behind it, is as current as any answer.
        current = not bid.live and any(
            other.live and other.url == bid.product.url for other in bids)
        try:
            got = (_download(source, bid.product, bid.url, bid.day, now) if bid.live
                   else bid.product.served(source, current))
        except Exception as exc:  # noqa: BLE001 - surfaced to the user in the report
            problems.append(_failure(exc, bid.url))
            # On to the product's addresses after the one that failed, and
            # its copy, unless that claims already beside the answer that
            # failed.
            if bid.live:
                addresses = bid.product.addresses
                bids += _live_bids(bid.product, addresses[addresses.index(bid.url) + 1:],
                                   problems, copied=_beside(bid, _copy_bid(bid.product)))
            continue
        # An answer passed over is worth a word: the preliminary's for the
        # final, which has stalled, and any of the product's own for its copy.
        problems += [_passed_over(other, "the final's") for other in bids
                     if bid.product.final and other.live and other.product is not bid.product]
        problems += [_passed_over(other, f"its copy's {bid.day[:10]}") for other in bids
                     if not bid.live and other.live and other.product is bid.product]
        if got.from_cache:
            got.warnings.insert(0, f"live fetch failed ({'; '.join(problems)})")
        elif problems:
            got.warnings.insert(0, f"{'; '.join(problems)}; served by {got.url}")
        return got

    return Fetched(source, "", now, from_cache=False, sha256="", error="; ".join(problems))


def _passed_over(answer: _Bid, than: str) -> str:
    """Why an answer did not serve: the latest day it said was no later than
    ``than``, or it said none, which is no reason to take it for the later."""
    if not answer.day:
        return f"latest day not said ({answer.url})"
    return f"latest day {answer.day[:10]}, no later than {than} ({answer.url})"


def _failure(exc: Exception, url: str) -> str:
    """What failed where, the reason first, so that a line cut short says why."""
    return f"{exc} ({url})"


def _latest_day(url: str) -> str:
    """The latest time a griddap product's dataset says it has, or "" for a
    feed with nothing to ask and for an answer with no time in it. Raises when
    the dataset does not answer: a dataset that cannot say its latest day is
    not asked for the day either."""
    probe = probe_url(url)
    return _latest_time(_http_get(probe).text) if probe else ""


# What a probe answers: ERDDAP's CSV of one time, the last line of it.
_TIME = re.compile(r"\d{4}-\d{2}-\d{2}T[\d:.]+Z?")


def _latest_time(text: str) -> str:
    """The time a probe answered, or "" when it answered anything else, which
    is then no reason to keep the copy there is."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines[-1] if lines and _TIME.fullmatch(lines[-1]) else ""


def _is_griddap_csv(text: str) -> bool:
    """Whether a griddap answer is ERDDAP's CSV of a subset, whole: its columns,
    time first, then their units, then rows, the last of them a row like any
    other. A proxy's page, an empty body, the header of nothing, a row cut
    short or an error written after the rows is not kept, and the day its
    dataset said is not recorded against it."""
    end = len(text)
    while end and text[end - 1] == "\n":
        end -= 1
    head = text.find("\n")
    units = text.find("\n", head + 1) if head >= 0 else -1
    if units < 0 or units >= end:
        return False
    last = text[text.rfind("\n", units, end) + 1:end]
    return (text.startswith("time,") and bool(_TIME.match(last))
            and last.count(",") == text.count(",", 0, head))


# The columns of a griddap answer that say where a value is, not what it is:
# ERDDAP's standard axes, and the depth CoastWatch's OISST calls "zlev".
_AXES = frozenset({"time", "altitude", "depth", "latitude", "longitude", "zlev"})


def _last_times(text: str) -> tuple[str, str]:
    """The times of the last row of a griddap answer, whole, and of its last
    row with a value in it, "" when no row has one. A dataset can list a day
    before its values are in it, as NCEI's preliminary OISST listed 12 October
    with every cell NaN; the rows are read from the end, so a day with values
    is done with at its last row."""
    head = text.find("\n")
    names = text[:head].split(",")
    values = [i for i, name in enumerate(names) if name not in _AXES]
    first = text.find("\n", head + 1) + 1
    end, last = len(text), ""
    while end > first:
        start = text.rfind("\n", first - 1, end) + 1
        row = text[start:end].split(",")
        if len(row) == len(names):
            last = last or row[0]
            if any(row[i] != "NaN" for i in values):
                return last, row[0]
        end = start - 1
    return last, ""


# Markup from its first character on, past any white space or byte order mark.
_MARKUP = re.compile(r"[\N{ZERO WIDTH NO-BREAK SPACE}\s]*<")


def _is_markup(text: str) -> bool:
    """Whether an answer is markup: a web page, an RSS feed or a KML file. No
    other feed's file opens with a tag."""
    return bool(_MARKUP.match(text))


def _read_meta(path: Path) -> dict:
    """What was recorded of the cached copy: where and when it came from."""
    try:
        meta = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return meta if isinstance(meta, dict) else {}


def _download(source: Source, product: _Product, url: str, said: str, now: str) -> Fetched:
    """A product's text, downloaded from ``url`` and kept, or its copy when the
    copy came from there and the dataset's latest day, as it ``said``, is the
    one the copy is recorded at; or the copy is of an ERDDAP table downloaded
    within the hour (TABLE_REST); or the server, asked with the date it gave
    the copy, or with none the tag, says the file has not changed since, which
    it is asked for a day from the copy's download (WHOLE_AFTER). Raises when
    the address fails or answers with anything but its data, as a web page is
    for a feed that is not one, or with a subset of nothing but NaN."""
    meta = product.meta()
    ours = meta.get("url") == url
    if said and meta.get("probe") == said and ours:
        # A copy that is gone, or is not what its record was written for, is
        # downloaded again.
        with contextlib.suppress(OSError, ValueError):
            return _current(source, product.kept(meta), meta, url, now)
    if ours and rests(url):
        # So is one whose record says no time it was downloaded, or a time
        # after now, as a clock put back would.
        with contextlib.suppress(OSError, ValueError, TypeError):
            if _within(meta.get("fetched_at"), now, TABLE_REST):
                return Fetched(source, product.kept(meta), meta["fetched_at"], from_cache=False,
                               sha256=meta.get("sha256", ""), url=url, rested=True)
    # Only a copy that reads back is worth asking after: told it has not
    # changed, the run would have nothing else to serve. And only for a day
    # from its download, so not one whose record says no time it was
    # downloaded, or a time after now.
    copy, asking = None, {}
    if ours:
        with contextlib.suppress(ValueError, TypeError):
            if _within(meta.get("fetched_at"), now, WHOLE_AFTER):
                asking = _asking(meta)
    if asking:
        with contextlib.suppress(OSError, ValueError):
            copy = product.kept(meta)
    answer = _http_get(url, asking if copy is not None else None)
    if answer is None:
        return _current(source, copy, meta, url, now)
    # One line ending from here on, and the copy written as the very bytes its
    # digest is taken over. In text mode on Windows every "\n" was written as
    # "\r\n" and every CRLF a feed sent became "\r\r\n", which read back as
    # two lines; and the archive's digest never matched the translated file,
    # so it was rewritten on every run.
    text = answer.text.replace("\r\n", "\n")
    if probe_url(url):
        if not _is_griddap_csv(text):
            raise ValueError("its answer is not ERDDAP's CSV")
        last, valued = _last_times(text)
        if not valued:
            raise ValueError("its answer has no values")
        if said and valued != last:
            # A day listed before its values are in it: the copy is recorded
            # at the last day it has values for, so that the subset is asked
            # for again until they come.
            said = valued
    elif not text.strip():
        raise ValueError("its answer is empty")
    elif not source.markup and _is_markup(text):
        raise ValueError("its answer is a web page")
    data = text.encode("utf-8")
    digest = hashlib.sha256(data).hexdigest()
    got = Fetched(source, text, now, from_cache=False, sha256=digest, url=url)
    record = {"url": url, "fetched_at": now, "sha256": digest, "bytes": len(data)}
    if said:
        record["probe"] = said
    if answer.etag:
        record["etag"] = answer.etag
    if answer.modified:
        record["modified"] = answer.modified
    # The text serves whether or not it can be kept.
    try:
        product.keep(data, record)
    except OSError as exc:
        got.warnings.append(f"kept no copy: {exc}")
    if source.archive:
        try:
            _archive(product.raw_dir, product.name, data, digest)
        except OSError as exc:
            got.warnings.append(f"archived no copy: {exc}")
    return got


def _within(stamp, now: str, span: timedelta) -> bool:
    """Whether the time ``stamp`` is no later than ``now`` and less than
    ``span`` before it. Raises for a stamp that is not a time with its zone."""
    return timedelta(0) <= datetime.fromisoformat(now) - datetime.fromisoformat(stamp) < span


def _current(source: Source, text: str, meta: dict, url: str, now: str) -> Fetched:
    """The copy, current though not downloaded again: unchanged since it was."""
    return Fetched(source, text, meta.get("fetched_at", now), from_cache=False,
                   sha256=meta.get("sha256", ""), url=url, unchanged=True)


def _archive(raw_dir: Path, name: str, data: bytes, digest: str) -> None:
    """Keep one dated snapshot per day so the record can be audited later."""
    archive_dir = raw_dir / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    path = archive_dir / f"{name}_{stamp}.txt"
    if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() == digest:
        return
    path.write_bytes(data)


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
