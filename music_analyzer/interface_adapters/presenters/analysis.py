from dataclasses import asdict
import json


def present_analysis(report, as_json=False):
    if as_json:
        return json.dumps(asdict(report), allow_nan=False)
    lines = [f'Run {report.run_id}: {report.status}']
    for result in report.stages:
        lines.append(f'{result.stage}: ' + ', '.join(f'{key}={value}' for key, value in result.values))
        if result.summary:
            summary = result.summary
            lines.append(f'  Section exposure coverage: {summary.coverage:.1%}; provisional raw scores')
            ranked = sorted(zip(summary.labels, summary.mean, summary.minimum, summary.maximum),
                            key=lambda item: item[1], reverse=True)
            for label, mean, low, high in ranked[:10]:
                lines.append(f'  {label}: mean={mean:.4g}, section range={low:.4g}..{high:.4g}')
            if len(ranked) > 10:
                lines.append('  Top 10 displayed (not selected tags); --json retains all scores and windows.')
        lines.append('  ' + result.uncertainty)
        lines.append('  Provenance: ' + ', '.join(f'{key}={value}' for key, value in result.provenance))
    if report.detail:
        lines.append(report.detail)
    return '\n'.join(lines)
