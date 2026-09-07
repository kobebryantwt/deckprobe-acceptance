"""Audit fixture intent, add independently supported drafts, preserve existing GT.

This is a DeckProbe adapter, not a generic Casework feature extractor. Only the
listed public fixtures with their original content bindings are inspected.
"""
import json
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

from .common import DEFAULT_HOME, atomic, digest, locked, sha
from .maintenance import modules, sync

EXT = 'security.has_external_relationships'
JS = 'security.has_javascript'
COUNT = {'pdf':'pdf.page_count','pptx':'powerpoint.slide_count','xlsx':'excel.sheet_count'}


def criterion(label, target=None, kind='target', note=''):
    value={'label':label}
    if target:value.update(type=kind,target=target)
    elif kind=='error':value['type']='error'
    if note:value['note']=note
    return value


def inspect_public(s):
    """No network, scripts or product invocation. No general claim for arbitrary PDF."""
    assert not s['private'] and sha(s['path'])==s['sha256']
    if s['format']=='pdf':
        from pypdf import PdfReader, __version__
        reader=PdfReader(s['path'])
        root=reader.trailer['/Root']; links=[]
        for i,page in enumerate(reader.pages):
            for j,ref in enumerate(page.get('/Annots',[])):
                annot=ref.get_object();action=annot.get('/A',{})
                if action.get('/S')=='/URI':
                    links.append({'location':f'/Root /Pages → page[{i}] /Annots[{j}] /A /URI',
                                  'uri':str(action['/URI'])})
        action=root.get('/OpenAction',{})
        javascript=action.get('/S')=='/JavaScript' and '/JS' in action
        return {'method':f'pypdf {__version__}：读取页面链接注释与 Catalog OpenAction',
                'links':links,'linkCount':len(links),'javascript':javascript,
                'javascriptLocation':'/Root /OpenAction /S 与 /JS',
                'javascriptText':str(action.get('/JS','')),
                'scope':'仅用于本次简单构造样本；不是任意 PDF 的全路径外链 / JavaScript 扫描器。'}
    with zipfile.ZipFile(s['path']) as z:
        links=[]
        for name in sorted(z.namelist()):
            if name.endswith('.rels'):
                xml=ET.fromstring(z.read(name))
                for rel in xml:
                    if rel.get('TargetMode')=='External':
                        links.append({'location':name+' / Relationship[@Id="'+rel.get('Id','')+'"]',
                                      'uri':rel.get('Target'),'relationshipType':rel.get('Type')})
        result={'method':'Python zipfile + ElementTree：检查全部 .rels 的 TargetMode="External"',
                'links':links,'linkCount':len(links)}
        if 'word/document.xml' in z.namelist():
            result['method']='Python zipfile + ElementTree：读取 word/document.xml，统计 w:p 段落元素'
            xml=ET.fromstring(z.read('word/document.xml'))
            result['paragraphCount']=len(xml.findall('.//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p'))
        return result


