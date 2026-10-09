"""Deterministic flow contract for non-blocking library status/error banners.

This is a DOM/CSS regression, not a browser geometry test. A status card in
normal flow in the existing scrollable tracks panel cannot paint over search
or the independently positioned detail dock when a 503 message wraps.
"""
import re
import unittest
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class BannerElements(HTMLParser):
    def __init__(self):
        super().__init__()
        self.stack = []
        self.parents = {}
        self.order = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        identifier = attrs.get('id')
        if identifier:
            self.parents[identifier] = list(self.stack)
            self.order.append(identifier)
        if tag not in ('meta', 'link', 'input', 'br', 'img'):
            self.stack.append(identifier or tag)

    def handle_endtag(self, tag):
        if self.stack:
            self.stack.pop()


def declarations(css, selector):
    """Read successive declarations for an exact (non-media) selector."""
    result = {}
    for match in re.finditer(re.escape(selector) + r'\{([^{}]*)\}', css):
        for declaration in match.group(1).split(';'):
            if ':' in declaration:
                key, value = declaration.split(':', 1)
                result[key.strip()] = value.strip()
    return result


class ExplorerBannerLayoutTests(unittest.TestCase):
    def test_refresh_and_503_card_follow_search_in_scrollable_panel(self):
        for package in ('music_analyzer', 'music_explorer'):
            with self.subTest(package=package):
                assets = ROOT / package / 'frameworks/explorer/assets'
                elements = BannerElements()
                elements.feed((assets / 'index.html').read_text())
                self.assertIn('tracks-panel', elements.parents['loading-surface'])
                self.assertLess(elements.order.index('track-search'),
                                elements.order.index('loading-surface'))
                self.assertLess(elements.order.index('loading-surface'),
                                elements.order.index('tracks'))
                css = (assets / 'style.css').read_text()
                refresh = declarations(css, '.loading-surface.refresh')
                self.assertEqual(refresh.get('position'), 'static')
                # Preserve the generic [hidden] display rule; a later refresh
                # display declaration of equal specificity would override it.
                self.assertNotIn('display', refresh)
                self.assertEqual(declarations(css, '.loading-surface[hidden]').get('display'),
                                 'none')
                self.assertEqual(refresh.get('padding'), '0')
                self.assertEqual(refresh.get('pointer-events'), 'none')
                card = declarations(css, '.loading-surface.refresh .loading-card')
                self.assertEqual(card.get('width'), '100%')
                self.assertEqual(declarations(css, '.panel').get('overflow'), 'auto')
                self.assertIn('style="pointer-events:auto"',
                              (assets / 'index.html').read_text())


if __name__ == '__main__':
    unittest.main()
