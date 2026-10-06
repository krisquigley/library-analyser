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
let selectedGraphControls={mood:'',bpmMin:null,bpmMax:null,genres:[],m3uBpmMin:'',m3uBpmMax:'',m3uCount:'10'};
let selectionRequestSeq=0;
const selectionPostSeqKey='music-explorer-selection-post-seq';
let selectionPostSeq=loadSelectionPostSeq();
let selectionEpoch=0;
let refreshRequestSeq=0;
let selectionDetailRequestSeq=0;
let pendingSelectionIntent=null;
let loadingRefreshToken=0;
let lastRefreshError=null;
let hasCompletedInitialRefresh=false;
let trackSummaryPage={tracks:[],metadata:{},next_cursor:null,query:'',order:'title'};
let trackSummaryRequestSeq=0;
let graphLoadState={status:'idle',message:'Graph not loaded. Use the Load graph button when you want the 3D library graph.'};
function sessionStorageNumber(key){
  try{
    if(typeof sessionStorage!=='undefined'){
      const value=Number(sessionStorage.getItem(key)||'0');
      return Number.isFinite(value)&&value>0?Math.floor(value):0;
    }
  }catch(_error){}
  return 0;
}
function loadSelectionPostSeq(){return sessionStorageNumber(selectionPostSeqKey);}
function storeSelectionPostSeq(value){
  try{if(typeof sessionStorage!=='undefined') sessionStorage.setItem(selectionPostSeqKey,String(value));}catch(_error){}
}
function nextSelectionPostSeq(){selectionPostSeq+=1; storeSelectionPostSeq(selectionPostSeq); return selectionPostSeq;}
function resetSelectionPostSeq(){selectionPostSeq=0; storeSelectionPostSeq(selectionPostSeq);}
function selectionClientId(){
  const key='music-explorer-selection-client-id';
  try{
    if(typeof sessionStorage!=='undefined'){
      let id=sessionStorage.getItem(key);
      if(!id){id='tab-'+Date.now().toString(36)+'-'+Math.random().toString(36).slice(2); sessionStorage.setItem(key,id);}
      return id;
    }
  }catch(_error){}
  if(!selectionClientId.fallback) selectionClientId.fallback='tab-'+Math.random().toString(36).slice(2);
  return selectionClientId.fallback;
}
function syncSelectionEpoch(snapshot){
  if(snapshot && typeof snapshot.selection_epoch==='number') selectionEpoch=snapshot.selection_epoch;
  return snapshot;
}
function invalidateSelectionIntent(){selectionRequestSeq++; pendingSelectionIntent=null;}
async function applyHistorySelection(path){const token=++selectionRequestSeq; pendingSelectionIntent=null; const posted=syncSelectionEpoch(await api(path,{method:'POST'})); if(token!==selectionRequestSeq) return; state=posted; await refresh();}
function text(el,value){el.textContent=value==null?'':String(value);return el;}
function nextFrame(){return new Promise(resolve=>{if(typeof requestAnimationFrame==='function') requestAnimationFrame(()=>resolve()); else setTimeout(resolve,0);});}
function loadingElements(){return {surface:typeof document!=='undefined'?(document.getElementById('library-loading')||document.getElementById('loading-surface')):null,status:typeof document!=='undefined'?document.getElementById('loading-status'):null,error:typeof document!=='undefined'?document.getElementById('loading-error'):null,retry:typeof document!=='undefined'?document.getElementById('loading-retry'):null};}
function setLoadingClass(surface,state){if(!surface) return; if(surface.classList){surface.classList.remove('active'); surface.classList.remove('refresh'); surface.classList.remove('error'); surface.classList.remove('done'); if(state) surface.classList.add(state);} else surface.className=state?'loading-surface '+state:'loading-surface';}
function setLoadingPhase(refreshToken,phase,detail){
  if(refreshToken!==refreshRequestSeq) return false;
  loadingRefreshToken=refreshToken;
  lastRefreshError=null;
  const {surface,status,error,retry}=loadingElements();
  if(surface){surface.hidden=false; setLoadingClass(surface,hasCompletedInitialRefresh?'refresh':'active'); surface.setAttribute('aria-busy','true');}
  if(status){text(status,detail?`${phase}: ${detail}`:phase); status.removeAttribute('role'); status.setAttribute('role','status');}
  if(error){error.hidden=true; text(error,'');}
  if(retry) retry.hidden=true;
  return true;
}
function setLoadingError(refreshToken,message){
  if(refreshToken!==refreshRequestSeq) return false;
  lastRefreshError=String(message||'Loading failed');
  const {surface,status,error,retry}=loadingElements();
  if(surface){surface.hidden=false; setLoadingClass(surface,'error'); surface.setAttribute('aria-busy','false');}
  if(status) text(status,'Unable to load library');
  if(error){error.hidden=false; error.setAttribute('role','alert'); text(error,lastRefreshError);}
  if(retry){retry.hidden=false; retry.onclick=()=>refresh().catch(()=>{});}
  return true;
}
function clearLoading(refreshToken){
  if(refreshToken!==refreshRequestSeq) return false;
  const {surface,status,error,retry}=loadingElements();
  if(surface){surface.setAttribute('aria-busy','false'); setLoadingClass(surface,'done'); surface.hidden=true;}
  hasCompletedInitialRefresh=true;
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
async function api(path, options){const r=await fetch(path, options); if(!r.ok) throw new Error(await r.text()); return r.json();}
function selectedNodeValue(n){return n.id===state.current_track_id?4:1;}
function updateSelectedTrackVisuals(){
  if(typeof document!=='undefined') for(const row of document.querySelectorAll('#tracks tr[data-track-id]')){row.className=row.dataset.trackId===state.current_track_id?'current':''; const button=row.querySelector ? row.querySelector('button') : null; if(button){if(row.className) button.setAttribute('aria-current','true'); else button.removeAttribute('aria-current');}}
  if(forceGraph){forceGraph.nodeVal(selectedNodeValue); if(typeof forceGraph.refresh==='function') forceGraph.refresh(); syncSelectedNodeHalo(forceGraph,visibleGraph);}
  else if(visibleGraph.nodes.length) renderCanvasFallback(visibleGraph);
  renderMoodStrip(visibleGraph);
}
async function refreshSelectionDependent(token){
  if(token!==selectionRequestSeq) return;
  const detailToken=++selectionDetailRequestSeq;
  const selectedId=state.current_track_id;
  updateSelectedTrackVisuals();
  if(selectedId){
    const detail=await api('/api/tracks/'+encodeURIComponent(selectedId));
    if(token!==selectionRequestSeq || detailToken!==selectionDetailRequestSeq || state.current_track_id!==selectedId) return;
    renderDetail(detail); updateSelectedTrackVisuals();
  } else {
    if(token!==selectionRequestSeq || detailToken!==selectionDetailRequestSeq) return;
    renderInitialDetail(graphModel);
  }
}
async function setCurrent(id){
  const token=++selectionRequestSeq;
  const postToken=nextSelectionPostSeq();
  pendingSelectionIntent=id;
  state={...state,current_track_id:id};
  updateSelectedTrackVisuals();
  const posted=syncSelectionEpoch(await api('/api/current',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({track_id:id,selection_token:postToken,selection_epoch:selectionEpoch,selection_client_id:selectionClientId()})}));
  if(token!==selectionRequestSeq) return;
  state=posted;
  pendingSelectionIntent=null;
  await refreshSelectionDependent(token);
}
function graphQueryFromControls(){const p=new URLSearchParams(); if(selectedGraphControls.mood) p.set('mood',selectedGraphControls.mood); const q=p.toString(); return q?'?'+q:'';}
async function refresh(){
  const refreshToken=++refreshRequestSeq;
  const token=selectionRequestSeq;
  try{
    setLoadingPhase(refreshToken,'Preparing library view');
    await nextFrame();
    if(abortStaleRefresh(refreshToken,token)) return;
    setLoadingPhase(refreshToken,'Loading library state');
    const refreshedState=syncSelectionEpoch(await api('/api/state'));
    if(abortStaleRefresh(refreshToken,token)) return;
    state={...refreshedState,current_track_id:pendingSelectionIntent||refreshedState.current_track_id};
    setLoadingPhase(refreshToken,'Loading first track page');
    const list=await api('/api/tracks/summary?limit=100&order=title');
    if(abortStaleRefresh(refreshToken,token)) return;
    applyTrackSummaryPage(list,{append:false,query:''});
    setLoadingPhase(refreshToken,'Rendering first track page',`${(list.tracks||[]).length} of ${list.metadata&&list.metadata.track_count!=null?list.metadata.track_count:'many'} tracks`);
    renderGraphLoadStatus();
    if(abortStaleRefresh(refreshToken,token)) return;
    await refreshSelectionDependent(token);
    if(abortStaleRefresh(refreshToken,token)) return;
    if(graphLoadState.status==='ready') renderMap(visibleGraph);
    clearLoading(refreshToken);
  }catch(error){
    if(abortStaleRefresh(refreshToken,token)) return;
    setLoadingError(refreshToken,error&&error.message?error.message:error);
    throw error;
  }
}
function trackTitle(t){return t.title||t.display_label||t.handle;}
function trackArtist(t){return t.artist||'Unknown artist';}
function applyTrackSummaryPage(page,options){
  const append=!!(options&&options.append);
  const previous=append&&Array.isArray(trackSummaryPage.tracks)?trackSummaryPage.tracks:[];
  const tracks=append?[...previous,...(page.tracks||[])]:[...(page.tracks||[])];
  trackSummaryPage={...page,tracks,query:(options&&options.query)||'',order:'title'};
  renderTracks(tracks);
}
async function loadTrackSummaryPage(query,options){
  const seq=++trackSummaryRequestSeq;
  const append=!!(options&&options.append);
  const cursor=options&&options.cursor;
  const normalizedQuery=String(query||'');
  const params=new URLSearchParams({limit:'100',order:'title'});
  if(normalizedQuery) params.set('query',normalizedQuery);
  if(cursor) params.set('cursor',cursor);
  const page=await api('/api/tracks/summary?'+params.toString());
  if(seq!==trackSummaryRequestSeq) return;
  applyTrackSummaryPage(page,{append,query:normalizedQuery});
}
function loadNextTrackSummaryPage(){
  const cursor=trackSummaryPage&&trackSummaryPage.next_cursor;
  if(!cursor) return Promise.resolve();
  return loadTrackSummaryPage(trackSummaryPage.query||'',{append:true,cursor});
}
function renderTracks(tracks){const root=document.getElementById('tracks'); if(!root) return; const table=document.createElement('table'); table.className='tracks-table'; const caption=document.createElement('caption'); const total=trackSummaryPage&&trackSummaryPage.metadata?trackSummaryPage.metadata.track_count:null; text(caption,total==null?`${tracks.length} tracks`:`Showing ${tracks.length} of ${total}`); table.append(caption); const thead=document.createElement('thead'); const headRow=document.createElement('tr'); for(const label of ['Title','Artist']) headRow.append(text(document.createElement('th'),label)); thead.append(headRow); const tbody=document.createElement('tbody'); const empty=document.createElement('p'); empty.id='track-search-empty'; empty.className='muted'; empty.setAttribute('role','status'); text(empty,'No tracks match your search'); empty.hidden=tracks.length!==0; const rows=tracks.map(t=>{const row=document.createElement('tr'); row.dataset.trackId=t.handle; row.dataset.title=trackTitle(t); row.dataset.artist=trackArtist(t); row.className=t.handle===state.current_track_id?'current':''; const titleCell=document.createElement('td'); const button=document.createElement('button'); text(button,trackTitle(t)); button.onclick=()=>setCurrent(t.handle); if(row.className) button.setAttribute('aria-current','true'); titleCell.append(button); const artistCell=text(document.createElement('td'),trackArtist(t)); row.append(titleCell,artistCell); return row;}); tbody.replaceChildren(...rows); table.append(thead,tbody); const status=document.createElement('p'); status.className='muted'; status.setAttribute('role','status'); status.setAttribute('aria-live','polite'); text(status,total==null?`${tracks.length} tracks loaded`:`Showing ${tracks.length} of ${total}`); const children=[table,status]; if(trackSummaryPage&&trackSummaryPage.next_cursor){const nav=document.createElement('nav'); nav.setAttribute('aria-label','Track list pagination'); const more=document.createElement('button'); more.type='button'; text(more,'Load more tracks'); more.onclick=()=>loadNextTrackSummaryPage().catch(()=>{}); nav.append(more); children.push(nav);} children.push(empty); root.replaceChildren(...children); const search=document.getElementById('track-search'); if(search && !search.dataset.summarySearchWired){search.dataset.summarySearchWired='1'; let timer=null; search.oninput=()=>{clearTimeout(timer); const q=search.value; timer=setTimeout(()=>loadTrackSummaryPage(q).catch(()=>{}),150);};}}
function filterTrackRows(query,tbody,empty){const needle=String(query||'').trim().toLowerCase(); let shown=0; for(const row of tbody.children){const haystack=`${row.dataset.title||''} ${row.dataset.artist||''}`.toLowerCase(); row.hidden=!!needle && !haystack.includes(needle); if(!row.hidden) shown++;} if(empty) empty.hidden=shown!==0;}
function renderGraphLoadStatus(){const root=document.getElementById('graph-load-status')||document.getElementById('controls'); if(!root) return; let panel=document.getElementById('graph-load-status'); if(!panel){panel=document.createElement('section'); panel.id='graph-load-status'; panel.className='graph-load-status'; root.append(panel);} panel.replaceChildren(); panel.append(text(document.createElement('h3'),'Library graph')); const p=document.createElement('p'); text(p,graphLoadState.message||'Graph not loaded. Use the Load graph button when you want the 3D library graph.'); panel.append(p); if(graphLoadState.status==='idle'||graphLoadState.status==='error'||graphLoadState.status==='ready'){const button=document.createElement('button'); button.id='load-graph'; button.type='button'; text(button,graphLoadState.status==='error'?'Retry graph':graphLoadState.status==='ready'?'Reload graph':'Load graph'); button.onclick=()=>loadGraph().catch(()=>{}); panel.append(button);} if(graphLoadState.status==='ready') appendM3UDownloadControls(panel); else if(graphLoadState.status==='loading'||graphLoadState.status==='rendering'){const busy=document.createElement('p'); busy.setAttribute('role','status'); busy.setAttribute('aria-live','polite'); text(busy,graphLoadState.status==='loading'?'Loading graph…':'Rendering graph…'); panel.append(busy);}}
async function loadGraph(){const seq=(graphLoadState.requestSeq||0)+1; graphLoadState={...graphLoadState,status:'loading',message:'Loading graph. The track list, search, history, and detail remain usable.',requestSeq:seq}; renderGraphLoadStatus(); try{const controlQuery=graphQueryFromControls(); const graph=await api('/api/mood-axis-graph'+controlQuery+(controlQuery?'&':'?')+'contract=v2'); if(seq!==graphLoadState.requestSeq) return; graphModel=buildMoodGraphModel(graph); syncGraphControlOptions(graphModel); visibleGraph=applyMoodGraphFilters(graphModel,selectedGraphControls); graphLoadState={...graphLoadState,status:'rendering',message:`Rendering ${visibleGraph.nodes.length} positioned tracks`,requestSeq:seq}; renderGraphLoadStatus(); await nextFrame(); if(seq!==graphLoadState.requestSeq) return; renderMap(visibleGraph); const statusCopy=graphStatusMessage(graphModel.metadata.graph_status,visibleGraph.nodes.length); graphLoadState={...graphLoadState,status:statusCopy.status,message:statusCopy.message,requestSeq:seq}; renderGraphLoadStatus();}catch(error){if(seq!==graphLoadState.requestSeq) return; graphLoadState={...graphLoadState,status:'error',message:`Graph failed: ${error&&error.message?error.message:error}`,requestSeq:seq}; renderGraphLoadStatus(); throw error;}}

