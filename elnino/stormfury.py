"""Project STORMFURY, recreated as a decision procedure and run on live storms.

STORMFURY was a real experiment: NOAA and the US Navy, 1962 to 1983, four
seeded hurricanes and a published hypothesis. Recreating it in software means
recreating the three things it actually consisted of, and keeping them apart,
because they failed in different ways and only one of them failed at all.

  1. THE MECHANISM.  Seed the region just outside the eyewall with silver
     iodide. Freezing the supercooled water there releases latent heat, builds
     a new convective ring outside the existing eyewall, and that ring becomes
     the eyewall at a larger radius. Air reaching a larger radius while
     conserving its absolute angular momentum arrives turning more slowly, so
     the maximum wind falls.

     This part is not wrong. ``relocated_wind`` below computes it, and for a
     realistic eyewall expansion it predicts a wind reduction of roughly the
     size STORMFURY reported. The arithmetic was never the problem.

  2. THE TRIGGER.  The mechanism needs abundant supercooled liquid water in
     the seeding region for the silver iodide to nucleate. Aircraft
     microphysics campaigns flown in the late 1970s and early 1980s found the
     opposite: hurricane convection is dominated by warm-rain coalescence,
     which strips liquid water out below the freezing level, so eyewall
     updrafts arrive at the seeding altitudes already largely glaciated. There
     was little supercooled water to freeze, and freezing it was the entire
     mechanism.

     This is where the experiment failed, and it is a fact about hurricanes,
     not about the aircraft or the funding. ``SEEDABILITY`` records it.

  3. THE MEASUREMENT.  The claimed effects were wind reductions of about 31
     per cent (Debbie, 18 August 1969) and 15 per cent (Debbie, 20 August).
     Willoughby and colleagues then documented the natural eyewall replacement
     cycle - unseeded hurricanes rebuild their eyewalls at larger radii on
     their own schedule, with the same signature and the same magnitude. A
     single seeded storm doing what unseeded storms do routinely is not
     evidence of anything.

     ``natural_swings`` reproduces that argument on this season's live b-decks
     rather than citing it: it measures how often unseeded storms right now
     change intensity by as much as STORMFURY claimed to have caused.

What this module does NOT do is tell you a storm can be weakened. It computes
what the hypothesis predicts, checks whether the hypothesis could even be
triggered, and measures whether the effect would have been detectable if it
had been. Those are three separate answers and the panel prints all three.

The legacy is real and is stated at the bottom of the report: STORMFURY put
research aircraft inside hurricanes for twenty years, and that programme is
why the eyewall replacement cycle is known at all. The observation survived;
the modification did not.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field as dc_field

from . import cyclones

# --- physical constants ------------------------------------------------------
OMEGA = 7.292115e-5        # Earth's rotation rate, rad/s
KT_TO_MS = 0.514444
NM_TO_M = 1852.0
NM_TO_KM = 1.852

# --- the hypothesis ----------------------------------------------------------
# Eyewall expansion factors to tabulate. STORMFURY aimed to build the new ring
# a little outside the old one; Beulah's reformed eyewall and the natural
# replacements since both land in this range.
EXPANSION = (1.25, 1.5, 1.75, 2.0)

# --- STORMFURY's own operating criteria --------------------------------------
# The programme could not seed whatever it liked. These are its published
# constraints, and the point of keeping them here is that they are checkable
# against a live storm, which is what turns a slogan into a procedure.
#
# The landfall rule is the one that mattered: a storm had to have less than a
# 10 per cent chance of coming within 50 miles of a populated land area within
# 24 hours of seeding. It was adopted because nobody could tell a court the
# difference between a seeded hurricane and an unseeded one that did the same
# thing, which is the same epistemics that eventually closed the programme.
LANDFALL_MILES = 50.0
LANDFALL_KM = LANDFALL_MILES * 1.609344
LANDFALL_HOURS = 24
LANDFALL_PROBABILITY = 0.10

# Minimum intensity for a coherent eyewall to move. STORMFURY flew hurricanes;
# Debbie was a major hurricane on both seeding days.
MIN_WIND_KT = 64

# Where the aircraft flew from: Roosevelt Roads for the Atlantic seeding
# years, and Lakeland, where NOAA's hurricane aircraft fly from now. There is
# no Pacific base. A move to Guam to seed western-Pacific typhoons was planned
# in the mid-1970s, looking for storms the programme was allowed to touch, and
# abandoned over objections from governments in the region; no STORMFURY
# aircraft ever staged from there.
BASES = (
    ("Roosevelt Roads, Puerto Rico", -65.64, 18.25),   # the Atlantic years
    ("Lakeland, Florida", -82.02, 27.99),              # where NOAA flies from now
)

# Operational radius of a WP-3D staging from one of those bases with useful
# time on station. This is an assumption, not a published figure, and it is
# here as a named constant so it can be argued with rather than buried.
OPERATIONAL_RADIUS_KM = 2040.0    # about 1,100 nautical miles

# --- what killed it ----------------------------------------------------------
# Not computed, because it is an observation about hurricanes rather than about
# any particular storm. Stated here so the panel can quote it with its source
# instead of asserting it.
SEEDABILITY = {
    "requirement": (
        "Abundant supercooled liquid water in the seeding region, between "
        "roughly -4 and -20 °C, for silver iodide to nucleate."
    ),
    "observation": (
        "Hurricane eyewall updrafts are largely glaciated by the time they "
        "reach those temperatures. Warm-rain coalescence removes liquid water "
        "below the freezing level efficiently enough that little survives to "
        "be supercooled, leaving the seeding agent with nearly nothing to act "
        "on."
    ),
    "verdict": "The trigger is absent. The mechanism cannot start.",
    "source": "Willoughby et al., Bull. Am. Meteorol. Soc., 1985",
}

# Environmental structure of the seedable layer. A tropical lapse rate and a
# tropical surface temperature put the -4 and -20 °C levels where they sit over
# any warm ocean; this varies by a few hundred metres across the range of SSTs
# a hurricane exists over, which is not enough to change the argument, so it is
# computed from constants rather than sampled per storm.
LAPSE_K_PER_KM = 6.5
TROPICAL_SST_C = 28.5
SEED_WARM_C = -4.0
SEED_COLD_C = -20.0

# --- the historical record ---------------------------------------------------
@dataclass(frozen=True)
class Seeded:
    """One storm STORMFURY actually seeded, and what was claimed."""

    name: str
    year: int
    dates: str
    claimed: str
    outcome: str


HISTORY: tuple[Seeded, ...] = (
    Seeded(
        "Esther", 1961, "September 1961",
        "about 10 per cent",
        "Flown before STORMFURY formally existed, as the proof of concept "
        "that got the programme funded.",
    ),
    Seeded(
        "Beulah", 1963, "August 1963",
        "eyewall dissipated and reformed further out",
        "The first run missed the target area entirely. The second produced "
        "the reformation the hypothesis predicted, which is also what an "
        "unseeded eyewall replacement looks like.",
    ),
    Seeded(
        "Debbie", 1969, "18 and 20 August 1969",
        "31 per cent, then 15 per cent",
        "The showcase: five seedings on each of two days. These are the "
        "numbers the programme is remembered for, and the ones the natural "
        "replacement cycle later explained without any silver iodide.",
    ),
    Seeded(
        "Ginger", 1971, "September 1971",
        "no measurable effect",
        "A large, diffuse storm with no coherent eyewall to move. It was "
        "seeded because it was what was available, which is itself a "
        "statement about how rarely the criteria above are met.",
    ),
)

PROGRAMME = {
    "ran": "1962 to 1983",
    "agencies": "US Weather Bureau / NOAA with the US Navy",
    "seeded": 4,
    "ended": (
        "Formally ended in 1983. By then the natural eyewall replacement "
        "cycle had removed the evidence, the microphysics had removed the "
        "mechanism, and a move to the west Pacific in search of storms far "
        "from land had run into the problem that other nations' storms are "
        "not available to be experimented on."
    ),
    "legacy": (
        "Twenty years of research aircraft inside hurricanes. The eyewall "
        "replacement cycle, the modern understanding of hurricane structure, "
        "and the reconnaissance programme that still flies are all products "
        "of STORMFURY's observing arm. The measurement outlived the "
        "experiment it was built to serve."
    ),
}


# --- 1. the mechanism, computed ---------------------------------------------
def coriolis(lat: float) -> float:
    """Coriolis parameter at a latitude, in reciprocal seconds."""
    return 2.0 * OMEGA * math.sin(math.radians(lat))


def absolute_momentum(radius_nm: float, wind_kt: float, lat: float) -> float:
    """Absolute angular momentum per unit mass, m^2/s.

    ``M = r*v + |f|*r^2/2``. The second term is the planet's own rotation, and
    it is small for a tight tropical eyewall - a few per cent - but it grows
    as the square of the radius, so it is exactly the term that matters when
    the question is what happens if the eyewall moves outward.

    The Coriolis parameter is taken as a magnitude because the wind arrives
    here as a speed. A southern-hemisphere cyclone turns the other way, so
    both ``f`` and ``v`` are negative in the signed convention and the product
    is unchanged; mixing a positive speed with a negative ``f`` would instead
    have the planet subsidising the vortex below the equator and taxing it
    above, which is not a hemisphere difference that exists.
    """
    r = radius_nm * NM_TO_M
    v = wind_kt * KT_TO_MS
    return r * v + 0.5 * abs(coriolis(lat)) * r * r


def relocated_wind(wind_kt: float, from_nm: float, to_nm: float,
                   lat: float) -> float | None:
    """Tangential wind after the eyewall moves, conserving absolute momentum.

    This is STORMFURY's prediction, stated as arithmetic. Air that finds
    itself at a larger radius with the same absolute angular momentum must
    turn more slowly, and the planet takes a larger share of the total the
    further out it goes, which is why the wind falls faster than 1/r.

    A large enough relocation drives the answer negative, which means the
    momentum available cannot sustain any cyclonic wind at that radius. That
    is returned as None rather than as a negative wind, because it is the
    calculation running out of physical meaning rather than a forecast.
    """
    if from_nm <= 0 or to_nm <= 0:
        return None
    momentum = absolute_momentum(from_nm, wind_kt, lat)
    r2 = to_nm * NM_TO_M
    v2 = (momentum - 0.5 * abs(coriolis(lat)) * r2 * r2) / r2
    if v2 <= 0:
        return None
    return v2 / KT_TO_MS


def momentum_table(wind_kt: float, rmw_nm: float, lat: float,
                   factors: tuple[float, ...] = EXPANSION) -> list[dict]:
    """The hypothesis across a range of eyewall expansions."""
    out: list[dict] = []
    for factor in factors:
        to_nm = rmw_nm * factor
        after = relocated_wind(wind_kt, rmw_nm, to_nm, lat)
        out.append({
            "factor": factor,
            "from_nm": round(rmw_nm, 1),
            "to_nm": round(to_nm, 1),
            "before_kt": round(wind_kt),
            "after_kt": round(after) if after is not None else None,
            "drop_pct": (round(100.0 * (wind_kt - after) / wind_kt, 1)
                         if after is not None else None),
            "category_before": cyclones.category(int(round(wind_kt))),
            "category_after": (cyclones.category(int(round(after)))
                               if after is not None else None),
        })
    return out


def seedable_layer() -> dict:
    """Height and depth of the layer the hypothesis needed, in kilometres."""
    warm = (TROPICAL_SST_C - SEED_WARM_C) / LAPSE_K_PER_KM
    cold = (TROPICAL_SST_C - SEED_COLD_C) / LAPSE_K_PER_KM
    freezing = TROPICAL_SST_C / LAPSE_K_PER_KM
    return {
        "freezing_km": round(freezing, 1),
        "base_km": round(warm, 1),
        "top_km": round(cold, 1),
        "depth_km": round(cold - warm, 1),
    }


# --- 2. the criteria, evaluated ---------------------------------------------
@dataclass
class Criterion:
    """One of STORMFURY's operating rules, checked against a live storm."""

    name: str
    passed: bool | None      # None when the data to judge it is absent
    detail: str


