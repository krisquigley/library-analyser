"""Enforce static dependencies, including relative imports and nested imports.

Inner layers have a small explicit stdlib allowlist. This deliberately fails
closed when new dependencies appear; extending it requires boundary review.
Dynamic importing is forbidden outside infrastructure (except the entry point
which only statically imports its composition root).
"""
import ast
import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2] / 'music_analyzer'
ALLOWED_LAYERS = {
    'domain': {'domain'},
    'application': {'domain', 'application'},
    'interface_adapters': {'domain', 'application', 'interface_adapters'},
    'infrastructure': {'domain', 'application', 'infrastructure'},
    'frameworks': {'domain', 'application', 'interface_adapters', 'infrastructure', 'frameworks'},
}
INNER_STDLIB = {'__future__', 'dataclasses', 'typing', 'collections', 'enum', 'abc'}


def violations(source, module):
    layer = module.split('.')[1]
    package = module.rsplit('.', 1)[0]
    errors = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in {'__import__', 'eval', 'exec'}:
            errors.append('dynamic execution/import')
        imports = []
        if isinstance(node, ast.Import):
            imports = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ''
            if node.level:
                base = importlib.util.resolve_name('.' * node.level + base, package)
            imports = [base + '.' + alias.name for alias in node.names]
        for name in imports:
            parts = name.split('.')
            if parts[0] == 'music_analyzer':
                if len(parts) < 2 or parts[1] not in ALLOWED_LAYERS[layer]:
                    errors.append(name)
            elif layer in {'domain', 'application'} and parts[0] not in INNER_STDLIB:
                errors.append(name)
            elif layer == 'interface_adapters' and parts[0] not in {'json', 'dataclasses', 'typing', '__future__'}:
                errors.append(name)
    return errors


class ImportBoundaryTests(unittest.TestCase):
    def test_production_layers_point_inward(self):
        paths = list(ROOT.rglob('*.py'))
        self.assertTrue(paths)
        for path in paths:
            relative = path.relative_to(ROOT)
            if len(relative.parts) == 1:
                continue  # package marker and executable composition-root delegate
            module = 'music_analyzer.' + '.'.join(relative.with_suffix('').parts)
            with self.subTest(path=str(relative)):
                self.assertEqual(violations(path.read_text(), module), [])

    def test_checker_rejects_absolute_relative_external_and_dynamic_leaks(self):
        for source in (
            'import music_analyzer.infrastructure.environment.probes',
            'from ...infrastructure.environment import probes',
            'from ... import infrastructure',
            'import sqlite3', 'import pathlib', 'import argparse', 'import essentia',
            'import importlib', '__import__("essentia")',
            'def hidden():\n    import subprocess',
        ):
            with self.subTest(source=source):
                self.assertTrue(violations(source, 'music_analyzer.application.use_cases.example'))

    def test_checker_allows_inward_and_relative_dto_imports(self):
        self.assertEqual(violations('from ..dto.doctor import CheckResult',
                                   'music_analyzer.application.use_cases.example'), [])
