"""Readable review projection; full evidence remains in JSON/CSV exports."""
from music_analyzer.domain.review import FIELDS


MARKDOWN_HEADER = '''# Music library review

Genres, moods and instruments show the top 5 labelled mean scores (descending,
label order breaks ties), not probabilities or confirmed tags. Other labels and
full windows/ranges/raw predictions remain in JSON/CSV exports. Scores are rounded
to 6 significant digits here. Energy is provisional raw valence/arousal, not a DJ
energy scale. Manual annotations take precedence, but do not remove uncertainty.
Coverage describes sampled audio only; unsampled audio may differ.

'''


def escape_text(value):
    """Keep untrusted metadata inline, inert, and Unicode-readable."""
    result = []
    for char in str(value):
        code = ord(char)
        if char in '\r\n\t' or code in (0x85, 0x2028, 0x2029):
            result.append(' ')
        elif code < 32 or 0x7f <= code <= 0x9f or code in (0x200e, 0x200f, 0x061c) or 0x202a <= code <= 0x202e or 0x2066 <= code <= 0x2069:
            result.append('[U+%04X]' % code)
        elif char in '&<>|':
            result.append({'&': '&amp;', '<': '&lt;', '>': '&gt;', '|': '&#124;'}[char])
        elif char in '\\`*_{}[]()#+-.!':
            result.append('\\' + char)
        else:
            result.append(char)
    return ''.join(result)


def display_value(value):
    if isinstance(value, (float, int)):
        return format(value, '.6g')
    return escape_text(value)


def markdown_track(report):
    track, run = report.track, report.track.run
    filename = track.locations[0].rsplit('/', 1)[-1] if track.locations else 'Unknown file'
    lines = ['## ' + escape_text(filename), '',
             '- Track ID: ' + escape_text(track.track_id),
             '- SHA256: ' + escape_text(track.sha256),
             '- Size: ' + str(track.size) + ' bytes']
    lines.extend('- Location: ' + escape_text(path) for path in track.locations)
    if not track.locations:
        lines.append('- Location: missing')
    lines.append('- Run: ' + (escape_text(run.run_id) + ' — ' + escape_text(run.status) if run else 'missing'))
    if run and run.detail:
        lines.append('- Run detail: ' + escape_text(run.detail))
    lines.append('- Needs review: ' + ('yes' if report.needs_review else 'no'))
    lines.extend(['', '### Effective results', ''])
    effective, manual = dict(report.effective), dict(track.overrides)
    names = {'bpm': 'BPM', 'key': 'Key', 'genres': 'Genres', 'mood': 'Moods',
             'instruments': 'Instruments', 'energy': 'Energy'}
    for field in FIELDS:
        value = effective.get(field)
        source = 'manual override' if field in manual else 'automatic/provisional'
        suffix = ''
        if value is None:
            rendered = 'missing / no selection'
        elif isinstance(value, str):
            rendered = escape_text(value)
        else:
            pairs = list(value)
            if field in ('genres', 'mood', 'instruments'):
                pairs = sorted(pairs, key=lambda pair: -pair[1])[:5]
                suffix = f'; top {len(pairs)} of {len(value)}'
            rendered = '; '.join(escape_text(label) + ': ' + display_value(score) for label, score in pairs)
        lines.append(f'- {names[field]} ({source}{suffix}): {rendered}')
        if field == 'energy' and field not in manual:
            lines.append('  Provisional raw valence/arousal; not a DJ energy scale.')
    lines.extend(['', '### Evidence and caveats', ''])
    for stage in run.stages if run else ():
        parts = []
        if stage.summary:
            parts.append(f'sampled coverage {stage.summary.coverage:.1%}; {len(stage.windows)} window(s)')
            parts.append('provisional' if stage.summary.provisional else 'not marked provisional')
            if stage.summary.uncertainty:
                parts.append(escape_text(stage.summary.uncertainty))
        else:
            parts.append('sampled coverage unavailable')
        if stage.uncertainty:
            parts.append(escape_text(stage.uncertainty))
        parts.append('provenance: ' + ('; '.join(escape_text(k) + '=' + escape_text(v)
            for k, v in stage.provenance) or 'unavailable'))
        lines.append('- ' + escape_text(stage.stage) + ': ' + '; '.join(parts))
    lines.extend('- Review: ' + escape_text(reason) for reason in report.reasons)
    if not report.reasons and not (run and run.stages):
        lines.append('- No retained evidence.')
    return '\n'.join(lines) + '\n\n'
