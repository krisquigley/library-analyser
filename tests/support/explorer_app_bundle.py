"""Test-only bridge from the Explorer browser app's ES modules to one classic script (#146).

The browser loads `app.js` as an ES module and follows its imports. Many
acceptance tests instead evaluate the app as a single classic script in a Node
`vm` context and reach into its top-level names. Until each feature has moved
into the layered modules (and its tests with it), this bundle keeps them running
against the same code: every imported module, in dependency order, then the
entry, with the import and export syntax removed and strict mode on, as in a module.

It flattens only the module syntax the app uses: named imports without renaming,
from relative `.js` paths, and exports declared inline. Anything else is
rejected, as is a top-level name declared by two modules, exported or not, which would collide once flat.
"""
from functools import lru_cache
from pathlib import Path
import re
import tempfile

_IMPORT = re.compile(r'^import\s*(?P<clause>[^;]*?)\s*from\s*(?P<quote>[\'"])(?P<specifier>[^\'"]+)(?P=quote)\s*;?[ \t]*\n?',
                     re.M | re.S)
_ANY_IMPORT = re.compile(r'^\s*import\b', re.M)
_NAMED_CLAUSE = re.compile(r'^\{\s*[\w$]+(?:\s*,\s*[\w$]+)*\s*,?\s*\}$', re.S)
_INLINE_EXPORT = re.compile(r'^export\s+(?=(?:async\s+)?function\b|const\b|let\b|class\b)', re.M)
_ANY_EXPORT = re.compile(r'^\s*export\b', re.M)
# A declaration at the start of a line is top level: the app's modules indent everything nested.
_TOP_LEVEL_NAME = re.compile(r'^(?:export\s+)?(?:async\s+)?(?:function\*?|const|let|var|class)\s+([\w$]+)', re.M)


class ExplorerAppBundleError(ValueError):
    pass


def bundle_explorer_app(entry: Path) -> str:
    entry = Path(entry).resolve()
    ordered = []
    _visit(entry, ordered, visiting=set())
    sources = {path: path.read_text(encoding='utf-8') for path in ordered}
    _reject_colliding_names(sources)
    return "'use strict';\n" + ''.join(_flatten(sources[path], path) for path in ordered)


@lru_cache(maxsize=None)
def explorer_app_script(entry: Path) -> Path:
    """The bundle written to a temporary file, for tests that pass a script path to Node.

    The other assets beside the entry (the vendored graph library, index.html,
    style.css) are linked into the same directory, as tests find them by path.
    The directory is named for the package, so a subtest still says which copy ran.
    """
    entry = Path(entry).resolve()
    if not entry.is_file():
        # The browser gate runs these modules against an installed wheel, without the source
        # tree; its own tests never evaluate the app, so only an import must not fail.
        return entry
    package = entry.parents[3].name
    directory = Path(tempfile.mkdtemp(prefix=f'explorer-app-{package}-'))
    for sibling in entry.parent.iterdir():
        if sibling.name not in (entry.name, 'app', '__pycache__'):
            (directory / sibling.name).symlink_to(sibling)
    bundle = directory / entry.name
    bundle.write_text(bundle_explorer_app(entry), encoding='utf-8')
    return bundle


def _visit(path, ordered, visiting):
    if path in ordered:
        return
    if path in visiting:
        raise ExplorerAppBundleError(f'Import cycle through {path.name}')
    visiting.add(path)
    for specifier in _specifiers(path.read_text(encoding='utf-8'), path):
        _visit((path.parent / specifier).resolve(), ordered, visiting)
    visiting.discard(path)
    ordered.append(path)


def _specifiers(source, path):
    imports = list(_IMPORT.finditer(source))
    if len(imports) != len(_ANY_IMPORT.findall(source)):
        raise ExplorerAppBundleError(f'{path.name}: an import must be `import {{…}} from \'./….js\';`')
    for match in imports:
        if not _NAMED_CLAUSE.match(match.group('clause')):
            raise ExplorerAppBundleError(f'{path.name}: only named imports without renaming can be bundled')
        specifier = match.group('specifier')
        if not specifier.startswith(('./', '../')) or not specifier.endswith('.js'):
            raise ExplorerAppBundleError(f'{path.name}: import {specifier!r} must be a relative .js path')
        yield specifier


def _flatten(source, path):
    stripped = _INLINE_EXPORT.sub('', _IMPORT.sub('', source))
    if _ANY_EXPORT.search(stripped):
        raise ExplorerAppBundleError(f'{path.name}: only inline exports (`export function …`) can be bundled')
    return stripped


def _reject_colliding_names(sources):
    declared_in = {}
    for path, source in sources.items():
        for name in dict.fromkeys(_TOP_LEVEL_NAME.findall(source)):
            if name in declared_in:
                raise ExplorerAppBundleError(
                    f"'{name}' is declared in both {declared_in[name].name} and {path.name}; the bundle would collide")
            declared_in[name] = path
