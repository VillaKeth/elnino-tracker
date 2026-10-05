"""The site's menu: one bar naming the site's pages, the first thing on each.

The site is four pages: the dashboard, which is also its front page, the El
Nino map, the storm desk and the atlas. Each opens on this bar, so a reader
can get from any of them to any other, and finds the way in the same place on
every one. Its rules are the shell's (``dashboard._css``), which all four
carry.
"""

from __future__ import annotations

from .svg import esc

# The site's pages, in the order the menu names them.
PAGES = (
    ("dashboard.html", "Dashboard"),
    ("map.html", "El Niño map"),
    ("storms.html", "Storm desk"),
    ("atlas.html", "Atlas"),
)

# The front page's icon, beside the site's name. It is a picture of the name,
# so a screen reader is not shown it, and reads the name once.
_MARK = ('<svg class="sitemark" viewBox="0 0 32 32" width="22" height="22" '
         'aria-hidden="true" focusable="false">'
         '<circle cx="16" cy="16" r="15" fill="#eb6834"/>'
         '<circle cx="16" cy="16" r="7" fill="#fcd8c6"/></svg>')


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
