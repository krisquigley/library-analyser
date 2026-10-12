import unittest

from music_analyzer.application.dto.catalogue import TrackMetadata
from music_analyzer.application.use_cases.metadata_validation import validate_metadata


class MetadataValidationTests(unittest.TestCase):
    def test_accepts_empty_and_text_metadata_without_changing_values(self):
        for metadata in (
            TrackMetadata(),
            TrackMetadata(common=(('title', 'Été 東京'), ('artist', ('One', '東京'))),
                          tags=(('custom:rating', ('5',)),), warnings=('retained warning',)),
            TrackMetadata(common=[['title', 'Song']], tags=[['TITLE', ['Song']]], warnings=['warning']),
        ):
            with self.subTest(metadata=metadata):
                self.assertIsNone(validate_metadata(metadata))

    def test_rejects_boolean_duration_without_coercion(self):
        for seconds in (True, False):
            for source in ('mutagen', 'ffprobe', 'tag', ''):
                with self.subTest(seconds=seconds, source=source):
                    with self.assertRaisesRegex(ValueError, '[Dd]uration.*numeric'):
                        validate_metadata(TrackMetadata(duration_seconds=seconds, duration_source=source))

    def test_duration_validation_preserves_separate_normalization_and_eligibility(self):
        for seconds in (None, 0, -1, 180, 180.5, 1201, float('nan'), float('inf'), -float('inf'), '180'):
            with self.subTest(seconds=seconds):
                metadata = TrackMetadata(duration_seconds=seconds, duration_source='mutagen')
                self.assertIsNone(validate_metadata(metadata))
                self.assertIs(metadata.duration_seconds, seconds)

    def test_rejects_non_pair_collections_and_malformed_common_values(self):
        for common in ({'title': 'Song'}, 'title', None, (('title',),),
                       (('title', 'Song', 'extra'),), ((1, 'Song'),),
                       (('title', 1),), (('artist', ('One', 2)),)):
            with self.subTest(common=common):
                with self.assertRaisesRegex(ValueError, '[Mm]etadata'):
                    validate_metadata(TrackMetadata(common=common))

    def test_rejects_scalar_or_nontext_tag_values_and_malformed_pairs(self):
        for tags in ({'TITLE': ['Song']}, 'TITLE', None, (('TITLE',),),
                     ((1, ('Song',)),), (('TITLE', 'Song'),),
                     (('TITLE', (1,)),), (('TITLE', None),)):
            with self.subTest(tags=tags):
                with self.assertRaisesRegex(ValueError, '[Mm]etadata'):
                    validate_metadata(TrackMetadata(tags=tags))

    def test_rejects_non_collection_or_nontext_warnings(self):
        for warnings in ('warning', {'warning': 'text'}, None, (1,)):
            with self.subTest(warnings=warnings):
                with self.assertRaisesRegex(ValueError, '[Mm]etadata'):
                    validate_metadata(TrackMetadata(warnings=warnings))
