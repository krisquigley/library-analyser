import {createPlaylistDownload} from '../application/download-playlist/download-playlist.js';
import {PLAYLIST_DOWNLOAD_EVENT_TYPES} from '../application/download-playlist/playlist-download-events.js';
import {createPlaylistPreview} from '../application/preview-playlist/preview-playlist.js';
import {PLAYLIST_PREVIEW_EVENT_TYPES} from '../application/preview-playlist/playlist-preview-events.js';
import {playlistPreviewController} from '../adapters/controllers/playlist-preview-controller.js';
import {playlistPreviewViewModel, playlistReadinessViewModel, presentPlaylistPreviewEvent} from '../adapters/presenters/playlist-preview-presenter.js';
import {playlistPreviewView} from '../frameworks/views/playlist-preview-view.js';
import {createTrackPlayback} from '../application/listen-to-track/listen-to-track.js';
import {TRACK_PLAYBACK_EVENT_TYPES, TRACK_PLAYBACK_STATE_EVENT_TYPES} from '../application/listen-to-track/track-playback-events.js';
import {trackAudioUrl} from '../adapters/gateways/track-audio-url.js';
import {presentTrackPlaybackEvent, presentTrackPlaybackProgress} from '../adapters/presenters/track-playback-presenter.js';
import {htmlAudioTrackPlayer} from '../frameworks/html-audio-track-player.js';
import {EMPTY_PLAYLIST_DRAFT} from '../domain/playlist-draft.js';
import {createPlaylistRecipeExport} from '../application/export-playlist-recipe/export-playlist-recipe.js';
import {PLAYLIST_RECIPE_EXPORT_EVENT_TYPES} from '../application/export-playlist-recipe/playlist-recipe-export-events.js';
import {playlistRecipeExportController} from '../adapters/controllers/playlist-recipe-export-controller.js';
import {presentPlaylistRecipeExportEvent} from '../adapters/presenters/playlist-recipe-export-presenter.js';
import {playlistRecipeExportView} from '../frameworks/views/playlist-recipe-export-view.js';
import {createSavedRecipeLoad} from '../application/load-saved-recipe/load-saved-recipe.js';
import {SAVED_RECIPE_EVENT_TYPES} from '../application/load-saved-recipe/saved-recipe-events.js';
import {savedRecipeController} from '../adapters/controllers/saved-recipe-controller.js';
import {presentRejectedSavedRecipeInput, presentSavedRecipeEvent, savedRecipesViewModel} from '../adapters/presenters/saved-recipe-presenter.js';
import {savedRecipeView} from '../frameworks/views/saved-recipe-view.js';
import {createTagWrite} from '../application/write-tags/write-tags.js';
import {TAG_WRITE_EVENT_TYPES} from '../application/write-tags/tag-write-events.js';
import {tagWriteController} from '../adapters/controllers/tag-write-controller.js';
import {presentRejectedTagWriteInput, presentTagWriteEvent, tagWriteViewModel} from '../adapters/presenters/tag-write-presenter.js';
import {tagWriteView} from '../frameworks/views/tag-write-view.js';
import {createToolPanels} from '../application/open-tool-panel/open-tool-panel.js';
import {TOOL_PANEL_EVENT_TYPES} from '../application/open-tool-panel/tool-panel-events.js';
import {toolPanelController} from '../adapters/controllers/tool-panel-controller.js';
import {toolPanelViewModel} from '../adapters/presenters/tool-panel-presenter.js';
import {toolPanelsView} from '../frameworks/views/tool-panels-view.js';
import {playlistGeneratorSteps} from '../frameworks/views/playlist-steps-view.js';
import {createNeighbourhoodLabels} from '../application/label-neighbourhood/label-neighbourhood.js';
import {NEIGHBOURHOOD_LABEL_EVENT_TYPES} from '../application/label-neighbourhood/neighbourhood-label-events.js';
import {trackLabelViewModels} from '../adapters/presenters/track-label-presenter.js';
import {createTrackLabels} from '../frameworks/graph-scene/track-labels.js';
import {playlistDownloadController} from '../adapters/controllers/playlist-download-controller.js';
import {fetchExplorerApi} from '../adapters/gateways/explorer-api-gateway.js';
import {libraryArousalRangeViewModel,playlistControlsViewModel, presentLoadedPlaylistDraft, presentPlaylistDownloadEvent, presentRejectedPlaylistInput} from '../adapters/presenters/playlist-download-presenter.js';
import {browserPlaylistFile} from '../frameworks/browser-playlist-file.js';
import {createLinkLabels} from '../frameworks/graph-scene/link-labels.js';
import {browserHandBuiltPlaylistStore} from '../frameworks/browser-hand-built-playlist-store.js';
import {handBuiltPlaylistView} from '../frameworks/views/hand-built-playlist-view.js';
import {playlistJourneyView} from '../frameworks/views/playlist-journey-view.js';
import {playlistJourneyViewModel} from '../adapters/presenters/playlist-journey-presenter.js';
import {createHandBuiltPlaylist} from '../application/build-playlist/build-playlist.js';
import {HAND_BUILT_PLAYLIST_EVENT_TYPES} from '../application/build-playlist/hand-built-playlist-events.js';
import {handBuiltPlaylistViewModel, presentHandBuiltPlaylistDownload} from '../adapters/presenters/hand-built-playlist-presenter.js';
import {createInMemoryEventBus} from '../frameworks/in-memory-event-bus.js';
import {createGraphRendering} from '../application/render-graph/render-graph.js';
import {forceGraphRenderer, graphViewPose, observeGraphInput} from '../frameworks/graph-scene/force-graph-rendering.js';
import {createSelectedNodeHalo, findSceneObject, graphObjectTrackId} from '../frameworks/graph-scene/selected-node-halo.js';
import {neighbourhoodFocusDistance,animateCameraArc, createCameraControlsWatch} from '../frameworks/graph-scene/camera-focus-scene.js';
import {jumpCameraToPickedNode, mountedPickedNode, pickedTrackId} from '../frameworks/graph-scene/graph-pick.js';
import {configureForceGraph, createGraphDataMount, createGraphFraming, drawCanvasFallback, fitGraphToElement, graphContainer, observeElementResize, selectedTrackNodeSize} from '../frameworks/graph-scene/force-graph-scene.js';
import {playlistDownloadView} from '../frameworks/views/playlist-download-view.js';
import {EMPTY_GRAPH_CONTROLS} from '../domain/graph-filters.js';
import {libraryArousalRange,moodGraphModel,trackBpmsOf} from '../domain/mood-graph.js';
import {isIndexedMoodAxisGraph, normalizeMoodAxisGraphDto} from '../adapters/gateways/mood-axis-graph-dto.js';
import {createGraphLoad} from '../application/load-graph/load-graph.js';
import {graphControlsController} from '../adapters/controllers/graph-controls-controller.js';
import {GRAPH_IDLE_STATUS, graphControlOptionsViewModel, graphControlValuesViewModel, presentGraphLoadEvent} from '../adapters/presenters/graph-load-presenter.js';
import {graphControlsView} from '../frameworks/views/graph-controls-view.js';
import {graphStatusView} from '../frameworks/views/graph-status-view.js';
import {createTrackSearch} from '../application/search-tracks/search-tracks.js';
import {TRACK_SEARCH_EVENT_TYPES} from '../application/search-tracks/track-search-events.js';
import {emptyTrackResults} from '../domain/track-search.js';
import {trackListViewModel,trackBpmBadges} from '../adapters/presenters/track-list-presenter.js';
import {trackListView} from '../frameworks/views/track-list-view.js';
import {detailFieldViewModel, trackDetailFailureViewModel, trackDetailLoadingViewModel, trackDetailViewModel, trackMetadataViewModel} from '../adapters/presenters/track-detail-presenter.js';
import {trackDetailView} from '../frameworks/views/track-detail-view.js';
import {sessionSelectionTickets} from '../frameworks/session-selection-tickets.js';
import {awaitingServer} from '../domain/track-selection.js';
import {createTrackSelection} from '../application/select-track/select-track.js';
import {moodStripMarks} from '../domain/mood-strip.js';
import {moodStripViewModel} from '../adapters/presenters/mood-strip-presenter.js';
import {moodStripView} from '../frameworks/views/mood-strip-view.js';
import {selectionLinkLabels,graphNeighbourPositions,focusedLinkColor,focusedLinkWidth,relatednessLinkWidth, focusedNodeColor, graphAxisSpec, graphNeighbourFocus, linkLabel, nodeLabel, relatednessLinkColor} from '../adapters/presenters/graph-scene-presenter.js';
import {cameraViewDirection, selectionFocusPose} from '../domain/camera-arc.js';
import {createCameraFocus} from '../application/focus-camera/focus-camera.js';
import {CAMERA_FOCUS_EVENT_TYPES} from '../application/focus-camera/camera-focus-events.js';
import {TRACK_SELECTION_EVENT_TYPES} from '../application/select-track/track-selection-events.js';
import {GRAPH_LOAD_EVENT_TYPES} from '../application/load-graph/graph-load-events.js';
import {GRAPH_RENDERING_EVENT_TYPES} from '../application/render-graph/render-graph-events.js';
import {installExplorerDiagnostics} from '../frameworks/explorer-diagnostics.js';
import {createInMemorySession} from '../frameworks/in-memory-session.js';
import {createGraphAxes} from '../frameworks/graph-scene/graph-axes.js';
import {createForceGraphStage} from '../frameworks/graph-scene/force-graph-stage.js';
import {createLibraryRefresh} from '../application/refresh-library/refresh-library.js';
import {LIBRARY_REFRESH_EVENT_TYPES} from '../application/refresh-library/library-refresh-events.js';
import {presentLibraryRefreshEvent} from '../adapters/presenters/library-loading-presenter.js';
import {libraryLoadingView} from '../frameworks/views/library-loading-view.js';
const graphStage=createForceGraphStage({create:elem=>configureForceGraph(ForceGraph3D()(elem),{nodeLabel,linkLabel,linkColor:relatednessLinkColor,linkWidth:relatednessLinkWidth,nodeValue:selectedNodeValue,onNodeClick:selectGraphNode})});
const graphAxes=createGraphAxes();
const nodeHalo=createSelectedNodeHalo();
const graphDataMount=createGraphDataMount({onReplaced:()=>nodeHalo.clear()});
// A new layout is framed at once; cancelling first keeps a focus arc from overwriting the frame.
const graphFraming=createGraphFraming({onReframe:()=>cancelCameraFocus('graph-reframed')});
const playlistEvents=createInMemoryEventBus();
const explorerApi=fetchExplorerApi((path,options)=>fetch(path,options));
const labelEvents=createInMemoryEventBus();
const neighbourhoodLabels=createNeighbourhoodLabels({explorerApi,eventBus:labelEvents});
const trackLabels=createTrackLabels({onPlayRequested:trackId=>trackPlayback.toggle(trackId),onSeekRequested:(trackId,seconds)=>trackPlayback.seek(trackId,seconds),onAddRequested:trackId=>handBuiltPlaylist.add({selectedTrackId:currentTrackId(),neighbourId:trackId}).catch(()=>{})});
// #278: the playlist built by hand from the labels' + buttons, kept in this browser and shown in the strip over the graph.
const handBuiltEvents=createInMemoryEventBus();
const handBuiltPlaylist=createHandBuiltPlaylist({store:browserHandBuiltPlaylistStore(browserLocalStorage()),explorerApi,playlistFile:browserPlaylistFile(),eventBus:handBuiltEvents});
const handBuiltStrip=handBuiltPlaylistView({onRemoveRequested:trackId=>handBuiltPlaylist.remove(trackId).catch(()=>{}),onClearRequested:()=>handBuiltPlaylist.clear().catch(()=>{}),onDownloadRequested:()=>handBuiltPlaylist.download(),onPlayRequested:trackId=>trackPlayback.toggle(trackId),onChooseRequested:trackId=>handBuiltPlaylist.choose(trackId),onMoveRequested:(trackId,places)=>handBuiltPlaylist.move(trackId,places).catch(()=>{})});
const playlistJourneyChart=playlistJourneyView();
handBuiltEvents.subscribe('hand-built-playlist-changed',event=>{handBuiltStrip.show(handBuiltPlaylistViewModel(event)); playlistJourneyChart.show(playlistJourneyViewModel(event)); trackLabels.showPlaylist(event.trackIds);});
handBuiltEvents.subscribe('hand-built-playlist-track-chosen',event=>selectGraphNode({id:event.trackId}));
for(const type of ['hand-built-playlist-download-started','hand-built-playlist-downloaded','hand-built-playlist-download-failed']) handBuiltEvents.subscribe(type,event=>handBuiltStrip.showDownload(presentHandBuiltPlaylistDownload(event)));
function browserLocalStorage(){try{return globalThis.localStorage??null;}catch{return null;}}
const linkLabels=createLinkLabels();
function showLinkLabels(viewModels){const host=typeof document!=='undefined'&&document.getElementById('graph3d'); if(host) linkLabels.show(host,viewModels);}
function showTrackLabels(viewModels){const host=typeof document!=='undefined'&&document.getElementById('graph3d'); if(host) trackLabels.show(host,viewModels);}
labelEvents.subscribe('neighbourhood-labelled',event=>{showTrackLabels(trackLabelViewModels(event)); graphRendering.wake();});
for(const type of ['neighbourhood-labelling','neighbourhood-labels-failed','neighbourhood-labels-cleared']) labelEvents.subscribe(type,()=>showTrackLabels([]));
const playlistDraftSession=createInMemorySession({draft:EMPTY_PLAYLIST_DRAFT});
const playlistDownload=createPlaylistDownload({explorerApi,playlistFile:browserPlaylistFile(),playlistDraft:playlistDraftSession,eventBus:playlistEvents});
const playlistControls=playlistDownloadController({playlistDownload,currentTrackId,rejectInput:message=>playlistControlsView.show(presentRejectedPlaylistInput(message))});
const playlistControlsView=playlistDownloadView({onControlsEdited:controls=>playlistControls.controlsEdited(controls),onDownloadRequested:controls=>playlistControls.downloadRequested(controls),onArcAdded:()=>playlistControls.arcAdded(),onArcRemoved:place=>playlistControls.arcRemoved(place),onArcMoved:(place,offset)=>playlistControls.arcMoved(place,offset),onArcEdited:(place,fields)=>playlistControls.arcEdited(place,fields)});
for(const type of PLAYLIST_DOWNLOAD_EVENT_TYPES) playlistEvents.subscribe(type,event=>playlistControlsView.show(presentPlaylistDownloadEvent(event)));
const playlistPreview=createPlaylistPreview({explorerApi,playlistDraft:playlistDraftSession,eventBus:playlistEvents});
const playlistPreviewControls=playlistPreviewController({playlistPreview,currentTrackId});
// #258: one track plays at a time from the preview's rows, in one audio player whose own controls seek.
const playbackEvents=createInMemoryEventBus();
const trackPlayerElement=typeof document!=='undefined'?document.createElement('audio'):{play(){},pause(){},load(){},removeAttribute(){}};
const trackPlayback=createTrackPlayback({trackPlayer:htmlAudioTrackPlayer({audio:trackPlayerElement,audioUrl:trackAudioUrl,onReport:report=>trackPlayback.heard(report)}),eventBus:playbackEvents});
const playlistPreviewPanel=playlistPreviewView({onPreviewRequested:()=>playlistPreviewControls.previewRequested(),onPlayRequested:trackId=>trackPlayback.toggle(trackId),player:trackPlayerElement});
playbackEvents.subscribe('track-playback-progressed',event=>trackLabels.showProgress(presentTrackPlaybackProgress(event)));
for(const type of TRACK_PLAYBACK_STATE_EVENT_TYPES) playbackEvents.subscribe(type,event=>{const update=presentTrackPlaybackEvent(event); playlistPreviewPanel.showPlayback(update); handBuiltStrip.showPlayback(update); trackLabels.showPlayback(update);});
for(const type of PLAYLIST_PREVIEW_EVENT_TYPES) playlistEvents.subscribe(type,event=>playlistPreviewPanel.show(presentPlaylistPreviewEvent(event)));
// #234: Preview waits, saying why, until the recipe is complete; checked on every draft edit and change of track.
function showPlaylistReadiness(){const readiness=playlistReadinessViewModel(playlistPreview.gaps(currentTrackId())); playlistPreviewPanel.show(readiness); playlistControlsView.show(readiness);}
for(const type of ['playlist-draft-edited','saved-recipe-loaded']) playlistEvents.subscribe(type,showPlaylistReadiness);
const playlistRecipeExport=createPlaylistRecipeExport({playlistDraft:playlistDraftSession,playlistFile:browserPlaylistFile(),eventBus:playlistEvents});
const recipeExportControls=playlistRecipeExportController({playlistRecipeExport,currentTrackId});
const recipeExportPanel=playlistRecipeExportView({onExportRequested:()=>recipeExportControls.exportRequested()});
for(const type of PLAYLIST_RECIPE_EXPORT_EVENT_TYPES) playlistEvents.subscribe(type,event=>recipeExportPanel.show(presentPlaylistRecipeExportEvent(event)));
const savedRecipes=createSavedRecipeLoad({explorerApi,playlistDraft:playlistDraftSession,eventBus:playlistEvents});
const savedRecipeControls=savedRecipeController({savedRecipes,rejectInput:message=>savedRecipePanel.show(presentRejectedSavedRecipeInput(message))});
const savedRecipePanel=savedRecipeView({onListRequested:()=>savedRecipeControls.listRequested(),onLoadRequested:name=>savedRecipeControls.loadRequested(name)});
for(const type of SAVED_RECIPE_EVENT_TYPES) playlistEvents.subscribe(type,event=>savedRecipePanel.show(presentSavedRecipeEvent(event)));
playlistEvents.subscribe('saved-recipe-loaded',event=>playlistControlsView.show(presentLoadedPlaylistDraft(event.draft)));
// A loaded recipe starts from its own track (owner decision A, #139): it becomes the current track.
playlistEvents.subscribe('saved-recipe-loaded',event=>setCurrent(event.startTrackId));
// Tags are written only after the listener previews and approves that one action (#132).
const toolPanelEvents=createInMemoryEventBus();
const toolPanels=createToolPanels({eventBus:toolPanelEvents});
const toolPanelControls=toolPanelController({toolPanels,rejectInput:message=>globalThis.console?.warn(message)});
const toolPanelDisplay=toolPanelsView({onToggleRequested:tool=>toolPanelControls.toggleRequested(tool),onCloseRequested:tool=>toolPanelControls.closeRequested(tool),onOpenRequested:tool=>toolPanelControls.openRequested(tool)});
for(const type of TOOL_PANEL_EVENT_TYPES) toolPanelEvents.subscribe(type,event=>toolPanelDisplay.show(toolPanelViewModel(event)));
// Closing the Playlist silences the track playing from its preview (#258).
toolPanelEvents.subscribe('tool-panel-closed',event=>{if(event.tool==='playlist') trackPlayback.stop();});
const tagWriteEvents=createInMemoryEventBus();
const tagWrite=createTagWrite({explorerApi,eventBus:tagWriteEvents});
const tagWriteControls=tagWriteController({tagWrite,currentTrackId,rejectInput:message=>tagWritePanel.show(presentRejectedTagWriteInput(message))});
const tagWritePanel=tagWriteView({onPreviewRequested:(policy,target)=>tagWriteControls.previewRequested(policy,target),onApplyRequested:()=>tagWriteControls.applyRequested()});
for(const type of TAG_WRITE_EVENT_TYPES) tagWriteEvents.subscribe(type,event=>tagWritePanel.show(presentTagWriteEvent(event)));
// The latest playlist preview is what "Previewed playlist" tags; a new or failed preview withdraws it first.
playlistEvents.subscribe('playlist-previewed',event=>tagWriteControls.playlistPreviewed(event.preview.tracks));
for(const type of ['playlist-preview-started','playlist-preview-failed']) playlistEvents.subscribe(type,()=>tagWriteControls.playlistPreviewCleared());
const selectionTickets=sessionSelectionTickets({storage:tabSessionStorage(),now:()=>Date.now(),random:()=>Math.random()});
const cameraFocusSession=createInMemorySession({pendingTrackId:null,frame:null,viewIntent:0,selectionViewIntent:0,focusGeneration:0});
// Render on demand (#86): the vendor loop would otherwise redraw WebGL every frame, even when nothing moves.
const renderingEvents=createInMemoryEventBus();
const graphRendering=createGraphRendering({renderer:forceGraphRenderer(graphStage.current),eventBus:renderingEvents});
const cameraEvents=createInMemoryEventBus();
const cameraFocus=createCameraFocus({focusSession:cameraFocusSession,eventBus:cameraEvents});
const cameraControlsWatch=createCameraControlsWatch({onControlsReplaced:()=>cancelCameraFocus('controls-replaced'),onViewClaimed:()=>cameraFocus.claimView('listener-orbit')});
cameraEvents.subscribe('camera-focus-cancelled',event=>{if(typeof cancelAnimationFrame==='function') cancelAnimationFrame(event.frame);});
const graphSession=createInMemorySession({loadState:'idle',controls:EMPTY_GRAPH_CONTROLS,
  model:{nodes:[],links:[],unpositioned:[],availableMoods:[],selectedMood:'',metadata:{},genreOptions:[]},visible:{nodes:[],links:[],unpositioned:[]}});
