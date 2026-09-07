"""Content-addressed corpus and human-reviewed, independently sourced answers."""
from __future__ import annotations

import hashlib
import html
import io
import json
from pathlib import Path
import shutil
import struct
import xml.etree.ElementTree as ET
import zipfile

from .common import ROOT, CODE, atomic, digest, immutable, now, read, sha


def zip_bytes(parts):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for name, value in sorted(parts.items()):
            i = zipfile.ZipInfo(name, (2000, 1, 1, 0, 0, 0))
            i.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(i, value.encode() if isinstance(value, str) else value)
    return out.getvalue()


def pdf_bytes(pages=1, javascript=False, link=False):
    objects = [b"<< /Type /Catalog /Pages 2 0 R" + (b" /OpenAction << /S /JavaScript /JS (void\\(0\\)) >>" if javascript else b"") + b" >>",
               f"<< /Type /Pages /Count {pages} /Kids [{' '.join(str(i+3)+' 0 R' for i in range(pages))}] >>".encode()]
    for _ in range(pages):
        annotation = b" /Annots [<< /Type /Annot /Subtype /Link /Rect [0 0 20 20] /A << /S /URI /URI (https://deckprobe-canary.invalid/never-follow) >> >>]" if link else b""
        objects.append(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 72 72]" + annotation + b" >>")
    data, offsets = b"%PDF-1.4\n", [0]
    for n, obj in enumerate(objects, 1):
        offsets.append(len(data)); data += f"{n} 0 obj\n".encode() + obj + b"\nendobj\n"
    start = len(data)
    data += f"xref\n0 {len(objects)+1}\n0000000000 65535 f \n".encode()
    data += b"".join(f"{n:010d} 00000 n \n".encode() for n in offsets[1:])
    return data + f"trailer\n<< /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n".encode()


