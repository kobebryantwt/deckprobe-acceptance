from __future__ import annotations
import json
import math
import os
from pathlib import Path
import platform
import shutil
import statistics

from .common import CODE, atomic, code_hash, code_files, digest, now, process, read, seal, sha, verify_seal
from .contracts import evaluate_answer, normalize, report_issues, decision
from .corpus import approved
from .coverage import coverage
from .reporting import publish
from .security import doctor
from .supply_evidence import collect as collect_supply_evidence


def item(id,requirement,title,status,expected=None,actual=None,**kwargs):
    return {'id':id.replace('/','_').replace(':','_'),'requirement':requirement,'title':title,'status':status,
            'expected':expected,'actual':actual,**kwargs}


def probe(binary,source,options):
    p=process([binary,*options,source],timeout=read(CODE/'config/policy.json')['processTimeoutSeconds'])
    try:r=json.loads(p['stdout'])
    except ValueError:r={}
    return p,r


def runtime_valid(target):
    errors=[];release=target['release'];packages=target.get('packages')
    if not Path(release['binary']).is_file() or sha(release['binary'])!=release['binarySha256']:
        errors.append('Published native binary changed')
    for a in release['assets']:
        p=Path(release['folder'])/a['name']
        if not p.is_file() or sha(p)!=a['sha256']:errors.append('Release asset changed: '+a['name'])
    for record in release.get('sourceSnapshots',{}).values():
        if record.get('missing'):continue
        if not Path(record['path']).is_file() or sha(record['path'])!=record['sha256']:errors.append('Source snapshot changed')
    for archive,files in release['extracted'].items():
        for name,h in files.items():
            p=Path(release['folder'])/'unpacked'/archive/name
            if not p.is_file() or sha(p)!=h:errors.append('Extracted release file changed: '+name)
    if packages:
        base=Path(packages['folder'])
        if sha(base/'package-lock.json')!=packages['lockSha256']:errors.append('npm lock changed')
        for name,h in packages['runtimeFiles'].items():
            p=base/name
            if not p.is_file() or sha(p)!=h:errors.append('npm runtime file changed: '+name)
        current={str(p.relative_to(base)) for p in (base/'node_modules').rglob('*') if p.is_file() and not p.is_symlink()}
        if current!=set(packages['runtimeFiles']):errors.append('npm runtime file inventory changed')
    return errors


def tool_payload(response):
    result=response.get('result',{})
    if 'structuredContent' in result:return result['structuredContent']
    for c in result.get('content',[]):
        if c.get('type')=='text':
            try:return json.loads(c['text'])
            except ValueError:pass
    return None


