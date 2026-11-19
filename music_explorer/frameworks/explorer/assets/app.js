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
let selectionRequestSeq=0;
const selectionTickets=sessionSelectionTickets({storage:tabSessionStorage(),now:()=>Date.now(),random:()=>Math.random()});
let selectionEpoch=0;
let refreshRequestSeq=0;
let selectionDetailRequestSeq=0;
let selectionDetailFlight=null;
let pendingSelectionIntent=null;
let pendingSelectionOperation=null;
let pendingCameraSelection=null;
let cameraViewIntentGeneration=0;
let cameraFocusGeneration=0;
let cameraFocusFrame=null;
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
function tabSessionStorage(){try{return typeof sessionStorage!=='undefined'?sessionStorage:undefined;}catch(_error){return undefined;}}
function syncSelectionEpoch(snapshot){
  if(snapshot && typeof snapshot.selection_epoch==='number') selectionEpoch=snapshot.selection_epoch;
  return snapshot;
}
function invalidateSelectionIntent(){invalidateCameraViewIntent(); selectionRequestSeq++; pendingSelectionIntent=null; pendingSelectionOperation=null; pendingCameraSelection=null;}
async function applyHistorySelection(action){
  const viewIntentGeneration=invalidateCameraViewIntent();
  const token=++selectionRequestSeq;
  pendingCameraSelection=null;
  pendingSelectionIntent=null;
  pendingSelectionOperation=token;
  renderDetailLoading();
  try{
    const posted=await explorerApi.applyHistory(action);
    if(token!==selectionRequestSeq) return;
    state=syncSelectionEpoch(posted);
    if(viewIntentGeneration===cameraViewIntentGeneration){
      cancelCameraFocus();
      pendingCameraSelection=state.current_track_id;
    }
    pendingSelectionOperation=null;
    await refresh();
  }catch(error){
    if(token!==selectionRequestSeq) return;
    pendingSelectionOperation=null;
    renderDetailError(error);
  }
}
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
  if(selectionToken!==selectionRequestSeq){clearLoading(refreshToken); return true;}
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
async function refreshSelectionDependent(token){
  if(token!==selectionRequestSeq || pendingSelectionOperation!==null || pendingSelectionIntent!==null) return;
  const selectedId=state.current_track_id;
  if(selectionDetailFlight && selectionDetailFlight.token===token && selectionDetailFlight.id===selectedId) return selectionDetailFlight.promise;
  const detailToken=++selectionDetailRequestSeq;
  const ownsDetail=()=>token===selectionRequestSeq && detailToken===selectionDetailRequestSeq && state.current_track_id===selectedId;
  updateSelectedTrackVisuals();
  if(!selectedId){renderInitialDetail(graphModel); return;}
  renderDetailLoading();
  const flight={token,id:selectedId,promise:null};
  selectionDetailFlight=flight;
  flight.promise=(async()=>{
    try{
      const detail=await explorerApi.loadTrackDetail(selectedId);
      if(!ownsDetail()) return;
      renderDetail(detail); updateSelectedTrackVisuals();
    }catch(error){
      if(!ownsDetail()) return;
      renderDetailError(error,()=>{
        if(!ownsDetail() || pendingSelectionOperation!==null || pendingSelectionIntent!==null) return;
        return refreshSelectionDependent(token);
      });
    }finally{
      if(selectionDetailFlight===flight) selectionDetailFlight=null;
    }
  })();
  return flight.promise;
}
async function setCurrent(id,{focusCamera=true}={}){
  const viewIntentGeneration=invalidateCameraViewIntent();
  const token=++selectionRequestSeq;
  const selectionToken=selectionTickets.nextTicket();
  pendingCameraSelection=null;
  pendingSelectionIntent=id;
  pendingSelectionOperation=token;
  state={...state,current_track_id:id};
  renderDetailLoading();
  updateSelectedTrackVisuals();
  try{
    const posted=await explorerApi.chooseCurrentTrack({trackId:id,selectionToken,selectionEpoch,clientId:selectionTickets.clientId()});
    if(token!==selectionRequestSeq) return;
    state=syncSelectionEpoch(posted);
    if(viewIntentGeneration===cameraViewIntentGeneration){
      cancelCameraFocus();
      pendingCameraSelection=focusCamera?state.current_track_id:null;
    }
    pendingSelectionIntent=null;
    pendingSelectionOperation=null;
    await refreshSelectionDependent(token);
  }catch(error){
    if(token!==selectionRequestSeq) return;
    pendingSelectionOperation=null;
    pendingSelectionIntent=null;
    // An unaccepted intent never authorizes a detail GET, including via retry.
    renderDetailError(error);
  }
}
async function refresh(){
  const refreshToken=++refreshRequestSeq;
  const token=selectionRequestSeq;
  const operationPending=pendingSelectionOperation!==null;
  try{
    setLoadingPhase(refreshToken,'Preparing library view');
    await nextFrame();
    if(abortStaleRefresh(refreshToken,token)) return;
    setLoadingPhase(refreshToken,'Loading library state');
    const refreshedState=await explorerApi.loadLibraryState();
    if(abortStaleRefresh(refreshToken,token)) return;
    // A refresh begun during a selection/history POST cannot reconcile its older snapshot.
    if(!operationPending && pendingSelectionOperation===null){
      if(state.current_track_id!==refreshedState.current_track_id){cancelCameraFocus(); pendingCameraSelection=refreshedState.current_track_id;}
      state=syncSelectionEpoch(refreshedState);
    }
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
function renderInitialDetail(model){const root=document.getElementById('detail'); if(!root) return; root.setAttribute('aria-busy','false'); root.replaceChildren();}
function fieldDisplay(field){return fieldValues(field);}
function detailGauge(label,value){return trackDetail.gauge(scoreGaugeViewModel(label,value));}
function renderDetailField(name,field){return trackDetail.field(detailFieldViewModel(name,field));}
function graphRelatednessLegend(){return 'Link alpha reflects axis-independent relatedness strength from existing stored summaries; higher-score links are more opaque.';}
function relatednessLinkAlpha(link){const score=Number(link&&link.score); const clamped=Number.isFinite(score)?Math.max(0,Math.min(1,score)):0; return Math.round((0.18+clamped*0.54)*100)/100;}
function relatednessLinkColor(link){return `rgba(240,240,240,${relatednessLinkAlpha(link)})`;}
function renderTrackMetadata(metadata){return trackDetail.metadata(trackMetadataViewModel(metadata));}
function renderDetail(detail){trackDetail.show(trackDetailViewModel(detail));}
function buildGraphModel(tracks, projection){return buildMoodGraphModel({positioned:tracks||[],edges:(projection&&projection.edges)||[],unpositioned:[],available_moods:[],selected_mood:'',metadata:{}});}
function applyGraphFilters(model, filters){return applyMoodGraphFilters(model,filters);}
function orbitCamera(c,dx,dy){c.yaw=(c.yaw||0)+dx*0.01; c.pitch=(c.pitch||0)+dy*0.01; return c;}
function panCamera(c,dx,dy){c.panX=(c.panX||0)+dx; c.panY=(c.panY||0)+dy; return c;}
function zoomCamera(c,delta){c.distance=(c.distance||0)+delta*0.01; return c;}
function canvasPoint(e,rect,canvas){const cw=canvas.clientWidth||rect.width, ch=canvas.clientHeight||rect.height, bx=canvas.clientLeft||0, by=canvas.clientTop||0; return {x:(e.clientX-rect.left-bx)*(canvas.width/cw),y:(e.clientY-rect.top-by)*(canvas.height/ch)};}
function graphColorLegend(model){const r=model.colorRanges||{}; const endpoints=range=>Array.isArray(range)?range:(range&&Number.isFinite(range.min)&&Number.isFinite(range.max)?[range.min,range.max]:null); const display=range=>{const e=endpoints(range); return e?`${displayNumber(e[0])} to ${displayNumber(e[1])}`:'no positioned values';}; return `Color relative to this library: valence blue → orange/red (${display(r.valence)} native); arousal dark/dim → bright (${display(r.arousal)} native). Selected node is larger.`;}
function buildMoodGraphModel(graph){return moodGraphModel(normalizeMoodAxisGraphDto(graph),{genreThresholdApplies:isIndexedMoodAxisGraph(graph)});}
// Raw selected-label means, never display-normalized z or camera coordinates.
function buildMoodStrip(data, selectedId){return data.nodes.filter(n=>n.moodScore!=null).map(n=>({id:n.id,label:n.label,score:n.moodScore.raw,position:n.moodScore.raw,selected:n.id===selectedId,description:`${n.label}: ${n.moodScore.label} ${displayNumber(n.moodScore.raw)} / 1 (raw sigmoid mean score)`})).sort((a,b)=>a.score-b.score || (a.id<b.id?-1:a.id>b.id?1:0));}
function graphDimensions(elem){const parent=elem&&elem.parentElement; const style=parent&&typeof getComputedStyle==='function'?getComputedStyle(parent):null; const trim=style?['paddingLeft','paddingRight','borderLeftWidth','borderRightWidth'].reduce((sum,name)=>sum+(parseFloat(style[name])||0),0):0; const width=Math.max(1,Math.floor(((parent&&parent.clientWidth)||elem.clientWidth||900)-trim)); const height=Math.max(1,Math.floor(elem.clientHeight||1040)); return {width,height};}
function updateGraphSize(elem,graph){if(!elem||!graph) return {width:0,height:0}; const size=graphDimensions(elem); graph.width(size.width).height(size.height); wakeGraphRendering(); return size;}
function observeGraphResize(elem){if(graphResizeObserver||!elem) return; const resize=()=>updateGraphSize(elem,forceGraph); if(typeof ResizeObserver!=='undefined'){graphResizeObserver=new ResizeObserver(resize); graphResizeObserver.observe(elem); if(elem.parentElement) graphResizeObserver.observe(elem.parentElement);} if(typeof window!=='undefined') window.addEventListener('resize',resize);}
// Frame display coordinates only: musical-axis values and fixed node positions stay intact.
function graphCameraFrame(nodes, size, fov){
  const positioned=nodes.filter(n=>[n.x,n.y,n.z].every(Number.isFinite));
  if(!positioned.length) return {position:{x:0,y:0,z:650},target:{x:0,y:0,z:0}};
  const min={x:Infinity,y:Infinity,z:Infinity}, max={x:-Infinity,y:-Infinity,z:-Infinity};
  for(const n of positioned) for(const axis of ['x','y','z']){min[axis]=Math.min(min[axis],n[axis]); max[axis]=Math.max(max[axis],n[axis]);}
  const target={}, half={};
  for(const axis of ['x','y','z']){target[axis]=(min[axis]+max[axis])/2; half[axis]=(max[axis]-min[axis])/2;}
  const aspect=size.width>0&&size.height>0?size.width/size.height:1;
  const tanHalfFov=Math.tan((Number.isFinite(fov)&&fov>0&&fov<180?fov:50)*Math.PI/360);
  const radius=4, padding=1.2;
  const distance=Math.max(40,half.z+radius+padding*Math.max((half.y+radius)/tanHalfFov,(half.x+radius)/(tanHalfFov*aspect)));
  return {position:{x:target.x,y:target.y,z:target.z+distance},target};
}
// Axis coordinates are in the same fixed display space as node fx/fy/fz.
// The offsets leave the origin outside the occupied node volume; they are not data minima.
function graphAxisSpec(nodes){
  const valid=nodes.filter(n=>['x','y','z'].every(k=>Number.isFinite(n[k])));
  if(!valid.length) return [];
  const min={},max={};
  for(const key of ['x','y','z']){min[key]=Math.min(...valid.map(n=>n[key]));max[key]=Math.max(...valid.map(n=>n[key]));}
  const start={x:min.x-18,y:min.y-18,z:min.z-18};
  return [['x','X valence (native)','#ff7777',360],['y','Y arousal (native)','#76dfa0',360],['z','Z BPM','#84b9ff',36]].map(([key,label,color,units])=>{
    const end={...start,[key]:Math.max(max[key]+18,start[key]+36)};
    const rawValues=valid.map(n=>n.axis&&n.axis[key]&&n.axis[key].raw).filter(Number.isFinite);
    const references=rawValues.length?[Math.min(...rawValues),Math.max(...rawValues)]:[min[key]/units,max[key]/units];
    return {key,label,color,start,end,references:references.map(displayNumber)};
  });
}
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
function invalidateCameraViewIntent(){
  cameraViewIntentGeneration++;
  pendingCameraSelection=null;
  cancelCameraFocus();
  return cameraViewIntentGeneration;
}
// Own the timeline: bundled cameraPosition's timed tweens have no public cancellation.
function cancelCameraFocus(){
  cameraFocusGeneration++;
  if(cameraFocusFrame!==null && typeof cancelAnimationFrame==='function') cancelAnimationFrame(cameraFocusFrame);
  cameraFocusFrame=null;
}
function observeCameraFocusControls(graph){
  const controls=typeof graph?.controls==='function'?graph.controls():null;
  if(controls===cameraFocusControls) return;
  cancelCameraFocus();
  if(cameraFocusControls?.removeEventListener) cameraFocusControls.removeEventListener('start',invalidateCameraViewIntent);
  cameraFocusControls=controls;
  if(controls?.addEventListener) controls.addEventListener('start',invalidateCameraViewIntent);
}
// Normalize by the largest component before measuring: finite wheel poses can
// have an overflowing radius, while subnormal gaps have overflowing reciprocals.
function cameraUnitDirection(vector){
  const axes=['x','y','z'];
  if(!axes.every(axis=>Number.isFinite(vector[axis]))) return null;
  const largest=Math.max(...axes.map(axis=>Math.abs(vector[axis])));
  if(largest===0) return null;
  const scaled=Object.fromEntries(axes.map(axis=>[axis,vector[axis]/largest]));
  const length=Math.hypot(scaled.x,scaled.y,scaled.z);
  return Object.fromEntries(axes.map(axis=>[axis,scaled[axis]/length]));
}
function cameraViewDirection(position,target){
  const axes=['x','y','z'];
  if(!axes.every(axis=>Number.isFinite(position[axis])&&Number.isFinite(target[axis]))) return null;
  const offset=Object.fromEntries(axes.map(axis=>[axis,position[axis]-target[axis]]));
  if(axes.every(axis=>Number.isFinite(offset[axis]))) return cameraUnitDirection(offset);
  // Opposite finite coordinates can overflow subtraction too.
  const largest=Math.max(...axes.flatMap(axis=>[Math.abs(position[axis]),Math.abs(target[axis])]));
  return cameraUnitDirection(Object.fromEntries(axes.map(axis=>[axis,position[axis]/largest-target[axis]/largest])));
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
  const generation=cameraFocusGeneration;
  settleCameraFocusInput(graph);
  const fromPosition={...graph.cameraPosition()};
  const fromTarget={...graph.controls().target};
  // Interpolate the camera-relative offset on an arc, never through lookAt.
  // Transport up along that arc so passing a world-up pole cannot flip roll.
  const axes=['x','y','z'];
  const subtract=(a,b)=>Object.fromEntries(axes.map(axis=>[axis,a[axis]-b[axis]]));
  const scale=(v,k)=>Object.fromEntries(axes.map(axis=>[axis,v[axis]*k]));
  const dot=(a,b)=>axes.reduce((sum,axis)=>sum+a[axis]*b[axis],0);
  const cross=(a,b)=>({x:a.y*b.z-a.z*b.y,y:a.z*b.x-a.x*b.z,z:a.x*b.y-a.y*b.x});
  const magnitude=v=>Math.hypot(v.x,v.y,v.z);
  const endOffset=subtract(position,target), endDistance=magnitude(endOffset);
  const startOffset=subtract(fromPosition,fromTarget);
  const measuredStartDistance=magnitude(startOffset);
  // THREE/Trackball squares offsets during lookAt. Recover only exceptional
  // radii whose squared norm is unsafe; ordinary orbits keep their full radius.
  const safeRadius=Math.sqrt(Number.MAX_VALUE)/4;
  const recoverRadius=measuredStartDistance>safeRadius;
  const startDistance=recoverRadius?endDistance:(measuredStartDistance||endDistance);
  // A small focus offset cannot be represented beside an astronomical pan target.
  // Exceptional recovery also rebases translation; ordinary arcs stay intact.
  const interpolationTarget=recoverRadius?{x:0,y:0,z:0}:fromTarget;
  const endDirection=cameraUnitDirection(endOffset);
  const startDirection=cameraViewDirection(fromPosition,fromTarget)||endDirection;
  const cosine=Math.max(-1,Math.min(1,dot(startDirection,endDirection)));
  const angle=Math.acos(cosine>1-1e-15?1:cosine);
  let tangent=subtract(endDirection,scale(startDirection,cosine));
  const camera=graph.camera(), fromUp=camera.up?{...camera.up}:null;
  if(magnitude(tangent)<1e-8) {
    // Antiparallel directions need a deterministic plane perpendicular to up.
    tangent=cross(fromUp||{x:0,y:1,z:0},startDirection);
    if(magnitude(tangent)<1e-8) tangent=cross({x:1,y:0,z:0},startDirection);
    if(magnitude(tangent)<1e-8) tangent=cross({x:0,y:0,z:1},startDirection);
  }
  tangent=scale(tangent,1/magnitude(tangent));
  const rotationAxis=cross(startDirection,tangent);
  const started=typeof performance!=='undefined'?performance.now():Date.now();
  const step=timestamp=>{
    if(generation!==cameraFocusGeneration || graph!==forceGraph) return;
    cameraFocusFrame=null;
    const now=Number.isFinite(timestamp)?timestamp:(typeof performance!=='undefined'?performance.now():Date.now());
    const progress=Math.min(1,Math.max(0,(now-started)/700));
    const interpolate=(from,to)=>Object.fromEntries(['x','y','z'].map(axis=>[axis,from[axis]+(to[axis]-from[axis])*progress]));
    const theta=angle*progress, c=Math.cos(theta), s=Math.sin(theta);
    const distance=startDistance+(endDistance-startDistance)*progress;
    // Large finite starts can erase node coordinates at t=1 by cancellation.
    const nextTarget=progress===1?target:interpolate(interpolationTarget,target);
    const nextPosition=Object.fromEntries(axes.map(axis=>[axis,nextTarget[axis]+distance*(startDirection[axis]*c+tangent[axis]*s)]));
    if(fromUp && camera.up?.set) {
      const turned=cross(rotationAxis,fromUp), along=dot(rotationAxis,fromUp)*(1-c);
      camera.up.set(...axes.map(axis=>fromUp[axis]*c+turned[axis]*s+rotationAxis[axis]*along));
    }
    setCameraFocusPose(graph,progress===1?position:nextPosition,nextTarget);
    if(progress<1) cameraFocusFrame=requestAnimationFrame(step);
  };
  cameraFocusFrame=requestAnimationFrame(step);
}
// Graph picks own the view immediately; server acceptance still owns detail.
function selectGraphNode(picked){
  const id=picked?.id;
  if(typeof id!=='string' || !id) return;
  cancelCameraFocus();
  pendingCameraSelection=null;
  // A replacement can be visible-but-not-mounted during loadGraph's frame gap.
  const node=visibleGraph.nodes.some(n=>n.id===id)
    ?renderedGraphData.nodes.find(n=>n.id===id):null;
  if(forceGraph && node){
    try {
      const axes=['x','y','z'];
      const target={x:node.fx,y:node.fy,z:node.fz};
      const controls=forceGraph.controls(), from=forceGraph.cameraPosition();
      const position=Object.fromEntries(axes.map(axis=>[axis,target[axis]+(from[axis]-controls.target[axis])]));
      // Finite coordinates can still lose the orbit offset through rounding.
      const squaredOffset=axes.reduce((sum,axis)=>sum+(position[axis]-target[axis])**2,0);
      if(axes.every(axis=>Number.isFinite(target[axis])&&Number.isFinite(position[axis]))
          && squaredOffset>=2**-1022 && Number.isFinite(squaredOffset)){
        observeCameraFocusControls(forceGraph);
        settleCameraFocusInput(forceGraph);
        setCameraFocusPose(forceGraph,position,target);
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
  if(!forceGraph || framedGraphLayout===null || pendingCameraSelection===null) return;
  const id=pendingCameraSelection;
  pendingCameraSelection=null;
  if(id!==state.current_track_id) return;
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
    const distance=Math.max(controls.minDistance??0,Math.min(controls.maxDistance??Infinity,100));
    // A positioned origin has no radial direction. Preserve the current orbit
    // direction (relative to the panned target), or use +Z for a coincident pose.
    const direction=length===0
      ?(cameraViewDirection(forceGraph.cameraPosition(),controls.target)||{x:0,y:0,z:1})
      :cameraUnitDirection(target);
    // Normalize before radius scaling: distance*target can underflow for a
    // tiny non-origin node even when the final camera offset is renderable.
    const position={x:target.x+distance*direction.x,y:target.y+distance*direction.y,z:target.z+distance*direction.z};
    if(![position.x,position.y,position.z].every(Number.isFinite)) return;
    // Require a normal-range unscaled squared norm for reliable orientation.
    // A nonzero offset can still underflow that norm (or overflow it). Skip
    // before settling input; never widen custom bounds to make focus eligible.
    const dx=position.x-target.x, dy=position.y-target.y, dz=position.z-target.z;
    const squaredOffset=dx*dx+dy*dy+dz*dz;
    if(!(squaredOffset>=2**-1022) || !Number.isFinite(squaredOffset)) return;
    animateCameraFocus(forceGraph,position,target);
  } catch(error) {
    // A camera adapter failure does not revoke an accepted selection.
    cancelCameraFocus();
  }
}
function renderMoodStrip(data){
  const canvas=document.getElementById('mood-strip'), picker=document.getElementById('mood-strip-picker'), readout=document.getElementById('mood-strip-value');
  if(!canvas||!picker||!readout) return;
  const marks=buildMoodStrip(data,state.current_track_id), ctx=canvas.getContext('2d');
  const width=Math.max(1,Math.floor(canvas.clientWidth||600)), height=70, pad=14;
  canvas.width=width; canvas.height=height;
  const x=m=>pad+(width-2*pad)*m.position;
  ctx.clearRect(0,0,width,height); ctx.strokeStyle='#444'; ctx.beginPath();ctx.moveTo(pad,35);ctx.lineTo(width-pad,35);ctx.stroke();
  // Stack tied/nearby pixels deterministically, keeping all marks visible in bounded canvas DOM.
  const stack=new Map();
  for(const mark of marks){const pixel=Math.round(x(mark)), level=stack.get(pixel)||0; stack.set(pixel,level+1); const y=level%2?35+5+Math.floor(level/2)*5:35-5-Math.floor(level/2)*5; mark.y=Math.max(5,Math.min(height-5,y)); if(mark.selected) continue; ctx.beginPath();ctx.arc(x(mark),mark.y,3,0,Math.PI*2);ctx.fillStyle='#164e8c';ctx.fill();}
  for(const mark of marks.filter(m=>m.selected)){ctx.beginPath();ctx.arc(x(mark),mark.y,5,0,Math.PI*2);ctx.fillStyle='#b02212';ctx.fill();}
  picker.max=String(Math.max(0,marks.length-1)); picker.disabled=!marks.length;
  let index=marks.findIndex(m=>m.selected); if(index<0) index=0;
  picker.value=String(index);
  const show=()=>text(readout,marks.length?`${Number(picker.value)+1} / ${marks.length}: ${marks[Number(picker.value)].description}`:'No visible tracks have this selected mood score; tracks without it have no mark.');
  picker.oninput=show; show();
  canvas.onclick=event=>{if(!marks.length) return; const px=(event.clientX-canvas.getBoundingClientRect().left)*width/canvas.getBoundingClientRect().width; let nearest=0; for(let i=1;i<marks.length;i++) if(Math.abs(x(marks[i])-px)<Math.abs(x(marks[nearest])-px)) nearest=i; picker.value=String(nearest); show();};
}
function renderMap(data){pendingGraphAxisSpec=graphAxisSpec(graphModel.nodes.length?graphModel.nodes:data.nodes);const elem=document.getElementById('graph3d')||replaceCanvasWithGraphElement(); if(typeof ForceGraph3D==='function'){if(!forceGraph){forceGraph=ForceGraph3D()(elem).enableNodeDrag(false).cooldownTicks(0).nodeId('id').nodeRelSize(4).nodeLabel(nodeLabel).nodeColor(n=>n.color).nodeVal(selectedNodeValue).linkLabel(linkLabel).linkOpacity(1).linkColor(relatednessLinkColor).linkWidth(l=>1+Math.max(0,Number(l.score)||0)); forceGraph.onNodeClick(selectGraphNode); observeGraphResize(elem); observeGraphInput(elem); if(!graphAxesAnimating && typeof requestAnimationFrame==='function'){graphAxesAnimating=true;requestAnimationFrame(animateGraphAxes);}} observeCameraFocusControls(forceGraph); const size=updateGraphSize(elem,forceGraph); const signature=JSON.stringify([data.nodes.map(n=>[n.id,n.x,n.y,n.z]),data.links.map(l=>[l.source,l.target,l.score])]); if(signature!==renderedGraphSignature){disposeSelectedNodeHalo(); renderedGraphData={nodes:data.nodes.map(n=>Object.assign({},n,{fx:n.fx,fy:n.fy,fz:n.fz})),links:data.links.map(l=>Object.assign({},l))}; forceGraph.graphData(renderedGraphData); renderedGraphSignature=signature;} else {const live=new Map(data.nodes.map(n=>[n.id,n])); for(const node of renderedGraphData.nodes){const updated=live.get(node.id); if(updated){node.moodScore=updated.moodScore; node.axis=updated.axis;}}} syncSelectedNodeHalo(forceGraph,data); forceGraph.numDimensions(3); forceGraph.d3AlphaDecay(1); forceGraph.d3VelocityDecay(1); const layout=JSON.stringify(data.nodes.map(n=>JSON.stringify([n.id,n.x,n.y,n.z])).sort()); if(layout!==framedGraphLayout){const frame=graphCameraFrame(data.nodes,size,forceGraph.camera().fov); /* Synchronize the orbit target even when bundled controls are disabled. */ cancelCameraFocus(); setCameraFocusPose(forceGraph,frame.position,frame.target); framedGraphLayout=layout;} focusPendingCameraSelection(true); wakeGraphRendering();} else {disposeSelectedNodeHalo();renderCanvasFallback(data,elem);} renderMoodStrip(data);}
function nodeLabel(n){return `${escapeHtml(n.label)}<br>valence ${displayNumber(n.axis.x.raw)} (${escapeHtml(n.axis.x.scale)})<br>arousal ${displayNumber(n.axis.y.raw)} (${escapeHtml(n.axis.y.scale)})<br>${escapeHtml(n.axis.z.label)} ${displayNumber(n.axis.z.raw)} (${escapeHtml(n.axis.z.scale)})<br>${n.moodScore?`${escapeHtml(n.moodScore.label)} ${displayNumber(n.moodScore.raw)} / 1`:'Selected mood score unavailable'}`;}
function linkLabel(l){return escapeHtml(`score ${displayNumber(l.score)}; ${l.explanation||''}; groups ${l.supportedGroupCount||0}`);}
function escapeHtml(value){return String(value).replace(/[&<>'"]/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[ch]));}
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
exposeForBrowserTests({state:()=>state,graphModel:()=>graphModel,visibleGraph:()=>visibleGraph,forceGraph:()=>forceGraph,framedGraphLayout:()=>framedGraphLayout,renderedGraphData:()=>renderedGraphData,graphAxes:()=>graphAxes,selectedNodeHalo:()=>selectedNodeHalo,pendingSelectionOperation:()=>pendingSelectionOperation,pendingCameraSelection:()=>pendingCameraSelection,cameraFocusFrame:()=>cameraFocusFrame,trackSummaryPage:()=>trackSummaryPage,trackSummaryStatus:()=>trackSummaryStatus,graphLoadState:()=>graphLoadState,text:()=>text,api:()=>api,renderDetailLoading:()=>renderDetailLoading,setCurrent:()=>setCurrent,renderTracks:()=>renderTracks,renderDetailField:()=>renderDetailField,renderTrackMetadata:()=>renderTrackMetadata,renderDetail:()=>renderDetail,buildMoodGraphModel:()=>buildMoodGraphModel,buildMoodStrip:()=>buildMoodStrip,graphAxisSpec:()=>graphAxisSpec,graphObjectTrackId:()=>graphObjectTrackId,findSceneObject:()=>findSceneObject,syncSelectedNodeHalo:()=>syncSelectedNodeHalo,syncGraphAxes:()=>syncGraphAxes,cancelCameraFocus:()=>cancelCameraFocus,animateCameraFocus:()=>animateCameraFocus,renderMap:()=>renderMap,setStateForTesting:()=>setStateForTesting},
  {buildMoodGraphModel:value=>{buildMoodGraphModel=value;},renderMap:value=>{renderMap=value;},renderDetail:value=>{renderDetail=value;},renderDetailLoading:value=>{renderDetailLoading=value;},setCurrent:value=>{setCurrent=value;},animateCameraFocus:value=>{animateCameraFocus=value;},cancelCameraFocus:value=>{cancelCameraFocus=value;}});
