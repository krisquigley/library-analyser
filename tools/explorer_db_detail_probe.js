// Outward observer only. Handles and graph bodies are transient, never published.
(() => {
  const d=window.__dbBridge={requests:[],selections:[]}, original=window.fetch;
  const now=()=>performance.now();
  window.fetch=async function(input,options={}) {
    const path=new URL(String(input),location.href).pathname;
    const route=path.startsWith('/api/tracks/')&&path!='/api/tracks/summary'?'/api/tracks/<id>':path;
    const r={route,method:options.method||'GET',request_id:'request-'+(d.requests.length+1),request_ms:now()};
    const selected=d.selections.at(-1);
    if(route==='/api/current'&&r.method==='POST') {
      r.request_handle=JSON.parse(options.body).track_id;
      r.sequence=selected?.sequence;
    }
    if(route==='/api/tracks/<id>') {
      r.request_handle=decodeURIComponent(path.slice('/api/tracks/'.length));
      r.sequence=selected?.sequence;
    }
    d.requests.push(r);
    try {
      const response=await original.apply(this,arguments);
      r.headers_ms=now();r.status=response.status;
      response.json=async()=> {
        const text=await response.text();r.body_ms=now();
        const value=JSON.parse(text);r.parse_ms=now();
        if(route==='/api/current')r.response_handle=value.current_track_id;
        if(route==='/api/tracks/<id>')r.response_handle=value.handle;
        if(route==='/api/mood-axis-graph'&&response.ok) {
          const bytes=new TextEncoder().encode(text);d.graph_bytes=bytes.length;
          d.graph_counts={nodes:value.nodes.length,links:value.links.length,unpositioned:value.unpositioned.length};
          d.graph_value=value;
          d.graph_sha256=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),b=>b.toString(16).padStart(2,'0')).join('');
        }
        return value;
      };
      return response;
    } catch(error) {r.failed=true;throw error;}
  };
  document.addEventListener('click',event=> {
    if(event.target.closest('#tracks tbody tr'))d.selections.push({sequence:d.selections.length+1,
      intended_handle:d.intended_handle,receipt_ms:now(),is_trusted:event.isTrusted===true});
  },true);
})();
