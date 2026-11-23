// The page's one 3D graph (#146): created on first use and set up once, with the axes it shows and its frame loop.
// It holds the vendored graph instance, a detail, so the composition root keeps no mutable binding for it.

export function createForceGraphStage({create}) {
  let graph = null;
  let axisSpec = [];
  let framesStarted = false;

  return Object.freeze({
    current: () => graph,
    shows: candidate => graph !== null && candidate === graph,
    ensure(element, setUp) {
      if (!graph) {
        graph = create(element);
        setUp(graph);
      }
      return graph;
    },
    stageAxes(spec) { axisSpec = spec; },
    axisSpec: () => axisSpec,
    startFrames(requestFrame, onFrame) {
      if (framesStarted) return;
      framesStarted = true;
      requestFrame(onFrame);
    },
  });
}
