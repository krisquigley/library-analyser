// The mood strip (#146): every visible track with a score for the selected mood, placed at its raw score.
// Tracks without that score have no mark; the score is never rescaled.

export function moodStripMarks(nodes, selectedId) {
  return nodes.filter(node => node.moodScore != null)
    .map(node => ({id: node.id, label: node.label, moodLabel: node.moodScore.label, score: node.moodScore.raw,
      position: node.moodScore.raw, selected: node.id === selectedId}))
    .sort(lowestScoreFirst);
}

function lowestScoreFirst(a, b) {
  return a.score - b.score || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0);
}
