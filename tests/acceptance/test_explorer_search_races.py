"""PR1 RED behavior specs: query intent owns results before debounce expires.

These run the complete delivered asset in an isolated Node VM, using DOM events,
controlled timers and deferred HTTP responses rather than source-shape assertions.
The startup summary response is tolerated here only to isolate race regressions;
search-first startup is specified separately. No real catalogue is accessed.
"""
import os
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[2]
NODE = os.environ.get('EXPLORER_TEST_NODE') or shutil.which('node') or '/tmp/node-host-v24'

HARNESS = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
class Element {
  constructor(tag='div') {
    this.tagName=tag.toUpperCase(); this.children=[]; this.dataset={};
    this.attributes={}; this.hidden=false; this.disabled=false; this.value='';
    this._text=''; this.className='';
    this.classList={add:()=>{},remove:()=>{}};
  }
  set textContent(v) { this._text=String(v); this.children=[]; }
  get textContent() { return this._text+this.children.map(c=>c.textContent).join(''); }
  append(...items) { for(const item of items) { item.parentElement=this; this.children.push(item); } }
  replaceChildren(...items) { this._text=''; this.children=[]; this.append(...items); }
  setAttribute(k,v) { this.attributes[k]=String(v); }
  removeAttribute(k) { delete this.attributes[k]; }
  getAttribute(k) { return this.attributes[k]??null; }
  querySelector(selector) { return walk(this).find(e=>e.tagName===selector.toUpperCase())||null; }
  addEventListener(type,fn) { this['on'+type]=fn; }
  dispatchEvent(event) { return this['on'+event.type]?.(event); }
  click() { if(!this.disabled) return this.onclick?.({target:this}); }
}
function walk(root) { return root.children.flatMap(child=>[child,...walk(child)]); }
async function flush() { for(let i=0;i<30;i++) await Promise.resolve(); }
async function boot() {
  const roots={};
  for(const id of ['tracks','track-search','controls','undo','reset','detail']) {
    roots[id]=new Element(id==='track-search'?'input':'div'); roots[id].id=id;
  }
  const document={
    getElementById:id=>roots[id]||Object.values(roots).flatMap(walk).find(e=>e.id===id)||null,
    createElement:tag=>new Element(tag),
    querySelectorAll:selector=>selector==='#tracks tr[data-track-id]'?
      walk(roots.tracks).filter(e=>e.tagName==='TR'&&e.dataset.trackId):[],
  };
  let clock=0, timerId=0;
  const timers=new Map(), requests=[];
  const fetch=(path,options)=>{
    const url=new URL(path,'http://test.invalid');
    if(url.pathname==='/api/state') return Promise.resolve({ok:true,json:async()=>({current_track_id:null,history:[]})});
    assert.equal(url.pathname,'/api/tracks/summary','race fixture expects only state/summary, not graph or detail');
    let resolve,reject;
    const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});
    const request={url,options,settled:false,
      succeed(tracks,cursor=null) { this.settled=true; resolve({ok:true,json:async()=>({tracks,metadata:{track_count:tracks.length},next_cursor:cursor})}); },
      fail(message='page unavailable') { this.settled=true; resolve({ok:false,text:async()=>message}); },
    };
    requests.push(request); return promise;
  };
  const context={document,fetch,URLSearchParams,console,
    setTimeout(fn,delay=0) { const id=++timerId; timers.set(id,{fn,due:clock+delay}); return id; },
    clearTimeout(id) { timers.delete(id); },
    requestAnimationFrame(fn) { queueMicrotask(fn); },
  };
  vm.runInNewContext(fs.readFileSync(process.argv[1],'utf8'),context,{filename:process.argv[1]});
  await flush();
  // Drain the OLD startup fetch without making it part of a race assertion.
  for(const r of requests.filter(r=>!r.url.searchParams.get('query'))) r.succeed([]);
  await flush();
  assert.equal(typeof roots['track-search'].oninput,'function','fixture needs the delivered search handler wired');
  return {
    roots,requests,
    input(value) { const input=roots['track-search']; input.value=value; input.dispatchEvent({type:'input',target:input}); },
    async advance(ms=150) {
      clock+=ms;
      while(true) {
        const entry=[...timers].filter(([,t])=>t.due<=clock).sort((a,b)=>a[1].due-b[1].due)[0];
        if(!entry) break;
        timers.delete(entry[0]); entry[1].fn(); await flush();
      }
    },
    rows() { return document.querySelectorAll('#tracks tr[data-track-id]').map(e=>e.dataset.trackId); },
    more() { return walk(roots.tracks).find(e=>e.tagName==='BUTTON'&&/load more/i.test(e.textContent)); },
    retry() { return walk(roots.tracks).find(e=>e.tagName==='BUTTON'&&/retry/i.test(e.textContent)); },
    matching(query,cursor=null) { return requests.filter(r=>r.url.searchParams.get('query')===query&&r.url.searchParams.get('cursor')===cursor); },
  };
}
const track=id=>({handle:id,title:id,artist:'Synthetic artist'});
async function search(h,query,ids,cursor=null) {
  h.input(query); await h.advance();
  const request=h.matching(query).at(-1);
  assert(request,'nonblank search must request its bounded matching page');
  assert.equal(request.url.searchParams.get('limit'),'100');
  assert.equal(request.url.searchParams.get('order'),'title');
  request.succeed(ids.map(track),cursor); await flush();
  assert.deepEqual(h.rows(),ids,'setup response must render genuine rows');
  return request;
}
(async()=>{
  const h=await boot();
  SCENARIO
})().catch(error=>{console.error(error);process.exitCode=1;});
"""


class ExplorerSearchRaceRedTests(unittest.TestCase):
    def run_scenario(self, scenario):
        if not Path(NODE).is_file():
            self.fail('Node is required; set EXPLORER_TEST_NODE (no skipped acceptance)')
        for package in ('music_analyzer', 'music_explorer'):
            with self.subTest(package=package):
                asset = ROOT / package / 'frameworks/explorer/assets/app.js'
                result = subprocess.run([NODE, '-e', HARNESS.replace('SCENARIO', scenario), str(asset)],
                                        capture_output=True, text=True, timeout=20)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_previous_response_cannot_render_during_replacement_debounce(self):
        self.run_scenario(r"""
          h.input('alpha'); await h.advance();
          const old=h.matching('alpha')[0]; assert(old);
          h.input('beta'); // deliberately do NOT advance the new debounce
          old.succeed([track('obsolete-alpha')]); await flush();
          assert(!h.rows().includes('obsolete-alpha'), 'old response must be invalidated at input intent, before debounce');
          assert.equal(h.matching('beta').length,0,'new query is still debouncing');
        """)

    def test_clear_immediately_removes_rows_and_pagination_without_blank_fetch(self):
        self.run_scenario(r"""
          await search(h,'alpha',['alpha-1'],'alpha-page-2');
          const before=h.requests.length;
          h.input('   ');
          assert.deepEqual(h.rows(),[], 'whitespace clear must remove rows synchronously');
          assert(!h.more(),'clear must discard the old page cursor immediately');
          await h.advance();
          assert.equal(h.requests.length,before,'clear must not request an unfiltered first page');
        """)

    def test_blank_query_never_requests_unfiltered_page(self):
        for cleared in ('', '   '):
            with self.subTest(cleared=repr(cleared)):
                self.run_scenario(r"""
                  const before=h.requests.length;
                  h.input(CLEARED); await h.advance();
                  assert.equal(h.requests.length,before,'blank or whitespace input must not fetch a summary page');
                  assert.deepEqual(h.rows(),[]);
                """.replace('CLEARED', repr(cleared)))

    def test_clear_invalidates_pending_success_before_debounce(self):
        self.run_scenario(r"""
          h.input('alpha'); await h.advance(); const old=h.matching('alpha')[0]; assert(old);
          h.input(''); old.succeed([track('obsolete-alpha')],'obsolete-cursor'); await flush();
          assert.deepEqual(h.rows(),[], 'response for a cleared query must never resurrect rows');
          assert(!h.more(),'response for cleared query must never resurrect its cursor');
          const before=h.requests.length; await h.advance();
          assert.equal(h.requests.length,before,'clear must not fetch');
        """)

    def test_stale_next_page_cannot_append_during_new_query_debounce(self):
        self.run_scenario(r"""
          await search(h,'alpha',['alpha-1'],'alpha-page-2');
          assert(h.more()); h.more().click(); await flush();
          const page=h.matching('alpha','alpha-page-2')[0]; assert(page);
          h.input('beta'); // old page arrives before beta's timer fires
          page.succeed([track('obsolete-alpha-2')]); await flush();
          assert(!h.rows().includes('obsolete-alpha-2'),'stale page must not append after new input intent');
          await h.advance(); const fresh=h.matching('beta')[0]; assert(fresh);
          assert.equal(fresh.url.searchParams.get('cursor'),null,'new query must never reuse the old cursor');
          fresh.succeed([track('beta-1')]); await flush();
          assert.deepEqual(h.rows(),['beta-1']);
        """)

    def test_repeated_more_requests_one_inflight_cursor(self):
        self.run_scenario(r"""
          await search(h,'alpha',['alpha-1'],'alpha-page-2');
          const more=h.more(); assert(more); more.click(); more.click(); await flush();
          assert.equal(h.matching('alpha','alpha-page-2').length,1,'double-more must request a cursor only once while pending');
          h.matching('alpha','alpha-page-2')[0].succeed([track('alpha-2')]); await flush();
          assert.deepEqual(h.rows(),['alpha-1','alpha-2'],'append exactly once');
        """)

    def test_failed_next_page_has_visible_retry_for_same_cursor(self):
        self.run_scenario(r"""
          await search(h,'alpha',['alpha-1'],'alpha-page-2');
          h.more().click(); await flush(); const failed=h.matching('alpha','alpha-page-2')[0]; assert(failed);
          failed.fail(); await flush();
          assert.deepEqual(h.rows(),['alpha-1'],'page failure must preserve accepted rows');
          const errors=walk(h.roots.tracks).filter(e=>!e.hidden&&['alert','status'].includes(e.getAttribute('role')));
          assert(errors.some(e=>/error|fail|unavailable|unable|could not/i.test(e.textContent)),
            'page failure needs a visible scoped error state, not the ordinary result count or swallowed rejection');
          const retry=h.retry(); assert(retry&&!retry.hidden&&!retry.disabled,'page failure needs explicit retry');
          retry.click(); await flush(); const attempts=h.matching('alpha','alpha-page-2');
          assert.equal(attempts.length,2,'retry must request the same query and cursor once');
          attempts[1].succeed([track('alpha-2')]); await flush();
          assert.deepEqual(h.rows(),['alpha-1','alpha-2']);
        """)


class ExplorerSearchRaceBaselineControls(unittest.TestCase):
    run_scenario = ExplorerSearchRaceRedTests.run_scenario
    # Kept separate from RED inventory: this proves the fixture exercises existing
    # successful search/paging and the already-present post-request sequence guard.
    def test_control_matching_page_and_explicit_append(self):
        self.run_scenario(r"""
          await search(h,'alpha',['alpha-1'],'alpha-page-2');
          const before=h.requests.length; await h.advance(1000);
          assert.equal(h.requests.length,before,'paging is explicitly requested, not prefetched');
          h.more().click(); await flush(); const page=h.matching('alpha','alpha-page-2')[0]; assert(page);
          page.succeed([track('alpha-2')]); await flush();
          assert.deepEqual(h.rows(),['alpha-1','alpha-2']);
        """)

    def test_control_later_dispatched_query_wins_reverse_completion(self):
        self.run_scenario(r"""
          h.input('alpha'); await h.advance(); const old=h.matching('alpha')[0]; assert(old);
          h.input('beta'); await h.advance(); const fresh=h.matching('beta')[0]; assert(fresh);
          fresh.succeed([track('beta-1')]); await flush();
          old.succeed([track('alpha-1')]); await flush();
          assert.deepEqual(h.rows(),['beta-1']);
        """)

    def test_control_clear_ignores_stale_failure(self):
        self.run_scenario(r"""
          h.input('alpha'); await h.advance(); const old=h.matching('alpha')[0]; assert(old);
          h.input(''); old.fail('obsolete alpha failure'); await flush();
          assert.deepEqual(h.rows(),[]);
          assert(!h.roots.tracks.textContent.includes('obsolete alpha failure'),'stale failure cannot replace clear intent');
        """)


if __name__ == '__main__':
    unittest.main()
