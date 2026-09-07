from __future__ import annotations
import argparse
import json
from pathlib import Path
import shutil
import sys
import urllib.error

if hasattr(sys.stdout, "reconfigure"):
    try: sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception: pass
if hasattr(sys.stderr, "reconfigure"):
    try: sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception: pass

from .common import CODE, DEFAULT_HOME, atomic, code_hash, digest, locked, now, process, read, sha, verify_seal
from .corpus import prepare_corpus, record_decisions
from .coverage import capture_catalog
from .releases import api, discover, download_release, prepare_packages
from .runner import run, paired_performance
from .security import doctor
from .reporting import compare, rebuild
from .supply_evidence import refresh_signature_audit
from .review_view import render_grouped_review
from .ci_snapshot import export_snapshot, validate_snapshot
from .github_ci import (aggregate as ci_aggregate, freeze as ci_freeze, platform_smoke,
                        publish_history, run_main, run_performance, verdict as ci_verdict)


def input_fingerprint(home):
    corpus=read(Path(home)/'corpus/manifest.json',{'sources':[]})
    current={s['id']:sha(s['path']) if Path(s['path']).is_file() else None for s in corpus['sources']}
    return digest({'code':code_hash(),'sources':current,'manifest':corpus,
                   'answers':read(Path(home)/'answers/index.json'),
                   'decisions':{p.name:sha(p) for p in (Path(home)/'answers/decisions').glob('*.json')},
                   'declarations':read(Path(home)/'declarations.json'),
                   'environment':doctor(home)})


def check(home):
    identity,discovery=discover(home)
    fingerprint=digest({'release':identity,'assets':input_fingerprint(home)})
    state=read(Path(home)/'state.json',{})
    changed=state.get('lastHandledFingerprint')!=fingerprint
    result={'checkedAt':now(),'fingerprint':fingerprint,'changed':changed,'release':discovery['candidate']['tag'],
            'reason':'new release, asset, corpus, rule, approval or environment' if changed else 'unchanged',
            'shouldNotify':False}
    atomic(Path(home)/'last-check.json',result)
    return result


def refresh_attestations(release):
    gh=shutil.which('gh');items=[]
    for a in release['assets']:
        if not (a['name'].startswith('deckprobe-') and a['name'].endswith(('.tar.gz','.zip'))):continue
        if gh:
            try:
                bundles=api('https://api.github.com/repos/'+release['release']['repository']+'/attestations/sha256:'+a['sha256'])
                bundle_file=Path(release['folder'])/'attestations'/(a['name']+'.jsonl')
                atomic(bundle_file,''.join(json.dumps(x['bundle'])+'\n' for x in bundles.get('attestations',[])))
                if not bundles.get('attestations'):raise ValueError('No published attestations for this artifact')
                p=process([gh,'attestation','verify',str(Path(release['folder'])/a['name']),
                           '--bundle',str(bundle_file),'--repo',release['release']['repository'],
                           '--source-digest',release['release']['commit'],'--format','json'],timeout=90)
                status='passed' if p['exitCode']==0 else ('blocked' if p.get('timedOut') or p.get('launchError') else 'failed')
                items.append({'asset':a['name'],'status':status,'bundlePath':str(bundle_file),'bundleSha256':sha(bundle_file),**p})
            except (OSError,ValueError) as e:
                items.append({'asset':a['name'],'status':'blocked','reason':str(e)})
        else:items.append({'asset':a['name'],'status':'blocked','reason':'gh is not installed'})
    atomic(Path(release['folder'])/'attestation-refresh.json',items)
    return items


