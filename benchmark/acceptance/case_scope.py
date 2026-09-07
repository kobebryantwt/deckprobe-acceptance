"""Curate GT scope from case intent; no file parsing or answer/review mutations.

Legacy suite questions establish intent only, never confer approval on new facts.
The frozen extraction inventory is kept intact as reference evidence.
"""
import json
from pathlib import Path
from .common import ROOT, DEFAULT_HOME, atomic, locked
from .maintenance import modules, sync

IMAGE='images.package.image_part_count'
LINKS={'security.has_external_relationships','links.external_reference_count','links.external_unique_targets'}
# Explicit reviewed source-case intent; never select by a result being easy to pass.
LEGACY_KEYS={
 'docx-summary-1k-budget':set(), 'formats-discovery':set(), 'strict-unresolved':set(),
 'pptx-repeat-exact-slide-count':{'powerpoint.slide_count'},
 'pdf-html-masquerade':set(), 'pptx-as-docx':set(), 'unsupported-csv':set(),
 'encrypted-pptx-password':{'security.encrypted'},
 'signed-pdf':{'security.signature_count'}, 'linked-pdf':LINKS,
 'xref-stream-pdf':{'pdf.page_count'}, 'large-pdf':{'file.size_bytes','pdf.page_count'},
 'repairable-pdf':{'pdf.page_count'}, 'empty-pptx':{'powerpoint.slide_count',IMAGE},
 'webp-svg-pptx':{IMAGE,'links.external_reference_count'},
 'embedded-pptx':{'security.has_embedded_files'},
 'animation-pptx':{'powerpoint.slides_with_timing_count'},
 'feedback-xlsx':{'excel.sheet_count',IMAGE}|LINKS,
 'defined-name-xlsx':{'excel.sheet_count','excel.defined_name_count','excel.shared_string_count'},
 'image-only-docx':{IMAGE,'word.paragraph_count'},
 'commented-docx':{'word.paragraph_count','word.table_count',IMAGE}|LINKS,
 'legacy-chinese-doc':{'word.page_count','word.word_count','word.character_count'},
 'keynote-transitions':{'powerpoint.transition_count'},
 'numbers-old':set(),
 'key-deep':{IMAGE,'file.size_bytes'}, 'numbers-deep':{IMAGE,'file.size_bytes'},
 'pages-deep':{IMAGE,'file.size_bytes'},
 'legacy-doc-deep':{'word.page_count','word.word_count','word.character_count'},
 'legacy-ppt-deep':{'powerpoint.slide_count'},
 'xlsx-deep':{'excel.sheet_count','excel.table_count',IMAGE}|LINKS,
 'encrypted-docx':{'security.encrypted'}, 'encrypted-xlsx':{'security.encrypted'},
 'unsupported-html':set(), 'unsupported-rtf':set(), 'unsupported-unknown':set(),
}


def primary(s,a):
    for c in s.get('purpose',{}).get('checks',[]):
        if c.get('factKey')==a.get('factKey') and c.get('factKey'):return True
        if a.get('factKey') in c.get('factKeys',[]):return True
        if c.get('type') and c.get('type')==a.get('check',{}).get('type') and (not c.get('target') or c['target']==a['check'].get('target')):return True
    return False


def plan(p):
    questions={}
    for path in sorted((ROOT/'benchmark/suites').glob('*/questions.jsonl')):
        for line in path.read_text().splitlines():
            q=json.loads(line)
            questions.setdefault(q.get('caseId'),[]).append({'question':q['question'],'source':str(path.relative_to(ROOT))+'#'+q['questionId']})
    scopes=[];purposes={}
    for s in p['samples']:
        keys=LEGACY_KEYS.get(s['id'])
        for a in s['answers']:
            selected=(a.get('kind')!='fact' or (a.get('factKey') in keys if keys is not None else primary(s,a)))
            scopes.append({'answerId':a['id'],'mode':'case' if selected else 'reference',
                'reason':'对应此样本的已登记用途 / 原用例定义。' if selected else '通用取证与当前样本主验证目的无关，保留参考，不列入审核或执行。'})
        if keys is not None:
            original=questions.get(s['id'],[])
            # Only replace the prior generated generic placeholder; preserve edited purposes.
            old=s.get('purpose',{})
            if old.get('checks')==[{'label':'补齐与原用例目的对应的独立事实 / 状态依据'}]:
                chosen=[a for a in s['answers'] if a.get('factKey') in keys]
                checks=[{'label':a['question'],'factKey':a['factKey']} for a in chosen]
                checks += [{'label':q['question'],'note':'原用例要求，需核对相应 GT 和执行证据；参考：'+q['source']} for q in original]
                if not checks:checks=[{'label':'需核对该样本的原始用途和专用检查','note':'没有证据支持通用内容计数是本样本目标，暂不补造 GT。'}]
                purposes[s['id']]={'summary':'按原用例目的维护专用 GT；未接入的检查继续显示缺口。','checks':checks,'source':'legacy-suite-intent'}
    return scopes,purposes


def run(home=DEFAULT_HOME):
    home=Path(home);Store,_=modules();store=Store(home/'casework');before=store.get('deckprobe')
    # This is a one-time curated migration, never overwrite later user scope choices.
    if before.get('scopeSchema')==1:raise ValueError('已按用途整理；后续请在页面维护范围，避免覆盖人工选择。')
    backup=home/'migrations/case-scope-v1';backup.mkdir(parents=True,exist_ok=True);backup.chmod(0o700)
    import sqlite3
    with store.connect() as source, sqlite3.connect(backup/'before.sqlite3') as dest:source.backup(dest)
    (backup/'before.sqlite3').chmod(0o600)
    scopes,purposes=plan(before)
    p=store.act('deckprobe',{'revision':before['revision'],'action':'set_case_scopes','actor':'Codex · 按样本用途整理',
                           'note':'按用户要求减少无关 GT；原答案、审批和取证全部保留。','scopes':scopes,'purposeUpdates':purposes})
    assert all(old['answers']==new['answers'] for old,new in zip(before['samples'],p['samples']))
    with locked(home):sync(home)
    summary={'samples':len(p['samples']),'inCase':sum(x['mode']=='case' for x in scopes),
             'reference':sum(x['mode']=='reference' for x in scopes),'answersAndReviewsUnchanged':True,
             'withoutCaseGT':sum(not any(p['answerScopes'][a['id']]['mode']=='case' for a in s['answers']) for s in p['samples'])}
    atomic(backup/'summary.json',summary);print(json.dumps(summary))


if __name__=='__main__':run()
