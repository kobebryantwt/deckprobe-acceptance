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
    before_checks={x['id']:x for x in a.get('checks',[])}
    status_transitions=[{'id':x['id'],'classification':'status_changed','before':before_checks[x['id']].get('status'),'after':x.get('status')}
                        for x in b.get('checks',[]) if x['id'] in before_checks and before_checks[x['id']].get('status')!=x.get('status')]
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
    current_performance=next((x.get('details',{}).get('distributions',[]) for x in b.get('checks',[]) if x.get('id')=='performance_pair'),[])
    source_labels={}
    for source in read(Path(after_folder)/'report-context.json',{}).get('sources',[]):
        binding=source.get('purpose',{}).get('binding',{})
        source_labels[source.get('id')]=binding.get('inputName') or Path(str(source.get('path',''))).name or source.get('id')
    result={'before':a['runId'],'after':b['runId'],'comparable':not differences,'guardDifferences':differences,
            'changes':changes,'statusTransitions':status_transitions,'performance':performance,
            'currentPerformance':current_performance,'sourceLabels':source_labels}
    output=Path(output)
    if output.exists():raise ValueError('Comparison output must be a new directory')
    output.mkdir(parents=True)
    atomic(output/'comparison.json',result)
    atomic(output/'comparison.html',_comparison_page(result))
    seal(output)
    return result


