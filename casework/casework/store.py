from __future__ import annotations

import base64
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
from datetime import datetime, timezone
from uuid import uuid4
from .facts import fact_fields, migrate_project, validate_mapping


class Conflict(ValueError):
    pass


def now():
    return datetime.now(timezone.utc).isoformat()


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(encoded(value).encode()).hexdigest()


def sha(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def answer_digest(answer):
    if answer.get('factVersion')==2:
        return digest({k:answer.get(k) for k in ['id','kind','factKey','definition','valueState','question','expected','evidence','binding']})
    return digest({k: answer.get(k) for k in ['id','question','expected','evidence','check','options','requirement','binding']})


def binding(sample):
    return {k: sample[k] for k in ['sha256','format','inputName']}


def validate_answer(a):
    if not isinstance(a.get('question'), str) or not a['question'].strip():
        raise ValueError('请填写测试问题')
    if 'expected' not in a:
        raise ValueError('请填写预期答案')
    a.setdefault('check',{});a.setdefault('evidence',{});a.setdefault('options',[]);a.setdefault('requirement','')
    if not isinstance(a['check'],dict):raise ValueError('检查定义必须是 JSON 对象')
    if not isinstance(a.get('evidence'), dict) or not isinstance(a.get('options',[]),list):
        raise ValueError('依据必须是对象，请求参数必须是列表')
    if not all(isinstance(v,str) for v in a.get('options',[])):
        raise ValueError('请求参数必须逐项为字符串')
    encoded(a)


class Store:
    """SQLite transactions + immutable project snapshots. No business evaluator."""
    def __init__(self, home):
        self.home = Path(home).expanduser().resolve()
        self.home.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db = self.home/'casework.sqlite3'
        with self.connect() as c:
            c.executescript('''
                CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY, revision INTEGER NOT NULL, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS history(project TEXT NOT NULL, revision INTEGER NOT NULL,
                    at TEXT NOT NULL, actor TEXT NOT NULL, action TEXT NOT NULL, entity TEXT NOT NULL,
                    note TEXT NOT NULL, snapshot TEXT NOT NULL, PRIMARY KEY(project,revision));
            ''')
        self.db.chmod(0o600)

    def connect(self):
        c = sqlite3.connect(str(self.db), timeout=15)
        c.execute('PRAGMA foreign_keys=ON')
        return c

    def projects(self):
        with self.connect() as c:
            return [{'id':p['id'],'name':p['name'],'revision':p['revision'],'samples':len(p['samples'])}
                    for (raw,) in c.execute('SELECT data FROM projects ORDER BY id') for p in [json.loads(raw)]]

    def get(self, project):
        with self.connect() as c:
            row = c.execute('SELECT data FROM projects WHERE id=?',(project,)).fetchone()
        if not row: raise ValueError('项目不存在')
        return json.loads(row[0])

    def history(self, project, revision=None):
        with self.connect() as c:
            if revision is not None:
                row=c.execute('SELECT snapshot FROM history WHERE project=? AND revision=?',(project,revision)).fetchone()
                if not row: raise ValueError('历史版本不存在')
                return json.loads(row[0])
            rows=c.execute('SELECT revision,at,actor,action,entity,note FROM history WHERE project=? ORDER BY revision DESC',(project,)).fetchall()
        return [dict(zip(['revision','at','actor','action','entity','note'],r)) for r in rows]

    def materialize(self, path=None, data=None, input_name=None, expected_hash=None):
        # Local documents are copied, never executed or edited in place.
        if path:
            source=Path(path).expanduser().resolve()
            if not source.is_file(): raise ValueError('文件不存在或不是普通文件')
            if source.stat().st_size > 128*1024*1024: raise ValueError('单文件上限为 128 MB')
            data=source.read_bytes(); input_name=input_name or source.name
        if not isinstance(data,bytes): raise ValueError('缺少文件内容')
        if len(data)>128*1024*1024: raise ValueError('单文件上限为 128 MB')
        if not input_name or Path(input_name).name!=input_name or input_name in {'.','..'} or '/' in input_name or '\\' in input_name:
            raise ValueError('输入文件名无效')
        h=hashlib.sha256(data).hexdigest()
        if expected_hash and h!=expected_hash: raise ValueError('文件哈希不匹配；重新定位不能替换内容，请使用“替换内容”')
        folder=self.home/'objects'/h;folder.mkdir(parents=True,exist_ok=True,mode=0o700)
        dest=folder/input_name
        if dest.exists():
            if sha(dest)!=h: raise ValueError('内容缓存已被修改')
        else:
            fd,temp=tempfile.mkstemp(dir=folder)
            try:
                with os.fdopen(fd,'wb') as f: f.write(data);f.flush();os.fsync(f.fileno())
                os.chmod(temp,0o400);os.replace(temp,dest)
            finally:
                if Path(temp).exists():Path(temp).unlink()
        return {'sha256':h,'bytes':len(data),'path':str(dest),'inputName':input_name,
                'format':Path(input_name).suffix.lstrip('.').lower() or 'bin',
                'location':str(Path(path).expanduser().resolve()) if path else '浏览器选择的本地文件'}

    def import_bundle(self, bundle):
        if bundle.get('schemaVersion')!=1: raise ValueError('不支持的数据契约版本')
        p=copy.deepcopy(bundle['project'])
        if not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}',p.get('id','')):raise ValueError('项目 ID 只能含字母、数字、下划线与连字符')
        p.setdefault('name',p['id']);p.setdefault('samples',[]);p['revision']=1
        ids=set();aids=set()
        for s in p['samples']:
            if s['id'] in ids:raise ValueError('样本 ID 重复')
            ids.add(s['id']);s.setdefault('inputName',Path(s['path']).name)
            # Imported missing files remain visible and repairable.
            if Path(s['path']).is_file():
                original=s.get('location',s['path'])
                s.update(self.materialize(path=s['path'],input_name=s['inputName'],expected_hash=s['sha256']))
                s['location']=original
            s.setdefault('title',s['id']);s.setdefault('private',True);s.setdefault('active',True);s.setdefault('version',1)
            if isinstance(s.get('purpose'),dict):s['purpose']['binding']=binding(s)
            for a in s.setdefault('answers',[]):
                if a['id'] in aids:raise ValueError('答案 ID 重复')
                aids.add(a['id'])
                if a.get('factVersion')==2:a.update(fact_fields(a))
                else:validate_answer(a)
                a.setdefault('binding',binding(s));a.setdefault('revision',1)
                a['digest']=answer_digest(a)
                # Portable import never confers human approval.
                a['status']='pending';a.pop('review',None);a.setdefault('managed',False)
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            if c.execute('SELECT 1 FROM projects WHERE id=?',(p['id'],)).fetchone():raise Conflict('项目已存在；导入不会覆盖人工维护内容')
            c.execute('INSERT INTO projects VALUES(?,?,?)',(p['id'],1,encoded(p)))
            c.execute('INSERT INTO history VALUES(?,?,?,?,?,?,?,?)',(p['id'],1,now(),'import','import',p['id'],'导入样本和 GT；审批保持待审',encoded(p)))
        return p

    def refresh_bundle(self, bundle, actor='dataset-refresh', note='刷新受管数据集；保留内容身份未变化的人工维护记录'):
        """Replace a managed project's sample set without treating paths as identity.

        Matching content IDs keep answers and approvals. A logical-name or format
        change updates the binding and makes those answers stale. New or changed
        content starts without inherited answers. The caller is responsible for
        archiving the database and retired object files before cleanup.
        """
        if bundle.get('schemaVersion')!=1:raise ValueError('不支持的数据契约版本')
        incoming=copy.deepcopy(bundle['project']);project_id=incoming.get('id','')
        if not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}',project_id):raise ValueError('项目 ID 只能含字母、数字、下划线与连字符')
        with self.connect() as c:
            row=c.execute('SELECT data FROM projects WHERE id=?',(project_id,)).fetchone()
        if not row:raise ValueError('项目不存在；首次导入请使用 import_bundle')
        previous=json.loads(row[0]);old_by_id={s['id']:s for s in previous.get('samples',[])}
        incoming.setdefault('name',project_id);incoming.setdefault('samples',[])
        ids=set();answer_ids=set();preserved=[];added=[];changed_bindings=[]
        prepared=[]
        for raw in incoming['samples']:
            s=copy.deepcopy(raw)
            if s['id'] in ids:raise ValueError('样本 ID 重复')
            ids.add(s['id']);s.setdefault('inputName',Path(s['path']).name)
            original=s.get('location',s['path'])
            if Path(s['path']).is_file():
                s.update(self.materialize(path=s['path'],input_name=s['inputName'],expected_hash=s['sha256']))
                s['location']=original
            s.setdefault('title',s['id']);s.setdefault('private',True);s.setdefault('active',True);s.setdefault('version',1)
            if isinstance(s.get('purpose'),dict):s['purpose']['binding']=binding(s)
            old=old_by_id.get(s['id'])
            if old and old.get('sha256')==s.get('sha256'):
                old_binding=binding(old);new_binding=binding(s)
                s['answers']=copy.deepcopy(old.get('answers',[]));s['version']=old.get('version',1)
                if old_binding!=new_binding:
                    s['version']+=1;changed_bindings.append(s['id'])
                    for a in s['answers']:
                        a['binding']=new_binding;a['status']='stale';a.pop('review',None);a['revision']=a.get('revision',0)+1
                        a['digest']=answer_digest(a)
                preserved.append(s['id'])
            else:
                s['answers']=[];added.append(s['id'])
            for a in s['answers']:
                if a['id'] in answer_ids:raise ValueError('答案 ID 重复')
                answer_ids.add(a['id'])
            prepared.append(s)
        incoming['samples']=prepared;incoming['revision']=previous['revision']+1
        incoming['mappings']={k:v for k,v in previous.get('mappings',{}).items() if k in answer_ids}
        incoming['answerScopes']={k:v for k,v in previous.get('answerScopes',{}).items() if k in answer_ids}
        removed=sorted(set(old_by_id)-ids)
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            current=c.execute('SELECT revision FROM projects WHERE id=?',(project_id,)).fetchone()
            if not current or current[0]!=previous['revision']:raise Conflict('项目在刷新期间发生变化，请重试')
            c.execute('UPDATE projects SET revision=?,data=? WHERE id=?',(incoming['revision'],encoded(incoming),project_id))
            c.execute('INSERT INTO history VALUES(?,?,?,?,?,?,?,?)',(project_id,incoming['revision'],now(),actor,
                'dataset_refresh',project_id,note,encoded(incoming)))
        incoming['_refresh']={'preserved':len(preserved),'added':len(added),'removed':len(removed),
                              'changedBindings':len(changed_bindings)}
        return incoming

    def act(self, project, request):
        actor=str(request.get('actor','')).strip();note=str(request.get('note','')).strip()
        if not actor: raise ValueError('请填写操作者姓名')
        action=request.get('action');entity=request.get('sampleId','')
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            row=c.execute('SELECT data FROM projects WHERE id=?',(project,)).fetchone()
            if not row:raise ValueError('项目不存在')
            p=json.loads(row[0])
            if request.get('revision')!=p['revision']:raise Conflict('页面版本已过期，请刷新后再操作')
            sample=next((s for s in p['samples'] if s['id']==entity),None)
            if action=='migrate_facts':
                migrate_project(p);entity=project
            elif action in {'set_answer_scope','set_case_scopes'}:
                rows=request.get('scopes',[]) if action=='set_case_scopes' else [{'answerId':request.get('answerId'),'mode':request.get('mode'),'reason':note}]
                all_answers={a['id']:a for s in p['samples'] for a in s['answers']}
                for item in rows:
                    aid=item.get('answerId');mode=item.get('mode')
                    if aid not in all_answers or mode not in {'case','reference'}:raise ValueError('无效的验收范围')
                    if action=='set_answer_scope' and (not sample or not any(a['id']==aid for a in sample['answers'])):raise ValueError('答案不属于当前样本')
                    p.setdefault('answerScopes',{})[aid]={'mode':mode,'reason':str(item.get('reason','')),'actor':actor,'at':now()}
                if action=='set_case_scopes':
                    for sid, purpose in request.get('purposeUpdates',{}).items():
                        target_sample=next((s for s in p['samples'] if s['id']==sid),None)
                        if not target_sample or not isinstance(purpose.get('summary'),str) or not isinstance(purpose.get('checks'),list):raise ValueError('无效的样本用途')
                        target_sample['purpose']={**copy.deepcopy(purpose),'binding':binding(target_sample)}
                    mapping_updates=request.get('mappingUpdates',{})
                    if mapping_updates and request.get('confirmMappings') is not True:
                        raise ValueError('批量映射需要确认统计口径一致')
                    for aid,raw_mapping in mapping_updates.items():
                        answer=all_answers.get(aid)
                        if not answer or answer.get('kind')!='fact':raise ValueError('映射只能关联文档事实')
                        m=validate_mapping(raw_mapping);previous=p.setdefault('mappings',{}).get(aid,{})
                        m['revision']=previous.get('revision',0)+1;m['actor']=actor;m['at']=now()
                        p['mappings'][aid]=m
                p['scopeSchema']=1;entity=project if action=='set_case_scopes' else request['answerId']
            elif action=='import_fact_drafts':
                migrate_project(p)
                for row in request['drafts']:
                    dest=next((s for s in p['samples'] if s['id']==row['sampleId']),None)
                    if dest is None or row['sourceSha256']!=dest['sha256']:raise Conflict('取证后样本发生变化')
                    fields=fact_fields(row['fact'])
                    existing=next((a for a in dest['answers'] if a.get('factKey')==fields['factKey']),None)
                    if existing:
                        if existing.get('valueState')=='known' and fields['valueState']=='known' and encoded(existing['expected'])!=encoded(fields['expected']):
                            finding={'answerId':existing['id'],'factKey':fields['factKey'],'candidate':fields,'note':'新取证与已有 GT 不一致；未自动改答案。'}
                            if finding not in dest.setdefault('factFindings',[]):dest['factFindings'].append(finding)
                        continue
                    a={**fields,'id':dest['id']+':fact-'+uuid4().hex[:10], 'binding':binding(dest),
                       'status':'pending','managed':True,'revision':1}
                    a['digest']=answer_digest(a);dest['answers'].append(a)
                    if p.get('scopeSchema')==1:p.setdefault('answerScopes',{})[a['id']]={'mode':'reference','reason':'自动取证先作参考；请按样本用途纳入 GT。','actor':actor,'at':now()}
                    if row.get('mapping'):p['mappings'][a['id']]=validate_mapping(row['mapping'])
                for s in p['samples']:
                    for criterion in s.get('purpose',{}).get('checks',[]):
                        keys=request.get('purposeFactKeys',{}).get(s['id'],{}).get(criterion['label'])
                        if keys:
                            criterion['factKeys']=keys
                            criterion['note']='独立事实在下方维护；产品是否支持及其字段映射单独记录。'
                entity=project
            elif action=='add_sample':
                file=self._file(request)
                sample={'id':'sample-'+uuid4().hex[:12],**file,'title':request.get('title') or file['inputName'],
                        'private':request.get('private',True) is not False,'active':True,'version':1,'answers':[],
                        'tags':request.get('tags',[]),'origin':'manual'}
                p['samples'].append(sample);entity=sample['id']
            elif action=='review_all_scenarios':
                if request.get('confirm') is not True:raise ValueError('请确认已通篇核对全部场景内的断言与依据')
                status=request.get('status','approved')
                if status not in {'approved','rejected','deferred'}:raise ValueError('无效的审核状态')
                scopes=p.get('answerScopes',{})
                for s in p['samples']:
                    if not s['active']:continue
                    if not Path(s['path']).is_file() or sha(s['path'])!=s['sha256']:
                        raise ValueError(f"样本 {s['inputName']} 缺失或内容变化，不能批量批准")
                    in_case=[ans for ans in s['answers'] if scopes.get(ans['id'],{}).get('mode')!='reference']
                    for current in in_case:
                        if status=='approved':
                            if current.get('kind')=='fact' and current.get('valueState') in {'unknown','unreadable'}:
                                raise ValueError(f"样本 {s['inputName']} 的断言「{current.get('question')}」仍为待核定状态")
                            if current.get('factVersion')==2 and not current.get('definition','').strip():
                                raise ValueError(f"样本 {s['inputName']} 的断言「{current.get('question')}」未定义统计口径")
                            if current['status']=='stale' or current['binding']!=binding(s):
                                raise ValueError(f"样本 {s['inputName']} 的断言需要重新绑定")
                            if not current['evidence'].get('method'):
                                raise ValueError(f"样本 {s['inputName']} 的断言未填写取证方法")
                        if status=='approved' and current['status']=='approved' and current.get('review',{}).get('digest')==current['digest']:
                            continue
                        current.update(status=status,managed=True,revision=current['revision']+1,
                            review={'actor':actor,'note':note,'at':now(),'digest':current['digest']})
                entity=project
            elif not sample:raise ValueError('样本不存在')
            elif action=='relink':
                file=self._file(request,input_name=sample['inputName'],expected_hash=sample['sha256'])
                if Path(request.get('path') or request.get('filename','')).suffix.lower()!=('.'+sample['format']):
                    raise ValueError('后缀不同，请使用替换内容并重新审核 GT')
                sample.update(file)
            elif action=='replace':
                file=self._file(request)
                if binding(file)==binding(sample):raise ValueError('内容和逻辑文件名均未改变，请使用重新定位')
                sample['replacement']={'previousSha256':sample['sha256'],'at':now(),'actor':actor,'note':note}
                sample.update(file);sample['version']+=1
                sample['title']=request.get('title') or file['inputName']
                sample['private']=request.get('private',True) is not False
                for a in sample['answers']:a['status']='stale';a.pop('review',None);a['managed']=True;a['revision']+=1
            elif action=='sample_status':
                if not isinstance(request.get('active'),bool):raise ValueError('请选择状态')
                sample['active']=request['active']
            elif action=='sample_visibility':
                if not isinstance(request.get('private'),bool):raise ValueError('请选择公开或私有属性')
                sample['private']=request['private']
            elif action=='save_purpose':
                purpose=copy.deepcopy(request['purpose'])
                if not isinstance(purpose.get('summary'),str) or not purpose['summary'].strip():
                    raise ValueError('请填写样本用途')
                checks=purpose.get('checks',[])
                if not isinstance(checks,list) or any(not isinstance(x,dict) or not isinstance(x.get('label'),str) for x in checks):
                    raise ValueError('主要验证项必须是带 label 的对象列表')
                for check in checks:
                    if any(k in check and not isinstance(check[k],str) for k in ['type','target','note']):
                        raise ValueError('验证项的类型、target 和说明必须是文字')
                purpose['binding']=binding(sample)
                sample['purpose']=purpose
            elif action=='save_mapping':
                a=next((a for a in sample['answers'] if a['id']==request.get('answerId')),None)
                if not a or a.get('kind')!='fact':raise ValueError('映射只能关联文档事实')
                m=validate_mapping(request['mapping'])
                if m['status']=='mapped' and request.get('confirm') is not True:raise ValueError('请确认字段与事实统计口径一致')
                mappings=p.setdefault('mappings',{});m['revision']=mappings.get(a['id'],{}).get('revision',0)+1
                m['actor']=actor;m['at']=now();mappings[a['id']]=m;entity=a['id']
            elif action in {'save_answer','review_answer','review_scenario'}:
                a=next((a for a in sample['answers'] if a['id']==request.get('answerId')),None)
                if action=='review_scenario':
                    if request.get('confirm') is not True:raise ValueError('请确认已核对场景内的全部断言与依据')
                    status=request.get('status')
                    if status not in {'approved','rejected','deferred'}:raise ValueError('无效的审核状态')
                    requested=request.get('answers',[])
                    if not requested:raise ValueError('场景中没有可审核断言')
                    by_id={x['id']:x for x in sample['answers']}
                    chosen=[]
                    for item in requested:
                        current=by_id.get(item.get('id'))
                        if not current or item.get('digest')!=current['digest']:raise Conflict('场景内容已变化，请刷新后审核')
                        if p.get('answerScopes',{}).get(current['id'],{}).get('mode')=='reference':raise ValueError('参考取证不能作为场景断言审核')
                        if status=='approved':
                            if current.get('kind')=='fact' and current.get('valueState') in {'unknown','unreadable'}:raise ValueError('场景中仍有待核定答案')
                            if current.get('factVersion')==2 and not current.get('definition','').strip():raise ValueError('场景中仍有未定义统计口径的事实')
                            if current['status']=='stale' or current['binding']!=binding(sample):raise ValueError('场景中存在需要重新绑定的答案')
                            if not sample['active']:raise ValueError('已停用样本不能批准场景')
                            if not Path(sample['path']).is_file() or sha(sample['path'])!=sample['sha256']:raise ValueError('样本缺失或内容变化，不能批准')
                            if not current['evidence'].get('method'):raise ValueError('场景中仍有未填写取证方法的断言')
                        chosen.append(current)
                    for current in chosen:
                        if status=='approved' and current['status']=='approved' and current.get('review',{}).get('digest')==current['digest']:continue
                        current.update(status=status,managed=True,revision=current['revision']+1,
                            review={'actor':actor,'note':note,'at':now(),'digest':current['digest']})
                    entity=sample['id']
                elif action=='save_answer':
                    fields=request['answer']
                    is_fact=fields.get('kind')=='fact' or (a and a.get('kind')=='fact')
                    if is_fact:fields=fact_fields(fields)
                    else:validate_answer(fields)
                    if is_fact and a and any(a.get(k)!=fields.get(k) for k in ['factKey','definition']):
                        old_mapping=p.setdefault('mappings',{}).get(a['id'])
                        if old_mapping:old_mapping.update(status='unmapped',note='事实口径变化，请重新确认映射。')
                    if not a:
                        a={'id':sample['id']+':answer-'+uuid4().hex[:10],'revision':0};sample['answers'].append(a)
                    keys=['kind','factVersion','factKey','definition','valueState','question','expected','evidence'] if is_fact else ['question','expected','evidence','check','options','requirement']
                    a.update({k:copy.deepcopy(fields[k]) for k in keys if k in fields})
                    if is_fact:
                        for k in ['check','options','requirement','payload']:a.pop(k,None)
                    a.update(binding=binding(sample),status='pending',managed=True,revision=a['revision']+1)
                    a.pop('review',None);a.pop('display',None);a['digest']=answer_digest(a)
                elif action=='review_answer':
                    if not a:raise ValueError('答案不存在')
                    if request.get('answerDigest')!=a['digest']:raise Conflict('答案内容已变化，请刷新后审核')
                    if request.get('confirm') is not True:raise ValueError('请确认已核对当前答案与依据')
                    status=request.get('status')
                    if status not in {'approved','rejected','deferred'}:raise ValueError('无效的审核状态')
                    if status=='approved':
                        if a.get('kind')=='fact' and a.get('valueState') in {'unknown','unreadable'}:raise ValueError('尚无可靠答案，请先补充取证或人工核定')
                        if a.get('factVersion')==2 and not a.get('definition','').strip():raise ValueError('批准事实前需明确统计口径')
                        if a['status']=='stale' or a['binding']!=binding(sample):raise ValueError('文件版本已变化，请先修订并重新绑定答案')
                        if not sample['active']:raise ValueError('已停用的样本不能批准新答案')
                        if not Path(sample['path']).is_file() or sha(sample['path'])!=sample['sha256']:raise ValueError('样本缺失或内容变化，不能批准')
                        if not a['evidence'].get('method'):raise ValueError('批准前需要填写取证方法')
                    a.update(status=status,managed=True,revision=a['revision']+1,
                             review={'actor':actor,'note':note,'at':now(),'digest':a['digest']})
                if action!='review_scenario':entity=a['id']
            else:raise ValueError('不支持的操作')
            p['revision']+=1
            c.execute('UPDATE projects SET revision=?,data=? WHERE id=?',(p['revision'],encoded(p),project))
            c.execute('INSERT INTO history VALUES(?,?,?,?,?,?,?,?)',(project,p['revision'],now(),actor,action,entity,note,encoded(p)))
        return p

    def _file(self, r, input_name=None, expected_hash=None):
        if r.get('path'):return self.materialize(path=r['path'],input_name=input_name,expected_hash=expected_hash)
        try: data=base64.b64decode(r.get('data',''),validate=True)
        except ValueError:raise ValueError('文件编码无效')
        return self.materialize(data=data,input_name=input_name or r.get('filename'),expected_hash=expected_hash)

    def export(self, project):
        return {'schemaVersion':1,'project':self.get(project)}
