import shutil
import subprocess
import unittest
from pathlib import Path
from tests.support.explorer_app_bundle import explorer_app_script


REPO_ROOT = Path(__file__).resolve().parents[3]
APP_JS = explorer_app_script(REPO_ROOT / 'music_explorer' / 'frameworks' / 'explorer' / 'assets' / 'app.js')


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
