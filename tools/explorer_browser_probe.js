// External observation only: packaged application bytes remain unchanged.
(() => {
  const d = window.__diagnostic = {milestones_ms:{navigation:0}, requests:[],
    responsiveness:{frame_gaps_ms:[],long_tasks_ms:[],input_latency_ms:[],frame_count:0,long_tasks_status:'observed'}, consumed_count:0};
  const now=()=>performance.now();
  let last=null;
  function frame(t){if(last!==null)d.responsiveness.frame_gaps_ms.push(t-last);last=t;d.responsiveness.frame_count++;requestAnimationFrame(frame);}
  requestAnimationFrame(frame);
  new PerformanceObserver(list=>{for(const entry of list.getEntries())d.responsiveness.long_tasks_ms.push(entry.duration);}).observe({type:'longtask',buffered:true});
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
        d.graph_response={content_encoding:response.headers.get('Content-Encoding'),
          content_length:Number(response.headers.get('Content-Length'))};
      }
      response.json=async()=>{
        // Split the actual consumed body from parse, without a duplicate body/clone.
        const text=await response.text();
        if(graph)d.milestones_ms.graph_body=now();
        const value=JSON.parse(text);
        if(graph){
          d.milestones_ms.graph_json=now();
          const bytes=new TextEncoder().encode(text);
          const digest=await crypto.subtle.digest('SHA-256',bytes);
          d.graph_response.consumed_bytes=bytes.byteLength;
          d.graph_response.consumed_sha256=Array.from(new Uint8Array(digest),b=>b.toString(16).padStart(2,'0')).join('');
          d.graph_response.json_counts={nodes:value.nodes.length,links:value.links.length,unpositioned:value.unpositioned.length};
        }
        return value;
      };
      return response;
    }catch(error){record.elapsed_ms=now()-start;throw error;}
  };
  document.addEventListener('input',()=>{const t=now();requestAnimationFrame(()=>d.responsiveness.input_latency_ms.push(now()-t));},true);
})();
