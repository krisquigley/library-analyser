"""Streaming UTF-8 exports, atomic no-clobber publication in destination directory."""
import csv
import json
import os
from pathlib import Path
import tempfile
from music_analyzer.domain.review import FIELDS


def safe_cell(value):
    text = str(value)
    if text.startswith(('\t', '\r', '\n')) or text.lstrip().startswith(('=', '+', '-', '@')):
        return "'" + text
    return text


class FileReviewOutput:
    def __init__(self, mapper):
        self.mapper = mapper

    def write(self, reports, format, destination):
        if format not in ('json', 'csv'): raise ValueError('Unsupported export format')
        target = Path(destination).absolute()
        if any(p.is_symlink() for p in (target, *target.parents)):
            raise ValueError('Refusing symlink export path')
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='',
                    prefix='.export-', dir=target.parent, delete=False) as stream:
                temporary = Path(stream.name)
                if format == 'json':
                    stream.write('[')
                    separator = ''
                    for report in reports:
                        stream.write(separator)
                        json.dump(self.mapper(report), stream, ensure_ascii=False, allow_nan=False)
                        separator = ',\n'
                    stream.write(']\n')
                else:
                    writer = csv.writer(stream)
                    writer.writerow(['track_id', 'sha256', 'size', 'locations', 'needs_review',
                                     *('override_' + f for f in FIELDS), 'record'])
                    for report in reports:
                        record = self.mapper(report)
                        writer.writerow([safe_cell(report.track.track_id), safe_cell(report.track.sha256),
                            report.track.size, safe_cell('\n'.join(report.track.locations)), report.needs_review,
                            *(safe_cell(dict(report.track.overrides).get(f, '')) for f in FIELDS),
                            safe_cell(json.dumps(record, ensure_ascii=False, allow_nan=False))])
                stream.flush()
                os.fsync(stream.fileno())
            # Never overwrite any existing file (including analysis DB or music).
            os.link(temporary, target)
        finally:
            if temporary is not None: temporary.unlink(missing_ok=True)