def prepare(home,online=False,with_previous=True):
    from .maintenance import sync
    managed=sync(home)
    corpus={'managed':True,'note':'样本与答案由 Casework 维护'} if managed else prepare_corpus(home,online=online)
    render_grouped_review(home)
    if not online:return {'corpus':corpus,'offline':True,'note':'Existing acquisition lock preserved; use --online to acquire releases'}
    _,data=discover(home)
    records={}
    for label in (['candidate','previous'] if with_previous else ['candidate']):
        if not data.get(label):continue
        release=download_release(home,data[label]);refresh_attestations(release)
        packages=prepare_packages(home,data,release)
        refresh_signature_audit(packages)
        records[label]={'release':release,'packages':packages}
    prepared={'discovery':data,'targets':records}
    atomic(Path(home)/'prepared.json',prepared)
    for label in reversed(list(records)):capture_catalog(home,records[label])
    sec={'checkedAt':now(),'repository':data['candidate']['repository']}
    try:sec['privateReporting']=api('https://api.github.com/repos/'+sec['repository']+'/private-vulnerability-reporting')
    except (OSError,ValueError) as e:sec['blocked']=str(e)
    atomic(Path(home)/'security-entry.json',sec)
    return {'corpus':corpus,'releases':{k:v['release']['release']['tag'] for k,v in records.items()},'securityEntry':sec,
            'review':str(Path(home)/'answers/review.html')}


def weekly(home):
    result=check(home)
    if not result['changed']:return result
    prior=read(Path(home)/'state.json',{}).get('lastWeeklyCandidate')
    prepare(home,online=True)
    outputs=[]
    for label in read(Path(home)/'prepared.json')['targets']:
        outputs.append(run(home,label=label,diagnostic=False,performance=True))
    paired=paired_performance(home)
    if len(outputs)==2:
        dest=Path(home)/'comparisons'/(outputs[1]['runId']+'--'+outputs[0]['runId'])
        if not dest.exists():compare(Path(home)/'runs'/outputs[1]['runId'],Path(home)/'runs'/outputs[0]['runId'],dest)
    weekly_comparison=None
    if prior:
        prior_folder=Path(home)/'runs'/prior
        errors=verify_seal(prior_folder)
        if errors:raise ValueError('; '.join(errors))
        # Re-evaluate the last weekly frozen component combination under today's rules.
        old_target=read(prior_folder/'run.json')['acceptance']['target']
        baseline=run(home,label='weekly-baseline',diagnostic=False,performance=True,target_override=old_target)
        dest=Path(home)/'comparisons'/('weekly-'+baseline['runId']+'--'+outputs[0]['runId'])
        if not dest.exists():compare(Path(home)/'runs'/baseline['runId'],Path(home)/'runs'/outputs[0]['runId'],dest)
        weekly_comparison=str(dest/'comparison.html')
    state=read(Path(home)/'state.json',{})
    # Mark handled only after comparison has also completed successfully.
    snapshot=read(Path(home)/'discovery.json')['id']
    state['lastHandledFingerprint']=digest({'release':snapshot,'assets':input_fingerprint(home)})
    state['lastWeeklyCandidate']=outputs[0]['runId']
    atomic(Path(home)/'state.json',state)
    return {'changed':True,'shouldNotify':True,'runs':outputs,'pairedPerformance':paired,'weeklyComparison':weekly_comparison,'pendingAnswers':str(Path(home)/'answers/review.html')}


