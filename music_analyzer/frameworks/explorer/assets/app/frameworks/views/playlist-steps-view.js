// The playlist generator's later accordion steps (#234): the preview, then saving, exporting and downloading.

export function playlistGeneratorSteps() {
  return Object.freeze({preview: generatorStep('playlist-step-preview', 'Preview'),
    finish: generatorStep('playlist-step-finish', 'Save, export and download')});
}

function generatorStep(id, title) {
  const step = Object.assign(document.createElement('details'), {id, open: true, className: 'playlist-step'});
  const summary = document.createElement('summary');
  summary.textContent = title;
  step.append(summary);
  return step;
}