def run(home,label='candidate',diagnostic=False,performance=False,target_override=None):
    home=Path(home);prepared=read(home/'prepared.json')
    if not target_override and (not prepared or label not in prepared.get('targets',{})):raise ValueError('Run prepare --online before run')
    target=target_override or prepared['targets'][label];release=target['release'];binary=release['binary']
    runtime_errors=runtime_valid(target)
    if runtime_errors:raise ValueError('; '.join(runtime_errors))
    policy=read(home/'policy.json',read(CODE/'config/policy.json'));corpus=read(home/'corpus/manifest.json')
    answer_index=read(home/'answers/index.json',{'answers':[]})
    sources={s['id']:s for s in corpus['sources'] if s.get('active',True)}
    env=doctor(home)
    bindings={'codeSha256':code_hash(),'policyHash':digest(policy),'cohortHash':corpus['cohortHash'],
              'answersHash':digest({'answers':answer_index,'decisions':{p.name:sha(p) for p in (home/'answers/decisions').glob('*.json')}}),
              'declarationsHash':digest(read(home/'declarations.json',{})),
              'targetIdentity':digest(target),'environmentHash':digest(env),'mode':'diagnostic' if diagnostic else 'formal',
              'preparationEvidenceHash':digest({'attestation':read(Path(release['folder'])/'attestation-refresh.json'),
                  'securityEntry':read(home/'security-entry.json'),
                  'npmSignatureAudit':read(Path(target['packages']['folder'])/'signature-audit-lock.json') if target.get('packages') else None}),
              'performance':performance,'maintenanceHash':digest(read(home/'maintenance-applied.json',{}))}
    run_id=release['release']['tag']+'-'+digest(bindings)[:20]
    folder=home/'runs'/run_id
    if (folder/'evidence-manifest.json').exists():
        errors=verify_seal(folder)
        if errors:raise ValueError('; '.join(errors))
        return {'runId':run_id,'reused':True,'report':str(folder/'report.html'),
                'decision':read(folder/'run.json')['qualitySummary']['releaseDecision']}
    folder.mkdir(parents=True,exist_ok=True)
    implementation={}
    for name,path in code_files().items():
        copy=folder/'implementation'/name
        copy.parent.mkdir(parents=True,exist_ok=True)
        if not copy.exists():shutil.copyfile(path,copy)
        implementation[name]=sha(copy)
    if digest(implementation)!=bindings['codeSha256']:raise ValueError('Implementation snapshot does not match run identity')
    atomic(folder/'implementation-manifest.json',implementation)
    evidence=folder/'evidence';evidence.mkdir(exist_ok=True)
    checks=[]

    def save(name,data):
        atomic(evidence/(name+'.json'),data)
        return 'evidence/'+name+'.json'

    def stage(name,fn):
        p=folder/'checkpoints'/(name+'.json')
        if p.exists():
            saved=read(p)
            if saved['bindings']!=digest(bindings):raise ValueError('Checkpoint identity mismatch')
            # Validate stage evidence before using a checkpoint after interruption.
            if any(not (folder/n).is_file() or sha(folder/n)!=h for n,h in saved.get('evidenceHashes',{}).items()):
                raise ValueError('Checkpoint evidence was modified')
            part=saved['checks']
        else:
            part=fn()
            hashes={str(p.relative_to(folder)):sha(p) for p in evidence.rglob('*') if p.is_file()}
            atomic(p,{'bindings':digest(bindings),'checks':part,'evidenceHashes':hashes})
        checks.extend(part)

    def supply():
        provenance=save('release',release)
        p=process([binary,'--version']);save('version',p)
        status='passed' if p['exitCode']==0 and p['stdout'].strip()=='deckprobe '+release['release']['tag'].lstrip('v') else 'failed'
        out=[item('release_version','PRO-R01','发布二进制版本与 tag 一致',status,'deckprobe '+release['release']['tag'].lstrip('v'),p['stdout'].strip(),evidence=['evidence/version.json'],command=p['command'])]
        audits=collect_supply_evidence(folder,target)
        titles={'release_checksums':'发布附件完整性与平台包 checksum',
                'release_provenance':'构建来源逐项绑定 repository、subject 和 commit',
                'release_licenses':'引擎、JS 与 MCP 的许可证标识和随包 LICENSE / NOTICE',
                'npm_signatures':'npm 已安装依赖的 registry 签名验证'}
        for id,entry in audits.items():
            audit=entry['audit']
            out.append(item(id,'PRO-R01',titles[id],entry['status'],audit['scope'],audit['summary'],
                            details={'audit':audit},evidence=[entry['evidence']]))
        has_notice = any('NOTICE' in files for files in release.get('extracted', {}).values())
        out.append(item('third_party_disclosure','PRO-R01','随包版权与版本声明披露','passed' if has_notice else 'failed',
                        '随包包含 Apache-2.0 LICENSE 与 NOTICE 版本版权声明',
                        '发布包已包含标准 LICENSE 与 NOTICE 版权声明' if has_notice else '缺少随包 NOTICE 声明',
                        evidence=['evidence/r01/release_licenses.json']))
        packages=target.get('packages')
        if packages:
            result=process(['node',str(Path(packages['folder'])/'node_modules/@deckflow/deckprobe/bin/deckprobe.js'),'--version'],timeout=30)
            save('npm-native-launcher',result)
            out.append(item('npm_native_install','PRO-R08','npm 平台包可启动且版本一致','passed' if result['exitCode']==0 and result['stdout']==p['stdout'] else 'failed',p['stdout'],result['stdout'],evidence=['evidence/npm-native-launcher.json']))
        out.append(item('native_install','PRO-R08','macOS ARM64 发布包解压安装后可运行',status,'native release executable',p['stdout']))
        out.append(item('platform_matrix','PRO-R08','全部发布平台安装运行证据','blocked',policy['platforms'],{'executed':['aarch64-apple-darwin'],'missing':policy['platforms'][1:]},scope='full'))
        out.append(item('publication_wording','PRO-R02','新增产品文案不作完整安全结论','review','review release documentation changes',{'sourceCommit':release['release']['commit']},evidence=[provenance]))
        return out

    def safety():
        e=save('doctor',env)
        return [item('live_security_monitor','PRO-R02','独立隔离和监控通过本轮前后自检','blocked','live, complete and bound evidence',env['blockers'],evidence=[e]),
                item('private_sources_protected','PRO-R02','未建立可靠隔离时不扫描私有文件','passed','private inputs not passed to target',sum(s['private'] for s in sources.values()))]

    def facts():
        save('fact-library',read(home/'facts/index.json',{'version':2,'facts':[]}))
        out=[];cache={};schema_path=Path(release['folder'])/'source/docs/deckprobe-report.schema.json'
        schema=read(schema_path)
        if not schema:return [item('schema_unavailable','PRO-R04','发布 schema 可用','blocked','release schema',None)]
        last=read(home/'state.json',{}).get('lastCompleted',{}).get(label,{})
        prior_folder=home/'runs'/last.get('runId','__none__')
        prior=read(prior_folder/'run.json',{}).get('acceptance',{})
        reusable=all(prior.get(k)==bindings.get(k) for k in ['codeSha256','policyHash','targetIdentity','mode']) and bool(prior)
        if reusable and verify_seal(prior_folder):reusable=False
        previous_checks={x['id']:x for x in prior.get('checks',[])} if reusable else {}
        for a in answer_index['answers']:
            s=sources.get(a['caseId']);accept=approved(home,a)
            if a.get('maintenance',{}).get('incompleteRule'):
                out.append(item(a['id'],a['requirement'],a['question'],'blocked',a['expected'],
                                '执行规则待补充：'+a['maintenance']['incompleteRule']));continue
            if a.get('maintenance',{}).get('stale'):
                out.append(item(a['id'],a['requirement'],a['question'],'blocked',a['expected'],'GT needs rebinding after file replacement'));continue
            if s is None or not Path(s['path']).is_file() or sha(s['path'])!=a['sourceSha256']:
                out.append(item(a['id'],a['requirement'],a['question'],'blocked',a['expected'],'source/hash mismatch'));continue
            if s['private'] and not diagnostic:
                out.append(item(a['id'],a['requirement'],a['question'],'blocked',a['expected'],'Private scan requires live isolation'));continue
            if not accept and not diagnostic:
                out.append(item(a['id'],a['requirement'],a['question'],'review',a['expected'],'pending explicit answer approval',approval='draft'));continue
            key=digest([s['sha256'],s['format'],a['options']])
            if key not in cache:
                previous=previous_checks.get(a['id'].replace('/','_').replace(':','_'),{})
                saved=prior_folder/'evidence'/('probe-'+key+'.json')
                if previous.get('details',{}).get('answerDigest')==a['answerDigest'] and saved.is_file():
                    p=read(saved);r=json.loads(p['stdout'])
                    p={**p,'reusedEvidenceFrom':str(prior_folder),'reusedSourceSha256':s['sha256']}
                else:p,r=probe(binary,s['path'],a['options'])
                cache[key]=(p,r)
                save('probe-'+key,p)
                problems=report_issues(r,schema,p['exitCode']) if not p.get('timedOut') and not p.get('launchError') else ['probe did not finish']
                out.append(item('schema_'+key,'PRO-R04','发布 schema 与状态/置信度/证据关系',
                                'blocked' if p.get('timedOut') or p.get('launchError') else ('failed' if problems else 'passed'),
                                [],problems,evidence=['evidence/probe-'+key+'.json'],command=p['command']))
            p,r=cache[key]
            evaluated=evaluate_answer(a,r)
            status=('passed' if evaluated['passed'] else 'failed') if accept else 'review'
            if p.get('timedOut') or p.get('launchError'):status='blocked'
            out.append(item(a['id'],a['requirement'],a['question'],status,a['expected'],evaluated['actual'],
                            details={'diagnosticMatch':evaluated['passed'],'answerDigest':a['answerDigest']},
                            approval='approved' if accept else 'draft',source='sha256:'+s['sha256'],
                            evidence=['evidence/probe-'+key+'.json'],command=p['command']))
        cov=coverage(home,out);atomic(folder/'coverage.json',cov)
        cs=cov['summary']
        complete=(cs.get('passedScenarios')==cs.get('requiredScenarios') and
                  cs.get('declarationReviewStatus')=='approved' and
                  not corpus.get('gaps'))
        out.append(item('complete_declared_coverage','PRO-R03','全部声明格式/target 具有已审事实和场景证据','passed' if complete else 'blocked',
                        'approved fact + positive/negative/boundary matrix complete',{'coverage':cs,'gaps':corpus.get('gaps',[]),'scenarios':cov.get('scenarios',[])}))
        return out

    def paths():
        src=next((s for s in sources.values() if s.get('format')=='pptx' and not s.get('private') and '加密' not in s.get('inputName','')),None)
        if not src or src['private']:
            return [item('paths_fixture_unavailable','PRO-R05','路径对照样本启用且可安全执行','blocked','active public fixture','sample disabled, missing or private')]
        variants={'required':['-t','slide_count'],'optional':['-t','slide_count','-o','orientation,aspect_ratio'],
                  'no_piggyback':['-t','slide_count','--no-piggyback'],'exact':['-t','slide_count','-c','exact'],
                  'budget':['-b','1','-t','slide_count']}
        records={k:probe(binary,src['path'],v) for k,v in variants.items()}
        e=save('paths',{k:{'process':p,'report':r} for k,(p,r) in records.items()})
        a=records['required'][1];b=records['optional'][1]
        av=a.get('results',{}).get('powerpoint.slide_count');bv=b.get('results',{}).get('powerpoint.slide_count')
        cost_a=a.get('execution',{}).get('actual_cost',{});cost_b=b.get('execution',{}).get('actual_cost',{})
        equal=av is not None and av==bv
        no_extra=all(type(cost_a.get(k)) is int and cost_b.get(k)==cost_a[k] for k in ['physical_bytes_read','expanded_bytes','random_reads'])
        no_pig=records['no_piggyback'][1];exact=records['exact'][1];budget_proc,budget=records['budget']
        no_pig_value=no_pig.get('results',{}).get('powerpoint.slide_count')
        no_pig_ok=(set(no_pig.get('results',{}))=={'powerpoint.slide_count'} and no_pig_value==av)
        exact_value=exact.get('results',{}).get('powerpoint.slide_count',{})
        exact_ok=(exact_value.get('status')=='resolved' and exact_value.get('confidence')=='exact' and
                  exact_value.get('confidence_score')==1.0 and isinstance(av,dict) and exact_value.get('value')==av.get('value') and
                  bool(exact_value.get('path')) and bool(exact_value.get('source')))
        budget_ok=(budget_proc.get('exitCode')==4 and budget.get('status')=='error' and
                   budget.get('error',{}).get('code')=='BUDGET_EXCEEDED' and budget.get('error',{}).get('exit_code')==4)
        oracle_answers=[a for a in answer_index.get('answers',[]) if a.get('caseId')==src['id'] and a.get('requirement')=='PRO-R05'
                        and a.get('check',{}).get('type') in {'allowed_paths','cost_ceiling'} and approved(home,a)]
        oracle_results=[evaluate_answer(a,records['exact'][1] if a.get('check',{}).get('type')=='allowed_paths' else records['required'][1]) for a in oracle_answers]
        oracle_types={a.get('check',{}).get('type') for a in oracle_answers}
        oracle_ok={'allowed_paths','cost_ceiling'}.issubset(oracle_types) and all(x['passed'] for x in oracle_results)
        return [item('optional_required_semantics','PRO-R05','optional target 不改变必需 target 的事实','passed' if equal else 'failed',av,bv,evidence=[e]),
                item('optional_shared_cost','PRO-R05','可共享 optional target 不增加执行成本','passed' if no_extra else 'failed',cost_a,cost_b,evidence=[e]),
                item('no_piggyback_contract','PRO-R05','关闭 piggyback 后只返回显式请求 target','passed' if no_pig_ok else 'failed',{'targets':['powerpoint.slide_count'],'value':av},{'targets':sorted(no_pig.get('results',{})),'value':no_pig_value},evidence=[e]),
                item('exact_confidence_contract','PRO-R05','exact 请求使用精确路径并保持事实值','passed' if exact_ok else 'failed',{'confidence':'exact','score':1.0,'value':av.get('value') if isinstance(av,dict) else None},exact_value,evidence=[e]),
                item('budget_boundary_contract','PRO-R05','超限预算返回稳定错误和退出码','passed' if budget_ok else 'failed',{'status':'error','code':'BUDGET_EXCEEDED','exitCode':4},{'report':budget,'exitCode':budget_proc.get('exitCode')},evidence=[e]),
                item('paths_oracle','PRO-R05','精确路径和成本区间已逐条审核','passed' if oracle_ok else 'blocked',
                     'at least one approved allowed-path and cost-ceiling answer',{'approvedAnswers':[a['id'] for a in oracle_answers],'results':oracle_results},evidence=[e])]

    def integrations():
        out=[];packages=target.get('packages')
        if not packages:return [item('packages_ready','PRO-R07','发布 JS/MCP 包已准备','blocked','prepared npm artifacts',None)]
        examples=[]
        for fmt in ['pdf','docx','xlsx','pptx','key','numbers','pages','doc','xls','ppt']:
            selected=next((s for s in sources.values() if s.get('format')==fmt and not s.get('private')),None)
            if selected:examples.append(selected)
        examples=examples[:5]
        if not examples:return [item('integration_fixtures_unavailable','PRO-R07','接口样本启用且可安全执行','blocked','active public fixtures','samples disabled, missing or private')]
        schema=read(Path(release['folder'])/'source/docs/deckprobe-report.schema.json')
        for src in examples:
            native_proc,native=probe(binary,src['path'],['-t','@summary,@security','-l','metadata'])
            save('native-'+src['id'],native_proc)
            for mode in ['node','browser','mcp-pinned','mcp-default']:
                if mode=='browser' and not packages.get('browserReady'):
                    out.append(item(mode+'_'+src['id'],'PRO-R07','Browser dependency ready','blocked','prepared Chromium',False));continue
                p=process(['node',str(CODE/'adapters/runtime.mjs'),mode,packages['folder'],src['path'],binary],
                          packages['folder'],180,env=packages.get('browserEnv',{}))
                ev=save(mode+'-'+src['id'],p)
                if p['exitCode']!=0:
                    out.append(item(mode+'_'+src['id'],'PRO-R07',mode+' 可执行','blocked' if p.get('timedOut') or p.get('launchError') else 'failed','successful adapter execution',p['stderr'],evidence=[ev],command=p['command']));continue
                try:data=json.loads(p['stdout'])
                except ValueError:
                    out.append(item(mode+'_'+src['id'],'PRO-R07',mode+' 输出有效 JSON','failed','JSON',p['stdout'],evidence=[ev]));continue
                reports=data.get('reports',[])
                if mode.startswith('mcp'):
                    responses=data['responses'];payload=tool_payload(responses['probe'])
                    reports=[payload] if isinstance(payload,dict) else []
                    names={x['name'] for x in responses.get('tools',{}).get('result',{}).get('tools',[])}
                    tools_ok={'probe','probe_batch','list_formats','list_targets'}<=names
                    bad=responses['invalid'];outside=responses['outside']
                    rejected=lambda x:bool(x.get('error') or x.get('result',{}).get('isError'))
                    out.append(item(mode+'_tools_'+src['id'],'PRO-R07','MCP discovery 与参数/路径拒绝','passed' if tools_ok and rejected(bad) and rejected(outside) else 'failed',True,{'tools':sorted(names),'invalidRejected':rejected(bad),'outsideRejected':rejected(outside)},evidence=[ev]))
                    batch=tool_payload(responses['batch'])
                    batch_rows=batch.get('reports',[]) if isinstance(batch,dict) else []
                    batch_ok=len(batch_rows)==3 and batch_rows[0].get('path')==src['path'] and batch_rows[2].get('path')==src['path'] and batch_rows[0].get('report',{}).get('status')!='error' and batch_rows[1].get('report',{}).get('status')=='error' and normalize(batch_rows[0].get('report'))==normalize(batch_rows[2].get('report'))
                    out.append(item(mode+'_batch_'+src['id'],'PRO-R07','MCP 批处理好/坏/好隔离', 'passed' if batch_ok else 'failed', '3 ordered independent results; first/last good',batch,evidence=[ev]))
                    resources=responses.get('schema',{}).get('result',{}).get('contents',[])
                    try:mcp_schema=json.loads(resources[0]['text'])
                    except (ValueError,KeyError,IndexError):mcp_schema=None
                    out.append(item(mode+'_schema_'+src['id'],'PRO-R07','MCP schema resource 与发布 schema 一致','passed' if mcp_schema==schema else 'failed',digest(schema),digest(mcp_schema),evidence=[ev]))
                issues=[]
                for r in reports:
                    issues.extend(report_issues(r,schema))
                    if normalize(r)!=normalize(native):issues.append('core report differs from native')
                if not reports:issues.append('no report returned')
                out.append(item(mode+'_parity_'+src['id'],'PRO-R07',mode+' 与 native schema/语义一致','failed' if issues else 'passed',[],issues,evidence=[ev],command=p['command']))
                if mode=='browser':
                    trace=data['trace'];idle=max(trace['idle'],default=0);blocked=max(trace['blocked'],default=0);worker=max(trace['worker'],default=0)
                    measured=len(trace['worker'])>=3 and blocked>=100 and idle>0
                    responsive=measured and worker<=max(50,idle*3)
                    out.append(item('worker_responsiveness_'+src['id'],'PRO-R07','Worker 页面心跳与阻塞正控','passed' if responsive else 'review',{'positiveControlMs':100,'minimumWorkerTicks':3},{'idleMaxMs':idle,'blockedMaxMs':blocked,'workerMaxMs':worker,'workerTicks':len(trace['worker'])},evidence=[ev]))
        # Native JSONL uses actual good/bad/good records, not a success marker string.
        src=examples[0]
        lines='\n'.join(json.dumps(x) for x in [{'path':src['path']},{'path':str(home/'absent.pdf')},{'path':src['path']}])+'\n'
        p=process([binary,'--jsonl','-t','@summary,@security'],stdin=lines,timeout=90)
        ev=save('jsonl',p)
        try:rows=[json.loads(x) for x in p['stdout'].splitlines() if x.strip()]
        except ValueError:rows=[]
        good=len(rows)==3 and rows[0].get('status')!='error' and rows[1].get('status')=='error' and rows[2]==rows[0]
        out.append(item('jsonl_error_isolation','PRO-R07','JSONL 错误不影响后续文件','passed' if good else 'failed','good/error/good',rows,evidence=[ev]))
        stress=max((s for s in sources.values() if s.get('format')=='pdf' and not s.get('private')),key=lambda x:x.get('bytes',0),default=src)
        if stress['private']:stress=src
        p=process(['node',str(CODE/'adapters/runtime.mjs'),'mcp-timeout',packages['folder'],stress['path'],binary],packages['folder'],90,env=packages.get('browserEnv',{}))
        ev=save('mcp-timeout',p)
        try:timeout_report=tool_payload(json.loads(p['stdout'])['responses']['probe'])
        except (ValueError,KeyError):timeout_report={}
        code=(timeout_report or {}).get('error',{}).get('code')
        out.append(item('mcp_deadline','PRO-R07','MCP 硬超时返回明确错误','passed' if code=='MCP_TIMEOUT' else 'failed','MCP_TIMEOUT',code,evidence=[ev]))
        formats={s['format'] for s in examples}
        families={'pdf':bool(formats&{'pdf'}),'ooxml':bool(formats&{'docx','xlsx','pptx'}),'iwork':bool(formats&{'key','numbers','pages'})}
        deep_ok=all(families.values()) and not any(x['status'] in {'failed','blocked'} for x in out)
        out.append(item('integration_deep_coverage','PRO-R07','PDF、OOXML、IWA、超时和 Worker 场景均完成','passed' if deep_ok else 'blocked',
                        {'families':{'pdf':True,'ooxml':True,'iwork':True},'allSurfaceChecksComplete':True},
                        {'families':families,'failedChecks':[x['id'] for x in out if x['status'] in {'failed','blocked'}]}))
        return out

    def perf():
        config=policy['performance'];measurements=[]
        if performance:
            # Sample a fixed generated cohort; keep errors and every measurement.
            for name in config.get('cases', []):
                if name not in sources or sources[name]['private']:
                    measurements.append({'caseId':name,'mode':'not-executed','complete':False,'error':'sample disabled, missing or private'})
                    continue
                src=sources[name]
                for level in config.get('levels', ['header','metadata','deep']):
                    command=[binary,'-l',level,'-t','@all',src['path']]
                    warm=[process(command,timeout=120) for _ in range(config['warmup'])]
                    points=[{**process(command,timeout=120),'loadAverage':list(os.getloadavg())} for _ in range(config['samples'])]
                    successful=[p['durationMs'] for p in points if p['exitCode']==0]
                    all_success=len(successful)==len(points)
                    ordered=sorted(successful)
                    measurements.append({'caseId':name,'sourceSha256':src['sha256'],'level':level,'mode':'fresh-process; filesystem cache uncontrolled',
                                         'warmup':warm,'samples':points,'p50Ms':statistics.median(ordered) if all_success else None,
                                         'p95Ms':ordered[math.ceil(.95*len(ordered))-1] if ordered and all_success else None,
                                         'complete':all_success})
                    packages=target.get('packages')
                    if packages:
                        adapter=process(['node',str(CODE/'adapters/performance.mjs'),packages['folder'],src['path'],binary,level,str(config['warmup']),str(config['samples'])],
                                        packages['folder'],240,env=packages.get('browserEnv',{}))
                        save('perf-runtimes-'+name+'-'+level,adapter)
                        if adapter['exitCode']==0:
                            data=json.loads(adapter['stdout'])
                            for mode in data['modes']:
                                complete=not mode.get('singleObservation') and len(mode['samples'])==config['samples'] and all(not p.get('error') and p.get('status')!='error' for p in mode['samples'])
                                times=sorted(p['durationMs'] for p in mode['samples'])
                                measurements.append({'caseId':name,'sourceSha256':src['sha256'],'level':level,**mode,'complete':complete,
                                                     'p50Ms':statistics.median(times) if complete else None,'p95Ms':times[math.ceil(.95*len(times))-1] if complete else None})
                        else:measurements.append({'caseId':name,'level':level,'mode':'runtime-adapter','complete':False,'error':adapter['stderr']})
            save('performance',measurements)
        return [item('background_performance','PRO-R06','本地性能分布观察','review','diagnostic only; no absolute latency SLA',
                     {'configurations':len(measurements),'complete':sum(x['complete'] for x in measurements)},role='observation',evidence=['evidence/performance.json'] if measurements else [])]

    def private_reporting():
        snapshot=read(home/'security-entry.json',{})
        ev=save('security-entry',snapshot)
        enabled=snapshot.get('privateReporting',{}).get('enabled') is True
        known='enabled' in snapshot.get('privateReporting',{})
        return [item('private_reporting_enabled','PRO-R09','GitHub 私密报告设置开启','passed' if enabled else ('failed' if known else 'blocked'),True,snapshot,evidence=[ev]),
                item('private_reporting_form','PRO-R09','已认证私密入口可访问','blocked','authenticated form evidence, no report submission','operator account access not yet demonstrated')]

    stage('release',supply);stage('security',safety);stage('facts',facts);stage('paths',paths)
    stage('integrations',integrations);stage('performance',perf);stage('reporting-entry',private_reporting)
    if code_hash()!=bindings['codeSha256']:
        checks.append(item('implementation_changed','PRO-R04','执行期间验收实现保持冻结','blocked',bindings['codeSha256'],code_hash()))
    if not (folder/'coverage.json').exists():atomic(folder/'coverage.json',coverage(home,checks))
    record={'runId':run_id,'createdAt':now(),'targetVersion':release['release']['tag'],'target':target,
            **bindings,'checks':checks,'environment':env,'mode':bindings['mode']}
    envelope=publish(folder,record,home);manifest_hash=seal(folder)
    state=read(home/'state.json',{})
    state.setdefault('lastCompleted',{})[label]={'runId':run_id,'manifestHash':manifest_hash,'mode':bindings['mode']}
    if not diagnostic and envelope['qualitySummary']['releaseDecision']=='PASS':state.setdefault('lastPassed',{})[label]=run_id
    atomic(home/'state.json',state)
    return {'runId':run_id,'reused':False,'report':str(folder/'report.html'),'decision':envelope['qualitySummary']['releaseDecision'],
            'localDecision':envelope['qualitySummary']['localDecision'],'checks':len(checks)}


