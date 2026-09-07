"""Use the verified Core's canonical dual report contract, plus acceptance scope."""
from __future__ import annotations
import importlib.util
import html
import json
import shutil
from pathlib import Path
from .common import ROOT, CODE, atomic, code_hash, now, read, seal, sha, verify_seal
from .contracts import decision, compare_assertions
from .report_view import render


def core():
    spec=importlib.util.spec_from_file_location('acceptance_benchmark_core',ROOT/'benchmark/scripts/deck_benchmark.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    if not module.core_conformance()['ok']:raise RuntimeError('Benchmark Core behavioral conformance failed')
    return module


def publish(folder, record, home=None):
    c=core();folder=Path(folder)
    implementation = folder / 'implementation-manifest.json'
    if not implementation.exists():
        if record.get('codeSha256') != code_hash():
            raise ValueError('Current implementation does not match the frozen report identity')
        from .case_explanations import SUPPORTED
        manifest = {}
        for name in SUPPORTED:
            source = CODE / name
            destination = folder / 'implementation' / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
            manifest[name] = sha(destination)
        atomic(implementation, manifest)
    results=[];cases=[];questions=[]
    for item in record['checks']:
        definition={'id':item['id'],'type':'acceptance_contract','role':item.get('role','gate'),
                    'severity':'critical' if item['requirement'] in {'PRO-R02','PRO-R03','PRO-R04'} else 'major',
                    'featureId':item['requirement'],'expected':item.get('expected')}
        case={'id':item['id'],'covers':[item['requirement']],'assertions':[definition]}
        cases.append(case)
        result={'caseId':item['id'],'status':item['status'],'source':{'uri':item.get('source','release://'+record['targetVersion'])},
                'durationMs':0,'command':item.get('command',[]),'assertions':[{**definition,'status':item['status'],'actual':item.get('actual'),'details':item.get('details')}],
                'evidence':item.get('evidence',[])}
        # Core's build_findings treats case-blocked as infrastructure, retaining that distinction.
        results.append(result)
        questions.append({'questionId':'q-'+item['id'],'caseId':item['id'],'question':item['title'],
                          'answer':item.get('expected'),'assertionIds':[item['id']],
                          'evidence':item.get('evidence',[]),'reviewStatus':item.get('approval','approved-rule')})
        atomic(folder/'raw'/(item['id'].replace(':','-')+'.json'),result)
    suite={'id':'deckprobe-release-acceptance-v1','displayName':'DeckProbe 发布验收 · 完整手册',
           'version':'1','profile':'probe','qualityPolicy':{'version':'1','scoring':{'aggregation':'macro_feature','scale':100}}}
    target={'id':'released-'+record['targetVersion'],'displayName':'Published DeckProbe '+record['targetVersion']}
    quality=c.summarize_quality(results,cases,suite,'declarative')
    quality['releaseDecision']=decision(record['checks'])
    quality['decisionReason']='Explicit mandatory checks; missing coverage/evidence never becomes PASS'
    quality['localDecision']=decision([x for x in record['checks'] if x.get('scope','local')=='local'])
    envelope={'contractVersion':c.REPORT_CONTRACT_VERSION,'benchmarkCoreVersion':c.CORE_VERSION,
              'runId':record['runId'],'createdAt':record['createdAt'],'suite':suite,'target':target,
              'evaluator':{'id':'release-acceptance','version':'1','codeSha256':record['codeSha256']},
              'results':results,'findings':c.build_findings(results,suite,target,record['runId']),
              'qualitySummary':quality,'counts':{s:sum(r['status']==s for r in results) for s in ['passed','failed','review','blocked']},
              'acceptance':record}
    atomic(folder/'questions.json',questions)
    atomic(folder/'run.json',envelope)
    c.build_reports(envelope,folder,questions)
    # Core reports use the checkout as a reproduction cwd. Public acceptance
    # reports retain the command but publish a repository-relative location.
    from .ci_snapshot import _portable
    agent=read(folder/'agent-report.json')
    if agent is not None:atomic(folder/'agent-report.json',_portable(agent))
    core_page=(folder/'report.html').read_text().replace(str(ROOT),'<repository>')
    atomic(folder/'report.html',core_page)
    atomic(folder/'core-report.html',(folder/'report.html').read_text())
    render(folder,envelope,home)
    return envelope


def rebuild(folder, output):
    errors=verify_seal(folder)
    if errors:raise ValueError('; '.join(errors))
    output=Path(output)
    if output.exists():raise ValueError('Rebuild output must be a new directory')
    import shutil
    shutil.copytree(folder,output)
    # A presentation rebuild must preserve the original machine verdict and evidence bytes.
    if not (output/'core-report.html').exists():
        shutil.copyfile(output/'report.html',output/'core-report.html')
    render(output,read(output/'run.json'),Path(folder).parent.parent)
    seal(output)
    return str(output/'report.html')


def compare(before_folder, after_folder, output):
    for folder in [before_folder,after_folder]:
        errors=verify_seal(folder)
        if errors:raise ValueError('; '.join(errors))
    a=read(Path(before_folder)/'run.json')['acceptance'];b=read(Path(after_folder)/'run.json')['acceptance']
    guards=['codeSha256','policyHash','cohortHash','answersHash','declarationsHash']
    differences=[k for k in guards if a.get(k)!=b.get(k)]
    changes=compare_assertions(a['checks'],b['checks'],not differences)
    performance=[]
    first=read(Path(before_folder)/'evidence/performance.json',[])
    second=read(Path(after_folder)/'evidence/performance.json',[])
    key=lambda x:(x.get('caseId'),x.get('sourceSha256'),x.get('level'),x.get('mode'))
    indexed={key(x):x for x in first}
    for current in second:
        previous=indexed.get(key(current))
        if not previous or not current.get('complete') or not previous.get('complete'):continue
        for metric in ['p50Ms','p95Ms']:
            before=previous.get(metric);after=current.get(metric)
            if before is None or after is None:continue
            delta=after-before;relative=delta/before if before>0 else None
            alert=relative is not None and relative>=.2 and delta>=2
            performance.append({'caseId':current['caseId'],'level':current['level'],'mode':current['mode'],'metric':metric,
                                'before':before,'after':after,'absoluteDeltaMs':delta,'relativeDelta':relative,
                                'status':'review' if alert else 'observation','comparable':not differences,
                                'claim':'background observation only; controlled repeat required for attribution'})
    result={'before':a['runId'],'after':b['runId'],'comparable':not differences,'guardDifferences':differences,'changes':changes,'performance':performance}
    output=Path(output)
    if output.exists():raise ValueError('Comparison output must be a new directory')
    output.mkdir(parents=True)
    atomic(output/'comparison.json',result)
    rows=''.join('<tr>'+''.join('<td>'+html.escape(str(x.get(k,'')))+'</td>' for k in ['id','classification','before','after'])+'</tr>' for x in changes)
    perf_rows=''.join('<tr>'+''.join('<td>'+html.escape(str(x.get(k,'')))+'</td>' for k in ['caseId','level','mode','metric','before','after','status'])+'</tr>' for x in performance)
    atomic(output/'comparison.html','<!doctype html><meta charset="utf-8"><title>DeckProbe 周度差异</title><style>body{font:15px system-ui;margin:40px}td,th{padding:10px;border:1px solid #ddd}table{border-collapse:collapse;width:100%}</style><h1>周度差异</h1><p>可直接归因产品变化：'+str(not differences)+'；条件变化：'+html.escape(', '.join(differences))+'</p><table><tr><th>断言</th><th>分类</th><th>之前</th><th>之后</th></tr>'+rows+'</table><h2>后台性能观察</h2><p>超过20%且2ms仅提示复核；不作为正式性能回归结论。</p><table><tr><th>样本</th><th>级别</th><th>运行方式</th><th>指标</th><th>之前</th><th>之后</th><th>结论</th></tr>'+perf_rows+'</table>')
    seal(output)
    return result
