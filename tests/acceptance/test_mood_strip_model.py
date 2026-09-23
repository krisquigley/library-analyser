"""Browser presentation policy exercised with Node, without network or a DOM."""
import shutil
import subprocess
import unittest
from pathlib import Path

APP = Path(__file__).resolve().parents[2] / 'music_analyzer/frameworks/explorer/assets/app.js'


@unittest.skipUnless(shutil.which('node'), 'Node required for browser model tests')
class MoodStripModelTests(unittest.TestCase):
    def test_fixed_raw_scale_filter_selection_ties_and_exact_tooltips(self):
        script = r"""
const assert = require('node:assert/strict');
const app = require(process.argv[1]);
const node = (id, raw, mood='calm', bpm=100) => ({track_id:id,display_label:id,x:{raw:0.1,normalized:0.1},y:{raw:0.2,normalized:0.2},z:{label:'BPM',raw:bpm,normalized:bpm/20,scale:'fixed-BPM/20-display-units'},mood_score:raw==null?null:{label:mood,raw,normalized:raw,scale:'sigmoid-score-[0,1]'},bpm});
const payload = {selected_mood:'calm',positioned:[node('z',0.6),node('b',0),node('a',0.6),node('top',1),node('missing',null)],unpositioned:[]};
const model = app.buildMoodGraphModel(payload);
const strip = app.buildMoodStrip(app.applyMoodGraphFilters(model,{}), 'a');
assert.deepEqual(strip.map(m=>[m.id,m.score,m.selected]),[['b',0,false],['a',0.6,true],['z',0.6,false],['top',1,false]]);
assert(strip.every(m=>m.position===m.score));
assert(strip[1].description.includes('calm 0.6'));
assert(app.nodeLabel(model.nodes[1]).includes('BPM 100'));
assert(!strip.some(m=>m.id==='missing'));
assert.equal(model.nodes.length,5);
const filtered = app.buildMoodStrip(app.applyMoodGraphFilters(model,{bpmMin:101}),'a');
assert.deepEqual(filtered,[]);
const heavy = app.buildMoodStrip(app.applyMoodGraphFilters(app.buildMoodGraphModel({...payload,selected_mood:'heavy',positioned:[node('a',0.123456789,'heavy')]}),{}),'a');
assert.equal(heavy[0].score,0.123456789);
assert(heavy[0].description.includes('heavy 0.123456789'));
assert.equal(heavy[0].position,0.123456789);
assert.equal(strip[0].position,0);
assert.equal(strip.at(-1).position,1);
"""
        subprocess.run(['node', '-e', script, str(APP)], check=True)