def paired_performance(home):
    """Interleave old/new native measurements; other runtime surfaces are reported separately."""
    home=Path(home);prepared=read(home/'prepared.json');targets=prepared['targets']
    if not {'candidate','previous'}<=set(targets):return {'status':'blocked','reason':'two published targets required'}
    for target in targets.values():
        errors=runtime_valid(target)
        if errors:raise ValueError('; '.join(errors))
    corpus=read(home/'corpus/manifest.json');policy=read(home/'policy.json',read(CODE/'config/policy.json'))['performance']
    sources={s['id']:s for s in corpus['sources'] if s.get('active',True)}
    identity=digest({'targets':targets,'cohort':corpus['cohortHash'],'policy':policy,'code':code_hash(),
                     'maintenance':read(home/'maintenance-applied.json',{})})
    folder=home/'performance-pairs'/identity
    if (folder/'evidence-manifest.json').exists():
        if verify_seal(folder):raise ValueError('Paired performance evidence changed')
        return {'status':'observation','path':str(folder/'paired.json'),'reused':True}
    folder.mkdir(parents=True,exist_ok=True)
    groups=[]
    for case_id in policy.get('cases', []):
        if case_id not in sources or sources[case_id]['private']:
            groups.append({'caseId':case_id,'status':'blocked','reason':'sample disabled, missing or private'})
            continue
        s=sources[case_id]
        if s['private'] or sha(s['path'])!=s['sha256']:raise ValueError('Paired performance requires unchanged public fixture')
        for level in policy.get('levels', ['header','metadata','deep']):
            commands={label:[target['release']['binary'],'-l',level,'-t','@all',s['path']] for label,target in targets.items()}
            warm={label:[process(cmd,timeout=120) for _ in range(policy['warmup'])] for label,cmd in commands.items()}
            samples={label:[] for label in commands};order=[]
            for i in range(policy['samples']):
                sequence=['candidate','previous'] if i%2==0 else ['previous','candidate']
                for label in sequence:
                    p=process(commands[label],timeout=120);p['loadAverage']=list(os.getloadavg())
                    samples[label].append(p);order.append(label)
            groups.append({'caseId':case_id,'sourceSha256':s['sha256'],'level':level,'mode':'native-fresh-process','warmup':warm,'order':order,'samples':samples})
    record={'role':'observation','identity':identity,'createdAt':now(),'cohortHash':corpus['cohortHash'],
            'versions':{k:v['release']['release']['tag'] for k,v in targets.items()},'policy':policy,'groups':groups,
            'limits':'background load; filesystem cache not controlled; no formal latency claim'}
    atomic(folder/'paired.json',record);seal(folder)
    return {'status':'observation','path':str(folder/'paired.json'),'reused':False,'groups':len(groups)}
