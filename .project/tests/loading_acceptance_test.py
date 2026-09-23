
from pathlib import Path
import copy,contextlib,importlib.util,io,json,subprocess,sys,unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/".project/checks"))
def load(name,path):
 spec=importlib.util.spec_from_file_location(name,path)
 module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
candidate=load("loading_regression_under_test",ROOT/".project/checks/loading_regression.py")

# Captured from the original real TCP loading run. The UDP unit row is
# explicitly synthetic; actual TCP/UDP contracts are required by the native gate.
FIXTURE_RESULTS = [{'argv': ['engine_prepared_lifecycle_contract', 'contract'],
  'result': {'passed': True,
             'assertions': 123,
             'prepared_operations': 19,
             'frames': 20,
             'skipped': 0,
             'actual_gameenv': True}},
 {'argv': ['engine_tracker_owner_contract'],
  'result': {'passed': True, 'paired_tracker': True, 'workers': 2, 'skipped': 0}},
 {'argv': ['engine_loading_cancellation_contract', 'reset.begin', '1'],
  'result': {'passed': True, 'assertions': 17, 'actual_gameenv': True, 'cancelled': True, 'skipped': 0}},
 {'argv': ['engine_loading_cancellation_contract', 'match.begin', '1'],
  'result': {'passed': True, 'assertions': 17, 'actual_gameenv': True, 'cancelled': True, 'skipped': 0}},
 {'argv': ['engine_loading_cancellation_contract', 'animations.template', '2'],
  'result': {'passed': True, 'assertions': 17, 'actual_gameenv': True, 'cancelled': True, 'skipped': 0}},
 {'argv': ['engine_loading_cancellation_contract', 'animations.generate', '17'],
  'result': {'passed': True, 'assertions': 17, 'actual_gameenv': True, 'cancelled': True, 'skipped': 0}},
 {'argv': ['engine_loading_cancellation_contract', 'animations.prepare-generated', '5'],
  'result': {'passed': True, 'assertions': 17, 'actual_gameenv': True, 'cancelled': True, 'skipped': 0}},
 {'argv': ['engine_loading_cancellation_contract', 'animations.file', '3'],
  'result': {'passed': True, 'assertions': 19, 'actual_gameenv': True, 'cancelled': True, 'skipped': 0}},
 {'argv': ['engine_loading_cancellation_contract', 'animations.cache', '4'],
  'result': {'passed': True, 'assertions': 17, 'actual_gameenv': True, 'cancelled': True, 'skipped': 0}},
 {'argv': ['engine_loading_cancellation_contract', 'team.player', '2'],
  'result': {'passed': True, 'assertions': 17, 'actual_gameenv': True, 'cancelled': True, 'skipped': 0}},
 {'argv': ['engine_loading_cancellation_contract', 'match.players', '1'],
  'result': {'passed': True, 'assertions': 17, 'actual_gameenv': True, 'cancelled': True, 'skipped': 0}},
 {'argv': ['engine_loading_cancellation_contract', 'match.stadium', '1'],
  'result': {'passed': True, 'assertions': 17, 'actual_gameenv': True, 'cancelled': True, 'skipped': 0}},
 {'argv': ['engine_loading_cancellation_contract', 'match.finalized', '1'],
  'result': {'passed': True, 'assertions': 19, 'actual_gameenv': True, 'cancelled': True, 'skipped': 0}},
 {'argv': ['engine_loading_cancellation_contract', 'reset.controllers', '1'],
  'result': {'passed': True, 'assertions': 17, 'actual_gameenv': True, 'cancelled': True, 'skipped': 0}},
 {'argv': ['engine_loading_cancellation_contract', 'reset.cache', '1'],
  'result': {'passed': True, 'assertions': 17, 'actual_gameenv': True, 'cancelled': True, 'skipped': 0}},
 {'argv': ['engine_loading_cancellation_contract', 'reset.pages', '1'],
  'result': {'passed': True, 'assertions': 17, 'actual_gameenv': True, 'cancelled': True, 'skipped': 0}},
 {'argv': ['engine_loading_cancellation_contract', 'reset.match-data', '1'],
  'result': {'passed': True, 'assertions': 17, 'actual_gameenv': True, 'cancelled': True, 'skipped': 0}},
 {'argv': ['engine_loading_cancellation_contract', 'reset.loading-page', '1'],
  'result': {'passed': True, 'assertions': 17, 'actual_gameenv': True, 'cancelled': True, 'skipped': 0}},
 {'argv': ['engine_loading_cancellation_contract', 'loading.background.create', '1'],
  'result': {'passed': True, 'assertions': 17, 'actual_gameenv': True, 'cancelled': True, 'skipped': 0}},
 {'argv': ['engine_loading_cancellation_contract', 'loading.background.load', '1'],
  'result': {'passed': True, 'assertions': 17, 'actual_gameenv': True, 'cancelled': True, 'skipped': 0}},
 {'argv': ['engine_loading_cancellation_contract', 'loading.background.ready', '1'],
  'result': {'passed': True, 'assertions': 17, 'actual_gameenv': True, 'cancelled': True, 'skipped': 0}},
 {'argv': ['engine_loading_cancellation_contract', 'loading.caption.left', '1'],
  'result': {'passed': True, 'assertions': 17, 'actual_gameenv': True, 'cancelled': True, 'skipped': 0}},
 {'argv': ['engine_loading_cancellation_contract', 'loading.logo.left.create', '1'],
  'result': {'passed': True, 'assertions': 17, 'actual_gameenv': True, 'cancelled': True, 'skipped': 0}},
 {'argv': ['engine_loading_cancellation_contract', 'loading.logo.left.load', '1'],
  'result': {'passed': True, 'assertions': 17, 'actual_gameenv': True, 'cancelled': True, 'skipped': 0}},
 {'argv': ['engine_loading_cancellation_contract', 'loading.caption.right', '1'],
  'result': {'passed': True, 'assertions': 17, 'actual_gameenv': True, 'cancelled': True, 'skipped': 0}},
 {'argv': ['engine_loading_cancellation_contract', 'loading.logo.right.create', '1'],
  'result': {'passed': True, 'assertions': 17, 'actual_gameenv': True, 'cancelled': True, 'skipped': 0}},
 {'argv': ['engine_loading_cancellation_contract', 'loading.logo.right.load', '1'],
  'result': {'passed': True, 'assertions': 17, 'actual_gameenv': True, 'cancelled': True, 'skipped': 0}},
 {'argv': ['engine_loading_cancellation_contract', 'loading.finalize', '1'],
  'result': {'passed': True, 'assertions': 17, 'actual_gameenv': True, 'cancelled': True, 'skipped': 0}},
 {'argv': ['engine_loading_seat_contract'],
  'result': {'passed': True,
             'checks': 14,
             'ownership_checks': 12,
             'stream_terminal_checks': 2,
             'assertions': 1049,
             'skipped': 0,
             'real_tcp': True,
             'frame_owner_checked': True,
             'actual_gameenv': False}},
 {'argv': ['engine_loading_tcp_contract'],
  'result': {'passed': True,
             'checks': 11,
             'assertions': 500,
             'skipped': 0,
             'real_tcp': True,
             'frame_owner_checked': True,
             'actual_gameenv': False}},
 {'argv': ['engine_loading_client_drain_contract'],
  'result': {'passed': True,
             'checks': 5,
             'assertions': 35,
             'skipped': 0,
             'actual_gameenv': True,
             'actual_client': True,
             'transport': 'TCP',
             'maximum_cancel_seconds': 0.100606343}}]

