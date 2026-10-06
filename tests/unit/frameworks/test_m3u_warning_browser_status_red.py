import shutil
import subprocess
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
APP_JS = REPO_ROOT / 'music_explorer' / 'frameworks' / 'explorer' / 'assets' / 'app.js'


class M3UWarningBrowserStatusRedTests(unittest.TestCase):
    def test_m3u_dead_end_warning_is_rendered_as_safe_status_text(self):
        if not shutil.which('node'):
            source = APP_JS.read_text(encoding='utf-8')
            if 'X-Music-Explorer-Playlist-Warning' not in source or 'textContent' not in source:
                self.fail('M3U warning from response headers must be shown via textContent status, not HTML')
            return
        script = r"""
const assert = require('assert');
const app = require(process.argv[1]);
const clicked = [];
const revoked = [];
const elements = {};
function makeElement(tag){return {tagName:tag.toUpperCase(), children:[], attributes:{}, dataset:{}, style:{}, className:'', id:'', hidden:false, value:'', min:'', max:'', type:'', textContent:'', innerHTML:'', download:'', href:'', parentElement:null, clientWidth:600, clientHeight:400, append(...nodes){for(const node of nodes){if(node && typeof node === 'object') node.parentElement=this; this.children.push(node); if(node && node.id) elements[node.id]=node;}}, replaceChildren(...nodes){this.children=[]; this.append(...nodes);}, setAttribute(k,v){this.attributes[k]=String(v);}, remove(){this.removed=true;}, click(){clicked.push({tag:this.tagName, href:this.href, download:this.download});}, getContext(){return {clearRect(){}, fillRect(){}, beginPath(){}, moveTo(){}, lineTo(){}, stroke(){}, arc(){}, fill(){}};}};}
elements['graph-load-status'] = makeElement('section'); elements.graph3d = makeElement('div'); elements['mood-strip'] = makeElement('canvas'); elements['mood-strip-picker'] = makeElement('input'); elements['mood-strip-value'] = makeElement('span');
global.document = {body: makeElement('body'), createElement: makeElement, createTextNode: text => ({textContent:String(text)}), getElementById: id => elements[id] || null, querySelectorAll: () => []};
global.requestAnimationFrame = cb => cb();
global.URL = {createObjectURL: blob => 'blob:playlist', revokeObjectURL: url => revoked.push(url)};
global.Blob = class Blob { constructor(parts, options){this.parts=parts; this.options=options;} };
global.fetch = async path => {if(String(path).startsWith('/api/mood-axis-graph')) return {ok:true, json:async()=>({dto_version:'mood-axis-graph-compact-v1', selected_mood:'relaxing', available_moods:['relaxing'], metadata:{graph_status:{state:'ready'}}, nodes:[], links:[], unpositioned:[]})}; return {ok:true, headers:{get:name => {
  const key = String(name).toLowerCase();
  if(key === 'content-disposition') return 'attachment; filename="warning.m3u"';
  if(key === 'x-music-explorer-playlist-warning') return 'Playlist is shorter than requested because traversal reached a dead end <img src=x onerror=alert(1)>';
  return 'audio/x-mpegurl';
}}, text:async()=> '#EXTM3U\n/song.mp3\n'};};
app.setStateForTesting({current_track_id:'start-track'});
app.setGraphControlsForTesting({m3uBpmMin:'90', m3uBpmMax:'130', m3uCount:'25'});
app.loadGraph().then(async () => {
  const button = elements['download-m3u'];
  assert(button && typeof button.onclick === 'function', 'ready graph must render an explicit M3U download button');
  await button.onclick();
  const status = elements['m3u-download-status'];
  assert(status, 'M3U download controls must include a persistent status element for warnings');
  assert.strictEqual(status.attributes.role, 'status');
  assert.strictEqual(status.attributes['aria-live'], 'polite');
  assert.match(status.textContent, /shorter than requested/);
  assert.match(status.textContent, /dead end/);
  assert.strictEqual(status.innerHTML, '', 'warning status must not be written with innerHTML');
  assert.deepStrictEqual(clicked, [{tag:'A', href:'blob:playlist', download:'warning.m3u'}]);
  assert.deepStrictEqual(revoked, ['blob:playlist']);
}).catch(error => {console.error(error && error.stack || error); process.exit(1);});
"""
        subprocess.run(['node', '-e', script, str(APP_JS)], check=True, cwd=REPO_ROOT)


if __name__ == '__main__':
    unittest.main()
