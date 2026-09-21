import unittest
from music_analyzer.domain.catalogue import FileIdentity
from music_analyzer.application.use_cases.scan_library import ScanLibrary, ResolveTrack
from music_analyzer.application.dto.catalogue import Inventory, ScanIssue


class ScanTests(unittest.TestCase):
    def test_identity_is_exact_bytes_not_recording(self):
        a = FileIdentity('a' * 64, 12)
        self.assertEqual(a.track_id, FileIdentity('a' * 64, 12).track_id)
        self.assertNotEqual(a.track_id, FileIdentity('b' * 64, 12).track_id)
        with self.assertRaises(ValueError):
            FileIdentity('invalid', 12)

    def test_partial_inventory_never_marks_missing(self):
        class InventoryPort:
            def inventory(self, root, limits):
                return Inventory(root, (), (ScanIssue(root, 'permission denied'),), False)
        class Repository:
            def register(self, inventory):
                self.received = inventory
                return ()
        repo = Repository()
        result = ScanLibrary(InventoryPort(), repo).execute('/selected')
        self.assertFalse(repo.received.complete)
        self.assertEqual(result.issues[0].detail, 'permission denied')

    def test_resolve_checks_content_and_tries_duplicate_locations(self):
        class Repo:
            def locations(self, track): return ('old', 'copy')
        class Files:
            def matches(self, path, track): return path == 'copy'
        self.assertEqual(ResolveTrack(Repo(), Files()).execute('id').location, 'copy')
        with self.assertRaisesRegex(ValueError, 'scan'):
            ResolveTrack(type('EmptyCatalogue', (), {'locations': lambda s, t: ()})(), Files()).execute('id')
