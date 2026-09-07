"""Product-independent fact records. Legacy digests remain valid during migration."""
import copy

VALUE_STATES = {'known', 'unknown', 'unreadable', 'not_applicable'}


def fact_fields(fields):
    a=copy.deepcopy(fields)
    a.update(kind='fact', factVersion=2)
    if not isinstance(a.get('question'),str) or not a['question'].strip():raise ValueError('请填写事实问题')
    if not isinstance(a.get('factKey'),str) or not a['factKey'].strip():raise ValueError('请填写事实标识')
    if not isinstance(a.get('definition'),str):raise ValueError('统计口径必须是文字')
    a.setdefault('valueState','known')
    if a['valueState'] not in VALUE_STATES:raise ValueError('无效的取证状态')
    if a['valueState']=='known' and 'expected' not in a:raise ValueError('请填写事实答案')
    if a['valueState']!='known':a['expected']=None
    a.setdefault('evidence',{})
    if not isinstance(a['evidence'],dict):raise ValueError('依据必须是对象')
    # Product fields never belong in a new fact's semantic content.
    for k in ['check','options','requirement','payload','display']:a.pop(k,None)
    return a


def migrate_project(p):
    if p.get('factSchema')==2:return
    mappings=p.setdefault('mappings',{})
    for s in p['samples']:
        for a in s['answers']:
            if a.get('check',{}).get('type')!='target':
                a.setdefault('kind','contract');continue
            a['kind']='fact'
            a['factKey']=a['check']['target']
            a['definition']='沿用原审核问题及独立依据的统计口径（原字段：'+a['check']['target']+'）。'
            a['valueState']='known'
            a['legacyFactDigest']=a['digest']
            mappings[a['id']]={'status':'mapped','adapter':p.get('adapter',p['id']),
                'check':copy.deepcopy(a['check']),'options':copy.deepcopy(a.get('options',[])),
                'requirement':a.get('requirement',''),'revision':1,
                'note':'从原检查机械拆分；原摘要、答案、依据与审批原样保留。'}
        if s.get('purpose'):
            for c in s['purpose'].get('checks',[]):
                if c.get('type')=='target' and c.get('target'):c['factKey']=c['target']
    p['factSchema']=2


def validate_mapping(mapping):
    m=copy.deepcopy(mapping)
    if m.get('status') not in {'mapped','unsupported','unmapped'}:raise ValueError('无效的映射状态')
    m.setdefault('check',{});m.setdefault('options',[]);m.setdefault('requirement','')
    if not isinstance(m['check'],dict) or not isinstance(m['options'],list) or not all(isinstance(x,str) for x in m['options']):
        raise ValueError('检查必须是对象，请求参数必须是字符串列表')
    allowed={'target','status','error','allowed_paths','cost_ceiling'}
    if m['status']=='mapped' and m['check'].get('type') not in allowed:
        raise ValueError('事实映射的检查类型无效')
    if m['status']=='mapped' and m['check'].get('type') in {'target','status','allowed_paths'} and not m['check'].get('target'):
        raise ValueError('该事实映射需填写 target')
    return m
