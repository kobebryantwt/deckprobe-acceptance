"""Release-contract evaluation. No automatic approval or target-as-oracle."""
from __future__ import annotations
import copy
import json
import math
import re

CONFIDENCE = {"none":0.0,"low":0.4,"medium":0.7,"high":0.95,"exact":1.0}
UNRESOLVED = {"planned","unknown","unsupported","invalid","budget_exceeded","failed"}


def report_issues(report, schema, exit_code=None):
    import jsonschema
    issues = []
    try:
        validator = jsonschema.Draft202012Validator(schema)
        issues.extend("schema: " + e.message for e in validator.iter_errors(report))
    except (jsonschema.SchemaError, TypeError) as e:
        raise ValueError("Invalid released schema: " + str(e))
    if not isinstance(report,dict): return issues + ['report is not an object']
    if report.get('status') == 'error':
        if exit_code is not None and report.get('error',{}).get('exit_code') != exit_code:
            issues.append('reported exit code differs from process')
        return issues
    if report.get('view') == 'values': return issues
    unresolved = []
    for key, result in report.get('results',{}).items():
        if not isinstance(result,dict):
            issues.append('target is not an object: '+key); continue
        if result.get('target') != key: issues.append('canonical target mismatch: '+key)
        status = result.get('status')
        if status in {'resolved','estimated'}:
            if 'value' not in result: issues.append('missing resolved value: '+key)
            if result.get('confidence') not in CONFIDENCE or result.get('confidence_score') != CONFIDENCE.get(result.get('confidence')):
                issues.append('confidence mapping: '+key)
            if not result.get('path') or not result.get('source'): issues.append('missing evidence: '+key)
        elif status in UNRESOLVED:
            if 'value' in result: issues.append('unresolved target carries value: '+key)
            if result.get('confidence') not in {None,'none'} or result.get('confidence_score') not in {None,0,0.0}:
                issues.append('unresolved target confidence is not none: '+key)
            unresolved.append(key)
        else: issues.append('invalid target status: '+key)
    execution=report.get('execution',{})
    if sorted(execution.get('unresolved_targets',[])) != sorted(unresolved):
        issues.append('unresolved targets mismatch')
    if report.get('status') != ('partial' if unresolved else 'ok'):
        issues.append('partial/ok mismatch')
    for field in ['physical_bytes_read','expanded_bytes','random_reads']:
        value=execution.get('actual_cost',{}).get(field)
        if type(value) is not int or value < 0: issues.append('invalid cost: '+field)
    return issues


def evaluate_answer(a, report):
    c=a['check']; typ=c['type']; expected=a['expected']
    if typ=='target':
        r=report.get('results',{}).get(c['target'],{})
        actual=r.get('value')
        available=r.get('status') in {'resolved','estimated'} and 'value' in r
        comparator=c.get('comparator','exact')
        if comparator=='exact':ok=available and type(actual) is type(expected) and actual==expected
        elif comparator=='numeric_tolerance':
            if not (available and type(actual) in {int,float} and type(expected) in {int,float}):ok=False
            else:
                delta=abs(actual-expected);limits=[]
                if 'absolute_tolerance' in c:limits.append(delta<=c['absolute_tolerance'])
                if 'relative_tolerance' in c:limits.append(delta<=abs(expected)*c['relative_tolerance'])
                ok=bool(limits) and any(limits)
        elif comparator=='ordered_equal':ok=available and isinstance(actual,list) and actual==expected
        elif comparator=='unordered_equal':
            try:ok=available and sorted(json.dumps(x,sort_keys=True) for x in actual)==sorted(json.dumps(x,sort_keys=True) for x in expected)
            except TypeError:ok=False
        elif comparator=='contains':ok=available and expected in actual
        elif comparator=='regex':ok=available and isinstance(actual,str) and re.search(expected,actual) is not None
        elif comparator=='present':ok=available and actual is not None
        elif comparator=='absent':ok=not available or actual is None
        else:raise ValueError('Unknown target comparator: '+comparator)
    elif typ=='status':
        actual=report.get('results',{}).get(c['target'],{}).get('status');ok=actual==expected
    elif typ=='error':
        actual=report.get('error',{}).get('code');ok=report.get('status')=='error' and actual==expected
    elif typ=='allowed_paths':
        actual=report.get('results',{}).get(c['target'],{}).get('path');ok=actual in expected
    elif typ=='cost_ceiling':
        actual=report.get('execution',{}).get('actual_cost',{})
        ok=all(type(actual.get(k)) is int and 0<=actual[k]<=v for k,v in expected.items())
    else: raise ValueError('Unknown acceptance check: '+typ)
    return {'passed':ok,'actual':actual,'expected':expected}


def normalize(report):
    """Only transport/source and elapsed-time differences are excluded."""
    r=copy.deepcopy(report)
    if isinstance(r,dict):
        if isinstance(r.get('input'),dict):
            for key in ['source_kind','path','name']:
                r['input'].pop(key,None)
        if isinstance(r.get('execution'),dict):
            r['execution'].get('actual_cost',{}).pop('elapsed_ms',None)
        # Explicit header-only provenance equivalences for file vs supplied bytes.
        # Actual parsed-part/source evidence for every other target is retained.
        provenance={
            'document.extension':{'input path','input name'},
            'document.extension_matches':{'input path + detected profile','input name + detected profile'},
            'document.file_size':{'filesystem metadata','source length'},
        }
        for target,allowed in provenance.items():
            value=r.get('results',{}).get(target)
            if isinstance(value,dict) and value.get('source') in allowed:
                value['source']='equivalent input identity metadata'
    return r


def decision(items):
    required=[x for x in items if x.get('role','gate')=='gate']
    if any(x['status']=='failed' for x in required): return 'FAIL'
    if not required or any(x['status']=='blocked' for x in required): return 'INCOMPLETE'
    if any(x['status']=='review' for x in required): return 'REVIEW'
    return 'PASS'


def compare_assertions(before, after, compatible):
    old={x['id']:x for x in before}; result=[]
    for item in after:
        previous=old.get(item['id'])
        if previous is None: kind='new_coverage'
        elif not compatible: kind='incomparable'
        elif previous['status']=='passed' and item['status']=='failed': kind='regression'
        elif previous['status']=='failed' and item['status']=='passed': kind='fixed'
        elif previous['status']=='failed' and item['status']=='failed': kind='existing_failure'
        elif item['status']=='blocked' or previous['status']=='blocked': kind='environment_or_evidence'
        elif item['status']=='review' or previous['status']=='review': kind='needs_review'
        else: kind='unchanged'
        result.append({'id':item['id'],'classification':kind,'before':previous and previous['status'],'after':item['status']})
    result.extend({'id':key,'classification':'removed_coverage','before':v['status'],'after':None} for key,v in old.items() if key not in {x['id'] for x in after})
    return result
