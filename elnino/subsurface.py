"""Subsurface heat: warm water volume and the recharge oscillator.

SST tells you what ENSO *is* right now. Warm water volume tells you what it is
*about to be*. WWV -- the volume of water above the 20 degC isotherm between
5N and 5S -- is the memory of the coupled system: the equatorial Pacific
recharges heat during La Nina, discharges it during El Nino, and the recharge
leads the SST response by roughly two to three seasons.

Jin's recharge oscillator (1997) formalises this as a two-variable system in
SST anomaly T and thermocline depth anomaly h. Plotted against each other, the
ENSO cycle traces a clockwise loop:

        h > 0, T ~ 0   recharged, primed to warm
        h > 0, T > 0   El Nino developing
        h ~ 0, T > 0   El Nino mature, discharge under way
        h < 0, T > 0   El Nino decaying, heat exported poleward
        h < 0, T ~ 0   discharged, primed to cool
        h < 0, T < 0   La Nina
        h ~ 0, T < 0   La Nina mature, recharge under way

Where a given month sits on that loop is a genuine forecast constraint, and it
is the single most useful thing the tracker knows that a pure SST monitor does
not.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date

from .parsers import MonthValue, WwvObservation

# The phase-space octants, walking clockwise. Each entry is the CENTRE angle
# of the octant in degrees, its name, and what it implies; an observation is
# assigned to the octant whose centre is within 22.5 degrees.
PHASES: tuple[tuple[float, str, str], ...] = (
    (180.0, "La Nina mature, recharging",
     "Cold event at peak while heat rebuilds along the equator."),
    (135.0, "Recharged, cool",
     "Heat has returned but the surface has not yet responded."),
    (90.0, "Recharged, primed to warm",
     "Maximum stored heat. Historically the launch point of a warm event."),
    (45.0, "El Nino developing",
     "Stored heat is converting into surface warmth. The growth phase."),
    (0.0, "El Nino mature, discharging",
     "Surface anomaly near peak; the equator is now exporting heat."),
    (-45.0, "El Nino decaying",
     "Heat content already spent. The surface anomaly is living on borrowed time."),
    (-90.0, "Discharged, primed to cool",
     "Minimum stored heat. Historically the launch point of a cold event."),
    (-135.0, "La Nina developing",
     "Deficit is converting into surface cooling."),
)

MIN_SAMPLE = 24  # months needed before a statistic is worth quoting


@dataclass(frozen=True)
class PhasePoint:
    when: date
    sst: float  # Nino-3.4 anomaly, degC
    heat: float  # WWV anomaly, 10^14 m^3


@dataclass
class SubsurfaceState:
    """Everything the tracker knows about stored heat, in one object."""

    latest: WwvObservation
    west: WwvObservation | None
    east_anomaly: float | None
    rank_alltime: int
    rank_month: int
    total_alltime: int
    total_month: int
    percentile: float
    tendency: float  # 10^14 m^3 per month, over the last 3 months
    tendency_label: str
    phase_angle: float  # degrees
    phase_name: str
    phase_note: str
    phase_confident: bool
    lead_months: int
    lead_correlation: float
    trajectory: list[PhasePoint] = field(default_factory=list)
    implied_nino34: float | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def anomaly(self) -> float:
        return self.latest.anomaly

    @property
    def discharging(self) -> bool:
        return self.tendency < -0.02


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _stdev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    average = _mean(values)
    return math.sqrt(sum((v - average) ** 2 for v in values) / (len(values) - 1))


def _correlation(left: list[float], right: list[float]) -> float:
    if len(left) < MIN_SAMPLE or len(left) != len(right):
        return 0.0
    left_mean, right_mean = _mean(left), _mean(right)
    numerator = sum((a - left_mean) * (b - right_mean) for a, b in zip(left, right))
    denominator = math.sqrt(
        sum((a - left_mean) ** 2 for a in left) * sum((b - right_mean) ** 2 for b in right)
    )
    return numerator / denominator if denominator else 0.0


def _index(values: list[MonthValue]) -> dict[tuple[int, int], float]:
    return {(v.year, v.month): v.value for v in values}


def _shift(key: tuple[int, int], months: int) -> tuple[int, int]:
    total = key[0] * 12 + (key[1] - 1) + months
    return total // 12, total % 12 + 1


def lead_lag(
    heat: list[MonthValue], sst: list[MonthValue], max_lead: int = 12
) -> tuple[int, float, dict[int, float]]:
    """Find the lead time at which WWV best predicts Nino-3.4.

    Returns (best lead in months, its correlation, the whole profile). The
    profile is worth keeping: a lead that has collapsed relative to its
    historical value is itself a warning that the system is behaving oddly.
    """
    heat_index, sst_index = _index(heat), _index(sst)
    profile: dict[int, float] = {}
    for lead in range(0, max_lead + 1):
        pairs = [
            (value, sst_index[_shift(key, lead)])
            for key, value in heat_index.items()
            if _shift(key, lead) in sst_index
        ]
        if len(pairs) < MIN_SAMPLE:
            continue
        profile[lead] = _correlation([p[0] for p in pairs], [p[1] for p in pairs])
    if not profile:
        return 0, 0.0, {}
    best = max(profile, key=lambda lead: profile[lead])
    return best, profile[best], profile


def classify_phase(sst_sigma: float, heat_sigma: float) -> tuple[float, str, str, bool]:
    """Locate a month on the recharge-oscillator loop.

    Inputs are already normalised to standard deviations so the phase space is
    circular; otherwise the angle just reports which variable has the larger
    physical units.
    """
    angle = math.degrees(math.atan2(heat_sigma, sst_sigma))
    radius = math.hypot(sst_sigma, heat_sigma)
    for centre, name, note in PHASES:
        if angle >= centre - 22.5:
            return angle, name, note, radius >= 0.75
    return angle, PHASES[0][1], PHASES[0][2], radius >= 0.75


def analyse(
    wwv: list[WwvObservation],
    wwv_west: list[WwvObservation],
    nino34: list[MonthValue],
    trajectory_months: int = 48,
) -> SubsurfaceState | None:
    """Build the full subsurface picture. Returns None without WWV data."""
    if not wwv:
        return None

    latest = wwv[-1]
    anomalies = [obs.anomaly for obs in wwv]
    notes: list[str] = []

    # Ranking, both against the whole record and against the same calendar
    # month, because WWV has its own annual cycle.
    ordered = sorted(anomalies, reverse=True)
    rank_alltime = ordered.index(latest.anomaly) + 1
    same_month = sorted(
        (obs.anomaly for obs in wwv if obs.month == latest.month), reverse=True
    )
    rank_month = same_month.index(latest.anomaly) + 1
    percentile = 100.0 * (1.0 - (rank_alltime - 1) / max(len(anomalies) - 1, 1))

    # Tendency over the last three months: is heat still arriving or leaving?
    tendency = 0.0
    if len(wwv) >= 4:
        tendency = (latest.anomaly - wwv[-4].anomaly) / 3.0
    if tendency > 0.05:
        tendency_label = "still recharging"
    elif tendency < -0.05:
        tendency_label = "discharging"
    else:
        tendency_label = "flat"

    west = wwv_west[-1] if wwv_west else None
    east_anomaly = None
    if west and west.year == latest.year and west.month == latest.month:
        east_anomaly = latest.anomaly - west.anomaly
        if east_anomaly > 0.5 and west.anomaly < 0.5:
            notes.append(
                "Heat content is concentrated in the eastern half of the basin "
                "with the west drawn down: the thermocline tilt of a mature "
                "east-Pacific event. The tilt moves with the surface warming "
                "rather than ahead of it, so it marks the event's strength now; "
                "how much fuel is left is the basin-wide total and its tendency."
            )

    # Normalise both variables before taking a phase angle.
    sst_index = _index(nino34)
    sst_values = [v.value for v in nino34]
    heat_sigma_scale = _stdev(anomalies) or 1.0
    sst_sigma_scale = _stdev(sst_values) or 1.0

    latest_sst = sst_index.get((latest.year, latest.month))
    if latest_sst is None and nino34:
        latest_sst = nino34[-1].value
        notes.append(
            f"WWV runs to {latest.label} but Nino-3.4 to {nino34[-1].label}; "
            "the phase angle pairs the nearest available months."
        )
    latest_sst = latest_sst if latest_sst is not None else 0.0

    angle, phase_name, phase_note, confident = classify_phase(
        latest_sst / sst_sigma_scale, latest.anomaly / heat_sigma_scale
    )
    if not confident:
        notes.append(
            "Both variables are close to zero, so the phase angle is poorly "
            "constrained - treat the named phase as provisional."
        )

    lead_months, lead_correlation, _ = lead_lag(
        [obs.month_value for obs in wwv], nino34
    )

    # What the historical WWV-to-SST regression implies for Nino-3.4 at that
    # lead. Deliberately the simplest possible statement of the relationship.
    implied = None
    if lead_correlation > 0.3:
        implied = (
            lead_correlation * (latest.anomaly / heat_sigma_scale) * sst_sigma_scale
        )

    trajectory: list[PhasePoint] = []
    for obs in wwv[-trajectory_months:]:
        value = sst_index.get((obs.year, obs.month))
        if value is None:
            continue
        trajectory.append(PhasePoint(date(obs.year, obs.month, 1), value, obs.anomaly))

    return SubsurfaceState(
        latest=latest,
        west=west,
        east_anomaly=east_anomaly,
        rank_alltime=rank_alltime,
        rank_month=rank_month,
        total_alltime=len(anomalies),
        total_month=len(same_month),
        percentile=percentile,
        tendency=tendency,
        tendency_label=tendency_label,
        phase_angle=angle,
        phase_name=phase_name,
        phase_note=phase_note,
        phase_confident=confident,
        lead_months=lead_months,
        lead_correlation=lead_correlation,
        trajectory=trajectory,
        implied_nino34=implied,
        notes=notes,
    )