function graphState(){return graphSession.read();}
const graphEvents=createInMemoryEventBus();
const graphLoad=createGraphLoad({explorerApi,graphSession,clock:{nextFrame:()=>nextFrame()},eventBus:graphEvents,buildGraphModel:buildMoodGraphModel});
const graphControls=graphControlsController({graphLoad,rejectInput:message=>graphFilterControls.showRejection(message)});
const graphFilterControls=graphControlsView({onMoodChosen:mood=>graphControls.moodChosen(mood),onBpmRangeEdited:range=>graphControls.bpmRangeEdited(range),onGenresEdited:genres=>graphControls.genresEdited(genres),onFiltersCleared:()=>graphControls.filtersCleared()});
const graphStatusDisplay=graphStatusView({onReload:()=>loadGraph().catch(()=>{}),appendPlaylistControls:panel=>appendM3UDownloadControls(panel)});
function showGraphLoadEvent(event){const status=presentGraphLoadEvent(event); if(status) graphStatusDisplay.show(status);}
graphEvents.subscribe('graph-controls-edited',event=>graphFilterControls.showValues(graphControlValuesViewModel(event.controls)));
graphEvents.subscribe('graph-load-started',event=>{cameraFocus.claimView('graph-reloaded'); showGraphLoadEvent(event);});
graphEvents.subscribe('graph-model-built',event=>{playlistControlsView.show(libraryArousalRangeViewModel(libraryArousalRange(event.model))); trackList.showBpmBadges(trackBpmBadges(trackSearchSession.read().results.tracks,trackBpmsOf(event.model))); graphFilterControls.showOptions(graphControlOptionsViewModel(event.model,event.controls)); showGraphLoadEvent(event);});
graphEvents.subscribe('graph-render-due',event=>renderMap(event.visible));
graphEvents.subscribe('graph-ready',showGraphLoadEvent);
graphEvents.subscribe('graph-load-failed',showGraphLoadEvent);
graphEvents.subscribe('graph-filters-applied',event=>{cameraFocus.claimView('graph-filtered'); if(event.shown) renderMap(event.visible); showGraphLoadEvent(event);});
const trackSearchSession=createInMemorySession({searchState:'idle',results:emptyTrackResults(),failure:null});
const trackEvents=createInMemoryEventBus();
const trackSearch=createTrackSearch({explorerApi,trackSession:trackSearchSession,clock:{wait:ms=>new Promise(resolve=>setTimeout(resolve,ms))},eventBus:trackEvents});
const trackList=trackListView({onTrackChosen:trackId=>setCurrent(trackId),onQueryTyped:query=>trackSearch.queryTyped(query),onLoadMore:()=>trackSearch.loadMore().catch(()=>{}),onRetry:()=>trackSearch.retry().catch(()=>{})});
for(const type of TRACK_SEARCH_EVENT_TYPES) trackEvents.subscribe(type,event=>renderTracks(event.results.tracks));
const trackDetail=trackDetailView();
const moodStrip=moodStripView();
toolPanelEvents.subscribe('tool-panel-opened',event=>{if(event.tool==='mood') renderMoodStrip(graphState().visible);});
const selectionSession=createInMemorySession({snapshot:{current_track_id:null},epoch:0,selectionState:'none'});
function currentTrackId(){return selectionSession.read().snapshot.current_track_id;}
const selectionEvents=createInMemoryEventBus();
const trackSelection=createTrackSelection({explorerApi,selectionTickets,selectionSession,eventBus:selectionEvents});
// A preview's approval belongs to the track it was made for; any change of track discards it.
for(const type of ['track-chosen','selection-rewinding','library-selection-changed','no-track-selected']) selectionEvents.subscribe(type,()=>tagWriteControls.trackChanged());
for(const type of TRACK_SELECTION_EVENT_TYPES) selectionEvents.subscribe(type,showPlaylistReadiness);
selectionEvents.subscribe('track-chosen',()=>{cameraFocus.claimViewForSelection('new-selection'); renderDetailLoading(); updateSelectedTrackVisuals();});
selectionEvents.subscribe('selection-rewinding',()=>{cameraFocus.claimViewForSelection('new-selection'); renderDetailLoading();});
selectionEvents.subscribe('selection-accepted',event=>cameraFocus.requestForAcceptedSelection(event.focusCamera?event.trackId:null));
selectionEvents.subscribe('selection-refused',event=>renderDetailError(event.failure));
selectionEvents.subscribe('library-selection-changed',event=>{cancelCameraFocus('new-selection'); cameraFocus.request(event.trackId);});
selectionEvents.subscribe('no-track-selected',()=>{updateSelectedTrackVisuals(); renderInitialDetail();});
selectionEvents.subscribe('track-detail-loading',()=>{updateSelectedTrackVisuals(); renderDetailLoading();});
selectionEvents.subscribe('track-detail-loaded',event=>{renderDetail(event.detail); updateSelectedTrackVisuals();});
selectionEvents.subscribe('track-detail-failed',event=>renderDetailError(event.failure,()=>trackSelection.retryDetail()));
const refreshEvents=createInMemoryEventBus();
const libraryRefresh=createLibraryRefresh({explorerApi,librarySelection:trackSelection,clock:{nextFrame:()=>nextFrame()},eventBus:refreshEvents});
const libraryLoading=libraryLoadingView({onRetry:()=>refresh().catch(()=>{})});
for(const type of LIBRARY_REFRESH_EVENT_TYPES) refreshEvents.subscribe(type,event=>libraryLoading.show(presentLibraryRefreshEvent(event)));
refreshEvents.subscribe('library-loaded',()=>{if(graphState().loadState==='ready') renderMap(graphState().visible);});
function refresh(){return libraryRefresh.refresh();}
function tabSessionStorage(){try{return typeof sessionStorage!=='undefined'?sessionStorage:undefined;}catch(_error){return undefined;}}
async function applyHistorySelection(action){if(await trackSelection.rewind(action)) await refresh();}
function nextFrame(){return new Promise(resolve=>{if(typeof requestAnimationFrame==='function') requestAnimationFrame(()=>resolve()); else setTimeout(resolve,0);});}
const selectedNodeValue=selectedTrackNodeSize(currentTrackId);
function updateSelectedTrackVisuals(){
  if(typeof document!=='undefined') for(const row of document.querySelectorAll('#tracks tr[data-track-id]')){row.className=row.dataset.trackId===currentTrackId()?'current':''; const button=row.querySelector ? row.querySelector('button') : null; if(button){if(row.className) button.setAttribute('aria-current','true'); else button.removeAttribute('aria-current');}}
  const graph=graphStage.current();
  if(graph){graphRendering.wake(); graph.nodeVal(selectedNodeValue); focusNeighbourhood(graph); if(typeof graph.refresh==='function') graph.refresh(); syncSelectedNodeHalo(graph,graphState().visible); focusPendingCameraSelection();}
  else if(graphState().visible.nodes.length) drawCanvasFallback(graphState().visible,null,currentTrackId());
  renderMoodStrip(graphState().visible);
}
function renderDetailLoading(){trackDetail.showLoading(trackDetailLoadingViewModel());}
function renderDetailError(error,retry){trackDetail.showFailure(trackDetailFailureViewModel(error),retry);}
async function setCurrent(id,{focusCamera=true}={}){return trackSelection.choose(id,{focusCamera});}
function renderTracks(tracks){trackList.show(trackListViewModel({tracks,...trackSearchSession.read(),currentTrackId:currentTrackId(),trackBpms:trackBpmsOf(graphState().model)}));}
function loadGraph(){return graphLoad.load();}

