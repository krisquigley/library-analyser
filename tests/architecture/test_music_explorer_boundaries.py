"""Standalone explorer package dependency boundaries."""
import ast
import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2] / 'music_explorer'
ALLOWED_LAYERS = {
    'domain': {'domain'},
    'application': {'domain', 'application'},
    'interface_adapters': {'domain', 'application', 'interface_adapters'},
    'infrastructure': {'domain', 'application', 'interface_adapters', 'infrastructure'},
    'frameworks': {'domain', 'application', 'interface_adapters', 'infrastructure', 'frameworks'},
}
INNER_STDLIB = {'__future__', 'abc', 'dataclasses', 'typing', 'collections', 'enum', 'math', 'hashlib', 'json', 'platform'}
ADAPTER_STDLIB = INNER_STDLIB | {'json'}


def violations(source: str, module: str) -> list[str]:
    layer = module.split('.')[1]
    package = module.rsplit('.', 1)[0]
    errors: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in {'__import__', 'eval', 'exec'}:
            errors.append('dynamic execution/import')
        imports: list[str] = []
        if isinstance(node, ast.Import):
            imports = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ''
            if node.level:
                base = importlib.util.resolve_name('.' * node.level + base, package)
            imports = [base + '.' + alias.name for alias in node.names]
        for name in imports:
            parts = name.split('.')
            if parts[0] == 'music_explorer':
                if len(parts) < 2 or parts[1] not in ALLOWED_LAYERS[layer]:
                    errors.append(name)
            elif parts[0] == 'music_analyzer' and layer in {'domain', 'application'}:
                errors.append(name)
            elif layer in {'domain', 'application'} and parts[0] not in INNER_STDLIB:
                errors.append(name)
            elif layer == 'interface_adapters' and parts[0] not in ADAPTER_STDLIB and parts[0] != 'music_analyzer':
                errors.append(name)
    return errors


class MusicExplorerBoundaryTests(unittest.TestCase):
    def test_layers_exist(self):
        for layer in ALLOWED_LAYERS:
            with self.subTest(layer=layer):
                self.assertTrue((ROOT / layer / '__init__.py').exists())

    def test_production_layers_point_inward(self):
        paths = list(ROOT.rglob('*.py'))
        self.assertTrue(paths)
        for path in paths:
            relative = path.relative_to(ROOT)
            if len(relative.parts) == 1:
                continue
            module = 'music_explorer.' + '.'.join(relative.with_suffix('').parts)
            with self.subTest(path=str(relative)):
                self.assertEqual(violations(path.read_text(encoding='utf-8'), module), [])

    def test_inner_layers_reject_analyzer_and_delivery_details(self):
        for source in (
            'import music_analyzer.application.use_cases.explorer',
            'from music_analyzer.infrastructure.persistence import explorer_readonly',
            'import sqlite3', 'from http.server import BaseHTTPRequestHandler',
            'from importlib import resources', 'import pathlib',
        ):
            with self.subTest(source=source):
                self.assertTrue(violations(source, 'music_explorer.application.use_cases.example'))


if __name__ == '__main__':
    unittest.main()