def ooxml(ext, count=1, external=False):
    if ext in {"docx", "dotx", "docm", "dotm"}:
        family, main = "word", "word/document.xml"
        content = '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>' + '<w:p><w:r><w:t>Acceptance</w:t></w:r></w:p>' * count + '</w:body></w:document>'
        typ = {"docx":"application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml", "dotx":"application/vnd.openxmlformats-officedocument.wordprocessingml.template.main+xml", "docm":"application/vnd.ms-word.document.macroEnabled.main+xml", "dotm":"application/vnd.ms-word.template.macroEnabledTemplate.main+xml"}[ext]
        parts = {main: content}
    elif ext in {"xlsx", "xltx", "xlsm", "xltm", "xlsb"}:
        family, main = "excel", "xl/workbook.xml"
        typ = {"xlsx":"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml", "xltx":"application/vnd.openxmlformats-officedocument.spreadsheetml.template.main+xml", "xlsm":"application/vnd.ms-excel.sheet.macroEnabled.main+xml", "xltm":"application/vnd.ms-excel.template.macroEnabled.main+xml", "xlsb":"application/vnd.ms-excel.sheet.binary.macroEnabled.main"}[ext]
        if ext == "xlsb":
            # BIFF12 empty workbook begin/end records; identity fixture, not deep parsing GT.
            main = "xl/workbook.bin"
            parts = {main: bytes([0x83, 0x01, 0, 0x84, 0x01, 0])}
        else:
            parts = {main:'<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>' + ''.join(f'<sheet name="Sheet{i}" sheetId="{i}" r:id="rId{i}"/>' for i in range(1,count+1)) + '</sheets></workbook>'}
            parts['xl/_rels/workbook.xml.rels'] = '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' + ''.join(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>' for i in range(1,count+1)) + '</Relationships>'
            for i in range(1,count+1):
                parts[f'xl/worksheets/sheet{i}.xml'] = '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData/></worksheet>'
    else:
        family, main = "powerpoint", "ppt/presentation.xml"
        typ = {"pptx":"application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml", "ppsx":"application/vnd.openxmlformats-officedocument.presentationml.slideshow.main+xml", "potx":"application/vnd.openxmlformats-officedocument.presentationml.template.main+xml", "pptm":"application/vnd.ms-powerpoint.presentation.macroEnabled.main+xml", "ppsm":"application/vnd.ms-powerpoint.slideshow.macroEnabled.main+xml", "potm":"application/vnd.ms-powerpoint.template.macroEnabled.main+xml"}[ext]
        parts = {main:'<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><p:sldIdLst>' + ''.join(f'<p:sldId id="{255+i}" r:id="rId{i}"/>' for i in range(1,count+1)) + '</p:sldIdLst><p:sldSz cx="9144000" cy="6858000"/></p:presentation>'}
        parts['ppt/_rels/presentation.xml.rels'] = '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' + ''.join(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide{i}.xml"/>' for i in range(1,count+1)) + '</Relationships>'
        for i in range(1,count+1):
            parts[f'ppt/slides/slide{i}.xml'] = '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"><p:cSld><p:spTree/></p:cSld></p:sld>'
    content_types = '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/' + main + '" ContentType="' + typ + '"/></Types>'
    parts['[Content_Types].xml'] = content_types
    parts['_rels/.rels'] = '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="' + main + '"/>' + ('<Relationship Id="external" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" TargetMode="External" Target="https://deckprobe-canary.invalid/never-follow"/>' if external else '') + '</Relationships>'
    return zip_bytes(parts), family


def add_source(home, data, ext, label, provenance, private=False):
    h = hashlib.sha256(data).hexdigest()
    p = Path(home) / "corpus" / "objects" / h / ("input." + ext)
    p.parent.mkdir(parents=True, exist_ok=True)
    if private:p.parent.chmod(0o700)
    if p.exists() and sha(p) != h:
        raise ValueError("Corpus cache was modified: " + h)
    if not p.exists():
        p.write_bytes(data)
        p.chmod(0o400 if private else 0o444)
    return {"id": label, "sha256": h, "bytes": len(data), "format": ext,
            "path": str(p), "private": private, "provenance": provenance}


def answer(source, key, check, expected, evidence, requirement="PRO-R03", options=None):
    a = {"id": source["id"] + ":" + key, "sourceSha256": source["sha256"], "caseId": source["id"],
         "format": source["format"], "question": f"{source['id']} 的 {key} 是否符合独立依据？",
         "check": check, "expected": expected, "evidence": evidence, "requirement": requirement,
         "options": options or ["-l", "deep", "-t", "@all"], "reviewStatus": "draft"}
    a["answerDigest"] = digest(a)
    return a


def independent_facts(data, ext):
    """Use separate PDF/XML parsers, never the product report."""
    facts, evidence = {}, {}
    if ext == "pdf":
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(data))
        facts['pdf.page_count'] = len(reader.pages)
        facts['security.encrypted'] = reader.is_encrypted
        evidence = {"method": "pypdf PdfReader (independent of Rust lopdf)", "location": "PDF /Root /Pages tree", "implementationSha256": sha(__file__)}
    elif ext=='xls':
        import xlrd
        book=xlrd.open_workbook(file_contents=data,on_demand=True)
        facts['excel.sheet_count']=book.nsheets
        evidence={'method':'xlrd BIFF/CFB parser (independent of Rust office_oxide)','location':'BIFF BoundSheet records','implementationSha256':sha(__file__)}
        book.release_resources()
    elif zipfile.is_zipfile(io.BytesIO(data)):
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            names = set(z.namelist())
            facts['security.has_macros'] = any(n.lower().endswith('vbaproject.bin') for n in names)
            if facts['security.has_macros']:
                # A real CFB signature, not merely a filename or macro-enabled suffix.
                vba=next(n for n in names if n.lower().endswith('vbaproject.bin'))
                if not z.read(vba).startswith(bytes.fromhex('d0cf11e0a1b11ae1')):
                    raise ValueError('Macro fixture lacks a CFB VBA project')
            if 'ppt/presentation.xml' in names:
                xml = ET.fromstring(z.read('ppt/presentation.xml'))
                facts['powerpoint.slide_count'] = len(xml.findall('.//{http://schemas.openxmlformats.org/presentationml/2006/main}sldId'))
            if 'xl/workbook.xml' in names:
                xml = ET.fromstring(z.read('xl/workbook.xml'))
                facts['excel.sheet_count'] = len(xml.findall('.//{http://schemas.openxmlformats.org/spreadsheetml/2006/main}sheet'))
            evidence = {"method": "Python zipfile + ElementTree", "location": "package part / XML element", "implementationSha256": sha(__file__)}
    return facts, evidence


def prepare_corpus(home, online=False):
    sources, answers, incidents, legacy = {}, [], [], []
    for file in sorted((ROOT / 'benchmark/suites').glob('*/cases.jsonl')):
        questions_file = file.parent / 'questions.jsonl'
        questions = [json.loads(x) for x in questions_file.read_text().splitlines() if x.strip()] if questions_file.exists() else []
        for line in file.read_text().splitlines():
            if not line.strip(): continue
            case = json.loads(line); ref = case.get('source', {})
            uri = ref.get('uri', '')
            if not uri or not Path(uri).is_file():
                incidents.append({"caseId": case['id'], "reason": "source unavailable"}); continue
            actual = sha(uri)
            if actual != ref.get('sha256'):
                incidents.append({"caseId": case['id'], "reason": "source SHA differs from historical approval"}); continue
            key = actual + ':' + Path(uri).suffix.lower()
            if key not in sources:
                sources[key] = add_source(home, Path(uri).read_bytes(), Path(uri).suffix.lstrip('.'), case['id'],
                    {"type":"existing-local", "uri":uri, "historicalSha256":actual}, private=True)
            legacy.append({"suite":file.parent.name,"case":case,"questions":[q for q in questions if q.get('caseId') == case['id']],
                           "sourceId":sources[key]['id'], "sourceUnchanged":True,
                           "reuseStatus":"needs-evidence-binding-review"})
    # Import historical facts and questions without silently re-approving a changed evaluator contract.
    atomic(Path(home)/'corpus/legacy-review.json', legacy)
    generated = []
    for count in (0,1,3,2000):
        generated.append((f'pdf-pages-{count}', 'pdf', pdf_bytes(count), {"pages":count}))
    generated.extend([('pdf-javascript','pdf',pdf_bytes(1,True),{"javascript":True}),
                      ('pdf-external-link','pdf',pdf_bytes(1,link=True),{"externalLink":True})])
    for ext in ['docx','dotx','docm','dotm','xlsx','xltx','xlsm','xltm','xlsb','pptx','ppsx','potx','pptm','ppsm','potm']:
        data, _ = ooxml(ext)
        generated.append((f'{ext}-minimal',ext,data,{"structureCount":1,"containsVbaProject":False}))
    for ext in ['pptx','xlsx']:
        for count in (0,3):
            generated.append((f'{ext}-count-{count}',ext,ooxml(ext,count)[0],{"structureCount":count}))
        generated.append((f'{ext}-external','%s'%ext,ooxml(ext,1,True)[0],{"externalRelationship":True}))
    for ext in ['key','numbers','pages']:
        generated.append((f'{ext}-legacy-xml',ext,zip_bytes({'index.apxl' if ext=='key' else 'index.xml':'<?xml version="1.0"?><document/>'}),{"legacyXML":True,"structuralFixtureOnly":True}))
    for ext in read(CODE/'config/policy.json')['declaredProfiles']:
        generated.append((f'{ext}-mismatch',ext,b'<!doctype html><html>type mismatch</html>',{"container":"html"}))
    generated.append(('pptx-truncated','pptx',ooxml('pptx')[0][:80],{"truncation":80}))
    for label, ext, data, params in generated:
        src = add_source(home,data,ext,label,{"type":"generated","generator":"acceptance.corpus/1","generatorSha256":sha(__file__),"parameters":params})
        sources[src['id']] = src
        evidence = {"method":"deterministic construction + independent inspection","parameters":params,"generatorSha256":sha(__file__)}
        if label.endswith('mismatch'):
            answers.append(answer(src,'malformed',{"type":"error"},'MALFORMED_INPUT',evidence))
        elif 'legacy-xml' in label:
            answers.append(answer(src,'unsupported',{"type":"error"},'UNSUPPORTED_FORMAT',evidence))
        elif label == 'pptx-truncated':
            answers.append(answer(src,'malformed',{"type":"error"},'MALFORMED_INPUT',evidence))
        else:
            facts, ev = independent_facts(data,ext)
            for name,value in facts.items():
                answers.append(answer(src,name,{"type":"target","target":name},value,ev))
    for public in read(CODE/'config/public-sources.json',[]):
        cached=Path(home)/'corpus/objects'/public['sha256']/('input.'+public['format'])
        if cached.exists():data=cached.read_bytes()
        elif online:
            from .releases import fetch
            data=fetch(public['url'])
        else:
            incidents.append({'caseId':public['id'],'reason':'public source not materialized; run prepare --online'});continue
        if hashlib.sha256(data).hexdigest()!=public['sha256']:raise ValueError('Public source changed')
        src=add_source(home,data,public['format'],public['id'],{'type':'public-pinned',**public})
        sources[src['id']]=src
        facts,ev=independent_facts(data,public['format'])
        for name,value in facts.items():answers.append(answer(src,name,{'type':'target','target':name},value,{**ev,'source':public['url']}))
    manifest = {"version":"1","sources":list(sources.values()),"incidents":incidents,
                "gaps":["Legacy Excel 独立 sheet/数据事实","有效签名 OOXML","加密与签名 PDF","真实旧 XML iWork","IWA 深层独立事实","全 target 语义与边界"]}
    manifest['cohortHash'] = digest(sorted((s['id'],s['sha256']) for s in manifest['sources']))
    atomic(Path(home)/'corpus/manifest.json',manifest)
    for a in answers:
        immutable(Path(home)/'answers/objects'/(a['answerDigest']+'.json'),a)
    atomic(Path(home)/'answers/index.json', {"version":"1","answers":answers})
    render_review(home, manifest, answers, legacy)
    return {"sources":len(manifest['sources']),"privateSources":sum(s['private'] for s in manifest['sources']),
            "draftAnswers":len(answers),"historicalCases":len(legacy),"incidents":incidents,"cohortHash":manifest['cohortHash']}


def approved(home, a):
    expected = {k:v for k,v in a.items() if k!='answerDigest'}
    if digest(expected) != a.get('answerDigest'):
        return False
    decision = read(Path(home)/'answers/decisions'/(a['answerDigest']+'.json'),{})
    return decision.get('decision')=='approved' and decision.get('answerDigest')==a['answerDigest'] and bool(decision.get('reviewer'))


def record_decisions(home, decision_file):
    rows = read(decision_file)
    known = {a['answerDigest']:a for a in read(Path(home)/'answers/index.json')['answers']}
    for row in rows:
        if row.get('answerDigest') not in known or row.get('decision') not in {'approved','rejected'} or not row.get('reviewer'):
            raise ValueError('Decision needs an exact current answer digest, reviewer and approved/rejected value')
        dest=Path(home)/'answers/decisions'/(row['answerDigest']+'.json')
        old=read(dest)
        stamp=row.get('recordedAt') or (old or {}).get('recordedAt') or now()
        immutable(dest,{**row,'recordedAt':stamp})


def render_review(home, manifest, answers, legacy):
    esc = lambda v: html.escape(json.dumps(v,ensure_ascii=False) if not isinstance(v,str) else v)
    rows = ''.join('<tr><td>'+esc(a['id'])+'<br><a href="../corpus/objects/'+a['sourceSha256']+'/input.'+a['format']+'">源文件</a><br><small>SHA-256: '+a['sourceSha256']+'</small></td><td>'+esc(a['expected'])+'</td><td>'+esc(a['evidence'])+'</td><td><code>'+a['answerDigest']+'</code></td><td>'+('已批准' if approved(home,a) else '待审核/未批准')+'</td></tr>' for a in answers)
    page = '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>DeckProbe GT 逐条审核</title><style>body{font:15px/1.6 system-ui;margin:40px;color:#17202a}table{border-collapse:collapse;width:100%}td,th{border:1px solid #ddd;padding:12px;vertical-align:top}code{overflow-wrap:anywhere}thead{background:#eef2f7}</style><h1>GT 逐条审核</h1><p>所有新答案均为草案。批准方案不等于批准下列答案。请用 ID 指定批准、拒绝或修改；每条决定绑定右侧内容哈希。</p><p>源文件 '+str(len(manifest['sources']))+' 份；历史用例 '+str(len(legacy))+' 条另见 legacy-review.json，尚未重新绑定新契约。</p><table><thead><tr><th>断言 ID</th><th>预期答案</th><th>独立依据</th><th>答案哈希</th><th>状态</th></tr></thead><tbody>'+rows+'</tbody></table><h2>未覆盖项</h2><ul>'+''.join('<li>'+esc(g)+'</li>' for g in manifest['gaps'])+'</ul></html>'
    atomic(Path(home)/'answers/review.html',page)
    atomic(Path(home)/'answers/decisions.template.json',[{"answerDigest":a['answerDigest'],"id":a['id'],"decision":"pending","reviewer":""} for a in answers])
