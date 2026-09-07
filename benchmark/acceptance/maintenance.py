"""DeckProbe adapter for the independent Casework module.

All product-specific import, validation and execution export live here.
"""
from pathlib import Path
import copy
import sys

from .common import ROOT, DEFAULT_HOME, atomic, digest, immutable, locked, read, sha
from .review_view import describe, render_grouped_review


def modules():
    location=str(ROOT/'casework')
    if location not in sys.path:sys.path.insert(0,location)
    from casework.store import Store
    from casework.server import serve
    return Store,serve


def initialize(home, manager_home=None, project_id=None):
    home=Path(home).resolve();manager_home=Path(manager_home or home/'casework').resolve()
    Store,_=modules();store=Store(manager_home)
    configured=read(home/'maintenance.json',{})
    project_id=project_id or configured.get('project') or 'deckprobe'
    if not any(p['id']==project_id for p in store.projects()):
        if project_id!='deckprobe':
            raise ValueError('Casework 项目不存在：'+project_id)
        corpus=read(home/'corpus/manifest.json');index=read(home/'answers/index.json')
        if not corpus or not index:raise ValueError('请先完成验收样本准备')
        by_source={}
        for a in index['answers']:by_source.setdefault(a['caseId'],[]).append(a)
        state=read(home/'state.json',{}).get('lastCompleted',{}).get('candidate',{})
        run=read(home/'runs'/state.get('runId','__none__')/'run.json',{}).get('acceptance',{})
        checks={c['id']:c for c in run.get('checks',[])}
        samples=[]
        for source in corpus['sources']:
            s=copy.deepcopy(source);s['sourceRecord']=copy.deepcopy(source)
            s['inputName']=Path(s['path']).name;s['location']=s['provenance'].get('uri') or s['path']
            first=next(iter(by_source.get(s['id'],[])),None)
            s['title']=(describe(first,s)['sample']+' · '+s['format'].upper()) if first else Path(s['location']).name
            s['answers']=[]
            for a in by_source.get(s['id'],[]):
                view=describe(a,s);raw=checks.get(a['id'].replace('/','_').replace(':','_'))
                item={k:copy.deepcopy(a[k]) for k in ['id','question','expected','evidence','check','options','requirement']}
                item.update(payload=copy.deepcopy(a),display=view)
                if raw and raw.get('details',{}).get('answerDigest')==a['answerDigest']:
                    item['lastResult']={'runId':run['runId'],'actual':raw.get('actual'),'status':raw['status'],
                                        'matchesDraft':raw.get('details',{}).get('diagnosticMatch'),'answerDigest':a['answerDigest']}
                s['answers'].append(item)
            samples.append(s)
        store.import_bundle({'schemaVersion':1,'project':{'id':'deckprobe','name':'DeckProbe 发布验收',
            'samples':samples,'adapter':'deckprobe-acceptance-v1','gaps':corpus.get('gaps',[])}})
    atomic(home/'maintenance.json',{'module':'casework','home':str(manager_home),'project':project_id,'version':1})
    return store


def validate(a):
    check=a['check'];kind=check.get('type')
    if kind not in {'target','status','error','allowed_paths','cost_ceiling'}:raise ValueError(a['id']+'：不支持的检查类型')
    if kind in {'target','status','allowed_paths'} and not isinstance(check.get('target'),str):raise ValueError(a['id']+'：请填写 target')
    if kind in {'target','status','allowed_paths'} and not check.get('target','').strip():raise ValueError(a['id']+'：target 不能为空')
    if kind in {'status','error'} and not isinstance(a['expected'],str):raise ValueError(a['id']+'：状态或错误码必须是文字')
    if kind=='allowed_paths' and not isinstance(a['expected'],list):raise ValueError(a['id']+'：允许路径必须是列表')
    if kind=='cost_ceiling' and (not isinstance(a['expected'],dict) or any(type(v) is not int or v<0 for v in a['expected'].values())):raise ValueError(a['id']+'：成本上限必须是非负整数对象')
    if a.get('requirement') not in {'PRO-R03','PRO-R04','PRO-R05'}:raise ValueError(a['id']+'：GT 要求编号需为 PRO-R03、PRO-R04 或 PRO-R05')


