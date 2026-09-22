"""The atmospheric half of the coupled system.

A warm ocean is not an El Nino. The event that reaches people on land is the
one where the Walker circulation actually reorganises: trades slacken, deep
convection migrates east off the Maritime Continent, sea level pressure rises
at Darwin and falls at Tahiti, and the upper-level outflow reverses. Without
that, the teleconnections that cause drought and flood never fire.

This module reads every atmospheric feed the tracker collects, converts each to
a standard score with a sign convention where POSITIVE ALWAYS MEANS EL-NINO-
LIKE, and combines them into a single Walker index. Keeping the raw indicators
alongside the composite is deliberate: when one disagrees with the rest, that
disagreement is the interesting part.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from datetime import date

from .parsers import MonthValue

# key -> (display name, sign, what a positive score means physically)
#
# sign == -1 means the raw index runs the other way from El Nino, so it is
# flipped before scoring. Only Darwin pressure is already aligned: Darwin runs
# HIGH during El Nino while every other index here runs low.
CONVENTIONS: dict[str, tuple[str, float, str]] = {
    "soi": ("Southern Oscillation Index", -1.0,
            "Tahiti-minus-Darwin pressure gradient has collapsed."),
    "eqsoi": ("Equatorial SOI", -1.0,
              "Pressure has risen over Indonesia relative to the east Pacific."),
    "darwin": ("Darwin sea level pressure", +1.0,
               "Sinking air and suppressed convection over the Maritime Continent."),
    "tahiti": ("Tahiti sea level pressure", -1.0,
               "Pressure has fallen over the central-eastern south Pacific."),
    "olr": ("OLR, date line (160E-160W)", -1.0,
            "Deep convection has moved onto the date line."),
    "olr_central": ("OLR, central Pacific", -1.0,
                    "Convection is established well east of its normal position."),
    "trade_central": ("850 hPa trades, central Pacific", -1.0,
                      "Central Pacific trades have weakened or reversed."),
    "trade_west": ("850 hPa trades, western Pacific", -1.0,
                   "Westerly anomalies over the warm pool - the wave-forcing region."),
    "trade_east": ("850 hPa trades, eastern Pacific", -1.0,
                   "Eastern Pacific trades have weakened."),
    "zwnd200": ("200 hPa zonal wind, east Pacific", -1.0,
                "The upper branch of the Walker cell has reversed."),
}

# The Walker index weights the surface pressure gradient and the convective
# response most heavily, because those are what teleconnections are made of.
WALKER_WEIGHTS: dict[str, float] = {
    "soi": 0.18,
    "eqsoi": 0.14,
    "darwin": 0.08,
    "tahiti": 0.08,
    "olr": 0.16,
    "olr_central": 0.08,
    "trade_central": 0.14,
    "trade_west": 0.06,
    "trade_east": 0.04,
    "zwnd200": 0.04,
}

# reqsoi.for is published as a standard score already; re-standardising it
# against its own history inflates the reading by roughly half a sigma.
PRESTANDARDIZED = {"eqsoi"}

# A feed more than this many months behind the newest one is reported as stale
# rather than current. cpolr in particular can sit months behind the rest.
STALE_AFTER = 2

COUPLED_THRESHOLD = 1.0  # Walker index at or above this = a coupled event
WWB_THRESHOLD = -1.0  # standardized western-Pacific 850 hPa wind
MIN_SAMPLE = 24


@dataclass(frozen=True)
class Indicator:
    key: str
    name: str
    latest: MonthValue
    raw: float
    score: float  # standard deviations, positive = El-Nino-like
    meaning: str
    standardized_by_source: bool
    history: list[MonthValue] = field(default_factory=list)
    months_behind: int = 0

    @property
    def label(self) -> str:
        return self.latest.label

    @property
    def stale(self) -> bool:
        return self.months_behind > STALE_AFTER

    @property
    def supports_el_nino(self) -> bool:
        return self.score > 0.0


@dataclass
class WindBurst:
    """A month of sustained westerly anomaly over the warm pool.

    Not a true westerly wind burst: those last days and need daily winds to
    resolve. A month that averages strongly westerly nearly always contains
    one, so this is a lower bound on burst activity, and it is labelled that
    way everywhere it appears.
    """

    when: date
    score: float

    @property
    def label(self) -> str:
        return f"{self.when:%b %Y}"


@dataclass
class MjoState:
    when: date
    enhanced_longitude: str
    enhanced_value: float
    pacific_value: float | None
    amplitude: float
    constructive: bool
    note: str


@dataclass
class AtmosphereState:
    indicators: list[Indicator]
    walker_index: float
    walker_history: list[MonthValue]
    coupled: bool
    agreement: float  # fraction of indicators pointing the same way
    dissenters: list[Indicator]
    bursts: list[WindBurst]
    burst_count_12mo: int
    mjo: MjoState | None
    qbo: Indicator | None
    notes: list[str] = field(default_factory=list)

    @property
    def latest_label(self) -> str:
        return self.walker_history[-1].label if self.walker_history else "n/a"

    def by_key(self, key: str) -> Indicator | None:
        for indicator in self.indicators:
            if indicator.key == key:
                return indicator
        return None


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _stdev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    average = _mean(values)
    return math.sqrt(sum((v - average) ** 2 for v in values) / (len(values) - 1))


def standardize(values: list[MonthValue]) -> list[MonthValue]:
    """Convert to standard scores against the file's own record.

    Done per calendar month where the sample allows it, because several of
    these quantities (OLR especially) have a large annual cycle that would
    otherwise masquerade as an anomaly.
    """
    by_month: dict[int, list[float]] = {}
    for value in values:
        by_month.setdefault(value.month, []).append(value.value)

    out: list[MonthValue] = []
    whole = [v.value for v in values]
    whole_mean, whole_sd = _mean(whole), _stdev(whole)
    for value in values:
        sample = by_month[value.month]
        if len(sample) >= MIN_SAMPLE:
            centre, spread = _mean(sample), _stdev(sample)
        else:
            centre, spread = whole_mean, whole_sd
        out.append(
            MonthValue(value.year, value.month, (value.value - centre) / (spread or 1.0))
        )
    return out


def build_indicator(
    key: str, sections: dict[str, list[MonthValue]], history_months: int = 120
) -> Indicator | None:
    """Turn one parsed CPC grid into a signed, standardized indicator."""
    convention = CONVENTIONS.get(key)
    if not convention:
        return None
    name, sign, meaning = convention

    supplied = sections.get("standardized") or []
    if key in PRESTANDARDIZED:
        series = sections.get("data") or sections.get("standardized") or []
        from_source = True
    elif supplied:
        series, from_source = supplied, True
    else:
        base = sections.get("anomaly") or sections.get("data") or sections.get("original")
        if not base:
            return None
        series, from_source = standardize(base), False
    if not series:
        return None

    raw_source = (
        sections.get("anomaly") or sections.get("data") or sections.get("original") or series
    )
    raw_index = {(v.year, v.month): v.value for v in raw_source}

    latest = series[-1]
    signed = [MonthValue(v.year, v.month, v.value * sign) for v in series[-history_months:]]
    return Indicator(
        key=key,
        name=name,
        latest=latest,
        raw=raw_index.get((latest.year, latest.month), latest.value),
        score=latest.value * sign,
        meaning=meaning,
        standardized_by_source=from_source,
        history=signed,
    )


def walker_series(indicators: list[Indicator], months: int = 120) -> list[MonthValue]:
    """Weighted composite through time, renormalised over whatever reported.

    Different feeds stop at different months, so the weights are rescaled to
    the indicators actually present for each month rather than letting a
    missing feed drag the composite toward zero.
    """
    buckets: dict[tuple[int, int], list[tuple[float, float]]] = {}
    for indicator in indicators:
        weight = WALKER_WEIGHTS.get(indicator.key, 0.0)
        if weight <= 0.0:
            continue
        for value in indicator.history:
            buckets.setdefault((value.year, value.month), []).append((weight, value.value))

    out: list[MonthValue] = []
    for (year, month), pairs in sorted(buckets.items()):
        total_weight = sum(weight for weight, _ in pairs)
        if total_weight <= 0.0:
            continue
        composite = sum(weight * value for weight, value in pairs) / total_weight
        out.append(MonthValue(year, month, composite))
    return out[-months:]


def detect_bursts(
    trade_west: list[MonthValue], within_months: int = 24
) -> list[WindBurst]:
    """Months of sustained warm-pool westerly anomaly, most recent first."""
    if not trade_west:
        return []
    standardized = standardize(trade_west)
    recent = standardized[-within_months:]
    bursts = [
        WindBurst(date(v.year, v.month, 1), v.value)
        for v in recent
        if v.value <= WWB_THRESHOLD
    ]
    bursts.sort(key=lambda burst: burst.when, reverse=True)
    return bursts


def read_mjo(series: dict[str, list[tuple[date, float]]]) -> MjoState | None:
    """Locate enhanced convection in the CPC 200 hPa velocity potential index.

    CPC's convention: a NEGATIVE standardized value is anomalous upper-level
    divergence, which means enhanced convection at that longitude. The band
    that matters for ENSO is 160E to 120W - an MJO pulse there reinforces
    westerly anomalies and can trigger a Kelvin wave.
    """
    if not series:
        return None
    latest_date = max(values[-1][0] for values in series.values() if values)
    snapshot: dict[str, float] = {}
    for longitude, values in series.items():
        for when, value in reversed(values):
            if when == latest_date:
                snapshot[longitude] = value
                break
    if not snapshot:
        return None

    enhanced_longitude = min(snapshot, key=lambda key: snapshot[key])
    enhanced_value = snapshot[enhanced_longitude]
    pacific = [snapshot.get(band) for band in ("160E", "120W")]
    pacific_values = [value for value in pacific if value is not None]
    pacific_value = min(pacific_values) if pacific_values else None
    amplitude = max(abs(value) for value in snapshot.values())

    constructive = pacific_value is not None and pacific_value <= -0.5
    if constructive:
        note = (
            f"Enhanced convection sits over the Pacific ({enhanced_longitude}), "
            "which reinforces westerly anomalies and can launch a downwelling "
            "Kelvin wave."
        )
    elif enhanced_value <= -1.0:
        note = (
            f"The active phase is over {enhanced_longitude}, away from the "
            "central Pacific, so it is not currently reinforcing the event."
        )
    else:
        note = "No strongly organised intraseasonal signal at the moment."

    return MjoState(
        when=latest_date,
        enhanced_longitude=enhanced_longitude,
        enhanced_value=enhanced_value,
        pacific_value=pacific_value,
        amplitude=amplitude,
        constructive=constructive,
        note=note,
    )


def analyse(
    grids: dict[str, dict[str, list[MonthValue]]],
    mjo_series: dict[str, list[tuple[date, float]]] | None = None,
    qbo: dict[str, list[MonthValue]] | None = None,
) -> AtmosphereState:
    """Assemble the atmospheric state from every feed that parsed."""
    indicators: list[Indicator] = []
    for key in CONVENTIONS:
        sections = grids.get(key)
        if not sections:
            continue
        indicator = build_indicator(key, sections)
        if indicator:
            indicators.append(indicator)

    if indicators:
        newest = max((i.latest.year * 12 + i.latest.month) for i in indicators)
        indicators = [
            replace(i, months_behind=newest - (i.latest.year * 12 + i.latest.month))
            for i in indicators
        ]

    history = walker_series(indicators)
    walker_index = history[-1].value if history else 0.0

    notes: list[str] = []
    current = [i for i in indicators if not i.stale]
    positive = [i for i in current if i.score > 0.25]
    negative = [i for i in current if i.score < -0.25]
    total_signed = len(positive) + len(negative)
    agreement = len(positive) / total_signed if total_signed else 0.0
    dissenters = sorted(negative, key=lambda i: i.score)

    if indicators and agreement < 0.75 and walker_index > COUPLED_THRESHOLD:
        notes.append(
            "The composite is strong but the indicators do not all agree; the "
            "dissenting feeds are listed so the disagreement is visible rather "
            "than averaged away."
        )

    # Feeds report at different times. Say so rather than implying one date.
    stale = [i for i in indicators if i.stale]
    if stale:
        listed = ", ".join(f"{i.name} ({i.label})" for i in stale)
        notes.append(
            f"Behind the other feeds and excluded from the current composite: {listed}."
        )

    bursts = []
    trade_west_sections = grids.get("trade_west") or {}
    trade_west = (
        trade_west_sections.get("anomaly")
        or trade_west_sections.get("data")
        or trade_west_sections.get("original")
        or []
    )
    if trade_west:
        bursts = detect_bursts(trade_west)
    burst_count_12mo = sum(
        1
        for burst in bursts
        if (history[-1].year * 12 + history[-1].month) - (burst.when.year * 12 + burst.when.month) < 12
    ) if history else len(bursts)

    qbo_indicator = None
    if qbo:
        standardized = qbo.get("standardized") or standardize(
            qbo.get("anomaly") or qbo.get("data") or []
        )
        if standardized:
            latest = standardized[-1]
            qbo_indicator = Indicator(
                key="qbo30",
                name="QBO, 30 hPa zonal wind",
                latest=latest,
                raw=latest.value,
                score=latest.value,
                meaning=(
                    "Westerly phase aloft, which tends to suppress MJO amplitude."
                    if latest.value > 0
                    else "Easterly phase aloft, which tends to favour a stronger MJO."
                ),
                standardized_by_source=bool(qbo.get("standardized")),
                history=standardized[-120:],
            )

    return AtmosphereState(
        indicators=sorted(indicators, key=lambda i: -i.score),
        walker_index=walker_index,
        walker_history=history,
        coupled=walker_index >= COUPLED_THRESHOLD,
        agreement=agreement,
        dissenters=dissenters,
        bursts=bursts,
        burst_count_12mo=burst_count_12mo,
        mjo=read_mjo(mjo_series or {}),
        qbo=qbo_indicator,
        notes=notes,
    )