@dataclass
class Assessment:
    """Whether STORMFURY would have been allowed to fly this storm."""

    storm_key: str
    title: str
    basin: str
    wind_kt: int | None = None
    rmw_nm: int | None = None
    lat: float = 0.0
    lon: float = 0.0
    criteria: list[Criterion] = dc_field(default_factory=list)
    momentum: list[dict] = dc_field(default_factory=list)
    note: str = ""

    @property
    def eligible(self) -> bool:
        return all(c.passed for c in self.criteria if c.passed is not None) \
            and not any(c.passed is None for c in self.criteria)

    @property
    def blocked_by(self) -> list[str]:
        return [c.name for c in self.criteria if c.passed is False]

    @property
    def unknown(self) -> list[str]:
        return [c.name for c in self.criteria if c.passed is None]


def _range_criterion(lon: float, lat: float) -> Criterion:
    scored = [(cyclones.great_circle(lon, lat, blon, blat), name)
              for name, blon, blat in BASES]
    gap, base = min(scored)
    ok = gap <= OPERATIONAL_RADIUS_KM
    return Criterion(
        "Within aircraft range", ok,
        f"{gap:,.0f} km from {base}"
        + ("" if ok else f", beyond the {OPERATIONAL_RADIUS_KM:,.0f} km "
                         "operational radius assumed here"),
    )


