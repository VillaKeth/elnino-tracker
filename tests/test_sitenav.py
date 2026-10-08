"""The site's menu (elnino/sitenav.py): one bar naming the site's pages, the
first thing on every page, so a reader can get from any page to any other."""

from __future__ import annotations

import re
import sys
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from elnino import atlas, atlasview, dashboard, sitenav, stormdesk  # noqa: E402
# The helpers only: importing a TestCase class here would run it twice.
from test_tracker import _DeskFixtures  # noqa: E402

PAGES = ["dashboard.html", "map.html", "storms.html", "atlas.html"]
NAMES = ["Dashboard", "El Niño Map", "Storm Desk", "Atlas"]


def tabs(html: str) -> list[tuple[str, str, bool, str | None]]:
    """(href, name, whether the reader is on it, where it carries the view)
    for each page the menu in ``html`` names, in its order."""
    nav = re.search(r'<nav class="sitebar"[^>]*>(.*?)</nav>', html, re.S).group(1)
    found = []
    for href, attrs, name in re.findall(r'<a class="tab" href="([^"]*)"([^>]*)>([^<]*)</a>', nav):
        carried = re.search(r' data-carry="([^"]*)"', attrs)
        found.append((href, name, ' aria-current="page"' in attrs, carried and carried.group(1)))
    return found


def flat(css: str) -> str:
    """``css`` with every run of spacing one space, as a rule reads on a line."""
    return " ".join(css.split())


def rule(css: str, selector: str) -> str:
    """The declarations of the one rule ``selector`` heads in ``css``."""
    found = re.findall(r"(?:^|\n)" + re.escape(selector) + r" \{([^}]*)\}", css)
    assert len(found) == 1, (selector, found)
    return " ".join(found[0].split())


