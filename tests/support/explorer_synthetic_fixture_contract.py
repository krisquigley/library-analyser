"""Shared RED seam only: never synthesizes a database or graph itself.

Only the absent future outward fixture module gets an availability fallback.
Import errors within an implemented module propagate. Missing behavior is an
assertion failure before fixture I/O, never a skip or fabricated generator.
"""
import importlib


try:
    fixture_tool = importlib.import_module('tools.explorer_synthetic_fixture')
except ModuleNotFoundError as error:
    if error.name != 'tools.explorer_synthetic_fixture':
        raise
    fixture_tool = None


def public_fixture(test_case, **options):
    factory = getattr(fixture_tool, 'public_synthetic_fixture', None)
    test_case.assertTrue(
        callable(factory),
        'Missing public_synthetic_fixture behavior for ' + test_case.id(),
    )
    return factory(**options)