def _eyewall_criterion(wind: int | None, rmw: int | None) -> Criterion:
    if wind is None:
        return Criterion("Coherent eyewall", None, "no analysed intensity")
    if wind < MIN_WIND_KT:
        return Criterion(
            "Coherent eyewall", False,
            f"{wind} kt is below the {MIN_WIND_KT} kt hurricane threshold; "
            "there is no closed eyewall to relocate",
        )
    if rmw is None:
        return Criterion(
            "Coherent eyewall", None,
            f"{wind} kt, but the deck reports no radius of maximum wind, so "
            "the eyewall's position is unknown",
        )
    if rmw > MAX_EYEWALL_NM:
        # Same judgement the confound measurement makes, for the same reason:
        # past this radius the reported maximum is where a broad wind field
        # happens to peak, and there is no ring of convection to move.
        return Criterion(
            "Coherent eyewall", False,
            f"the wind maximum sits {rmw} nm out, past the {MAX_EYEWALL_NM} "
            "nm limit for a structure that is an eyewall rather than a broad "
            "wind field",
        )
    return Criterion(
        "Coherent eyewall", True,
        f"{wind} kt with the eyewall at {rmw} nm",
    )


def _landfall_criterion(storm) -> Criterion:
    """The 10 per cent / 50 mile / 24 hour rule, read off the forecast."""
    horizon = [f for f in storm.forecast if 0 < f.tau <= LANDFALL_HOURS]
    if not horizon:
        return Criterion(
            "Clear of land for 24 h", None,
            "no official forecast on file to judge the approach",
        )
    official_min = min(cyclones.distance_to_coast(f.lon, f.lat)
                       for f in horizon)

    # The probability half of the rule, from whatever scatter the deck carried.
    tracks = storm.scatter
    breaches = 0
    counted = 0
    for fixes in tracks.values():
        window = [f for f in fixes if 0 < f.tau <= LANDFALL_HOURS]
        if not window:
            continue
        counted += 1
        if min(cyclones.distance_to_coast(f.lon, f.lat)
               for f in window) <= LANDFALL_KM:
            breaches += 1
    share = (breaches / counted) if counted else None

    if share is None:
        ok = official_min > LANDFALL_KM
        return Criterion(
            "Clear of land for 24 h", ok,
            f"official track stays {official_min:,.0f} km off the coast; no "
            "ensemble on file, so this is the deterministic track alone",
        )
    ok = share <= LANDFALL_PROBABILITY and official_min > LANDFALL_KM
    return Criterion(
        "Clear of land for 24 h", ok,
        f"{share * 100:.0f}% of {counted} tracks come within "
        f"{LANDFALL_KM:,.0f} km of land inside {LANDFALL_HOURS} h "
        f"(rule: at most {LANDFALL_PROBABILITY * 100:.0f}%); "
        f"official track's closest approach {official_min:,.0f} km",
    )