class TestTheMenu(unittest.TestCase):

    def test_it_names_every_page_in_one_order_and_marks_the_reader_s_own(self):
        for here in PAGES:
            with self.subTest(here=here):
                found = tabs(sitenav.bar(here))
                self.assertEqual([href for href, *_ in found], PAGES)
                self.assertEqual([name for _, name, *_ in found], NAMES)
                self.assertEqual([href for href, _, current, _ in found if current], [here])

    def test_its_mark_leads_to_the_front_page_and_is_named_for_the_site(self):
        html = sitenav.bar("atlas.html")
        self.assertIn('<nav class="sitebar" aria-label="Site">', html)
        brand = re.search(r'<a class="brand" href="([^"]*)">(<svg[^>]*>.*?</svg>)<span>([^<]*)</span></a>',
                          html, re.S)
        self.assertTrue(brand, html)
        self.assertEqual((brand.group(1), brand.group(3)), ("dashboard.html", "El Niño Tracker"))
        # The mark is a picture of the name beside it, so a screen reader
        # reads the name once.
        self.assertIn('aria-hidden="true"', brand.group(2))

    def test_its_mark_is_el_nino_s_warm_tongue_and_the_site_s_icon(self):
        # The equatorial Pacific as a blue disc, and El Niño's warm tongue
        # reaching west along the equator from South America, hottest in the
        # east: a tongue and its core. The tab's icon is the same picture.
        mark = re.search(r'<svg class="sitemark"[^>]*>(.*?)</svg>',
                         sitenav.bar("atlas.html"), re.S).group(1)
        self.assertEqual(re.findall(r"<(circle|path)\b", mark), ["circle", "path", "path"])
        self.assertNotIn("#fcd8c6", mark)
        icon = re.fullmatch(r'<link rel="icon" href="data:image/svg\+xml,([^"<>#]*)">', sitenav.ICON)
        self.assertTrue(icon, sitenav.ICON)
        self.assertIn(mark, unquote(icon.group(1)))
        self.assertIn('xmlns="http://www.w3.org/2000/svg"', unquote(icon.group(1)))

    def test_it_hands_the_view_on_only_where_it_is_asked_to(self):
        found = tabs(sitenav.bar("storms.html", carry=("map.html",)))
        self.assertEqual([(href, carried) for href, _, _, carried in found if carried],
                         [("map.html", "map.html")])
        self.assertEqual([carried for *_, carried in tabs(sitenav.bar("atlas.html")) if carried], [])

    def test_a_page_the_site_does_not_have_is_refused(self):
        for here, carry in (("index.html", ()), ("map", ()), ("storms.html", ("Map.html",))):
            with self.subTest(here=here, carry=carry), self.assertRaises(ValueError):
                sitenav.bar(here, carry=carry)

    def test_one_stylesheet_styles_it_on_every_page(self):
        # The shell's rules, which all four pages carry. The desk and the atlas
        # lay their pages out as a column the height of the screen: the menu
        # keeps its height there. The dashboard is read a long way down: there
        # alone the menu stays pinned in reach, over the page's column, and
        # what a reader tabs to or opens stays clear of it. Paper has no use
        # for it.
        css = dashboard._css()
        self.assertIn("flex: none;", rule(css, ".sitebar"))
        self.assertIn("overflow-x: auto;", rule(css, ".sitebar"))
        pinned = rule(css, ".dashpage .sitebar")
        self.assertIn("position: sticky; top: 0;", pinned)
        self.assertEqual(re.findall(r"([^{};\n]*\.sitebar[^{};\n]*) \{[^}]*position: sticky", css),
                         [".dashpage .sitebar"])
        # Its name starts where the column's own words do.
        self.assertIn("padding-inline: max(16px, (100% - 1080px) / 2 + 16px);", pinned)
        self.assertIn("\n.wrap { max-width: 1080px; margin: 0 auto; padding: 32px 16px 72px; }", css)
        self.assertEqual(rule(css, ":root:has(> body.dashpage)"), "scroll-padding-top: 60px;")
        self.assertIn("box-shadow: inset 0 -2px 0 var(--s2);",
                      rule(css, '.sitebar .tab[aria-current="page"]'))
        self.assertIn("@media print { .sitebar { display: none; } }", css)

    def test_its_mark_keeps_its_size_and_each_link_is_a_thumb_high(self):
        # The shell sizes every svg to its box: the mark is sized for itself.
        # The name and each page are 44 px high, as the desk's controls are.
        css = dashboard._css()
        self.assertIn("\nsvg { width: 100%; height: auto;", css)
        # A logo keeps its colours where colours are forced: flattened to one,
        # its tongue would vanish into its sea.
        self.assertEqual(rule(css, ".sitebar .sitemark"),
                         "flex: none; width: 22px; height: 22px; forced-color-adjust: none;")
        self.assertIn("min-height: 44px;", rule(css, ".sitebar .brand"))
        self.assertIn("min-height: 44px;", rule(css, ".sitebar .tab"))

    def test_it_fits_a_phone_320_px_wide(self):
        # There the pages alone fit, closer still: the name leads where the
        # Dashboard does.
        self.assertIn("@media (max-width: 359px) { .sitebar .brand { display: none; } "
                      ".sitebar .tab { padding: 0 4px; } }", flat(dashboard._css()))

    def test_the_reader_s_page_is_marked_where_colours_are_forced(self):
        # Forced colours drop the shadow that marks it: there it is underlined.
        self.assertIn('@media (forced-colors: active) { .sitebar .tab[aria-current="page"] { '
                      'text-decoration: underline 2px; text-underline-offset: 6px; } }',
                      flat(dashboard._css()))


class TestEveryPageOpensOnIt(_DeskFixtures, unittest.TestCase):

    def test_the_map_and_the_storm_desk_open_on_it_handing_the_view_across(self):
        for focus, here, other in (("world", "map.html", "storms.html"),
                                   ("storms", "storms.html", "map.html")):
            with self.subTest(focus=focus):
                html = stormdesk.page(self.state(self.polo()), focus=focus)
                self.assertEqual(html.count('<nav class="sitebar"'), 1)
                self.assertIn('<body class="deskpage">\n' + sitenav.bar(here, carry=(other,))
                              + '\n<header class="deskhead">', html)
                # The menu names the pages, so the header keeps only the theme.
                self.assertIn('<div class="headbtns"><button type="button" class="themebtn" '
                              'id="theme">Dark</button></div>', html)
                self.assertNotIn('<a class="themebtn"', html)

    def test_the_atlas_opens_on_it(self):
        html = atlasview.page(SimpleNamespace(
            atlas=atlas.evaluate(), cyclones=SimpleNamespace(storms=(), available=False),
            generated=date(2026, 9, 23), run_at="2026-10-01T11:12:00+00:00"))
        self.assertEqual(html.count('<nav class="sitebar"'), 1)
        self.assertIn('<body class="atlaspage">\n' + sitenav.bar("atlas.html")
                      + '\n\n<header class="atlasbar">', html)
        self.assertNotIn("&larr; Dashboard", html)
        # The map and its dossier are the page's main part, a landmark a
        # reader can go to past the menu.
        self.assertEqual(html.count("<main"), 1)
        self.assertIn('\n<main class="atlaswrap">\n', html)


if __name__ == "__main__":
    unittest.main()
