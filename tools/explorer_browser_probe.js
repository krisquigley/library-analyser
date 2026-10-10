// External observation only: packaged application bytes remain unchanged.
(() => {
  const observerMode=window.__diagnosticObserverMode==='native-json'?'native-json':'verified';
  const milestones={navigation:0};
  for(const name of ['graph_body_start','graph_body_end','graph_body','graph_json_start','graph_json_end','graph_json',
    'graph_verification_start','graph_verification_end','graph_native_json_start','graph_native_json_end',
    'graph_model_start','graph_model_end','graph_scene_start','graph_scene_end',
    'graph_first_presentation','graph_post_focus_readback'])milestones[name]=null;
  const d = window.__diagnostic = {observer_mode:observerMode,milestones_ms:milestones, requests:[],input_observations:[],
    responsiveness:{frame_gaps_ms:[],long_tasks_ms:[],long_tasks:[],gpu_time_ms:null,
      input_latency_ms:[],frame_count:0,long_tasks_status:'observed'}, consumed_count:0};
  const now=()=>performance.now();
  let last=null;
  function frame(t){if(last!==null)d.responsiveness.frame_gaps_ms.push(t-last);last=t;d.responsiveness.frame_count++;requestAnimationFrame(frame);}
  requestAnimationFrame(frame);
  try{
    if(PerformanceObserver.supportedEntryTypes && !PerformanceObserver.supportedEntryTypes.includes('longtask'))throw new Error('unsupported');
    new PerformanceObserver(list=>{for(const entry of list.getEntries()){
      if(!Number.isFinite(entry.startTime)||!Number.isFinite(entry.duration)||entry.startTime<0||entry.duration<0)continue;
      d.responsiveness.long_tasks_ms.push(entry.duration);
      d.responsiveness.long_tasks.push({start_ms:entry.startTime,end_ms:entry.startTime+entry.duration,duration_ms:entry.duration});
    }}).observe({type:'longtask',buffered:true});
  }catch(error){d.responsiveness.long_tasks_status='unavailable';}
  function route(path){if(['/api/state','/api/current','/api/mood-axis-graph','/api/tracks/summary'].includes(path))return path;if(path.startsWith('/api/tracks/'))return '/api/tracks/<id>';return 'unknown';}
  const original=window.fetch;
  window.fetch=async function(input,options){
    const path=new URL(input,location.href).pathname, start=now(), graph=path==='/api/mood-axis-graph';
    if(graph)d.milestones_ms.graph_request=start;
    const record={route:route(path),method:options?.method||'GET',outcome:'connection_error',elapsed_ms:null};d.requests.push(record);
    try{
      const response=await original.apply(this,arguments);
      record.status=response.status;record.outcome=response.ok?'ok':'http_error';record.elapsed_ms=now()-start;
      if(graph&&response.ok){
        d.milestones_ms.graph_headers=now();
        const lengthHeader=response.headers.get('Content-Length');
        const length=lengthHeader!==null && lengthHeader.trim()!==''?Number(lengthHeader):NaN;
        d.graph_response={content_encoding:response.headers.get('Content-Encoding'),
          content_length:Number.isFinite(length)&&length>=0?length:null,
          consumed_bytes:null,consumed_sha256:null,
          consumed_identity_status:observerMode==='native-json'?'unavailable-native-json':'unavailable'};
      }
      const nativeJson=response.json;
      response.json=async()=>{
        if(observerMode==='native-json'){
          if(graph)d.milestones_ms.graph_native_json_start=now();
          const value=await nativeJson.call(response);
          if(graph){
            d.milestones_ms.graph_native_json_end=now();
            d.graph_response.json_counts={nodes:value.nodes.length,links:value.links.length,unpositioned:value.unpositioned.length};
          }
          return value;
        }
        // Split the actual consumed body from parse, without a duplicate body/clone.
        if(graph)d.milestones_ms.graph_body_start=now();
        const text=await response.text();
        if(graph){d.milestones_ms.graph_body_end=now();d.milestones_ms.graph_body=d.milestones_ms.graph_body_end;d.milestones_ms.graph_json_start=now();}
        const value=JSON.parse(text);
        if(graph){
          d.milestones_ms.graph_json_end=now();d.milestones_ms.graph_json=d.milestones_ms.graph_json_end;
          d.milestones_ms.graph_verification_start=now();
          const bytes=new TextEncoder().encode(text);
          const digest=await crypto.subtle.digest('SHA-256',bytes);
          d.graph_response.consumed_bytes=bytes.byteLength;
          d.graph_response.consumed_sha256=Array.from(new Uint8Array(digest),b=>b.toString(16).padStart(2,'0')).join('');
          d.graph_response.json_counts={nodes:value.nodes.length,links:value.links.length,unpositioned:value.unpositioned.length};
          d.graph_response.consumed_identity_status='verified';
          d.milestones_ms.graph_verification_end=now();
        }
        return value;
      };
      return response;
    }catch(error){record.elapsed_ms=now()-start;throw error;}
  };
  // Install only at the outward decoration seam, after packaged functions exist.
  // No poses, bounds, durations, controls, or runtime cancellation rules change.
  d.installFocusObservation=function(){
    if(d.focus?.motion)return;
    d.focus={...(d.focus||{}),motion:{starts:[],cancellations:[]}};
    if(typeof cancelCameraFocus!=='function'||typeof cameraFocusFrame==='undefined')return;
    let reason=null, pendingUnclassified=null;
    const observedControls=new WeakSet();
    const withReason=(label,call)=>{const previous=reason;reason=label;try{return call();}finally{reason=previous;}};
    const cancel=cancelCameraFocus;
    cancelCameraFocus=function(){
      const active=cameraFocusFrame!=null, at=now();
      if(!active){
        // An idle cancellation cannot attribute an earlier plain cancellation.
        // Also undo a tentative label if our start observer ran first.
        if(pendingUnclassified?.reason==='user-orbit')pendingUnclassified.reason='unclassified';
        pendingUnclassified=null;
      }
      const value=cancel.apply(this,arguments);
      if(active&&cameraFocusFrame==null){
        const label=arguments[0]?.type==='start'?'user-orbit':(reason||'unclassified');
        const record={reason:label,at_ms:at,clock:'browser-performance'};
        d.focus.motion.cancellations.push(record);
        pendingUnclassified=label==='unclassified'?record:null;
        // Only the current synchronous dispatch can supply a discarded cause;
        // a later event with the same quantized clock must not reuse it.
        if(pendingUnclassified)Promise.resolve().then(()=>{
          if(pendingUnclassified===record)pendingUnclassified=null;
        });
      }
      return value;
    };
    function watchControls(){
      const controls=typeof forceGraph!=='undefined'&&forceGraph?.controls?.();
      if(!controls?.addEventListener||observedControls.has(controls))return;
      observedControls.add(controls);
      controls.addEventListener('start',()=>{
        // An adapter may discard the event argument before invoking cancellation.
        // Correlate only an actual cancellation in this synchronous event tick;
        // never label an idle start, completion, or arbitrary cancellation orbit.
        if(pendingUnclassified&&pendingUnclassified.at_ms===now()&&cameraFocusFrame==null){
          pendingUnclassified.reason='user-orbit';
        }
      });
    }
    const select=setCurrent;
    setCurrent=function(){pendingUnclassified=null;return withReason('new-selection',()=>select.apply(this,arguments));};
    const focus=animateCameraFocus;
    animateCameraFocus=function(){
      pendingUnclassified=null;watchControls();
      const start={at_ms:now(),clock:'browser-performance',active_after:null};
      d.focus.motion.starts.push(start);
      const value=withReason('new-focus',()=>focus.apply(this,arguments));
      start.active_after=cameraFocusFrame!=null;
      watchControls();return value;
    };
    watchControls();
  };
  function phase(){
    const m=d.milestones_ms;
    if(typeof cameraFocusFrame!=='undefined'&&cameraFocusFrame!=null)return 'focus';
    for(const name of ['body','json','verification','model','scene'])if(m['graph_'+name+'_start']!=null&&m['graph_'+name+'_end']==null)return name;
    if(m.graph_native_json_start!=null&&m.graph_native_json_end==null)return 'native-json';
    return m.graph_scene_end!=null?'after-scene':'pending';
  }
  function receipt(event){
    const t=now(),record={action:event.type==='input'?'input':event.type==='pointerdown'?'orbit':'selection',
      receipt_clock:'browser-performance',received_ms:t,frame_ms:null,
      is_trusted:event.isTrusted===true,phase_at_receipt:phase()};
    if(d.contention_action)d.input_observations.push(record);
    requestAnimationFrame(()=>{
      record.frame_ms=now();
      if(event.type==='input')d.responsiveness.input_latency_ms.push(record.frame_ms-t);
    });
  }
  document.addEventListener('input',receipt,true);
  document.addEventListener('pointerdown',event=>{
    const canvas=typeof forceGraph!=='undefined'&&forceGraph?.renderer?.()?.domElement;
    if(d.contention_action&&canvas&&event.target===canvas)receipt(event);
  },true);
  document.addEventListener('click',event=>{if(d.contention_action)receipt(event);},true);
})();
