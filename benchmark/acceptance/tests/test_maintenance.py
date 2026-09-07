import copy
import tempfile
from pathlib import Path
import unittest

from benchmark.acceptance.common import atomic,read,digest,sha
from benchmark.acceptance.corpus import answer,approved
from benchmark.acceptance.maintenance import initialize,apply_project,sync


class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.home=Path(self.temp.name)
        file=self.home/'input.pdf';file.write_bytes(b'Synthetic test, not a real document')
        self.source={'id':'demo','path':str(file),'format':'pdf','sha256':sha(file),'bytes':file.stat().st_size,'private':False,'provenance':{'type':'generated'}}
        self.a=answer(self.source,'count',{'type':'target','target':'pdf.page_count'},0,{'method':'independent control'})
        atomic(self.home/'corpus/manifest.json',{'sources':[self.source],'gaps':[],'cohortHash':digest([('demo',sha(file))])})
        atomic(self.home/'answers/index.json',{'answers':[self.a]})
        self.store=initialize(self.home);self.p=self.store.get('deckprobe')

    def tearDown(self):self.temp.cleanup()

    def act(self,action,**extra):
        self.p=self.store.act('deckprobe',{'revision':self.p['revision'],'actor':'Synthetic reviewer','sampleId':'demo','action':action,'note':'test',**extra})

    def test_sync_approval_edit_and_revoke(self):
        apply_project(self.home,self.p)
        self.assertEqual(read(self.home/'answers/index.json')['answers'][0],self.a)
        a=self.p['samples'][0]['answers'][0]
        self.act('review_answer',answerId=a['id'],answerDigest=a['digest'],status='approved',confirm=True)
        apply_project(self.home,self.p)
        first=read(self.home/'answers/index.json')['answers'][0];self.assertTrue(approved(self.home,first))
        a=self.p['samples'][0]['answers'][0]
        self.act('review_answer',answerId=a['id'],answerDigest=a['digest'],status='deferred',confirm=True)
        sync(self.home)
        current=read(self.home/'answers/index.json')['answers'][0]
        self.assertFalse(approved(self.home,current));self.assertNotEqual(current['answerDigest'],first['answerDigest'])
        self.assertTrue(approved(self.home,first)) # historic approval remains attached to historic content

    def test_reference_even_if_approved_and_mapped_never_executes(self):
        self.act('migrate_facts');a=self.p['samples'][0]['answers'][0]
        self.act('review_answer',answerId=a['id'],answerDigest=a['digest'],status='approved',confirm=True)
        self.act('set_answer_scope',answerId=a['id'],mode='reference');sync(self.home)
        self.assertEqual(read(self.home/'answers/index.json')['answers'],[])
        library=read(self.home/'facts/index.json')
        self.assertEqual(library['summary']['reference'],1)
        self.assertEqual(library['facts'][0]['fact']['status'],'approved')
        self.act('set_answer_scope',answerId=a['id'],mode='case');sync(self.home)
        self.assertTrue(approved(self.home,read(self.home/'answers/index.json')['answers'][0]))

    def test_manual_edit_survives_sync(self):
        a=copy.deepcopy(self.p['samples'][0]['answers'][0]);a['expected']=3
        self.act('save_answer',answerId=a['id'],answer=a)
        sync(self.home);sync(self.home)
        current=read(self.home/'answers/index.json')['answers'][0]
        self.assertEqual(current['expected'],3);self.assertFalse(approved(self.home,current))

    def test_incomplete_draft_syncs_without_disrupting_existing_answers(self):
        self.act('save_answer',answer={'question':'稍后补充规则', 'expected':0},note='')
        sync(self.home)
        answers=read(self.home/'answers/index.json')['answers']
        self.assertEqual(answers[0],self.a)
        self.assertTrue(answers[1]['maintenance']['incompleteRule'])
        self.assertEqual(answers[1]['requirement'],'PRO-R03')
        self.assertFalse(approved(self.home,answers[1]))

    def test_fact_inventory_and_execution_mapping_are_separate(self):
        self.act('migrate_facts')
        a=self.p['samples'][0]['answers'][0]
        self.act('review_answer',answerId=a['id'],answerDigest=a['digest'],status='approved',confirm=True)
        sync(self.home)
        self.assertTrue(approved(self.home,read(self.home/'answers/index.json')['answers'][0]))
        self.act('save_mapping',answerId=a['id'],mapping={'status':'unsupported'})
        sync(self.home)
        self.assertEqual(read(self.home/'answers/index.json')['answers'],[])
        facts=read(self.home/'facts/index.json')['facts']
        self.assertEqual(facts[0]['fact']['status'],'approved')
        self.act('save_mapping',answerId=a['id'],mapping={'status':'mapped','check':a['check'],'options':a['options'],'requirement':a['requirement']},confirm=True)
        sync(self.home)
        self.assertTrue(approved(self.home,read(self.home/'answers/index.json')['answers'][0]))

    def test_replacement_blocks_old_answers_and_disable_removes_execution(self):
        file=self.home/'new.pdf';file.write_bytes(b'changed')
        self.act('replace',path=str(file));sync(self.home)
        a=read(self.home/'answers/index.json')['answers'][0]
        self.assertTrue(a['maintenance']['stale'])
        self.act('sample_status',active=False);sync(self.home)
        self.assertEqual(read(self.home/'answers/index.json')['answers'],[])
        self.assertFalse(read(self.home/'corpus/manifest.json')['sources'][0]['active'])


if __name__=='__main__':unittest.main()
