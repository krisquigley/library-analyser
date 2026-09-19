import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from music_analyzer.frameworks.cli.main import build_analysis, build_batch_worker
from music_analyzer.infrastructure.config import load_settings
from music_analyzer.infrastructure.models.manifest import load_manifest
from tests.integration.infrastructure.test_essentia import Library

class CacheWiringTests(unittest.TestCase):
    def test_both_composition_paths_inject_xdg_cache(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = load_settings(environment={'HOME': directory}, database=str(root/'db'))
            with patch.dict('os.environ', {'XDG_CACHE_HOME': str(root/'cache')}), \
                 patch('music_analyzer.frameworks.cli.main.load_backend', return_value=(Library(), 'v', SimpleNamespace(numpy=SimpleNamespace(__version__='fake')))), \
                 patch('music_analyzer.frameworks.cli.main.build_models', return_value=(SimpleNamespace(manifest=load_manifest()), ())), \
                 patch('music_analyzer.frameworks.cli.main.subprocess.run', return_value=SimpleNamespace(stdout='ffmpeg fixture-only version')), \
                 patch('music_analyzer.frameworks.cli.main.load_settings', return_value=settings):
                explicit = build_analysis()
                _, worker = build_batch_worker(settings, 900)
                for usecase in (explicit, worker.__self__):
                    self.assertEqual(usecase._engine.cache.root, root/'cache/music-analyzer/embeddings-v1')
