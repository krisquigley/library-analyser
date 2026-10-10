"""Node VM observer regressions, not real-browser responsiveness evidence."""
import json
import subprocess
import unittest
from tests.unit.benchmark_tools.test_explorer_browser_native_json_observation import node_executable
from tools import explorer_browser_diagnostic as diagnostic

class BrowserProbeFailures(unittest.TestCase):
    def test_unsupported_longtask_type_is_unavailable_not_empty_observed(self):
        script=r'''
const vm=require('vm'), fs=require('fs');
const context={URL,performance:{now:()=>10},requestAnimationFrame(){},
PerformanceObserver:class{static supportedEntryTypes=[];observe(){}},
document:{addEventListener(){}},window:{fetch(){}}};
vm.createContext(context);vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),context);
process.stdout.write(JSON.stringify(context.window.__diagnostic.responsiveness));
'''
        output=subprocess.run([node_executable(),'-e',script,str(diagnostic.PROBE)],capture_output=True,text=True,timeout=10)
        self.assertEqual(output.returncode,0,output.stderr)
        response=json.loads(output.stdout)
        self.assertEqual(response['long_tasks_status'],'unavailable')
        self.assertEqual(response['long_tasks'],[])
        self.assertIsNone(response['gpu_time_ms'])

    def test_parse_and_hash_failures_preserve_completed_boundaries(self):
        from tests.unit.benchmark_tools.test_explorer_browser_phase_attribution import _run_observer
        for stage in ('parse','hash'):
            with self.subTest(stage=stage):
                injection = ("context.JSON.parse=()=>{throw new Error('private parse');};" if stage=='parse' else
                             "context.crypto.subtle.digest=async()=>{throw new Error('private hash');};")
                observed=_run_observer(injection+'''
const response=await context.fetch('/api/mood-axis-graph');
try{await response.json();}catch(error){}
''')['diagnostic']
                milestones=observed['milestones_ms']
                self.assertEqual(milestones['graph_body_start'],0)
                self.assertEqual(milestones['graph_body_end'],10)
                self.assertEqual(milestones['graph_json_start'],10)
                if stage=='parse':
                    self.assertIsNone(milestones['graph_json_end'])
                    self.assertIsNone(milestones['graph_verification_start'])
                else:
                    self.assertEqual(milestones['graph_json_end'],13)
                    self.assertEqual(milestones['graph_verification_start'],13)
                self.assertIsNone(milestones['graph_verification_end'])
                self.assertIsNone(milestones['graph_model_start'])
                self.assertIsNone(observed['graph_response']['consumed_sha256'])
                self.assertNotIn('private',json.dumps(observed))

    def test_absent_or_invalid_content_length_is_null_not_zero(self):
        script=r'''
const vm=require('vm'), fs=require('fs');
(async()=>{const lengths=[null,'', 'not-a-number', '-1', 'Infinity', '42'];const results=[];
for(const length of lengths){const context={URL,location:{href:'http://owned.invalid'},performance:{now:()=>10},requestAnimationFrame(){},
PerformanceObserver:class{observe(){}},document:{addEventListener(){}},window:{fetch:async()=>({ok:true,status:200,headers:{get:name=>name==='Content-Length'?length:null}})}};
vm.createContext(context);vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),context);
await context.window.fetch('/api/mood-axis-graph');results.push(context.window.__diagnostic.graph_response.content_length);}
process.stdout.write(JSON.stringify(results));})();
'''
        output=subprocess.run([node_executable(),'-e',script,str(diagnostic.PROBE)],capture_output=True,text=True,timeout=10)
        self.assertEqual(output.returncode,0,output.stderr)
        self.assertEqual(json.loads(output.stdout),[None,None,None,None,None,42])

    def test_native_malformed_counts_keep_completed_native_interval(self):
        script=r'''
const vm=require('vm'), fs=require('fs');let tick=0;
const response={ok:true,status:200,headers:{get:()=>null},json:async()=>({nodes:null})};
const context={URL,location:{href:'http://owned.invalid'},performance:{now:()=>++tick},requestAnimationFrame(){},
PerformanceObserver:class{observe(){}},document:{addEventListener(){}},
window:{__diagnosticObserverMode:'native-json',fetch:async()=>response}};
vm.createContext(context);vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),context);
(async()=>{const result=await context.window.fetch('/api/mood-axis-graph');
try{await result.json();}catch(error){}
process.stdout.write(JSON.stringify(context.window.__diagnostic));})();
'''
        output=subprocess.run([node_executable(),'-e',script,str(diagnostic.PROBE)],capture_output=True,text=True,timeout=10)
        self.assertEqual(output.returncode,0,output.stderr)
        response=json.loads(output.stdout)
        m=response['milestones_ms']
        self.assertIsInstance(m['graph_native_json_start'],(int,float))
        self.assertGreater(m['graph_native_json_end'],m['graph_native_json_start'])
        self.assertIsNone(m['graph_body_end'])
        self.assertIsNone(m['graph_json_end'])
        self.assertIsNone(response['graph_response']['consumed_sha256'])
        self.assertNotIn('json_counts',response['graph_response'])

    def test_trusted_selection_receipt_uses_browser_clock_without_host_subtraction(self):
        script=r'''
const vm=require('vm'), fs=require('fs');let tick=10,frames=[],listeners={};
const context={URL,performance:{now:()=>tick},requestAnimationFrame:fn=>frames.push(fn),
PerformanceObserver:class{observe(){}},document:{addEventListener:(type,fn)=>listeners[type]=fn},window:{fetch(){}}};
vm.createContext(context);vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),context);
context.window.__diagnostic.contention_action='selection';
if(listeners.click)listeners.click({type:'click',isTrusted:true});
tick=20;const ready=frames;frames=[];for(const fn of ready)fn(tick);
process.stdout.write(JSON.stringify(context.window.__diagnostic));
'''
        output=subprocess.run([node_executable(),'-e',script,str(diagnostic.PROBE)],capture_output=True,text=True,timeout=10)
        self.assertEqual(output.returncode,0,output.stderr)
        result=json.loads(output.stdout)
        self.assertEqual(len(result['input_observations']),1)
        record=result['input_observations'][0]
        self.assertEqual(record['action'],'selection')
        self.assertTrue(record['is_trusted'])
        self.assertEqual(record['receipt_clock'],'browser-performance')
        self.assertEqual(record['received_ms'],10)
        self.assertEqual(record['frame_ms'],20)
        self.assertNotIn('attempt_to_receipt_ms',record)

if __name__=='__main__': unittest.main()
