import {createPlaylistDownload} from './app/application/download-playlist/download-playlist.js';
import {PLAYLIST_DOWNLOAD_EVENT_TYPES} from './app/application/download-playlist/playlist-download-events.js';
import {playlistDownloadController} from './app/adapters/controllers/playlist-download-controller.js';
import {fetchExplorerApi} from './app/adapters/gateways/explorer-api-gateway.js';
import {playlistControlsViewModel, presentPlaylistDownloadEvent, presentRejectedPlaylistInput} from './app/adapters/presenters/playlist-download-presenter.js';
import {browserPlaylistFile} from './app/frameworks/browser-playlist-file.js';
import {createInMemoryEventBus} from './app/frameworks/in-memory-event-bus.js';
import {createGraphRendering} from './app/application/render-graph/render-graph.js';
import {forceGraphRenderer, graphViewPose, observeGraphInput} from './app/frameworks/graph-scene/force-graph-rendering.js';
import {createSelectedNodeHalo, findSceneObject, graphObjectTrackId} from './app/frameworks/graph-scene/selected-node-halo.js';
import {createCameraControlsWatch, settleCameraFocusInput, showCameraArcPose} from './app/frameworks/graph-scene/camera-focus-scene.js';
import {jumpCameraToPickedNode, mountedPickedNode, pickedTrackId} from './app/frameworks/graph-scene/graph-pick.js';
import {configureForceGraph, createGraphDataMount, createGraphFraming, drawCanvasFallback, graphContainer, graphDimensions, selectedTrackNodeSize} from './app/frameworks/graph-scene/force-graph-scene.js';
import {playlistDownloadView} from './app/frameworks/views/playlist-download-view.js';
import {EMPTY_GRAPH_CONTROLS} from './app/domain/graph-filters.js';
import {moodGraphModel} from './app/domain/mood-graph.js';
import {isIndexedMoodAxisGraph, normalizeMoodAxisGraphDto} from './app/adapters/gateways/mood-axis-graph-dto.js';
import {createGraphLoad} from './app/application/load-graph/load-graph.js';
import {graphControlsController} from './app/adapters/controllers/graph-controls-controller.js';
import {GRAPH_IDLE_STATUS, graphControlOptionsViewModel, graphControlValuesViewModel, presentGraphLoadEvent} from './app/adapters/presenters/graph-load-presenter.js';
import {graphControlsView} from './app/frameworks/views/graph-controls-view.js';
import {graphStatusView} from './app/frameworks/views/graph-status-view.js';
import {createTrackSearch} from './app/application/search-tracks/search-tracks.js';
import {TRACK_SEARCH_EVENT_TYPES} from './app/application/search-tracks/track-search-events.js';
import {emptyTrackResults} from './app/domain/track-search.js';
import {trackListViewModel} from './app/adapters/presenters/track-list-presenter.js';
import {trackListView} from './app/frameworks/views/track-list-view.js';
import {detailFieldViewModel, trackDetailFailureViewModel, trackDetailLoadingViewModel, trackDetailViewModel, trackMetadataViewModel} from './app/adapters/presenters/track-detail-presenter.js';
import {trackDetailView} from './app/frameworks/views/track-detail-view.js';
import {sessionSelectionTickets} from './app/frameworks/session-selection-tickets.js';
import {awaitingServer} from './app/domain/track-selection.js';
import {createTrackSelection} from './app/application/select-track/select-track.js';
import {moodStripMarks} from './app/domain/mood-strip.js';
import {moodStripViewModel} from './app/adapters/presenters/mood-strip-presenter.js';
import {moodStripView} from './app/frameworks/views/mood-strip-view.js';
import {graphAxisSpec, linkLabel, nodeLabel, relatednessLinkColor} from './app/adapters/presenters/graph-scene-presenter.js';
import {cameraArcPose, cameraFocusArc, cameraViewDirection, focusProgress, selectionFocusPose} from './app/domain/camera-arc.js';
import {createCameraFocus} from './app/application/focus-camera/focus-camera.js';
import {CAMERA_FOCUS_EVENT_TYPES} from './app/application/focus-camera/camera-focus-events.js';
import {TRACK_SELECTION_EVENT_TYPES} from './app/application/select-track/track-selection-events.js';
import {GRAPH_LOAD_EVENT_TYPES} from './app/application/load-graph/graph-load-events.js';
import {GRAPH_RENDERING_EVENT_TYPES} from './app/application/render-graph/render-graph-events.js';
import {installExplorerDiagnostics} from './app/frameworks/explorer-diagnostics.js';
import {createLibraryRefresh} from './app/application/refresh-library/refresh-library.js';
import {LIBRARY_REFRESH_EVENT_TYPES} from './app/application/refresh-library/library-refresh-events.js';
import {presentLibraryRefreshEvent} from './app/adapters/presenters/library-loading-presenter.js';
import {libraryLoadingView} from './app/frameworks/views/library-loading-view.js';
let state={current_track_id:null};
let graphModel={nodes:[],links:[],unpositioned:[],availableMoods:[],selectedMood:'',metadata:{},genreOptions:[]};
let visibleGraph={nodes:[],links:[],unpositioned:[]};
let forceGraph=null;
let graphResizeObserver=null;
let graphAxes=null;
const nodeHalo=createSelectedNodeHalo();
const graphDataMount=createGraphDataMount({onReplaced:()=>nodeHalo.clear()});
// A new layout is framed at once; cancelling first keeps a focus arc from overwriting the frame.
const graphFraming=createGraphFraming({onReframe:()=>cancelCameraFocus('graph-reframed')});
let graphAxesAnimating=false;
let pendingGraphAxisSpec=[];
let selectedGraphControls=EMPTY_GRAPH_CONTROLS;
const playlistEvents=createInMemoryEventBus();
const explorerApi=fetchExplorerApi((path,options)=>fetch(path,options));
const playlistDownload=createPlaylistDownload({explorerApi,playlistFile:browserPlaylistFile(),eventBus:playlistEvents});
const playlistControls=playlistDownloadController({playlistDownload,currentTrackId:()=>state.current_track_id,rejectInput:message=>playlistControlsView.show(presentRejectedPlaylistInput(message))});
const playlistControlsView=playlistDownloadView({onControlsEdited:controls=>playlistControls.controlsEdited(controls),onDownloadRequested:controls=>playlistControls.downloadRequested(controls),onArcAdded:()=>playlistControls.arcAdded(),onArcRemoved:place=>playlistControls.arcRemoved(place),onArcMoved:(place,offset)=>playlistControls.arcMoved(place,offset),onArcEdited:(place,fields)=>playlistControls.arcEdited(place,fields)});
for(const type of PLAYLIST_DOWNLOAD_EVENT_TYPES) playlistEvents.subscribe(type,event=>playlistControlsView.show(presentPlaylistDownloadEvent(event)));
const selectionTickets=sessionSelectionTickets({storage:tabSessionStorage(),now:()=>Date.now(),random:()=>Math.random()});
let selectionEpoch=0;
let selectionState='none';
// Mirrors the selection's wait for the server for the browser probe and the diagnostics, until #146 step 8.
let pendingSelectionOperation=null;
let pendingCameraSelection=null;
let cameraViewIntentGeneration=0;
let cameraFocusGeneration=0;
let cameraFocusFrame=null;
// The camera variables above mirror the focus for the browser probe and the tests, until #146 step 8.
const legacyCameraFocusSession=Object.freeze({read:()=>({pendingTrackId:pendingCameraSelection,frame:cameraFocusFrame,viewIntent:cameraViewIntentGeneration,focusGeneration:cameraFocusGeneration}),write(changes){if('pendingTrackId' in changes) pendingCameraSelection=changes.pendingTrackId; if('frame' in changes) cameraFocusFrame=changes.frame; if('viewIntent' in changes) cameraViewIntentGeneration=changes.viewIntent; if('focusGeneration' in changes) cameraFocusGeneration=changes.focusGeneration;}});
// Render on demand (#86): the vendor loop would otherwise redraw WebGL every frame, even when nothing moves.
const renderingEvents=createInMemoryEventBus();
const graphRendering=createGraphRendering({renderer:forceGraphRenderer(()=>forceGraph),eventBus:renderingEvents});
const cameraEvents=createInMemoryEventBus();
const cameraFocus=createCameraFocus({focusSession:legacyCameraFocusSession,eventBus:cameraEvents});
const cameraControlsWatch=createCameraControlsWatch({onControlsReplaced:()=>cancelCameraFocus('controls-replaced'),onViewClaimed:()=>invalidateCameraViewIntent('listener-orbit')});
cameraEvents.subscribe('camera-focus-cancelled',event=>{if(typeof cancelAnimationFrame==='function') cancelAnimationFrame(event.frame);});
let trackSearchSession={searchState:'idle',results:emptyTrackResults(),failure:null};
let graphLoadState={...GRAPH_IDLE_STATUS};
// Transitional (#146): the graph session lives in the page's variables, which the browser tests and
// tools still read and set, until the 3D scene and selection move into the layers.
const legacyGraphSession=Object.freeze({read:()=>({loadState:graphLoadState.status==='error'?'failed':graphLoadState.status,model:graphModel,visible:visibleGraph,controls:selectedGraphControls}),write(changes){if('model' in changes) graphModel=changes.model; if('visible' in changes) visibleGraph=changes.visible; if('controls' in changes) selectedGraphControls=changes.controls; if('loadState' in changes) graphLoadState={...graphLoadState,status:changes.loadState==='failed'?'error':changes.loadState};}});
const graphEvents=createInMemoryEventBus();
const graphLoad=createGraphLoad({explorerApi,graphSession:legacyGraphSession,clock:{nextFrame:()=>nextFrame()},eventBus:graphEvents,buildGraphModel:buildMoodGraphModel});
const graphControls=graphControlsController({graphLoad,rejectInput:message=>graphFilterControls.showRejection(message)});
const graphFilterControls=graphControlsView({onMoodChosen:mood=>graphControls.moodChosen(mood),onBpmRangeEdited:range=>graphControls.bpmRangeEdited(range),onGenresEdited:genres=>graphControls.genresEdited(genres),onFiltersCleared:()=>graphControls.filtersCleared()});
const graphStatusDisplay=graphStatusView({onReload:()=>loadGraph().catch(()=>{}),appendPlaylistControls:panel=>appendM3UDownloadControls(panel)});
function showGraphLoadEvent(event){const status=presentGraphLoadEvent(event); if(status) graphLoadState={...graphLoadState,...status}; renderGraphLoadStatus();}
graphEvents.subscribe('graph-controls-edited',event=>graphFilterControls.showValues(graphControlValuesViewModel(event.controls)));
graphEvents.subscribe('graph-load-started',event=>{invalidateCameraViewIntent('graph-reloaded'); showGraphLoadEvent(event);});
graphEvents.subscribe('graph-model-built',event=>{graphFilterControls.showOptions(graphControlOptionsViewModel(event.model,event.controls)); showGraphLoadEvent(event);});
graphEvents.subscribe('graph-render-due',event=>renderMap(event.visible));
graphEvents.subscribe('graph-ready',showGraphLoadEvent);
graphEvents.subscribe('graph-load-failed',showGraphLoadEvent);
graphEvents.subscribe('graph-filters-applied',event=>{invalidateCameraViewIntent('graph-filtered'); if(event.shown) renderMap(event.visible); showGraphLoadEvent(event);});
const trackSearchStore=Object.freeze({read:()=>trackSearchSession,write(changes){trackSearchSession={...trackSearchSession,...changes};}});
const trackEvents=createInMemoryEventBus();
const trackSearch=createTrackSearch({explorerApi,trackSession:trackSearchStore,clock:{wait:ms=>new Promise(resolve=>setTimeout(resolve,ms))},eventBus:trackEvents});
const trackList=trackListView({onTrackChosen:trackId=>setCurrent(trackId),onQueryTyped:query=>trackSearch.queryTyped(query),onLoadMore:()=>trackSearch.loadMore().catch(()=>{}),onRetry:()=>trackSearch.retry().catch(()=>{})});
for(const type of TRACK_SEARCH_EVENT_TYPES) trackEvents.subscribe(type,event=>renderTracks(event.results.tracks));
const trackDetail=trackDetailView();
const moodStrip=moodStripView();
const legacySelectionSession=Object.freeze({read:()=>({snapshot:state,epoch:selectionEpoch,selectionState}),write(changes){if('snapshot' in changes) state=changes.snapshot; if('epoch' in changes) selectionEpoch=changes.epoch; if('selectionState' in changes){selectionState=changes.selectionState; pendingSelectionOperation=awaitingServer(selectionState)?selectionState:null;}}});
const selectionEvents=createInMemoryEventBus();
const trackSelection=createTrackSelection({explorerApi,selectionTickets,selectionSession:legacySelectionSession,eventBus:selectionEvents});
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
refreshEvents.subscribe('library-loaded',()=>{if(graphLoadState.status==='ready') renderMap(visibleGraph);});
function refresh(){return libraryRefresh.refresh();}
function tabSessionStorage(){try{return typeof sessionStorage!=='undefined'?sessionStorage:undefined;}catch(_error){return undefined;}}
async function applyHistorySelection(action){if(await trackSelection.rewind(action)) await refresh();}
function nextFrame(){return new Promise(resolve=>{if(typeof requestAnimationFrame==='function') requestAnimationFrame(()=>resolve()); else setTimeout(resolve,0);});}
const selectedNodeValue=selectedTrackNodeSize(()=>state.current_track_id);
function updateSelectedTrackVisuals(){
  if(typeof document!=='undefined') for(const row of document.querySelectorAll('#tracks tr[data-track-id]')){row.className=row.dataset.trackId===state.current_track_id?'current':''; const button=row.querySelector ? row.querySelector('button') : null; if(button){if(row.className) button.setAttribute('aria-current','true'); else button.removeAttribute('aria-current');}}
  if(forceGraph){graphRendering.wake(); forceGraph.nodeVal(selectedNodeValue); if(typeof forceGraph.refresh==='function') forceGraph.refresh(); syncSelectedNodeHalo(forceGraph,visibleGraph); focusPendingCameraSelection();}
  else if(visibleGraph.nodes.length) drawCanvasFallback(visibleGraph,null,state.current_track_id);
  renderMoodStrip(visibleGraph);
}
function renderDetailLoading(){trackDetail.showLoading(trackDetailLoadingViewModel());}
function renderDetailError(error,retry){trackDetail.showFailure(trackDetailFailureViewModel(error),retry);}
async function setCurrent(id,{focusCamera=true}={}){return trackSelection.choose(id,{focusCamera});}
function renderTracks(tracks){trackList.show(trackListViewModel({tracks,...trackSearchSession,currentTrackId:state.current_track_id}));}
function renderGraphLoadStatus(){graphStatusDisplay.show({status:graphLoadState.status,message:graphLoadState.message||GRAPH_IDLE_STATUS.message});}
function loadGraph(){return graphLoad.load();}

