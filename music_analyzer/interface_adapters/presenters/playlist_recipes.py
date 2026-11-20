"""Words and JSON for the playlist recipe commands (#139)."""
import json

LIST_HEADER = 'NAME\tSTART_TRACK\tUPDATED\tPROBLEM'


def present_recipe_saved(event) -> str:
    return f'{"Replaced" if event.replaced else "Saved"} playlist recipe "{event.name}"'


def present_recipe_deleted(event) -> str:
    return f'Deleted playlist recipe "{event.name}"'


def present_recipe_list(summaries, as_json=False) -> str:
    if as_json:
        return json.dumps([{'name': summary.name, 'start_track_id': summary.start_track_id,
                            'updated_at': summary.updated_at, 'problem': summary.problem} for summary in summaries],
                          ensure_ascii=False)
    rows = [f'{summary.name}\t{summary.start_track_id or ""}\t{summary.updated_at}\t{summary.problem or ""}'
            for summary in summaries]
    return '\n'.join([LIST_HEADER, *rows])


def present_saved_recipe(saved) -> str:
    """The recipe alone, so that what `show` prints can be saved back."""
    return json.dumps(saved.document, ensure_ascii=False, indent=2)