def apply_project(home,p):
    """Caller holds the acceptance execution lock. Prepare and run use this view."""
    home=Path(home);sources=[];answers=[];decisions=[];facts=[]
    for s in p['samples']:
        source=copy.deepcopy(s.get('sourceRecord',{}))
        source.update({k:s[k] for k in ['id','format','path','sha256','bytes','private','active']})
        source.setdefault('provenance',{'type':'managed-local','uri':s['location']})
        if s.get('replacement'):
            source['provenance']={'type':'managed-replacement','uri':s['location'],
                                  'replacement':s['replacement'],'previousProvenance':source['provenance']}
        source['maintenance']={'version':s['version'],'inputName':s['inputName'],'location':s['location']}
        if s.get('purpose'):source['purpose']=copy.deepcopy(s['purpose'])
        sources.append(source)
        for original in s['answers']:
            a=copy.deepcopy(original)
            scope=p.get('answerScopes',{}).get(a['id'],{'mode':'case'})
            if a.get('kind')=='fact':
                mapping=p.get('mappings',{}).get(a['id'],{'status':'unmapped'})
                facts.append({'sampleId':s['id'],'active':s['active'],'fact':original,'mapping':mapping,'scope':scope})
                if mapping.get('status')!='mapped':continue
                a.update(check=mapping['check'],options=mapping.get('options',[]),requirement=mapping.get('requirement','PRO-R03'))
                a['managed']=True
            if not s['active'] or scope.get('mode')=='reference':continue
            rule_error=None
            try:validate(a)
            except ValueError as error:rule_error=str(error)
            if a.get('kind')=='fact' and a.get('valueState')!='known':rule_error='事实尚无可比较的已知值：'+a.get('valueState','unknown')
            body=copy.deepcopy(a.get('payload',{}));body.pop('answerDigest',None)
            if a.get('managed') or not body:
                body.update({k:copy.deepcopy(a.get(k)) for k in ['id','question','expected','evidence','check','options','requirement']})
                body.update(caseId=s['id'],sourceSha256=a['binding']['sha256'],format=a['binding']['format'],reviewStatus='draft',
                            maintenance={'revision':a['revision'],'contentDigest':a['digest'],'inputName':a['binding']['inputName'],
                                         'stale':a['status']=='stale'})
            if rule_error:
                body.setdefault('maintenance',{})['incompleteRule']=rule_error
                if body.get('requirement') not in {'PRO-R03','PRO-R04','PRO-R05'}:
                    body['requirement']='PRO-R03'
            if a.get('kind')=='fact':
                body['factReference']={'id':a['id'],'digest':a['digest'],'definition':a.get('definition'),
                                       'mapping':mapping}
            body['answerDigest']=digest(body);answers.append(body)
            if not rule_error and a['status']=='approved' and a.get('review',{}).get('digest')==a['digest']:
                if a['binding']!={k:s[k] for k in ['sha256','format','inputName']}:raise ValueError('已批准答案与当前文件不匹配')
                if not Path(s['path']).is_file() or sha(s['path'])!=s['sha256']:raise ValueError('已批准样本不可读取或哈希变化')
                decisions.append({'id':a['id'],'answerDigest':body['answerDigest'],'decision':'approved',
                                  'reviewer':a['review']['actor'],'recordedAt':a['review']['at'],'note':a['review']['note']})
    manifest={'version':'1','sources':sources,'gaps':p.get('gaps',[]),'incidents':[],
              'maintenanceRevision':p['revision'],'cohortHash':digest(sorted((s['id'],s['sha256']) for s in sources))}
    # Finish validation before touching the execution view. Historic objects are immutable.
    for a in answers:immutable(home/'answers/objects'/(a['answerDigest']+'.json'),a)
    for d in decisions:immutable(home/'answers/decisions'/(d['answerDigest']+'.json'),d)
    # Revisions are only unique inside one Casework project.
    immutable(home/'managed-inputs'/p['id']/('revision-'+str(p['revision'])+'.json'),p)
    atomic(home/'corpus/manifest.json',manifest);atomic(home/'answers/index.json',{'version':'1','answers':answers})
    atomic(home/'facts/index.json',{'version':2,'facts':facts,'summary':{
        'total':len(facts),'approved':sum(x['fact']['status']=='approved' for x in facts),
        'known':sum(x['fact'].get('valueState')=='known' for x in facts),
        'mapped':sum(x['mapping'].get('status')=='mapped' and x['scope'].get('mode')!='reference' for x in facts),
        'inCase':sum(x['scope'].get('mode')!='reference' for x in facts),
        'reference':sum(x['scope'].get('mode')=='reference' for x in facts)}})
    render_grouped_review(home)
    atomic(home/'maintenance-applied.json',{'revision':p['revision'],'answers':len(answers),'samples':len(sources)})
    return {'message':f'已同步 {len(sources)} 份样本、{len(answers)} 条启用样本的 GT。历史报告未改动。','revision':p['revision']}


def sync(home):
    config=read(Path(home)/'maintenance.json')
    if not config:return False
    Store,_=modules();store=Store(config['home'])
    apply_project(home,store.get(config['project']))
    return True


def run_server(home=DEFAULT_HOME,port=8767):
    home=Path(home).resolve()
    with locked(home):
        store=initialize(home)
        config=read(home/'maintenance.json');config['url']=f'http://127.0.0.1:{port}'
        atomic(home/'maintenance.json',config)
        config=read(home/'maintenance.json')
        apply_project(home,store.get(config['project']))
    _,serve=modules()
    def apply(p):
        with locked(home):return apply_project(home,p)
    serve(store.home,port,on_apply=apply,default_project=config['project'])
