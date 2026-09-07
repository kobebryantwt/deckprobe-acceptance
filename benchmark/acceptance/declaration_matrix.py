"""Build the reviewable extension -> resolved profile -> target declaration denominator."""
from pathlib import Path
import json

from .common import CODE, atomic, digest, now, read

EXTENSION_PROFILES={
    'pdf':['pdf'],'docx':['docx','encrypted-ooxml'],'docm':['docm'],'dotx':['dotx'],'dotm':['dotm'],
    'xlsx':['xlsx','encrypted-ooxml'],'xlsm':['xlsm'],'xltx':['xltx'],'xltm':['xltm'],'xlsb':['xlsb'],
    'pptx':['pptx','encrypted-ooxml'],'pptm':['pptm'],'ppsx':['ppsx'],'ppsm':['ppsm'],'potx':['potx'],'potm':['potm'],
    'doc':['doc'],'dot':['doc'],'xls':['xls'],'xlt':['xls'],'ppt':['ppt'],'pps':['ppt'],'pot':['ppt'],
    'key':['key'],'numbers':['numbers'],'pages':['pages'],
}

def prepare(home,catalog_path):
    home=Path(home);catalog=json.loads(Path(catalog_path).read_text());catalog_id=digest(catalog)
    previous=read(home/'declarations.json',{});rows=[]
    previous_rows={r['id']:r for r in previous.get('rows',[])}
    for extension,profiles in EXTENSION_PROFILES.items():
        for profile in profiles:
            for target,value in catalog['targets'].items():
                details=value.get('profile_details',{}).get(profile)
                if not details:continue
                for level in details.get('supported_levels',[]):
                    row_id=f'{extension}->{profile}/{target}/{level}'
                    old=previous_rows.get(row_id)
                    # Incremental review: unchanged targets inherit approval; only new rows generate draft.
                    status=old.get('reviewStatus','draft') if old else 'draft'
                    intro=old.get('introducedByCatalog',catalog_id) if old else catalog_id
                    rows.append({'id':row_id,'extension':extension,
                        'resolvedProfile':profile,'target':target,'level':level,
                        'scenarios':old.get('scenarios',['fact']) if old else ['fact'],
                        'introducedByCatalog':intro,'reviewStatus':status})
    old_scenarios={x.get('id'):x for x in previous.get('scenarioCoverage',[])}
    required=read(CODE/'config/policy.json').get('requiredScenarios',[])
    scenarios=[old_scenarios.get(x,{'id':x,'reviewStatus':'draft','answerIds':[]}) for x in required]
    # Track breaking changes if any previously declared targets were removed
    current_ids={r['id'] for r in rows}
    removed=[r for r in previous.get('rows',[]) if r['id'] not in current_ids]
    all_rows_approved=bool(rows) and all(r['reviewStatus']=='approved' for r in rows)
    scenarios_complete=all(s.get('reviewStatus')=='approved' and s.get('answerIds') for s in scenarios)
    matrix_status='approved' if (all_rows_approved and scenarios_complete and previous.get('reviewStatus')=='approved') else 'draft'
    matrix={'version':2,'reviewStatus':matrix_status,'catalogId':catalog_id,'catalogToolVersion':catalog.get('tool_version'),
        'preparedAt':now(),'extensionProfiles':EXTENSION_PROFILES,'rows':rows,
        'scenarioCoverage':scenarios,'breakingChanges':removed}
    if previous.get('review'):matrix['review']=previous['review']
    atomic(home/'declarations.json',matrix)
    return {'catalogId':catalog_id,'rows':len(rows),'extensions':len(EXTENSION_PROFILES),
            'profiles':len({p for ps in EXTENSION_PROFILES.values() for p in ps}),'reviewStatus':matrix_status,
            'newRows':sum(r['reviewStatus']=='draft' for r in rows),'breakingChanges':len(removed)}

def approve(home,expected_digest,reviewer):
    home=Path(home);matrix=read(home/'declarations.json',{})
    current=digest({k:v for k,v in matrix.items() if k not in {'reviewStatus','review'}})
    if current!=expected_digest:raise ValueError('声明矩阵内容已变化，请重新审核')
    missing=[x.get('id') for x in matrix.get('scenarioCoverage',[]) if not x.get('answerIds')]
    if missing:raise ValueError('场景尚未绑定答案：'+', '.join(missing))
    if not matrix.get('rows'):raise ValueError('声明矩阵为空')
    matrix['reviewStatus']='approved';matrix['review']={'reviewer':reviewer,'at':now(),'digest':current}
    for row in matrix['rows']:row['reviewStatus']='approved'
    for row in matrix.get('scenarioCoverage',[]):row['reviewStatus']='approved'
    atomic(home/'declarations.json',matrix);return {'reviewStatus':'approved','rows':len(matrix['rows']),'digest':current}

def review_digest(home):
    matrix=read(Path(home)/'declarations.json',{})
    return digest({k:v for k,v in matrix.items() if k not in {'reviewStatus','review'}})

def bind_scenario(home,scenario,answer_ids):
    home=Path(home);matrix=read(home/'declarations.json',{});answers=read(home/'answers/index.json',{}).get('answers',[])
    known={a['id'] for a in answers};missing=sorted(set(answer_ids)-known)
    if missing:raise ValueError('答案 ID 不存在：'+', '.join(missing))
    row=next((x for x in matrix.get('scenarioCoverage',[]) if x.get('id')==scenario),None)
    if row is None:raise ValueError('不是必需场景：'+scenario)
    row.update(answerIds=sorted(set(answer_ids)),reviewStatus='draft')
    matrix['reviewStatus']='draft';matrix.pop('review',None);atomic(home/'declarations.json',matrix)
    return {'scenario':scenario,'answerIds':row['answerIds'],'reviewStatus':'draft'}
