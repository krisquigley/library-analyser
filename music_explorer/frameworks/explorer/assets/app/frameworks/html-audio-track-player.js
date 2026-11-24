// The track player over an HTML audio element (#258). The element's own controls are the seek bar; what the element
// does is reported for the track it was given, and nothing is reported once it is stopped.

const UNPLAYABLE = 'the file is missing or in a format this browser cannot play';

export function htmlAudioTrackPlayer({audio, audioUrl, onReport}) {
  let trackId = null;
  const report = (kind, message) => {
    if (trackId !== null) onReport(message === undefined ? {kind, trackId} : {kind, trackId, message});
  };
  audio.onplaying = () => report('playing');
  audio.onpause = () => { if (!audio.ended) report('paused'); };
  audio.onended = () => report('ended');
  audio.onerror = () => report('failed', UNPLAYABLE);

  function play() {
    const playing = trackId;
    Promise.resolve(audio.play()).catch(error => {
      // A newer load or a pause interrupts a play that has not started; that is no failure.
      if (error?.name !== 'AbortError' && playing === trackId) report('failed', error?.message || UNPLAYABLE);
    });
  }

  function load(requested) {
    trackId = requested;
    audio.src = audioUrl(requested);
    play();
  }

  function stop() {
    trackId = null;
    audio.pause();
    audio.removeAttribute('src');
    audio.load();
  }

  return Object.freeze({load, pause: () => audio.pause(), resume: play, stop});
}
