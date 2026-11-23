import {createPlaylistDownload} from '../application/download-playlist/download-playlist.js';
import {PLAYLIST_DOWNLOAD_EVENT_TYPES} from '../application/download-playlist/playlist-download-events.js';
import {createPlaylistPreview} from '../application/preview-playlist/preview-playlist.js';
import {PLAYLIST_PREVIEW_EVENT_TYPES} from '../application/preview-playlist/playlist-preview-events.js';
import {playlistPreviewController} from '../adapters/controllers/playlist-preview-controller.js';
import {playlistPreviewViewModel, presentPlaylistPreviewEvent} from '../adapters/presenters/playlist-preview-presenter.js';
import {playlistPreviewView} from '../frameworks/views/playlist-preview-view.js';
import {EMPTY_PLAYLIST_DRAFT} from '../domain/playlist-draft.js';
import {playlistDownloadController} from '../adapters/controllers/playlist-download-controller.js';
import {fetchExplorerApi} from '../adapters/gateways/explorer-api-gateway.js';
import {playlistControlsViewModel, presentPlaylistDownloadEvent, presentRejectedPlaylistInput} from '../adapters/presenters/playlist-download-presenter.js';
import {browserPlaylistFile} from '../frameworks/browser-playlist-file.js';
import {createInMemoryEventBus} from '../frameworks/in-memory-event-bus.js';
import {createGraphRendering} from '../application/render-graph/render-graph.js';
import {forceGraphRenderer, graphViewPose, observeGraphInput} from '../frameworks/graph-scene/force-graph-rendering.js';
import {createSelectedNodeHalo, findSceneObject, graphObjectTrackId} from '../frameworks/graph-scene/selected-node-halo.js';
import {animateCameraArc, createCameraControlsWatch} from '../frameworks/graph-scene/camera-focus-scene.js';
import {jumpCameraToPickedNode, mountedPickedNode, pickedTrackId} from '../frameworks/graph-scene/graph-pick.js';
import {configureForceGraph, createGraphDataMount, createGraphFraming, drawCanvasFallback, fitGraphToElement, graphContainer, observeElementResize, selectedTrackNodeSize} from '../frameworks/graph-scene/force-graph-scene.js';
import {playlistDownloadView} from '../frameworks/views/playlist-download-view.js';
import {EMPTY_GRAPH_CONTROLS} from '../domain/graph-filters.js';
import {moodGraphModel} from '../domain/mood-graph.js';
import {isIndexedMoodAxisGraph, normalizeMoodAxisGraphDto} from '../adapters/gateways/mood-axis-graph-dto.js';
import {createGraphLoad} from '../application/load-graph/load-graph.js';
import {graphControlsController} from '../adapters/controllers/graph-controls-controller.js';
import {GRAPH_IDLE_STATUS, graphControlOptionsViewModel, graphControlValuesViewModel, presentGraphLoadEvent} from '../adapters/presenters/graph-load-presenter.js';
import {graphControlsView} from '../frameworks/views/graph-controls-view.js';
import {graphStatusView} from '../frameworks/views/graph-status-view.js';
import {createTrackSearch} from '../application/search-tracks/search-tracks.js';
import {TRACK_SEARCH_EVENT_TYPES} from '../application/search-tracks/track-search-events.js';
import {emptyTrackResults} from '../domain/track-search.js';
import {trackListViewModel} from '../adapters/presenters/track-list-presenter.js';
import {trackListView} from '../frameworks/views/track-list-view.js';
import {detailFieldViewModel, trackDetailFailureViewModel, trackDetailLoadingViewModel, trackDetailViewModel, trackMetadataViewModel} from '../adapters/presenters/track-detail-presenter.js';
import {trackDetailView} from '../frameworks/views/track-detail-view.js';
import {sessionSelectionTickets} from '../frameworks/session-selection-tickets.js';
import {awaitingServer} from '../domain/track-selection.js';
import {createTrackSelection} from '../application/select-track/select-track.js';
import {moodStripMarks} from '../domain/mood-strip.js';
import {moodStripViewModel} from '../adapters/presenters/mood-strip-presenter.js';
import {moodStripView} from '../frameworks/views/mood-strip-view.js';
import {graphAxisSpec, linkLabel, nodeLabel, relatednessLinkColor} from '../adapters/presenters/graph-scene-presenter.js';
import {cameraViewDirection, selectionFocusPose} from '../domain/camera-arc.js';
import {createCameraFocus} from '../application/focus-camera/focus-camera.js';
import {CAMERA_FOCUS_EVENT_TYPES} from '../application/focus-camera/camera-focus-events.js';
import {TRACK_SELECTION_EVENT_TYPES} from '../application/select-track/track-selection-events.js';
import {GRAPH_LOAD_EVENT_TYPES} from '../application/load-graph/graph-load-events.js';
import {GRAPH_RENDERING_EVENT_TYPES} from '../application/render-graph/render-graph-events.js';
import {installExplorerDiagnostics} from '../frameworks/explorer-diagnostics.js';
import {createInMemorySession} from '../frameworks/in-memory-session.js';
import {createGraphAxes} from '../frameworks/graph-scene/graph-axes.js';
import {createLibraryRefresh} from '../application/refresh-library/refresh-library.js';
import {LIBRARY_REFRESH_EVENT_TYPES} from '../application/refresh-library/library-refresh-events.js';
import {presentLibraryRefreshEvent} from '../adapters/presenters/library-loading-presenter.js';
import {libraryLoadingView} from '../frameworks/views/library-loading-view.js';
let forceGraph=null;
const graphAxes=createGraphAxes();
const nodeHalo=createSelectedNodeHalo();
const graphDataMount=createGraphDataMount({onReplaced:()=>nodeHalo.clear()});
// A new layout is framed at once; cancelling first keeps a focus arc from overwriting the frame.
const graphFraming=createGraphFraming({onReframe:()=>cancelCameraFocus('graph-reframed')});
let graphAxesAnimating=false;
let pendingGraphAxisSpec=[];
const playlistEvents=createInMemoryEventBus();
const explorerApi=fetchExplorerApi((path,options)=>fetch(path,options));
const playlistDraftSession=createInMemorySession({draft:EMPTY_PLAYLIST_DRAFT});
const playlistDownload=createPlaylistDownload({explorerApi,playlistFile:browserPlaylistFile(),playlistDraft:playlistDraftSession,eventBus:playlistEvents});
const playlistControls=playlistDownloadController({playlistDownload,currentTrackId,rejectInput:message=>playlistControlsView.show(presentRejectedPlaylistInput(message))});
const playlistControlsView=playlistDownloadView({onControlsEdited:controls=>playlistControls.controlsEdited(controls),onDownloadRequested:controls=>playlistControls.downloadRequested(controls),onArcAdded:()=>playlistControls.arcAdded(),onArcRemoved:place=>playlistControls.arcRemoved(place),onArcMoved:(place,offset)=>playlistControls.arcMoved(place,offset),onArcEdited:(place,fields)=>playlistControls.arcEdited(place,fields)});
for(const type of PLAYLIST_DOWNLOAD_EVENT_TYPES) playlistEvents.subscribe(type,event=>playlistControlsView.show(presentPlaylistDownloadEvent(event)));
const playlistPreview=createPlaylistPreview({explorerApi,playlistDraft:playlistDraftSession,eventBus:playlistEvents});
const playlistPreviewControls=playlistPreviewController({playlistPreview,currentTrackId});
const playlistPreviewPanel=playlistPreviewView({onPreviewRequested:()=>playlistPreviewControls.previewRequested()});
for(const type of PLAYLIST_PREVIEW_EVENT_TYPES) playlistEvents.subscribe(type,event=>playlistPreviewPanel.show(presentPlaylistPreviewEvent(event)));
const selectionTickets=sessionSelectionTickets({storage:tabSessionStorage(),now:()=>Date.now(),random:()=>Math.random()});
const cameraFocusSession=createInMemorySession({pendingTrackId:null,frame:null,viewIntent:0,focusGeneration:0});
// Render on demand (#86): the vendor loop would otherwise redraw WebGL every frame, even when nothing moves.
const renderingEvents=createInMemoryEventBus();
const graphRendering=createGraphRendering({renderer:forceGraphRenderer(()=>forceGraph),eventBus:renderingEvents});
const cameraEvents=createInMemoryEventBus();
const cameraFocus=createCameraFocus({focusSession:cameraFocusSession,eventBus:cameraEvents});
const cameraControlsWatch=createCameraControlsWatch({onControlsReplaced:()=>cancelCameraFocus('controls-replaced'),onViewClaimed:()=>invalidateCameraViewIntent('listener-orbit')});
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
graphEvents.subscribe('graph-load-started',event=>{invalidateCameraViewIntent('graph-reloaded'); showGraphLoadEvent(event);});
graphEvents.subscribe('graph-model-built',event=>{graphFilterControls.showOptions(graphControlOptionsViewModel(event.model,event.controls)); showGraphLoadEvent(event);});
graphEvents.subscribe('graph-render-due',event=>renderMap(event.visible));
graphEvents.subscribe('graph-ready',showGraphLoadEvent);
graphEvents.subscribe('graph-load-failed',showGraphLoadEvent);
graphEvents.subscribe('graph-filters-applied',event=>{invalidateCameraViewIntent('graph-filtered'); if(event.shown) renderMap(event.visible); showGraphLoadEvent(event);});
const trackSearchSession=createInMemorySession({searchState:'idle',results:emptyTrackResults(),failure:null});
const trackEvents=createInMemoryEventBus();
const trackSearch=createTrackSearch({explorerApi,trackSession:trackSearchSession,clock:{wait:ms=>new Promise(resolve=>setTimeout(resolve,ms))},eventBus:trackEvents});
const trackList=trackListView({onTrackChosen:trackId=>setCurrent(trackId),onQueryTyped:query=>trackSearch.queryTyped(query),onLoadMore:()=>trackSearch.loadMore().catch(()=>{}),onRetry:()=>trackSearch.retry().catch(()=>{})});
for(const type of TRACK_SEARCH_EVENT_TYPES) trackEvents.subscribe(type,event=>renderTracks(event.results.tracks));
const trackDetail=trackDetailView();
const moodStrip=moodStripView();
const selectionSession=createInMemorySession({snapshot:{current_track_id:null},epoch:0,selectionState:'none'});
function currentTrackId(){return selectionSession.read().snapshot.current_track_id;}
const selectionEvents=createInMemoryEventBus();
const trackSelection=createTrackSelection({explorerApi,selectionTickets,selectionSession,eventBus:selectionEvents});
let selectionViewIntent=0;
selectionEvents.subscribe('track-chosen',()=>{selectionViewIntent=invalidateCameraViewIntent('new-selection'); renderDetailLoading(); updateSelectedTrackVisuals();});
selectionEvents.subscribe('selection-rewinding',()=>{selectionViewIntent=invalidateCameraViewIntent('new-selection'); renderDetailLoading();});
selectionEvents.subscribe('selection-accepted',event=>{if(selectionViewIntent!==cameraFocus.viewIntent()) return; cancelCameraFocus('new-selection'); cameraFocus.request(event.focusCamera?event.trackId:null);});
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
  if(forceGraph){graphRendering.wake(); forceGraph.nodeVal(selectedNodeValue); if(typeof forceGraph.refresh==='function') forceGraph.refresh(); syncSelectedNodeHalo(forceGraph,graphState().visible); focusPendingCameraSelection();}
  else if(graphState().visible.nodes.length) drawCanvasFallback(graphState().visible,null,currentTrackId());
  renderMoodStrip(graphState().visible);
}
function renderDetailLoading(){trackDetail.showLoading(trackDetailLoadingViewModel());}
function renderDetailError(error,retry){trackDetail.showFailure(trackDetailFailureViewModel(error),retry);}
async function setCurrent(id,{focusCamera=true}={}){return trackSelection.choose(id,{focusCamera});}
function renderTracks(tracks){trackList.show(trackListViewModel({tracks,...trackSearchSession.read(),currentTrackId:currentTrackId()}));}
function loadGraph(){return graphLoad.load();}

