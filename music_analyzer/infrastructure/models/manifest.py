"""Packaged, curated selection only: no user-supplied manifests or URLs."""
import json
import re
from importlib.resources import files
from urllib.parse import urlsplit

from music_analyzer.application.dto.models import ModelError


def official_url(value):
    if not isinstance(value, str):
        return False
    parsed = urlsplit(value)
    return (parsed.scheme == 'https' and parsed.netloc == 'essentia.upf.edu'
            and parsed.path.startswith('/models/') and not parsed.query
            and not parsed.fragment and '%' not in value
            and all(part not in {'.', '..'} for part in parsed.path.split('/')))


def validate_manifest(entries):
    try:
        if not isinstance(entries, list) or not entries:
            raise ValueError('Expected a nonempty model list')
        result = {}
        required = {'id', 'url', 'metadata_url', 'size', 'publisher_sha256',
                    'metadata', 'license_url', 'license_note'}
        for entry in entries:
            if not isinstance(entry, dict) or set(entry) != required:
                raise ValueError('Unexpected manifest fields')
            model_id = entry['id']
            if not isinstance(model_id, str) or not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,100}', model_id):
                raise ValueError('Unsafe model identifier')
            if model_id in result:
                raise ValueError('Duplicate model identifier')
            for field in ('url', 'metadata_url', 'license_url'):
                if not official_url(entry[field]):
                    raise ValueError('Expected an official HTTPS URL')
            if not entry['url'].endswith('/' + model_id + '.pb') or entry['metadata_url'] != entry['url'][:-3] + '.json':
                raise ValueError('Model URLs do not match identifier')
            if type(entry['size']) is not int or not 0 < entry['size'] <= 1_000_000_000:
                raise ValueError('Invalid asset size')
            checksum = entry['publisher_sha256']
            if checksum is not None and (not isinstance(checksum, str) or not re.fullmatch('[0-9a-f]{64}', checksum)):
                raise ValueError('Invalid publisher SHA256')
            metadata = entry['metadata']
            if not isinstance(metadata, dict) or metadata.get('link') != entry['url']:
                raise ValueError('Metadata link mismatch')
            if str(metadata.get('version')) != model_id.rsplit('-', 1)[1]:
                raise ValueError('Metadata version mismatch')
            classes = metadata.get('classes')
            if not isinstance(classes, list) or not classes or not all(isinstance(c, str) and c.strip() for c in classes) or len(classes) != len(set(classes)):
                raise ValueError('Missing or invalid ordered classes')
            if not metadata.get('schema') or not metadata.get('inference') or not metadata.get('author') or not entry['license_note']:
                raise ValueError('Missing inference metadata or attribution')
            result[model_id] = entry
        return result
    except (ValueError, TypeError, KeyError) as error:
        raise ModelError(f'Invalid packaged model manifest: {error}') from error


def load_manifest():
    try:
        return validate_manifest(json.loads(files(__package__).joinpath('data/manifest.json').read_text()))
    except (OSError, ValueError) as error:
        raise ModelError(f'Cannot read packaged model manifest: {error}') from error


def license_text():
    return files(__package__).joinpath('data/LICENSE').read_text()
