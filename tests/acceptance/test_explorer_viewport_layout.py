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
        for element in ('tracks', 'detail', 'undo', 'reset', 'controls',
                        'mood-strip', 'mood-strip-picker', 'mood-strip-value'):
            self.assertIn('overlay', html.ancestors[element][2], element)
        # #233: a header bar opens the tools; the Library is a drawer, the others are centred modal dialogs.
        for tool in ('library', 'filters', 'playlist', 'tag-write'):
            self.assertEqual(html.tags[f'{tool}-panel'], 'dialog', tool)
            self.assertEqual(html.tags[f'open-{tool}'], 'button', tool)
            self.assertIn('app-bar', html.ancestors[f'open-{tool}'], tool)
        for tool in ('playlist', 'tag-write'):
            self.assertIn(f'{tool}-panel', html.ancestors[f'close-{tool}'], tool)
        self.assertIn('library-panel', html.ancestors['tracks'])
        self.assertIn('filters-panel', html.ancestors['controls'])
        self.assertIn('tag-write-panel', html.ancestors['tag-write'])
        self.assertIn('app-bar', html.ancestors['graph-load-status'], 'a graph failure and its retry stay in view')
        self.assertIn('playlist-panel', html.ancestors['playlist-controls'])
        self.assertEqual(html.tags['detail-panel'], 'section', 'the selected track stays in view beside the graph')
        self.assertNotIn('candidates', html.tags, 'no numbered candidate list below the controls')
        css = (ASSETS / 'style.css').read_text()
        self.assertIn('position:fixed', css)
        self.assertIn('100dvh', css)
        self.assertIn('pointer-events:none', css)
        self.assertIn('pointer-events:auto', css)
        self.assertNotIn('grid-template-columns', css)
        self.assertIn('::backdrop', css)


    def test_the_header_stays_reachable_on_a_phone(self):
        """#245: on a narrow screen the graph status squeezed the header until its tool buttons fell under the drawer."""
        css = (ASSETS / 'style.css').read_text()
        self.assertIn('.app-bar .graph-load-status button{', css)
        self.assertIn('white-space:nowrap', css[css.index('.app-bar .graph-load-status button{'):].split('}')[0])
        narrow = css[css.index('@media(max-width:560px){'):]
        narrow = narrow[:narrow.index('\n}\n')]
        self.assertIn('.app-bar{flex-wrap:wrap', narrow, 'the tools take their own row')
        self.assertIn('.app-tools{width:100%', narrow)
        self.assertIn('--app-bar-height:', narrow, 'panels start below the taller header')


if __name__ == '__main__':
    unittest.main()