function appendM3UDownloadControls(panel){playlistControlsView.mount(panel,playlistControlsViewModel({draft:playlistDownload.draft(),downloadState:playlistDownload.downloadState(),moods:graphModel.availableMoods||[]}));}
function renderInitialDetail(){trackDetail.showNone();}
function renderDetailField(name,field){return trackDetail.field(detailFieldViewModel(name,field));}
function renderTrackMetadata(metadata){return trackDetail.metadata(trackMetadataViewModel(metadata));}
function renderDetail(detail){trackDetail.show(trackDetailViewModel(detail));}
function buildMoodGraphModel(graph){return moodGraphModel(normalizeMoodAxisGraphDto(graph),{genreThresholdApplies:isIndexedMoodAxisGraph(graph)});}
function updateGraphSize(elem,graph){if(!elem||!graph) return {width:0,height:0}; const size=graphDimensions(elem); graph.width(size.width).height(size.height); graphRendering.wake(); return size;}
function observeGraphResize(elem){if(graphResizeObserver||!elem) return; const resize=()=>updateGraphSize(elem,forceGraph); if(typeof ResizeObserver!=='undefined'){graphResizeObserver=new ResizeObserver(resize); graphResizeObserver.observe(elem); if(elem.parentElement) graphResizeObserver.observe(elem.parentElement);} if(typeof window!=='undefined') window.addEventListener('resize',resize);}
function disposeGraphAxes(group){
  if(!group) return;
  group.parent.remove(group);
  for(const mesh of group.children){mesh.geometry.dispose();mesh.material.dispose();}
  if(group.labels) for(const label of group.labels) label.remove();
}

