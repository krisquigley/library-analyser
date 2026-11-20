"""Expressions that read a real Explorer page through its opt-in diagnostics seam (#146), for Playwright tests.

Open the page with ``diagnostics_url`` so the seam is installed; never read the page's own variables.
"""
from tools.explorer_browser_routes import diagnostics_url  # noqa: F401  (re-exported for the browser tests)

SEAM = 'window.explorerDiagnostics'
SNAPSHOT = SEAM + '.snapshot()'
GRAPH = SEAM + '.graph()'
SCENE = SEAM + '.scene()'


def snapshot_is(condition):
    """A page predicate on the snapshot, written over ``s``: ``snapshot_is("s.graphStatus==='ready'")``."""
    return f'(s=>{condition})({SNAPSHOT})'
