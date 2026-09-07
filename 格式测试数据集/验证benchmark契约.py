#!/usr/bin/env python3
"""Validate GT v2 artifacts and compare their embedded contract with a released DeckProbe."""
import argparse
import importlib.util
import json
from pathlib import Path
import subprocess

from jsonschema import Draft202012Validator

ROOT=Path(__file__).resolve().parent

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--deckprobe',required=True);args=parser.parse_args()
    schema=json.loads((ROOT/'benchmark-gt.schema.json').read_text())
    Draft202012Validator.check_schema(schema);validator=Draft202012Validator(schema)
    artifact_errors={}
    for name in ['DeckProbe深度探测完整结果.json','benchmark-cross-validation.example.json','benchmark-ground-truth.example.json']:
        errors=list(validator.iter_errors(json.loads((ROOT/name).read_text())))
        artifact_errors[name]=[{'path':list(e.path),'message':e.message} for e in errors]
    native_schema=json.loads(subprocess.run([args.deckprobe,'schema'],check=True,capture_output=True,text=True).stdout)
    spec=importlib.util.spec_from_file_location('generator',ROOT/'生成深度探测产物.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    _,live_catalog=module.discover_catalog(args.deckprobe)
    stored=json.loads((ROOT/'DeckProbe字段目录.json').read_text())
    target_differences={
        'missingFromStored':sorted(set(live_catalog['targets'])-set(stored['targets'])),
        'missingFromLive':sorted(set(stored['targets'])-set(live_catalog['targets'])),
        'schemaMismatch':sorted(k for k in set(stored['targets'])&set(live_catalog['targets']) if stored['targets'][k]['schema']!=live_catalog['targets'][k]['schema'])}
    result={'ok':not any(artifact_errors.values()) and schema['$defs']['deckprobeEnvelope']==native_schema and not any(target_differences.values()),
        'toolVersion':live_catalog.get('tool_version'),'targetCount':len(live_catalog['targets']),'artifactErrors':artifact_errors,
        'embeddedReportSchemaExact':schema['$defs']['deckprobeEnvelope']==native_schema,'targetDifferences':target_differences}
    print(json.dumps(result,ensure_ascii=False,indent=2));raise SystemExit(0 if result['ok'] else 1)

if __name__=='__main__':main()
