import copy
import io
import json
import os
from pathlib import Path
import sys
import tarfile
import tempfile
import time
import unittest
from unittest.mock import patch
import zipfile

from benchmark.acceptance.common import atomic, code_hash, digest, locked, process, read, seal, sha, verify_seal
from benchmark.acceptance.contracts import compare_assertions, decision, evaluate_answer, normalize, report_issues
from benchmark.acceptance.corpus import add_source, answer, approved, pdf_bytes, ooxml, independent_facts, record_decisions
from benchmark.acceptance.releases import safe_extract, verify_sri
from benchmark.acceptance.security import validate_session, CONTROL_NAMES
from benchmark.acceptance.reporting import publish, rebuild, compare
from benchmark.acceptance.cli import check
from benchmark.acceptance.report_view import comparison_kind, target_observation, capture_context
from benchmark.acceptance.ci_snapshot import export_snapshot, materialize_snapshot, validate_snapshot
from benchmark.acceptance.github_ci import (aggregate as aggregate_ci, freeze as freeze_ci,
                                            publish_history, sanitize_publication, _canonical_arch,
                                            _platform_smoke_sample, _history_page)
from benchmark.acceptance.reporting import _comparison_page
from benchmark.acceptance import security

SCENARIOS=['identity','content_mismatch','missing_vs_zero','positive_and_negative_security','documented_limit','budget_boundary']
def approved_claims(answer_id):
    return {'reviewStatus':'approved','rows':[{'id':'pdf->pdf/pdf.page_count/deep','extension':'pdf','profile':'pdf',
        'target':'pdf.page_count','level':'deep','reviewStatus':'approved'}],
        'scenarioCoverage':[{'id':x,'reviewStatus':'approved','answerIds':[answer_id]} for x in SCENARIOS]}


class AcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()

    def test_source_cache_tampering(self):
        s=add_source(self.root,b'abc','pdf','a',{})
        Path(s['path']).chmod(0o644);Path(s['path']).write_bytes(b'bad')
        with self.assertRaises(ValueError):add_source(self.root,b'abc','pdf','a',{})

    def test_generated_sources_are_deterministic_and_independent(self):
        self.assertEqual(pdf_bytes(3),pdf_bytes(3))
        self.assertEqual(ooxml('pptx',3),ooxml('pptx',3))
        f,_=independent_facts(pdf_bytes(3),'pdf');self.assertEqual(f['pdf.page_count'],3)
        f,_=independent_facts(ooxml('pptx',3)[0],'pptx');self.assertEqual(f['powerpoint.slide_count'],3)

    def test_macro_extension_is_not_macro_presence(self):
        f,_=independent_facts(ooxml('xlsm')[0],'xlsm');self.assertIs(f['security.has_macros'],False)

    def test_draft_never_approved_by_default(self):
        s=add_source(self.root,b'a','pdf','a',{})
        a=answer(s,'count',{'type':'target','target':'pdf.page_count'},1,{'method':'independent'})
        self.assertFalse(approved(self.root,a))

    def test_approval_binds_evidence_and_expected_value(self):
        s=add_source(self.root,b'a','pdf','a',{})
        a=answer(s,'count',{'type':'target','target':'pdf.page_count'},1,{'method':'independent'})
        atomic(self.root/'answers/index.json',{'answers':[a]})
        file=self.root/'decisions.json';atomic(file,[{'answerDigest':a['answerDigest'],'reviewer':'human','decision':'approved'}])
        record_decisions(self.root,file);record_decisions(self.root,file)
        self.assertTrue(approved(self.root,a))
        for key,value in [('expected',2),('sourceSha256','x'),('evidence',{'method':'product-output'})]:
            changed=copy.deepcopy(a);changed[key]=value;self.assertFalse(approved(self.root,changed))

    def test_pending_or_unidentified_reviewer_cannot_approve(self):
        atomic(self.root/'answers/index.json',{'answers':[]})
        atomic(self.root/'bad.json',[{'answerDigest':'x','decision':'approved','reviewer':''}])
        with self.assertRaises(ValueError):record_decisions(self.root,self.root/'bad.json')

    def test_null_missing_zero_and_boolean_are_distinct(self):
        a={'check':{'type':'target','target':'x'},'expected':0}
        for value in [{},{'status':'unknown'},{'status':'resolved','value':None},{'status':'resolved','value':False}]:
            self.assertFalse(evaluate_answer(a,{'results':{'x':value}})['passed'])
        self.assertTrue(evaluate_answer(a,{'results':{'x':{'status':'resolved','value':0}}})['passed'])

    def test_normalized_gt_comparators(self):
        report={'results':{'x':{'status':'resolved','value':10.4},'items':{'status':'resolved','value':['b','a']}}}
        self.assertTrue(evaluate_answer({'check':{'type':'target','target':'x','comparator':'numeric_tolerance','absolute_tolerance':.5},'expected':10},report)['passed'])
        self.assertTrue(evaluate_answer({'check':{'type':'target','target':'items','comparator':'unordered_equal'},'expected':['a','b']},report)['passed'])
        self.assertTrue(evaluate_answer({'check':{'type':'target','target':'x','comparator':'present'},'expected':None},report)['passed'])

    def test_partial_confidence_evidence_and_cost_semantics(self):
        r={'status':'partial','results':{'x':{'target':'x','status':'unknown'}},'execution':{'unresolved_targets':['x'],'actual_cost':{'physical_bytes_read':1,'expanded_bytes':0,'random_reads':1}}}
        self.assertEqual(report_issues(r,{}),[])
        r['status']='ok';self.assertIn('partial/ok mismatch',report_issues(r,{}))
        r['status']='partial';r['execution']['actual_cost']['random_reads']=True
        self.assertIn('invalid cost: random_reads',report_issues(r,{}))

    def test_strict_release_schema_used(self):
        self.assertTrue(report_issues({'status':'error'}, {'type':'object','required':['schema_version']}))

    def test_no_false_pass_for_missing_gate(self):
        self.assertEqual(decision([]),'INCOMPLETE')
        self.assertEqual(decision([{'status':'review'}]),'REVIEW')
        self.assertEqual(decision([{'status':'blocked'},{'status':'passed'}]),'INCOMPLETE')
        self.assertEqual(decision([{'status':'failed'},{'status':'blocked'}]),'FAIL')
        self.assertEqual(decision([{'status':'passed'},{'status':'failed','role':'observation'}]),'PASS')

    def test_new_coverage_is_not_regression(self):
        result=compare_assertions([{'id':'old','status':'failed'}],[{'id':'old','status':'failed'},{'id':'new','status':'failed'}],True)
        self.assertEqual([x['classification'] for x in result],['existing_failure','new_coverage'])

    def test_policy_changes_block_attribution(self):
        result=compare_assertions([{'id':'a','status':'passed'}],[{'id':'a','status':'failed'}],False)
        self.assertEqual(result[0]['classification'],'incomparable')

    def test_normalization_keeps_fact_and_evidence_differences(self):
        a={'input':{'source_kind':'local_file'},'results':{'x':{'value':1,'source':'a'}}}
        b=copy.deepcopy(a);b['input']['source_kind']='browser_bytes';self.assertEqual(normalize(a),normalize(b))
        b['results']['x']['source']='b';self.assertNotEqual(normalize(a),normalize(b))

    def test_only_documented_header_provenance_is_equivalent(self):
        a={'results':{'document.file_size':{'value':12,'source':'filesystem metadata','path':'pdf.header'}}}
        b=copy.deepcopy(a);b['results']['document.file_size']['source']='source length'
        self.assertEqual(normalize(a),normalize(b))
        b['results']['document.file_size']['path']='different'
        self.assertNotEqual(normalize(a),normalize(b))

    def test_weekly_unchanged_quiet_but_same_tag_new_asset_triggers(self):
        data={'candidate':{'tag':'v2.5.0'}}
        with patch('benchmark.acceptance.cli.discover',return_value=('asset-a',data)),patch('benchmark.acceptance.cli.input_fingerprint',return_value='inputs'):
            first=check(self.root);self.assertTrue(first['changed'])
            atomic(self.root/'state.json',{'lastHandledFingerprint':first['fingerprint']})
            second=check(self.root);self.assertFalse(second['changed']);self.assertFalse(second['shouldNotify'])
        with patch('benchmark.acceptance.cli.discover',return_value=('asset-b',data)),patch('benchmark.acceptance.cli.input_fingerprint',return_value='inputs'):
            self.assertTrue(check(self.root)['changed'])

    def test_no_stale_security_receipt(self):
        session={'runId':'old'}
        self.assertTrue(validate_session(session,'new','artifact','corpus'))

    def test_positive_controls_and_loss_required(self):
        c={n:{'observed':True,'blocked':True} for n in CONTROL_NAMES}
        s={'runId':'r','artifactSha256':'a','cohortHash':'c','phase':'closed','preflight':c,'postflight':copy.deepcopy(c),
           'droppedEvents':0,'droppedPackets':0,'rulesCleaned':True,'independentCollectors':True}
        self.assertEqual(validate_session(s,'r','a','c'),[])
        s['postflight']['dns']['observed']=False;self.assertTrue(validate_session(s,'r','a','c'))
        s['postflight']['dns']['observed']=True;s['droppedPackets']=None;self.assertTrue(validate_session(s,'r','a','c'))

    def test_empty_logs_are_not_security_proof(self):
        self.assertTrue(validate_session({'runId':'r','phase':'closed'},'r','a','c'))

    def test_evidence_tampering_and_missing_files(self):
        atomic(self.root/'a.json',{'a':1});seal(self.root);self.assertEqual(verify_seal(self.root),[])
        atomic(self.root/'a.json',{'a':2});self.assertTrue(verify_seal(self.root))
        (self.root/'a.json').unlink();self.assertTrue(verify_seal(self.root))

    def test_unsealed_extra_file_detected(self):
        atomic(self.root/'a.json',{});seal(self.root);atomic(self.root/'extra.json',{})
        self.assertTrue(verify_seal(self.root))

    def test_evidence_path_traversal_rejected(self):
        atomic(self.root/'evidence-manifest.json',{'files':{'../private': 'a'}})
        self.assertTrue(verify_seal(self.root))

    def test_archive_traversal_and_symlink_rejected(self):
        for name,link in [('../escape',False),('evil',True)]:
            f=io.BytesIO()
            with tarfile.open(fileobj=f,mode='w:gz') as t:
                info=tarfile.TarInfo(name)
                if link:info.type=tarfile.SYMTYPE;info.linkname='/etc/passwd';t.addfile(info)
                else:info.size=1;t.addfile(info,io.BytesIO(b'x'))
            with self.assertRaises(ValueError):safe_extract(f.getvalue(),self.root/'out')

    def test_archive_expansion_limit(self):
        f=io.BytesIO()
        with zipfile.ZipFile(f,'w',zipfile.ZIP_DEFLATED) as z:z.writestr('huge',b'0'*10000)
        with self.assertRaises(ValueError):safe_extract(f.getvalue(),self.root/'out',max_bytes=100)

    def test_npm_integrity(self):
        import base64,hashlib
        sri='sha512-'+base64.b64encode(hashlib.sha512(b'yes').digest()).decode()
        self.assertTrue(verify_sri(b'yes',sri));self.assertFalse(verify_sri(b'no',sri))

    def test_execution_lock(self):
        with locked(self.root):
            with self.assertRaises(RuntimeError):
                with locked(self.root):pass

    def test_security_module_supports_windows_without_pwd(self):
        with patch.object(security, 'pwd', None), patch.object(security.platform, 'system', return_value='Windows'), \
             patch.object(security.platform, 'machine', return_value='AMD64'), \
             patch.object(security, 'process', return_value={'exitCode': 0, 'stdout': 'v24.0.0\n'}):
            result = security.doctor(self.root)
        self.assertIsNone(result['testIdentity'])
        self.assertIn('select a native platform adapter', '; '.join(result['blockers']))

    def test_publication_sanitizer_ignores_git_worktree_metadata(self):
        site = self.root / 'site'; site.mkdir()
        git_pointer = site / '.git'
        git_pointer.write_text('gitdir: /home/runner/work/repo/.git/worktrees/site\n', encoding='utf-8')
        report = site / 'report.json'
        report.write_text('{"path":"local-evidence://result.json"}\n', encoding='utf-8')
        self.assertEqual(sanitize_publication(site), [])
        report.write_text('{"path":"/home/runner/private/result.json"}\n', encoding='utf-8')
        self.assertEqual(sanitize_publication(site), [str(report)])
        self.assertEqual(git_pointer.read_text(encoding='utf-8'),
                         'gitdir: /home/runner/work/repo/.git/worktrees/site\n')

    def test_platform_smoke_uses_frozen_ordinary_fixture_not_first_edge_case(self):
        snapshot = self.root / 'snapshot'
        atomic(snapshot / 'samples.json', {'samples': [
            {'id': 'malformed-edge', 'object': 'objects/edge.docm'},
            {'id': 'ordinary-pdf', 'object': 'objects/valid.pdf'},
        ]})
        lock = {'policy': {'performance': {'cases': ['ordinary-pdf']}}}
        self.assertEqual(_platform_smoke_sample(lock, snapshot)['id'], 'ordinary-pdf')

    def test_platform_arch_names_are_normalized_before_comparison(self):
        self.assertEqual(_canonical_arch('aarch64'), 'arm64')
        self.assertEqual(_canonical_arch('arm64'), 'arm64')
        self.assertEqual(_canonical_arch('amd64'), 'x86_64')
        self.assertEqual(_canonical_arch('x86_64'), 'x86_64')

    def test_process_timeout_kills_child_group(self):
        sentinel=self.root/'escaped'
        child='import time,pathlib;time.sleep(.5);pathlib.Path('+repr(str(sentinel))+').write_text("escaped")'
        code='import subprocess,sys,time;subprocess.Popen([sys.executable,"-c",'+repr(child)+']);time.sleep(10)'
        result=process([sys.executable,'-c',code],timeout=.1)
        self.assertTrue(result['timedOut']);time.sleep(.6);self.assertFalse(sentinel.exists())

    def test_public_ci_snapshot_is_path_independent_and_tamper_evident(self):
        sample=add_source(self.root,b'public-pdf','pdf','case-cc0cff1b91879bebb339',{'type':'generated'});sample['private']=False
        pptx=add_source(self.root,b'public-pptx','pptx','case-2e921ccffab9ea815eea',{'type':'generated'});pptx['private']=False
        xlsx=add_source(self.root,b'public-xlsx','xlsx','case-fad1409b1b0d8cb9f7ef',{'type':'generated'});xlsx['private']=False
        atomic(self.root/'corpus/manifest.json',{'sources':[sample,pptx,xlsx],'gaps':[],'cohortHash':'cohort'})
        a=answer(sample,'页面数',{'type':'target','target':'pdf.page_count'},1,
                 {'method':'independent','recordPath':'/Users/example/private/evidence.json'})
        atomic(self.root/'answers/index.json',{'answers':[a]})
        atomic(self.root/'answers/decisions'/(a['answerDigest']+'.json'),
               {'answerDigest':a['answerDigest'],'decision':'approved','reviewer':'human'})
        atomic(self.root/'declarations.json',approved_claims(a['id']))
        out=self.root/'snapshot';result=export_snapshot(self.root,out)
        self.assertTrue(result['ready']);self.assertEqual(validate_snapshot(out),[])
        self.assertNotIn('/Users/',(out/'answers.json').read_text())
        execution=self.root/'execution';materialize_snapshot(out,execution)
        frozen=read(execution/'answers/index.json')['answers'][0]
        self.assertTrue(approved(execution,frozen))
        objects=list((out/'objects').rglob('*'))
        target=next(p for p in objects if p.is_file());target.chmod(0o600);target.write_bytes(b'changed')
        self.assertTrue(validate_snapshot(out))

    def test_snapshot_validation_scans_claims_and_rejects_unlisted_files(self):
        sample=add_source(self.root,b'public-pdf','pdf','case-cc0cff1b91879bebb339',{'type':'generated'});sample['private']=False
        pptx=add_source(self.root,b'public-pptx','pptx','case-2e921ccffab9ea815eea',{'type':'generated'});pptx['private']=False
        xlsx=add_source(self.root,b'public-xlsx','xlsx','case-fad1409b1b0d8cb9f7ef',{'type':'generated'});xlsx['private']=False
        atomic(self.root/'corpus/manifest.json',{'sources':[sample,pptx,xlsx],'gaps':[],'cohortHash':'cohort'})
        a=answer(sample,'页面数',{'type':'target','target':'pdf.page_count'},1,{'method':'independent'})
        atomic(self.root/'answers/index.json',{'answers':[a]})
        atomic(self.root/'answers/decisions'/(a['answerDigest']+'.json'),{'answerDigest':a['answerDigest'],'decision':'approved','reviewer':'human'})
        atomic(self.root/'declarations.json',approved_claims(a['id']))
        out=self.root/'snapshot';export_snapshot(self.root,out)
        claims=read(out/'claims.json');claims['claims']['note']='token=secret-value';atomic(out/'claims.json',claims)
        self.assertIn('sensitive value at claims.claims.note',validate_snapshot(out))
        atomic(out/'claims.json',{'schemaVersion':1,'claims':approved_claims(a['id'])})
        (out/'unexpected.txt').write_text('extra')
        self.assertIn('checksum inventory mismatch',validate_snapshot(out))

    def test_draft_snapshot_never_gets_ready_marker(self):
        sample=add_source(self.root,b'public','pdf','public',{'type':'generated'});sample['private']=False
        atomic(self.root/'corpus/manifest.json',{'sources':[sample],'cohortHash':'cohort'})
        a=answer(sample,'页面数',{'type':'target','target':'pdf.page_count'},1,{'method':'independent'})
        atomic(self.root/'answers/index.json',{'answers':[a]});atomic(self.root/'declarations.json',approved_claims(a['id']))
        out=self.root/'draft';result=export_snapshot(self.root,out,allow_draft=True)
        self.assertFalse(result['ready']);self.assertFalse((out/'READY').exists())
        self.assertIn('snapshot is not READY',validate_snapshot(out))
        with self.assertRaisesRegex(ValueError,'still require approval'):
            export_snapshot(self.root,self.root/'formal')

    def test_ready_snapshot_rejects_missing_performance_fixture(self):
        sample=add_source(self.root,b'public','pdf','pdf-pages-1',{'type':'generated'});sample['private']=False
        atomic(self.root/'corpus/manifest.json',{'sources':[sample],'gaps':[],'cohortHash':'cohort'})
        a=answer(sample,'页面数',{'type':'target','target':'pdf.page_count'},1,{'method':'independent'})
        atomic(self.root/'answers/index.json',{'answers':[a]})
        atomic(self.root/'answers/decisions'/(a['answerDigest']+'.json'),{'answerDigest':a['answerDigest'],'decision':'approved','reviewer':'human'})
        atomic(self.root/'declarations.json',approved_claims(a['id']))
        with self.assertRaisesRegex(ValueError,'performance cases are missing'):
            export_snapshot(self.root,self.root/'formal')

    def test_ci_aggregate_rejects_mismatched_and_duplicate_results(self):
        lock={'runId':'r','inputDigest':'digest','candidate':{'tag':'v1'},'snapshotDigest':'s',
              'codeSha256':code_hash(),'policyHash':'p','status':'READY'}
        atomic(self.root/'lock.json',lock)
        result={'schemaVersion':1,'runId':'other','inputDigest':'digest','job':'security-linux','checks':[]}
        atomic(self.root/'inputs/a/job-result.json',result);seal(self.root/'inputs/a')
        with self.assertRaisesRegex(ValueError,'binding mismatch'):
            aggregate_ci(self.root/'lock.json',self.root/'inputs',self.root/'out-a')
        result['runId']='r';result['release']='v1';atomic(self.root/'inputs/a/job-result.json',result);seal(self.root/'inputs/a')
        atomic(self.root/'inputs/b/job-result.json',result);seal(self.root/'inputs/b')
        with self.assertRaisesRegex(ValueError,'duplicate job result'):
            aggregate_ci(self.root/'lock.json',self.root/'inputs',self.root/'out-b')

    @patch('benchmark.acceptance.github_ci.npm_record', side_effect=[{'version':'1'}, {'version':'1'}] * 4)
    @patch('benchmark.acceptance.github_ci._release', return_value=({'tag':'v1','assets':[]}, {'tag':'v0','assets':[]}))
    @patch('benchmark.acceptance.github_ci.validate_snapshot', return_value=[])
    def test_failed_and_forced_same_input_get_new_run_ids(self, _validate, _release, _npm):
        snapshot=self.root/'snapshot';snapshot.mkdir()
        first=freeze_ci(snapshot,self.root/'first')
        atomic(self.root/'history/history.json',{'runs':[{'inputDigest':first['inputDigest'],'decision':'FAIL'}]})
        retry=freeze_ci(snapshot,self.root/'retry',history=self.root/'history')
        self.assertTrue(retry['changed']);self.assertIn('-rerun-',retry['runId'])
        self.assertEqual(retry['combinationId'],first['combinationId'])
        atomic(self.root/'history/history.json',{'runs':[{'inputDigest':first['inputDigest'],'decision':'PASS'}]})
        quiet=freeze_ci(snapshot,self.root/'quiet',history=self.root/'history')
        self.assertEqual(quiet['status'],'NO_CHANGE');self.assertFalse(quiet['changed'])
        forced=freeze_ci(snapshot,self.root/'forced',history=self.root/'history',force=True)
        self.assertTrue(forced['changed']);self.assertIn('-rerun-',forced['runId'])

    def test_no_change_updates_history_without_overwriting_run(self):
        lock={'schemaVersion':1,'runId':'v1-input','inputDigest':'digest','candidate':{'tag':'v1'},
              'snapshotDigest':'s','codeSha256':code_hash(),'policyHash':'p','status':'READY'}
        atomic(self.root/'lock.json',lock);(self.root/'empty').mkdir()
        aggregate_ci(self.root/'lock.json',self.root/'empty',self.root/'run')
        implementation=read(self.root/'run/implementation-manifest.json')
        self.assertIn('github_ci.py',implementation);self.assertIn('linux_security.py',implementation)
        publish_history(self.root/'run',self.root/'site')
        original=sha(self.root/'site/runs/v1-input/run.json')
        lock['status']='NO_CHANGE';atomic(self.root/'no-change-lock.json',lock)
        aggregate_ci(self.root/'no-change-lock.json',self.root/'empty',self.root/'no-change')
        result=publish_history(self.root/'no-change',self.root/'site')
        self.assertTrue(result['noChange']);self.assertEqual(sha(self.root/'site/runs/v1-input/run.json'),original)
        self.assertEqual(read(self.root/'site/history.json')['checks'][-1]['status'],'NO_CHANGE')

    def test_history_and_incomparable_diff_prioritize_human_summary(self):
        history={'runs':[{'runId':'r1','createdAt':'2026-09-07T14:48:05+00:00','release':'v2.5.0','decision':'FAIL',
                          'url':'runs/r1/report.html','comparisonUrl':'comparisons/a/comparison.html',
                          'counts':{'passed':327,'failed':18,'blocked':2},'performanceAlerts':1}]}
        history_html=_history_page(history)
        self.assertIn('327 PASS · 18 FAIL · 2 BLOCKED',history_html)
        self.assertIn('北京时间',history_html)
        comparison={'before':'a','after':'b','comparable':False,'guardDifferences':['codeSha256'],
                    'changes':[{'id':str(i),'classification':'incomparable','before':'passed','after':'passed'} for i in range(406)],
                    'statusTransitions':[{'id':'changed','title':'必需字段是否保持不变？','requirement':'PRO-R05',
                                          'classification':'status_changed','before':'failed','after':'passed',
                                          'expected':True,'beforeActual':False,'afterActual':True,
                                          'beforeUrl':'../../runs/a/report.html#PRO-R05/changed',
                                          'afterUrl':'../../runs/b/report.html#PRO-R05/changed'}],
                    'currentPerformance':[],'sourceLabels':{}}
        comparison_html=_comparison_page(comparison)
        self.assertEqual(comparison_html.count('class="change '),1)
        self.assertIn('只展示状态变化，不归因于产品',comparison_html)
        self.assertIn('查看全部 406 条机器比较记录',comparison_html)
        self.assertIn('必需字段是否保持不变？',comparison_html)
        self.assertIn('前版 · FAILED',comparison_html)
        self.assertIn('本轮 · PASSED',comparison_html)
        self.assertIn('查看本轮详情',comparison_html)

    def test_offline_report_rebuild_preserves_evidence_and_escape(self):
        folder=self.root/'run';folder.mkdir()
        record={'checks':[{'id':'a','requirement':'PRO-R03','title':'<script>bad</script>','status':'review','expected':1,'actual':2}],
                'targetVersion':'v2.5.0','runId':'r','createdAt':'2026-01-01','codeSha256':code_hash(),'mode':'diagnostic'}
        publish(folder,record);atomic(folder/'coverage.json',{});seal(folder)
        original=sha(folder/'run.json')
        rebuild(folder,self.root/'rebuilt')
        self.assertEqual(sha(folder/'run.json'),original)
        self.assertEqual(verify_seal(self.root/'rebuilt'),[])
        self.assertNotIn('<script>bad</script>',(self.root/'rebuilt/report.html').read_text())
        self.assertEqual(read(folder/'run.json')['qualitySummary']['releaseDecision'],'REVIEW')
        self.assertEqual(sha(self.root/'rebuilt/run.json'),original)
        self.assertEqual(sha(self.root/'rebuilt/agent-report.json'),sha(folder/'agent-report.json'))

    def test_presentation_draft_match_never_becomes_approval(self):
        matched={'status':'review','approval':'draft','details':{'diagnosticMatch':True}}
        self.assertEqual(comparison_kind(matched),'matched')
        self.assertEqual(matched['status'],'review')
        self.assertEqual(comparison_kind({'status':'review','details':{'diagnosticMatch':False}}),'different')
        self.assertEqual(comparison_kind({'status':'review','actual':'pending explicit answer approval'}),'unexecuted')
        self.assertEqual(comparison_kind({'status':'blocked','actual':[]}), 'blocked')
        self.assertEqual(comparison_kind({'status':'blocked','actual':'Private scan requires live isolation'}), 'unexecuted')

    def test_presentation_parser_error_missing_null_and_zero_distinct(self):
        answer={'check':{'type':'target','target':'count'}}
        def observe(report):return target_observation(answer,{'stdout':json.dumps(report)})
        self.assertEqual(observe({'status':'error','error':{'code':'MALFORMED_INPUT'}})['kind'],'error')
        self.assertEqual(observe({'results':{}})['kind'],'missing')
        self.assertFalse(observe({'results':{'count':{'status':'unknown'}}})['valuePresent'])
        for value in [None,0,False]:
            actual=observe({'results':{'count':{'status':'resolved','value':value}}})
            self.assertTrue(actual['valuePresent']);self.assertIs(actual['result']['value'],value)

    def test_report_rejects_current_gt_for_a_different_frozen_run(self):
        atomic(self.root/'corpus/manifest.json',{'sources':[{'id':'s','sha256':'source'}]})
        atomic(self.root/'answers/index.json',{'answers':[{'expected':'unreviewed replacement'}]})
        record={'runId':'old','cohortHash':'other','answersHash':'other'}
        ctx=capture_context(self.root/'run',record,self.root)
        self.assertFalse(ctx['corpusBound']);self.assertFalse(ctx['answersBound'])
        self.assertEqual(ctx['sources'],[]);self.assertEqual(ctx['answers'],[])


if __name__=='__main__':unittest.main()
