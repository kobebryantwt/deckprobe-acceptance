"""R01: explicit expected/observed fields, with archived evidence for each claim."""
from __future__ import annotations
import json
import hashlib
from pathlib import Path
import re
import shutil

from .common import atomic, digest, now, process, read, sha


def refresh_signature_audit(packages):
    """Preparation-stage network operation, bound to the frozen installed dependency tree."""
    base=Path(packages['folder'])
    if sha(base/'package-lock.json')!=packages['lockSha256']:
        raise ValueError('Dependency lock changed before signature audit')
    for name,h in packages['runtimeFiles'].items():
        if not (base/name).is_file() or sha(base/name)!=h:
            raise ValueError('Installed dependency changed before signature audit: '+name)
    result=process(['npm','audit','signatures'],base,180)
    bound={'version':1,'createdAt':now(),'packageIdentity':packages['id'],
           'lockSha256':packages['lockSha256'],'runtimeManifestSha256':digest(packages['runtimeFiles']),
           'result':result,'resultSha256':digest(result)}
    atomic(base/'signature-audit-lock.json',bound)
    return bound


def field(label,expected,actual,expected_evidence=None,actual_evidence=None,status=None,note=None):
    if status is None:
        status='blocked' if actual is None else ('passed' if type(actual) is type(expected) and actual==expected else 'failed')
    return {'label':label,'expected':expected,'actual':actual,'status':status,
            'expectedEvidence':expected_evidence or [],'actualEvidence':actual_evidence or [],'note':note}


def aggregate(rows):
    states={r['status'] for r in rows}
    if 'failed' in states:return 'failed'
    if 'blocked' in states or not states:return 'blocked'
    if 'review' in states:return 'review'
    return 'passed'


def pointer(path,locator='',label='证据'):
    return {'path':path,'locator':locator,'label':label}


def provenance_fields(asset,release,verification,evidence_path):
    """Use verified output, never an unverified base64 payload or an exit code alone."""
    certificate=verification.get('signature',{}).get('certificate',{})
    statement=verification.get('statement',{})
    subjects=statement.get('subject',[])
    subject=next((s for s in subjects if s.get('name')==asset['name']),{})
    repo='https://github.com/'+release['repository']
    base='/verificationResult/'
    def row(label,expected,actual,path):
        return field(label,expected,actual,actual_evidence=[pointer(evidence_path,base+path,'已验签声明')])
    return [row('repository · 源仓库',repo,certificate.get('sourceRepositoryURI'),'signature/certificate/sourceRepositoryURI'),
            row('subject · 资产名称',asset['name'],subject.get('name'),'statement/subject'),
            row('subject · SHA-256',asset['sha256'],subject.get('digest',{}).get('sha256'),'statement/subject'),
            row('commit · 源代码提交',release['commit'],certificate.get('sourceRepositoryDigest'),'signature/certificate/sourceRepositoryDigest'),
            row('tag · 源代码引用','refs/tags/'+release['tag'],certificate.get('sourceRepositoryRef'),'signature/certificate/sourceRepositoryRef')]


def signature_counts(result):
    text=result.get('stdout','')
    def number(pattern):
        m=re.search(pattern,text);return int(m.group(1)) if m else None
    return {'audited':number(r'audited (\d+) packages?'),
            'signatures':number(r'(\d+) packages? have verified registry signatures'),
            'attestations':number(r'(\d+) packages? have verified attestations')}


def license_text_sha(text):
    # Windows release archives use CRLF. Preserve every other character.
    normalized=text.replace('\r\n','\n').replace('\r','\n')
    return hashlib.sha256(normalized.encode('utf-8')).hexdigest()


