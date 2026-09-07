"""Import normalized evidence/GT records as pending Casework facts."""
from __future__ import annotations

import json
from pathlib import Path


STATE_MAP={"observed":"known","absent":"known","not_applicable":"not_applicable",
           "unsupported":"unknown","unknown":"unknown","error":"unreadable"}


def import_records(store, project_id, path, actor="evidence import"):
    data=json.loads(Path(path).read_text())
    records=data.get('records',[]) if data.get('record_kind')=='record_collection' else [data]
    project=store.get(project_id);by_id={s['id']:s for s in project['samples']};by_hash={s['sha256']:s for s in project['samples']}
    drafts=[];unmatched=[]
    for record in records:
        if record.get('record_kind') not in {'cross_validation','ground_truth'}:continue
        sample_record=record.get('sample',{});sample=by_id.get(sample_record.get('case_id')) or by_hash.get(sample_record.get('sha256'))
        if sample is None:unmatched.append(record.get('record_id'));continue
        producer=record.get('producer',{})
        for field in record.get('fields',[]):
            state=STATE_MAP.get(field.get('state'),'unknown')
            gt=field.get('ground_truth',{})
            expected=gt.get('expected',field.get('value')) if state=='known' else None
            if field.get('state')=='absent':expected=False
            evidence=field.get('evidence',[])
            locations=[x.get('locator') for x in evidence if x.get('locator')]
            fact={"kind":"fact","factKey":field['fact_id'],"definition":field['definition'],
                  "question":field.get('notes') or (field['definition']+' 的核定结果是什么？'),
                  "valueState":state,"expected":expected,
                  "evidence":{"method":" / ".join(x for x in [producer.get('name'),producer.get('version'),producer.get('independence')] if x),
                              "location":"；".join(locations) or record.get('record_id','normalized record'),
                              "notes":"来源记录 "+record.get('record_id','unknown')+"；导入不会继承外部审批。"}}
            source_mapping=field.get('target_mapping') or {"status":"unmapped","rationale":"尚未映射产品字段"}
            mapping={"status":{"product_unsupported":"unsupported"}.get(source_mapping.get('status'),source_mapping.get('status','unmapped')),
                     "note":source_mapping.get('rationale','')}
            if mapping['status']=='mapped':
                check=source_mapping.get('check')
                mapping.update(adapter='deckprobe',check={"type":"target" if check=='value' else check})
                if source_mapping.get('target'):mapping['check']['target']=source_mapping['target']
                mapping.update(options=source_mapping.get('request_options',[]),requirement=source_mapping.get('requirement','PRO-R03'))
                mapping['check']['comparator']=gt.get('comparator','exact')
                for key in ['absolute_tolerance','relative_tolerance']:
                    if key in gt:mapping['check'][key]=gt[key]
            drafts.append({"sampleId":sample['id'],"sourceSha256":sample['sha256'],"fact":fact,"mapping":mapping})
    if drafts:
        project=store.act(project_id,{"action":"import_fact_drafts","revision":project['revision'],"actor":actor,
            "note":"导入标准化第三方事实；所有内容保持待审。","drafts":drafts,"purposeFactKeys":{}})
    return {"project":project_id,"records":len(records),"facts":len(drafts),"unmatchedRecords":unmatched,
            "revision":project['revision']}
