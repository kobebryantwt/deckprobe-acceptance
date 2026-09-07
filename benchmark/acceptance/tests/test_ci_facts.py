import tempfile
import unittest
from pathlib import Path
from benchmark.acceptance.common import atomic,read,digest,seal
from benchmark.acceptance.ci_snapshot import export_snapshot,validate_snapshot
from benchmark.acceptance.github_ci import aggregate
from benchmark.acceptance.contracts import decision
from benchmark.acceptance.corpus import add_source

class FactSnapshotTests(unittest.TestCase):
 def test_performance_review_and_blocked_are_observations_not_release_gates(self):
  gate={'id':'functional','status':'passed','role':'gate'}
  for status in ('review','blocked'):
   performance={'id':'performance_pair','status':status,'role':'observation'}
   self.assertEqual(decision([gate,performance]),'PASS')

 def test_unmapped_public_fact_survives_export_and_tamper_detected(self):
  with tempfile.TemporaryDirectory() as d:
   home=Path(d);s=add_source(home,b'public','pdf','a',{})
   s['private']=False
   atomic(home/'corpus/manifest.json',{'sources':[s],'gaps':[]})
   atomic(home/'facts/index.json',{'facts':[{'sampleId':'a','fact':{'id':'f','binding':{'sha256':s['sha256']},'expected':9,'status':'pending'},'mapping':{'status':'unsupported'},'scope':{'mode':'case'}}]})
   out=home/'out';export_snapshot(home,out,allow_draft=True)
   data=read(out/'facts.json');self.assertEqual(data['facts'][0]['fact']['expected'],9)
   self.assertEqual(data['facts'][0]['fact']['status'],'pending')
   self.assertEqual(validate_snapshot(out,require_ready=False),[])
   data['facts'][0]['fact']['expected']=10;atomic(out/'facts.json',data)
   self.assertTrue(any('fact record digest mismatch' in x for x in validate_snapshot(out,require_ready=False)))
 def test_wrong_release_is_rejected(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);atomic(p/'lock.json',{'runId':'r','inputDigest':'i','candidate':{'tag':'v1'}})
   atomic(p/'jobs/a/job-result.json',{'schemaVersion':1,'runId':'r','inputDigest':'i','release':'v2','job':'main-functional','checks':[]});seal(p/'jobs/a')
   with self.assertRaisesRegex(ValueError,'release binding mismatch'):aggregate(p/'lock.json',p/'jobs',p/'out')
