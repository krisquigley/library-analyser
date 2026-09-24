import ast
from pathlib import Path
import unittest


class StandaloneExplorerHttpBoundaryTests(unittest.TestCase):
    def test_server_does_not_import_private_projection_artifact_builder(self):
        tree = ast.parse(Path('music_exporer/frameworks/explorer/server.py').read_text())
        private_imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == 'music_exporer.application.use_cases.projection_artifacts':
                private_imports.extend(alias.name for alias in node.names if alias.name.startswith('_'))
        self.assertNotIn('_build_artifact', private_imports)


if __name__ == '__main__':
    unittest.main()
