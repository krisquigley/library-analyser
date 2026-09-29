from dataclasses import dataclass
import unittest

from music_analyzer.application.dto.catalogue import Inventory, ScanIssue
from music_analyzer.application.use_cases.scan_library import ScanLibrary
from music_analyzer.domain.catalogue import FileIdentity


@dataclass(frozen=True)
class Metadata:
    measured_duration_seconds: float | None = None
    duration_source: str = 'mutagen'
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class File:
    location: str
    identity: FileIdentity
    mtime_ns: int = 1
    format: str = 'flac'
    metadata: Metadata = Metadata()


class Files:
    def __init__(self, inventory):
        self._inventory = inventory

    def inventory(self, root, limits):
        return self._inventory


class Catalogue:
    def __init__(self):
        self.registered = None

    def register(self, inventory):
        self.registered = inventory
        return ('old-location',)


class ScanLibraryDurationPolicyTests(unittest.TestCase):
    def identity(self, char):
        return FileIdentity(char * 64, 1)

    def test_registers_all_identities_and_marks_excluded_in_report_with_warnings(self):
        included = File('/music/exact.flac', self.identity('a'), metadata=Metadata(1200.0, 'mutagen'))
        too_long = File('/music/long.flac', self.identity('b'), metadata=Metadata(1200.1, 'ffprobe'))
        unknown = File('/music/unknown.flac', self.identity('c'), metadata=Metadata(None, 'mutagen'))
        textual_tag = File('/music/textual.flac', self.identity('d'), metadata=Metadata(30.0, 'textual-tag'))
        repo = Catalogue()

        report = ScanLibrary(Files(Inventory('/music', (included, too_long, unknown, textual_tag), (), True)), repo).execute('/music')

        self.assertEqual(tuple(file.location for file in repo.registered.files), ('/music/exact.flac', '/music/long.flac', '/music/unknown.flac', '/music/textual.flac'))
        self.assertTrue(repo.registered.complete, 'scan registers catalogue identities/locations; active views filter eligibility')
        by_location = {file.location: file for file in report.files}
        self.assertEqual(by_location['/music/exact.flac'].metadata.warnings, ())
        self.assertTrue(any('>1200.0s' in warning for warning in by_location['/music/long.flac'].metadata.warnings))
        self.assertTrue(any('duration unverified' in warning for warning in by_location['/music/unknown.flac'].metadata.warnings))
        self.assertTrue(any('duration unverified' in warning for warning in by_location['/music/textual.flac'].metadata.warnings))
        self.assertEqual(report.missing, ('old-location',))

    def test_scan_issues_are_preserved_while_registering_unverified_identity_for_history(self):
        file = File('/music/unreadable.flac', self.identity('e'), metadata=Metadata())
        issue = ScanIssue('/music/secret', 'permission denied')
        repo = Catalogue()

        report = ScanLibrary(Files(Inventory('/music', (file,), (issue,), False)), repo).execute('/music')

        self.assertEqual(tuple(file.location for file in repo.registered.files), ('/music/unreadable.flac',))
        self.assertFalse(repo.registered.complete)
        self.assertEqual(report.issues, (issue,))
        self.assertTrue(report.files[0].metadata.warnings)


if __name__ == '__main__':
    unittest.main()
