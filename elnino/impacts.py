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

# Confidence reflects how consistently the relationship appears across past
# events, not how severe the outcome is.
HIGH = "high"
MODERATE = "moderate"
EMERGING = "weaker / contested"

# Flavour gating. EP (canonical, east-Pacific) and CP (Modoki, central-Pacific)
# events teleconnect differently; a few relationships flip almost entirely.
ANY, EP, CP = "any", "east-pacific", "central-pacific"


@dataclass(frozen=True)
class Teleconnection:
    region: str
    area: str
    window: str  # the season in which the signal appears
    effect: str
    polarity: str  # dry | wet | hot | cold | storm | marine | health
    confidence: str
    min_intensity: float  # ONI at which this typically becomes evident
    flavour: str
    detail: str
    exposure: str


@dataclass
class ActiveImpact:
    link: Teleconnection
    likelihood: str
    margin: float  # projected peak ONI minus the link's threshold
    timing: str
    flavour_note: str = ""

    @property
    def severity(self) -> int:
        """Crude ordering for display: confidence first, then margin."""
        rank = {HIGH: 3, MODERATE: 2, EMERGING: 1}[self.link.confidence]
        return rank * 10 + min(int(self.margin * 4), 9)


@dataclass
class ImpactAssessment:
    active: list[ActiveImpact]
    watch: list[ActiveImpact]
    peak_oni: float
    flavour: str
    by_area: dict[str, list[ActiveImpact]] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


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
        "ONI may produce very little of it.",
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
        "The 1997-98 and 2014-17 events drove the largest bleaching episodes on "
        "record. Central and eastern Pacific reefs go first, then the wider basin.",
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
    if margin >= 1.0:
        return "likely"
    if margin >= 0.4:
        return "probable"
    if margin >= 0.0:
        return "possible"
    return "unlikely"


def flavour_of(flavour_index: float) -> str:
    """EP, CP or mixed, from the Nino-1+2 minus Nino-4 difference."""
    if flavour_index >= 1.0:
        return EP
    if flavour_index <= -0.5:
        return CP
    return "mixed"


def evaluate(link: Teleconnection, oni: float,
             flavour: str) -> tuple[float, str, str]:
    """Score one relationship at one ONI. Returns margin, likelihood, note.

    Pulled out of ``assess`` so the globe can score the same catalogue at
    today's ONI as well as at the projected peak without a second copy of the
    gating rules drifting away from this one.
    """
    margin = oni - link.min_intensity
    note = ""
    if link.flavour == EP and flavour == CP:
        margin -= 0.75
        note = "Gated to east-Pacific events; the current flavour argues against it."
    elif link.flavour == EP and flavour == EP:
        note = "Reinforced by the east-Pacific flavour of this event."
    elif link.flavour == CP and flavour == EP:
        margin -= 0.75
        note = "Gated to central-Pacific events; this one is not."
    return margin, _likelihood(margin, link.confidence), note


def assess(
    peak_oni: float,
    flavour_index: float,
    current_oni: float | None = None,
    months_to_peak: int | None = None,
) -> ImpactAssessment:
    """Which teleconnections the projected event puts in play.

    ``flavour_index`` is the Nino-1+2 minus Nino-4 anomaly difference: strongly
    positive means an east-Pacific event, negative a central-Pacific one.
    """
    flavour = flavour_of(flavour_index)

    notes: list[str] = []
    active: list[ActiveImpact] = []
    watch: list[ActiveImpact] = []

    for link in CATALOGUE:
        margin, likelihood, flavour_note = evaluate(link, peak_oni, flavour)
        timing = link.window
        if months_to_peak is not None and months_to_peak > 0:
            timing = f"{link.window} (peak expected in ~{months_to_peak} months)"

        impact = ActiveImpact(link, likelihood, margin, timing, flavour_note)
        if likelihood in ("likely", "probable"):
            active.append(impact)
        elif likelihood in ("possible", "uncertain"):
            watch.append(impact)

    active.sort(key=lambda i: -i.severity)
    watch.sort(key=lambda i: -i.severity)

    by_area: dict[str, list[ActiveImpact]] = {}
    for impact in active + watch:
        by_area.setdefault(impact.link.area, []).append(impact)

    if flavour == EP:
        notes.append(
            "An east-Pacific event. The coastal Peru/Ecuador flooding signal and "
            "Atlantic hurricane suppression are at their strongest in this flavour."
        )
    elif flavour == CP:
        notes.append(
            "A central-Pacific (Modoki) event. Coastal South American flooding is "
            "much less likely than the ONI alone would suggest, and several "
            "North American patterns shift westward."
        )
    else:
        notes.append(
            "Flavour is mixed, so flavour-gated relationships are neither "
            "reinforced nor discounted."
        )

    if current_oni is not None and current_oni < peak_oni - 0.3:
        notes.append(
            f"These are keyed to the PROJECTED peak of {peak_oni:+.1f} degC, not "
            f"today's {current_oni:+.1f} degC. If the event underperforms the "
            "forecast, the lower-margin entries drop out first."
        )

    notes.append(
        "Hazard outlook from historical composites, not a forecast. ENSO shifts "
        "the odds; it does not decide the outcome, and vulnerability matters more "
        "than rainfall percentile."
    )

    return ImpactAssessment(
        active=active,
        watch=watch,
        peak_oni=peak_oni,
        flavour=flavour,
        by_area=by_area,
        notes=notes,
    )