def _seedability_criterion() -> Criterion:
    """The one criterion no storm has ever passed."""
    return Criterion(
        "Supercooled water to seed", False,
        SEEDABILITY["observation"] + " " + SEEDABILITY["verdict"],
    )


def assess(storm) -> Assessment | None:
    """Run STORMFURY's decision procedure against one live storm."""
    fix = storm.latest
    if fix is None:
        return None
    out = Assessment(
        storm_key=storm.key, title=storm.title, basin=storm.basin_name,
        wind_kt=fix.wind, rmw_nm=fix.rmw, lat=fix.lat, lon=fix.lon,
    )
    out.criteria = [
        _range_criterion(fix.lon, fix.lat),
        _eyewall_criterion(fix.wind, fix.rmw),
        _landfall_criterion(storm),
        _seedability_criterion(),
    ]
    if fix.wind and fix.rmw:
        out.momentum = momentum_table(float(fix.wind), float(fix.rmw), fix.lat)
        out.note = (
            "The momentum column is what the hypothesis predicts if the "
            "eyewall could be moved. Nothing in this system can move it."
        )
    return out


# --- 3. the confound, measured on live data ---------------------------------
# STORMFURY's headline claim was a 31 per cent wind reduction within a day of
# seeding. The question that closed the programme is how often an untouched
# hurricane does that anyway.
DEBBIE_CLAIM_PCT = 31.0
SWING_WINDOW_H = 24

