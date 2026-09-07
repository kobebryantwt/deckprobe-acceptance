import copy
import shutil
import tempfile
import unittest
from pathlib import Path

from benchmark.acceptance.case_explanations import SUPPORTED, explain
from benchmark.acceptance.common import CODE, atomic, sha
from benchmark.acceptance.report_view import build_model


class CaseExplanationTests(unittest.TestCase):
    def test_performance_pair_uses_policy_sample_count_and_is_not_a_release_gate(self):
        row = {'id':'performance_pair', 'requirement':'PRO-R06', 'title':'performance',
               'status':'review', 'role':'observation',
               'actual':{'configurations':51,'blocked':0,'alerts':2}}
        explanation = explain(row, {'performance':{'warmup':5,'samples':50}}, {})
        self.assertIn('50 个有效点', ''.join(explanation['method']))
        self.assertIn('不参与发布门禁', explanation['limitation'])

    def test_matching_unknown_and_private_count_do_not_become_fact_proof(self):
        row = {'id':'optional_required_semantics', 'requirement':'PRO-R05', 'title':'pair',
               'expected':{'status':'unknown'}, 'actual':{'status':'unknown'}, 'status':'passed'}
        original = copy.deepcopy(row)
        explanation = explain(row, {}, {})
        self.assertIn('不能证明页数', explanation['limitation'])
        self.assertEqual(row, original)
        row = {'id':'private_sources_protected', 'requirement':'PRO-R02', 'actual':35}
        explanation = explain(row, {}, {})
        self.assertIn('不是产品通过的文件数', ''.join(explanation['criteria']))
        self.assertIn('无独立监控事件', str(explanation['observedFields']))

    def test_fact_gap_explains_mapping_state_instead_of_human_gt_review(self):
        row = {'id':'fact-gap-case-a-fact-1','requirement':'PRO-R03','title':'宏数量？',
               'status':'review','role':'observation',
               'actual':{'caseId':'case-a','factKey':'macros.vba_project_count',
                         'mappingStatus':'unsupported','reason':'没有同口径字段'}}
        explanation = explain(row, {}, {})
        self.assertEqual(explanation['kind'],'产品暂不支持')
        self.assertIn('不参与发布门禁',explanation['limitation'])

    def test_fact_gap_aggregate_evidence_does_not_attach_the_whole_corpus(self):
        row = {'id':'fact-gap-case-b-fact-1','requirement':'PRO-R03','title':'工作表数量？',
               'status':'review','role':'observation','expected':1,
               'actual':{'caseId':'case-b','factKey':'excel.sheet_count','mappingStatus':'unmapped'},
               'evidence':['facts.json']}
        envelope = {'qualitySummary':{}, 'acceptance':{'runId':'demo','targetVersion':'demo',
                    'createdAt':'2026-01-01', 'mode':'ci','checks':[row]}}
        sources=[{'id':'case-a','path':'a.pptx','sha256':'a'},
                 {'id':'case-b','path':'b.xlsb','sha256':'b'}]
        with tempfile.TemporaryDirectory() as name:
            folder=Path(name)
            atomic(folder/'facts.json',{'facts':[{'sampleId':'case-a'},{'sampleId':'case-b'}]})
            model=build_model(folder,envelope,{'sources':sources})
            self.assertEqual(model['rows'][0]['sourceIds'],['case-b'])

    def test_missing_or_changed_implementation_cannot_borrow_new_explanation(self):
        row = {'id':'live_security_monitor', 'requirement':'PRO-R02', 'title':'monitor',
               'status':'blocked','actual':[], 'expected':'live evidence'}
        envelope = {'qualitySummary':{}, 'acceptance':{'runId':'demo','targetVersion':'demo',
                    'createdAt':'2026-01-01', 'mode':'diagnostic','checks':[row]}}
        with tempfile.TemporaryDirectory() as name:
            folder=Path(name)
            self.assertFalse(build_model(folder,envelope,{})['context']['protocolBound'])
            for path, expected_hash in SUPPORTED.items():
                self.assertEqual(sha(CODE/path), expected_hash, 'Review protocol wording when implementation changes')
                dest=folder/'implementation'/path
                dest.parent.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(CODE/path,dest)
            atomic(folder/'implementation-manifest.json',SUPPORTED)
            bound=build_model(folder,envelope,{})
            self.assertTrue(bound['context']['protocolBound'])
            self.assertEqual(bound['rows'][0]['protocol']['kind'],'安全环境验证')
            self.assertEqual(bound['rows'][0]['status'],'blocked')
            (folder/'implementation/runner.py').write_text('changed semantics')
            changed=build_model(folder,envelope,{})
            self.assertFalse(changed['context']['protocolBound'])
            self.assertEqual(changed['rows'][0]['protocol']['kind'],'历史检查')


if __name__ == '__main__':
    unittest.main()

class ApprovalWordingTests(unittest.TestCase):
    def _row(self, approval, status):
        return {'id':'case','requirement':'PRO-R03','status':status,'approval':approval,
                'answer':{'question':'数量？','check':{'type':'target','target':'count'},'options':[]}}

    def test_approved_pass_wording_is_not_hypothetical_pending_warning(self):
        p=explain(self._row('approved','passed'),{}, {})
        self.assertIn('正式通过',p['limitation'])
        self.assertNotIn('尚未人工审核',p['limitation'])

    def test_draft_match_remains_diagnostic_only(self):
        p=explain(self._row('draft','review'),{}, {})
        self.assertIn('尚未人工审核',p['limitation'])
        self.assertIn('诊断观察',p['limitation'])


class SchemaWordingTests(unittest.TestCase):
    def test_empty_schema_issue_list_means_validation_ran_and_passed(self):
        row={'id':'schema_x','title':'schema','requirement':'PRO-R04','actual':[]}
        p=explain(row,{}, {})
        self.assertIn('已执行 JSON Schema',p['observed'])
        self.assertIn('未发现契约违规',p['observed'])
        self.assertNotIn('记录了 0 条',p['observed'])
