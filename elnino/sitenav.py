"""The site's menu: one bar naming the site's pages, the first thing on each.

The site is four pages: the Dashboard, which is also its front page, the El
Nino Map, the Storm Desk and the Atlas. Each opens on this bar, so a reader
can get from any of them to any other, and finds the way in the same place on
every one. Its rules are the shell's (``dashboard._css``), which all four
carry. Its mark is the site's icon too, in every page's tab.
"""

from __future__ import annotations

from urllib.parse import quote

from .svg import esc

# The site's pages, in the order the menu names them.
PAGES = (
    ("dashboard.html", "Dashboard"),
    ("map.html", "El Niño Map"),
    ("storms.html", "Storm Desk"),
    ("atlas.html", "Atlas"),
)

# The site's mark: the equatorial Pacific as a disc of sea, and El Nino's
# warm tongue reaching west along the equator from the coast of South America,
# its core hottest in the east, as a sea surface temperature anomaly map draws
# it: widest at the coast, its western end rounded. The tongue and its core end
# on the disc's rim, so nothing needs clipping.
_SHAPES = ('<circle cx="16" cy="16" r="15" fill="#2366a8"/>'
           '<path d="M29.42 9.3C22 9.5 14 12 9.5 14.2C7.8 15 7.8 17 9.5 17.8'
           'C14 20 22 22.5 29.42 22.7A15 15 0 0 0 29.42 9.3Z" fill="#f59a4f"/>'
           '<path d="M30.51 12.2C25 12.6 20 14 17.6 15.2C16.6 15.7 16.6 16.3 17.6 16.8'
           'C20 18 25 19.4 30.51 19.8A15 15 0 0 0 30.51 12.2Z" fill="#d8402a"/>')

# Beside the site's name in the menu. It is a picture of the name, so a screen
# reader is not shown it, and reads the name once.
_MARK = ('<svg class="sitemark" viewBox="0 0 32 32" width="22" height="22" '
         f'aria-hidden="true" focusable="false">{_SHAPES}</svg>')

# The same picture as every page's icon, written into the page: a data URI,
# not a request.
ICON = ('<link rel="icon" href="data:image/svg+xml,'
        + quote(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">{_SHAPES}</svg>',
                safe="/=:.,-")
        + '">')


def bar(here: str, carry: tuple[str, ...] = ()) -> str:
    """The menu as the page ``here`` shows it, marking that page as the one
    the reader is on.

    The pages in ``carry`` are handed the reader's view as they are followed:
    their links wear ``data-carry``, which the page's own script reads to
    write the view into them (the storm desk's ``carryView``).
    """
    names = dict(PAGES)
    for page in (here, *carry):
        if page not in names:
            raise ValueError(f"{page!r} is not a page of the site")
    tabs = []
    for href, name in PAGES:
        attrs = f' href="{href}"'
        if href == here:
            attrs += ' aria-current="page"'
        if href in carry:
            attrs += f' data-carry="{href}"'
        tabs.append(f'<li><a class="tab"{attrs}>{esc(name)}</a></li>')
    return ('<nav class="sitebar" aria-label="Site">'
            f'<a class="brand" href="dashboard.html">{_MARK}<span>El Niño Tracker</span></a>'
            f'<ul>{"".join(tabs)}</ul></nav>')