def intent(s):
    id=s['id'];fmt=s['format'];targets={a['check'].get('target') for a in s['answers']}
    checks=[];summary=''
    if s['private']:
        planned={'signed-pdf':('核验历史签名样本',[criterion('是否包含数字签名','security.has_digital_signature'),criterion('签名数量','security.signature_count')]),
                 'linked-pdf':('核验历史外链样本',[criterion('是否存在外链',EXT)]),
                 'embedded-pptx':('核验嵌入对象样本',[criterion('是否存在嵌入文件','security.has_embedded_files')])}
        if 'encrypted' in id:summary='核验历史加密样本';checks=[criterion('是否加密','security.encrypted')]
        elif id in planned:summary,checks=planned[id]
        else:summary='真实文档补充覆盖：需先核对原用例目的与独立依据';checks=[criterion('补齐与原用例目的对应的独立事实 / 状态依据')]
        summary+='。这是待核实的用途，不能仅凭文件名确认特征；需逐项建立独立依据，私有扫描仍受隔离条件限制。'
    elif id.endswith('-mismatch') or id=='pptx-truncated':
        summary='验证内容与后缀不符或包被截断时的错误行为。';checks=[criterion('是否返回约定的输入错误',kind='error',note='错误码仍需人工审核对应版本契约；不是正常格式内容样本。')]
    elif 'legacy-xml' in id:
        summary='验证旧 XML iWork 最小结构的限制行为。';checks=[criterion('旧结构是否按契约拒绝',kind='error'),criterion('真实历史 iWork 文件的限制行为',note='当前只是构造的最小结构，不能替代历史作者工具导出的真实文件。')]
    elif id in {'pdf-external-link','pptx-external','xlsx-external'}:
        summary='验证能否识别文件中的外部链接，而不是仅检查页数或加密标记。'
        checks=[criterion('是否存在外链',EXT),criterion('外链数量和地址',note='独立结构核验：1 条外链；数量及地址见主要 GT 的依据。当前发布目录只有存在性字段，没有数量或地址集合接口，不能自动对照。'),criterion('扫描时不访问外链',note='归属 R02，需要独立网络监控；静态 GT 不能证明没有联网。')]
    elif id=='pdf-javascript':
        summary='验证能否识别打开文档时的 JavaScript 动作。'
        checks=[criterion('是否包含 JavaScript',JS),criterion('扫描时不执行 JavaScript',note='归属 R02，需运行期监控，不能由存在性检测推断。')]
    elif fmt=='xlsb':
        summary='验证 XLSB 二进制工作簿的格式与深层解析限制；宏检测只是辅助项。'
        checks=[criterion('识别 XLSB 格式及 profile','document.format_profile'),criterion('受限 target 的状态与原因',note='需按发布契约独立建立限制行为 GT；不能用“没有宏”代表 XLSB 已覆盖。')]
    elif 'security.has_digital_signature' in targets:
        summary='识别真实数字签名结构并核对签名数量；证书信任与签名存在性分开。'
        checks=[criterion('是否包含数字签名','security.has_digital_signature'),criterion('签名数量','security.signature_count')]
    elif any(a['check'].get('target')=='security.encrypted' and a['expected'] is True for a in s['answers']):
        summary='验证需要打开密码的 PDF 能否被识别为加密。';checks=[criterion('是否加密','security.encrypted')]
    elif id=='poi-simplemacro-xlsm':
        summary='验证实际包含 VBA 项目的宏工作簿。';checks=[criterion('是否包含宏','security.has_macros')]
    elif fmt in {'docx','dotx','docm','dotm'}:
        summary='核对最小 Word 结构中的段落数量。';checks=[criterion('段落数量','word.paragraph_count')]
    else:
        count=next((t for t in targets if t in {'pdf.page_count','excel.sheet_count','powerpoint.slide_count'}),None)
        summary='核对构造或独立解析得到的页面 / 工作表 / 幻灯片数量。'
        if count:checks=[criterion('结构数量',count)]
        else:summary='核验格式基本结构及已登记事实。';checks=[criterion('基本结构的独立答案需补齐')]
    if not s['private'] and id.endswith('-minimal') and fmt in {'docm','dotm','xlsm','xltm','pptm','ppsm','potm'}:
        summary+='该文件虽使用宏格式后缀，但内部没有 VBA 项目，属于“无宏”反例。'
        checks.append(criterion('宏格式后缀不应被误判为含宏','security.has_macros'))
    if id in {'pdf-pages-1','pptx-minimal','xlsx-minimal'}:
        checks.append(criterion('无外链对照',EXT))
        if id=='pdf-pages-1':checks.append(criterion('无 JavaScript 对照',JS))
    if id=='pdf-pages-2000':checks.append(criterion('大页数下的预算与性能',note='页数正确不能代替预算 / 性能验证，需 R06 独立运行记录。'))
    return {'summary':summary,'checks':checks}


