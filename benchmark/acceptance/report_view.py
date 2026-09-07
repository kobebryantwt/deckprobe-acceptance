"""Offline, evidence-bound presentation. Never changes grading or GT approval."""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

from .common import CODE, atomic, digest, now, read, sha
from .case_explanations import SUPPORTED, LEGACY, explain, protocol

ASSETS = CODE / 'presentation'


def report_template():
    template = (ASSETS / 'templates/report.template.html').read_text()
    before, rest = template.split('<!-- TEMPLATE_ONLY_BEGIN -->', 1)
    _, after = rest.split('<!-- TEMPLATE_ONLY_END -->', 1)
    return before + after


def check_id(value):
    return value.replace('/', '_').replace(':', '_')


def capture_context(folder, record, home=None):
    """Snapshot matching corpus/GT metadata; don't attach today's changed answers to old runs."""
    folder = Path(folder)
    existing = read(folder / 'report-context.json')
    if existing:
        if any(existing.get(k) != record.get(k) for k in ['runId', 'cohortHash', 'answersHash']):
            raise ValueError('Presentation context does not match the frozen run')
        return existing
    home = Path(home) if home else folder.parent.parent
    corpus = read(home / 'corpus/manifest.json', {})
    index = read(home / 'answers/index.json', {})
    decisions = {p.name: sha(p) for p in (home / 'answers/decisions').glob('*.json')}
    sources = corpus.get('sources', [])
    corpus_ok = bool(sources) and digest(sorted((s['id'], s['sha256']) for s in sources)) == record.get('cohortHash')
    answers_ok = bool(index) and digest({'answers': index, 'decisions': decisions}) == record.get('answersHash')
    context = {'version': 1, 'runId': record['runId'], 'cohortHash': record.get('cohortHash'),
               'answersHash': record.get('answersHash'), 'corpusBound': corpus_ok,
               'answersBound': answers_ok, 'sources': sources if corpus_ok else [],
               'answers': index.get('answers', []) if answers_ok and corpus_ok else [],
               'note': '仅附加与原运行哈希匹配的样本和答案；未匹配的上下文明确缺失。'}
    atomic(folder / 'report-context.json', context)
    return context


def link(value):
    if not isinstance(value, str):
        return None
    if value.startswith('/'):
        return Path(value).as_uri()
    return value if urlparse(value).scheme in {'https', 'http', 'file'} else None


def comparison_kind(check):
    # Some blocked answer rows were intentionally not executed; do not render the blocker as a product value.
    if isinstance(check.get('actual'),str) and check['actual'] in {'pending explicit answer approval', 'Private scan requires live isolation'}:
        return 'unexecuted'
    # Matching a draft is evidence of equality, never approval or a formal PASS.
    if check['status'] == 'blocked':
        return 'blocked'
    if check['status'] == 'failed':
        return 'different'
    match = (check.get('details') or {}).get('diagnosticMatch')
    if isinstance(match, bool):
        return 'matched' if match else 'different'
    if check['status'] == 'passed':
        return 'matched'
    return 'review'


def execution_reason(check):
    if check.get('actual') == 'pending explicit answer approval':
        return '本轮尚未执行：等待该条 GT 的明确审核。'
    if check.get('actual') == 'Private scan requires live isolation':
        return '本轮尚未执行：样本标记为私有；实时隔离与网络、进程监控未通过自检，因此未将文件交给待测系统。'
    return None


def target_observation(answer, data):
    """Distinguish parser errors and missing value from a legitimate JSON null."""
    if not answer or answer.get('check', {}).get('type') != 'target':
        return None
    try:
        report = json.loads(data.get('stdout', ''))
    except (ValueError, AttributeError):
        return None
    if not isinstance(report, dict):
        return None
    if report.get('status') == 'error':
        return {'kind': 'error', 'error': report.get('error'), 'status': 'error'}
    key = answer['check']['target']
    result = report.get('results', {}).get(key)
    if not isinstance(result, dict):
        return {'kind': 'missing', 'target': key, 'status': report.get('status')}
    return {'kind': 'target', 'valuePresent': 'value' in result, 'result': result}


