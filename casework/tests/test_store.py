import copy
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import urllib.request
import urllib.error

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from casework.store import Store, Conflict, sha
from casework.server import make_server
from casework.evidence import import_records


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.file=self.root/'a.pdf';self.file.write_bytes(b'public synthetic fixture')
        self.store=Store(self.root/'state')
        self.p=self.store.import_bundle({'schemaVersion':1,'project':{'id':'demo','name':'Demo','samples':[
            {'id':'sample','title':'Example','path':str(self.file),'format':'pdf','sha256':sha(self.file),'bytes':self.file.stat().st_size,
             'answers':[{'id':'a','question':'How many?','expected':0,'evidence':{'method':'independent control'},'check':{'type':'target','target':'count'},'options':[],'requirement':'PRO-R03'}]}]}})

    def tearDown(self):self.temp.cleanup()

    def act(self,action,**kwargs):
        self.p=self.store.act('demo',{'revision':self.p['revision'],'actor':'Test reviewer','action':action,'sampleId':'sample','note':'Synthetic test',**kwargs})
        return self.p

    def approve(self):
        a=self.p['samples'][0]['answers'][0]
        return self.act('review_answer',answerId='a',answerDigest=a['digest'],status='approved',confirm=True)

    def test_scenario_review_is_atomic_and_preserves_existing_approval(self):
        self.act('migrate_facts');first=self.p['samples'][0]['answers'][0]
        extra={'question':'Second fact','kind':'fact','factKey':'second','definition':'Synthetic second fact','valueState':'known','expected':2,'evidence':{'method':'independent control'}}
        self.act('save_answer',answer=extra);answers=self.p['samples'][0]['answers']
        self.act('review_scenario',answers=[{'id':a['id'],'digest':a['digest']} for a in answers],status='approved',confirm=True)
        self.assertTrue(all(a['status']=='approved' for a in self.p['samples'][0]['answers']))
        revisions=[a['revision'] for a in self.p['samples'][0]['answers']]
        self.act('review_scenario',answers=[{'id':a['id'],'digest':a['digest']} for a in self.p['samples'][0]['answers']],status='approved',confirm=True)
        self.assertEqual([a['revision'] for a in self.p['samples'][0]['answers']],revisions)
        bad={'question':'Unknown','kind':'fact','factKey':'unknown','definition':'Unknown synthetic','valueState':'unknown','expected':None,'evidence':{'method':'pending'}}
        self.act('save_answer',answer=bad);before=copy.deepcopy(self.p)
        with self.assertRaises(ValueError):self.act('review_scenario',answers=[{'id':a['id'],'digest':a['digest']} for a in self.p['samples'][0]['answers']],status='approved',confirm=True)
        self.p=self.store.get('demo');self.assertEqual(self.p,before)

    def test_scope_preserves_approval_and_new_extraction_stays_reference(self):
        self.approve();before=copy.deepcopy(self.p['samples'][0]['answers'])
        self.act('set_answer_scope',answerId='a',mode='reference')
        self.assertEqual(self.p['samples'][0]['answers'],before)
        self.assertEqual(self.p['answerScopes']['a']['mode'],'reference')
        self.act('set_answer_scope',answerId='a',mode='case')
        self.assertEqual(self.p['samples'][0]['answers'],before)
        self.act('import_fact_drafts',drafts=[{'sampleId':'sample','sourceSha256':self.p['samples'][0]['sha256'],
            'fact':{'question':'Reference only?','factKey':'images.count','definition':'Synthetic','expected':0,'evidence':{}}}])
        added=self.p['samples'][0]['answers'][-1]
        self.assertEqual(self.p['answerScopes'][added['id']]['mode'],'reference')
        with self.assertRaises(ValueError):self.act('set_answer_scope',answerId='a',mode='invalid')

    def test_approval_edit_and_history_survive_restart(self):
        self.approve();old=self.p['samples'][0]['answers'][0]
        a=copy.deepcopy(old);a['expected']=False
        self.act('save_answer',answerId='a',answer=a)
        current=self.p['samples'][0]['answers'][0]
        self.assertEqual(current['status'],'pending');self.assertNotEqual(current['digest'],old['digest'])
        self.assertEqual(Store(self.root/'state').get('demo'),self.p)
        self.assertEqual(self.store.history('demo',2)['samples'][0]['answers'][0]['status'],'approved')

    def test_relink_preserves_approval_and_logical_name(self):
        self.approve();old=copy.deepcopy(self.p['samples'][0]['answers'][0])
        moved=self.root/'renamed.pdf';moved.write_bytes(self.file.read_bytes())
        self.act('relink',path=str(moved))
        self.assertEqual(self.p['samples'][0]['answers'][0],old)
        self.assertEqual(self.p['samples'][0]['inputName'],'a.pdf')
        self.assertEqual(self.file.read_bytes(),b'public synthetic fixture')

    def test_wrong_relink_rolls_back(self):
        wrong=self.root/'wrong.pdf';wrong.write_bytes(b'different')
        before=self.store.get('demo')
        with self.assertRaises(ValueError):self.act('relink',path=str(wrong))
        self.assertEqual(self.store.get('demo'),before)

    def test_same_bytes_new_suffix_invalidates_and_defaults_private(self):
        self.approve();renamed=self.root/'a.docx';renamed.write_bytes(self.file.read_bytes())
        self.act('replace',path=str(renamed))
        self.assertEqual(self.p['samples'][0]['answers'][0]['status'],'stale')
        self.assertTrue(self.p['samples'][0]['private'])
        with self.assertRaises(ValueError):self.approve()

    def test_stale_browser_cannot_overwrite(self):
        revision=self.p['revision'];self.approve()
        with self.assertRaises(Conflict):self.store.act('demo',{'revision':revision,'actor':'Other','action':'sample_status','sampleId':'sample','active':False,'note':'stale'})

    def test_approval_requires_confirmation_and_actual_file(self):
        a=self.p['samples'][0]['answers'][0]
        with self.assertRaises(ValueError):self.act('review_answer',answerId='a',answerDigest=a['digest'],status='approved',confirm=False)
        Path(self.p['samples'][0]['path']).unlink()
        with self.assertRaises(ValueError):self.approve()

    def test_portable_import_never_imports_approval(self):
        self.approve();bundle=self.store.export('demo');bundle['project']['id']='copied'
        p=self.store.import_bundle(bundle)
        self.assertEqual(p['samples'][0]['answers'][0]['status'],'pending')

    def test_dataset_refresh_preserves_same_content_and_drops_removed_sample(self):
        self.approve();second=self.root/'b.pdf';second.write_bytes(b'new managed sample')
        bundle={'schemaVersion':1,'project':{'id':'demo','name':'Refreshed','factSchema':2,'samples':[
            {'id':'sample','title':'Moved','path':str(self.file),'inputName':'a.pdf','format':'pdf','sha256':sha(self.file),'bytes':self.file.stat().st_size},
            {'id':'second','title':'Second','path':str(second),'format':'pdf','sha256':sha(second),'bytes':second.stat().st_size}]}}
        p=self.store.refresh_bundle(bundle)
        self.assertEqual(p['_refresh'],{'preserved':1,'added':1,'removed':0,'changedBindings':0})
        self.assertEqual(p['samples'][0]['answers'][0]['status'],'approved')
        self.assertEqual(p['samples'][1]['answers'],[])
        reduced=copy.deepcopy(bundle);reduced['project']['samples']=reduced['project']['samples'][1:]
        p=self.store.refresh_bundle(reduced)
        self.assertEqual(p['_refresh']['removed'],1)
        self.assertEqual([s['id'] for s in p['samples']],['second'])

    def test_dataset_refresh_name_change_invalidates_binding(self):
        self.approve();bundle={'schemaVersion':1,'project':{'id':'demo','name':'Refreshed','samples':[
            {'id':'sample','title':'Renamed','path':str(self.file),'inputName':'renamed.pdf','format':'pdf','sha256':sha(self.file),'bytes':self.file.stat().st_size}]}}
        p=self.store.refresh_bundle(bundle);a=p['samples'][0]['answers'][0]
        self.assertEqual(a['status'],'stale');self.assertNotIn('review',a)
        self.assertEqual(a['binding']['inputName'],'renamed.pdf')

    def test_disable_retains_answers_and_history(self):
        self.act('sample_status',active=False)
        self.assertFalse(self.p['samples'][0]['active']);self.assertEqual(len(self.p['samples'][0]['answers']),1)
        with self.assertRaises(ValueError):self.approve()

    def test_purpose_preserves_gt_and_binds_file_version(self):
        self.approve();answers=copy.deepcopy(self.p['samples'][0]['answers'])
        self.act('save_purpose',purpose={'summary':'结构数量检查','checks':[{'label':'数量','type':'target','target':'count'}]})
        self.assertEqual(self.p['samples'][0]['answers'],answers)
        self.assertEqual(self.store.history('demo')[0]['action'],'save_purpose')
        purpose=self.p['samples'][0]['purpose']
        file=self.root/'new.pdf';file.write_bytes(b'changed')
        self.act('replace',path=str(file))
        self.assertNotEqual(purpose['binding']['sha256'],self.p['samples'][0]['sha256'])

    def test_fact_mapping_changes_preserve_fact_approval(self):
        self.approve();old=copy.deepcopy(self.p['samples'][0]['answers'][0])
        self.act('migrate_facts')
        a=self.p['samples'][0]['answers'][0]
        self.assertEqual(a['digest'],old['digest']);self.assertEqual(a['review'],old['review'])
        self.act('save_mapping',answerId='a',mapping={'status':'unsupported'},confirm=False)
        self.assertEqual(self.p['samples'][0]['answers'][0],a)
        self.act('save_mapping',answerId='a',mapping={'status':'mapped','check':{'type':'target','target':'new.count'}},confirm=True)
        self.assertEqual(self.p['samples'][0]['answers'][0],a)

    def test_case_scope_and_mapping_reconciliation_is_atomic(self):
        self.act('migrate_facts');a=copy.deepcopy(self.p['samples'][0]['answers'][0])
        self.act('set_case_scopes',scopes=[{'answerId':'a','mode':'case','reason':'sample purpose'}],
            purposeUpdates={},mappingUpdates={'a':{'status':'unsupported','note':'no equivalent target'}},confirmMappings=True)
        self.assertEqual(self.p['answerScopes']['a']['mode'],'case')
        self.assertEqual(self.p['mappings']['a']['status'],'unsupported')
        self.assertEqual(self.p['samples'][0]['answers'][0],a)

    def test_unknown_fact_not_zero_and_approval_requires_answer(self):
        self.act('save_answer',answer={'kind':'fact','question':'有几张图？','factKey':'images.count','definition':'图片对象计数','valueState':'unknown'})
        a=self.p['samples'][0]['answers'][-1]
        self.assertIsNone(a['expected']);self.assertNotIn('check',a)
        with self.assertRaises(ValueError):self.act('review_answer',answerId=a['id'],answerDigest=a['digest'],status='approved',confirm=True)
        fields={**a,'valueState':'known','expected':0,'evidence':{'method':'independent manual count'}}
        self.act('save_answer',answerId=a['id'],answer=fields)
        a=self.p['samples'][0]['answers'][-1]
        self.act('review_answer',answerId=a['id'],answerDigest=a['digest'],status='approved',confirm=True)
        self.assertEqual(self.p['samples'][0]['answers'][-1]['status'],'approved')

    def test_batch_drafts_keep_existing_answers_and_report_conflicts(self):
        self.act('migrate_facts');old=copy.deepcopy(self.p['samples'][0]['answers'][0])
        self.act('import_fact_drafts',drafts=[{'sampleId':'sample','sourceSha256':self.p['samples'][0]['sha256'],
            'fact':{'factKey':'count','definition':'Same count','question':'How many?','expected':9,'evidence':{'method':'independent'}}}])
        self.assertEqual(self.p['samples'][0]['answers'][0],old)
        self.assertEqual(len(self.p['samples'][0]['factFindings']),1)

    def test_optional_reason_and_minimal_draft(self):
        self.act('save_answer',answer={'question':'最少字段的草案', 'expected':False},note='')
        a=self.p['samples'][0]['answers'][-1]
        self.assertIs(a['expected'],False)
        self.assertEqual(a['check'],{});self.assertEqual(a['evidence'],{})
        self.assertEqual(self.store.history('demo')[0]['note'],'')
        with self.assertRaises(ValueError):
            self.act('review_answer',answerId=a['id'],answerDigest=a['digest'],status='approved',confirm=True,note='')
        original=self.p['samples'][0]['answers'][0]
        self.act('review_answer',answerId=original['id'],answerDigest=original['digest'],status='approved',confirm=True,note='')
        self.assertEqual(self.p['samples'][0]['answers'][0]['status'],'approved')
        self.act('sample_status',active=False,note='')
        replacement=self.root/'new.pdf';replacement.write_bytes(b'new synthetic content')
        self.act('replace',path=str(replacement),note='')
        self.assertEqual(self.p['samples'][0]['version'],2)

    def test_required_question_and_expected_still_checked(self):
        for fields in [{'question':'','expected':3},{'question':'Question'}]:
            with self.assertRaises(ValueError):self.act('save_answer',answer=fields,note='')

    def test_normalized_evidence_imports_pending_fact_and_mapping(self):
        record={'artifact_schema_version':2,'record_id':'third-party-1','record_kind':'cross_validation',
            'sample':{'case_id':'sample','sha256':self.p['samples'][0]['sha256']},
            'producer':{'name':'independent-reader','version':'1','independence':'independent_implementation'},
            'fields':[{'fact_id':'pdf.page-tree.count','definition':'Reachable page leaves','state':'observed','value':3,
                'evidence':[{'kind':'tool_output','locator':'page_count'}],
                'target_mapping':{'status':'mapped','target':'pdf.page_count','check':'value','request_options':['-t','pdf.page_count'],'requirement':'PRO-R03','rationale':'same definition'}}]}
        path=self.root/'evidence.json';path.write_text(json.dumps(record))
        result=import_records(self.store,'demo',path)
        self.assertEqual(result['facts'],1)
        project=self.store.get('demo');fact=project['samples'][0]['answers'][-1]
        self.assertEqual(fact['status'],'pending');self.assertEqual(fact['expected'],3)
        self.assertEqual(project['mappings'][fact['id']]['check']['target'],'pdf.page_count')

    def test_http_host_origin_and_write_token(self):
        server=make_server(self.store,0);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        base=f'http://127.0.0.1:{server.server_port}'
        try:
            bootstrap=json.load(urllib.request.urlopen(base+'/api/projects'))
            for headers in [{'Host':'evil.example'},{'Origin':'https://evil.example'}]:
                with self.assertRaises(urllib.error.HTTPError) as error:urllib.request.urlopen(urllib.request.Request(base+'/api/projects',headers=headers))
                self.assertEqual(error.exception.code,403)
            body={'project':'demo','revision':self.p['revision'],'actor':'Browser test','action':'sample_status','sampleId':'sample','active':False,'note':'synthetic'}
            request=urllib.request.Request(base+'/api/action',data=json.dumps(body).encode(),headers={'Content-Type':'application/json'})
            with self.assertRaises(urllib.error.HTTPError) as error:urllib.request.urlopen(request)
            self.assertEqual(error.exception.code,403)
            request.add_header('X-Casework-Token',bootstrap['token'])
            result=json.load(urllib.request.urlopen(request));self.assertFalse(result['samples'][0]['active'])
            self.assertEqual(self.store.get('demo')['revision'],2)
        finally:server.shutdown();server.server_close();thread.join()


if __name__=='__main__':unittest.main()