def main(argv=None):
    parser=argparse.ArgumentParser(description='Acceptance of released DeckProbe artifacts; no development binary fallback')
    parser.add_argument('--home',type=Path,default=DEFAULT_HOME)
    sub=parser.add_subparsers(dest='command',required=True)
    sub.add_parser('check');sub.add_parser('doctor');sub.add_parser('weekly');sub.add_parser('performance-pair')
    manage=sub.add_parser('manage');manage.add_argument('--port',type=int,default=8767)
    dataset=sub.add_parser('dataset');dataset_sub=dataset.add_subparsers(dest='dataset_command',required=True)
    dataset_import=dataset_sub.add_parser('import');dataset_import.add_argument('--source',type=Path,required=True)
    dataset_import.add_argument('--project',default='deckprobe-format-dataset')
    claims=sub.add_parser('claims');claims_sub=claims.add_subparsers(dest='claims_command',required=True)
    claims_prepare=claims_sub.add_parser('prepare');claims_prepare.add_argument('--catalog',type=Path,required=True)
    claims_approve=claims_sub.add_parser('approve');claims_approve.add_argument('--digest',required=True);claims_approve.add_argument('--reviewer',required=True)
    claims_bind=claims_sub.add_parser('bind-scenario');claims_bind.add_argument('--scenario',required=True);claims_bind.add_argument('--answer',action='append',required=True)
    claims_sub.add_parser('review-digest')
    prep=sub.add_parser('prepare');prep.add_argument('--online',action='store_true');prep.add_argument('--candidate-only',action='store_true')
    execute=sub.add_parser('run');execute.add_argument('--target',choices=['candidate','previous'],default='candidate')
    execute.add_argument('--diagnostic',action='store_true');execute.add_argument('--performance',action='store_true')
    approval=sub.add_parser('approve',help='Import explicitly reviewed per-answer decisions; never call to auto-approve')
    approval.add_argument('--decisions',type=Path,required=True)
    cmp=sub.add_parser('compare');cmp.add_argument('--before',type=Path,required=True);cmp.add_argument('--after',type=Path,required=True);cmp.add_argument('--output',type=Path,required=True)
    rep=sub.add_parser('report');rep.add_argument('--run',type=Path,required=True);rep.add_argument('--output',type=Path,required=True)
    snapshot=sub.add_parser('snapshot');snapshot_sub=snapshot.add_subparsers(dest='snapshot_command',required=True)
    snapshot_export=snapshot_sub.add_parser('export');snapshot_export.add_argument('--output',type=Path,required=True);snapshot_export.add_argument('--allow-draft',action='store_true')
    snapshot_validate=snapshot_sub.add_parser('validate');snapshot_validate.add_argument('--snapshot',type=Path,required=True);snapshot_validate.add_argument('--allow-draft',action='store_true')
    freeze_cmd=sub.add_parser('freeze');freeze_cmd.add_argument('--snapshot',type=Path,required=True);freeze_cmd.add_argument('--output',type=Path,required=True)
    freeze_cmd.add_argument('--release-tag');freeze_cmd.add_argument('--history',type=Path);freeze_cmd.add_argument('--force',action='store_true')
    main_cmd=sub.add_parser('run-main');main_cmd.add_argument('--lock',type=Path,required=True);main_cmd.add_argument('--snapshot',type=Path,required=True);main_cmd.add_argument('--output',type=Path,required=True)
    security_cmd=sub.add_parser('run-security-linux');security_cmd.add_argument('--lock',type=Path,required=True);security_cmd.add_argument('--snapshot',type=Path,required=True);security_cmd.add_argument('--output',type=Path,required=True)
    perf_cmd=sub.add_parser('run-performance');perf_cmd.add_argument('--lock',type=Path,required=True);perf_cmd.add_argument('--snapshot',type=Path,required=True);perf_cmd.add_argument('--output',type=Path,required=True)
    platform_cmd=sub.add_parser('run-platform');platform_cmd.add_argument('--lock',type=Path,required=True);platform_cmd.add_argument('--snapshot',type=Path,required=True);platform_cmd.add_argument('--platform',required=True);platform_cmd.add_argument('--output',type=Path,required=True)
    aggregate_cmd=sub.add_parser('aggregate');aggregate_cmd.add_argument('--lock',type=Path,required=True);aggregate_cmd.add_argument('--inputs',type=Path,required=True);aggregate_cmd.add_argument('--output',type=Path,required=True)
    history_cmd=sub.add_parser('publish-history');history_cmd.add_argument('--run',type=Path,required=True);history_cmd.add_argument('--site',type=Path,required=True);history_cmd.add_argument('--comparison',type=Path)
    site_cmd=sub.add_parser('build-site');site_cmd.add_argument('--run',type=Path,required=True);site_cmd.add_argument('--site',type=Path,required=True)
    verdict_cmd=sub.add_parser('verdict');verdict_cmd.add_argument('--run',type=Path,required=True)
    args=parser.parse_args(argv);home=args.home.expanduser().resolve()
    try:
        if args.command=='manage':
            from .maintenance import run_server
            run_server(home,args.port)
            return 0
        with locked(home):
            if args.command=='dataset':
                from .dataset_onboarding import onboard
                result=onboard(args.source,home,args.project)
            elif args.command=='claims':
                from .declaration_matrix import prepare as prepare_claims,approve as approve_claims,bind_scenario,review_digest
                if args.claims_command=='prepare':result=prepare_claims(home,args.catalog)
                elif args.claims_command=='approve':result=approve_claims(home,args.digest,args.reviewer)
                elif args.claims_command=='bind-scenario':result=bind_scenario(home,args.scenario,args.answer)
                else:result={'digest':review_digest(home)}
            elif args.command=='snapshot':
                if args.snapshot_command=='export':
                    from .maintenance import sync
                    sync(home)
                    result=export_snapshot(home,args.output,args.allow_draft)
                else:
                    errors=validate_snapshot(args.snapshot,require_ready=not args.allow_draft)
                    result={'valid':not errors,'errors':errors}
                    if errors:raise ValueError('; '.join(errors))
            elif args.command=='freeze':result=ci_freeze(args.snapshot,args.output,args.release_tag,args.history,args.force)
            elif args.command=='run-main':result=run_main(args.lock,args.snapshot,home,args.output)
            elif args.command=='run-security-linux':
                from .linux_security import run_security
                result=run_security(args.lock,args.snapshot,home,args.output)
            elif args.command=='run-performance':result=run_performance(args.lock,args.snapshot,home,args.output)
            elif args.command=='run-platform':result=platform_smoke(args.lock,args.snapshot,args.platform,args.output)
            elif args.command=='aggregate':result=ci_aggregate(args.lock,args.inputs,args.output)
            elif args.command=='publish-history':result=publish_history(args.run,args.site,args.comparison)
            elif args.command=='build-site':result=publish_history(args.run,args.site)
            elif args.command=='verdict':
                result=ci_verdict(args.run)
                print(json.dumps(result,ensure_ascii=False,indent=2))
                return 0 if result['success'] else 1
            elif args.command in {'check','run','weekly','performance-pair'}:
                from .maintenance import sync
                sync(home)
                if args.command=='check':result=check(home)
                elif args.command=='weekly':result=weekly(home)
                elif args.command=='performance-pair':result=paired_performance(home)
                else:result=run(home,args.target,args.diagnostic,args.performance)
            elif args.command=='prepare':result=prepare(home,args.online,not args.candidate_only)
            elif args.command=='doctor':result=doctor(home)
            elif args.command=='approve':
                if read(home/'maintenance.json'):
                    raise ValueError('当前已启用 Casework，请在管理页面记录审批，避免两套审批源冲突')
                record_decisions(home,args.decisions)
                from .corpus import render_review
                render_review(home,read(home/'corpus/manifest.json'),read(home/'answers/index.json')['answers'],read(home/'corpus/legacy-review.json',[]))
                render_grouped_review(home)
                result={'decisionsImported':True}
            elif args.command=='compare':
                compared=compare(args.before,args.after,args.output)
                result={'comparable':compared['comparable'],'guardDifferences':compared['guardDifferences'],
                        'changes':len(compared['changes']),'performanceComparisons':len(compared['performance']),
                        'report':str(args.output.resolve()/'comparison.html')}
            else:result={'report':rebuild(args.run,args.output)}
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return 0
    except (OSError,ValueError,RuntimeError) as e:
        print(json.dumps({'status':'blocked','error':str(e)},ensure_ascii=False),file=sys.stderr)
        return 2


if __name__=='__main__':sys.exit(main())