function appendM3UDownloadControls(panel){const steps=playlistGeneratorSteps(); playlistControlsView.mount(panel,playlistControlsViewModel({draft:playlistDownload.draft(),downloadState:playlistDownload.downloadState(),moods:graphState().model.availableMoods||[],arousalRange:libraryArousalRange(graphState().model)}),steps.finish); panel.append(steps.preview,steps.finish); playlistPreviewPanel.mount(steps.preview,playlistPreviewViewModel()); showPlaylistReadiness(); recipeExportPanel.mount(steps.finish); savedRecipePanel.mount(steps.finish,savedRecipesViewModel());}
function mountTagWritePanel(){const root=document.getElementById('tag-write'); if(root) tagWritePanel.mount(root,tagWriteViewModel());}
function renderInitialDetail(){trackDetail.showNone();}
function renderDetailField(name,field){return trackDetail.field(detailFieldViewModel(name,field));}
function renderTrackMetadata(metadata){return trackDetail.metadata(trackMetadataViewModel(metadata));}
function renderDetail(detail){trackDetail.show(trackDetailViewModel(detail));}
function renderDetailFields(detail){return trackDetail.fieldList(trackDetailViewModel(detail));}
function buildMoodGraphModel(graph){return moodGraphModel(normalizeMoodAxisGraphDto(graph),{genreThresholdApplies:isIndexedMoodAxisGraph(graph)});}
function fitGraph(elem){const size=fitGraphToElement(graphStage.current(),elem); graphRendering.wake(); return size;}

