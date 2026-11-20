"""Issue #146: the test-only bridge from the browser app's ES modules to one classic script."""
import tempfile
import unittest
from pathlib import Path

from tests.support.explorer_app_bundle import ExplorerAppBundleError, bundle_explorer_app, explorer_app_script


def _write(root, files):
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')


class ExplorerAppBundleTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def test_a_script_without_imports_is_kept_and_made_strict(self):
        _write(self.root, {'app.js': 'let state = {};\nfunction start(){}\n'})

        self.assertEqual("'use strict';\nlet state = {};\nfunction start(){}\n", bundle_explorer_app(self.root / 'app.js'))

    def test_modules_come_before_their_importers_without_import_or_export_syntax(self):
        _write(self.root, {
            'app.js': "import {playlistQuery} from './app/adapters/query.js';\nplaylistQuery();\n",
            'app/adapters/query.js': "import {recipe} from '../domain/recipe.js';\nexport function playlistQuery(){ return recipe(); }\n",
            'app/domain/recipe.js': 'export const DEFAULT = 1;\nexport function recipe(){ return DEFAULT; }\n',
        })

        self.assertEqual("'use strict';\n"
                         'const DEFAULT = 1;\nfunction recipe(){ return DEFAULT; }\n'
                         'function playlistQuery(){ return recipe(); }\n'
                         'playlistQuery();\n', bundle_explorer_app(self.root / 'app.js'))

    def test_a_module_imported_twice_is_included_once(self):
        _write(self.root, {
            'app.js': "import {a} from './app/domain/a.js';\nimport {b} from './app/domain/b.js';\n",
            'app/domain/a.js': "import {c} from './c.js';\nexport function a(){ return c; }\n",
            'app/domain/b.js': "import {c} from './c.js';\nexport function b(){ return c; }\n",
            'app/domain/c.js': 'export const c = 3;\n',
        })

        self.assertEqual(1, bundle_explorer_app(self.root / 'app.js').count('const c = 3;'))

    def test_a_multi_line_import_is_removed(self):
        _write(self.root, {
            'app.js': "import {\n  a,\n  b,\n} from './app/domain/ab.js';\na(); b();\n",
            'app/domain/ab.js': 'export function a(){}\nexport function b(){}\n',
        })

        self.assertTrue(bundle_explorer_app(self.root / 'app.js').endswith('a(); b();\n'))

    def test_syntax_the_bundle_cannot_flatten_is_rejected(self):
        cases = {
            'a renamed import': "import {a as b} from './app/domain/a.js';\n",
            'a default import': "import a from './app/domain/a.js';\n",
            'a namespace import': "import * as a from './app/domain/a.js';\n",
            'a bare specifier': "import {a} from 'three';\n",
        }
        _write(self.root, {'app/domain/a.js': 'export function a(){}\n'})
        for name, entry in cases.items():
            with self.subTest(name):
                _write(self.root, {'app.js': entry})
                with self.assertRaises(ExplorerAppBundleError):
                    bundle_explorer_app(self.root / 'app.js')

    def test_export_forms_other_than_inline_declarations_are_rejected(self):
        for source in ('export default function a(){}\n', 'function a(){}\nexport {a};\n'):
            with self.subTest(source):
                _write(self.root, {'app.js': "import {a} from './app/domain/a.js';\n", 'app/domain/a.js': source})
                with self.assertRaises(ExplorerAppBundleError):
                    bundle_explorer_app(self.root / 'app.js')

    def test_two_modules_declaring_the_same_top_level_name_are_rejected(self):
        _write(self.root, {
            'app.js': "import {a} from './app/domain/a.js';\nfunction a(){}\n",
            'app/domain/a.js': 'export function a(){}\n',
        })

        with self.assertRaisesRegex(ExplorerAppBundleError, "'a'"):
            bundle_explorer_app(self.root / 'app.js')

    def test_two_modules_with_the_same_private_top_level_name_are_rejected(self):
        # Flattened, the later declaration would silently replace the earlier one.
        _write(self.root, {
            'app.js': "import {view} from './app/frameworks/view.js';\nimport {present} from './app/adapters/present.js';\n",
            'app/frameworks/view.js': 'function status(text){ return text; }\nexport function view(){ return status; }\n',
            'app/adapters/present.js': 'async function status({state}){ return state; }\nexport function present(){ return status; }\n',
        })

        with self.assertRaisesRegex(ExplorerAppBundleError, "'status' is declared in both"):
            bundle_explorer_app(self.root / 'app.js')

    def test_names_declared_inside_functions_may_repeat(self):
        _write(self.root, {
            'app.js': "import {a} from './app/domain/a.js';\nfunction b(){ const text = 2; return text; }\n",
            'app/domain/a.js': 'export function a(){\n  const text = 1;\n  return text;\n}\n',
        })

        self.assertIn('const text = 1;', bundle_explorer_app(self.root / 'app.js'))

    def test_an_import_cycle_is_rejected(self):
        _write(self.root, {
            'app.js': "import {a} from './app/domain/a.js';\n",
            'app/domain/a.js': "import {b} from './b.js';\nexport function a(){}\n",
            'app/domain/b.js': "import {a} from './a.js';\nexport function b(){}\n",
        })

        with self.assertRaisesRegex(ExplorerAppBundleError, 'cycle'):
            bundle_explorer_app(self.root / 'app.js')


    def test_the_bundle_file_sits_beside_links_to_the_other_assets_in_a_directory_named_for_the_package(self):
        assets = self.root / 'music_explorer/frameworks/explorer/assets'
        _write(assets, {'app/main/main.js': "import {a} from '../domain/a.js';\na();\n", 'index.html': '<html></html>',
                        'vendor/lib.js': 'lib();\n', 'app/domain/a.js': 'export function a(){}\n'})

        bundle = explorer_app_script(assets / 'app/main/main.js')

        self.assertTrue(bundle.parent.name.startswith('explorer-app-music_explorer-'))
        self.assertEqual("'use strict';\nfunction a(){}\na();\n", bundle.read_text(encoding='utf-8'))
        self.assertEqual('lib();\n', (bundle.parent / 'vendor/lib.js').read_text(encoding='utf-8'))
        self.assertTrue((bundle.parent / 'index.html').is_file())
        self.assertFalse((bundle.parent / 'app').exists())


    def test_a_missing_entry_is_returned_unchanged_for_the_caller_to_fail_on(self):
        missing = self.root / 'music_explorer/frameworks/explorer/assets/app.js'

        self.assertEqual(missing.resolve(), explorer_app_script(missing))


if __name__ == '__main__':
    unittest.main()
