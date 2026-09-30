"""What past events actually did.

The analog machinery in ``classify`` finds which historical events resemble the
current one. This module supplies the other half of that comparison: what
happened when those events matured. The numbers for each event - its peak,
duration and strength class - are computed from the live index rather than
stored here, so this file holds only the documented record: the flavour the
literature gives the event, and its consequences. No summary names a strength
class, because the class depends on which index is read - 1965-66 is Very
Strong on RONI and Strong on ONI, 2023-24 Moderate on RONI and Very Strong on
ONI - and a stored word would contradict the table printed beside it.

Sources for the consequence records are NOAA/NCEI event summaries, the WMO El
Nino/La Nina Updates, FEWS NET and IPC assessments, and OCHA situation reports.
Loss figures from different events are not comparable with each other: methods,
coverage and currency years all differ, so they are quoted as published and
described rather than totalled.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class EventRecord:
    label: str
    flavour: str
    summary: str
    consequences: tuple[str, ...] = field(default_factory=tuple)
    lesson: str = ""


# Keyed by the calendar year in which the event's development began.
EVENTS: dict[int, EventRecord] = {
    1957: EventRecord(
        "1957-58", "east-pacific",
        "Observed during the International Geophysical Year, which is why it is "
        "unusually well documented for its era.",
        (
            "Severe drought across northeastern Brazil.",
            "The first El Nino to be documented with basin-wide instrumentation, "
            "which is what allowed Bjerknes to propose the coupled mechanism.",
        ),
        "The event that turned El Nino from a Peruvian coastal curiosity into a "
        "global climate phenomenon.",
    ),
    1965: EventRecord(
        "1965-66", "east-pacific",
        "Sharply peaked - it decayed quickly through the following spring.",
        ("Indian monsoon failure compounding a drought already under way.",),
    ),
    1972: EventRecord(
        "1972-73", "east-pacific",
        "An event whose economic consequences were felt worldwide within months.",
        (
            "The Peruvian anchoveta fishery collapsed from roughly 12 million "
            "tonnes to under 2 million; it did not fully recover for years.",
            "Global fishmeal shortage propagated into soy and grain markets, "
            "coinciding with the Soviet grain purchases to produce a world food "
            "price shock.",
            "Drought across the Sahel, India and Australia in the same year.",
        ),
        "The event that demonstrated ENSO is transmitted through commodity "
        "markets as well as through the atmosphere.",
    ),
    1982: EventRecord(
        "1982-83", "east-pacific",
        "The strongest event of the record up to its time, and almost entirely "
        "unanticipated.",
        (
            "Catastrophic flooding in Peru and Ecuador; drought and the Ash "
            "Wednesday bushfires in southeastern Australia.",
            "Severe drought in Indonesia, the Philippines, southern Africa and "
            "northeast Brazil.",
            "Damage assessed at the time in the region of US$8 billion.",
        ),
        "It was missed as it developed. Satellite SST retrievals were "
        "contaminated by stratospheric aerosol from the El Chichon eruption, and "
        "the buoy network did not yet exist - which is precisely why the TAO "
        "array was built and why redundant, independent indices matter.",
    ),
    1986: EventRecord(
        "1986-87", "central-pacific",
        "A long-lived event that ran on through a second winter, into early 1988.",
        ("Drought in southern Africa and across the Indian subcontinent.",),
    ),
    1991: EventRecord(
        "1991-92", "east-pacific",
        "An event followed by an unusually prolonged run of warm conditions "
        "through the mid-1990s.",
        (
            "Severe drought in southern Africa - by several measures the worst of "
            "the twentieth century there - with maize production falling by more "
            "than half in Zimbabwe and Zambia.",
        ),
    ),
    1997: EventRecord(
        "1997-98", "east-pacific",
        "The benchmark east-Pacific event: rapidly developing, and the first to "
        "be forecast with useful lead time.",
        (
            "Indonesian drought and peat fires produced a haze emergency across "
            "Southeast Asia.",
            "Torrential flooding in Peru and Ecuador; drought and highland frost "
            "in Papua New Guinea requiring international relief.",
            "Flooding in East Africa followed by the largest Rift Valley fever "
            "outbreak on record in Kenya and Somalia.",
            "1998 became the warmest year then recorded.",
            "Damage estimates published at the time ranged from US$32 billion "
            "upward, with roughly 23,000 deaths attributed across associated events.",
        ),
        "It was forecast months ahead, and the forecast was widely disbelieved. "
        "The places that acted on it - notably parts of Peru - measurably reduced "
        "their losses.",
    ),
    2002: EventRecord(
        "2002-03", "central-pacific",
        "A central-Pacific event.",
        ("Australian drought severe enough to cut national GDP growth.",),
    ),
    2009: EventRecord(
        "2009-10", "central-pacific",
        "Central-Pacific in character: the warmth peaked near the date line "
        "rather than off South America.",
        (
            "Contributed to record global warmth in 2010.",
            "Followed immediately by a strong La Nina and the 2010-11 Queensland "
            "floods - a reminder that the hazard does not end when the warm event does.",
        ),
    ),
    2014: EventRecord(
        "2014-15", "central-pacific",
        "The first year of the 2014-16 warm run: widely forecast to become a "
        "major event, it stalled, then re-intensified the following year.",
        ("Little direct impact, but it began the 2014-17 global coral bleaching "
         "episode, the longest on record.",),
        "The clearest modern case of an event that was over-forecast. Strong "
        "westerly forcing in early 2014 did not couple, and the event stalled - "
        "which is why this tracker reports ocean and atmosphere separately.",
    ),
    2015: EventRecord(
        "2015-16", "east-pacific",
        "Comparable at its peak to 1997-98 in either index, though with a "
        "different structure and a warmer background state.",
        (
            "Drought in Ethiopia described as the worst in fifty years, with more "
            "than ten million people requiring food assistance.",
            "Southern African drought affecting tens of millions across the "
            "region's main growing season.",
            "Severe drought and fires in Indonesia; water emergencies across the "
            "Pacific islands.",
            "2016 set a global temperature record; mass coral bleaching on the "
            "Great Barrier Reef and across the Pacific.",
        ),
        "Humanitarian appeals were launched months in advance on the strength of "
        "the forecast, and were substantially underfunded until the impacts "
        "arrived. The science led; the financing did not follow.",
    ),
    2018: EventRecord(
        "2018-19", "central-pacific",
        "A central-Pacific event whose atmosphere was slow to respond: the ocean "
        "was at El Nino levels from the autumn of 2018, but CPC did not declare "
        "El Nino conditions until February 2019.",
        (),
    ),
    2023: EventRecord(
        "2023-24", "east-pacific",
        "Built on an already record-warm ocean, which made attribution of the "
        "resulting heat unusually contested.",
        (
            "Consecutive global temperature records through 2023 and 2024.",
            "Panama Canal transits restricted for months as Gatun Lake fell, "
            "rerouting global shipping.",
            "Drought emergencies declared in Zambia, Zimbabwe and Malawi.",
            "Widespread coral bleaching declared a global event in 2024.",
        ),
        "The warming background pulled the two indices apart: ONI, measured "
        "against a 30-year base period that lags the warming, ran well above "
        "RONI, so how unusual the Pacific itself was depends on which index is "
        "read - the problem RONI, now the official index, was adopted to remove.",
    ),
}


def for_episode(episode) -> EventRecord | None:
    """The documented record of the event an index episode is, if there is one.

    Each record describes the event that developed in its key year and matured
    over the northern winter that followed, so it belongs to an episode whose
    run contains that December. A run can contain two: SON 2014 to AMJ 2016 is
    a single episode in both indices, and its record is the winter it peaked
    in - 2015-16 - not the stalled 2014-15 start. A run with no record of its
    own gets none; the old look-up borrowed a neighbouring year's, which would
    have given a 2019-20 run the 2018-19 record.
    """
    def month(season) -> int:
        return season.centre.year * 12 + season.centre.month - 1

    first, last = month(episode.onset), month(episode.latest)
    peak = month(episode.peak)
    winters = [year for year in EVENTS if first <= year * 12 + 11 <= last]
    if not winters:
        return None
    return EVENTS[min(winters, key=lambda year: abs(year * 12 + 11 - peak))]