def build_model(folder, envelope, context):
    folder = Path(folder)
    record = envelope['acceptance']
    sources = {s['id']: {**s, 'href': link(s['path']), 'originHref': link(s.get('provenance', {}).get('uri') or s.get('provenance', {}).get('url'))}
               for s in context.get('sources', [])}
    by_path = {s['path']: s['id'] for s in sources.values()}
    by_hash = {}
    for s in sources.values():
        by_hash.setdefault(s['sha256'], []).append(s['id'])
    answers = {check_id(a['id']): a for a in context.get('answers', [])}
    evidence = {}
    # Explanations must match the archived evaluator, not whatever happens to be
    # checked out today. Unknown historical implementations retain raw rules.
    implementation = read(folder / 'implementation-manifest.json', {})
    explained = all(implementation.get(name) in ({value} | LEGACY.get(name,set())) and
                    (folder / 'implementation' / name).is_file() and
                    sha(folder / 'implementation' / name) == implementation.get(name)
                    for name, value in SUPPORTED.items())
    policy = read(folder / 'implementation/config/policy.json', {})

    def evidence_data(name):
        if not isinstance(name, str) or urlparse(name).scheme or Path(name).is_absolute():
            return None
        if name not in evidence:
            path = (folder / name).resolve()
            if folder.resolve() not in path.parents or not path.is_file():
                return None
            try:
                value = read(path)
            except (ValueError, UnicodeError):
                return None
            evidence[name] = value
        return evidence.get(name)

    def referenced_sources(value, found):
        if isinstance(value, dict):
            for key, item in value.items():
                if key == 'caseId' and isinstance(item, str) and item in sources:
                    found.add(item)
                elif key == 'sourceSha256' and isinstance(item, str):
                    found.update(by_hash.get(item, []))
                else:
                    referenced_sources(item, found)
        elif isinstance(value, list):
            for item in value:
                referenced_sources(item, found)
        elif isinstance(value, str) and value in by_path:
            found.add(by_path[value])

    rows = []
    for check in record['checks']:
        answer = answers.get(check['id'])
        # Additional per-answer binding check, including false/zero type differences.
        if answer and (digest(answer['expected']) != digest(check.get('expected')) or
                       (check.get('details', {}).get('answerDigest') not in (None, answer['answerDigest']))):
            answer = None
        found = set()
        if answer and answer['caseId'] in sources:
            found.add(answer['caseId'])
        referenced_sources(check.get('command', []), found)
        refs = []
        for name in check.get('evidence', []):
            data = evidence_data(name)
            if data is not None:
                referenced_sources(data, found)
                refs.append(name)
        # Some integration assertions intentionally omit the command; IDs bind their fixture.
        for sid in sources:
            if check['id'].endswith('_' + sid):
                found.add(sid)
        baseline = []
        if check['requirement'] == 'PRO-R07' and '_parity_' in check['id']:
            for sid in sorted(found):
                name = 'evidence/native-' + sid + '.json'
                if evidence_data(name) is not None:
                    baseline.append(name)
        observation = next((v for name in refs if (v := target_observation(answer, evidence.get(name))) is not None), None)
        row = {**check, 'comparison': comparison_kind(check), 'answer': answer, 'targetObservation': observation,
               'sourceIds': sorted(found), 'evidence': refs, 'baselineEvidence': baseline, 'executionReason': execution_reason(check)}
        if check['id'] == 'private_sources_protected':
            row['sourceIds'] = sorted(s['id'] for s in sources.values() if s.get('private'))
        if check['id'] == 'native_install' and evidence_data('evidence/version.json') is not None:
            row['evidence'] = [*refs, 'evidence/version.json']
        row['protocol'] = explain(row, policy, evidence) if explained else protocol(
            '历史检查', row['title'], ['该版本的执行实现尚未适配可读说明。'],
            ['保留原始预期与实际记录，不能从标题推断额外测试步骤。'], [],
            '仅重建页面；原始判定不变。', showExpected=True, expectedLabel='归档预期记录')
        rows.append(row)
    return {'version': 1, 'runId': record['runId'], 'targetVersion': record['targetVersion'],
            'createdAt': record['createdAt'], 'mode': record['mode'],
            'quality': envelope['qualitySummary'], 'counts': envelope.get('counts', {}),
            'context': {'corpusBound': context.get('corpusBound', False), 'answersBound': context.get('answersBound', False),
                        'protocolBound': explained},
            'rows': rows, 'sources': list(sources.values()), 'evidence': evidence,
            'documents':read(folder/'evidence/r01/documents.json',{})}


def render(folder, envelope, home=None):
    folder = Path(folder)
    context = capture_context(folder, envelope['acceptance'], home)
    model = build_model(folder, envelope, context)
    # Inert JSON data in HTML: HTML-sensitive characters cannot terminate the script element.
    payload = json.dumps(model, ensure_ascii=False, separators=(',', ':')).replace('&', '\\u0026').replace('<', '\\u003c').replace('>', '\\u003e')
    template = report_template()
    page = template.replace('/*REPORT_CSS*/', (ASSETS / 'report.css').read_text())
    page = page.replace('/*REPORT_JS*/', (ASSETS / 'report.mjs').read_text()).replace('REPORT_DATA_JSON', payload)
    atomic(folder / 'report.html', page)
    atomic(folder / 'case-protocols.json', {'version': 1, 'runId': model['runId'],
        'implementationBound': model['context']['protocolBound'],
        'note': '呈现说明；不新增执行证据，不改变原始判定或 GT。',
        'cases': {r['id']: r['protocol'] for r in model['rows']}})
    atomic(folder / 'presentation.json', {'version': 1, 'renderedAt': now(), 'runId': model['runId'],
        'renderer': {str(p.relative_to(CODE)): sha(p) for p in [Path(__file__), CODE/'case_explanations.py', *sorted(ASSETS.iterdir())] if p.is_file()},
        'note': '仅重建呈现。原始验收结论、批准状态及机器报告不变。'})
