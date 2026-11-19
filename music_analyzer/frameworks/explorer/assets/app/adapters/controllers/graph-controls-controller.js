// The mood tracker and graph filter controls' input (#146): validated, then handed to the load-graph use case.

import {GRAPH_CONTROLS_EDIT} from '../../application/load-graph/graph-controls-edit-schema.js';
import {RequestSchemaError, validRequest} from './request-schema.js';

export function graphControlsController({graphLoad, rejectInput}) {
  function validControls(request) {
    try {
      return validRequest(GRAPH_CONTROLS_EDIT, request);
    } catch (error) {
      if (!(error instanceof RequestSchemaError)) throw error;
      rejectInput(error.message);
      return null;
    }
  }

  function filtersEdited(changes) {
    graphLoad.editControls(changes);
    return graphLoad.applyFilters();
  }

  return Object.freeze({
    async moodChosen(mood) {
      if (validControls({mood})) await graphLoad.chooseMood(mood);
    },
    bpmRangeEdited(range) {
      const valid = validControls(range);
      return valid ? filtersEdited({bpmMin: bpmBound(valid.bpmMin), bpmMax: bpmBound(valid.bpmMax)}) : false;
    },
    genresEdited(genres) {
      return validControls({genres}) ? filtersEdited({genres: [...genres]}) : false;
    },
    filtersCleared() {
      return graphLoad.clearFilters();
    },
  });
}

function bpmBound(text) {
  return text.trim() === '' ? null : Number(text);
}
