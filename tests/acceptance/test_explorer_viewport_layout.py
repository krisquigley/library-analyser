"""Viewport delivery contract for the browser explorer (not graph policy)."""
import unittest
from html.parser import HTMLParser
from pathlib import Path

ASSETS = Path(__file__).resolve().parents[2] / 'music_analyzer/frameworks/explorer/assets'


class Elements(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parents = []
        self.ancestors = {}
        self.tags = {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if 'id' in attrs:
            self.ancestors[attrs['id']] = list(self.parents)
            self.tags[attrs['id']] = tag
        if tag not in ('meta', 'link', 'input', 'br', 'img'):
            self.parents.append(attrs.get('id', attrs.get('class', tag)))

    def handle_endtag(self, tag):
        if self.parents:
            self.parents.pop()


class ExplorerViewportLayoutTests(unittest.TestCase):
    def test_graph_is_root_viewport_layer_and_every_control_has_overlay_home(self):
        html = Elements()
        html.feed((ASSETS / 'index.html').read_text())
        self.assertIn('graph-viewport', html.ancestors['map'])
        for element in ('tracks', 'detail', 'undo', 'reset', 'controls', 'candidates',
                        'graph-info', 'mood-strip', 'mood-strip-picker', 'mood-strip-value'):
            self.assertIn('overlay', html.ancestors[element][2], element)
        for element in ('tracks-panel', 'candidate-panel', 'detail-panel'):
            self.assertEqual(html.tags[element], 'details')
        css = (ASSETS / 'style.css').read_text()
        self.assertIn('position:fixed', css)
        self.assertIn('100dvh', css)
        self.assertIn('pointer-events:none', css)
        self.assertIn('pointer-events:auto', css)
        self.assertNotIn('grid-template-columns', css)


if __name__ == '__main__':
    unittest.main()
