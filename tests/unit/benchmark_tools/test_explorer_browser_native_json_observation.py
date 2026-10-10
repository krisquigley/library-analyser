"""Observer-light contracts executed in Node, NOT Chromium/performance evidence.

The VM supplies native-response boundaries, not an alternative application.
The opt-in observer mode must not read a second body, parse/hash for verification,
or promote a known fixture manifest into evidence of consumed byte identity.
"""
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import unittest

from tools import explorer_browser_diagnostic as tool

ROOT = Path(__file__).resolve().parents[3]


def node_executable():
    executable = shutil.which('node') or shutil.which('nodejs')
    if executable:
        return executable
    # Playwright bundles Node; using this executable launches no browser/driver.
    spec = importlib.util.find_spec('playwright')
    if spec and spec.origin:
        executable = Path(spec.origin).parent / 'driver' / 'node'
        if executable.is_file():
            return str(executable)
    raise unittest.SkipTest('Node VM unavailable; observer contracts unverified, not RED')


def native_observation():
    script = r'''
const fs = require('fs'), vm = require('vm');
const value = {nodes:[{id:'public-00000'}],links:[],unpositioned:[]};
const calls = {json:0,text:0,digest:0,encode:0};
let clock=10;
const response={ok:true,status:200,headers:{get:name=>name==='Content-Encoding'?'gzip':'42'},
  json:async function(){calls.json++;return value;},
  text:async function(){calls.text++;return JSON.stringify(value);}};
const context={URL,Uint8Array,location:{href:'http://127.0.0.1/'},
  performance:{now:()=>++clock},requestAnimationFrame:()=>{},
  PerformanceObserver:class {observe(){}},document:{addEventListener(){}},
  TextEncoder:class {encode(text){calls.encode++;return Buffer.from(text);}},
  crypto:{subtle:{digest:async()=>{calls.digest++;return new Uint8Array(32);}}},
  window:{__diagnosticObserverMode:'native-json',fetch:async()=>response}};
vm.createContext(context);
vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),context);
(async()=>{
  const response=await context.window.fetch('/api/mood-axis-graph');
  const consumed=await response.json();
  process.stdout.write(JSON.stringify({calls,same_value:consumed===value,
    observation:context.window.__diagnostic}));
})().catch(error=>{console.error(error);process.exitCode=1;});
'''
    result = subprocess.run([node_executable(), '-e', script, str(tool.PROBE)],
                            cwd=ROOT, capture_output=True, text=True, timeout=10)
    if result.returncode:
        raise AssertionError('Probe VM execution failed, not intended RED: ' + result.stderr)
    return json.loads(result.stdout)


class NativeJsonObserverContracts(unittest.TestCase):
    def test_native_json_uses_original_method_and_keeps_unobserved_identity_null(self):
        result = native_observation()
        self.assertEqual(result['calls'], {'json': 1, 'text': 0, 'digest': 0, 'encode': 0},
                         'observer-light must invoke native json, not text/parse/hash')
        self.assertTrue(result['same_value'], 'return native consumed value unchanged')

        d = result['observation']
        self.assertEqual(d.get('observer_mode'), 'native-json', 'label observer perturbation mode')
        response = d['graph_response']
        self.assertEqual(response.get('consumed_identity_status'), 'unavailable-native-json')
        self.assertIn('consumed_bytes', response)
        self.assertIn('consumed_sha256', response)
        self.assertIsNone(response['consumed_bytes'])
        self.assertIsNone(response['consumed_sha256'])
        # Native response.json combines body/decode/parse; its completion is NOT
        # an observed parse start/end or separate decoded-body completion.
        m = d['milestones_ms']
        for name in ('graph_body', 'graph_json', 'graph_json_start', 'graph_json_end'):
            self.assertIn(name, m, 'unobserved timestamps must be explicit null')
            self.assertIsNone(m[name])
        self.assertIsInstance(m.get('graph_native_json_end'), (int, float))

    def test_native_json_manifest_is_not_substituted_for_consumed_identity(self):
        counts = {'nodes': 1, 'links': 0, 'unpositioned': 0}
        manifest = {'content_encoding': 'gzip', 'encoded': {'body_bytes': 42},
                    'decoded': {'body_bytes': 100, 'sha256': 'a' * 64}, 'counts': counts}
        response = {'content_encoding': 'gzip', 'content_length': 42,
                    'consumed_bytes': None, 'consumed_sha256': None,
                    'consumed_identity_status': 'unavailable-native-json', 'json_counts': counts}
        sample = {'outcome': 'ok', 'observer_mode': 'native-json',
                  'failures': [], 'graph_response': response.copy()}
        tool.validate_graph_response(sample, manifest)
        self.assertEqual(sample['outcome'], 'ok',
                         'unavailable identity in declared native mode is not an observed mismatch')
        self.assertEqual(sample['graph_response'], response,
                         'known manifest hash/bytes must not masquerade as consumed evidence')
        self.assertEqual(sample['failures'], [])


if __name__ == '__main__':
    unittest.main()
