import json
from dataclasses import asdict

from music_analyzer.application.dto.models import ModelReport


def present_models(report: ModelReport, *, as_json: bool) -> str:
    if as_json:
        return json.dumps({**asdict(report), 'ready': report.ready}, ensure_ascii=False, indent=2)
    lines = ['Model integrity ready: ' + ('yes' if report.ready else 'no'), 'Inference validated: no']
    for model in report.models:
        lines.append(f'{"OK" if model.available else "FAIL"} {model.model_id} [{model.integrity}]: {model.detail}')
    return '\n'.join(lines)
