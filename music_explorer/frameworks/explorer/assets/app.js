import {createPlaylistDownload} from './app/application/download-playlist/download-playlist.js';
import {PLAYLIST_DOWNLOAD_EVENT_TYPES} from './app/application/download-playlist/playlist-download-events.js';
import {playlistDownloadController} from './app/adapters/controllers/playlist-download-controller.js';
import {fetchExplorerApi} from './app/adapters/gateways/explorer-api-gateway.js';
import {playlistControlsViewModel, presentPlaylistDownloadEvent, presentRejectedPlaylistInput} from './app/adapters/presenters/playlist-download-presenter.js';
import {browserPlaylistFile} from './app/frameworks/browser-playlist-file.js';
import {createInMemoryEventBus} from './app/frameworks/in-memory-event-bus.js';
import {playlistDownloadView} from './app/frameworks/views/playlist-download-view.js';
import {displayNumber} from './app/domain/display-number.js';
import {applyMoodGraphFilters, EMPTY_GRAPH_CONTROLS, passesGraphFilters} from './app/domain/graph-filters.js';
import {moodGraphModel, moodNodeColor} from './app/domain/mood-graph.js';
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
import {fieldValues} from './app/domain/track-evidence.js';
import {detailFieldViewModel, scoreGaugeViewModel, trackDetailFailureViewModel, trackDetailLoadingViewModel, trackDetailViewModel, trackMetadataViewModel} from './app/adapters/presenters/track-detail-presenter.js';
import {trackDetailView} from './app/frameworks/views/track-detail-view.js';
import {sessionSelectionTickets} from './app/frameworks/session-selection-tickets.js';
import {awaitingServer} from './app/domain/track-selection.js';
import {createTrackSelection} from './app/application/select-track/select-track.js';
import {moodStripMarks} from './app/domain/mood-strip.js';
import {moodMarkDescription, moodStripViewModel} from './app/adapters/presenters/mood-strip-presenter.js';
import {moodStripView} from './app/frameworks/views/mood-strip-view.js';
import {graphCameraFrame} from './app/domain/camera-frame.js';
import {graphAxisSpec, graphColorLegend, graphRelatednessLegend, linkLabel, nodeLabel, relatednessLinkAlpha, relatednessLinkColor} from './app/adapters/presenters/graph-scene-presenter.js';
import {cameraArcPose, cameraFocusArc, cameraViewDirection, focusProgress, pickedNodePose, selectionFocusPose} from './app/domain/camera-arc.js';
import {createCameraFocus} from './app/application/focus-camera/focus-camera.js';
let state={current_track_id:null};
let graphModel={nodes:[],links:[],unpositioned:[],availableMoods:[],selectedMood:'',metadata:{},genreOptions:[]};
let visibleGraph={nodes:[],links:[],unpositioned:[]};
let forceGraph=null;
let framedGraphLayout=null;
let renderedGraphSignature=null;
let renderedGraphData={nodes:[],links:[]};
let graphResizeObserver=null;
let graphAxes=null;
let selectedNodeHalo=null;
let graphAxesAnimating=false;
let pendingGraphAxisSpec=[];
let selectedGraphControls=EMPTY_GRAPH_CONTROLS;
const playlistEvents=createInMemoryEventBus();
const explorerApi=fetchExplorerApi((path,options)=>fetch(path,options));
const playlistDownload=createPlaylistDownload({explorerApi,playlistFile:browserPlaylistFile(),eventBus:playlistEvents});
const playlistControls=playlistDownloadController({playlistDownload,currentTrackId:()=>state.current_track_id,rejectInput:message=>playlistControlsView.show(presentRejectedPlaylistInput(message))});
const playlistControlsView=playlistDownloadView({onControlsEdited:controls=>playlistControls.controlsEdited(controls),onDownloadRequested:controls=>playlistControls.downloadRequested(controls)});
for(const type of PLAYLIST_DOWNLOAD_EVENT_TYPES) playlistEvents.subscribe(type,event=>playlistControlsView.show(presentPlaylistDownloadEvent(event)));
const LEGACY_PLAYLIST_CONTROLS={m3uBpmMin:'bpmMin',m3uBpmMax:'bpmMax',m3uCount:'count',m3uDuration:'durationMinutes',m3uHarmonic:'harmonicMixing',m3uMinKeyStrength:'minimumKeyStrength',m3uArc:'energyArc',m3uEnergyLow:'energyLow',m3uEnergyHigh:'energyHigh',m3uMood:'moodHold'};
const selectionTickets=sessionSelectionTickets({storage:tabSessionStorage(),now:()=>Date.now(),random:()=>Math.random()});
let selectionEpoch=0;
let refreshRequestSeq=0;
let selectionState='none';
// Mirrors the selection's wait for the server for the browser probe and the diagnostics, until #146 step 8.
let pendingSelectionOperation=null;
let pendingCameraSelection=null;
let cameraViewIntentGeneration=0;
let cameraFocusGeneration=0;
let cameraFocusFrame=null;
// The camera variables above mirror the focus for the browser probe and the tests, until #146 step 8.
const legacyCameraFocusSession=Object.freeze({read:()=>({pendingTrackId:pendingCameraSelection,frame:cameraFocusFrame,viewIntent:cameraViewIntentGeneration,focusGeneration:cameraFocusGeneration}),write(changes){if('pendingTrackId' in changes) pendingCameraSelection=changes.pendingTrackId; if('frame' in changes) cameraFocusFrame=changes.frame; if('viewIntent' in changes) cameraViewIntentGeneration=changes.viewIntent; if('focusGeneration' in changes) cameraFocusGeneration=changes.focusGeneration;}});
const cameraEvents=createInMemoryEventBus();
const cameraFocus=createCameraFocus({focusSession:legacyCameraFocusSession,eventBus:cameraEvents});
cameraEvents.subscribe('camera-focus-cancelled',event=>{if(typeof cancelAnimationFrame==='function') cancelAnimationFrame(event.frame);});
let cameraFocusControls=null;
let loadingRefreshToken=0;
let lastRefreshError=null;
// Transitional (#146): trackSummaryPage and trackSummaryStatus mirror the search for the browser tests and tools.
let trackSearchSession={searchState:'idle',results:emptyTrackResults(),failure:null};
let trackSummaryPage={tracks:[],metadata:{},next_cursor:null,query:'',order:'title'};
let trackSummaryStatus='idle';
let graphLoadState={...GRAPH_IDLE_STATUS};
// Transitional (#146): the graph session lives in the page's variables, which the browser tests and
// tools still read and set, until the 3D scene and selection move into the layers.
const legacyGraphSession=Object.freeze({read:()=>({loadState:graphLoadState.status==='error'?'failed':graphLoadState.status,model:graphModel,visible:visibleGraph,controls:selectedGraphControls}),write(changes){if('model' in changes) graphModel=changes.model; if('visible' in changes) visibleGraph=changes.visible; if('controls' in changes) selectedGraphControls=changes.controls; if('loadState' in changes) graphLoadState={...graphLoadState,status:changes.loadState==='failed'?'error':changes.loadState};}});
const graphEvents=createInMemoryEventBus();
const graphLoad=createGraphLoad({explorerApi,graphSession:legacyGraphSession,clock:{nextFrame:()=>nextFrame()},eventBus:graphEvents,buildGraphModel:graph=>buildMoodGraphModel(graph)});
const graphControls=graphControlsController({graphLoad,rejectInput:message=>graphFilterControls.showRejection(message)});
const graphFilterControls=graphControlsView({onMoodChosen:mood=>graphControls.moodChosen(mood),onBpmRangeEdited:range=>graphControls.bpmRangeEdited(range),onGenresEdited:genres=>graphControls.genresEdited(genres),onFiltersCleared:()=>graphControls.filtersCleared()});
const graphStatusDisplay=graphStatusView({onReload:()=>loadGraph().catch(()=>{}),appendPlaylistControls:panel=>appendM3UDownloadControls(panel)});
function showGraphLoadEvent(event){const status=presentGraphLoadEvent(event); if(status) graphLoadState={...graphLoadState,...status}; renderGraphLoadStatus();}
graphEvents.subscribe('graph-controls-edited',event=>graphFilterControls.showValues(graphControlValuesViewModel(event.controls)));
graphEvents.subscribe('graph-load-started',event=>{invalidateCameraViewIntent(); showGraphLoadEvent(event);});
graphEvents.subscribe('graph-model-built',event=>{graphFilterControls.showOptions(graphControlOptionsViewModel(event.model,event.controls)); showGraphLoadEvent(event);});
graphEvents.subscribe('graph-render-due',event=>renderMap(event.visible));
graphEvents.subscribe('graph-ready',showGraphLoadEvent);
graphEvents.subscribe('graph-load-failed',showGraphLoadEvent);
graphEvents.subscribe('graph-filters-applied',event=>{invalidateCameraViewIntent(); if(event.shown) renderMap(event.visible); showGraphLoadEvent(event);});
const trackSearchStore=Object.freeze({read:()=>trackSearchSession,write(changes){trackSearchSession={...trackSearchSession,...changes}; const {results,searchState}=trackSearchSession; trackSummaryPage={tracks:results.tracks,metadata:results.metadata,next_cursor:results.nextCursor,query:results.query,order:'title'}; trackSummaryStatus=searchState==='failed'?'error':searchState;}});
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
selectionEvents.subscribe('track-chosen',()=>{selectionViewIntent=invalidateCameraViewIntent(); renderDetailLoading(); updateSelectedTrackVisuals();});
selectionEvents.subscribe('selection-rewinding',()=>{selectionViewIntent=invalidateCameraViewIntent(); renderDetailLoading();});
selectionEvents.subscribe('selection-accepted',event=>{if(selectionViewIntent!==cameraFocus.viewIntent()) return; cancelCameraFocus(); cameraFocus.request(event.focusCamera?event.trackId:null);});
selectionEvents.subscribe('selection-refused',event=>renderDetailError(event.failure));
selectionEvents.subscribe('library-selection-changed',event=>{cancelCameraFocus(); cameraFocus.request(event.trackId);});
selectionEvents.subscribe('no-track-selected',()=>{updateSelectedTrackVisuals(); renderInitialDetail();});
selectionEvents.subscribe('track-detail-loading',()=>{updateSelectedTrackVisuals(); renderDetailLoading();});
selectionEvents.subscribe('track-detail-loaded',event=>{renderDetail(event.detail); updateSelectedTrackVisuals();});
selectionEvents.subscribe('track-detail-failed',event=>renderDetailError(event.failure,()=>trackSelection.retryDetail()));
function tabSessionStorage(){try{return typeof sessionStorage!=='undefined'?sessionStorage:undefined;}catch(_error){return undefined;}}
function syncSelectionEpoch(snapshot){
  if(snapshot && typeof snapshot.selection_epoch==='number') selectionEpoch=snapshot.selection_epoch;
  return snapshot;
}
async function applyHistorySelection(action){if(await trackSelection.rewind(action)) await refresh();}
function text(el,value){el.textContent=value==null?'':String(value);return el;}
function nextFrame(){return new Promise(resolve=>{if(typeof requestAnimationFrame==='function') requestAnimationFrame(()=>resolve()); else setTimeout(resolve,0);});}
function loadingElements(){return {surface:typeof document!=='undefined'?(document.getElementById('library-loading')||document.getElementById('loading-surface')):null,status:typeof document!=='undefined'?document.getElementById('loading-status'):null,error:typeof document!=='undefined'?document.getElementById('loading-error'):null,retry:typeof document!=='undefined'?document.getElementById('loading-retry'):null};}
function setLoadingClass(surface,state){if(!surface) return; if(surface.classList){surface.classList.remove('active'); surface.classList.remove('refresh'); surface.classList.remove('error'); surface.classList.remove('done'); if(state) surface.classList.add(state);} else surface.className=state?'loading-surface '+state:'loading-surface';}
function setLoadingPhase(refreshToken,phase,detail){
  if(refreshToken!==refreshRequestSeq) return false;
  loadingRefreshToken=refreshToken;
  lastRefreshError=null;
  const {surface,status,error,retry}=loadingElements();
  if(surface){surface.hidden=false; setLoadingClass(surface,'refresh'); surface.setAttribute('aria-busy','false');}
  if(status){text(status,detail?`${phase}: ${detail}`:phase); status.removeAttribute('role'); status.setAttribute('role','status');}
  if(error){error.hidden=true; text(error,'');}
  if(retry) retry.hidden=true;
  return true;
}
function setLoadingError(refreshToken,message){
  if(refreshToken!==refreshRequestSeq) return false;
  lastRefreshError=String(message||'Loading failed');
  const {surface,status,error,retry}=loadingElements();
  if(surface){surface.hidden=false; setLoadingClass(surface,'refresh'); surface.setAttribute('aria-busy','false');}
  if(status) text(status,'Unable to load library');
  if(error){error.hidden=false; error.setAttribute('role','alert'); text(error,lastRefreshError);}
  if(retry){retry.hidden=false; retry.onclick=()=>refresh().catch(()=>{});}
  return true;
}
function clearLoading(refreshToken){
  if(refreshToken!==refreshRequestSeq) return false;
  const {surface,status,error,retry}=loadingElements();
  if(surface){surface.setAttribute('aria-busy','false'); setLoadingClass(surface,'done'); surface.hidden=true;}
  if(status) text(status,'Library loaded');
  if(error){error.hidden=true; text(error,'');}
  if(retry) retry.hidden=true;
  return true;
}
function abortStaleRefresh(refreshToken,selectionToken){
  if(refreshToken!==refreshRequestSeq) return true;
  if(selectionToken!==trackSelection.generation()){clearLoading(refreshToken); return true;}
  return false;
}
function selectedNodeValue(n){return n.id===state.current_track_id?4:1;}
function updateSelectedTrackVisuals(){
  if(typeof document!=='undefined') for(const row of document.querySelectorAll('#tracks tr[data-track-id]')){row.className=row.dataset.trackId===state.current_track_id?'current':''; const button=row.querySelector ? row.querySelector('button') : null; if(button){if(row.className) button.setAttribute('aria-current','true'); else button.removeAttribute('aria-current');}}
  if(forceGraph){wakeGraphRendering(); forceGraph.nodeVal(selectedNodeValue); if(typeof forceGraph.refresh==='function') forceGraph.refresh(); syncSelectedNodeHalo(forceGraph,visibleGraph); focusPendingCameraSelection();}
  else if(visibleGraph.nodes.length) renderCanvasFallback(visibleGraph);
  renderMoodStrip(visibleGraph);
}
function renderDetailLoading(){trackDetail.showLoading(trackDetailLoadingViewModel());}
function renderDetailError(error,retry){trackDetail.showFailure(trackDetailFailureViewModel(error),retry);}
function refreshSelectionDependent(generation){return trackSelection.loadDetail(generation);}
async function setCurrent(id,{focusCamera=true}={}){return trackSelection.choose(id,{focusCamera});}
async function refresh(){
  const refreshToken=++refreshRequestSeq;
  const token=trackSelection.generation();
  const operationPending=trackSelection.awaitingServer();
  try{
    setLoadingPhase(refreshToken,'Preparing library view');
    await nextFrame();
    if(abortStaleRefresh(refreshToken,token)) return;
    setLoadingPhase(refreshToken,'Loading library state');
    const refreshedState=await explorerApi.loadLibraryState();
    if(abortStaleRefresh(refreshToken,token)) return;
    // A refresh begun during a selection/history POST cannot reconcile its older snapshot.
    if(!operationPending) trackSelection.reconcile(refreshedState);
    renderGraphLoadStatus();
    if(abortStaleRefresh(refreshToken,token)) return;
    if(!operationPending) await refreshSelectionDependent(token);
    if(abortStaleRefresh(refreshToken,token)) return;
    if(graphLoadState.status==='ready') renderMap(visibleGraph);
    clearLoading(refreshToken);
  }catch(error){
    if(abortStaleRefresh(refreshToken,token)) return;
    setLoadingError(refreshToken,error&&error.message?error.message:error);
    throw error;
  }
}
function loadTrackSummaryPage(query,options){return trackSearch.loadPage({query,...options});}
function loadNextTrackSummaryPage(){return trackSearch.loadMore();}
function renderTracks(tracks){trackList.show(trackListViewModel({tracks,...trackSearchSession,currentTrackId:state.current_track_id}));}
function renderGraphLoadStatus(){graphStatusDisplay.show({status:graphLoadState.status,message:graphLoadState.message||GRAPH_IDLE_STATUS.message});}
function loadGraph(){return graphLoad.load();}

