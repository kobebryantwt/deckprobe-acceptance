from __future__ import annotations
import json
from pathlib import Path
from .common import CODE, atomic, digest, immutable, process, read
from .corpus import approved

PROFILE_ROUTES={'dot':'doc','xlt':'xls','pps':'ppt','pot':'ppt'}


def capture_catalog(home, prepared):
    binary=prepared['release']['binary']
    policy=read(CODE/'config/policy.json')
    records={}
    for extension in policy['declaredProfiles']:
        profile=PROFILE_ROUTES.get(extension,extension)
        proc=process([binary,'targets','--format',profile],timeout=30)
        try:data=json.loads(proc['stdout'])
        except ValueError:data={}
        records[extension]={'process':proc,'catalog':data,'resolvedProfile':profile}
    # Stable identity excludes durations/collection times but includes all advertised semantics.
    catalogs={k:{'resolvedProfile':v['resolvedProfile'],'catalog':v['catalog']} for k,v in records.items()}
    identity=digest(catalogs)
    folder=Path(home)/'catalogs'/identity
    folder.mkdir(parents=True,exist_ok=True)
    immutable(folder/'catalog.json',catalogs)
    atomic(folder/'capture.json',records)
    frozen=read(Path(home)/'declarations.json',{'version':1,'reviewStatus':'draft','rows':[]})
    by_id={r['id']:r for r in frozen['rows']}
    for extension,envelope in catalogs.items():
        profile=envelope['resolvedProfile'];value=envelope['catalog']
        for t in value.get('targets',[]):
            if not t.get('applicable',True):continue
            name=t.get('id') or t.get('target')
            if not name:continue
            for level in t.get('supported_levels',[]):
                key=f'{extension}->{profile}/{name}/{level}'
                if key not in by_id:
                    by_id[key]={'id':key,'extension':extension,'profile':profile,'target':name,'level':level,'scenarios':['fact'],
                               'introducedByCatalog':identity,'reviewStatus':'draft'}
    # Monotonic union: disappearing catalog entries never erase the denominator.
    frozen['rows']=[by_id[k] for k in sorted(by_id)]
    frozen['declaredProfiles']=policy['declaredProfiles']
    frozen['catalogId']=identity
    atomic(Path(home)/'declarations.json',frozen)
    return identity


def coverage(home, results=None):
    declaration=read(Path(home)/'declarations.json',{'rows':[]})
    answers=read(Path(home)/'answers/index.json',{'answers':[]})['answers']
    actual={x['id']:x for x in results or []}
    def result(a):return actual.get(a['id'].replace('/','_').replace(':','_'),{})
    rows=[]
    for row in declaration['rows']:
        extension=row.get('extension') or row.get('resolvedProfile') or row.get('profile','')
        applicable=[a for a in answers if a['format']==extension and a['check'].get('target')==row['target']
                    and row['level'] in a.get('options',[])]
        accepted=[a for a in applicable if approved(home,a)]
        ran=[a for a in accepted if result(a).get('status') in {'passed','failed'}]
        passed=[a for a in ran if result(a)['status']=='passed']
        rows.append({**row,'designed':bool(applicable),'approved':bool(accepted),'executed':bool(ran),'passed':bool(passed)})
    summary={key:sum(bool(r[key]) for r in rows) for key in ['designed','approved','executed','passed']}
    summary.update(total=len(rows),declarationReviewStatus=declaration.get('reviewStatus','draft'))
    policy=read(CODE/'config/policy.json')
    required=policy.get('requiredScenarios',[])
    declared={x.get('id'):x for x in declaration.get('scenarioCoverage',[])}
    scenario_rows=[]
    for scenario in required:
        item=declared.get(scenario,{})
        evidence_ids=item.get('answerIds',[])
        selected=[a for a in answers if a['id'] in evidence_ids]
        accepted=[a for a in selected if approved(home,a)]
        statuses=[result(a).get('status') for a in accepted]
        scenario_rows.append({'id':scenario,'designed':bool(selected),'approved':bool(selected) and len(accepted)==len(selected),
                              'executed':bool(accepted) and all(x in {'passed','failed'} for x in statuses),
                              'passed':bool(accepted) and all(x=='passed' for x in statuses),
                              'reviewStatus':item.get('reviewStatus','draft'),'answerIds':evidence_ids})
    summary['requiredScenarios']=len(required)
    summary['passedScenarios']=sum(x['passed'] and x['reviewStatus']=='approved' for x in scenario_rows)
    return {'summary':summary,'rows':rows,
            'scenarios':scenario_rows,
            'note':'Facts coverage only; positive/negative, boundary, surface and platform coverage are separate required dimensions.'}