def run(home=DEFAULT_HOME):
    home=Path(home).resolve();Store,_=modules();store=Store(home/'casework')
    before=store.get('deckprobe');old_answers={a['id']:a for s in before['samples'] for a in s['answers']}
    catalog_id=json.loads((home/'declarations.json').read_text())['catalogId']
    catalog=json.loads((home/'catalogs'/catalog_id/'catalog.json').read_text())
    folder=home/'purpose-audits'/digest({'revision':before['revision'],'code':sha(__file__)})[:20]
    folder.mkdir(parents=True,exist_ok=True)
    p=before;new=[];conflicts=[];rows=[]
    def act(sample,action,**kw):
        nonlocal p
        p=store.act('deckprobe',{'revision':p['revision'],'actor':'Codex · 用途覆盖校准',
            'sampleId':sample['id'],'action':action,'note':'按样本用途补齐主要检查；保留已有 GT 与审批。',**kw})
    plans={'pdf-external-link':[(EXT,True)],'pptx-external':[(EXT,True)],'xlsx-external':[(EXT,True)],
           'pdf-javascript':[(JS,True)],'pdf-pages-1':[(EXT,False),(JS,False)],
           'pptx-minimal':[(EXT,False)],'xlsx-minimal':[(EXT,False)]}
    for fmt in ['docx','dotx','docm','dotm']:plans[fmt+'-minimal']=[('word.paragraph_count',1)]
    for original in before['samples']:
        s=next(x for x in p['samples'] if x['id']==original['id'])
        modified=s.get('version',1)!=1
        if s['id'] in plans and not modified and not s['private']:
            facts=inspect_public(s)
            atomic(folder/(s['id']+'.json'),{'sampleSha256':s['sha256'],'inspectorSha256':sha(__file__),'facts':facts})
            for target,wanted in plans[s['id']]:
                actual=bool(facts['linkCount']) if target==EXT else facts['javascript'] if target==JS else facts['paragraphCount']
                assert type(actual)==type(wanted) and actual==wanted,(s['id'],target,actual)
                existing=[a for a in s['answers'] if a['check']=={'type':'target','target':target}]
                if existing:
                    if any(type(a['expected'])!=type(actual) or a['expected']!=actual for a in existing):conflicts.append([s['id'],target,'已有 GT 与独立事实冲突，未覆盖修改'])
                    continue
                assert any(t['id']==target and t.get('applicable') and 'deep' in t.get('supported_levels',[]) for t in catalog[s['format']]['targets'])
                question={'security.has_external_relationships':'这份文档是否包含指向文档外部的链接？',JS:'这份 PDF 是否包含 JavaScript 动作？','word.paragraph_count':'这份最小 Word 文档包含多少个段落？'}[target]
                location='；'.join(x['location'] for x in facts['links']) if target==EXT and facts['links'] else facts.get('javascriptLocation','word/document.xml 中的 w:p 元素') if target!=EXT else '遍历页面注释 / OpenAction 或包内全部 .rels；没有外部链接'
                notes=('外链数量：'+str(facts['linkCount'])+'；地址：'+', '.join(x['uri'] for x in facts['links'])+'。数量是独立样本事实，产品目录暂未提供数量接口。') if target==EXT else '直接检查结构，不执行脚本、不请求外链；不是以产品输出作为标准答案。'
                evidence={'method':facts['method'],'location':location,'notes':notes,'facts':facts,
                          'recordPath':str(folder/(s['id']+'.json')),'recordSha256':sha(folder/(s['id']+'.json')),
                          'inspectorSha256':sha(__file__),'sourceSha256':s['sha256'],'catalogId':catalog_id}
                act(s,'save_answer',answer={'question':question,'expected':actual,'check':{'type':'target','target':target},
                    'options':['-l','deep','-t',target],'requirement':'PRO-R03','evidence':evidence})
                new.append({'sample':s['id'],'target':target,'expected':actual})
        s=next(x for x in p['samples'] if x['id']==original['id'])
        purpose=intent(s) if not modified else {'summary':'文件已被替换，旧用途需要根据新文件重新核对。','checks':[criterion('重新确认样本用途与主要问题')]}
        # Preserve later human edits on repeated audits.
        if not s.get('purpose'):act(s,'save_purpose',purpose=purpose)
        rows.append({'sample':s['id'],'purpose':s.get('purpose',purpose),
                     'mainGT':sum(any(c.get('type')==a['check'].get('type') and (not c.get('target') or c['target']==a['check'].get('target')) for c in purpose['checks']) for a in s['answers'])})
    after=store.get('deckprobe')
    assert all(a==old_answers[a['id']] for s in after['samples'] for a in s['answers'] if a['id'] in old_answers)
    with locked(home):sync(home)
    report={'samples':len(rows),'added':new,'conflicts':conflicts,'rows':rows,'existingAnswersUnchanged':True}
    atomic(folder/'audit.json',report)
    print(json.dumps({'samples':len(rows),'newGT':len(new),'conflicts':conflicts,'report':str(folder/'audit.json')},ensure_ascii=False))


if __name__=='__main__':run()
