const controls=['tempo','harmony','energy','genre','mood'];
let state={current_track_id:null};
let graphModel={nodes:[],links:[],unpositioned:[],availableMoods:[],selectedMood:'',metadata:{},genreOptions:[]};
let visibleGraph={nodes:[],links:[],unpositioned:[]};
let forceGraph=null;
let framedGraphLayout=null;
let renderedGraphSignature=null;
let renderedGraphData={nodes:[],links:[]};
let graphResizeObserver=null;
let graphAxes=null;
let graphAxesAnimating=false;
let pendingGraphAxisSpec=[];
let selectedGraphControls={mood:'',bpmMin:null,bpmMax:null,genres:[]};
let selectionRequestSeq=0;
const selectionPostSeqKey='music-explorer-selection-post-seq';
let selectionPostSeq=loadSelectionPostSeq();
let selectionEpoch=0;
let refreshRequestSeq=0;
let selectionDetailRequestSeq=0;
let pendingSelectionIntent=null;
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
async function api(path, options){const r=await fetch(path, options); if(!r.ok) throw new Error(await r.text()); return r.json();}
function selectedControls(){const out={}; for(const n of controls){const el=document.querySelector(`[name=${n}]:checked`); out[n]=el?el.value:'off';} return out;}
function controlQuery(){return controls.map(n=>{const mode=(selectedControls()[n]||'off'); return `control=${encodeURIComponent(`${n}:${mode}:1`)}`;}).join('&');}
function selectedNodeValue(n){return n.id===state.current_track_id?4:1;}
function updateSelectedTrackVisuals(){
  if(typeof document!=='undefined') for(const li of document.querySelectorAll('#tracks li[data-track-id]')) li.className=li.dataset.trackId===state.current_track_id?'current':'';
  if(forceGraph){forceGraph.nodeVal(selectedNodeValue); if(typeof forceGraph.refresh==='function') forceGraph.refresh();}
  else if(visibleGraph.nodes.length) renderCanvasFallback(visibleGraph);
  renderMoodStrip(visibleGraph);
}
async function refreshSelectionDependent(token){
  if(token!==selectionRequestSeq) return;
  const detailToken=++selectionDetailRequestSeq;
  const selectedId=state.current_track_id;
  updateSelectedTrackVisuals();
  if(selectedId){
    const [detail,candidates]=await Promise.all([api('/api/tracks/'+encodeURIComponent(selectedId)),api('/api/candidates?'+controlQuery()+'&current='+encodeURIComponent(selectedId))]);
    if(token!==selectionRequestSeq || detailToken!==selectionDetailRequestSeq || state.current_track_id!==selectedId) return;
    renderDetail(detail); renderCandidates(candidates); updateSelectedTrackVisuals();
  } else {
    if(token!==selectionRequestSeq || detailToken!==selectionDetailRequestSeq) return;
    renderInitialDetail(graphModel); renderCandidates({candidates:[]});
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
async function refresh(){const refreshToken=++refreshRequestSeq; const token=selectionRequestSeq; const refreshedState=syncSelectionEpoch(await api('/api/state')); if(refreshToken!==refreshRequestSeq || token!==selectionRequestSeq) return; const list=await api('/api/tracks?limit=all'); if(refreshToken!==refreshRequestSeq || token!==selectionRequestSeq) return; const graph=await api('/api/mood-axis-graph'+graphQueryFromControls()); if(refreshToken!==refreshRequestSeq || token!==selectionRequestSeq) return; state={...refreshedState,current_track_id:pendingSelectionIntent||refreshedState.current_track_id}; renderTracks(list.tracks); graphModel=buildMoodGraphModel(graph); syncGraphControlOptions(graphModel); visibleGraph=applyMoodGraphFilters(graphModel,selectedGraphControls); renderMap(visibleGraph); await refreshSelectionDependent(token);}
function renderTracks(tracks){const ul=document.getElementById('tracks'); ul.replaceChildren(...tracks.map(t=>{const li=document.createElement('li'); li.dataset.trackId=t.handle; li.className=t.handle===state.current_track_id?'current':''; const b=document.createElement('button'); text(b,t.display_label||t.handle); b.onclick=()=>setCurrent(t.handle); li.append(b); return li;}));}
function renderInitialDetail(model){const root=document.getElementById('detail'); const h=document.createElement('h3'); text(h,'All-library valence / arousal / BPM graph'); const p=document.createElement('p'); text(p,`Showing ${visibleGraph.nodes.length} positioned tracks and ${model.unpositioned.length} unpositioned tracks. X=native valence, Y=native arousal, Z=raw BPM (fixed 20 BPM per depth unit); selected mood ${model.selectedMood||'none'} only changes the score strip; no sample-relative clipping.`); const help=document.createElement('p'); help.className='muted'; text(help,'3d-force-graph is bundled locally. Fixed coordinates are scaled for readable display only. Drag to orbit, wheel to zoom, hover/click nodes and links for evidence. Sparse edges are axis-independent relatedness from existing summaries, not screen distance.'); const list=document.createElement('ul'); for(const u of model.unpositioned){const li=document.createElement('li'); text(li,`${u.display_label||u.track_id}: ${(u.reasons||[]).join('; ')}`); list.append(li);} root.replaceChildren(h,p,help,list);}
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
function renderDetail(d){const root=document.getElementById('detail'); const selected=graphModel.nodes.find(n=>n.id===d.handle); const score=document.createElement('p'); const selectedScore=selected?.moodScore; text(score,selectedScore?`Selected ${selectedScore.label} raw sigmoid mean score: ${displayNumber(selectedScore.raw)} / 1 (not a calibrated probability).`:`Selected ${graphModel.selectedMood||'mood'} score: unavailable for this track.`); const parts=[document.createElement('h3'),document.createElement('p')]; text(parts[0],d.display_label||d.handle); text(parts[1],`Status: ${d.latest_run_status||'missing'} · Locations: ${d.available_locations}`); const reasons=document.createElement('p'); reasons.className='muted'; text(reasons,(d.reasons||[]).join('; ')); const fields=document.createElement('div'); for(const [name,f] of Object.entries(d.fields||{})) fields.append(renderDetailField(name,f)); root.replaceChildren(...parts,score,reasons,fields);}
function renderCandidates(data){const ol=document.getElementById('candidates'); ol.replaceChildren(...(data.candidates||[]).map(c=>{const li=document.createElement('li'); text(li,`${c.display_label||c.track_id} — ${c.tier} ${c.score==null?'':displayNumber(c.score)}`); return li;}));}
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
function graphColorLegend(model){const r=model.colorRanges||{}; const display=range=>range?`${displayNumber(range[0])} to ${displayNumber(range[1])}`:'no positioned values'; return `Color relative to this library: valence blue → orange/red (${display(r.valence)} native); arousal dark/dim → bright (${display(r.arousal)} native). Selected node is larger.`;}
function buildMoodGraphModel(graph){const scale=graphScale(); const positioned=graph.positioned||[]; const colorRanges={valence:axisRange(positioned,'x'),arousal:axisRange(positioned,'y')}; const nodes=positioned.map(n=>({color:moodNodeColor(relativeAxis(n.x.raw,colorRanges.valence),relativeAxis(n.y.raw,colorRanges.arousal)),id:n.track_id,label:n.display_label||n.track_id,fx:n.x.normalized*scale,fy:n.y.normalized*scale,fz:n.z.normalized*scale*2,x:n.x.normalized*scale,y:n.y.normalized*scale,z:n.z.normalized*scale*2,axis:{x:n.x,y:n.y,z:n.z},moodScore:n.mood_score||null,bpm:n.bpm,genres:n.genres||[],genreThreshold:n.genre_threshold==null?0.5:n.genre_threshold,reasons:n.reasons||[]})); const ids=new Set(nodes.map(n=>n.id)); const links=(graph.edges||[]).filter(e=>ids.has(e.a)&&ids.has(e.b)).map(e=>({source:e.a,target:e.b,name:`relatedness ${displayNumber(e.score)}: ${e.explanation||''}`,score:e.score,explanation:e.explanation,provenance:e.provenance,supportedGroupCount:e.supported_group_count})); const genreOptions=[...new Set(nodes.flatMap(n=>(n.genres||[]).map(g=>g[0])))].sort(); return {nodes,links,colorRanges,unpositioned:graph.unpositioned||[],availableMoods:graph.available_moods||[],selectedMood:graph.selected_mood||'',metadata:graph.metadata||{},genreOptions};}
function applyMoodGraphFilters(model, filters){const nodes=model.nodes.filter(n=>passesGraphFilters(n,filters||{})); const ids=new Set(nodes.map(n=>n.id)); return {nodes,links:model.links.filter(e=>ids.has(String((e.source&&e.source.id)||e.source))&&ids.has(String((e.target&&e.target.id)||e.target))),unpositioned:model.unpositioned};}
// Raw selected-label means, never display-normalized z or camera coordinates.
function buildMoodStrip(data, selectedId){return data.nodes.filter(n=>n.moodScore!=null).map(n=>({id:n.id,label:n.label,score:n.moodScore.raw,position:n.moodScore.raw,selected:n.id===selectedId,description:`${n.label}: ${n.moodScore.label} ${displayNumber(n.moodScore.raw)} / 1 (raw sigmoid mean score)`})).sort((a,b)=>a.score-b.score || (a.id<b.id?-1:a.id>b.id?1:0));}
function passesGraphFilters(n,filters){if(filters.bpmMin!=null && (n.bpm==null || n.bpm<filters.bpmMin)) return false; if(filters.bpmMax!=null && (n.bpm==null || n.bpm>filters.bpmMax)) return false; const genres=filters.genres||[]; if(genres.length){const scores=Object.fromEntries(n.genres); if(!genres.some(g=>(scores[g]??-1)>=n.genreThreshold)) return false;} return true;}
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
  return [['x','X valence (native)','#ff7777',180],['y','Y arousal (native)','#76dfa0',180],['z','Z BPM','#84b9ff',36]].map(([key,label,color,units])=>{
    const end={...start,[key]:Math.max(max[key]+18,start[key]+36)};
    const format=n=>displayNumber(n/units);
    return {key,label,color,start,end,references:[format(min[key]),format(max[key])]};
  });
}
function disposeGraphAxes(group){
  if(!group) return;
  group.parent.remove(group);
  for(const mesh of group.children){mesh.geometry.dispose();mesh.material.dispose();}
  if(group.labels) for(const label of group.labels) label.remove();
}
// Vendor bundles THREE privately. Reuse constructors of its rendered node mesh, so
// scene objects share that exact THREE instance without a second dependency/global.
function syncGraphAxes(graph,spec,element){
  const signature=JSON.stringify(spec);
  if(graphAxes && graphAxes.graph===graph && graphAxes.signature===signature) return graphAxes.group;
  const scene=graph.scene();
  if(!spec.length){disposeGraphAxes(graphAxes?.group);graphAxes=null;return null;}
  const findNode=obj=>obj.__graphObjType==='node' && obj.geometry && obj.material ? obj : (obj.children||[]).map(findNode).find(Boolean);
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
  if(forceGraph){syncGraphAxes(forceGraph,pendingGraphAxisSpec,document.getElementById('graph3d'));placeGraphAxisLabels(forceGraph);}
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
function renderMap(data){pendingGraphAxisSpec=graphAxisSpec(graphModel.nodes.length?graphModel.nodes:data.nodes);const elem=document.getElementById('graph3d')||replaceCanvasWithGraphElement(); if(typeof ForceGraph3D==='function'){if(!forceGraph){forceGraph=ForceGraph3D()(elem).enableNodeDrag(false).cooldownTicks(0).nodeId('id').nodeRelSize(4).nodeLabel(nodeLabel).nodeColor(n=>n.color).nodeVal(selectedNodeValue).linkLabel(linkLabel).linkOpacity(0.28).linkWidth(l=>1+Math.max(0,Number(l.score)||0)); forceGraph.onNodeClick(n=>setCurrent(n.id)); observeGraphResize(elem); if(!graphAxesAnimating && typeof requestAnimationFrame==='function'){graphAxesAnimating=true;requestAnimationFrame(animateGraphAxes);}} const size=updateGraphSize(elem,forceGraph); const signature=JSON.stringify([data.nodes.map(n=>[n.id,n.x,n.y,n.z]),data.links.map(l=>[l.source,l.target,l.score])]); if(signature!==renderedGraphSignature){renderedGraphData={nodes:data.nodes.map(n=>Object.assign({},n,{fx:n.fx,fy:n.fy,fz:n.fz})),links:data.links}; forceGraph.graphData(renderedGraphData); renderedGraphSignature=signature;} else {const live=new Map(data.nodes.map(n=>[n.id,n])); for(const node of renderedGraphData.nodes){const updated=live.get(node.id); if(updated){node.moodScore=updated.moodScore; node.axis=updated.axis;}}} forceGraph.numDimensions(3); forceGraph.d3AlphaDecay(1); forceGraph.d3VelocityDecay(1); const layout=JSON.stringify(data.nodes.map(n=>JSON.stringify([n.id,n.x,n.y,n.z])).sort()); if(layout!==framedGraphLayout){const frame=graphCameraFrame(data.nodes,size,forceGraph.camera().fov); /* cameraPosition lookAt also sets the bundled orbit controls target. */ forceGraph.cameraPosition(frame.position,frame.target,0); framedGraphLayout=layout;}} else {renderCanvasFallback(data);} renderMoodStrip(data); const info=document.getElementById('graph-info'); if(info) text(info,`${data.nodes.length} positioned tracks · ${data.links.length} sparse relatedness edges · ${data.unpositioned.length} unpositioned · score strip mood ${graphModel.selectedMood||'n/a'} · ${graphColorLegend(graphModel)} · no CDN calls`);}
function nodeLabel(n){return `${escapeHtml(n.label)}<br>valence ${displayNumber(n.axis.x.raw)} (${escapeHtml(n.axis.x.scale)})<br>arousal ${displayNumber(n.axis.y.raw)} (${escapeHtml(n.axis.y.scale)})<br>${escapeHtml(n.axis.z.label)} ${displayNumber(n.axis.z.raw)} (${escapeHtml(n.axis.z.scale)})<br>${n.moodScore?`${escapeHtml(n.moodScore.label)} ${displayNumber(n.moodScore.raw)} / 1`:'Selected mood score unavailable'}`;}
function linkLabel(l){return escapeHtml(`score ${displayNumber(l.score)}; ${l.explanation||''}; groups ${l.supportedGroupCount||0}`);}
function escapeHtml(value){return String(value).replace(/[&<>'"]/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[ch]));}
function replaceCanvasWithGraphElement(){const old=document.getElementById('map'); const div=document.createElement('div'); div.id='graph3d'; if(old) old.replaceWith(div); return div;}
function renderCanvasFallback(data){const canvas=document.getElementById('map')||document.createElement('canvas'); const size=graphDimensions(canvas); canvas.width=size.width; canvas.height=size.height; const ctx=canvas.getContext('2d'); ctx.clearRect(0,0,canvas.width,canvas.height); ctx.fillStyle='#fafafa'; ctx.fillRect(0,0,canvas.width,canvas.height); for(const n of data.nodes){ctx.beginPath(); ctx.arc(canvas.width/2+n.fx,canvas.height/2-n.fy,n.id===state.current_track_id?9:5,0,Math.PI*2); ctx.fillStyle=n.color; ctx.fill();}}
function buildControls(){const root=document.getElementById('controls'); buildGraphControls(root); for(const n of controls){const div=document.createElement('div'); div.append(text(document.createElement('span'),n+': ')); for(const m of ['off','soft','hard']){const label=document.createElement('label'), input=document.createElement('input'); input.type='radio'; input.name=n; input.value=m; input.checked=m==='off'; input.onchange=()=>{if(state.current_track_id) refresh();}; label.append(input,document.createTextNode(m)); div.append(label);} root.append(div);}}
function buildGraphControls(root){const fs=document.createElement('fieldset'); fs.id='graph-controls'; const legend=document.createElement('legend'); text(legend,'Graph filters and score display'); fs.append(legend); const mood=document.createElement('select'); mood.id='selected-mood'; mood.onchange=()=>{selectedGraphControls.mood=mood.value; refresh();}; fs.append(text(document.createElement('label'),'Score strip mood '),mood); const min=document.createElement('input'); min.id='bpm-min'; min.type='number'; min.placeholder='min BPM'; const max=document.createElement('input'); max.id='bpm-max'; max.type='number'; max.placeholder='max BPM'; for(const input of [min,max]) input.onchange=()=>{selectedGraphControls.bpmMin=min.value===''?null:Number(min.value); selectedGraphControls.bpmMax=max.value===''?null:Number(max.value); refresh();}; fs.append(min,max); const genres=document.createElement('select'); genres.id='genre-filter'; genres.multiple=true; genres.size=4; genres.onchange=()=>{selectedGraphControls.genres=Array.from(genres.selectedOptions).map(o=>o.value); refresh();}; fs.append(text(document.createElement('label'),' Genres ANY '),genres); const clear=document.createElement('button'); clear.type='button'; text(clear,'Clear graph filters'); clear.onclick=()=>{selectedGraphControls={mood:graphModel.selectedMood||'',bpmMin:null,bpmMax:null,genres:[]}; min.value=''; max.value=''; refresh();}; fs.append(clear); root.append(fs);}
function syncGraphControlOptions(model){const mood=document.getElementById('selected-mood'); if(mood){const current=selectedGraphControls.mood||model.selectedMood||''; mood.replaceChildren(...(model.availableMoods.length?model.availableMoods:['']).map(m=>{const o=document.createElement('option'); o.value=m; text(o,m||'No supported moods'); o.selected=m===current; return o;})); selectedGraphControls.mood=current&&model.availableMoods.includes(current)?current:(model.selectedMood||'');} const genres=document.getElementById('genre-filter'); if(genres){const selected=new Set(selectedGraphControls.genres||[]); genres.replaceChildren(...model.genreOptions.map(g=>{const o=document.createElement('option'); o.value=g; text(o,g); o.selected=selected.has(g); return o;}));}}
function wireCanvas(){/* 3d-force-graph owns orbit/pick controls. */}
if(typeof document!=='undefined'){document.getElementById('undo').onclick=()=>applyHistorySelection('/api/undo'); document.getElementById('reset').onclick=()=>applyHistorySelection('/api/reset'); buildControls(); wireCanvas(); refresh().catch(e=>text(document.getElementById('detail'),e.message));}
if(typeof module!=='undefined'){module.exports={detailGauge,displayNumber,graphAxisSpec,syncGraphAxes,buildMoodStrip,nodeLabel,buildMoodGraphModel,moodNodeColor,graphColorLegend,graphQueryFromControls,applyMoodGraphFilters,passesGraphFilters,buildGraphModel,applyGraphFilters,orbitCamera,panCamera,zoomCamera,canvasPoint,fieldDisplay,graphDimensions,updateGraphSize,graphCameraFrame,selectionClientId,syncSelectionEpoch};}
