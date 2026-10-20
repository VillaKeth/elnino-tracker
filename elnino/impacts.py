"""Teleconnections and the human exposure behind them.

An ENSO index is a number in the Pacific. What makes it matter is that the
atmosphere carries the signal to places thousands of kilometres away, on a
schedule that is known months in advance. This module holds the catalogue of
those relationships and reports which of them the current state of the system
puts in play, when, and with what confidence.

READ THIS BEFORE USING THE OUTPUT
---------------------------------
This is a **hazard outlook built from historical composites**, not a forecast.
It says "events of this size and shape have historically been followed by this
pattern in this season" - which is genuinely useful for anticipation and
useless as a prediction of any specific flood, harvest or outbreak. Three
limits are worth stating plainly:

  * ENSO shifts probabilities; it does not determine outcomes. A high-confidence
    teleconnection still fails in individual years.
  * Other drivers can reinforce or cancel it - the Indian Ocean Dipole, the
    Atlantic, the MJO, and in some regions a long-term trend that is now larger
    than the ENSO signal itself.
  * Impact depends far more on vulnerability than on rainfall percentiles.

For operational decisions use the national meteorological service, and for food
security the FEWS NET and IPC products, which combine this class of information
with ground truth. Sources for the relationships themselves are the CPC/IRI
seasonal composites and WMO El Nino/La Nina Updates.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from .classify import CP_FLAVOUR, EP_FLAVOUR, Episode
from .forecast import Projection, season_months

# Confidence reflects how consistently the relationship appears across past
# events, not how severe the outcome is.
HIGH = "high"
MODERATE = "moderate"
EMERGING = "weaker / contested"

# Flavour gating. EP (canonical, east-Pacific) and CP (Modoki, central-Pacific)
# events teleconnect differently; a few relationships flip almost entirely.
ANY, EP, CP = "any", "east-pacific", "central-pacific"
# How much stronger an event of the wrong flavour has to be for a gated link.
FLAVOUR_PENALTY = 0.75
# Margins past a link's threshold at which it reads "probable" and "likely".
# "Probable" is the bar for the outlook itself; below it a link is on watch.
PROBABLE_MARGIN = 0.4
LIKELY_MARGIN = 1.0
# The month names a link's window is written in, "Jun-Sep".
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
# An event grows through the boreal summer and peaks in the winter: a window
# opening from May falls in the year it grows, one opening earlier in the next.
GROWING_FROM = 5
Month = tuple[int, int]  # (year, month)


@dataclass(frozen=True)
class Teleconnection:
    region: str
    area: str
    window: str  # the season in which the signal appears
    effect: str
    polarity: str  # dry | wet | hot | cold | storm | marine | health
    confidence: str
    min_intensity: float  # index value at which this typically becomes evident
    flavour: str
    detail: str
    exposure: str


@dataclass
class ActiveImpact:
    link: Teleconnection
    likelihood: str
    margin: float  # projected peak minus the link's threshold, flavour included
    timing: str  # the window, dated for this event and set against today
    flavour_note: str = ""
    # The peak at which the link would reach "probable" and join the outlook,
    # flavour penalty included. None for a contested link, which is never
    # rated above "possible" however strong the event.
    needs: float | None = None
    when: str = ""  # "ahead", "under way" or "past"; "" when undated
    dated: str = ""  # the window dated for this event, Dec 2026–Mar 2027; "" when undated

    @property
    def severity(self) -> int:
        """Crude ordering for display: confidence first, then margin."""
        rank = {HIGH: 3, MODERATE: 2, EMERGING: 1}[self.link.confidence]
        return rank * 10 + min(int(self.margin * 4), 9)


@dataclass
class ImpactAssessment:
    active: list[ActiveImpact]
    watch: list[ActiveImpact]
    peak_index: float
    flavour: str
    by_area: dict[str, list[ActiveImpact]] = field(default_factory=dict)  # active only
    notes: list[str] = field(default_factory=list)
    index_name: str = "RONI"


CATALOGUE: tuple[Teleconnection, ...] = (
    # -- Maritime Continent and Australasia ---------------------------------
    Teleconnection(
        "Indonesia and Malaysia", "Maritime Continent", "Jun-Feb",
        "Suppressed rainfall; elevated peatland and forest fire risk", "dry", HIGH, 0.5, ANY,
        "Convection shifts east off the warm pool, leaving the archipelago under "
        "subsidence. The 1997-98 and 2015-16 events both produced severe haze episodes.",
        "Rice and palm systems, and transboundary haze affecting respiratory health "
        "across Singapore, Malaysia and southern Thailand.",
    ),
    Teleconnection(
        "Papua New Guinea highlands", "Maritime Continent", "Aug-Feb",
        "Drought and, at altitude, damaging frost", "dry", HIGH, 1.0, ANY,
        "Clear skies over high valleys allow radiative frost that destroys sweet "
        "potato, the staple crop, with no fallback.",
        "Subsistence farming communities with limited road access; 1997-98 required "
        "a large relief operation.",
    ),
    Teleconnection(
        "Eastern Australia", "Maritime Continent", "Jun-Feb",
        "Below-average rainfall, higher fire danger", "dry", HIGH, 0.5, ANY,
        "One of the oldest documented ENSO relationships. Strongly modulated by the "
        "Indian Ocean Dipole - a positive IOD compounds it, a negative one can cancel it.",
        "Wheat belt yields, water storage, and the summer bushfire season.",
    ),
    Teleconnection(
        "Philippines", "Maritime Continent", "Sep-Apr",
        "Rainfall deficit and delayed monsoon onset", "dry", HIGH, 0.5, ANY,
        "Reduced tropical cyclone landfalls but a genuine water deficit; typhoon "
        "tracks tend to shift east and recurve.",
        "Rice and maize irrigation, and hydropower supply on Luzon and Mindanao.",
    ),
    Teleconnection(
        "Mekong basin and Thailand", "Southeast Asia", "Nov-May",
        "Reduced river flow and dry-season water stress", "dry", MODERATE, 1.0, ANY,
        "Low wet-season accumulation carries into the dry season; compounded by "
        "upstream storage operations, which makes attribution to ENSO alone unsafe.",
        "Irrigated rice in the delta, salinity intrusion, and inland fisheries.",
    ),
    # -- South Asia ----------------------------------------------------------
    Teleconnection(
        "India and Pakistan", "South Asia", "Jun-Sep",
        "Weaker summer monsoon", "dry", EMERGING, 1.0, EP,
        "The classic relationship has weakened markedly since the 1980s and several "
        "strong El Nino years have produced near-normal monsoons. East-Pacific events "
        "retain more of the link than central-Pacific ones.",
        "Kharif sowing, reservoir recharge, and rural employment demand.",
    ),
    # -- Africa --------------------------------------------------------------
    Teleconnection(
        "Southern Africa", "Africa", "Dec-Mar",
        "Rainfall failure during the main growing season", "dry", HIGH, 0.5, ANY,
        "The strongest and most consistent humanitarian teleconnection in the "
        "catalogue. It arrives precisely in the maize planting and grain-filling "
        "window across Zimbabwe, Zambia, Malawi, Mozambique, Botswana and South Africa.",
        "Rain-fed maize for tens of millions of people, with regional price contagion "
        "when South African production falls.",
    ),
    Teleconnection(
        "Equatorial East Africa", "Africa", "Oct-Dec",
        "Enhanced short rains, flooding and landslides", "wet", HIGH, 0.5, ANY,
        "Kenya, southern Somalia, southeastern Ethiopia, Uganda and Tanzania. The "
        "sign is opposite to southern Africa and often surprises people expecting "
        "El Nino to mean drought everywhere.",
        "Displacement and damage to shelter and roads; flooding on top of existing "
        "drought recovery is a compounding failure, not an offsetting one.",
    ),
    Teleconnection(
        "Ethiopian highlands and Sudan", "Africa", "Jun-Sep",
        "Weak Kiremt rains", "dry", HIGH, 0.5, ANY,
        "The main Ethiopian growing rains fail before the enhanced short rains "
        "arrive, so a single event can deliver drought then flood within six months.",
        "Belg and Meher harvests, livestock condition, and Blue Nile inflow.",
    ),
    Teleconnection(
        "Rift Valley fever risk, East Africa", "Africa", "Nov-Mar",
        "Outbreak conditions following heavy rain", "health", MODERATE, 1.0, ANY,
        "Flooding of dambo depressions hatches infected mosquito eggs. Major "
        "outbreaks followed the 1997-98 event in Kenya and Somalia.",
        "Livestock mortality and human infection, with export bans on livestock "
        "removing a primary income source.",
    ),
    Teleconnection(
        "Highland malaria, East Africa and Andes", "Africa", "Dec-May",
        "Transmission at unusual altitude", "health", MODERATE, 1.0, ANY,
        "Warmer temperatures and standing water extend the vector range upslope "
        "into populations with little acquired immunity.",
        "Epidemic rather than endemic transmission, which health systems in those "
        "districts are not configured for.",
    ),
    # -- The Americas --------------------------------------------------------
    Teleconnection(
        "Coastal Peru and Ecuador", "South America", "Dec-Apr",
        "Extreme coastal rainfall, flooding and debris flows", "wet", HIGH, 1.0, EP,
        "The original El Nino. Requires warmth in Nino-1+2 specifically, which is "
        "why it is gated to east-Pacific events; a central-Pacific event of the same "
        "Nino-3.4 strength may produce very little of it.",
        "Huaicos destroying road and bridge links, urban flooding in Piura and "
        "Trujillo, and a sharp rise in waterborne disease.",
    ),
    Teleconnection(
        "Peruvian anchoveta fishery", "South America", "Nov-May",
        "Thermocline deepens and the fishery collapses", "marine", HIGH, 1.0, EP,
        "Upwelling continues but draws warm nutrient-poor water; biomass falls and "
        "seasons are cancelled.",
        "The world's largest single-species fishery and the fishmeal supply "
        "underpinning global aquaculture and livestock feed prices.",
    ),
    Teleconnection(
        "Northern South America", "South America", "Dec-Mar",
        "Rainfall deficit", "dry", HIGH, 0.5, ANY,
        "Colombia, Venezuela, Guyana and northern Brazil sit under the descending "
        "branch through the wet season.",
        "Hydropower-dependent grids - Colombia, Venezuela and Ecuador all draw most "
        "of their electricity from reservoirs - and Amazon river transport.",
    ),
    Teleconnection(
        "Northeast Brazil", "South America", "Feb-May",
        "Failure of the main rainy season", "dry", HIGH, 0.5, ANY,
        "The semi-arid sertao has among the clearest El Nino drought signals "
        "anywhere in the Americas.",
        "Subsistence agriculture and municipal water supply in a region with thin "
        "storage margins.",
    ),
    Teleconnection(
        "Southern Brazil, Uruguay, northeast Argentina", "South America", "Nov-Feb",
        "Above-average rainfall and flooding", "wet", HIGH, 0.5, ANY,
        "A strengthened subtropical jet steers storms across the Plata basin.",
        "Soy and maize - beneficial in moderation, then damaging - and displacement "
        "along the Parana and Uruguay rivers.",
    ),
    Teleconnection(
        "Central American Dry Corridor", "Central America", "May-Aug",
        "Delayed onset and mid-summer drought", "dry", HIGH, 0.5, ANY,
        "Guatemala, Honduras, El Salvador and Nicaragua. The canicula lengthens and "
        "the primera harvest fails.",
        "Smallholder maize and beans; repeated failures here are a documented driver "
        "of displacement and northward migration.",
    ),
    Teleconnection(
        "Caribbean", "Central America", "Dec-Apr",
        "Drier than normal dry season", "dry", MODERATE, 0.5, ANY,
        "Follows a suppressed Atlantic hurricane season, so two dry inputs arrive "
        "back to back.",
        "Island water supply with limited storage, and tourism-season demand.",
    ),
    Teleconnection(
        "US Gulf Coast and Southeast", "North America", "Dec-Mar",
        "Wetter and stormier than normal", "wet", HIGH, 0.5, ANY,
        "A southward-displaced, strengthened subtropical jet. Also raises the "
        "cool-season tornado and severe-storm count across the Gulf states.",
        "Flood risk in Louisiana, Mississippi, Alabama, Georgia and Florida.",
    ),
    Teleconnection(
        "California and the US Southwest", "North America", "Dec-Mar",
        "Tilt toward a wetter winter, strongest in the south", "wet", MODERATE, 1.0, ANY,
        "Less reliable than its reputation: several strong events delivered near-"
        "normal California precipitation. Southern California and Arizona have the "
        "clearer signal; northern California does not.",
        "Atmospheric-river flooding, debris flows on recent burn scars, and reservoir "
        "and snowpack recovery.",
    ),
    Teleconnection(
        "US Pacific Northwest and Ohio Valley", "North America", "Dec-Mar",
        "Drier and milder than normal", "dry", MODERATE, 0.5, ANY,
        "The northern storm track lifts away, leaving a thin snowpack.",
        "Snowpack-dependent summer water supply and the following fire season.",
    ),
    Teleconnection(
        "Canada and the northern United States", "North America", "Dec-Feb",
        "Milder winter", "hot", HIGH, 0.5, ANY,
        "A well-reproduced Pacific-North American pattern response.",
        "Lower heating demand, and a shorter ice season on the Great Lakes.",
    ),
    # -- Storms, oceans, and the global picture ------------------------------
    Teleconnection(
        "Atlantic hurricane season", "Global systems", "Aug-Oct",
        "Suppressed activity", "storm", HIGH, 0.5, EP,
        "Increased vertical wind shear over the main development region. One of the "
        "most reliable seasonal-forecast signals in existence, and the clearest "
        "case where an El Nino reduces rather than increases a hazard.",
        "Fewer US and Caribbean landfalls - though a single storm in a quiet season "
        "still does what a single storm does.",
    ),
    Teleconnection(
        "Eastern and central Pacific hurricanes", "Global systems", "Jul-Oct",
        "Enhanced activity, tracking further west", "storm", HIGH, 0.5, ANY,
        "Warm water and reduced shear extend the basin westward, raising the risk "
        "to Hawaii and to central Pacific island states.",
        "Small island states with minimal margin for a direct strike.",
    ),
    Teleconnection(
        "Western North Pacific typhoons", "Global systems", "Aug-Dec",
        "Formation shifts southeast; longer, more intense tracks", "storm", MODERATE, 1.0, ANY,
        "Genesis moves toward the southeast quadrant, giving storms a longer run "
        "over warm water and more time to intensify before recurving.",
        "Higher-intensity landfalls in Japan and Korea; more recurvature away from "
        "the Philippines even as that country dries.",
    ),
    Teleconnection(
        "Pacific and Indian Ocean coral reefs", "Global systems", "Dec-Jun",
        "Mass bleaching from accumulated heat stress", "marine", HIGH, 1.0, ANY,
        "The 1997-98, 2014-17 and 2023-25 events drove global bleaching "
        "episodes; the last put more than four fifths of the world's reef area "
        "under bleaching-level heat stress, the most extensive on record. "
        "Central and eastern Pacific reefs go first, then the wider basin.",
        "Reef fisheries, coastal protection from wave energy, and ecosystems that "
        "need a decade or more to recover if they recover at all.",
    ),
    Teleconnection(
        "Global mean surface temperature", "Global systems", "Dec-Nov",
        "Elevated for roughly a year, peaking after the event", "hot", HIGH, 1.0, ANY,
        "Heat released from the Pacific raises global temperature with a lag of "
        "three to six months, so the warmest calendar year is usually the one "
        "AFTER the peak.",
        "Compounding with the background trend: the hottest years on record have "
        "been El Nino years riding on top of it.",
    ),
    Teleconnection(
        "Pacific island states", "Global systems", "Nov-Apr",
        "Rainfall redistribution and a shifted cyclone belt", "storm", HIGH, 0.5, ANY,
        "Kiribati and Tuvalu turn wet while Fiji, Vanuatu, Samoa and Papua New "
        "Guinea dry; the cyclone belt shifts east toward French Polynesia.",
        "Freshwater lenses on atolls, which fail before anything else does.",
    ),
)


def _likelihood(margin: float, confidence: str) -> str:
    """Translate 'how far past the threshold' into words, tempered by confidence."""
    if confidence == EMERGING:
        return "possible" if margin >= 0.5 else "uncertain"
    if margin >= LIKELY_MARGIN:
        return "likely"
    if margin >= PROBABLE_MARGIN:
        return "probable"
    if margin >= 0.0:
        return "possible"
    return "unlikely"


def flavour_of(flavour_index: float) -> str:
    """EP, CP or mixed, from the Nino-1+2 minus Nino-4 difference."""
    if flavour_index >= EP_FLAVOUR:
        return EP
    if flavour_index <= CP_FLAVOUR:
        return CP
    return "mixed"


def flavour_words(flavour: str) -> str:
    """The flavour as a reader writes it, not as the catalogue keys it."""
    return {EP: "east-Pacific", CP: "central-Pacific"}.get(flavour, flavour)


def flavour_penalty(link: Teleconnection, flavour: str) -> float:
    """How much further an event of this flavour has to go for this link."""
    if (link.flavour, flavour) in ((EP, CP), (CP, EP)):
        return FLAVOUR_PENALTY
    return 0.0


def needs(link: Teleconnection, flavour: str) -> float | None:
    """The index peak at which a link reaches "probable", or None if it never can."""
    if link.confidence == EMERGING:
        return None
    return link.min_intensity + flavour_penalty(link, flavour) + PROBABLE_MARGIN


def evaluate(link: Teleconnection, value: float,
             flavour: str) -> tuple[float, str, str]:
    """Score one relationship at one index value. Returns margin, likelihood, note.

    Pulled out of ``assess`` so the globe can score the same catalogue at
    today's value as well as at the projected peak without a second copy of
    the gating rules drifting away from this one.
    """
    margin = value - link.min_intensity - flavour_penalty(link, flavour)
    note = ""
    if link.flavour == EP and flavour == CP:
        note = "Gated to east-Pacific events; the current flavour argues against it."
    elif link.flavour == EP and flavour == EP:
        note = "Reinforced by the east-Pacific flavour of this event."
    elif link.flavour == CP and flavour == EP:
        note = "Gated to central-Pacific events; this one is not."
    return margin, _likelihood(margin, link.confidence), note


def event_peak(episode: Episode | None, forecast_peak: Projection | None) -> tuple[str, int] | None:
    """The season the event peaks in, a (season, year) pair as CPC dates it,
    which each effect's window is dated by.

    An El Nino under way peaks at its highest, seen or forecast: a forecast
    above the episode's own peak is still to come, and one below it is the
    decay of an event that has peaked, whose southern African rains in June
    2027 were those of 2026-27, not those of the forecast's highest season a
    year on. With none under way the event is the one the forecast grows.
    """
    if episode is None:
        return (forecast_peak.season, forecast_peak.year) if forecast_peak else None
    if forecast_peak is not None and forecast_peak.mean > episode.peak.value:
        return forecast_peak.season, forecast_peak.year
    return episode.peak.season, episode.peak.year


def window_span(window: str, peak_season: tuple[str, int]) -> tuple[Month, Month]:
    """The (year, month) a link's window opens and closes in, for an event
    peaking in ``peak_season``, a (season, year) pair as CPC dates it.

    An event peaking in NDJ 2026 brings India's Jun-Sep monsoon of 2026,
    southern Africa's Dec-Mar rains of 2026-27 and Northeast Brazil's Feb-May
    of 2027; one peaking in JFM 2027 grew in 2026 all the same.
    """
    start, end = (MONTHS.index(name) + 1 for name in window.split("-"))
    year, month = season_months(*peak_season)[1]
    grew = year if month >= GROWING_FROM else year - 1
    first = grew if start >= GROWING_FROM else grew + 1
    last = first + 1 if end < start else first
    return (first, start), (last, end)


def _dated(first: Month, last: Month) -> str:
    """A window as dated: Jun\u2013Sep 2026, or Dec 2026\u2013Mar 2027 across a new year."""
    (y0, m0), (y1, m1) = first, last
    if y0 == y1:
        return f"{MONTHS[m0 - 1]}\u2013{MONTHS[m1 - 1]} {y0}"
    return f"{MONTHS[m0 - 1]} {y0}\u2013{MONTHS[m1 - 1]} {y1}"


def window_text(window: str) -> str:
    """A link's window as the page writes a span of months: Dec–Mar."""
    return window.replace("-", "–")


