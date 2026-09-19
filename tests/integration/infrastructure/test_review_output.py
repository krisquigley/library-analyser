from music_analyzer.interface_adapters.mappers.review import review_to_mapping
import csv
import io
import json
import tempfile
import unittest
from pathlib import Path
from music_analyzer.infrastructure.filesystem.review_output import FileReviewOutput, safe_cell
from music_analyzer.application.dto.review import StoredTrack, ReviewReport


class OutputTests(unittest.TestCase):
    def test_formula_prefixes_quotes_unicode_and_atomic_failure(self):
        for text in ('=1', '+2', '-3', '@SUM(A1)', '\t=1', '\r@x', '\n+2', '  =1'):
            self.assertEqual(safe_cell(text), "'" + text)
        self.assertEqual(safe_cell('été,"'), 'été,"')
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp)/'export.json'; dest.write_text('previous')
            track = StoredTrack('t', 'sha', 1, ('音',), None)
            report = ReviewReport(track, (), (), None, True, ('missing',))
            def broken():
                yield report
                raise ValueError('fixture failure')
            with self.assertRaises(ValueError): FileReviewOutput(review_to_mapping).write(broken(), 'json', str(dest))
            self.assertEqual(dest.read_text(), 'previous')
            self.assertEqual(list(Path(tmp).iterdir()), [dest])
            dest.unlink()
            FileReviewOutput(review_to_mapping).write(iter((report,)), 'json', str(dest))
            self.assertEqual(json.loads(dest.read_text())[0]['track_id'], 't')
            with self.assertRaises(FileExistsError): FileReviewOutput(review_to_mapping).write(iter(()), 'json', str(dest))