def _comparison_page(result):
    labels={'regression':'回归','fixed':'已修复','new_coverage':'新增覆盖','removed_coverage':'覆盖移除',
            'environment_or_evidence':'环境或证据变化','needs_review':'待复核','incomparable':'不可直接比较',
            'existing_failure':'持续失败','unchanged':'未变化','status_changed':'状态变化（不可归因）'}
    attention={'regression','fixed','new_coverage','removed_coverage','environment_or_evidence','needs_review','existing_failure'}
    changes=result.get('changes',[])
    if result.get('comparable'):important=[x for x in changes if x.get('classification') in attention]
    else:important=result.get('statusTransitions',[])+[x for x in changes if x.get('classification') in {'new_coverage','removed_coverage'}]
    count=lambda kind:sum(x.get('classification')==kind for x in changes)
    esc=lambda value:html.escape(str(value if value is not None else '—'))
    def change_card(row):
        kind=row.get('classification','unchanged')
        return f'<article class="change {esc(kind)}"><div><strong>{esc(row.get("id"))}</strong><span>{esc(labels.get(kind,kind))}</span></div><p>{esc(row.get("before"))} <b>→</b> {esc(row.get("after"))}</p></article>'
    alerts=[x for x in result.get('currentPerformance',[]) if x.get('status')=='review']
    def perf_card(row):
        name=result.get('sourceLabels',{}).get(row.get('caseId'),row.get('caseId'))
        p50=f'{row.get("previousP50Ms",0):.3f} → {row.get("candidateP50Ms",0):.3f} ms · {row.get("p50RelativeDelta",0)*100:+.1f}%'
        p95=f'{row.get("previousP95Ms",0):.3f} → {row.get("candidateP95Ms",0):.3f} ms · {row.get("p95RelativeDelta",0)*100:+.1f}%'
        return f'<article class="perf"><strong>{esc(name)}</strong><span>{esc(row.get("level"))} · {esc(row.get("mode"))}</span><dl><dt>p50</dt><dd>{esc(p50)}</dd><dt>p95</dt><dd>{esc(p95)}</dd></dl></article>'
    guards=', '.join(result.get('guardDifferences',[])) or '无'
    css='''*{box-sizing:border-box}body{margin:0;background:#f4f5f0;color:#202b29;font:14px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC",sans-serif}main{max-width:1120px;margin:auto;padding:44px 24px}a{color:#315e4d;text-decoration:none}.hero{display:flex;justify-content:space-between;gap:28px;align-items:flex-start}.eyebrow{font-size:11px;letter-spacing:1.4px;color:#315e4d}.hero h1{font-size:30px;margin:8px 0}.hero p{color:#6c7470}.actions{display:flex;gap:8px;flex-wrap:wrap}.button{background:#315e4d;color:#fff;padding:9px 14px;border-radius:7px}.button.secondary{background:#fff;color:#315e4d;border:1px solid #dce2d8}.notice{margin:22px 0;padding:14px 16px;border-radius:9px;background:#fff8eb;border:1px solid #ead5aa}.metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:22px 0 34px}.metric{background:#fff;border:1px solid #e2e6df;border-radius:10px;padding:15px}.metric strong{display:block;font-size:27px}.metric span{font-size:11px;color:#6c7470}section{margin:30px 0}h2{font-size:20px}.change,.perf{background:#fff;border:1px solid #e2e6df;border-radius:9px;padding:14px 16px;margin:9px 0}.change{display:flex;justify-content:space-between;gap:16px}.change div span,.perf>span{display:block;color:#6c7470;font-size:11px}.change p{margin:0;font-family:ui-monospace,monospace}.change.regression,.change.existing_failure{border-left:4px solid #ae443c}.change.fixed{border-left:4px solid #315e4d}.change.needs_review,.change.environment_or_evidence,.change.status_changed{border-left:4px solid #95621b}.perf{border-left:4px solid #95621b}.perf dl{display:grid;grid-template-columns:45px 1fr;gap:5px;margin:10px 0 0}.perf dt{color:#6c7470}.perf dd{margin:0;font-family:ui-monospace,monospace}details{background:#fff;border:1px solid #e2e6df;border-radius:9px;padding:13px 16px;margin-top:12px}summary{cursor:pointer;color:#315e4d}.machine{max-height:420px;overflow:auto;font:11px/1.6 ui-monospace,monospace;white-space:pre-wrap}.empty{color:#6c7470;background:#fff;padding:20px;border-radius:9px}@media(max-width:700px){main{padding:28px 16px}.hero{display:block}.actions{margin-top:16px}.metrics{grid-template-columns:1fr 1fr}.change{display:block}.change p{margin-top:8px;overflow-wrap:anywhere}}'''
    body=''.join(change_card(x) for x in important) or '<p class="empty">断言状态没有需要特别关注的变化。</p>'
    perf=''.join(perf_card(x) for x in alerts) or '<p class="empty">本轮没有 R06 配置触发性能复核阈值。</p>'
    raw=esc(json.dumps(changes,ensure_ascii=False,indent=2))
    comparable='可直接比较并归因于产品变化' if result.get('comparable') else '验收条件已变化，只展示状态变化，不归因于产品'
    fourth='值得关注的变化' if result.get('comparable') else '断言状态变化'
    return f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>DeckProbe 验收差异</title><style>{css}</style><main><header class="hero"><div><div class="eyebrow">DECKPROBE ACCEPTANCE · RUN COMPARISON</div><h1>两轮验收有什么变化？</h1><p>{esc(result.get('before'))} → {esc(result.get('after'))}</p></div><nav class="actions"><a class="button" href="../../latest/report.html">打开最新完整报告</a><a class="button secondary" href="../../">返回历史首页</a></nav></header><div class="notice"><strong>{esc(comparable)}</strong><br>比较条件变化：{esc(guards)}</div><div class="metrics"><div class="metric"><strong>{len(changes)}</strong><span>全部断言</span></div><div class="metric"><strong>{count('regression') if result.get('comparable') else '—'}</strong><span>新增回归</span></div><div class="metric"><strong>{count('fixed') if result.get('comparable') else '—'}</strong><span>已修复</span></div><div class="metric"><strong>{len(important)}</strong><span>{fourth}</span></div></div><section><h2>{'值得关注的断言变化' if result.get('comparable') else '本轮断言状态变化'}</h2>{body}<details><summary>查看全部 {len(changes)} 条机器比较记录</summary><pre class="machine">{raw}</pre></details></section><section><h2>本轮 R06 性能提醒</h2><p>这里只突出越过“变慢 20% 且至少 2 ms”的配置；它是观察项，不参与发布门禁。</p>{perf}</section></main></html>'''
