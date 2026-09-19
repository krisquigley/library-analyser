"""Bounded local model bundles, published by an atomic directory rename.

Existing invalid bundles are never silently replaced. Paths are trusted local
configuration, not a security boundary against concurrent hostile filesystem edits.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile

from music_analyzer.application.dto.models import ModelError, ModelResult
from music_analyzer.application.ports.models import ModelTransfer
from music_analyzer.infrastructure.models.manifest import license_text


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


class FileModelStorage:
    def __init__(self, directory: str, manifest: dict, transfer: ModelTransfer):
        self.root = Path(directory)
        self.manifest = manifest
        self.transfer = transfer

    def _entry(self, model_id):
        if model_id not in self.manifest:
            raise ModelError('Unknown model identifier; use the packaged selection.')
        return self.manifest[model_id]

    def _safe(self, path):
        for part in (path, *path.parents):
            if part.is_symlink():
                raise ModelError(f'Symlink model path rejected: {part}')

    def _verify(self, model_id, target):
        entry = self._entry(model_id)
        self._safe(target)
        for name in ('model.pb', 'metadata.json', 'receipt.json', 'LICENSE'):
            path = target / name
            self._safe(path)
            if not path.is_file():
                raise ModelError(f'Missing model asset: {path}; run models download for missing bundles.')
        if (target / 'model.pb').stat().st_size != entry['size']:
            raise ModelError(f'Model size mismatch: {target}')
        checksum = digest(target / 'model.pb')
        expected_receipt = self._receipt(entry, checksum)
        if json.loads((target / 'receipt.json').read_text()) != expected_receipt:
            raise ModelError(f'Integrity/provenance receipt mismatch: {target}')
        if json.loads((target / 'metadata.json').read_text()) != entry['metadata'] or (target / 'LICENSE').read_text() != license_text():
            raise ModelError(f'Metadata or license mismatch: {target}')
        if entry['publisher_sha256'] is not None and checksum != entry['publisher_sha256']:
            raise ModelError(f'Publisher SHA256 mismatch: {target}')
        return ModelResult(model_id, True, 'publisher-sha256' if entry['publisher_sha256'] else 'local-sha256',
                           'Bundle integrity matches; local hashes are not publisher authentication. Inference not tested.')

    def _receipt(self, entry, checksum):
        return {'model_id': entry['id'], 'url': entry['url'], 'size': entry['size'],
                'sha256': checksum, 'publisher_sha256': entry['publisher_sha256'],
                'metadata_url': entry['metadata_url'], 'license_url': entry['license_url'],
                'license_note': entry['license_note']}

    def verify(self, model_id):
        self._entry(model_id)
        try:
            return self._verify(model_id, self.root / model_id)
        except (OSError, ValueError) as error:
            raise ModelError(f'Cannot verify {model_id}: {error}; inspect bundle and retry.') from error

    def install(self, model_id):
        entry = self._entry(model_id)
        temporary = None
        try:
            self._safe(self.root)
            target = self.root / model_id
            self._safe(target)
            if target.exists():
                try:
                    return self.verify(model_id)
                except ModelError as error:
                    raise ModelError(f'{error} Move invalid bundle aside explicitly before downloading again.') from error
            self.root.mkdir(parents=True, exist_ok=True)
            temporary = Path(tempfile.mkdtemp(prefix='.download-', dir=self.root))
            self.transfer.download(entry['url'], str(temporary / 'model.pb'), entry['size'])
            (temporary / 'metadata.json').write_text(json.dumps(entry['metadata'], indent=2) + '\n')
            (temporary / 'LICENSE').write_text(license_text())
            checksum = digest(temporary / 'model.pb')
            (temporary / 'receipt.json').write_text(json.dumps(self._receipt(entry, checksum), indent=2) + '\n')
            result = self._verify(model_id, temporary)
            for path in temporary.iterdir():
                with path.open('rb') as stream:
                    os.fsync(stream.fileno())
            # A competing successful installer leaves a nonempty target: rename fails safely.
            if target.exists():
                raise ModelError('Model bundle appeared during download; retry verification.')
            temporary.rename(target)
            return result
        except (OSError, ValueError) as error:
            raise ModelError(f'Cannot install {model_id}: {error}; check directory and retry.') from error
        finally:
            if temporary is not None and temporary.exists():
                shutil.rmtree(temporary)