# Beyond this a reported radius of maximum wind is not an eyewall. A sprawling
# tropical storm with its strongest winds 200 nm from the centre has a wind
# field, not an eyewall, and running an eyewall relocation calculation on it
# produces a confident number about something that does not exist.
MAX_EYEWALL_NM = 60

# A replacement builds the new ring near the old one. A jump larger than this
# between two analyses is a re-analysis of a disorganised storm rather than a
# structural event, and including it would pad the count with noise.
MAX_RELOCATION = 3.0


def _synoptic_series(storm) -> list:
    return [f for f in storm.track
            if f.tau == 0 and f.wind and f.synoptic
            and f.stage in cyclones.WARM_CORE]


def natural_swings(storms, window: int = SWING_WINDOW_H) -> dict:
    """Every unseeded hurricane intensity change this season, as a distribution.

    One entry per storm per ``window``-hour interval: the signed fractional
    change in maximum wind. No storm in this sample has been seeded with
    anything, because no storm anywhere has been seeded since 1971.

    The interval has to *start* at hurricane strength, because that is the
    population Debbie belonged to and the comparison is only fair against it.
    Counting a tropical depression doubling from 15 to 30 kt as a 100 per cent
    intensity swing would inflate the natural variability with events that
    have nothing to do with an eyewall.
    """
    changes: list[dict] = []
    for storm in storms:
        series = _synoptic_series(storm)
        for index, later in enumerate(series):
            for earlier in series[:index]:
                if cyclones._hours_between(earlier.stamp, later.stamp) != window:
                    continue
                if not earlier.wind or earlier.wind < MIN_WIND_KT:
                    continue
                pct = 100.0 * (later.wind - earlier.wind) / earlier.wind
                changes.append({
                    "storm": storm.title,
                    "key": storm.key,
                    "from_kt": earlier.wind,
                    "to_kt": later.wind,
                    "stamp": later.stamp,
                    "pct": round(pct, 1),
                })
    drops = [c for c in changes if c["pct"] <= -DEBBIE_CLAIM_PCT]
    magnitude = [c for c in changes if abs(c["pct"]) >= DEBBIE_CLAIM_PCT]
    total = len(changes)
    return {
        "window": window,
        "changes": changes,
        "count": total,
        "storms": len({c["key"] for c in changes}),
        "weakened_as_much": len(drops),
        "moved_as_much": len(magnitude),
        "share_weakened": (len(drops) / total) if total else None,
        "share_moved": (len(magnitude) / total) if total else None,
        "biggest_drop": min((c["pct"] for c in changes), default=None),
        "biggest_rise": max((c["pct"] for c in changes), default=None),
        "claim": DEBBIE_CLAIM_PCT,
    }