function appendM3UDownloadControls(panel){playlistControlsView.mount(panel,playlistControlsViewModel({draft:playlistDownload.draft(),downloadState:playlistDownload.downloadState(),moods:graphModel.availableMoods||[]}));}
function downloadM3UPlaylist(){return playlistDownload.download(state.current_track_id);}
function applyCurrentGraphFilters(){return graphLoad.applyFilters();}
function renderInitialDetail(){trackDetail.showNone();}
function fieldDisplay(field){return fieldValues(field);}
function detailGauge(label,value){return trackDetail.gauge(scoreGaugeViewModel(label,value));}
function renderDetailField(name,field){return trackDetail.field(detailFieldViewModel(name,field));}
function renderTrackMetadata(metadata){return trackDetail.metadata(trackMetadataViewModel(metadata));}
function renderDetail(detail){trackDetail.show(trackDetailViewModel(detail));}
function buildGraphModel(tracks, projection){return buildMoodGraphModel({positioned:tracks||[],edges:(projection&&projection.edges)||[],unpositioned:[],available_moods:[],selected_mood:'',metadata:{}});}
function applyGraphFilters(model, filters){return applyMoodGraphFilters(model,filters);}
function orbitCamera(c,dx,dy){c.yaw=(c.yaw||0)+dx*0.01; c.pitch=(c.pitch||0)+dy*0.01; return c;}
function panCamera(c,dx,dy){c.panX=(c.panX||0)+dx; c.panY=(c.panY||0)+dy; return c;}
function zoomCamera(c,delta){c.distance=(c.distance||0)+delta*0.01; return c;}
function canvasPoint(e,rect,canvas){const cw=canvas.clientWidth||rect.width, ch=canvas.clientHeight||rect.height, bx=canvas.clientLeft||0, by=canvas.clientTop||0; return {x:(e.clientX-rect.left-bx)*(canvas.width/cw),y:(e.clientY-rect.top-by)*(canvas.height/ch)};}
function buildMoodGraphModel(graph){return moodGraphModel(normalizeMoodAxisGraphDto(graph),{genreThresholdApplies:isIndexedMoodAxisGraph(graph)});}
// Raw selected-label means, never display-normalized z or camera coordinates.
function buildMoodStrip(data, selectedId){return moodStripMarks(data.nodes,selectedId).map(mark=>({...mark,description:moodMarkDescription(mark)}));}
function graphDimensions(elem){const parent=elem&&elem.parentElement; const style=parent&&typeof getComputedStyle==='function'?getComputedStyle(parent):null; const trim=style?['paddingLeft','paddingRight','borderLeftWidth','borderRightWidth'].reduce((sum,name)=>sum+(parseFloat(style[name])||0),0):0; const width=Math.max(1,Math.floor(((parent&&parent.clientWidth)||elem.clientWidth||900)-trim)); const height=Math.max(1,Math.floor(elem.clientHeight||1040)); return {width,height};}
function updateGraphSize(elem,graph){if(!elem||!graph) return {width:0,height:0}; const size=graphDimensions(elem); graph.width(size.width).height(size.height); wakeGraphRendering(); return size;}
function observeGraphResize(elem){if(graphResizeObserver||!elem) return; const resize=()=>updateGraphSize(elem,forceGraph); if(typeof ResizeObserver!=='undefined'){graphResizeObserver=new ResizeObserver(resize); graphResizeObserver.observe(elem); if(elem.parentElement) graphResizeObserver.observe(elem.parentElement);} if(typeof window!=='undefined') window.addEventListener('resize',resize);}
function disposeGraphAxes(group){
  if(!group) return;
  group.parent.remove(group);
  for(const mesh of group.children){mesh.geometry.dispose();mesh.material.dispose();}
  if(group.labels) for(const label of group.labels) label.remove();
}

