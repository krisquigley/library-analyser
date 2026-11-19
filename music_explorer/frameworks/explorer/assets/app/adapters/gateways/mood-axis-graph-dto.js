// The graph response (#146): its compact and indexed DTOs, checked and normalised at the boundary.
// A malformed row or an out-of-range table reference is refused whole, never half-read.

export function isIndexedMoodAxisGraph(graph) {
  return Boolean(graph) && graph.dto_version === 'mood-axis-graph-indexed-v1';
}

function compactValue(value, fallback){return value==null?fallback:value;}
export function normalizeMoodAxisGraphDto(graph){
  if(!graph) return {positioned:[],edges:[],unpositioned:[],available_moods:[],selected_mood:'',metadata:{}};
  if(graph.dto_version==null) return graph;
  if(isIndexedMoodAxisGraph(graph)) return normalizeIndexedMoodAxisGraphDto(graph);
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
function indexedTableValue(table,index,label){
  if(index==null) return undefined;
  if(!Number.isInteger(index)||index<0||index>=table.length) throw new Error(`Invalid indexed graph ${label} reference: ${index}`);
  return table[index];
}
function normalizeIndexedMoodAxisGraphDto(graph){
  const axisByKey=Object.fromEntries((graph.axis||[]).map(a=>[a.key,a]));
  const axis=(key,raw,normalized)=>({label:(axisByKey[key]&&axisByKey[key].label)||key,raw,normalized,scale:axisByKey[key]&&axisByKey[key].scale});
  const genres=graph.genre_labels||[], reasons=graph.reason_text||[], explanations=graph.explanation_table||[], provenance=graph.provenance_table||[];
  const normalized={selected_mood:graph.selected_mood||'',available_moods:graph.available_moods||[],metadata:graph.metadata||{},unpositioned:[],positioned:[],edges:[]};
  normalized.positioned=(graph.nodes||[]).map((row,index)=>{
    if(!Array.isArray(row)||row.length<12) throw new Error(`Invalid indexed graph node row at ${index}`);
    const genreRows=Array.isArray(row[10])?row[10]:[];
    const reasonRows=Array.isArray(row[11])?row[11]:[];
    const legacyMoodPair=typeof row[8]==='number'&&row[8]>=0&&row[8]<=1&&typeof row[9]==='number'&&row[9]>=0&&row[9]<=1&&!(typeof row[6]==='number'&&row[6]>=0&&row[6]<=1);
    const bpm=legacyMoodPair?row[6]:compactValue(row[8],row[6]);
    const moodRaw=legacyMoodPair?row[8]:row[9];
    const moodNormalized=row[9];
    const node={track_id:row[0],display_label:row[1],x:axis('x',row[2],row[3]),y:axis('y',row[4],row[5]),z:axis('z',row[6],row[7]),mood_score:moodNormalized==null?null:{label:graph.selected_mood||'',raw:moodRaw,normalized:moodNormalized,scale:'sigmoid_mean_score_0_1'},bpm,genres:genreRows.map(([i,score])=>[indexedTableValue(genres,i,'genre'),score]),reasons:reasonRows.map(i=>indexedTableValue(reasons,i,'reason'))};
    if(row[12]!=null) node.genre_threshold=row[12];
    return node;
  });
  normalized.unpositioned=(graph.unpositioned||[]).map((row,index)=>{
    if(!Array.isArray(row)||row.length<3) throw new Error(`Invalid indexed graph unpositioned row at ${index}`);
    return {track_id:row[0],display_label:row[1],reasons:(Array.isArray(row[2])?row[2]:[]).map(i=>indexedTableValue(reasons,i,'reason'))};
  });
  normalized.edges=(graph.links||[]).map((row,index)=>{
    if(!Array.isArray(row)||row.length<3) throw new Error(`Invalid indexed graph link row at ${index}`);
    const source=row[0], target=row[1];
    if(!Number.isInteger(source)||source<0||source>=normalized.positioned.length||!Number.isInteger(target)||target<0||target>=normalized.positioned.length) throw new Error(`Invalid indexed graph link endpoint at ${index}`);
    const explanationIndex=row.length>4?row[4]:(graph.link_defaults||{}).explanation;
    const provenanceIndex=row.length>5?row[5]:(graph.link_defaults||{}).provenance;
    const edge={a:normalized.positioned[source].track_id,b:normalized.positioned[target].track_id,score:row[2],explanation:indexedTableValue(explanations,explanationIndex,'explanation'),provenance:indexedTableValue(provenance,provenanceIndex,'provenance')};
    if(row[3]!=null) edge.supported_group_count=row[3];
    return edge;
  });
  return normalized;
}
