"""The Dependency Rule for the Explorer browser app's ES modules (#146).

`music_explorer/frameworks/explorer/assets/app/` is laid out by layer. A module
may import only from its own layer or an inner one, by a relative `.js` path
that stays inside `app/`. Anything the checker cannot classify fails closed:
an unknown layer, a bare or absolute specifier, a dynamic `import()`, or an
import form the test bundle cannot flatten. The legacy `app.js`, which is
moving into the layers, may import any layer, as `main/` may.
"""
from pathlib import Path, PurePosixPath
import re
import unittest

REPO_ROOT = Path(__file__).resolve().parents[2]
ASSETS = REPO_ROOT / 'music_explorer/frameworks/explorer/assets'
APP = ASSETS / 'app'

ALLOWED_LAYERS = {
    'domain': {'domain'},
    'application': {'domain', 'application'},
    'adapters': {'domain', 'application', 'adapters'},
    'frameworks': {'domain', 'application', 'adapters', 'frameworks'},
    'main': {'domain', 'application', 'adapters', 'frameworks', 'main'},
}
_STATIC_IMPORT = re.compile(r'^\s*import\s*(?P<clause>[^;]*?)\s*from\s*[\'"](?P<specifier>[^\'"]+)[\'"]', re.M | re.S)
_SIDE_EFFECT_IMPORT = re.compile(r'^\s*import\s*[\'"]', re.M)
_ANY_IMPORT = re.compile(r'^\s*import\b', re.M)
_DYNAMIC_IMPORT = re.compile(r'(?<![\w$.])import\s*\(')
_RE_EXPORT = re.compile(r'^\s*export\s*(?:\*|\{[^}]*\})\s*from\b', re.M)
_NAMED_CLAUSE = re.compile(r'^\{\s*[\w$]+(?:\s*,\s*[\w$]+)*\s*,?\s*\}$', re.S)


def violations(source: str, module: str) -> list[str]:
    """Problems with `module` (a path relative to `app/`, or 'app.js' for the legacy entry)."""
    module_path = PurePosixPath(module)
    layer = 'main' if module == 'app.js' else module_path.parts[0]
    if layer not in ALLOWED_LAYERS:
        return [f'{module}: unknown layer {layer!r}']
    errors = []
    if _DYNAMIC_IMPORT.search(source):
        errors.append(f'{module}: dynamic import()')
    if _SIDE_EFFECT_IMPORT.search(source) or _RE_EXPORT.search(source):
        errors.append(f'{module}: side-effect imports and re-exports are not allowed')
    imports = list(_STATIC_IMPORT.finditer(source))
    if len(imports) != len(_ANY_IMPORT.findall(source)):
        errors.append(f'{module}: an import that is not `import {{…}} from \'…\'`')
    base = PurePosixPath('app') if module == 'app.js' else PurePosixPath(module).parent
    for match in imports:
        errors.extend(_import_violations(module, layer, base, match))
    return errors


def _import_violations(module, layer, base, match):
    specifier = match.group('specifier')
    if not _NAMED_CLAUSE.match(match.group('clause')):
        return [f'{module}: {specifier}: only named imports without renaming']
    if not specifier.startswith(('./', '../')) or not specifier.endswith('.js'):
        return [f'{module}: {specifier}: must be a relative .js path']
    target = _normalise(base / specifier) if module != 'app.js' else _normalise(PurePosixPath(specifier))
    if target is None or (module == 'app.js' and target.parts[:1] != ('app',)):
        return [f'{module}: {specifier}: leaves app/']
    target_layer = target.parts[1] if module == 'app.js' else target.parts[0]
    if target_layer not in ALLOWED_LAYERS[layer]:
        return [f'{module}: {layer} may not import {target_layer} ({specifier})']
    return []


def _normalise(path):
    parts = []
    for part in path.parts:
        if part == '..':
            if not parts:
                return None
            parts.pop()
        elif part != '.':
            parts.append(part)
    return PurePosixPath(*parts) if parts else None


class ExplorerAppBoundaryRuleTests(unittest.TestCase):
    def test_inward_imports_are_allowed(self):
        cases = [
            ('domain/playlist-recipe.js', "import {LEVELS} from './energy.js';"),
            ('application/download-playlist/download.js', "import {playlistRecipe} from '../../domain/playlist-recipe.js';"),
            ('adapters/gateways/query.js', "import {\n  playlistRecipe,\n} from '../../domain/playlist-recipe.js';"),
            ('frameworks/views/panel.js', "import {query} from '../../adapters/gateways/query.js';"),
            ('main/start.js', "import {panel} from '../frameworks/views/panel.js';"),
            ('app.js', "import {query} from './app/adapters/gateways/query.js';"),
        ]
        for module, source in cases:
            with self.subTest(module=module):
                self.assertEqual([], violations(source, module))

    def test_outward_imports_are_rejected(self):
        cases = [
            ('domain/recipe.js', "import {x} from '../application/use.js';"),
            ('application/use/use.js', "import {x} from '../../adapters/gateways/api.js';"),
            ('adapters/presenters/p.js', "import {x} from '../../frameworks/views/v.js';"),
            ('frameworks/views/v.js', "import {x} from '../../main/start.js';"),
        ]
        for module, source in cases:
            with self.subTest(module=module):
                self.assertEqual(1, len(violations(source, module)))

    def test_what_cannot_be_classified_fails_closed(self):
        cases = [
            ('widgets/w.js', ''),
            ('domain/a.js', "import {x} from 'three';"),
            ('domain/a.js', "import {x} from '/app/domain/b.js';"),
            ('domain/a.js', "import {x} from '../../vendor/x.js';"),
            ('domain/a.js', "import {x as y} from './b.js';"),
            ('domain/a.js', "import x from './b.js';"),
            ('domain/a.js', "import * as x from './b.js';"),
            ('domain/a.js', "import './b.js';"),
            ('domain/a.js', "export {x} from './b.js';"),
            ('domain/a.js', "const b = await import('./b.js');"),
            ('app.js', "import {x} from './vendor/x.js';"),
        ]
        for module, source in cases:
            with self.subTest(module=module, source=source):
                self.assertTrue(violations(source, module))


class ExplorerAppBoundaryTests(unittest.TestCase):
    def test_the_layers_exist(self):
        for layer in ALLOWED_LAYERS:
            with self.subTest(layer=layer):
                self.assertTrue((APP / layer).is_dir(), f'app/{layer}/ is missing')

    def test_every_module_respects_the_dependency_rule(self):
        modules = {'app.js': ASSETS / 'app.js'}
        modules.update({path.relative_to(APP).as_posix(): path for path in APP.rglob('*.js')})
        errors = [error for module, path in sorted(modules.items())
                  for error in violations(path.read_text(encoding='utf-8'), module)]
        self.assertEqual([], errors)

    def test_only_javascript_modules_live_in_the_app_tree(self):
        others = [path.relative_to(APP).as_posix() for path in APP.rglob('*')
                  if path.is_file() and path.suffix != '.js' and path.name not in ('.gitkeep', 'package.json')]
        self.assertEqual([], others)


if __name__ == '__main__':
    unittest.main()
