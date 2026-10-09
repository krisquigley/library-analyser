import shutil
import subprocess
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
APP_JS = REPO_ROOT / 'music_explorer' / 'frameworks' / 'explorer' / 'assets' / 'app.js'


class MoodAxisGraphBrowserIndexedRedTests(unittest.TestCase):
    def _run_node_assertions(self, script):
        if not shutil.which('node'):
            source = APP_JS.read_text(encoding='utf-8')
            if 'mood-axis-graph-indexed-v1' not in source or 'contract=v3' not in source:
                self.fail('browser graph adapter must support the indexed v3 DTO and request contract=v3')
            return
        result = subprocess.run(
            ['node', '-e', script, str(APP_JS)],
            check=False,
            cwd=REPO_ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if result.returncode != 0:
            self.fail(
                'Node assertion script failed with exit code '
                f'{result.returncode}\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}'
            )

    def test_indexed_v3_dto_normalizes_losslessly_to_existing_graph_model(self):
        self._run_node_assertions(r"""
const assert = require('assert');
const app = require(process.argv[1]);
const verbose = {selected_mood:'relaxing', available_moods:['relaxing','heavy'], metadata:{graph_status:{state:'ready'}, source_fingerprint:'fp-v3'}, unpositioned:[{track_id:'c',display_label:'Missing',reasons:['mood: no supported labels available']}], positioned:[
  {track_id:'a', display_label:'Alpha', x:{label:'valence',raw:0.7, normalized:0.7, scale:'native-emomusic-valence-regression'}, y:{label:'arousal',raw:0.2, normalized:0.2, scale:'native-emomusic-arousal-regression'}, z:{label:'BPM', raw:120, normalized:6, scale:'fixed-BPM/20-display-units'}, mood_score:{label:'relaxing',raw:0.9,normalized:0.9,scale:'sigmoid_mean_score_0_1'}, bpm:120, genres:[['rock',0.8],['jazz',0.2]], genre_threshold:0.35, reasons:['complete evidence']},
  {track_id:'b', display_label:'Beta', x:{label:'valence',raw:0.3, normalized:0.3, scale:'native-emomusic-valence-regression'}, y:{label:'arousal',raw:0.4, normalized:0.4, scale:'native-emomusic-arousal-regression'}, z:{label:'BPM', raw:130, normalized:6.5, scale:'fixed-BPM/20-display-units'}, mood_score:{label:'relaxing',raw:0.2,normalized:0.2,scale:'sigmoid_mean_score_0_1'}, bpm:130, genres:[['rock',0.7]], genre_threshold:0.5, reasons:[]}
], edges:[{a:'a',b:'b',score:0.77,explanation:'axis-independent relatedness',provenance:{policy:'sparse_k10',source:'persisted-positioned-edges'},supported_group_count:3}]};
const indexed = {dto_version:'mood-axis-graph-indexed-v1', selected_mood:'relaxing', available_moods:['relaxing','heavy'], metadata:{graph_status:{state:'ready'}, source_fingerprint:'fp-v3'}, axis:[
  {key:'x', label:'valence', scale:'native-emomusic-valence-regression'},
  {key:'y', label:'arousal', scale:'native-emomusic-arousal-regression'},
  {key:'z', label:'BPM', scale:'fixed-BPM/20-display-units'}
], genre_labels:['rock','jazz'], reason_text:['complete evidence','mood: no supported labels available'], explanation_table:['axis-independent relatedness'], provenance_table:[{policy:'sparse_k10',source:'persisted-positioned-edges'}], link_defaults:{explanation:0, provenance:0}, nodes:[
  ['a','Alpha',0.7,0.7,0.2,0.2,120,6,0.9,0.9,[[0,0.8],[1,0.2]],[0],0.35],
  ['b','Beta',0.3,0.3,0.4,0.4,130,6.5,0.2,0.2,[[0,0.7]],[],0.5]
], unpositioned:[['c','Missing',[1]]], links:[[0,1,0.77,3]]};
assert.strictEqual(typeof app.normalizeMoodAxisGraphDto, 'function');
assert.deepStrictEqual(app.normalizeMoodAxisGraphDto(indexed), verbose);
const indexedModel = app.buildMoodGraphModel(indexed);
const verboseModel = app.buildMoodGraphModel(verbose);
const withoutThresholdApplicability = model => ({...model, nodes:model.nodes.map(({genreThresholdApplies, ...node}) => node)});
assert.deepStrictEqual(withoutThresholdApplicability(indexedModel), withoutThresholdApplicability(verboseModel));
assert(indexedModel.nodes.every(node => node.genreThresholdApplies), 'indexed v3 nodes apply their persisted genre thresholds');
assert(verboseModel.nodes.every(node => !node.genreThresholdApplies), 'legacy/verbose nodes preserve the existing >0.1 genre filter');
assert.deepStrictEqual(app.applyMoodGraphFilters(app.buildMoodGraphModel(indexed), {genres:['jazz']}).nodes.map(n => n.id), [], 'scores below the per-node threshold must not pass v3 genre filters');
assert.deepStrictEqual(app.applyMoodGraphFilters(app.buildMoodGraphModel(indexed), {genres:['rock']}).nodes.map(n => n.id), ['a','b']);

const thresholdProbe = {dto_version:'mood-axis-graph-indexed-v1', selected_mood:'relaxing', available_moods:[], metadata:{}, axis:[
  {key:'x', label:'valence', scale:'native-emomusic-valence-regression'},
  {key:'y', label:'arousal', scale:'native-emomusic-arousal-regression'},
  {key:'z', label:'BPM', scale:'fixed-BPM/20-display-units'}
], genre_labels:['rock'], reason_text:[], explanation_table:[], provenance_table:[], link_defaults:{}, nodes:[
  ['below','Below',0,0,0,0,120,6,0.1,0.1,[[0,0.2]],[],0.35],
  ['at','At',0,0,0,0,120,6,0.1,0.1,[[0,0.35]],[],0.35],
  ['above','Above',0,0,0,0,120,6,0.1,0.1,[[0,0.36]],[],0.35],
  ['missing-fallback','Missing fallback',0,0,0,0,120,6,0.1,0.1,[[0,0.2]],[]]
], unpositioned:[], links:[]};
assert.deepStrictEqual(app.applyMoodGraphFilters(app.buildMoodGraphModel(thresholdProbe), {genres:['rock']}).nodes.map(n => n.id), ['above','missing-fallback'], 'v3 filtering is strict above per-node threshold and preserves 0.1 fallback when threshold is absent');
""")

    def test_load_graph_reports_v3_fetch_errors_with_retry_without_legacy_or_v2_fallback(self):
        self._run_node_assertions(r"""
const assert = require('assert');
const app = require(process.argv[1]);
function makeElement(tag){return {tagName:tag.toUpperCase(), children:[], attributes:{}, dataset:{}, className:'', id:'', hidden:false, value:'', selectedOptions:[], textContent:'', append(...nodes){this.children.push(...nodes); for(const node of nodes){if(node && node.id) elements[node.id]=node;}}, replaceChildren(...nodes){this.children=[]; this.append(...nodes);}, setAttribute(k,v){this.attributes[k]=String(v);}, removeAttribute(k){delete this.attributes[k];}, getContext(){return {clearRect(){}, fillRect(){}, beginPath(){}, moveTo(){}, lineTo(){}, stroke(){}, arc(){}, fill(){}};}};}
const elements = {'graph-load-status': makeElement('section'), graph3d: makeElement('div'), 'mood-strip': makeElement('div'), 'mood-strip-picker': makeElement('select'), 'mood-strip-value': makeElement('span')};
global.document = {createElement: makeElement, createTextNode: text => ({textContent:String(text)}), getElementById: id => elements[id] || null, querySelectorAll: () => []};
global.requestAnimationFrame = cb => cb();
const requested = [];
global.fetch = async path => {requested.push(String(path)); return {ok:false, status:503, text:async()=> 'indexed graph temporarily unavailable; retry'};};
app.setGraphControlsForTesting({mood:'relaxing'});
app.loadGraph().then(() => {throw new Error('loadGraph should reject when the explicit v3 request fails');}).catch(error => {
  assert.match(String(error && error.message || error), /temporarily unavailable|503|retry/i);
  assert.strictEqual(requested.length, 1, 'the browser must not issue a legacy/v2 fallback request after a v3 error');
  assert.match(requested[0], /^\/api\/mood-axis-graph\?/);
  assert(requested[0].includes('contract=v3'), 'browser must explicitly request indexed v3 graphs');
  assert(!requested[0].includes('contract=v2'), 'browser must not request compact v2 once v3 is required');
  const retry = elements['retry-graph'];
  assert(retry && /Retry graph/.test(retry.textContent), 'error state must render an explicit retry control');
  assert.match(elements['graph-load-status'].children.map(child => child.textContent || '').join(' '), /Graph failed/);
}).catch(error => {console.error(error && error.stack || error); process.exit(1);});
""")

    def test_load_graph_renders_indexed_v3_response_without_fallback(self):
        self._run_node_assertions(r"""
const assert = require('assert');
const app = require(process.argv[1]);
function makeElement(tag){return {tagName:tag.toUpperCase(), children:[], attributes:{}, dataset:{}, style:{}, className:'', id:'', hidden:false, value:'', selectedOptions:[], textContent:'', clientWidth:600, clientHeight:400, append(...nodes){this.children.push(...nodes); for(const node of nodes){if(node && node.id) elements[node.id]=node;}}, replaceChildren(...nodes){this.children=[]; this.append(...nodes);}, setAttribute(k,v){this.attributes[k]=String(v);}, removeAttribute(k){delete this.attributes[k];}, addEventListener(){}, getBoundingClientRect(){return {left:0,top:0,width:600,height:400};}, getContext(){return {canvas:this, clearRect(){}, fillRect(){}, beginPath(){}, moveTo(){}, lineTo(){}, stroke(){}, arc(){}, fill(){}, closePath(){}, fillText(){}, save(){}, restore(){}, translate(){}, scale(){}, measureText(){return {width:10};}};}};}
const elements = {'graph-load-status': makeElement('section'), graph3d: makeElement('canvas'), 'mood-strip': makeElement('canvas'), 'mood-strip-picker': makeElement('select'), 'mood-strip-value': makeElement('span')};
global.document = {createElement: makeElement, createTextNode: text => ({textContent:String(text)}), getElementById: id => elements[id] || null, querySelectorAll: () => []};
global.requestAnimationFrame = cb => cb();
const requested = [];
const indexed = {dto_version:'mood-axis-graph-indexed-v1', selected_mood:'relaxing', available_moods:['relaxing'], metadata:{graph_status:{state:'ready'}}, axis:[
  {key:'x', label:'valence', scale:'native-emomusic-valence-regression'},
  {key:'y', label:'arousal', scale:'native-emomusic-arousal-regression'},
  {key:'z', label:'BPM', scale:'fixed-BPM/20-display-units'}
], genre_labels:['rock'], reason_text:['complete evidence'], explanation_table:['axis-independent relatedness'], provenance_table:[{policy:'sparse_k10'}], link_defaults:{explanation:0, provenance:0}, nodes:[
  ['a','Alpha',0.7,0.7,0.2,0.2,120,6,0.9,0.9,[[0,0.8]],[0],0.5]
], unpositioned:[], links:[]};
global.fetch = async path => {requested.push(String(path)); return {ok:true, json:async()=> indexed};};
app.setGraphControlsForTesting({mood:'relaxing', bpmMin:119, bpmMax:121, genres:['rock']});
app.loadGraph().then(() => {
  assert.deepStrictEqual(requested, ['/api/mood-axis-graph?mood=relaxing&contract=v3']);
  const visible = app.getVisibleGraphForTesting();
  assert.deepStrictEqual(visible.nodes.map(node => [node.id, node.name, node.axis.z.raw, node.genres, node.genreThreshold, node.reasons]), [['a','Alpha',120,[['rock',0.8]],0.5,['complete evidence']]]);
  assert(elements['download-m3u'], 'ready indexed graph response must render the existing M3U controls');
  assert.match(elements['graph-load-status'].children.map(child => child.textContent || '').join(' '), /Graph ready: 1 positioned tracks/);
}).catch(error => {console.error(error && error.stack || error); process.exit(1);});
""")


if __name__ == '__main__':
    unittest.main()