def peak_when(peak_season: tuple[str, int], today: date) -> str:
    """How far ``today`` is from the peak season: "about 3 months away" to its
    centre month, "under way" within it, "now past" after it."""
    months = season_months(*peak_season)
    now = (today.year, today.month)
    if now > months[-1]:
        return "now past"
    if now >= months[0]:
        return "under way"
    year, month = months[1]
    return f"about {(year - today.year) * 12 + month - today.month} months away"


def assess(
    peak_index: float,
    flavour_index: float,
    current_index: float | None = None,
    peak_season: tuple[str, int] | None = None,
    today: date | None = None,
    index_name: str = "RONI",
) -> ImpactAssessment:
    """Which teleconnections the projected event puts in play.

    ``peak_index`` is the projected peak of the official index, and the
    catalogue's thresholds are read against it. ``flavour_index`` is the
    Nino-1+2 minus Nino-4 anomaly difference: strongly positive means an
    east-Pacific event, negative a central-Pacific one. Given the peak's
    ``peak_season`` and ``today``, each link's window is dated for this event
    and marked ahead, under way or past, and the past are listed last.
    """
    flavour = flavour_of(flavour_index)

    notes: list[str] = []
    active: list[ActiveImpact] = []
    watch: list[ActiveImpact] = []

    for link in CATALOGUE:
        margin, likelihood, flavour_note = evaluate(link, peak_index, flavour)
        timing, when, dated = window_text(link.window), "", ""
        if peak_season is not None and today is not None:
            first, last = window_span(link.window, peak_season)
            now = (today.year, today.month)
            when = "ahead" if now < first else "past" if now > last else "under way"
            dated = _dated(first, last)
            timing = f"{dated}, {when}"

        impact = ActiveImpact(link, likelihood, margin, timing, flavour_note,
                              needs(link, flavour), when, dated)
        if likelihood in ("likely", "probable"):
            active.append(impact)
        elif likelihood in ("possible", "uncertain"):
            watch.append(impact)

    # What is still to come first; an effect whose season has passed, last.
    active.sort(key=lambda i: (i.when == "past", -i.severity))
    watch.sort(key=lambda i: (i.when == "past", -i.severity))

    # The outlook proper, by area. Watch items are listed once, separately,
    # with what it would take to promote them.
    by_area: dict[str, list[ActiveImpact]] = {}
    for impact in active:
        by_area.setdefault(impact.link.area, []).append(impact)

    if flavour == EP:
        notes.append(
            "An east-Pacific event. The coastal Peru/Ecuador flooding signal and "
            "Atlantic hurricane suppression are at their strongest in this flavour."
        )
    elif flavour == CP:
        notes.append(
            "A central-Pacific (Modoki) event. Coastal South American flooding is "
            f"much less likely than {index_name} alone would suggest, and several "
            "North American patterns shift westward."
        )
    else:
        notes.append(
            "Flavour is mixed, so flavour-gated relationships are neither "
            "reinforced nor discounted."
        )

    if current_index is not None and current_index < peak_index - 0.3:
        notes.append(
            f"These are keyed to the PROJECTED {index_name} peak of "
            f"{peak_index:+.2f} degC, not today's {current_index:+.2f} degC. If the "
            "event underperforms the forecast, the lower-margin entries drop out first."
        )

    notes.append(
        "Hazard outlook from historical composites, not a forecast. ENSO shifts "
        "the odds; it does not decide the outcome, and vulnerability matters more "
        "than rainfall percentile."
    )

    return ImpactAssessment(
        active=active,
        watch=watch,
        peak_index=peak_index,
        flavour=flavour,
        by_area=by_area,
        notes=notes,
        index_name=index_name,
    )