// #243: once per selection or new graph data, never per frame.
function focusNeighbourhood(graph){const focus=graphNeighbourFocus(graphState().visible,currentTrackId()); graph.nodeColor(focusedNodeColor(focus)).linkColor(focusedLinkColor(focus,graphState().model?.nodes||[])).linkWidth(focusedLinkWidth(focus)); showLinkLabels(selectionLinkLabels(focus,graphState().model?.nodes||[],graphState().visible.links)); neighbourhoodLabels.label(focus).catch(()=>{});}
function syncSelectedNodeHalo(graph,data){return nodeHalo.sync(graph,(data&&data.nodes)||graphState().visible.nodes,currentTrackId());}
function animateGraphAxes(timestamp){
  const graph=graphStage.current();
  if(graph){
    graphRendering.viewObserved(graphViewPose(graph));
    if(graphRendering.drawing()){
      const viewport=document.getElementById('graph3d'); graphAxes.sync(graph,graphStage.axisSpec(),viewport); graphAxes.placeLabels(graph,viewport); trackLabels.place(graph,viewport,graphState().visible.nodes); linkLabels.place(graph,viewport,graphState().visible.nodes); syncSelectedNodeHalo(graph,graphState().visible);
      graphRendering.frameDrawn(Number.isFinite(timestamp)?timestamp:performance.now());
    }
  }
  requestAnimationFrame(animateGraphAxes);
}
// Own the timeline: bundled cameraPosition's timed tweens have no public cancellation.
function cancelCameraFocus(cause){cameraFocus.cancel(cause);}
function observeCameraFocusControls(graph){cameraControlsWatch.observe(graph);}
const cameraFrames=Object.freeze({request:callback=>requestAnimationFrame(callback),now:()=>typeof performance!=='undefined'?performance.now():Date.now()});
function animateCameraFocus(graph,position,target){
  observeCameraFocusControls(graph);
  cancelCameraFocus('new-focus');
  animateCameraArc(graph,{position,target},{cameraFocus,frames:cameraFrames,isShown:()=>graphStage.shows(graph)});
}
// Graph picks own the view immediately; server acceptance still owns detail.
function selectGraphNode(picked){
  const id=pickedTrackId(picked);
  if(id===null) return;
  cancelCameraFocus('new-selection');
  cameraFocus.request(null);
  const node=mountedPickedNode(id,{visible:graphState().visible.nodes,mounted:graphDataMount.current().nodes});
  const graph=graphStage.current();
  if(graph && node && jumpCameraToPickedNode(graph,node,{controlsWatch:cameraControlsWatch,neighbours:graphNeighbourPositions(graphState().visible,id)})==='failed') cancelCameraFocus('camera-failure');
  return setCurrent(id,{focusCamera:false});
}
function focusPendingCameraSelection(graphRendered=false){
  // Existing instances still show the old layout while a replacement loads.
  // Only renderMap may consume focus before the load state becomes ready.
  if(!graphRendered && graphState().loadState!=='ready') return;
  const graph=graphStage.current();
  if(!graph || graphFraming.layout()===null || cameraFocus.peek()==null) return;
  const id=cameraFocus.take(currentTrackId());
  if(id===null) return;
  const node=graphState().visible.nodes.find(n=>n.id===id);
  if(!node) return; // Keep active filters; hidden/unpositioned selections still show detail.
  const target={x:node.fx,y:node.fy,z:node.fz};
  if(![target.x,target.y,target.z].every(Number.isFinite)) return;
  const length=Math.hypot(target.x,target.y,target.z);
  if(!Number.isFinite(length)) return;
  // Camera focus is best-effort; it must never block accepted track detail.
  try {
    // Configured orbit bounds take precedence over the nominal display-space radius.
    const controls=graph.controls();
    const pose=selectionFocusPose(target,{currentDirection:()=>cameraViewDirection(graph.cameraPosition(),controls.target),minDistance:controls.minDistance,maxDistance:controls.maxDistance,distanceFor:neighbourhoodFocusDistance(graph,target,graphNeighbourPositions(graphState().visible,id))});
    // Skip before settling input; never widen custom bounds to make focus eligible.
    if(pose) animateCameraFocus(graph,pose.position,pose.target);
  } catch(error) {
    // A camera adapter failure does not revoke an accepted selection.
    cancelCameraFocus('camera-failure');
  }
}
function renderMoodStrip(data){moodStrip.show(moodStripViewModel(moodStripMarks(data.nodes,currentTrackId()),moodStrip.width()));}
function renderMap(data){
  graphStage.stageAxes(graphAxisSpec(graphState().model.nodes.length?graphState().model.nodes:data.nodes));
  const elem=graphContainer();
  if(typeof ForceGraph3D!=='function'){nodeHalo.clear(); drawCanvasFallback(data,elem,currentTrackId()); renderMoodStrip(data); return;}
  const graph=graphStage.ensure(elem,()=>{observeElementResize(elem,()=>fitGraph(elem)); observeGraphInput(elem,()=>graphRendering.wake()); if(typeof requestAnimationFrame==='function') graphStage.startFrames(requestAnimationFrame,animateGraphAxes);});
  observeCameraFocusControls(graph); const size=fitGraph(elem); graphDataMount.mount(graph,data); focusNeighbourhood(graph); syncSelectedNodeHalo(graph,data); graphFraming.frame(graph,data.nodes,size); focusPendingCameraSelection(true); graphRendering.wake();
  renderMoodStrip(data);
}
function buildControls(){const root=document.getElementById('controls'); buildGraphControls(root);}
function buildGraphControls(root){graphFilterControls.mount(root);}
if(typeof document!=='undefined'){document.getElementById('undo').onclick=()=>applyHistorySelection('undo'); document.getElementById('reset').onclick=()=>applyHistorySelection('reset'); toolPanelDisplay.mount(); toolPanelControls.toggleRequested('library'); libraryLoading.mount(); buildControls(); mountTagWritePanel(); renderTracks([]); graphStatusDisplay.show(GRAPH_IDLE_STATUS); loadGraph().catch(()=>{}); refresh().catch(()=>{});}
// The opt-in diagnostics seam (#146, owner decision A): off unless the page address has `diagnostics`.
installExplorerDiagnostics(globalThis,globalThis.location?.search||'',{buses:[[NEIGHBOURHOOD_LABEL_EVENT_TYPES,labelEvents],[HAND_BUILT_PLAYLIST_EVENT_TYPES,handBuiltEvents],[TOOL_PANEL_EVENT_TYPES,toolPanelEvents],[TRACK_PLAYBACK_EVENT_TYPES,playbackEvents],[GRAPH_LOAD_EVENT_TYPES,graphEvents],[GRAPH_RENDERING_EVENT_TYPES,renderingEvents],[CAMERA_FOCUS_EVENT_TYPES,cameraEvents],[TRACK_SEARCH_EVENT_TYPES,trackEvents],[TRACK_SELECTION_EVENT_TYPES,selectionEvents],[PLAYLIST_DOWNLOAD_EVENT_TYPES,playlistEvents],[PLAYLIST_PREVIEW_EVENT_TYPES,playlistEvents],[PLAYLIST_RECIPE_EXPORT_EVENT_TYPES,playlistEvents],[SAVED_RECIPE_EVENT_TYPES,playlistEvents],[TAG_WRITE_EVENT_TYPES,tagWriteEvents],[LIBRARY_REFRESH_EVENT_TYPES,refreshEvents]],snapshot:diagnosticSnapshot,graph:()=>({model:graphState().model,visible:graphState().visible,layout:graphFraming.layout()}),scene:()=>({graph:graphStage.current(),graphData:graphDataMount.current(),halo:nodeHalo.current(),findSceneObject,graphObjectTrackId}),views:()=>({trackMetadata:renderTrackMetadata,detailField:renderDetailField,trackDetailFields:renderDetailFields})});
function diagnosticSnapshot(){const {snapshot,selectionState}=selectionSession.read(); const camera=cameraFocusSession.read(); return {currentTrackId:snapshot.current_track_id??null,selectionEpoch:snapshot.selection_epoch??null,history:snapshot.history||[],graphStatus:graphState().loadState==='failed'?'error':graphState().loadState,cameraFocusActive:camera.frame!=null,pendingCameraTrackId:camera.pendingTrackId,selectionPending:awaitingServer(selectionState),trackSearchStatus:trackSearchSession.read().searchState==='failed'?'error':trackSearchSession.read().searchState,trackResultCount:trackSearchSession.read().results.tracks.length};}
handBuiltPlaylist.restore().catch(()=>{});