class LoadingTransportGate(unittest.TestCase):
 def execute(self,mutate=None,module=candidate):
  rows=copy.deepcopy(FIXTURE_RESULTS)
  by_key={tuple(row["argv"]):row["result"] for row in rows}
  udp=copy.deepcopy(rows[-1]["result"]);udp["transport"]="UDP"
  by_key[("engine_loading_udp_client_drain_contract",)]=udp
  calls=[]
  def run(argv,**kwargs):
   key=(Path(argv[0]).name,*argv[1:]);calls.append(key)
   result=copy.deepcopy(by_key[key]);extra="";code=0
   if mutate:result,extra,code=mutate(key,result)
   return subprocess.CompletedProcess(argv,code,json.dumps(result,separators=(",",":"))+"\n"+extra)
  with patch.object(candidate.subprocess,"run",side_effect=run),contextlib.redirect_stdout(io.StringIO()):
   result=module.probe(Path("/fixture"),{})
  return result,calls
 def reject(self,change):
  with self.assertRaises((RuntimeError,KeyError,TypeError,ValueError)):self.execute(change)
 def mutate_field(self,field,value,target="engine_loading_client_drain_contract"):
  def change(key,row):
   if key[0]==target:row[field]=value
   return row,"",0
  return change
 def test_both_transports_preserve_all_prior_contracts(self):
  result,calls=self.execute()
  self.assertEqual(result["checks"],32);self.assertEqual(len(calls),32)
  self.assertEqual(result["actual_client_drain_cases"],10)
  self.assertEqual(result["cancellation_checkpoints"],26)
  self.assertEqual(result["socket_ownership_cases"],12)
  self.assertEqual(result["stream_terminal_cases"],2)
 def test_tcp_cannot_be_replaced_by_udp(self):self.reject(self.mutate_field("transport","UDP"))
 def test_udp_cannot_be_replaced_by_tcp(self):self.reject(self.mutate_field("transport","TCP","engine_loading_udp_client_drain_contract"))
 def test_missing_transport_is_rejected(self):
  def change(key,row):
   if key[0]=="engine_loading_client_drain_contract":row.pop("transport")
   return row,"",0
  self.reject(change)
 def test_drain_case_count_cannot_shrink(self):
  for target in candidate.TARGETS[5:]:
   with self.subTest(target=target):self.reject(self.mutate_field("checks",4,target))
 def test_drain_assertions_cannot_shrink(self):self.reject(self.mutate_field("assertions",34))
 def test_actual_client_and_engine_are_required(self):
  for field in ["actual_client","actual_gameenv"]:
   with self.subTest(field=field):self.reject(self.mutate_field(field,False))
 def test_skips_and_failed_results_are_rejected(self):
  for field,value in [("skipped",1),("passed",False)]:
   with self.subTest(field=field):self.reject(self.mutate_field(field,value))
 def test_budget_boundary_applies_to_both_transports(self):
  for target in candidate.TARGETS[5:]:
   for value in [.25,1.,-1.,float("nan"),float("inf")]:
    with self.subTest(target=target,value=value):self.reject(self.mutate_field("maximum_cancel_seconds",value,target))
 def test_ambiguous_reports_are_rejected(self):
  self.reject(lambda key,row:(row,json.dumps(row,separators=(",",":"))+"\n",0))
 def test_sanitizer_diagnostic_is_rejected(self):
  for marker in ["runtime error:","ERROR: AddressSanitizer","ERROR: LeakSanitizer"]:
   with self.subTest(marker=marker):self.reject(lambda key,row:(row,marker,0))
 def test_nonzero_exit_is_rejected(self):self.reject(lambda key,row:(row,"",1))
 def test_original_ownership_scope_remains_required(self):
  self.reject(self.mutate_field("ownership_checks",11,"engine_loading_seat_contract"))
if __name__=="__main__":unittest.main(verbosity=2)