def eyewall_moves(storms) -> list[dict]:
    """Natural eyewall relocations in the decks, with no seeding involved.

    This is the mechanism STORMFURY was trying to induce, observed happening
    on its own. A hurricane whose reported radius of maximum wind jumps
    outward between two analyses has done, unaided, the thing five aircraft
    and a load of silver iodide canisters were sent to do.

    Restricted to storms that have an eyewall to move: hurricane strength, a
    radius tight enough to be an eyewall rather than a wind field, and a jump
    small enough to be a structural change rather than a re-analysis. Without
    those gates this fills up with disorganised tropical storms whose
    "radius of maximum wind" wandered by two hundred miles, and the momentum
    column then reports a confident number about an eyewall that never
    existed.
    """
    out: list[dict] = []
    for storm in storms:
        series = [f for f in storm.track
                  if f.tau == 0 and f.rmw and f.wind
                  and f.wind >= MIN_WIND_KT and f.rmw <= MAX_EYEWALL_NM]
        for earlier, later in zip(series, series[1:]):
            if later.rmw <= earlier.rmw:
                continue
            if later.rmw > earlier.rmw * MAX_RELOCATION:
                continue
            hours = cyclones._hours_between(earlier.stamp, later.stamp)
            if hours <= 0 or hours > 24:
                continue
            predicted = relocated_wind(float(earlier.wind), float(earlier.rmw),
                                       float(later.rmw), earlier.lat)
            out.append({
                "storm": storm.title,
                "key": storm.key,
                "stamp": later.stamp,
                "hours": hours,
                "from_nm": earlier.rmw,
                "to_nm": later.rmw,
                "wind_before": earlier.wind,
                "wind_after": later.wind,
                "predicted_kt": round(predicted) if predicted else None,
                "observed_pct": round(
                    100.0 * (later.wind - earlier.wind) / earlier.wind, 1),
            })
    out.sort(key=lambda m: -(m["to_nm"] / m["from_nm"]))
    return out


def relocation_skill(moves: list[dict]) -> dict:
    """How well the angular-momentum prediction matched the real hurricanes.

    This is the finding that does not come out of the literature: it comes out
    of this season's decks. Take every natural eyewall expansion in a hurricane
    above, ask what conserving absolute angular momentum predicts the wind
    should become, and compare that with the wind the storm actually had six
    hours later.

    The prediction is far too strong, consistently. A hurricane is not a
    spinning-down flywheel: it is continuously fed high-angular-momentum air
    through the boundary layer inflow, and the surface torque and the
    secondary circulation restore the vortex while the eyewall is moving. A
    closed-system momentum argument ignores all of that, so it is an upper
    bound on the weakening rather than a forecast of it.

    Which matters here for one reason. STORMFURY's predicted effect came from
    exactly this calculation. If the calculation overstates what a real
    eyewall relocation does to a real hurricane - and on this sample it
    overstates it several times over - then even a mechanism that worked
    perfectly would buy far less than the programme claimed.
    """
    scored = [m for m in moves if m["predicted_kt"] and m["wind_before"]]
    if not scored:
        return {"count": 0}
    predicted_drop = [100.0 * (m["wind_before"] - m["predicted_kt"])
                      / m["wind_before"] for m in scored]
    observed_drop = [-m["observed_pct"] for m in scored]
    mean_pred = sum(predicted_drop) / len(scored)
    mean_obs = sum(observed_drop) / len(scored)
    held = len([d for d in observed_drop if d <= 0])
    return {
        "count": len(scored),
        "mean_predicted_drop": round(mean_pred, 1),
        "mean_observed_drop": round(mean_obs, 1),
        "overstatement": (round(mean_pred / mean_obs, 1)
                          if mean_obs > 0.5 else None),
        "held_or_strengthened": held,
        "storms": len({m["key"] for m in scored}),
    }


