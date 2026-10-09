"""Search use-case boundary controls; matching is a repository responsibility."""
import unittest

from music_explorer.application.dto.explorer import ExplorerTrackSummary
from music_explorer.application.use_cases.explorer import ListExplorerTrackSummaries


class SummaryRepositorySpy:
    def __init__(self):
        self.calls = []
        self.rows = (ExplorerTrackSummary('sha256:' + 'a' * 64, 'Straße', 'Artist', 'file.flac', 1),)

    def list_track_summaries(self, limit, cursor=None, query='', order='title'):
        self.calls.append((limit, cursor, query, order))
        return {'application_id': 0x4D414E41, 'schema_version': 6,
                'read_policy': 'bounded_read_transaction'}, 2, self.rows, 'next-page'


class ExplorerSummarySearchApplicationContractTests(unittest.TestCase):
    def test_combined_literal_query_reaches_port_without_query_language_translation(self):
        repository = SummaryRepositorySpy()
        query = 'Straße\t Artist  100%_\\mix'
        page = ListExplorerTrackSummaries(repository).execute(
            limit=1, cursor='previous-page', query='  ' + query + '  ', order='artist')
        self.assertEqual(repository.calls, [(1, 'previous-page', query, 'artist')])
        self.assertEqual(page.query, query)
        self.assertEqual(page.tracks, repository.rows)
        self.assertEqual(page.metadata.track_count, 2)
        self.assertEqual(page.next_cursor, 'next-page')

    def test_blank_api_query_preserves_bounded_unfiltered_port_call(self):
        for query in ('', ' \t\n ', None):
            with self.subTest(query=query):
                repository = SummaryRepositorySpy()
                page = ListExplorerTrackSummaries(repository).execute(query=query)
                self.assertEqual(repository.calls, [(100, None, '', 'title')])
                self.assertEqual(page.query, '')

    def test_invalid_bounds_and_order_are_rejected_before_repository_io(self):
        for arguments in ({'limit': 0}, {'limit': 101}, {'query': 'x' * 201},
                          {'order': 'title; DROP TABLE tracks'}):
            with self.subTest(arguments=arguments):
                repository = SummaryRepositorySpy()
                with self.assertRaises(ValueError):
                    ListExplorerTrackSummaries(repository).execute(**arguments)
                self.assertEqual(repository.calls, [])

    def test_maximum_query_length_and_page_size_remain_accepted(self):
        repository = SummaryRepositorySpy()
        ListExplorerTrackSummaries(repository).execute(limit=100, query='x' * 200, order='id')
        self.assertEqual(repository.calls, [(100, None, 'x' * 200, 'id')])


if __name__ == '__main__':
    unittest.main()