function syncSelectedNodeHalo(graph,data){return nodeHalo.sync(graph,(data&&data.nodes)||(visibleGraph&&visibleGraph.nodes)||[],state.current_track_id);}
// Vendor bundles THREE privately. Reuse constructors of its rendered node mesh, so
// scene objects share that exact THREE instance without a second dependency/global.
function syncGraphAxes(graph,spec,element){
  const signature=JSON.stringify(spec);
  if(graphAxes && graphAxes.graph===graph && graphAxes.signature===signature) return graphAxes.group;
  const scene=graph.scene();
  if(!spec.length){disposeGraphAxes(graphAxes?.group);graphAxes=null;return null;}
  const sample=findSceneObject(scene,obj=>obj.__graphObjType==='node' && obj.geometry && obj.material);
  if(!sample){disposeGraphAxes(graphAxes?.group);graphAxes=null;return null;} // Objects may arrive one frame after graphData().
  disposeGraphAxes(graphAxes?.group);
  const group=new scene.constructor();
  group.name='mood-xyz-axes';group.labels=[];
  for(const axis of spec){
    const mesh=new sample.constructor(new sample.geometry.constructor(1,8,6),new sample.material.constructor({color:axis.color,transparent:true,opacity:0.8,depthWrite:false}));
    mesh.name='axis-'+axis.key;
    mesh.raycast=()=>{}; // Not a track/link and never eligible for graph picking.
    const length=axis.end[axis.key]-axis.start[axis.key];
    const center={...axis.start,[axis.key]:axis.start[axis.key]+length/2};
    mesh.position.set(center.x,center.y,center.z);
    mesh.scale.set(axis.key==='x'?length/2:0.65,axis.key==='y'?length/2:0.65,axis.key==='z'?length/2:0.65);
    group.add(mesh);
    if(element){
      for(const [content,position] of [[axis.label,axis.end],['data '+axis.references.join('–'),axis.start]]){
        const label=document.createElement('span');label.className='graph-axis-label';label.textContent=content;
        label.style.color=axis.color;element.append(label);group.labels.push(label);
        label.axisPosition=position;
      }
    }
  }
  scene.add(group);graphAxes={graph,signature,group};
  return group;
}
function placeGraphAxisLabels(graph){
  if(!graphAxes?.group.labels?.length) return;
  const elem=document.getElementById('graph3d');
  for(const label of graphAxes.group.labels){
    const p=graph.graph2ScreenCoords(label.axisPosition.x,label.axisPosition.y,label.axisPosition.z);
    label.style.transform=`translate(${p.x}px,${p.y}px) translate(-50%,-50%)`;
    label.style.display=Number.isFinite(p.x)&&Number.isFinite(p.y)&&p.x>=0&&p.y>=0&&p.x<elem.clientWidth&&p.y<elem.clientHeight?'':'none';
  }
}
function animateGraphAxes(timestamp){
  if(forceGraph){
    graphRendering.viewObserved(graphViewPose(forceGraph));
    if(graphRendering.drawing()){
      syncGraphAxes(forceGraph,pendingGraphAxisSpec,document.getElementById('graph3d'));placeGraphAxisLabels(forceGraph);syncSelectedNodeHalo(forceGraph,visibleGraph);
      graphRendering.frameDrawn(Number.isFinite(timestamp)?timestamp:performance.now());
    }
  }
  requestAnimationFrame(animateGraphAxes);
}
// View ownership outlives a POST or a deferred layout, independently of the RAF timeline.
// Cancel through the page's own cancelCameraFocus first: the browser diagnostic observes cancellations there.
function invalidateCameraViewIntent(cause){cancelCameraFocus(cause); return cameraFocus.claimView(cause);}
// Own the timeline: bundled cameraPosition's timed tweens have no public cancellation.
function cancelCameraFocus(cause){cameraFocus.cancel(cause);}
function observeCameraFocusControls(graph){cameraControlsWatch.observe(graph);}
function animateCameraFocus(graph,position,target){
  observeCameraFocusControls(graph);
  cancelCameraFocus('new-focus');
  const generation=cameraFocus.begin();
  settleCameraFocusInput(graph);
  const camera=graph.camera();
  const arc=cameraFocusArc({fromPosition:{...graph.cameraPosition()},fromTarget:{...graph.controls().target},fromUp:camera.up?{...camera.up}:null,position,target});
  const clockNow=()=>typeof performance!=='undefined'?performance.now():Date.now();
  const started=clockNow();
  const step=timestamp=>{
    if(graph!==forceGraph || !cameraFocus.frameRan(generation)) return;
    const progress=focusProgress(started,Number.isFinite(timestamp)?timestamp:clockNow());
    showCameraArcPose(graph,cameraArcPose(arc,progress));
    if(progress<1) cameraFocus.frameScheduled(generation,requestAnimationFrame(step)); else cameraFocus.finished(generation);
  };
  cameraFocus.frameScheduled(generation,requestAnimationFrame(step));
}
// Graph picks own the view immediately; server acceptance still owns detail.
function selectGraphNode(picked){
  const id=pickedTrackId(picked);
  if(id===null) return;
  cancelCameraFocus('new-selection');
  cameraFocus.request(null);
  const node=mountedPickedNode(id,{visible:visibleGraph.nodes,mounted:graphDataMount.current().nodes});
  if(forceGraph && node && jumpCameraToPickedNode(forceGraph,node,cameraControlsWatch)==='failed') cancelCameraFocus('camera-failure');
  return setCurrent(id,{focusCamera:false});
}
function focusPendingCameraSelection(graphRendered=false){
  // Existing instances still show the old layout while a replacement loads.
  // Only renderMap may consume focus before the load state becomes ready.
  if(!graphRendered && graphLoadState.status!=='ready') return;
  if(!forceGraph || graphFraming.layout()===null || cameraFocus.peek()==null) return;
  const id=cameraFocus.take(state.current_track_id);
  if(id===null) return;
  const node=visibleGraph.nodes.find(n=>n.id===id);
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
function renderMoodStrip(data){moodStrip.show(moodStripViewModel(moodStripMarks(data.nodes,state.current_track_id),moodStrip.width()));}
function renderMap(data){pendingGraphAxisSpec=graphAxisSpec(graphModel.nodes.length?graphModel.nodes:data.nodes);const elem=graphContainer(); if(typeof ForceGraph3D==='function'){if(!forceGraph){forceGraph=configureForceGraph(ForceGraph3D()(elem),{nodeLabel,linkLabel,linkColor:relatednessLinkColor,nodeValue:selectedNodeValue,onNodeClick:selectGraphNode}); observeGraphResize(elem); observeGraphInput(elem,()=>graphRendering.wake()); if(!graphAxesAnimating && typeof requestAnimationFrame==='function'){graphAxesAnimating=true;requestAnimationFrame(animateGraphAxes);}} observeCameraFocusControls(forceGraph); const size=updateGraphSize(elem,forceGraph); graphDataMount.mount(forceGraph,data); syncSelectedNodeHalo(forceGraph,data); graphFraming.frame(forceGraph,data.nodes,size); focusPendingCameraSelection(true); graphRendering.wake();} else {nodeHalo.clear();drawCanvasFallback(data,elem,state.current_track_id);} renderMoodStrip(data);}
function buildControls(){const root=document.getElementById('controls'); buildGraphControls(root);}
function buildGraphControls(root){graphFilterControls.mount(root);}
if(typeof document!=='undefined'){document.getElementById('undo').onclick=()=>applyHistorySelection('undo'); document.getElementById('reset').onclick=()=>applyHistorySelection('reset'); libraryLoading.mount(); buildControls(); renderTracks([]); renderGraphLoadStatus(); loadGraph().catch(()=>{}); refresh().catch(()=>{});}
// The opt-in diagnostics seam (#146, owner decision A): off unless the page address has `diagnostics`.
installExplorerDiagnostics(globalThis,globalThis.location?.search||'',{buses:[[GRAPH_LOAD_EVENT_TYPES,graphEvents],[GRAPH_RENDERING_EVENT_TYPES,renderingEvents],[CAMERA_FOCUS_EVENT_TYPES,cameraEvents],[TRACK_SEARCH_EVENT_TYPES,trackEvents],[TRACK_SELECTION_EVENT_TYPES,selectionEvents],[PLAYLIST_DOWNLOAD_EVENT_TYPES,playlistEvents],[LIBRARY_REFRESH_EVENT_TYPES,refreshEvents]],snapshot:diagnosticSnapshot,graph:()=>({model:graphModel,visible:visibleGraph,layout:graphFraming.layout()}),scene:()=>({graph:forceGraph,graphData:graphDataMount.current(),halo:nodeHalo.current(),findSceneObject,graphObjectTrackId}),views:()=>({trackMetadata:renderTrackMetadata,detailField:renderDetailField})});
function diagnosticSnapshot(){return {currentTrackId:state.current_track_id??null,selectionEpoch:state.selection_epoch??null,history:state.history||[],graphStatus:graphLoadState.status,cameraFocusActive:cameraFocusFrame!=null,pendingCameraTrackId:pendingCameraSelection,selectionPending:pendingSelectionOperation!=null,trackSearchStatus:trackSearchSession.searchState==='failed'?'error':trackSearchSession.searchState,trackResultCount:trackSearchSession.results.tracks.length};}
