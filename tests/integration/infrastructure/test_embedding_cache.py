import tempfile
import unittest
from pathlib import Path
from music_analyzer.application.dto.analysis import DecodedAudio
from music_analyzer.infrastructure.analysis.embedding_cache import FileEmbeddingCache
from music_analyzer.infrastructure.analysis.essentia import EssentiaEngine
from music_analyzer.infrastructure.models.manifest import load_manifest
from tests.integration.infrastructure.test_essentia import Library


class CacheTests(unittest.TestCase):
    def test_atomic_roundtrip_corruption_and_bounds(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = FileEmbeddingCache(directory, max_bytes=2000, max_entry_bytes=1000)
            value = (((0.1, 0.2),),)
            cache.put('a', value)
            self.assertEqual(cache.get('a'), value)
            for path in Path(directory).glob('*.json'):
                path.write_text('broken')
            self.assertIsNone(cache.get('a'))
            cache.put('large', (((1.,) * 1000,),))
            self.assertIsNone(cache.get('large'))
            for i in range(100): cache.put(str(i), value)
            self.assertLessEqual(sum(p.stat().st_size for p in Path(directory).iterdir()), 2000)

    def test_persistent_reuse_invalidation_and_head_compatibility(self):
        with tempfile.TemporaryDirectory() as directory:
            def run(identity='pcm-a', version='v1', checksum='hash', duration=120, stage='genres', head_hash='head', rate=16000):
                reads = []
                manifest = load_manifest()
                manifest['discogs-effnet-bs64-1']['metadata']['inference']['sample_rate'] = rate
                engine = EssentiaEngine(Library(), version, manifest,
                    lambda model: (model, checksum if model == 'discogs-effnet-bs64-1' else head_hash), lambda *args: reads.append(args) or [0.],
                    cache=FileEmbeddingCache(directory))
                result = engine.analyze(stage, DecodedAudio('unused', duration, 44100, identity))
                self.assertTrue(result.raw_predictions)
                self.assertIn(('audio-snapshot-pcm', identity), result.provenance)
                return len(reads)
            self.assertEqual(run(), 3)
            self.assertEqual(run(stage='mood'), 0)
            self.assertEqual(run(head_hash='new-head'), 0)
            self.assertEqual(run(rate=22050), 3)
            self.assertEqual(run(identity='pcm-b'), 3)
            self.assertEqual(run(version='v2'), 3)
            self.assertEqual(run(checksum='changed'), 3)
            self.assertEqual(run(duration=60), 1)
            for p in Path(directory).glob('*.json'): p.write_text('{}')
            self.assertEqual(run(), 3)

    def test_atomic_replace_failure_preserves_prior_entry(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            cache = FileEmbeddingCache(directory)
            cache.put('key', (((.1,),),))
            with patch('music_analyzer.infrastructure.analysis.embedding_cache.os.replace', side_effect=OSError('disk')):
                cache.put('key', (((.9,),),))
            self.assertEqual(cache.get('key'), (((.1,),),))
            self.assertEqual(len(list(Path(directory).iterdir())), 1)

    def test_unverified_audio_never_uses_persistent_cache(self):
        class ForbiddenCache:
            def get(self, key): self.fail()
            def put(self, key, value): self.fail()
        engine = EssentiaEngine(Library(), 'v', load_manifest(), lambda m: (m, 'hash'),
                                lambda *a: [0.], cache=ForbiddenCache())
        self.assertTrue(engine.analyze('genres', DecodedAudio('opaque', 1, 44100)).windows)

    def test_malformed_payload_and_deep_json_are_cache_misses(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = FileEmbeddingCache(directory)
            cache.put('key', (((.1,),),))
            path = next(Path(directory).glob('*.json'))
            for malformed in ('{"payload": 123, "sha256": "x"}', '[' * 1500 + '0' + ']' * 1500):
                path.write_text(malformed)
                self.assertIsNone(cache.get('key'))