function disposeSelectedNodeHalo(){
  const halo=selectedNodeHalo&&selectedNodeHalo.mesh;
  if(!halo){selectedNodeHalo=null;return;}
  if(halo.parent&&typeof halo.parent.remove==='function') halo.parent.remove(halo);
  else if(selectedNodeHalo.scene&&typeof selectedNodeHalo.scene.remove==='function') selectedNodeHalo.scene.remove(halo);
  if(halo.geometry&&typeof halo.geometry.dispose==='function') halo.geometry.dispose();
  if(halo.material&&typeof halo.material.dispose==='function') halo.material.dispose();
  halo.disposed=true;
  selectedNodeHalo=null;
}
function graphObjectTrackId(obj){
  const data=obj&&(obj.__data||obj.userData||{});
  return data.id||data.trackId||data.track_id||(data.node&&data.node.id)||null;
}
function updateHaloPosition(halo,node,selectedMesh){
  const sourcePosition=selectedMesh&&selectedMesh.position;
  const x=Number.isFinite(sourcePosition&&sourcePosition.x)?sourcePosition.x:node.x;
  const y=Number.isFinite(sourcePosition&&sourcePosition.y)?sourcePosition.y:node.y;
  const z=Number.isFinite(sourcePosition&&sourcePosition.z)?sourcePosition.z:node.z;
  if(halo.position&&typeof halo.position.set==='function') halo.position.set(x,y,z); else halo.position={x,y,z};
}
function sceneChildren(root){return root&&Array.isArray(root.children)?root.children:[];}
function findSceneObject(root,predicate){
  if(!root) return null;
  if(predicate(root)) return root;
  for(const child of sceneChildren(root)){const found=findSceneObject(child,predicate); if(found) return found;}
  return null;
}
function selectedHaloRadius(mesh){
  const geometry=mesh&&mesh.geometry;
  const base=geometry&&(Number.isFinite(geometry.radius)?geometry.radius:(geometry.parameters&&Number.isFinite(geometry.parameters.radius)?geometry.parameters.radius:1));
  const scale=mesh&&mesh.scale;
  const scalar=scale&&(Number.isFinite(scale.value)?scale.value:(Number.isFinite(scale.x)?Math.max(scale.x,scale.y||scale.x,scale.z||scale.x):1));
  return Math.max(1,(base||1)*(scalar||1))*1.3;
}
function makeFallbackHalo(node){
  return {name:'selected-node-halo',userData:{role:'selected-node-halo',trackId:node.id},geometry:{radius:1.3,dispose(){this.disposed=true;}},material:{color:'#f8f7ff',transparent:true,opacity:0.25,depthWrite:false,depthTest:false,dispose(){this.disposed=true;}},position:{set(x,y,z){this.x=x;this.y=y;this.z=z;}},scale:{setScalar(value){this.value=value;}},raycast(){}};
}
function createSelectedNodeHalo(graph,scene,node,selectedMesh){
  const three=selectedMesh&&selectedMesh.__THREE;
  const Geometry=(three&&three.SphereGeometry)||(selectedMesh&&selectedMesh.geometry&&selectedMesh.geometry.constructor);
  const Material=(three&&three.MeshBasicMaterial)||(selectedMesh&&selectedMesh.material&&selectedMesh.material.constructor);
  const Mesh=(three&&three.Mesh)||((selectedMesh&&selectedMesh.constructor));
  const realThreeScene=scene&&(scene.isScene||scene.type==='Scene');
  let halo;
  if(Geometry&&Material&&Mesh){
    const radius=selectedHaloRadius(selectedMesh);
    halo=new Mesh(new Geometry(radius,32,16),new Material({color:node.color==='#f8f7ff'?'#ffcc66':'#f8f7ff',transparent:true,opacity:0.25,depthWrite:false,depthTest:false}));
    halo.name='selected-node-halo';
    halo.userData={...(halo.userData||{}),role:'selected-node-halo',trackId:node.id};
    halo.raycast=()=>{};
  }else if(realThreeScene) return null;
  else halo=makeFallbackHalo(node);
  updateHaloPosition(halo,node,selectedMesh);
  scene.add(halo);
  selectedNodeHalo={graph,scene,mesh:halo,trackId:node.id,nodeMesh:selectedMesh||null};
  return halo;
}
function cachedSelectedNodeMesh(graph,scene,selectedId){
  if(!selectedNodeHalo||selectedNodeHalo.graph!==graph||selectedNodeHalo.scene!==scene||selectedNodeHalo.trackId!==selectedId) return null;
  const halo=selectedNodeHalo.mesh;
  if(!halo||halo.disposed||halo.parent===null) return null;
  const mesh=selectedNodeHalo.nodeMesh;
  if(!mesh||mesh.disposed||mesh.parent===null) return null;
  return mesh;
}
function syncSelectedNodeHalo(graph,data){
  if(!graph||typeof graph.scene!=='function'){disposeSelectedNodeHalo();return null;}
  const selectedId=state.current_track_id;
  const nodes=(data&&data.nodes)||(visibleGraph&&visibleGraph.nodes)||[];
  const selectedNode=selectedId?nodes.find(n=>n.id===selectedId):null;
  const scene=graph.scene();
  if(!selectedNode||!scene||typeof scene.add!=='function'){disposeSelectedNodeHalo();return null;}
  const cachedMesh=cachedSelectedNodeMesh(graph,scene,selectedId);
  if(cachedMesh){updateHaloPosition(selectedNodeHalo.mesh,selectedNode,cachedMesh);return selectedNodeHalo.mesh;}
  if(selectedNodeHalo&&selectedNodeHalo.graph===graph&&selectedNodeHalo.trackId===selectedId) disposeSelectedNodeHalo();
  const selectedMesh=findSceneObject(scene,obj=>obj!==scene && graphObjectTrackId(obj)===selectedId && obj.name!=='selected-node-halo' && !(obj.userData&&obj.userData.role==='selected-node-halo') && obj.geometry && obj.material);
  if(selectedNodeHalo&&selectedNodeHalo.graph===graph&&selectedNodeHalo.trackId===selectedId){updateHaloPosition(selectedNodeHalo.mesh,selectedNode,selectedMesh);selectedNodeHalo.nodeMesh=selectedMesh||null;return selectedNodeHalo.mesh;}
  disposeSelectedNodeHalo();
  return createSelectedNodeHalo(graph,scene,selectedNode,selectedMesh);
}
// Vendor bundles THREE privately. Reuse constructors of its rendered node mesh, so
// scene objects share that exact THREE instance without a second dependency/global.
function syncGraphAxes(graph,spec,element){
  const signature=JSON.stringify(spec);
  if(graphAxes && graphAxes.graph===graph && graphAxes.signature===signature) return graphAxes.group;
  const scene=graph.scene();
  if(!spec.length){disposeGraphAxes(graphAxes?.group);graphAxes=null;return null;}
  const findNode=obj=>obj.__graphObjType==='node' && obj.geometry && obj.material ? obj : sceneChildren(obj).map(findNode).find(Boolean);
  const sample=findNode(scene);
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
// Render on demand. The bundled loop redraws WebGL every frame even when the view
// is still, which under software rendering starves the main thread (#86). Keep it
// running only while the view can change; input, a moved pose, new data, a
// selection or a resize wakes it, and it pauses once quiet for graphRenderIdleMs.
const graphRenderIdleMs=500;
let graphRenderLoop={paused:false,pose:null,quietSince:null};
function graphViewPose(graph){
  const camera=graph.camera?.(), controls=graph.controls?.();
  const v=p=>p?[p.x,p.y,p.z,p.w]:null;
  return JSON.stringify([v(camera?.position),v(camera?.quaternion),v(camera?.up),v(controls?.target)]);
}
// resumeAnimation draws synchronously. Outside a frame callback, defer it to the
// next frame boundary so an input, fetch or selection handler is not delayed.
function wakeGraphRendering(inFrame=false){
  graphRenderLoop.quietSince=null;
  if(!graphRenderLoop.paused||!forceGraph) return;
  graphRenderLoop.paused=false;
  const graph=forceGraph;
  const resume=()=>{if(!graphRenderLoop.paused&&graph===forceGraph&&typeof graph.resumeAnimation==='function') graph.resumeAnimation();};
  if(inFrame) resume(); else requestAnimationFrame(resume);
}
function settleGraphRendering(graph,now){
  if(graphRenderLoop.quietSince===null){graphRenderLoop.quietSince=now; return;}
  if(now-graphRenderLoop.quietSince<graphRenderIdleMs||typeof graph.pauseAnimation!=='function') return;
  graph.pauseAnimation(); graphRenderLoop.paused=true;
}
function observeGraphInput(elem){
  if(!elem||typeof elem.addEventListener!=='function') return;
  // Controls and hover picking update only inside the vendor loop.
  for(const type of ['pointerdown','pointermove','wheel']) elem.addEventListener(type,()=>wakeGraphRendering(),{capture:true,passive:true});
}
function animateGraphAxes(timestamp){
  if(forceGraph){
    const pose=graphViewPose(forceGraph);
    if(pose!==graphRenderLoop.pose){graphRenderLoop.pose=pose; wakeGraphRendering(true);}
    if(!graphRenderLoop.paused){
      syncGraphAxes(forceGraph,pendingGraphAxisSpec,document.getElementById('graph3d'));placeGraphAxisLabels(forceGraph);syncSelectedNodeHalo(forceGraph,visibleGraph);
      settleGraphRendering(forceGraph,Number.isFinite(timestamp)?timestamp:performance.now());
    }
  }
  requestAnimationFrame(animateGraphAxes);
}
// View ownership outlives a POST or a deferred layout, independently of the RAF timeline.
// Cancel through the page's own cancelCameraFocus first: the browser diagnostic observes cancellations there.
function invalidateCameraViewIntent(){cancelCameraFocus(); return cameraFocus.claimView();}
// Own the timeline: bundled cameraPosition's timed tweens have no public cancellation.
function cancelCameraFocus(){cameraFocus.cancel();}
function observeCameraFocusControls(graph){
  const controls=typeof graph?.controls==='function'?graph.controls():null;
  if(controls===cameraFocusControls) return;
  cancelCameraFocus();
  if(cameraFocusControls?.removeEventListener) cameraFocusControls.removeEventListener('start',invalidateCameraViewIntent);
  cameraFocusControls=controls;
  if(controls?.addEventListener) controls.addEventListener('start',invalidateCameraViewIntent);
}
// Disabled bundled cameraPosition looks at the point but leaves its orbit
// target stale. Keep the public target synchronized for update and re-enable.
function setCameraFocusPose(graph,position,target){
  const controls=graph.controls?.();
  if(controls?.target) Object.assign(controls.target,target);
  graph.cameraPosition(position,target,0);
}
// Drain pending rotation/wheel/pan once through Trackball's public API. Zero
// speeds consume input endpoints; full dynamic damping clears residual rotation.
// A canonical pose keeps the update safe even when the original radius overflows.
function settleCameraFocusInput(graph){
  const controls=graph.controls(), camera=graph.camera();
  if(typeof controls.update!=='function') return;
  const position={...graph.cameraPosition()}, target={...controls.target};
  const up=camera.up?{...camera.up}:null;
  const orientation=camera.quaternion?.clone?camera.quaternion.clone():null;
  const settings={staticMoving:controls.staticMoving,dynamicDampingFactor:controls.dynamicDampingFactor,
    rotateSpeed:controls.rotateSpeed,zoomSpeed:controls.zoomSpeed,
    panSpeed:controls.panSpeed,noZoom:controls.noZoom,noPan:controls.noPan,
    noRotate:controls.noRotate,minDistance:controls.minDistance,maxDistance:controls.maxDistance};
  try {
    Object.assign(controls,{staticMoving:false,dynamicDampingFactor:1,rotateSpeed:0,zoomSpeed:0,panSpeed:0,
      noZoom:false,noPan:false,noRotate:false,minDistance:0,maxDistance:Infinity});
    if(camera.up?.set) camera.up.set(0,1,0);
    setCameraFocusPose(graph,{x:0,y:0,z:100},{x:0,y:0,z:0});
    controls.update();
  } finally {
    Object.assign(controls,settings);
    if(up && camera.up?.set) camera.up.set(up.x,up.y,up.z);
    setCameraFocusPose(graph,position,target);
    if(orientation) camera.quaternion.copy(orientation);
  }
}
function animateCameraFocus(graph,position,target){
  observeCameraFocusControls(graph);
  cancelCameraFocus();
  const generation=cameraFocus.begin();
  settleCameraFocusInput(graph);
  const camera=graph.camera();
  const arc=cameraFocusArc({fromPosition:{...graph.cameraPosition()},fromTarget:{...graph.controls().target},fromUp:camera.up?{...camera.up}:null,position,target});
  const clockNow=()=>typeof performance!=='undefined'?performance.now():Date.now();
  const started=clockNow();
  const step=timestamp=>{
    if(graph!==forceGraph || !cameraFocus.frameRan(generation)) return;
    const progress=focusProgress(started,Number.isFinite(timestamp)?timestamp:clockNow());
    const pose=cameraArcPose(arc,progress);
    if(pose.up && camera.up?.set) camera.up.set(pose.up.x,pose.up.y,pose.up.z);
    setCameraFocusPose(graph,pose.position,pose.target);
    if(progress<1) cameraFocus.frameScheduled(generation,requestAnimationFrame(step)); else cameraFocus.finished(generation);
  };
  cameraFocus.frameScheduled(generation,requestAnimationFrame(step));
}
// Graph picks own the view immediately; server acceptance still owns detail.
function selectGraphNode(picked){
  const id=picked?.id;
  if(typeof id!=='string' || !id) return;
  cancelCameraFocus();
  cameraFocus.request(null);
  // A replacement can be visible-but-not-mounted during loadGraph's frame gap.
  const node=visibleGraph.nodes.some(n=>n.id===id)
    ?renderedGraphData.nodes.find(n=>n.id===id):null;
  if(forceGraph && node){
    try {
      const controls=forceGraph.controls(), from=forceGraph.cameraPosition();
      const pose=pickedNodePose({x:node.fx,y:node.fy,z:node.fz},{cameraPosition:from,orbitTarget:controls.target});
      if(pose){
        observeCameraFocusControls(forceGraph);
        settleCameraFocusInput(forceGraph);
        setCameraFocusPose(forceGraph,pose.position,pose.target);
      }
    } catch(error) {
      // An unavailable camera must not prevent a valid track selection.
      cancelCameraFocus();
    }
  }
  return setCurrent(id,{focusCamera:false});
}
// Accepted selection gets one focus after initial framing, never a per-frame camera lock.
function focusPendingCameraSelection(graphRendered=false){
  // Existing instances still show the old layout while a replacement loads.
  // Only renderMap may consume focus before the load state becomes ready.
  if(!graphRendered && graphLoadState.status!=='ready') return;
  if(!forceGraph || framedGraphLayout===null || cameraFocus.peek()==null) return;
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
    cancelCameraFocus();
  }
}
function renderMoodStrip(data){moodStrip.show(moodStripViewModel(moodStripMarks(data.nodes,state.current_track_id),moodStrip.width()));}
function renderMap(data){pendingGraphAxisSpec=graphAxisSpec(graphModel.nodes.length?graphModel.nodes:data.nodes);const elem=document.getElementById('graph3d')||replaceCanvasWithGraphElement(); if(typeof ForceGraph3D==='function'){if(!forceGraph){forceGraph=ForceGraph3D()(elem).enableNodeDrag(false).cooldownTicks(0).nodeId('id').nodeRelSize(4).nodeLabel(nodeLabel).nodeColor(n=>n.color).nodeVal(selectedNodeValue).linkLabel(linkLabel).linkOpacity(1).linkColor(relatednessLinkColor).linkWidth(l=>1+Math.max(0,Number(l.score)||0)); forceGraph.onNodeClick(selectGraphNode); observeGraphResize(elem); observeGraphInput(elem); if(!graphAxesAnimating && typeof requestAnimationFrame==='function'){graphAxesAnimating=true;requestAnimationFrame(animateGraphAxes);}} observeCameraFocusControls(forceGraph); const size=updateGraphSize(elem,forceGraph); const signature=JSON.stringify([data.nodes.map(n=>[n.id,n.x,n.y,n.z]),data.links.map(l=>[l.source,l.target,l.score])]); if(signature!==renderedGraphSignature){disposeSelectedNodeHalo(); renderedGraphData={nodes:data.nodes.map(n=>Object.assign({},n,{fx:n.fx,fy:n.fy,fz:n.fz})),links:data.links.map(l=>Object.assign({},l))}; forceGraph.graphData(renderedGraphData); renderedGraphSignature=signature;} else {const live=new Map(data.nodes.map(n=>[n.id,n])); for(const node of renderedGraphData.nodes){const updated=live.get(node.id); if(updated){node.moodScore=updated.moodScore; node.axis=updated.axis;}}} syncSelectedNodeHalo(forceGraph,data); forceGraph.numDimensions(3); forceGraph.d3AlphaDecay(1); forceGraph.d3VelocityDecay(1); const layout=JSON.stringify(data.nodes.map(n=>JSON.stringify([n.id,n.x,n.y,n.z])).sort()); if(layout!==framedGraphLayout){const frame=graphCameraFrame(data.nodes,size,forceGraph.camera().fov); /* Synchronize the orbit target even when bundled controls are disabled. */ cancelCameraFocus(); setCameraFocusPose(forceGraph,frame.position,frame.target); framedGraphLayout=layout;} focusPendingCameraSelection(true); wakeGraphRendering();} else {disposeSelectedNodeHalo();renderCanvasFallback(data,elem);} renderMoodStrip(data);}
function replaceCanvasWithGraphElement(){const old=document.getElementById('map'); const div=document.createElement('div'); div.id='graph3d'; if(old) old.replaceWith(div); return div;}
function renderCanvasFallback(data,container){let canvas=document.getElementById('map'); if(!canvas&&container){canvas=(container.children||[]).find(child=>child.tagName==='CANVAS')||document.createElement('canvas'); canvas.id='map'; if(!canvas.parentElement){if(typeof container.replaceChildren==='function') container.replaceChildren(canvas); else if(typeof container.append==='function') container.append(canvas);}} if(!canvas) canvas=document.createElement('canvas'); const size=graphDimensions(canvas); canvas.width=size.width; canvas.height=size.height; const ctx=canvas.getContext('2d'); ctx.clearRect(0,0,canvas.width,canvas.height); ctx.fillStyle='#fafafa'; ctx.fillRect(0,0,canvas.width,canvas.height); for(const n of data.nodes){ctx.beginPath(); ctx.arc(canvas.width/2+n.fx,canvas.height/2-n.fy,n.id===state.current_track_id?9:5,0,Math.PI*2); ctx.fillStyle=n.color; ctx.fill();}}
function buildControls(){const root=document.getElementById('controls'); buildGraphControls(root);}
function clearGraphFilters(){return graphLoad.clearFilters();}
function buildGraphControls(root){graphFilterControls.mount(root);}
function syncGraphControlOptions(model){graphFilterControls.showOptions(graphControlOptionsViewModel(model,selectedGraphControls));}
function wireCanvas(){/* 3d-force-graph owns orbit/pick controls. */}
if(typeof document!=='undefined'){document.getElementById('undo').onclick=()=>applyHistorySelection('undo'); document.getElementById('reset').onclick=()=>applyHistorySelection('reset'); const retry=document.getElementById('loading-retry'); if(retry) retry.onclick=()=>refresh().catch(()=>{}); buildControls(); renderTracks([]); renderGraphLoadStatus(); wireCanvas(); loadGraph().catch(()=>{}); refresh().catch(()=>{});}
function setGraphModelForTesting(model){graphModel=model;}
function setStateForTesting(next){state={...state,...next};}
function setVisibleGraphForTesting(model){visibleGraph=model;}
function setGraphControlsForTesting(controls){const playlist={}; const graph={}; for(const [name,value] of Object.entries(controls||{})){if(Object.hasOwn(LEGACY_PLAYLIST_CONTROLS,name)) playlist[LEGACY_PLAYLIST_CONTROLS[name]]=value; else graph[name]=value;} if(Object.keys(playlist).length) playlistDownload.edit(playlist); if(Object.keys(graph).length) graphLoad.editControls(graph);}
function getGraphControlsForTesting(){return {...selectedGraphControls,genres:[...(selectedGraphControls.genres||[])]};}
function getVisibleGraphForTesting(){return {nodes:[...(visibleGraph.nodes||[])],links:[...(visibleGraph.links||[])],unpositioned:[...(visibleGraph.unpositioned||[])]};}
function getStateForTesting(){return {...state,history:[...(state.history||[])]};}
if(typeof module!=='undefined'){module.exports={refresh,updateSelectedTrackVisuals,renderMap,syncSelectedNodeHalo,setLoadingPhase,setLoadingError,clearLoading,nextFrame,detailGauge,displayNumber,graphAxisSpec,syncGraphAxes,buildMoodStrip,nodeLabel,normalizeMoodAxisGraphDto,buildMoodGraphModel,moodNodeColor,graphColorLegend,applyMoodGraphFilters,passesGraphFilters,buildGraphModel,applyGraphFilters,orbitCamera,panCamera,zoomCamera,canvasPoint,fieldDisplay,graphDimensions,updateGraphSize,graphCameraFrame,syncSelectionEpoch,renderInitialDetail,renderDetail,renderTrackMetadata,setGraphModelForTesting,setVisibleGraphForTesting,setStateForTesting,getStateForTesting,loadGraph,applyCurrentGraphFilters,renderGraphLoadStatus,renderTracks,loadTrackSummaryPage,loadNextTrackSummaryPage,graphRelatednessLegend,relatednessLinkAlpha,buildGraphControls,syncGraphControlOptions,clearGraphFilters,downloadM3UPlaylist,setGraphControlsForTesting,getGraphControlsForTesting,getVisibleGraphForTesting};}
// Transitional (#146). The real-browser tests and tools/explorer_browser_*.{py,js} read these
// internals as page globals, and wrap some functions to time them, which a module does not allow.
// A setter rebinds the module's own function, so a wrapper is called exactly as before. Each name
// goes as its feature moves into app/ and its tests move with it.
function exposeForBrowserTests(readers, writers){for(const [name,get] of Object.entries(readers)){if(name in globalThis) continue; Object.defineProperty(globalThis,name,{get,set:writers[name],configurable:true});}}
exposeForBrowserTests({state:()=>state,graphModel:()=>graphModel,visibleGraph:()=>visibleGraph,forceGraph:()=>forceGraph,framedGraphLayout:()=>framedGraphLayout,renderedGraphData:()=>renderedGraphData,graphAxes:()=>graphAxes,selectedNodeHalo:()=>selectedNodeHalo,pendingSelectionOperation:()=>pendingSelectionOperation,pendingCameraSelection:()=>pendingCameraSelection,cameraFocusFrame:()=>cameraFocusFrame,trackSummaryPage:()=>trackSummaryPage,trackSummaryStatus:()=>trackSummaryStatus,graphLoadState:()=>graphLoadState,text:()=>text,renderDetailLoading:()=>renderDetailLoading,setCurrent:()=>setCurrent,renderTracks:()=>renderTracks,renderDetailField:()=>renderDetailField,renderTrackMetadata:()=>renderTrackMetadata,renderDetail:()=>renderDetail,buildMoodGraphModel:()=>buildMoodGraphModel,buildMoodStrip:()=>buildMoodStrip,graphAxisSpec:()=>graphAxisSpec,graphObjectTrackId:()=>graphObjectTrackId,findSceneObject:()=>findSceneObject,syncSelectedNodeHalo:()=>syncSelectedNodeHalo,syncGraphAxes:()=>syncGraphAxes,cancelCameraFocus:()=>cancelCameraFocus,animateCameraFocus:()=>animateCameraFocus,renderMap:()=>renderMap,setStateForTesting:()=>setStateForTesting},
  {buildMoodGraphModel:value=>{buildMoodGraphModel=value;},renderMap:value=>{renderMap=value;},renderDetail:value=>{renderDetail=value;},renderDetailLoading:value=>{renderDetailLoading=value;},setCurrent:value=>{setCurrent=value;},animateCameraFocus:value=>{animateCameraFocus=value;},cancelCameraFocus:value=>{cancelCameraFocus=value;}});