function appendM3UDownloadControls(panel){playlistControlsView.mount(panel,playlistControlsViewModel({draft:playlistDownload.draft(),downloadState:playlistDownload.downloadState(),moods:graphState().model.availableMoods||[]})); playlistPreviewPanel.mount(panel,playlistPreviewViewModel());}
function renderInitialDetail(){trackDetail.showNone();}
function renderDetailField(name,field){return trackDetail.field(detailFieldViewModel(name,field));}
function renderTrackMetadata(metadata){return trackDetail.metadata(trackMetadataViewModel(metadata));}
function renderDetail(detail){trackDetail.show(trackDetailViewModel(detail));}
function buildMoodGraphModel(graph){return moodGraphModel(normalizeMoodAxisGraphDto(graph),{genreThresholdApplies:isIndexedMoodAxisGraph(graph)});}
function fitGraph(elem){const size=fitGraphToElement(forceGraph,elem); graphRendering.wake(); return size;}

function syncSelectedNodeHalo(graph,data){return nodeHalo.sync(graph,(data&&data.nodes)||graphState().visible.nodes,currentTrackId());}
function animateGraphAxes(timestamp){
  if(forceGraph){
    graphRendering.viewObserved(graphViewPose(forceGraph));
    if(graphRendering.drawing()){
      const viewport=document.getElementById('graph3d'); graphAxes.sync(forceGraph,pendingGraphAxisSpec,viewport); graphAxes.placeLabels(forceGraph,viewport); syncSelectedNodeHalo(forceGraph,graphState().visible);
      graphRendering.frameDrawn(Number.isFinite(timestamp)?timestamp:performance.now());
    }
  }
  requestAnimationFrame(animateGraphAxes);
}
// View ownership outlives a POST or a deferred layout, independently of the RAF timeline.
function invalidateCameraViewIntent(cause){cancelCameraFocus(cause); return cameraFocus.claimView(cause);}
// Own the timeline: bundled cameraPosition's timed tweens have no public cancellation.
function cancelCameraFocus(cause){cameraFocus.cancel(cause);}
function observeCameraFocusControls(graph){cameraControlsWatch.observe(graph);}
const cameraFrames=Object.freeze({request:callback=>requestAnimationFrame(callback),now:()=>typeof performance!=='undefined'?performance.now():Date.now()});
function animateCameraFocus(graph,position,target){
  observeCameraFocusControls(graph);
  cancelCameraFocus('new-focus');
  animateCameraArc(graph,{position,target},{cameraFocus,frames:cameraFrames,isShown:()=>graph===forceGraph});
}
// Graph picks own the view immediately; server acceptance still owns detail.
function selectGraphNode(picked){
  const id=pickedTrackId(picked);
  if(id===null) return;
  cancelCameraFocus('new-selection');
  cameraFocus.request(null);
  const node=mountedPickedNode(id,{visible:graphState().visible.nodes,mounted:graphDataMount.current().nodes});
  if(forceGraph && node && jumpCameraToPickedNode(forceGraph,node,cameraControlsWatch)==='failed') cancelCameraFocus('camera-failure');
  return setCurrent(id,{focusCamera:false});
}
function focusPendingCameraSelection(graphRendered=false){
  // Existing instances still show the old layout while a replacement loads.
  // Only renderMap may consume focus before the load state becomes ready.
  if(!graphRendered && graphState().loadState!=='ready') return;
  if(!forceGraph || graphFraming.layout()===null || cameraFocus.peek()==null) return;
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
    const controls=forceGraph.controls();
    const pose=selectionFocusPose(target,{currentDirection:()=>cameraViewDirection(forceGraph.cameraPosition(),controls.target),minDistance:controls.minDistance,maxDistance:controls.maxDistance});
    // Skip before settling input; never widen custom bounds to make focus eligible.
    if(pose) animateCameraFocus(forceGraph,pose.position,pose.target);
  } catch(error) {
    // A camera adapter failure does not revoke an accepted selection.
    cancelCameraFocus('camera-failure');
  }
}
function renderMoodStrip(data){moodStrip.show(moodStripViewModel(moodStripMarks(data.nodes,currentTrackId()),moodStrip.width()));}
function renderMap(data){pendingGraphAxisSpec=graphAxisSpec(graphState().model.nodes.length?graphState().model.nodes:data.nodes);const elem=graphContainer(); if(typeof ForceGraph3D==='function'){if(!forceGraph){forceGraph=configureForceGraph(ForceGraph3D()(elem),{nodeLabel,linkLabel,linkColor:relatednessLinkColor,nodeValue:selectedNodeValue,onNodeClick:selectGraphNode}); observeElementResize(elem,()=>fitGraph(elem)); observeGraphInput(elem,()=>graphRendering.wake()); if(!graphAxesAnimating && typeof requestAnimationFrame==='function'){graphAxesAnimating=true;requestAnimationFrame(animateGraphAxes);}} observeCameraFocusControls(forceGraph); const size=fitGraph(elem); graphDataMount.mount(forceGraph,data); syncSelectedNodeHalo(forceGraph,data); graphFraming.frame(forceGraph,data.nodes,size); focusPendingCameraSelection(true); graphRendering.wake();} else {nodeHalo.clear();drawCanvasFallback(data,elem,currentTrackId());} renderMoodStrip(data);}
function buildControls(){const root=document.getElementById('controls'); buildGraphControls(root);}
function buildGraphControls(root){graphFilterControls.mount(root);}
if(typeof document!=='undefined'){document.getElementById('undo').onclick=()=>applyHistorySelection('undo'); document.getElementById('reset').onclick=()=>applyHistorySelection('reset'); libraryLoading.mount(); buildControls(); renderTracks([]); graphStatusDisplay.show(GRAPH_IDLE_STATUS); loadGraph().catch(()=>{}); refresh().catch(()=>{});}
// The opt-in diagnostics seam (#146, owner decision A): off unless the page address has `diagnostics`.
installExplorerDiagnostics(globalThis,globalThis.location?.search||'',{buses:[[GRAPH_LOAD_EVENT_TYPES,graphEvents],[GRAPH_RENDERING_EVENT_TYPES,renderingEvents],[CAMERA_FOCUS_EVENT_TYPES,cameraEvents],[TRACK_SEARCH_EVENT_TYPES,trackEvents],[TRACK_SELECTION_EVENT_TYPES,selectionEvents],[PLAYLIST_DOWNLOAD_EVENT_TYPES,playlistEvents],[PLAYLIST_PREVIEW_EVENT_TYPES,playlistEvents],[LIBRARY_REFRESH_EVENT_TYPES,refreshEvents]],snapshot:diagnosticSnapshot,graph:()=>({model:graphState().model,visible:graphState().visible,layout:graphFraming.layout()}),scene:()=>({graph:forceGraph,graphData:graphDataMount.current(),halo:nodeHalo.current(),findSceneObject,graphObjectTrackId}),views:()=>({trackMetadata:renderTrackMetadata,detailField:renderDetailField})});
function diagnosticSnapshot(){const {snapshot,selectionState}=selectionSession.read(); const camera=cameraFocusSession.read(); return {currentTrackId:snapshot.current_track_id??null,selectionEpoch:snapshot.selection_epoch??null,history:snapshot.history||[],graphStatus:graphState().loadState==='failed'?'error':graphState().loadState,cameraFocusActive:camera.frame!=null,pendingCameraTrackId:camera.pendingTrackId,selectionPending:awaitingServer(selectionState),trackSearchStatus:trackSearchSession.read().searchState==='failed'?'error':trackSearchSession.read().searchState,trackResultCount:trackSearchSession.read().results.tracks.length};}