function appendM3UDownloadControls(panel){const fs=document.createElement('fieldset'); fs.id='m3u-download-controls'; const legend=document.createElement('legend'); text(legend,'Download M3U'); fs.append(legend); const bpmMin=document.createElement('input'); bpmMin.id='m3u-bpm-min'; bpmMin.type='number'; bpmMin.value=selectedGraphControls.m3uBpmMin||''; bpmMin.placeholder='min BPM'; const bpmMax=document.createElement('input'); bpmMax.id='m3u-bpm-max'; bpmMax.type='number'; bpmMax.value=selectedGraphControls.m3uBpmMax||''; bpmMax.placeholder='max BPM'; const count=document.createElement('input'); count.id='m3u-count'; count.type='number'; count.min='1'; count.max='1000'; count.value=selectedGraphControls.m3uCount||'10'; for(const input of [bpmMin,bpmMax,count]) input.onchange=()=>{selectedGraphControls.m3uBpmMin=bpmMin.value; selectedGraphControls.m3uBpmMax=bpmMax.value; selectedGraphControls.m3uCount=count.value;}; const button=document.createElement('button'); button.id='download-m3u'; button.type='button'; text(button,'Download M3U'); button.onclick=async()=>{selectedGraphControls.m3uBpmMin=bpmMin.value; selectedGraphControls.m3uBpmMax=bpmMax.value; selectedGraphControls.m3uCount=count.value; try{await downloadM3UPlaylist();}catch(error){const status=document.getElementById('m3u-download-status'); if(status){status.setAttribute('role','alert'); status.setAttribute('aria-live','assertive'); text(status,`M3U download failed: ${error&&error.message?error.message:error}`);}}}; const status=document.createElement('p'); status.id='m3u-download-status'; status.className='muted'; status.setAttribute('role','status'); status.setAttribute('aria-live','polite'); fs.append(bpmMin,bpmMax,count,button,status); panel.append(fs);}
async function downloadM3UPlaylist(){if(!state.current_track_id) throw new Error('Select a start track before downloading M3U'); const params=new URLSearchParams(); params.set('start',state.current_track_id); params.set('bpm_min',selectedGraphControls.m3uBpmMin||''); params.set('bpm_max',selectedGraphControls.m3uBpmMax||''); params.set('count',selectedGraphControls.m3uCount||'10'); const response=await fetch('/api/playlists/m3u?'+params.toString()); const body=response.text?await response.text():''; if(!response.ok) throw new Error(body||'M3U download failed'); const disposition=response.headers&&response.headers.get?response.headers.get('content-disposition')||'':''; const filename=((/filename="?([^";]+)"?/i.exec(disposition)||[])[1])||'library-graph-playlist.m3u'; const warning=response.headers&&response.headers.get?response.headers.get('X-Music-Explorer-Playlist-Warning'):''; const status=document.getElementById('m3u-download-status'); if(status){status.setAttribute('role','status'); status.setAttribute('aria-live','polite'); text(status,warning?`M3U downloaded. Warning: ${warning}`:'M3U downloaded.');} const blob=new Blob([body],{type:(response.headers&&response.headers.get?response.headers.get('content-type'):'')||'audio/x-mpegurl;charset=utf-8'}); const url=URL.createObjectURL(blob); const anchor=document.createElement('a'); anchor.href=url; anchor.download=filename; try{if(document.body&&document.body.append) document.body.append(anchor); anchor.click();}finally{if(anchor.remove) anchor.remove(); URL.revokeObjectURL(url);}}
function graphStatusMessage(graphStatus,positionedCount){const build='Run music-analyzer graph build --database DB, then reload this read-only explorer.'; const status=graphStatus&&typeof graphStatus.state==='string'?graphStatus.state:'ready'; switch(status){case 'ready': return {status:'ready',message:`Graph ready: ${positionedCount} positioned tracks`}; case 'stale': return {status:'ready',message:`Graph stale: showing the last stored snapshot for ${positionedCount} positioned tracks. ${build}`}; case 'build_needed': return {status:'ready',message:`Graph needs a build: no current stored graph snapshot is available. ${build}`}; case 'failed': return {status:'ready',message:`Graph failed: the last stored graph build did not complete successfully. ${build}`}; case 'building': return {status:'ready',message:`Graph building: a stored graph snapshot is not ready yet. ${build}`}; default: return {status:'ready',message:`Graph status unavailable: showing ${positionedCount} positioned tracks from the stored snapshot. ${build}`};}}
function applyCurrentGraphFilters(){if(graphLoadState.status!=='ready'){renderGraphLoadStatus(); return false;} visibleGraph=applyMoodGraphFilters(graphModel,selectedGraphControls); const statusCopy=graphStatusMessage(graphModel.metadata.graph_status,visibleGraph.nodes.length); graphLoadState={...graphLoadState,message:statusCopy.message}; renderMap(visibleGraph); renderGraphLoadStatus(); return true;}
function renderInitialDetail(model){const root=document.getElementById('detail'); if(!root) return; root.replaceChildren();}
function fieldDisplay(f){const a=f.automatic||{}; if(a.values&&a.values.length) return a.values; if(a.summary_values&&a.summary_values.length) return a.summary_values; return f.effective_source;}
// Detail is a presentation of retained evidence, not a graph filter or analysis threshold.
const detailScoreModels={genres:'genre_discogs400-discogs-effnet-1',mood:'mtg_jamendo_moodtheme-discogs-effnet-1',instruments:'mtg_jamendo_instrument-discogs-effnet-1'};
function detailProvenance(f){return Object.fromEntries(f.automatic?.provenance||[]);}
// Only presentation is rounded; callers retain raw scores for sorting and geometry.
function displayNumber(value){return typeof value==='number' && Number.isFinite(value)?(Math.sign(value)*Math.round((Math.abs(value)+Number.EPSILON)*10)/10).toFixed(1):String(value);}
const detailDisplayCutoff=0.1;
function detailEntries(f){return fieldDisplay(f);}
function detailGauge(label,value){
  const row=document.createElement('div'); row.className='score-row';
  const title=document.createElement('span'); text(title,label);
  const gauge=document.createElement('div'); gauge.className='score-gauge'; gauge.setAttribute('role','img');
  gauge.setAttribute('aria-label',`${label}: ${displayNumber(value)} out of 1`);
  const arc=document.createElement('span'); arc.className='score-arc';
  const needle=document.createElement('span'); needle.className='score-needle'; needle.style.transform=`rotate(${value*240-120}deg)`;
  const hub=document.createElement('span'); hub.className='score-hub';
  gauge.append(arc,needle,hub);
  row.append(title,gauge); return row;
}
function renderDetailField(name,f){
  const div=document.createElement('section'); div.className='field';
  div.append(text(document.createElement('h4'),name));
  if(f.manual_text!=null){div.append(text(document.createElement('p'),`Manual override: ${f.manual_text} (${f.typed_override_status||'unresolved'}; automatic evidence not displayed)`));return div;}
  const values=detailEntries(f);
  const provenance=detailProvenance(f);
  if(name in detailScoreModels){
    if(!(detailScoreModels[name] in provenance) || (provenance.model!=null && provenance.model!==detailScoreModels[name]) || (provenance.scale!=null && provenance.scale!=='sigmoid_mean_score_0_1')){
      div.append(text(document.createElement('p'),'no usable evidence (unsupported or missing model/scale)'));
      if(f.missing_reason) div.append(text(document.createElement('p'),f.missing_reason));
      return div;
    }
    div.append(text(document.createElement('p'),'display scores > 0.1 (raw 0–1 labelled scores; not probabilities; independent of analysis cutoff).'));
    const entries=Array.isArray(values)?values.filter(([label,v])=>typeof label==='string' && typeof v==='number' && Number.isFinite(v) && v>detailDisplayCutoff && v<=1).sort((a,b)=>b[1]-a[1] || a[0].localeCompare(b[0])):[];
    if(!entries.length) div.append(text(document.createElement('p'),Array.isArray(values)&&values.length?'no significant values':'no usable evidence'));
    // Bound layout, but never conceal qualifying labels without a count.
    for(const [label,v] of entries.slice(0,12)) div.append(detailGauge(label,v));
    if(entries.length>12) div.append(text(document.createElement('p'),`${entries.length-12} more significant labels not shown`));
  } else if(name==='energy'){
    if(provenance['emomusic-msd-musicnn-2']!=null && (provenance.model==null || provenance.model==='emomusic-msd-musicnn-2') && (provenance.scale==null || provenance.scale==='native_valence_arousal_regression') && Array.isArray(values)){
      const valid=values.filter(([label,v])=>['valence','arousal'].includes(label) && typeof v==='number' && Number.isFinite(v));
      div.append(text(document.createElement('p'),valid.length?`${valid.map(([k,v])=>`${k}: ${displayNumber(v)}`).join(' · ')} (Emomusic native regression scale; not a 0–1 probability)`:'no usable evidence'));
    }else div.append(text(document.createElement('p'),'no usable evidence (unsupported model or contradictory scale)'));
  }else if(name==='bpm' || name==='key'){
    const entry=Array.isArray(values)?values.find(([label,v])=>label===name && (name==='key'?typeof v==='string' && v.trim():typeof v==='number' && Number.isFinite(v) && v>0)):null;
    div.append(text(document.createElement('p'),entry?`${name==='bpm'?displayNumber(entry[1]):entry[1]}${name==='bpm'?' BPM (raw)':''}`:'no usable evidence'));
  }else div.append(text(document.createElement('p'),'no usable evidence (no supported display scale)'));
  if(f.missing_reason) div.append(text(document.createElement('p'),f.missing_reason));
  return div;
}
function graphRelatednessLegend(){return 'Link alpha reflects axis-independent relatedness strength from existing stored summaries; higher-score links are more opaque.';}
function relatednessLinkAlpha(link){const score=Number(link&&link.score); const clamped=Number.isFinite(score)?Math.max(0,Math.min(1,score)):0; return Math.round((0.18+clamped*0.54)*100)/100;}
function relatednessLinkColor(link){return `rgba(240,240,240,${relatednessLinkAlpha(link)})`;}
const metadataLabels={title:'Title',artist:'Artist',album:'Album',album_artist:'Album artist',date:'Date',year:'Year',genre:'Genre',composer:'Composer',track_number:'Track number',disc_number:'Disc number',comment:'Comment'};
const metadataAliases={albumartist:'album_artist',aalbumartist:'album_artist',aart:'album_artist',tpe2:'album_artist',tracknumber:'track_number',trkn:'track_number',trck:'track_number',discnumber:'disc_number',disk:'disc_number',tpos:'disc_number'};
function canonicalMetadataKey(key){const normalized=String(key||'').trim().toLowerCase().replace(/[ -]+/g,'_'); return metadataAliases[normalized]||normalized;}
function metadataValueText(value){return Array.isArray(value)?value.filter(v=>String(v).trim()).join('; '):String(value==null?'':value).trim();}
function renderTrackMetadata(metadata){const section=document.createElement('section'); section.className='field track-metadata'; const common=metadata&&Array.isArray(metadata.common)?metadata.common:[]; const tags=metadata&&Array.isArray(metadata.tags)?metadata.tags:[];  const seen=new Set(); let rendered=0; const appendRow=(key,value)=>{const canonical=canonicalMetadataKey(key); const valueText=metadataValueText(value); if(!valueText||seen.has(canonical)) return; seen.add(canonical); rendered++; section.append(text(document.createElement('p'),`${metadataLabels[canonical]||key}: ${valueText}`));}; for(const [k,v] of common) appendRow(k,v); for(const [k,vals] of tags) appendRow(k,vals||[]); if(!rendered) section.append(text(document.createElement('p'),'No embedded textual metadata found'));  return section;}
function renderDetail(d){const root=document.getElementById('detail'); const heading=document.createElement('h3'); text(heading,'Current Track'); const fields=document.createElement('div'); fields.append(renderTrackMetadata(d.metadata)); for(const [name,f] of Object.entries(d.fields||{})) fields.append(renderDetailField(name,f)); root.replaceChildren(heading,fields);}
function buildGraphModel(tracks, projection){return buildMoodGraphModel({positioned:tracks||[],edges:(projection&&projection.edges)||[],unpositioned:[],available_moods:[],selected_mood:'',metadata:{}});}
function applyGraphFilters(model, filters){return applyMoodGraphFilters(model,filters);}
function orbitCamera(c,dx,dy){c.yaw=(c.yaw||0)+dx*0.01; c.pitch=(c.pitch||0)+dy*0.01; return c;}
function panCamera(c,dx,dy){c.panX=(c.panX||0)+dx; c.panY=(c.panY||0)+dy; return c;}
function zoomCamera(c,delta){c.distance=(c.distance||0)+delta*0.01; return c;}
function canvasPoint(e,rect,canvas){const cw=canvas.clientWidth||rect.width, ch=canvas.clientHeight||rect.height, bx=canvas.clientLeft||0, by=canvas.clientTop||0; return {x:(e.clientX-rect.left-bx)*(canvas.width/cw),y:(e.clientY-rect.top-by)*(canvas.height/ch)};}
function graphScale(){return 180;}
function axisRange(positioned,axis){let min=Infinity,max=-Infinity; for(const n of positioned){const value=n[axis].raw; if(Number.isFinite(value)){min=Math.min(min,value); max=Math.max(max,value);}} return min===Infinity?null:[min,max];}
function relativeAxis(value,range){return range&&range[0]!==range[1]?(value-range[0])/(range[1]-range[0]):0.5;}
// Relative color only: musical coordinates remain native and are never clipped to a universal scale.
function moodNodeColor(valence,arousal){const hue=215-195*valence, saturation=48+32*arousal, lightness=27+33*arousal; return `hsl(${hue} ${saturation}% ${lightness}%)`;}
function graphColorLegend(model){const r=model.colorRanges||{}; const endpoints=range=>Array.isArray(range)?range:(range&&Number.isFinite(range.min)&&Number.isFinite(range.max)?[range.min,range.max]:null); const display=range=>{const e=endpoints(range); return e?`${displayNumber(e[0])} to ${displayNumber(e[1])}`:'no positioned values';}; return `Color relative to this library: valence blue → orange/red (${display(r.valence)} native); arousal dark/dim → bright (${display(r.arousal)} native). Selected node is larger.`;}
function compactValue(value, fallback){return value==null?fallback:value;}
function normalizeMoodAxisGraphDto(graph){
  if(!graph) return {positioned:[],edges:[],unpositioned:[],available_moods:[],selected_mood:'',metadata:{}};
  if(graph.dto_version==null) return graph;
  if(graph.dto_version!=='mood-axis-graph-compact-v1') throw new Error(`Unsupported mood-axis graph DTO version: ${graph.dto_version}`);
  const normalized={selected_mood:graph.selected_mood||'',available_moods:graph.available_moods||[],metadata:graph.metadata||{},unpositioned:[],positioned:[],edges:[]};
  normalized.unpositioned=(graph.unpositioned||[]).map(u=>({track_id:compactValue(u.track_id,u.id),display_label:compactValue(u.display_label,compactValue(u.label,u.id)),reasons:u.reasons||[]}));
  normalized.positioned=(graph.nodes||[]).map(n=>{
    const axis=n.axis||{};
    const node={track_id:compactValue(n.track_id,n.id),display_label:compactValue(n.display_label,compactValue(n.label,n.id)),x:n.x||axis.x,y:n.y||axis.y,z:n.z||axis.z,mood_score:n.mood_score||null,bpm:n.bpm,genres:n.genres||[],reasons:n.reasons||[]};
    if(n.genre_threshold!=null) node.genre_threshold=n.genre_threshold;
    return node;
  });
  normalized.edges=(graph.links||[]).map(e=>{
    const edge={a:compactValue(e.a,e.source),b:compactValue(e.b,e.target),score:e.score,explanation:e.explanation,provenance:e.provenance};
    if(e.supported_group_count!=null) edge.supported_group_count=e.supported_group_count;
    else if(e.supportedGroupCount!=null) edge.supported_group_count=e.supportedGroupCount;
    return edge;
  });
  return normalized;
}
function buildMoodGraphModel(graph){graph=normalizeMoodAxisGraphDto(graph); const scale=graphScale(); const positioned=graph.positioned||[]; const colorRanges={valence:axisRange(positioned,'x'),arousal:axisRange(positioned,'y')}; const nodes=positioned.map(n=>({color:moodNodeColor(relativeAxis(n.x.raw,colorRanges.valence),relativeAxis(n.y.raw,colorRanges.arousal)),id:n.track_id,label:n.display_label||n.track_id,fx:n.x.normalized*scale*2,fy:n.y.normalized*scale*2,fz:n.z.normalized*scale*2,x:n.x.normalized*scale*2,y:n.y.normalized*scale*2,z:n.z.normalized*scale*2,axis:{x:n.x,y:n.y,z:n.z},moodScore:n.mood_score||null,bpm:n.bpm,genres:n.genres||[],genreThreshold:n.genre_threshold==null?0.5:n.genre_threshold,reasons:n.reasons||[]})); const ids=new Set(nodes.map(n=>n.id)); const links=(graph.edges||[]).filter(e=>ids.has(e.a)&&ids.has(e.b)).map(e=>({source:e.a,target:e.b,name:`relatedness ${displayNumber(e.score)}: ${e.explanation||''}`,score:e.score,explanation:e.explanation,provenance:e.provenance,supportedGroupCount:e.supported_group_count})); const genreOptions=[...new Set(nodes.flatMap(n=>(n.genres||[]).filter(([,score])=>Number.isFinite(score)&&score>0.1).map(([label])=>label)))].sort(); return {nodes,links,colorRanges,unpositioned:graph.unpositioned||[],availableMoods:graph.available_moods||[],selectedMood:graph.selected_mood||'',metadata:graph.metadata||{},genreOptions};}
function applyMoodGraphFilters(model, filters){const nodes=model.nodes.filter(n=>passesGraphFilters(n,filters||{})); const ids=new Set(nodes.map(n=>n.id)); return {nodes,links:model.links.filter(e=>ids.has(String((e.source&&e.source.id)||e.source))&&ids.has(String((e.target&&e.target.id)||e.target))),unpositioned:model.unpositioned};}
// Raw selected-label means, never display-normalized z or camera coordinates.
function buildMoodStrip(data, selectedId){return data.nodes.filter(n=>n.moodScore!=null).map(n=>({id:n.id,label:n.label,score:n.moodScore.raw,position:n.moodScore.raw,selected:n.id===selectedId,description:`${n.label}: ${n.moodScore.label} ${displayNumber(n.moodScore.raw)} / 1 (raw sigmoid mean score)`})).sort((a,b)=>a.score-b.score || (a.id<b.id?-1:a.id>b.id?1:0));}
function passesGraphFilters(n,filters){if(filters.bpmMin!=null && (n.bpm==null || n.bpm<filters.bpmMin)) return false; if(filters.bpmMax!=null && (n.bpm==null || n.bpm>filters.bpmMax)) return false; const genres=filters.genres||[]; if(genres.length){const scores=Object.fromEntries(n.genres); if(!genres.some(g=>Number.isFinite(scores[g]) && scores[g]>0.1)) return false;} return true;}
function graphDimensions(elem){const parent=elem&&elem.parentElement; const style=parent&&typeof getComputedStyle==='function'?getComputedStyle(parent):null; const trim=style?['paddingLeft','paddingRight','borderLeftWidth','borderRightWidth'].reduce((sum,name)=>sum+(parseFloat(style[name])||0),0):0; const width=Math.max(1,Math.floor(((parent&&parent.clientWidth)||elem.clientWidth||900)-trim)); const height=Math.max(1,Math.floor(elem.clientHeight||1040)); return {width,height};}
function updateGraphSize(elem,graph){if(!elem||!graph) return {width:0,height:0}; const size=graphDimensions(elem); graph.width(size.width).height(size.height); return size;}
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
function animateGraphAxes(){
  if(forceGraph){syncGraphAxes(forceGraph,pendingGraphAxisSpec,document.getElementById('graph3d'));placeGraphAxisLabels(forceGraph);syncSelectedNodeHalo(forceGraph,visibleGraph);}
  requestAnimationFrame(animateGraphAxes);
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
function renderMap(data){pendingGraphAxisSpec=graphAxisSpec(graphModel.nodes.length?graphModel.nodes:data.nodes);const elem=document.getElementById('graph3d')||replaceCanvasWithGraphElement(); if(typeof ForceGraph3D==='function'){if(!forceGraph){forceGraph=ForceGraph3D()(elem).enableNodeDrag(false).cooldownTicks(0).nodeId('id').nodeRelSize(4).nodeLabel(nodeLabel).nodeColor(n=>n.color).nodeVal(selectedNodeValue).linkLabel(linkLabel).linkOpacity(1).linkColor(relatednessLinkColor).linkWidth(l=>1+Math.max(0,Number(l.score)||0)); forceGraph.onNodeClick(n=>setCurrent(n.id)); observeGraphResize(elem); if(!graphAxesAnimating && typeof requestAnimationFrame==='function'){graphAxesAnimating=true;requestAnimationFrame(animateGraphAxes);}} const size=updateGraphSize(elem,forceGraph); const signature=JSON.stringify([data.nodes.map(n=>[n.id,n.x,n.y,n.z]),data.links.map(l=>[l.source,l.target,l.score])]); if(signature!==renderedGraphSignature){disposeSelectedNodeHalo(); renderedGraphData={nodes:data.nodes.map(n=>Object.assign({},n,{fx:n.fx,fy:n.fy,fz:n.fz})),links:data.links.map(l=>Object.assign({},l))}; forceGraph.graphData(renderedGraphData); renderedGraphSignature=signature;} else {const live=new Map(data.nodes.map(n=>[n.id,n])); for(const node of renderedGraphData.nodes){const updated=live.get(node.id); if(updated){node.moodScore=updated.moodScore; node.axis=updated.axis;}}} syncSelectedNodeHalo(forceGraph,data); forceGraph.numDimensions(3); forceGraph.d3AlphaDecay(1); forceGraph.d3VelocityDecay(1); const layout=JSON.stringify(data.nodes.map(n=>JSON.stringify([n.id,n.x,n.y,n.z])).sort()); if(layout!==framedGraphLayout){const frame=graphCameraFrame(data.nodes,size,forceGraph.camera().fov); /* cameraPosition lookAt also sets the bundled orbit controls target. */ forceGraph.cameraPosition(frame.position,frame.target,0); framedGraphLayout=layout;}} else {disposeSelectedNodeHalo();renderCanvasFallback(data,elem);} renderMoodStrip(data);}
function nodeLabel(n){return `${escapeHtml(n.label)}<br>valence ${displayNumber(n.axis.x.raw)} (${escapeHtml(n.axis.x.scale)})<br>arousal ${displayNumber(n.axis.y.raw)} (${escapeHtml(n.axis.y.scale)})<br>${escapeHtml(n.axis.z.label)} ${displayNumber(n.axis.z.raw)} (${escapeHtml(n.axis.z.scale)})<br>${n.moodScore?`${escapeHtml(n.moodScore.label)} ${displayNumber(n.moodScore.raw)} / 1`:'Selected mood score unavailable'}`;}
function linkLabel(l){return escapeHtml(`score ${displayNumber(l.score)}; ${l.explanation||''}; groups ${l.supportedGroupCount||0}`);}
function escapeHtml(value){return String(value).replace(/[&<>'"]/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[ch]));}
function replaceCanvasWithGraphElement(){const old=document.getElementById('map'); const div=document.createElement('div'); div.id='graph3d'; if(old) old.replaceWith(div); return div;}
function renderCanvasFallback(data,container){let canvas=document.getElementById('map'); if(!canvas&&container){canvas=(container.children||[]).find(child=>child.tagName==='CANVAS')||document.createElement('canvas'); canvas.id='map'; if(!canvas.parentElement){if(typeof container.replaceChildren==='function') container.replaceChildren(canvas); else if(typeof container.append==='function') container.append(canvas);}} if(!canvas) canvas=document.createElement('canvas'); const size=graphDimensions(canvas); canvas.width=size.width; canvas.height=size.height; const ctx=canvas.getContext('2d'); ctx.clearRect(0,0,canvas.width,canvas.height); ctx.fillStyle='#fafafa'; ctx.fillRect(0,0,canvas.width,canvas.height); for(const n of data.nodes){ctx.beginPath(); ctx.arc(canvas.width/2+n.fx,canvas.height/2-n.fy,n.id===state.current_track_id?9:5,0,Math.PI*2); ctx.fillStyle=n.color; ctx.fill();}}
function buildControls(){const root=document.getElementById('controls'); buildGraphControls(root);}
function clearGraphFilters(){selectedGraphControls={...selectedGraphControls,bpmMin:null,bpmMax:null,genres:[]};}
function buildGraphControls(root){const moodFs=document.createElement('fieldset'); moodFs.id='mood-tracker-controls'; const moodLegend=document.createElement('legend'); text(moodLegend,'Selected mood strength'); moodFs.append(moodLegend); const mood=document.createElement('select'); mood.id='selected-mood'; mood.onchange=()=>{selectedGraphControls.mood=mood.value; if(graphLoadState.status==='ready') return loadGraph(); renderGraphLoadStatus();}; moodFs.append(text(document.createElement('label'),'Mood tracker score label '),mood); root.append(moodFs); const fs=document.createElement('fieldset'); fs.id='graph-controls'; const legend=document.createElement('legend'); text(legend,'Graph filters'); fs.append(legend); const min=document.createElement('input'); min.id='bpm-min'; min.type='number'; min.placeholder='min BPM'; min.setAttribute('aria-label','Minimum BPM'); const max=document.createElement('input'); max.id='bpm-max'; max.type='number'; max.placeholder='max BPM'; max.setAttribute('aria-label','Maximum BPM'); for(const input of [min,max]) input.onchange=()=>{selectedGraphControls.bpmMin=min.value===''?null:Number(min.value); selectedGraphControls.bpmMax=max.value===''?null:Number(max.value); applyCurrentGraphFilters();}; fs.append(min,max); const genres=document.createElement('select'); genres.id='genre-filter'; genres.multiple=true; genres.size=4; genres.onchange=()=>{selectedGraphControls.genres=Array.from(genres.selectedOptions).map(o=>o.value); applyCurrentGraphFilters();}; fs.append(text(document.createElement('label'),' Genres ANY '),genres); const clear=document.createElement('button'); clear.id='clear-graph-filters'; clear.type='button'; text(clear,'Clear graph filters'); clear.onclick=()=>{clearGraphFilters(); min.value=''; max.value=''; for(const option of genres.options||genres.children||[]) option.selected=false; applyCurrentGraphFilters();}; fs.append(clear); root.append(fs);}
function syncGraphControlOptions(model){const mood=document.getElementById('selected-mood'); if(mood){const current=selectedGraphControls.mood||model.selectedMood||''; mood.replaceChildren(...(model.availableMoods.length?model.availableMoods:['']).map(m=>{const o=document.createElement('option'); o.value=m; text(o,m||'No supported moods'); o.selected=m===current; return o;})); selectedGraphControls.mood=current&&model.availableMoods.includes(current)?current:(model.selectedMood||'');} const genres=document.getElementById('genre-filter'); if(genres){const selected=new Set(selectedGraphControls.genres||[]); genres.replaceChildren(...model.genreOptions.map(g=>{const o=document.createElement('option'); o.value=g; text(o,g); o.selected=selected.has(g); return o;}));}}
function wireCanvas(){/* 3d-force-graph owns orbit/pick controls. */}
if(typeof document!=='undefined'){document.getElementById('undo').onclick=()=>applyHistorySelection('/api/undo'); document.getElementById('reset').onclick=()=>applyHistorySelection('/api/reset'); const retry=document.getElementById('loading-retry'); if(retry) retry.onclick=()=>refresh().catch(()=>{}); buildControls(); renderGraphLoadStatus(); wireCanvas(); refresh().catch(()=>{});}
function setGraphModelForTesting(model){graphModel=model;}
function setStateForTesting(next){state={...state,...next};}
function setVisibleGraphForTesting(model){visibleGraph=model;}
function setGraphControlsForTesting(controls){selectedGraphControls={...selectedGraphControls,...controls,genres:[...((controls&&controls.genres)||selectedGraphControls.genres||[])]};}
function getGraphControlsForTesting(){return {...selectedGraphControls,genres:[...(selectedGraphControls.genres||[])]};}
function getVisibleGraphForTesting(){return {nodes:[...(visibleGraph.nodes||[])],links:[...(visibleGraph.links||[])],unpositioned:[...(visibleGraph.unpositioned||[])]};}
function getStateForTesting(){return {...state,history:[...(state.history||[])]};}
if(typeof module!=='undefined'){module.exports={refresh,updateSelectedTrackVisuals,renderMap,syncSelectedNodeHalo,setLoadingPhase,setLoadingError,clearLoading,nextFrame,detailGauge,displayNumber,graphAxisSpec,syncGraphAxes,buildMoodStrip,nodeLabel,normalizeMoodAxisGraphDto,buildMoodGraphModel,moodNodeColor,graphColorLegend,graphQueryFromControls,applyMoodGraphFilters,passesGraphFilters,buildGraphModel,applyGraphFilters,orbitCamera,panCamera,zoomCamera,canvasPoint,fieldDisplay,graphDimensions,updateGraphSize,graphCameraFrame,selectionClientId,syncSelectionEpoch,renderInitialDetail,renderDetail,renderTrackMetadata,setGraphModelForTesting,setVisibleGraphForTesting,setStateForTesting,getStateForTesting,loadGraph,applyCurrentGraphFilters,renderGraphLoadStatus,renderTracks,loadTrackSummaryPage,loadNextTrackSummaryPage,graphRelatednessLegend,relatednessLinkAlpha,buildGraphControls,syncGraphControlOptions,clearGraphFilters,downloadM3UPlaylist,setGraphControlsForTesting,getGraphControlsForTesting,getVisibleGraphForTesting};}
