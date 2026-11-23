// The Export recipe button and its status in the page (#139).

export function playlistRecipeExportView({onExportRequested}) {
  let status = null;

  function mount(panel) {
    const button = Object.assign(document.createElement('button'),
      {id: 'export-playlist-recipe', type: 'button', textContent: 'Export recipe',
        title: 'Download the drafted playlist as a recipe file, to save with music-analyzer playlist-recipe save'});
    button.onclick = () => onExportRequested();
    status = Object.assign(document.createElement('p'), {id: 'playlist-recipe-export-status', className: 'muted'});
    show({status: {text: '', urgent: false}});
    const section = Object.assign(document.createElement('section'), {id: 'playlist-recipe-export'});
    section.append(button, status);
    panel.append(section);
  }

  function show({status: {text, urgent}}) {
    if (!status) return;
    status.setAttribute('role', urgent ? 'alert' : 'status');
    status.setAttribute('aria-live', urgent ? 'assertive' : 'polite');
    status.textContent = text;
  }

  return Object.freeze({mount, show});
}
