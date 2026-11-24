"""#232: the Explorer's look comes from one set of design tokens, and every control is styled for the dark theme."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STYLESHEETS = [ROOT / package / 'frameworks/explorer/assets/style.css' for package in ('music_explorer', 'music_analyzer')]
LITERAL_COLOUR = re.compile(r'#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(')


def outside_tokens(css):
    """The stylesheet without comments, its :root token block or inline SVG data (whose colours are URL-encoded)."""
    css = re.sub(r'/\*.*?\*/', '', css, flags=re.S)
    css = re.sub(r':root\{[^}]*\}', '', css, count=1)
    return re.sub(r'url\("data:[^"]*"\)', 'url()', css)


class DesignTokenTests(unittest.TestCase):
    def test_colours_are_declared_once_as_tokens(self):
        for stylesheet in STYLESHEETS:
            with self.subTest(stylesheet=stylesheet.parent.parent.parent.parent.name):
                css = stylesheet.read_text()
                self.assertIn(':root{', css)
                literals = sorted(set(match.group(0) for match in LITERAL_COLOUR.finditer(outside_tokens(css))))
                self.assertEqual(literals, [], 'colour literals outside :root')

    def test_every_control_is_styled_for_the_dark_theme(self):
        css = STYLESHEETS[0].read_text()
        for selector in ('button{', 'button:disabled{', 'select:not([multiple]){', 'input[type=checkbox],input[type=radio],input[type=range]{',
                         'th{', 'td{', 'legend{', 'summary::before{'):
            self.assertIn(selector, css)
        self.assertIn('color-scheme:dark', css)
        self.assertIn('@media(prefers-reduced-motion:reduce)', css)
        self.assertIn('box-shadow:var(--focus-ring)', css)


if __name__ == '__main__':
    unittest.main()
