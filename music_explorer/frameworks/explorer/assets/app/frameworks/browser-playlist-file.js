// The PlaylistFile port in the browser (#146): offers the playlist as a download.

export function browserPlaylistFile() {
  return Object.freeze({
    save({filename, contents, contentType}) {
      const url = URL.createObjectURL(new Blob([contents], {type: contentType}));
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = filename;
      try {
        if (document.body?.append) document.body.append(anchor);
        anchor.click();
      } finally {
        anchor.remove?.();
        URL.revokeObjectURL(url);
      }
    },
  });
}