def collect(folder,target):
    folder=Path(folder);dest=folder/'evidence/r01';dest.mkdir(parents=True,exist_ok=True)
    release=target['release'];locked_release=release['release'];base=Path(release['folder'])
    packages=target.get('packages');groups_by_id={};documents={}

    def save(name,data):
        path=dest/name;atomic(path,data);return str(path.relative_to(folder))

    def document(path,expected_hash,name):
        path=Path(path)
        if not path.is_file() or not expected_hash:return None
        if sha(path)!=expected_hash:raise ValueError('R01 evidence file changed: '+str(path))
        output=dest/name;output.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,output)
        ref=str(output.relative_to(folder));text=output.read_bytes().decode('utf-8')
        documents[ref]={'text':text,'sha256':sha(output),'normalizedTextSha256':license_text_sha(text),
                        'lineEndings':'CRLF' if '\r\n' in text else 'LF'}
        return ref

    lock_ref=save('release-lock.json',locked_release)
    assets={a['name']:a for a in release['assets']}
    archives=[a for a in assets.values() if a['name'].startswith('deckprobe-') and a['name'].endswith(('.tar.gz','.zip'))]
    checksums={};checksum_refs={}
    for name,a in assets.items():
        if not (name.endswith('.sha256') or name=='sha256.sum'):continue
        ref=document(base/name,a['sha256'],'checksums/'+name)
        for n,line in enumerate((base/name).read_text().splitlines(),1):
            fields=line.split()
            if len(fields)<2:continue
            value,key=fields[0],fields[-1].lstrip('*')
            checksums.setdefault(key,[]).append(value)
            checksum_refs.setdefault(key,[]).append(pointer(ref,'line '+str(n),'发布方 checksum'))
    groups=[]
    for a in archives:
        values=checksums.get(a['name'],[]);actual=sha(base/a['name'])
        expected=values[0] if values else None
        row=field('安装包 SHA-256',expected,actual,checksum_refs.get(a['name']),
                  [pointer(lock_ref,'/assets','已冻结的发布资产信息')],
                  status='blocked' if not values else ('passed' if all(v==actual for v in values) else 'failed'),
                  note='实际值由本轮读取安装包字节计算；同时核对独立 .sha256 与汇总清单中的对应记录。')
        groups.append({'title':a['name'],'rows':[row]})
    api_rows=[]
    for a in assets.values():
        api_rows.append(field(a['name'],a.get('digest'),'sha256:'+sha(base/a['name']),
                             [pointer(lock_ref,'/assets','GitHub 发布 API 摘要')],
                             status='blocked' if not a.get('digest') else ('passed' if a['digest']=='sha256:'+sha(base/a['name']) else 'failed'),
                             note='这一层核对 GitHub 记录的附件摘要；不替代平台安装包 checksum 或构建来源验签。'))
    groups.append({'title':'全部发布附件 · GitHub 摘要核对','rows':api_rows})
    groups_by_id['release_checksums']={'summary':f"逐项核对 {len(archives)} 个平台安装包 checksum；另核对 {len(assets)} 个发布附件的 GitHub 摘要",
        'scope':'安装包 checksum 与附件完整性分开统计，附件数量不是通过证据。','groups':groups}

    # Archive both the raw verifier record and decoded, cryptographically verified fields.
    attestations=read(base/'attestation-refresh.json',release.get('provenance',[]))
    att_raw=save('attestation-processes.json',attestations)
    indexed={a['asset']:a for a in attestations};groups=[]
    for asset in archives:
        att=indexed.get(asset['name'],{});values=[]
        try:values=json.loads(att.get('stdout',''))
        except (ValueError,TypeError):pass
        if not isinstance(values,list):values=[]
        chosen=next((v for v in values if any(s.get('name')==asset['name'] for s in v.get('verificationResult',{}).get('statement',{}).get('subject',[]))),None)
        if chosen is None:chosen=values[0] if values and isinstance(values[0],dict) else {}
        verified=chosen.get('verificationResult',{})
        ref=save('attestation-'+asset['name']+'.json',{'verificationResult':verified,'asset':asset['name'],
                 'verificationCommand':att.get('command'),'verifiedAt':att.get('startedAt'),'exitCode':att.get('exitCode')})
        command=att.get('command',[])
        def argument(flag):
            try:return command[command.index(flag)+1]
            except (ValueError,IndexError):return None
        rows=[field('验签进程退出码',0,att.get('exitCode'),actual_evidence=[pointer(ref,'/exitCode','验签执行记录')]),
              field('验签约束 --repo',locked_release['repository'],argument('--repo'),actual_evidence=[pointer(ref,'/verificationCommand')]),
              field('验签约束 --source-digest',locked_release['commit'],argument('--source-digest'),actual_evidence=[pointer(ref,'/verificationCommand')])]
        rows.extend(provenance_fields(asset,locked_release,verified,ref))
        for row in rows:
            if not row['expectedEvidence']:row['expectedEvidence']=[pointer(lock_ref,'/commit 与 /assets','冻结的 release/tag/commit')]
        groups.append({'title':asset['name'],'rows':rows})
    groups_by_id['release_provenance']={'summary':f'{len(archives)} 个平台包：逐项展示 repository、subject 名称/摘要、commit 和 tag',
        'scope':'字段取自 gh 验签成功后输出的 verificationResult；解码出字段本身不等于验签。原始进程记录另行归档。',
        'groups':groups,'evidence':[att_raw]}

    v=tuple(map(int,locked_release['tag'].lstrip('v').split('.')))
    expected_license='Apache-2.0' if v>=(2,5,0) else 'MIT'
    canonical={}
    for name in ['LICENSE','NOTICE']:
        snapshot=release.get('sourceSnapshots',{}).get(name,{})
        if snapshot.get('path'):
            canonical[name]=document(snapshot['path'],snapshot.get('sha256'),'source/'+name)
    license_groups=[]

    def license_rows(component,root,files,expected,metadata=None):
        rows=[]
        if metadata is not None:
            ref=document(root/'package.json',files.get('package.json'),component+'/package.json')
            rows.append(field('package.json · license',expected,metadata.get('license'),actual_evidence=[pointer(ref,'/license','已安装包元数据')] if ref else []))
        for name in (['LICENSE','NOTICE'] if expected=='Apache-2.0' else ['LICENSE']):
            matches=[n for n in files if Path(n).name.upper()==name]
            match=matches[0] if matches else None
            actual_ref=document(root/match,files[match],component+'/'+name) if match else None
            rows.append(field(name+' · 随包文件存在',True,bool(actual_ref),actual_evidence=[pointer(actual_ref,'',name+' 原文')] if actual_ref else [],
                              note='这是随实际发布包分发的文件，不是仓库中另行下载的文件。'))
            if not actual_ref:continue
            source_ref=canonical.get(name) if component!='npm-mcp' else None
            if source_ref:
                rows.append(field(name+' · 正文一致性（统一换行符后的 SHA-256）',documents[source_ref]['normalizedTextSha256'],documents[actual_ref]['normalizedTextSha256'],
                    [pointer(source_ref,'','固定 commit 的 '+name)],[pointer(actual_ref,'','随包 '+name)],
                    note='仅允许 LF / CRLF 换行符差异，不删除空格、版权或其他正文。原始字节 SHA-256 与完整原文均保留。'))
            elif expected=='MIT' and name=='LICENSE':
                text=documents[actual_ref]['text']
                markers=['MIT License','Permission is hereby granted, free of charge','THE SOFTWARE IS PROVIDED "AS IS"']
                rows.append(field('MIT LICENSE · 必需文本片段',markers,[m for m in markers if m in text],actual_evidence=[pointer(actual_ref,'','完整许可证原文')],
                                  note='按已批准的 MIT 声明核对三个关键文本片段；不作法律完整性结论。'))
            else:
                rows.append(field(name+' · 独立预期文本', '已冻结的对应版本原文',None,status='blocked'))
        if expected=='MIT':
            rows.append(field('NOTICE · 本版本规则','当前 MIT 文件分发规则未要求 NOTICE','当前 MIT 文件分发规则未要求 NOTICE',note='不把未要求的 NOTICE 缺失计为失败。'))
        return rows

    for archive,files in release['extracted'].items():
        license_groups.append({'title':'引擎 '+locked_release['tag']+' · '+archive,
            'rows':license_rows(archive,base/'unpacked'/archive,files,expected_license)})
    if packages:
        npm_base=Path(packages['folder'])
        for package,component,expected in [('@deckflow/deckprobe','npm-js',expected_license),('@deckflow/deckprobe-mcp','npm-mcp','MIT' if packages['mcp']['version']=='0.1.1' else None)]:
            root=npm_base/'node_modules'/package;prefix='node_modules/'+package+'/'
            files={n[len(prefix):]:h for n,h in packages['runtimeFiles'].items() if n.startswith(prefix)}
            metadata=read(root/'package.json',{})
            rows=license_rows(component,root,files,expected,metadata) if expected else [field('版本许可规则','已审核的许可规则',None,status='blocked')]
            license_groups.append({'title':package+'@'+metadata.get('version','未知版本'),'rows':rows})
    groups_by_id['release_licenses']={'summary':f'核对 {len(license_groups)} 个发布组件的许可证声明、随包 LICENSE / NOTICE 与正文',
        'scope':'引擎与 JS 包按版本核对；MCP 0.1.1 单独核对 MIT。此项不证明第三方披露清单已完整。','groups':license_groups}

    if packages:
        audit_lock=read(Path(packages['folder'])/'signature-audit-lock.json',{})
        bound=(audit_lock.get('packageIdentity')==packages['id'] and audit_lock.get('lockSha256')==packages['lockSha256']
               and audit_lock.get('runtimeManifestSha256')==digest(packages['runtimeFiles'])
               and audit_lock.get('resultSha256')==digest(audit_lock.get('result')))
        result=audit_lock.get('result',{}) if bound else {}
        ref=save('npm-signatures.json',audit_lock)
        counts=signature_counts(result)
        rows=[field('审计日志与冻结依赖绑定',True,bound,status='passed' if bound else 'blocked',actual_evidence=[pointer(ref,'/lockSha256 与 /runtimeManifestSha256')]),
              field('npm audit signatures · 退出码',0,result.get('exitCode'),actual_evidence=[pointer(ref,'/result/exitCode')],note='0 是命令执行成功的退出码，不是包数量。'),
              field('registry 签名通过数量',counts['audited'],counts['signatures'],actual_evidence=[pointer(ref,'/result/stdout')],
                    status='blocked' if not counts['audited'] or counts['signatures'] is None else ('passed' if counts['audited']==counts['signatures'] else 'failed'),
                    note='预期为本次命令所审计的全部包；包数量来自同一份原始 stdout。')]
        groups_by_id['npm_signatures']={'summary':f"npm 审计 {counts['audited'] if counts['audited'] is not None else '未知'} 个包；registry 签名已验证 {counts['signatures'] if counts['signatures'] is not None else '未知'} 个",
            'scope':f"同一次命令另外报告 {counts['attestations'] if counts['attestations'] is not None else '未知'} 个包通过来源证明验证。签名与来源证明分别计数，不能混为全部包都通过来源证明。",
            'groups':[{'title':'已安装依赖 · npm audit signatures','rows':rows}],
            'log':{'command':result.get('command'),'stdout':result.get('stdout'),'stderr':result.get('stderr'),
                   'startedAt':result.get('startedAt'),'cwd':result.get('cwd')},'evidence':[ref]}

    result={}
    for id,audit in groups_by_id.items():
        rows=[r for g in audit['groups'] for r in g['rows']]
        audit['counts']={s:sum(r['status']==s for r in rows) for s in ['passed','failed','blocked','review']}
        audit['status']=aggregate(rows)
        evidence_ref=save(id+'.json',audit)
        result[id]={'audit':audit,'evidence':evidence_ref,'status':audit['status']}
    save('documents.json',documents)
    return result
