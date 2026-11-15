"""The unknown-track rule for explorer detail belongs to the application layer.

Any ExplorerRepository adapter reports absence through the port (``find_track``
returning ``None``); the use case — not a SQLite adapter — decides that this is
the actionable ``Unknown explorer track`` request failure.
"""
import unittest

from music_analyzer.application.use_cases.explorer import GetExplorerTrackDetail as AnalyzerGetExplorerTrackDetail
from music_explorer.application.use_cases.explorer import GetExplorerTrackDetail as StandaloneGetExplorerTrackDetail


class AbsentTrackRepository:
    """Adapter that knows nothing about the use-case error message."""

    def find_track(self, track_id):
        return None

    def read_track(self, track_id):  # pragma: no cover - detail must use find_track
        raise KeyError(track_id)

    def track_ids(self):  # pragma: no cover - detail must stay keyed
        raise AssertionError('detail must not enumerate active IDs')


class UnknownTrackDetailPolicyTests(unittest.TestCase):
    def test_unknown_detail_is_decided_by_the_use_case(self):
        for name, use_case in (('analyzer', AnalyzerGetExplorerTrackDetail),
                               ('standalone', StandaloneGetExplorerTrackDetail)):
            with self.subTest(package=name):
                with self.assertRaises(ValueError) as raised:
                    use_case(AbsentTrackRepository()).execute('sha256:' + 'f' * 64)
                self.assertEqual(str(raised.exception), 'Unknown explorer track')


if __name__ == '__main__':
    unittest.main()