# --- assembly ----------------------------------------------------------------
@dataclass
class FuryState:
    """The whole recreation: hypothesis, criteria, confound."""

    assessments: list[Assessment] = dc_field(default_factory=list)
    swings: dict = dc_field(default_factory=dict)
    moves: list[dict] = dc_field(default_factory=list)
    skill: dict = dc_field(default_factory=dict)
    layer: dict = dc_field(default_factory=dict)
    as_of: str = ""

    @property
    def available(self) -> bool:
        return bool(self.assessments) or bool(self.swings.get("count"))

    @property
    def eligible(self) -> list[Assessment]:
        return [a for a in self.assessments if a.eligible]

    @property
    def verdict(self) -> str:
        """The one-line answer, computed rather than asserted."""
        if not self.assessments:
            return ("No live storm to assess. The seedability criterion fails "
                    "for every storm regardless, so the count would be zero.")
        blocked = len([a for a in self.assessments if not a.eligible])
        return (
            f"{blocked} of {len(self.assessments)} live storms fail "
            f"STORMFURY's own criteria. Every one of them fails on "
            f"supercooled water, which is the criterion no hurricane has ever "
            f"passed and the reason the programme ended."
        )

    @property
    def reasons(self) -> list[str]:
        """The three independent failures, each with this run's number on it.

        Independent is the operative word. Fixing any one of them leaves the
        other two standing, which is why this is not an engineering problem
        waiting on a better aircraft.
        """
        out: list[str] = []
        out.append(
            "TRIGGER: the seeding agent needs supercooled liquid water and "
            "hurricane eyewalls are already glaciated at seeding altitude. "
            "Nothing to freeze, so the mechanism never starts. "
            + SEEDABILITY["source"] + "."
        )
        skill = self.skill
        if skill.get("count"):
            line = (
                f"MAGNITUDE: across {skill['count']} natural eyewall "
                f"expansions in {skill['storms']} hurricanes this season, "
                f"conserving angular momentum predicted a mean "
                f"{skill['mean_predicted_drop']:.1f}% wind drop and the "
                f"storms actually gave up {skill['mean_observed_drop']:.1f}%"
            )
            if skill.get("overstatement"):
                line += f", overstating it {skill['overstatement']:.1f}-fold"
            line += (". A hurricane is fed high-momentum air continuously, so "
                     "a closed-system argument is an upper bound, not a "
                     "forecast. STORMFURY's predicted effect came from that "
                     "same calculation.")
            out.append(line)
        swings = self.swings
        if swings.get("count"):
            out.append(
                f"DETECTION: {swings['weakened_as_much']} of "
                f"{swings['count']} unseeded hurricane intervals this season "
                f"weakened by at least the {swings['claim']:.0f}% STORMFURY "
                f"claimed for Debbie, and {swings['moved_as_much']} moved "
                f"that far in one direction or the other. An effect that size "
                f"is indistinguishable from what hurricanes do untouched, "
                f"which is what closed the programme."
            )
        return out


def evaluate(storms) -> FuryState:
    """Build the recreation from whatever the cyclone tier managed to fetch.

    Takes the ``CycloneState`` rather than the whole run, because everything
    here is arithmetic over ATCF decks and nothing else in the system is an
    input to it. That keeps it testable from a handful of fixture fixes.
    """
    out = FuryState(layer=seedable_layer())
    if storms is None or not storms.available:
        return out
    out.as_of = storms.as_of
    out.assessments = [a for a in (assess(s) for s in storms.active) if a]
    out.swings = natural_swings(storms.storms)
    out.moves = eyewall_moves(storms.storms)
    out.skill = relocation_skill(out.moves)
    return out
