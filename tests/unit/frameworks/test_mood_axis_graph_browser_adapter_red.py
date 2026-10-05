import shutil
import subprocess
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
APP_JS = REPO_ROOT / 'music_explorer' / 'frameworks' / 'explorer' / 'assets' / 'app.js'


class MoodAxisGraphBrowserAdapterRedTests(unittest.TestCase):
    def test_compact_dto_normalizes_to_same_graph_model_as_verbose_payload(self):
        if not shutil.which('node'):
            source = APP_JS.read_text(encoding='utf-8')
            exports = source[source.index('module.exports'):]
            if 'function normalizeMoodAxisGraphDto' not in source or 'normalizeMoodAxisGraphDto' not in exports:
                self.fail('app.js must define and export normalizeMoodAxisGraphDto for compact DTO normalization')
            return
        script = r"""
const assert = require('assert');
const app = require(process.argv[1]);
const verbose = {selected_mood:'relaxing', available_moods:['relaxing','heavy'], metadata:{graph_status:{state:'ready'}}, unpositioned:[{track_id:'c',display_label:'Missing',reasons:['mood: no supported labels available']}], positioned:[
  {track_id:'a', display_label:'Alpha', x:{label:'valence',raw:0.7, normalized:0.7, scale:'native'}, y:{label:'arousal',raw:0.2, normalized:0.2, scale:'native'}, z:{label:'BPM', raw:120, normalized:6, scale:'fixed-BPM/20-display-units'}, mood_score:{label:'relaxing',raw:0.9,normalized:0.9}, bpm:120, genres:[['rock',0.8]], genre_threshold:0.5, reasons:['complete evidence']},
  {track_id:'b', display_label:'Beta', x:{label:'valence',raw:0.3, normalized:0.3, scale:'native'}, y:{label:'arousal',raw:0.4, normalized:0.4, scale:'native'}, z:{label:'BPM', raw:130, normalized:6.5, scale:'fixed-BPM/20-display-units'}, mood_score:{label:'relaxing',raw:0.2,normalized:0.2}, bpm:130, genres:[['jazz',0.7]], genre_threshold:0.5, reasons:[]}
], edges:[{a:'a',b:'b',score:0.77,explanation:'axis-independent relatedness',provenance:{policy:'sparse_k10'},supported_group_count:3}]};
const compact = {dto_version:'mood-axis-graph-compact-v1', selected_mood:'relaxing', available_moods:['relaxing','heavy'], metadata:{graph_status:{state:'ready'}}, unpositioned:[{id:'c',label:'Missing',reasons:['mood: no supported labels available']}], nodes:[
  {id:'a', label:'Alpha', axis:{x:{label:'valence',raw:0.7, normalized:0.7, scale:'native'}, y:{label:'arousal',raw:0.2, normalized:0.2, scale:'native'}, z:{label:'BPM', raw:120, normalized:6, scale:'fixed-BPM/20-display-units'}}, mood_score:{label:'relaxing',raw:0.9,normalized:0.9}, bpm:120, genres:[['rock',0.8]], genre_threshold:0.5, reasons:['complete evidence']},
  {id:'b', label:'Beta', axis:{x:{label:'valence',raw:0.3, normalized:0.3, scale:'native'}, y:{label:'arousal',raw:0.4, normalized:0.4, scale:'native'}, z:{label:'BPM', raw:130, normalized:6.5, scale:'fixed-BPM/20-display-units'}}, mood_score:{label:'relaxing',raw:0.2,normalized:0.2}, bpm:130, genres:[['jazz',0.7]], genre_threshold:0.5, reasons:[]}
], links:[{source:'a',target:'b',score:0.77,explanation:'axis-independent relatedness',provenance:{policy:'sparse_k10'},supported_group_count:3}]};
assert.strictEqual(typeof app.normalizeMoodAxisGraphDto, 'function', 'compact DTO normalizer must be exported for tests and loadGraph');
const normalized = app.normalizeMoodAxisGraphDto(compact);
assert.deepStrictEqual(normalized, verbose);
const fromVerbose = app.buildMoodGraphModel(verbose);
const fromCompact = app.buildMoodGraphModel(compact);
assert.deepStrictEqual(fromCompact.nodes.map(n => [n.id,n.name,n.axis.x.raw,n.axis.x.normalized,n.axis.z.raw,n.axis.z.normalized,n.bpm,n.genres,n.reasons]), fromVerbose.nodes.map(n => [n.id,n.name,n.axis.x.raw,n.axis.x.normalized,n.axis.z.raw,n.axis.z.normalized,n.bpm,n.genres,n.reasons]));
assert.deepStrictEqual(fromCompact.links, fromVerbose.links);
assert.deepStrictEqual(fromCompact.unpositioned, fromVerbose.unpositioned);
assert.strictEqual(app.nodeLabel(fromCompact.nodes[0]), app.nodeLabel(fromVerbose.nodes[0]));
assert.deepStrictEqual(app.applyMoodGraphFilters(fromCompact, {bpmMin:119,bpmMax:121,genres:['rock']}).nodes.map(n=>n.id), ['a']);
"""
        subprocess.run(['node', '-e', script, str(APP_JS)], check=True, cwd=REPO_ROOT)

    def test_load_graph_explicitly_requests_compact_contract_v2(self):
        if not shutil.which('node'):
            source = APP_JS.read_text(encoding='utf-8')
            load_graph = source[source.index('async function loadGraph'):source.index('function graphStatusMessage')]
            if 'contract=v2' not in load_graph or 'graphQueryFromControls' not in load_graph:
                self.fail('loadGraph must request /api/mood-axis-graph with contract=v2 while preserving graphQueryFromControls mood negotiation')
            return
        script = r"""
const assert = require('assert');
const app = require(process.argv[1]);
function makeElement(tag){return {tagName:tag.toUpperCase(), children:[], attributes:{}, dataset:{}, className:'', id:'', hidden:false, value:'', selectedOptions:[], textContent:'', append(...nodes){this.children.push(...nodes);}, replaceChildren(...nodes){this.children=[...nodes];}, setAttribute(k,v){this.attributes[k]=String(v);}, removeAttribute(k){delete this.attributes[k];}, getContext(){return {clearRect(){}, fillRect(){}, beginPath(){}, moveTo(){}, lineTo(){}, stroke(){}, arc(){}, fill(){}};}};}
const elements = {'graph-load-status': makeElement('section'), graph3d: makeElement('div'), 'mood-strip': makeElement('div'), 'mood-strip-picker': makeElement('select'), 'mood-strip-value': makeElement('span')};
global.document = {createElement: makeElement, createTextNode: text => ({textContent:String(text)}), getElementById: id => elements[id] || null, querySelectorAll: () => []};
global.requestAnimationFrame = cb => cb();
let requested = [];
global.fetch = async path => {requested.push(String(path)); return {ok:true, json:async()=>({dto_version:'mood-axis-graph-compact-v1', selected_mood:'relaxing', available_moods:['relaxing'], metadata:{graph_status:{state:'ready'}}, nodes:[], links:[], unpositioned:[]})};};
app.setGraphControlsForTesting({mood:'relaxing', bpmMin:90, bpmMax:150, genres:['rock']});
app.loadGraph().then(() => {
  assert.strictEqual(requested.length, 1);
  assert.match(requested[0], /^\/api\/mood-axis-graph\?/);
  assert(requested[0].includes('contract=v2'), 'browser must opt into compact graph contract');
  assert(requested[0].includes('mood=relaxing'), 'mood negotiation must be preserved');
}).catch(error => {console.error(error && error.stack || error); process.exit(1);});
"""
        subprocess.run(['node', '-e', script, str(APP_JS)], check=True, cwd=REPO_ROOT)


if __name__ == '__main__':
    unittest.main()
