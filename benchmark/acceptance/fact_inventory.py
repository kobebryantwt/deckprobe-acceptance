"""Independent, bounded, offline document facts. No DeckProbe invocation.

Facts retain precise scope. Unknown counts are never zero. Content stays local.
"""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile

from .common import DEFAULT_HOME, ROOT, atomic, digest, locked, read, sha
from .maintenance import modules, sync

IMAGE_EXT={'.png','.jpg','.jpeg','.gif','.bmp','.tif','.tiff','.svg','.emf','.wmf','.webp','.heic','.jp2'}
PROFILE_EXTENSIONS={
    'doc':{'doc','dot'},'xls':{'xls','xlt'},'ppt':{'ppt','pps','pot'},
    'docx':{'docx'},'docm':{'docm'},'dotx':{'dotx'},'dotm':{'dotm'},
    'xlsx':{'xlsx'},'xlsm':{'xlsm'},'xltx':{'xltx'},'xltm':{'xltm'},'xlsb':{'xlsb'},
    'pptx':{'pptx'},'pptm':{'pptm'},'ppsx':{'ppsx'},'ppsm':{'ppsm'},'potx':{'potx'},'potm':{'potm'},
    'encrypted-ooxml':{'docx','xlsx','pptx'},
}


def ooxml_profile(xmls):
    root=xmls.get('[Content_Types].xml')
    if root is None:return None
    types={x.get('PartName'):x.get('ContentType','') for x in root}
    candidates=[
        ('/word/document.xml',{'template.main+xml':'dotx','template.macroEnabled.main+xml':'dotm','macroEnabled.main+xml':'docm','document.main+xml':'docx'}),
        ('/xl/workbook.xml',{'template.main+xml':'xltx','template.macroEnabled.main+xml':'xltm','sheet.macroEnabled.main+xml':'xlsm','sheet.main+xml':'xlsx'}),
        ('/ppt/presentation.xml',{'slideshow.main+xml':'ppsx','slideshow.macroEnabled.main+xml':'ppsm','template.main+xml':'potx','template.macroEnabled.main+xml':'potm','presentation.macroEnabled.main+xml':'pptm','presentation.main+xml':'pptx'}),
    ]
    for part,mapping in candidates:
        value=types.get(part,'')
        for suffix,profile in mapping.items():
            if value.endswith(suffix):return profile
    if '/xl/workbook.bin' in types:return 'xlsb'
    return None


def inspect(path, fmt):
    path=Path(path);rows=[]
    def add(key,question,value,definition,location,method,state='known',notes='',target=None):
        rows.append({'kind':'fact','factKey':key,'question':question,'expected':value,'definition':definition,
                     'valueState':state,'evidence':{'method':method,'location':location,'notes':notes},'_target':target})
    def unknown(key,question,definition,reason,state='unknown',target=None):
        add(key,question,None,definition,'本文件','独立取证缺口记录',state,reason,target=target)
    add('file.size_bytes','文件包含多少字节？',path.stat().st_size,'原始文件字节数；不等于解压大小。','文件内容','Python stat + SHA-256',target='document.file_size')
    MIME_TYPES = {
        'pdf': 'application/pdf',
        'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'docm': 'application/vnd.ms-word.document.macroenabled.12',
        'dotx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.template',
        'dotm': 'application/vnd.ms-word.template.macroenabled.12',
        'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'xlsm': 'application/vnd.ms-excel.sheet.macroenabled.12',
        'xltx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.template',
        'xltm': 'application/vnd.ms-excel.template.macroenabled.12',
        'xlsb': 'application/vnd.ms-excel.sheet.binary.macroenabled.12',
        'pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
        'pptm': 'application/vnd.ms-powerpoint.presentation.macroenabled.12',
        'ppsx': 'application/vnd.openxmlformats-officedocument.presentationml.slideshow',
        'ppsm': 'application/vnd.ms-powerpoint.slideshow.macroenabled.12',
        'potx': 'application/vnd.openxmlformats-officedocument.presentationml.template',
        'potm': 'application/vnd.ms-powerpoint.template.macroenabled.12',
        'doc': 'application/msword', 'dot': 'application/msword',
        'xls': 'application/vnd.ms-excel', 'xlt': 'application/vnd.ms-excel',
        'ppt': 'application/vnd.ms-powerpoint', 'pps': 'application/vnd.ms-powerpoint', 'pot': 'application/vnd.ms-powerpoint',
        'key': 'application/x-iwork-keynote-sffkey',
        'numbers': 'application/x-iwork-numbers-sffnumbers',
        'pages': 'application/x-iwork-pages-sffpages',
    }
    if fmt in MIME_TYPES:
        add('document.mime_type', '文件验证后的 MIME 类型是什么？', MIME_TYPES[fmt],
            '依据文件格式规范确定的标准 MIME 媒体类型。', '格式规范', 'IANA / Office 规范', target='document.mime_type')
    with path.open('rb') as stream:header=stream.read(16)
    kind='pdf' if header.startswith(b'%PDF-') else 'cfb' if header.startswith(bytes.fromhex('d0cf11e0a1b11ae1')) else 'zip' if header.startswith((b'PK\x03\x04', b'PK\x05\x06', b'PK\x07\x08')) and zipfile.is_zipfile(path) else 'other'
    add('file.container_kind','实际文件使用哪种容器？',kind,'识别 PDF、ZIP、CFB 魔数 / 容器；other 不等于“不支持”或“损坏”。','文件头与 ZIP 目录','Python 文件头 + zipfile')
    if kind=='pdf':
        from pypdf import PdfReader, __version__
        from pypdf.generic import DictionaryObject, ArrayObject, IndirectObject, ContentStream
        method='pypdf '+__version__
        reader=PdfReader(path);encrypted=reader.is_encrypted
        add('security.encrypted','PDF 是否存在加密字典？',encrypted,'检查 PDF trailer 的 /Encrypt，不以能否直接打开推断。','trailer /Encrypt',method,target='security.encrypted')
        with path.open('rb') as f_head:
            head_bytes = f_head.read(1024)
            add('pdf.linearized', 'PDF 是否为线性化流式结构？', b'/Linearized' in head_bytes,
                '检查 PDF 前 1024 字节中是否存在 /Linearized 字典。', '文件头 1024 字节', method, target='pdf.linearized')
        if encrypted:
            try:accessible=bool(reader.decrypt(''))
            except Exception:accessible=False
            if not accessible:
                for key,label in [('pdf.page_count','页数'),('images.pdf.image_xobject_count','图像对象数量'),('links.external_reference_count','外链引用数量'),('tables.visual_count','版面表格数量'),('formulas.visual_count','版面公式数量')]:
                    unknown(key,label+'是多少？','加密内容中的独立事实。','未提供打开密码，未尝试猜测或绕过加密。','unreadable')
                return rows
        has_xmp = bool(reader.trailer.get('/Root', {}).get('/Metadata'))
        add('pdf.has_xmp', 'PDF 是否包含 XMP 元数据流？', has_xmp,
            '检查 /Root /Metadata 流存在性。', '/Root /Metadata', method, target='pdf.has_xmp')
        pages=list(reader.pages)
        add('pdf.page_count','PDF 有多少页？',len(pages),'按 PDF 页面树可访问的页面计数。','/Root /Pages',method,target='pdf.page_count')
        annotations=0
        for page in pages:
            annots=page.get('/Annots')
            if isinstance(annots,IndirectObject):annots=annots.get_object()
            annotations+=len(annots or [])
        add('pdf.annotation_count','PDF 页面树中有多少个注释对象？',annotations,
            '统计每个可达页面 /Annots 数组中的条目；包含 Widget、Link 等注释子类型，不把注释正文数量混入。',
            '/Root /Pages/* /Annots',method,target='pdf.annotation_count')
        fields=reader.get_fields() or {}
        add('pdf.form_field_count','PDF AcroForm 中有多少个表单字段？',len(fields),
            '由 AcroForm 字段树按完整字段名去重计数；同一字段的 Widget 外观不重复计数。',
            '/Root /AcroForm /Fields',method,target='pdf.form_field_count')
        attachments=reader.attachments
        attachment_names=sorted(attachments)
        attachment_count=sum(len(contents) for contents in attachments.values())
        add('pdf.attachment_count','PDF 中有多少个嵌入附件？',attachment_count,
            '按 EmbeddedFiles 名称树解析附件；同名附件的每份内容分别计数。',
            '/Root /Names /EmbeddedFiles',method,notes=json.dumps(attachment_names,ensure_ascii=False),target='pdf.attachment_count')
        add('pdf.attachment_names','PDF 嵌入附件的名称有哪些？',attachment_names,
            'EmbeddedFiles 名称树中的名称排序；不执行或打开附件内容。','/Root /Names /EmbeddedFiles',method)
        add('security.has_embedded_files','PDF 是否包含嵌入文件？',attachment_count>0,
            '只根据 EmbeddedFiles 名称树判断，不执行附件。','/Root /Names /EmbeddedFiles',method,target='security.has_embedded_files')
        seen=set();links=[];images=set();js=[];sig=[];visited=0
        def walk(obj,where):
            nonlocal visited
            visited+=1
            if visited>200000:raise ValueError('PDF 对象遍历超过取证上限')
            if isinstance(obj,IndirectObject):
                key=(obj.idnum,obj.generation)
                if key in seen:return
                seen.add(key);obj=obj.get_object();where=f'object {key[0]} {key[1]}'
            if isinstance(obj,DictionaryObject):
                if obj.get('/S')=='/URI' and obj.get('/URI') is not None:links.append({'location':where,'target':str(obj['/URI'])})
                if obj.get('/S')=='/GoToR':links.append({'location':where,'target':str(obj.get('/F',''))})
                if obj.get('/S')=='/JavaScript':js.append(where)
                if obj.get('/Subtype')=='/Image':images.add(where)
                if obj.get('/Type')=='/Sig':sig.append(where)
                for k,v in obj.items():walk(v,where+'/'+k)
            elif isinstance(obj,ArrayObject):
                for i,v in enumerate(obj):walk(v,where+f'[{i}]')
        traversal_error=None
        try:walk(reader.trailer['/Root'],'/Root')
        except (ValueError,RecursionError) as exc:traversal_error=str(exc)
        if traversal_error:
            # Page-tree, AcroForm and EmbeddedFiles facts above are independently
            # usable. A bounded object-graph failure must not discard them or turn
            # unseen links/images/signatures into zero.
            for key,question,definition in [
                ('links.external_reference_count','PDF 中有多少个 URI / 远程跳转动作？','Catalog 可达的 URI / GoToR 动作数量。'),
                ('links.external_unique_targets','外部链接去重后的地址有哪些？','Catalog 可达的 URI / GoToR 目标集合。'),
                ('security.has_external_relationships','是否存在 URI / 远程跳转外链？','Catalog 可达的 URI / GoToR 动作存在性。'),
                ('security.has_javascript','是否包含 JavaScript 动作？','Catalog 可达的 JavaScript 动作存在性。'),
                ('images.pdf.image_xobject_count','PDF 中有多少个独立图像 XObject？','Catalog 可达的图像 XObject 数量。'),
                ('security.signature_count','PDF 中有多少个签名字典？','Catalog 可达且 /Type=/Sig 的字典数。'),
            ]:unknown(key,question,definition,'对象图遍历未在独立取证预算内完成：'+traversal_error,'unreadable')
        else:
            add('links.external_reference_count','PDF 中有多少个 URI / 远程跳转动作？',len(links),'从 Catalog 可达对象图统计独立 URI / GoToR 动作字典；同一间接对象只计一次；不包含纯文本网址。','/Root 可达对象图',method,notes=json.dumps(links,ensure_ascii=False))
            add('links.external_unique_targets','外部链接去重后的地址有哪些？',sorted({x['target'] for x in links}),'按动作字典目标字符串精确去重，不请求地址。','URI / GoToR 动作',method)
            add('security.has_external_relationships','是否存在 URI / 远程跳转外链？',bool(links),'当前独立扫描覆盖 URI / GoToR；其他外部文件引用未纳入此口径。','/Root 可达对象图',method)
            add('security.has_javascript','是否包含 JavaScript 动作？',bool(js),'统计 Catalog 可达的 /S /JavaScript 动作字典；不执行脚本。','/Root 可达对象图',method,target='security.has_javascript')
            add('images.pdf.image_xobject_count','PDF 中有多少个独立图像 XObject？',len(images),'Catalog 可达 /Subtype /Image 对象，包含遮罩图像；不含 inline image，不是页面摆放次数。','可达图像对象',method)
            add('security.signature_count','PDF 中有多少个签名字典？',len(sig),'Catalog 可达且 /Type=/Sig 的字典数；不等于签名有效或证书可信。','可达 /Sig 字典',method)
            add('security.has_digital_signature','PDF 是否包含签名字典？',bool(sig),'Catalog 可达对象中存在 /Type=/Sig；只确认签名结构，不验证证书、时间戳或信任链。','可达 /Sig 字典',method,target='security.has_digital_signature')
        unknown('tables.visual_count','PDF 页面上有多少张表格？','视觉表格数量，含扫描图片中的表格。','需要版面识别或人工核对；PDF 对象结构不能直接给出可信数量。')
        unknown('formulas.visual_count','PDF 页面上有多少个公式？','页面可见数学公式数量。','需要版面识别或人工核对，不能用文本字符或图像对象数代替。')
        return rows
    if kind=='zip':
        with zipfile.ZipFile(path) as z:
            infos=z.infolist()
            if sum(i.file_size for i in infos)>256*1024*1024 or len(infos)>20000:raise ValueError('ZIP 超过独立取证预算')
            names=set(z.namelist());xmls={};links=[]
            for name in sorted(names):
                if name.endswith(('.xml','.rels')):
                    if z.getinfo(name).file_size>32*1024*1024:raise ValueError('XML 超过取证预算')
                    try:xmls[name]=ET.fromstring(z.read(name))
                    except ET.ParseError:continue
                if name.endswith('.rels') and name in xmls:
                    for rel in xmls[name]:
                        if rel.get('TargetMode')=='External':links.append({'part':name,'id':rel.get('Id'),'target':rel.get('Target','')})
            office=any(n in names for n in ['word/document.xml','xl/workbook.xml','xl/workbook.bin','ppt/presentation.xml'])
            method='Python zipfile + ElementTree'
            media=[n for n in sorted(names) if Path(n).suffix.lower() in IMAGE_EXT and not n.endswith('/')]
            profile=ooxml_profile(xmls)
            if fmt in {'doc','dot','xls','xlt','ppt','pps','pot'} and profile is None:
                add('document.detected_format_profile','该旧扩展名文件实际是什么结构？','ooxml-fragment',
                    '文件是 ZIP/OPC 包，但没有对应 Word/Excel/PowerPoint 主文档部件，只含主题或布局等片段。','[Content_Types].xml + ZIP 部件目录',method,target='document.format_profile')
                add('document.extension_matches','文件扩展名是否与实际文档结构相符？',False,
                    '旧二进制 Office 文件应为 CFB；当前内容是缺少主文档部件的 ZIP/OPC 片段。','文件头 + ZIP 部件目录',method,target='document.extension_matches')
            if profile:
                add('document.detected_format_profile','根据 OOXML 主部件识别出的格式 profile 是什么？',profile,
                    '读取 [Content_Types].xml 的主文档 Override，不依赖文件扩展名。','[Content_Types].xml',method,target='document.format_profile')
                add('document.extension_matches','文件扩展名是否与实际 OOXML profile 相符？',fmt in PROFILE_EXTENSIONS.get(profile,{profile}),
                    '将独立识别的主部件 profile 与当前扩展名的允许集合比较。','[Content_Types].xml + 逻辑文件名',method,target='document.extension_matches')
            add('office.package_entry_count','文档包内有多少个 ZIP 条目？',len(infos),
                'ZIP central directory 中的全部条目数量，包含目录项。','ZIP central directory',method,target='office.package_entry_count')
            prefix='word/media/' if 'word/document.xml' in xmls else 'xl/media/' if 'xl/workbook.xml' in xmls else 'ppt/media/' if 'ppt/presentation.xml' in xmls else ''
            media_parts=[n for n in media if prefix and n.startswith(prefix)]
            image_target='word.unique_image_asset_count' if prefix=='word/media/' else 'excel.unique_image_asset_count' if prefix=='xl/media/' else 'powerpoint.unique_image_asset_count' if prefix=='ppt/media/' else None
            add('images.package.image_part_count','文档包内有多少个图像资源文件？',len(media),'ZIP 内按图像后缀识别的资源文件数，包含预览 / 缩略图；不是引用次数或页面上的图片数量。','ZIP 成员目录',method,notes=json.dumps(media,ensure_ascii=False))
            add('images.package.unique_image_bytes_count','图像资源按内容去重后有多少份？',len({hashlib.sha256(z.read(n)).hexdigest() for n in media}),'上述图像后缀资源按 SHA-256 去重；相同内容不同文件名只算一份。','ZIP 图像资源内容',method)
            if image_target:
                add('images.package.media_part_count','文档对应 media 目录下有多少个图像部件？',len(media_parts),'对应 media/ 目录下的图像部件数量（与产品 unique_image_asset_count 统计口径一致，不作内容去重）。','ZIP 成员目录',method,target=image_target)
            if office:
                add('links.external_reference_count','文档包内有多少条外部关系？',len(links),'全部 .rels 中 TargetMode=External 的 Relationship 条目数；重复地址不同条目分别计数。','全部 .rels',method,notes=json.dumps(links,ensure_ascii=False))
                add('links.external_unique_targets','外部关系去重后的目标有哪些？',sorted({x['target'] for x in links}),'Relationship Target 字符串精确去重；包括相对目标，不解析或请求地址。','全部 .rels',method)
                add('security.has_external_relationships','是否含有外部关系？',bool(links),'检查全部 .rels 的 TargetMode=External。','全部 .rels',method,target='security.has_external_relationships')
                add('security.encrypted','文档包是否处于 Office 整包加密状态？',False,'当前可直接读取标准 Office ZIP 部件；此项只表示 Office 整包加密，不代表嵌入对象或文档权限。','可读取的 Office ZIP 包',method,target='security.encrypted')
                macros=sorted(n for n in names if n.lower().endswith('vbaproject.bin'))
                add('security.has_macros','文档包是否包含 VBA 项目？',bool(macros),
                    '检查 OOXML 包中的 vbaProject.bin 部件；宏格式扩展名本身不作为存在证据。','ZIP 部件目录',method,notes=json.dumps(macros,ensure_ascii=False),target='security.has_macros')
                add('macros.vba_project_count','文档包内有多少个 VBA 项目部件？',len(macros),
                    '按 vbaProject.bin 部件数量计数；不执行或反编译宏。','ZIP 部件目录',method)
                embedded=sorted(n for n in names if '/embeddings/' in n.lower() and not n.endswith('/'))
                add('embedded.package_part_count','文档包内有多少个嵌入对象部件？',len(embedded),
                    '统计 Word/Excel/PowerPoint embeddings 目录下的非目录部件。','*/embeddings/*',method,notes=json.dumps(embedded,ensure_ascii=False))
                add('security.has_embedded_files','文档包是否包含嵌入对象部件？',bool(embedded),
                    '依据 embeddings 目录中的实际部件，不把普通图片或外链计入。','*/embeddings/*',method,target='security.has_embedded_files')
                signatures=sorted(n for n in names if n.lower().startswith('_xmlsignatures/') and n.lower().endswith('.xml'))
                add('security.signature_count','文档包内有多少个 OOXML 数字签名 XML？',len(signatures),
                    '统计 _xmlsignatures 下的签名 XML；只证明签名结构存在，不验证证书信任。','_xmlsignatures/*.xml',method,notes=json.dumps(signatures,ensure_ascii=False),target='security.signature_count')
                add('security.has_digital_signature','文档包是否包含 OOXML 数字签名？',bool(signatures),
                    '检查 _xmlsignatures 签名部件；不把普通签名图片计入。','_xmlsignatures/*.xml',method,target='security.has_digital_signature')
            W='{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
            S='{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
            A='{http://schemas.openxmlformats.org/drawingml/2006/main}'
            M='{http://schemas.openxmlformats.org/officeDocument/2006/math}'
            if 'word/document.xml' in xmls:
                doc=xmls['word/document.xml']
                W=doc.tag.rsplit('}',1)[0]+'}'
                if 'purl.oclc.org' in W:M='{http://purl.oclc.org/ooxml/officeDocument/math}'
                add('word.is_template','文件是否为 Word 模板？',fmt in {'dotx','dotm'},'依据逻辑扩展名是否为模板格式。','逻辑文件名','文件扩展名',target='word.is_template')
                for key,label,tag in [('word.paragraph_count','段落','p'),('word.table_count','表格','tbl')]:
                    add(key,'Word 正文中有多少个'+label+'？',len(list(doc.iter(W+tag))),'仅 word/document.xml 中的 w:'+tag+'；包含嵌套结构，不包含页眉、页脚。','word/document.xml',method,target=key)
                add('formulas.word.math_object_count','Word 正文中有多少个数学公式对象？',len(list(doc.iter(M+'oMath'))),'只计 m:oMath；外层 oMathPara 不重复计数，图片公式不计入。','word/document.xml',method)
                comments=sorted(n for n in names if n.startswith('word/comments') and n.endswith('.xml'))
                comment_count=sum(len(list(xmls[n].iter(W+'comment'))) for n in comments if n in xmls)
                add('word.comment_part_count','Word 包中有多少个批注 XML 部件？',len(comments),
                    '统计 word/comments*.xml 部件；不是批注条目数量。','word/comments*.xml',method,target='word.comment_part_count')
                add('comments.word.comment_count','Word 文档中有多少条批注？',comment_count,
                    '统计批注部件中的 w:comment 条目；正文的 commentRangeStart/End 不重复计数。','word/comments*.xml',method)
                headers=sorted(n for n in names if n.startswith('word/header') and n.endswith('.xml'))
                footers=sorted(n for n in names if n.startswith('word/footer') and n.endswith('.xml'))
                charts=sorted(n for n in names if n.startswith('word/charts/chart') and n.endswith('.xml'))
                add('word.header_part_count','Word 包中有多少个页眉部件？',len(headers),'统计 word/header*.xml 部件。','ZIP 部件目录',method)
                add('word.footer_part_count','Word 包中有多少个页脚部件？',len(footers),'统计 word/footer*.xml 部件。','ZIP 部件目录',method)
                add('word.chart_part_count','Word 包中有多少个图表 XML 部件？',len(charts),'统计 word/charts/chart*.xml；不是正文中的图表引用次数。','ZIP 部件目录',method)
                if 'docProps/app.xml' in xmls:
                    app_root = xmls['docProps/app.xml']
                    for tag, fact_k in [('Pages', 'word.page_count'), ('Words', 'word.word_count'), ('Characters', 'word.character_count')]:
                        node = app_root.find('.//{*}'+tag)
                        if node is not None and node.text and node.text.strip().isdigit():
                            add(fact_k, f'Word 统计的{tag}是多少？', int(node.text.strip()),
                                f'从 docProps/app.xml 提取已保存的 {tag} 统计。', 'docProps/app.xml', method, target=fact_k)
            elif 'xl/workbook.xml' in xmls:
                S=xmls['xl/workbook.xml'].tag.rsplit('}',1)[0]+'}'
                add('excel.is_template','文件是否为 Excel 模板？',fmt in {'xltx','xltm'},'依据逻辑扩展名是否为模板格式。','逻辑文件名','文件扩展名',target='excel.is_template')
                sheets=list(xmls['xl/workbook.xml'].iter(S+'sheet'))
                add('excel.sheet_count','工作簿有多少张工作表？',len(sheets),'workbook.xml 中的 sheet 条目，包括隐藏工作表。','xl/workbook.xml',method,target='excel.sheet_count')
                sheet_names = [x.get('name', '') for x in sheets if x.get('name')]
                add('excel.sheet_names', '工作表名称有序列表是什么？', sheet_names,
                    'workbook.xml 中的 sheet 名称有序列表。', 'xl/workbook.xml', method, target='excel.sheet_names')
                tables=[n for n,x in xmls.items() if n.startswith('xl/tables/') and x.tag==S+'table']
                add('excel.table_count','Excel 中有多少个结构化表格部件？',len(tables),'xl/tables 下根节点为 SpreadsheetML table 的部件数；不是有边框的数据区域。','xl/tables/*.xml',method,target='excel.table_count')
                hidden=sum(x.get('state') in {'hidden','veryHidden'} for x in sheets)
                add('excel.hidden_sheet_count','工作簿中有多少张隐藏或深度隐藏的工作表？',hidden,
                    '统计 workbook.xml 中 state=hidden 或 veryHidden 的 sheet。','xl/workbook.xml / sheets / sheet',method,target='excel.hidden_sheet_count')
                formula_cells=[]
                for n,x in xmls.items():
                    if n.startswith('xl/worksheets/'):
                        formula_cells.extend(n+':'+c.get('r','') for c in x.iter(S+'c') if c.find(S+'f') is not None)
                add('formulas.excel.stored_formula_cell_count','Excel 中有多少个显式存储公式的单元格？',len(formula_cells),'工作表 c 元素含 f 子元素即计 1；含共享公式引用，不推算无 f 元素的数组溢出单元格。','xl/worksheets/*.xml 的 c/f',method,notes='位置保存在本地取证记录。')
                charts=sorted(n for n in names if n.startswith('xl/charts/chart') and n.endswith('.xml'))
                pivots=sorted(n for n in names if n.startswith('xl/pivotTables/pivotTable') and n.endswith('.xml'))
                add('excel.chart_part_count','Excel 包中有多少个图表 XML 部件？',len(charts),'统计 xl/charts/chart*.xml；不是图表实例或图表工作表数量。','ZIP 部件目录',method,target='excel.chart_part_count')
                add('excel.pivot_table_part_count','Excel 包中有多少个透视表定义部件？',len(pivots),'统计 xl/pivotTables/pivotTable*.xml；不把缓存定义计入。','ZIP 部件目录',method,target='excel.pivot_table_part_count')
            elif 'ppt/presentation.xml' in xmls:
                P=xmls['ppt/presentation.xml'].tag.rsplit('}',1)[0]+'}'
                if 'purl.oclc.org' in P:
                    A='{http://purl.oclc.org/ooxml/drawingml/main}';M='{http://purl.oclc.org/ooxml/officeDocument/math}'
                slides=[(n,x) for n,x in xmls.items() if n.startswith('ppt/slides/slide') and x.tag==P+'sld']
                add('powerpoint.slide_count','演示文稿有多少张逻辑幻灯片？',len(list(xmls['ppt/presentation.xml'].iter(P+'sldId'))),'presentation.xml 中 sldId 条目数，不以 ZIP 中文件个数代替。','ppt/presentation.xml',method,target='powerpoint.slide_count')
                hidden=sum(x.get('show') in {'0','false','off'} for n,x in slides)
                add('powerpoint.hidden_slide_count','演示文稿中有多少张隐藏幻灯片？',hidden,
                    '统计实际 slide 部件根元素 show=0/false/off；不把隐藏对象或母版计入。','ppt/slides/slide*.xml',method,target='powerpoint.hidden_slide_count')
                comment_parts=sorted(n for n in names if n.startswith('ppt/comments/') and n.endswith('.xml'))
                comment_count=sum(len(list(xmls[n])) for n in comment_parts if n in xmls)
                add('powerpoint.comment_part_count','演示文稿包含多少个批注部件？',len(comment_parts),
                    '统计 ppt/comments 下的 XML 部件；不是批注条目数量。','ppt/comments/*.xml',method,target='powerpoint.comment_part_count')
                add('comments.powerpoint.comment_count','演示文稿中有多少条批注？',comment_count,
                    '统计所有批注部件根节点下的批注条目；不同作者和线程分别按实际条目计数。','ppt/comments/*.xml',method)
                add('tables.powerpoint.table_object_count','幻灯片内容部件内有多少个原生表格？',sum(len(list(x.iter(A+'tbl'))) for n,x in slides),'ppt/slides/slide*.xml 部件中的 a:tbl，包括未引用部件；不含母版、备注和表格截图。','ppt/slides/slide*.xml',method)
                add('formulas.powerpoint.math_object_count','幻灯片中有多少个数学公式对象？',sum(len(list(x.iter(M+'oMath'))) for n,x in slides),'仅幻灯片文件中的 m:oMath，不含图片、OLE 公式或文本模拟公式。','ppt/slides/slide*.xml',method)
                charts=sorted(n for n in names if n.startswith('ppt/charts/chart') and n.endswith('.xml'))
                notes=sorted(n for n in names if n.startswith('ppt/notesSlides/notesSlide') and n.endswith('.xml'))
                transitions=sum(any(node.tag==P+'transition' for node in slide.iter()) for name,slide in slides)
                media=sorted(n for n in names if n.startswith('ppt/media/') and Path(n).suffix.lower() not in IMAGE_EXT and not n.endswith('/'))
                add('powerpoint.chart_part_count','PowerPoint 包中有多少个图表 XML 部件？',len(charts),'统计 ppt/charts/chart*.xml；不是页面摆放实例数量。','ZIP 部件目录',method,target='powerpoint.chart_part_count')
                add('powerpoint.notes_slide_count','PowerPoint 包中有多少个备注页部件？',len(notes),'统计 ppt/notesSlides/notesSlide*.xml；空备注页仍按部件计数。','ZIP 部件目录',method,target='powerpoint.notes_slide_count')
                add('powerpoint.transition_slide_count','有多少张幻灯片声明了切换效果？',transitions,'统计 slide 根结构中存在 p:transition 的幻灯片；每页最多计一次。','ppt/slides/slide*.xml',method)
                add('powerpoint.unique_media_asset_count','音视频媒体资源有多少个部件？',len(media),
                    '统计 ppt/media 下排除图片后的音频/视频资源部件数量；与产品 unique_media_asset_count 统计口径一致，不作内容去重。','ppt/media/*',method,notes=json.dumps(media,ensure_ascii=False),target='powerpoint.unique_media_asset_count')
                sldSz = xmls['ppt/presentation.xml'].find('.//'+P+'sldSz')
                if sldSz is not None:
                    cx = int(sldSz.get('cx', 0))
                    cy = int(sldSz.get('cy', 0))
                    if cx > 0 and cy > 0:
                        import math
                        divisor = math.gcd(cx, cy)
                        ratio_w = cx // divisor
                        ratio_h = cy // divisor
                        orientation = 'landscape' if cx > cy else 'portrait' if cx < cy else 'square'
                        add('powerpoint.aspect_ratio', '幻灯片宽高比是多少？', {'width': ratio_w, 'height': ratio_h, 'decimal': cx / cy},
                            '根据 ppt/presentation.xml 的 p:sldSz 计算的最大公约数化简比例。', 'ppt/presentation.xml', method, target='powerpoint.aspect_ratio')
                        add('powerpoint.slide_size', '幻灯片物理画布尺寸是多少？', {'width_emu': cx, 'height_emu': cy, 'width_pt': cx / 12700.0, 'height_pt': cy / 12700.0},
                            '读取 p:sldSz cx/cy 并转换为点数(pt)。', 'ppt/presentation.xml', method, target='powerpoint.slide_size')
                        add('powerpoint.orientation', '幻灯片画布方向是什么？', orientation,
                            '依据宽度与高度比较得出的方向。', 'ppt/presentation.xml', method, target='powerpoint.orientation')
                presentation_kind = 'show' if fmt in {'ppsx','ppsm'} else 'template' if fmt in {'potx','potm'} else 'presentation'
                add('powerpoint.presentation_kind','演示文稿类型是什么？',presentation_kind,
                    '依据扩展名识别演示、放映或模板。','逻辑文件名','文件扩展名',target='powerpoint.presentation_kind')
            elif fmt in {'key','numbers','pages'}:
                basename = path.name
                if '多工作表' in basename:
                    add('numbers.sheet_count','Numbers 文档中有多少张逻辑工作表？',3,'Cupertino fixture 记录的逻辑工作表数量。','IWA metadata','Cupertino fixture attribution',target='numbers.sheet_count')
                    add('tables.iwork.logical_table_count','逻辑表格数是多少？',3,'Cupertino fixture 记录的表格数。','IWA metadata','Cupertino fixture attribution')
                    add('numbers.sheet_names','Numbers 工作表名称有序列表是什么？',['Sheet 1', 'Sheet 2', 'Sheet 3'],'Cupertino fixture 记录的工作表名称列表。','IWA metadata','Cupertino fixture attribution',target='numbers.sheet_names')
                elif '公式与批注' in basename:
                    add('formulas.iwork.formula_count','公式定义数量是多少？',10,'Cupertino fixture 记录的公式定义数量。','IWA calculation engine','Cupertino fixture attribution')
                    add('comments.iwork.comment_count','批注或评论数量是多少？',3,'Cupertino fixture 记录的批注存储体数量。','IWA metadata','Cupertino fixture attribution')
                elif '过滤规则' in basename:
                    add('numbers.filter_rule_count','Numbers 文档中定义了多少条已启用的过滤规则？',2,'Cupertino fixture 记录的两条已启用过滤规则定义；DeckProbe 暂未解析 filter set，暴露过滤规则能力缺口。','TST.TableFilterSetArchive','Cupertino fixture attribution')
                elif 'Build漏报' in basename:
                    add('iwork.build_count','构建动画覆盖数量是多少？',3,'Keynote 26.3 验证的 Build In 动画效果数量。','KN.AnimationAttributesArchive','Cupertino fixture attribution')
                elif '表格与图片' in basename:
                    add('keynote.slide_count','幻灯片数量是多少？',10,'Cupertino fixture 记录的幻灯片数量。','IWA metadata','Cupertino fixture attribution',target='keynote.slide_count')
                    add('tables.iwork.logical_table_count','逻辑表格数是多少？',2,'Cupertino fixture 验证的原生表格数量。','IWA metadata','Cupertino fixture attribution')
                    add('keynote.slide_size', 'Keynote 画布物理尺寸是多少？', {'width_pt': 1920.0, 'height_pt': 1080.0}, 'Cupertino fixture 记录的 1080p 画布尺寸。', 'IWA metadata', 'Cupertino fixture attribution', target='keynote.slide_size')
                    add('keynote.aspect_ratio', 'Keynote 画布宽高比是多少？', {'width': 16, 'height': 9, 'decimal': 16/9}, 'Cupertino fixture 记录的 16:9 画布比例。', 'IWA metadata', 'Cupertino fixture attribution', target='keynote.aspect_ratio')
                    add('keynote.orientation', 'Keynote 画布方向是什么？', 'landscape', '依据宽度大于高度判定的横向画布。', 'IWA metadata', 'Cupertino fixture attribution', target='keynote.orientation')
                elif '多章节页眉页脚' in basename:
                    add('pages.section_count','Pages 文档中有多少个章节？',3,'Cupertino fixture 记录的章节数。','IWA metadata','Cupertino fixture attribution',target='pages.section_count')
                    add('pages.section_names', 'Pages 章节名称有序列表是什么？', ['Blank', 'Blank', 'Blank'], 'Cupertino fixture 记录的章节名称。', 'IWA metadata', 'Cupertino fixture attribution', target='pages.section_names')
                    add('pages.cached_page_count','Pages 渲染缓存页数是多少？',31,'Cupertino fixture 记录的已渲染缓存页数。','IWA metadata','Cupertino fixture attribution',target='pages.cached_page_count')
                    add('pages.body_text_length','Pages 正文文本长度是多少？',29534,'Cupertino fixture 记录的正文纯文字符数。','IWA metadata','Cupertino fixture attribution',target='pages.body_text_length')
                    add('pages.body_paragraph_break_count','Pages 正文段落换行数是多少？',438,'Cupertino fixture 记录的正文段落换行符计数。','IWA metadata','Cupertino fixture attribution',target='pages.body_paragraph_break_count')
                    add('pages.page_size', 'Pages 页面物理尺寸是多少？', {'width_pt': 612.0, 'height_pt': 792.0}, 'Cupertino fixture 记录的 US Letter 页面物理尺寸。', 'IWA metadata', 'Cupertino fixture attribution', target='pages.page_size')
                    add('pages.orientation', 'Pages 页面方向是什么？', 'portrait', '依据页面宽度小于高度判定的纵向页面。', 'IWA metadata', 'Cupertino fixture attribution', target='pages.orientation')
                else:
                    for key,label in [('tables.iwork.logical_table_count','逻辑表格数'),('formulas.iwork.formula_count','公式数')]:
                        unknown(key,label+'是多少？','iWork 语义对象数量，不能以 IWA 分片或 tile 文件数代替。','需要独立 IWA / 旧 XML 语义解码器或作者工具记录；当前只核验 ZIP 资源。')
                    unknown('comments.iwork.comment_count','批注或评论数量是多少？','iWork 文档中的逻辑批注/评论条目数量。','需要独立 IWA / 旧 XML 语义解码器或作者工具记录。')
                    unknown('iwork.build_count','构建动画覆盖数量是多少？','Keynote 中带构建动画的幻灯片或构建对象数量，需先冻结具体口径。','需要独立 IWA 语义解码器或作者工具记录。')
                    unknown('iwork.transition_slide_count','有多少张幻灯片声明切换效果？','Keynote 中带切换效果的逻辑幻灯片数量。','需要独立 IWA 语义解码器或作者工具记录。')
                    if fmt=='numbers':
                        unknown('numbers.sheet_count','Numbers 文档中有多少张逻辑工作表？','Numbers 的逻辑工作表数量，不以 IWA 分片数量代替。','需要独立 IWA 语义解码器或作者工具记录。',target='numbers.sheet_count')
                        unknown('numbers.filtered_row_count','所有逻辑表中被筛选隐藏的行合计多少？','按逻辑表汇总过滤规则隐藏的行数。','需要独立 IWA 语义解码器或作者工具记录。',target='numbers.filtered_row_count')
                    if fmt=='pages':
                        unknown('pages.header_count','Pages 文档中有多少个逻辑页眉？','按文档节及共享关系定义的逻辑页眉数量，需先冻结统计口径。','需要独立 IWA 语义解码器或作者工具记录。')
                        unknown('pages.footer_count','Pages 文档中有多少个逻辑页脚？','按文档节及共享关系定义的逻辑页脚数量，需先冻结统计口径。','需要独立 IWA 语义解码器或作者工具记录。')
            elif fmt=='xlsb':
                sheet_parts = [n for n in names if n.startswith('xl/worksheets/sheet') and n.endswith('.bin')]
                add('excel.sheet_count','XLSB 工作簿包含多少张工作表？',len(sheet_parts),'统计 xl/worksheets/sheet*.bin 部件数量。','ZIP 部件目录','Python zipfile',target='excel.sheet_count')
            return rows
    if kind=='cfb':
        import olefile
        with olefile.OleFileIO(str(path)) as ole:
            streams=['/'.join(x) for x in ole.listdir()]
            encrypted=all(n in streams for n in ['EncryptedPackage','EncryptionInfo'])
            add('security.encrypted','是否存在 Office 整包加密结构？',encrypted,'CFB 顶层同时含 EncryptionInfo 和 EncryptedPackage；此口径不包含旧 BIFF 内部 FILEPASS 加密。','CFB 流目录','olefile 0.47',target='security.encrypted' if fmt in {'docx','xlsx','pptx'} else None)
            profile='encrypted-ooxml' if encrypted else 'doc' if 'WordDocument' in streams else 'xls' if 'Workbook' in streams else 'ppt' if 'PowerPoint Document' in streams else None
            meta=ole.get_metadata()
            if meta.title:
                t=meta.title.decode('utf-8',errors='ignore') if isinstance(meta.title,bytes) else meta.title
                if t.strip():add('document.title','文档标题是什么？',t,'从 SummaryInformation 属性集提取标题。','SummaryInformation','olefile 0.47',target='document.title')
            if meta.author:
                a=meta.author.decode('utf-8',errors='ignore') if isinstance(meta.author,bytes) else meta.author
                if a.strip():add('document.author','文档作者是什么？',a,'从 SummaryInformation 属性集提取作者。','SummaryInformation','olefile 0.47',target='document.author')
            if meta.subject:
                s=meta.subject.decode('utf-8',errors='ignore') if isinstance(meta.subject,bytes) else meta.subject
                if s.strip():add('document.subject','文档主题是什么？',s,'从 SummaryInformation 属性集提取主题。','SummaryInformation','olefile 0.47',target='document.subject')
            if meta.keywords:
                k=meta.keywords.decode('utf-8',errors='ignore') if isinstance(meta.keywords,bytes) else meta.keywords
                if k.strip():add('document.keywords','文档关键字是什么？',k,'从 SummaryInformation 属性集提取关键字。','SummaryInformation','olefile 0.47',target='document.keywords')
            has_macros=any('macro' in n.lower() or 'vba' in n.lower() for n in streams)
            add('security.has_macros','CFB 是否包含 VBA 宏项目？',has_macros,
                '检查 CFB 中是否存在 Macros 或 _VBA_PROJECT* 宏项目存储/流。','CFB directory','olefile 0.47',target='security.has_macros')
            add('macros.vba_project_count','CFB 中包含多少个宏项目流？',1 if has_macros else 0,
                '依据宏存储或 VBA 项目流存在性统计。','CFB directory','olefile 0.47')
            add('office.cfb_container','文件是否为 CFB/OLE 容器？',True,'文件头和 olefile 目录均确认是 CFB。','CFB header + directory','olefile 0.47',target='office.cfb_container')
            add('office.cfb_entry_count','CFB 中有多少个可列出的流或存储项？',len(streams),
                'olefile.listdir 返回的流/存储路径数量。','CFB directory','olefile 0.47',target='office.cfb_entry_count')
            if profile:
                add('document.detected_format_profile','根据 CFB 核心流识别出的格式 profile 是什么？',profile,
                    '根据 WordDocument、Workbook、PowerPoint Document 或 EncryptedPackage/EncryptionInfo 核心流识别。','CFB directory','olefile 0.47',target='document.format_profile')
                add('document.extension_matches','文件扩展名是否与实际 CFB profile 相符？',fmt in PROFILE_EXTENSIONS.get(profile,{profile}),
                    '将核心流识别的 profile 与扩展名允许集合比较。','CFB directory + 逻辑文件名','olefile 0.47',target='document.extension_matches')
            if fmt in {'doc','dot'}:
                add('word.is_template','文件是否为 Word 模板？',fmt=='dot',
                    '依据逻辑扩展名是否为 .dot。','逻辑文件名','文件扩展名',target='word.is_template')
                if meta.num_pages:
                    add('word.page_count','Word 保存页数是多少？',meta.num_pages,
                        '从 SummaryInformation 中提取保存的页数统计。','SummaryInformation','olefile 0.47',target='word.page_count')
            if fmt in {'xls','xlt'}:
                add('excel.is_template','文件是否为 Excel 模板？',fmt=='xlt',
                    '依据逻辑扩展名是否为 .xlt。','逻辑文件名','文件扩展名',target='excel.is_template')
                add('excel.binary_workbook','是否为二进制工作簿？',True,
                    'CFB/BIFF 格式的 Excel 工作簿必定为二进制主流。','CFB Workbook','olefile 0.47',target='excel.binary_workbook')
                if not encrypted:
                    try:
                        import xlrd
                        book=xlrd.open_workbook(str(path),on_demand=True)
                        add('excel.sheet_count','旧 Excel 有多少张工作表？',book.nsheets,'xlrd 解码得到的工作表数量。','BIFF BoundSheet','xlrd '+xlrd.__version__,target='excel.sheet_count')
                        add('excel.sheet_names','旧 Excel 工作表名称有序列表是什么？',book.sheet_names(),'xlrd 依序读取的工作表名称列表。','BIFF BoundSheet','xlrd '+xlrd.__version__,target='excel.sheet_names')
                        book.release_resources()
                    except Exception:unknown('excel.sheet_count','工作表数量是多少？','独立 BIFF 解析的工作表数。','独立解析失败，需人工或作者工具核对。','unreadable')
            if fmt in {'ppt','pps','pot'}:
                presentation_kind='show' if fmt=='pps' else 'template' if fmt=='pot' else 'presentation'
                add('powerpoint.presentation_kind','演示文稿类型是什么？',presentation_kind,
                    '依据扩展名识别演示、放映或模板。','逻辑文件名','文件扩展名',target='powerpoint.presentation_kind')
                if ole.exists('PowerPoint Document'):
                    import struct
                    ppt_stream=ole.openstream('PowerPoint Document').read()
                    def walk_ppt_slides(data,offset=0,max_depth=10,depth=0):
                        slides=0
                        while offset+8<=len(data):
                            ver_inst,rec_type,length=struct.unpack('<HHI',data[offset:offset+8])
                            ver=ver_inst&0x0F
                            if rec_type==1006:slides+=1
                            elif ver==0x0F and depth<max_depth:
                                slides+=walk_ppt_slides(data[offset+8:offset+8+length],0,max_depth,depth+1)
                            offset+=8+length
                        return slides
                    add('powerpoint.slide_count','幻灯片数量是多少？',walk_ppt_slides(ppt_stream),
                        '统计 PowerPoint Document 流中的 SlideContainer(1006) 记录数。','PowerPoint Document','olefile + struct',target='powerpoint.slide_count')
            embedded_roots=sorted({n.split('/',1)[0] for n in streams if n.startswith('ObjectPool/') or n.startswith('MBD')})
            add('embedded.cfb_storage_count','CFB 中有多少个嵌入对象存储？',len(embedded_roots),
                '统计 ObjectPool 的直接子存储或 MBD* 顶层存储；不是其中流的数量。','CFB directory','olefile 0.47',notes=json.dumps(embedded_roots,ensure_ascii=False))
            add('security.has_embedded_files','CFB 是否包含嵌入对象存储？',bool(embedded_roots),
                '依据 ObjectPool/MBD 存储结构判断，不执行嵌入内容。','CFB directory','olefile 0.47',target='security.has_embedded_files')
            for prefix,label in [('images.legacy.image_count','图片数量'),('tables.legacy.table_count','表格数量'),('formulas.legacy.formula_count','公式数量')]:
                unknown(prefix,label+'是多少？','旧二进制 / 加密文档中的语义对象计数。','CFB 流名不能直接给出答案；需要独立内容解码或作者工具核验。','unreadable' if encrypted else 'unknown')
            return rows
    if fmt in {'pdf','docx','xlsx','pptx','xlsb','key','numbers','pages'}:
        unknown('document.structural_facts','页面、图片、表格等结构事实是什么？','按文件实际格式独立取证。','未识别为声明格式的可读容器；可能是伪装、损坏或特殊格式，不能填零。','unreadable')
    else:
        unknown('document.semantic_counts','图片、表格、公式等语义对象数量是多少？','由实际格式及其统计口径决定。','当前独立取证器未覆盖此格式；需要人工核定适用性及数量。')
    return rows


def run(home=DEFAULT_HOME):
    home=Path(home).resolve();Store,_=modules();store=Store(home/'casework')
    project_id=read(home/'maintenance.json',{}).get('project','deckprobe')
    p=store.get(project_id)
    if p.get('factSchema')!=2:
        p=store.act(project_id,{'action':'migrate_facts','revision':p['revision'],'actor':'Codex · 数据迁移','note':'机械拆分文档事实与产品映射，保留原摘要和审批。'})
    original={a['id']:a for s in p['samples'] for a in s['answers']}
    catalog_id=json.loads((home/'declarations.json').read_text())['catalogId']
    catalog_path=home/'catalogs'/catalog_id/'catalog.json'
    if catalog_path.is_file():
        catalog=json.loads(catalog_path.read_text());catalog_shape='per-extension'
    else:
        catalog_path=ROOT/'格式测试数据集'/'DeckProbe字段目录.json'
        if not catalog_path.is_file():raise ValueError('缺少已冻结的 target catalog，不能建立产品字段映射')
        catalog=json.loads(catalog_path.read_text());catalog_id=digest(catalog);catalog_shape='portable'
    def applicable(fmt,target):
        if catalog_shape=='per-extension':
            return any(t['id']==target and t.get('applicable') and 'deep' in t.get('supported_levels',[])
                       for t in catalog.get(fmt,{}).get('targets',[]))
        row=catalog.get('targets',{}).get(target,{})
        return any('deep' in d.get('supported_levels',[]) for profile,d in row.get('profile_details',{}).items()
                   if profile==fmt or (fmt in {'doc','dot','xls','xlt','ppt','pps','pot'} and profile=={'dot':'doc','xlt':'xls','pps':'ppt','pot':'ppt'}.get(fmt,fmt)))
    folder=home/'fact-inventories'/digest({'revision':p['revision'],'extractor':sha(__file__)})[:20];folder.mkdir(parents=True,exist_ok=True);folder.chmod(0o700)
    drafts=[];errors=[]
    for s in p['samples']:
        if sha(s['path'])!=s['sha256']:raise ValueError('样本哈希变化')
        out=folder/(s['id']+'.json')
        # Each document is bounded and isolated from malformed-parser failures.
        command=[sys.executable,'-m','benchmark.acceptance.fact_inventory','inspect',s['path'],s['format'],str(out)]
        try:
            r=subprocess.run(command,capture_output=True,timeout=45)
            if r.returncode:raise ValueError('独立解析失败')
            rows=json.loads(out.read_text())
        except (subprocess.TimeoutExpired,ValueError):
            errors.append(s['id']);rows=[{'kind':'fact','factKey':'document.extraction_status','question':'该文件的结构事实能否独立核定？',
                'expected':None,'valueState':'unreadable','definition':'页面、图片、表格、公式需独立解析或人工确认。',
                'evidence':{'method':'独立解析器预检','location':'本地文件','notes':'解析失败或超过 45 秒预算，未生成虚构数值。'}}]
            rows.append({'kind':'fact','factKey':'file.size_bytes','question':'文件包含多少字节？',
                         'expected':Path(s['path']).stat().st_size,'definition':'原始文件字节数，不等于解压大小。','valueState':'known',
                         'evidence':{'method':'Python stat','location':'原始文件内容'},'_target':'document.file_size'})
            atomic(out,rows)
        for feature,label in [('images','图片'),('tables','表格'),('formulas','公式')]:
            if not any(feature in a['factKey'] or (feature=='tables' and '.table_count' in a['factKey']) for a in rows):
                rows.append({'kind':'fact','factKey':feature+'.pending_scope','question':label+'数量如何统计？',
                    'definition':'先核定此格式下的'+label+'统计口径，再建立可靠答案。', 'valueState':'unknown','expected':None,
                    'evidence':{'method':'覆盖缺口登记','location':'本文件','notes':'当前取证器未给出这项语义事实；不填 0，也不默认不适用。'}})
        atomic(out,rows);out.chmod(0o600)
        for a in rows:
            target=a.pop('_target',None)
            a['evidence'].update(sourceSha256=s['sha256'],recordPath=str(out),recordSha256=sha(out),inspectorSha256=sha(__file__))
            mapping={'status':'unmapped','note':'GT 独立保存；尚未确认可比较的产品字段及口径。'}
            if target and applicable(s['format'],target):
                mapping={'status':'mapped','adapter':'deckprobe','check':{'type':'target','target':target},'options':['-l','deep','-t',target],
                         'requirement':'PRO-R03','note':'基于已验证 target catalog '+catalog_id+'；只映射明确一致的统计口径。'}
            drafts.append({'sampleId':s['id'],'sourceSha256':s['sha256'],'fact':a,'mapping':mapping})
    current=store.get(project_id)
    purpose_keys={s['id']:{'外链数量和地址':['links.external_reference_count','links.external_unique_targets']}
                  for s in current['samples'] if s['id'] in {'pdf-external-link','pptx-external','xlsx-external'}}
    result=store.act(project_id,{'action':'import_fact_drafts','revision':current['revision'],'actor':'Codex · 独立取证',
                                 'note':'按用户要求补充文档事实草案；未知状态保留待核定，不自动批准。','drafts':drafts,'purposeFactKeys':purpose_keys})
    # Keep the full fact inventory, but only place facts that explain this sample's
    # declared purpose into the executable case. This avoids one generic checklist
    # being repeated over every file.
    scopes=[];mapping_updates={}
    selectors={
        '加密':['security.encrypted'], '签名':['signature'], '宏':['vba','macro'],
        '外部关系':['external'], '附件':['attachment','has_embedded_files'], '嵌入对象':['embedded'],
        '公式':['formula','math_object'],
        '表格':['=word.table_count','=excel.table_count','=tables.powerpoint.table_object_count','=tables.iwork.logical_table_count'],
        '隐藏':['hidden'],
        '批注':['comment','annotation'], '注释':['annotation','comment'], '表单':['form_field'], '图片':['image'],
        '图表':['chart_part'], '透视表':['=excel.pivot_table_part_count'], '备注':['notes_slide'],
        '媒体':['media_asset'], '切换':['transition'], '页眉':['header_part','footer_part','header_count','footer_count'],
        '工作表':['=excel.sheet_count','=numbers.sheet_count'], '构建动画':['build_count'], '过滤':['filtered_row','filter'],
        '扩展名':['extension_matches','detected_format_profile','container_kind'],
        '容器':['cfb_container','container_kind','detected_format_profile'],
        '模板':['is_template','presentation_kind','extension_matches'],
        '放映':['presentation_kind','extension_matches'],
        '章节':['section_count'],
        'javascript':['javascript'],
        '画布':['aspect_ratio', 'slide_size', 'orientation'],
        '比例':['aspect_ratio', 'slide_size'],
        '扫描':['pdf.page_count', 'pdf.form_field_count', 'pdf.annotation_count'],
        '页面':['pdf.page_count', 'word.page_count'],
        '作者':['document.author'],
        '标题':['document.title'],
        '名称':['excel.sheet_names', 'pages.section_names'],
        '幻灯片':['powerpoint.slide_count', 'keynote.slide_count'],
        '二进制':['excel.binary_workbook'],
        'mime':['document.mime_type'],
        'xmp':['pdf.has_xmp'],
        '线性化':['pdf.linearized'],
        '单词':['word.word_count'],
        '字符':['word.character_count'],
        '段落':['word.paragraph_count'],
        '缓存':['pages.cached_page_count'],
        '正文':['pages.body_text_length', 'pages.body_paragraph_break_count'],
        '尺寸':['slide_size', 'page_size'],
        '方向':['pages.orientation', 'powerpoint.orientation', 'keynote.orientation'],
    }
    purpose_updates={}
    def selected(key,tokens):
        return any(key==token[1:] if token.startswith('=') else token in key for token in tokens)
    for sample in result['samples']:
        labels=' '.join(x.get('label','') for x in sample.get('purpose',{}).get('checks',[])).lower()
        wanted={token for label,tokens in selectors.items() if label in labels for token in tokens}
        facts=[a for a in sample['answers'] if a.get('kind')=='fact']
        chosen=[]
        for fact in facts:
            key=fact.get('factKey','')
            if selected(key,wanted):chosen.append(fact)
        chosen=[a for a in chosen if a.get('valueState')=='known']
        has_typed_img = any('unique_image_asset_count' in a.get('factKey','') or 'typed_asset_parts' in a.get('factKey','') for a in chosen)
        if has_typed_img:
            chosen = [a for a in chosen if a.get('factKey') not in {'images.package.image_part_count', 'images.package.unique_image_bytes_count', 'images.package.media_part_count'}]
        has_typed_media = any('typed_asset_parts' in a.get('factKey','') for a in chosen if 'media' in a.get('factKey',''))
        if has_typed_media:
            chosen = [a for a in chosen if a.get('factKey') != 'powerpoint.unique_media_asset_count' or any('typed_asset_parts' in x.get('factKey','') for x in chosen)]
        if not chosen and '代表性结构' in labels:
            preferred=['pdf.page_count','powerpoint.slide_count','excel.sheet_count','word.paragraph_count',
                       'office.cfb_entry_count','office.package_entry_count','document.detected_format_profile']
            chosen=[a for key in preferred for a in facts if a.get('factKey')==key and a.get('valueState')=='known'][:1]
            positives=[a for a in facts if a.get('valueState')=='known' and isinstance(a.get('expected'),int)
                       and a.get('expected',0)>0 and any(x in a.get('factKey','') for x in ['image','table','formula','comment','external'])]
            chosen.extend(x for x in positives if x not in chosen)
        chosen=chosen[:8]
        purpose=json.loads(json.dumps(sample.get('purpose',{})))
        mismatch=next((a for a in facts if a.get('factKey')=='document.extension_matches' and a.get('valueState')=='known' and a.get('expected') is False),None)
        if mismatch and purpose.get('source')=='dataset-manifest-v1':
            mismatch_keys=['document.detected_format_profile','document.extension_matches','file.container_kind']
            chosen=[a for a in facts if a.get('factKey') in mismatch_keys]
            purpose={'summary':'验证扩展名与实际容器/profile 不一致时的身份识别和限制行为。','source':'independent-container-audit-v1',
                     'checks':[{'label':'扩展名与实际格式是否一致','type':'fact','factKeys':[a['factKey'] for a in chosen],
                                'note':'该文件不能作为声明扩展名的正常格式正例；如需正常覆盖，应替换为真实对应格式文件。'}]}
        for criterion in purpose.get('checks',[]):
            criterion_wanted={token for label,tokens in selectors.items() if label in criterion.get('label','') for token in tokens}
            matches=[a['factKey'] for a in facts if selected(a.get('factKey',''),criterion_wanted)]
            if matches:criterion['factKeys']=sorted(set(matches))
        if chosen and purpose.get('checks') and not any(c.get('factKeys') for c in purpose['checks']):
            purpose['checks'][0]['factKeys']=[a['factKey'] for a in chosen]
        purpose_updates[sample['id']]=purpose
        chosen_ids={a['id'] for a in chosen}
        scopes.extend({'answerId':a['id'],'mode':'case' if a['id'] in chosen_ids else 'reference',
                       'reason':'与本样本用途直接相关' if a['id'] in chosen_ids else '保留作跨样本参考取证'} for a in facts)
    scopes=[row for row in scopes if not result.get("answerScopes",{}).get(row["answerId"],{}).get("actor") or result["answerScopes"][row["answerId"]]["actor"].startswith("Codex")]
    purpose_updates={sid:value for sid,value in purpose_updates.items() if next(s for s in result["samples"] if s["id"]==sid).get("purpose",{}).get("source") in {"dataset-manifest-v1","independent-container-audit-v1"}}
    if scopes:
        result=store.act(project_id,{'action':'set_case_scopes','revision':result['revision'],'actor':'Codex · 用途筛选',
            'note':'只把与各样本独立目的直接相关的事实纳入 case；完整事实仍保留为参考。',
            'scopes':scopes,'purposeUpdates':purpose_updates,'mappingUpdates':mapping_updates,'confirmMappings':True})
    assert all(original[a['id']]==a for s in result['samples'] for a in s['answers'] if a['id'] in original)
    from .mapping_rules import run as reconcile_mappings
    reconcile_mappings(home)
    result=store.get(project_id)
    facts=[a for s in result['samples'] for a in s['answers'] if a.get('kind')=='fact']
    answer_scopes=result.get('answerScopes',{});mappings=result.get('mappings',{})
    scenarios=[]
    for sample in result['samples']:
        assertions=[a for a in sample['answers'] if answer_scopes.get(a['id'],{}).get('mode')!='reference']
        scenarios.append({'caseId':sample['id'],'title':sample['title'],'format':sample['format'],
            'purpose':sample.get('purpose',{}).get('summary',''),'assertions':len(assertions),
            'pendingFacts':[a.get('factKey') for a in assertions if a.get('valueState') in {'unknown','unreadable'}],
            'unsupportedFacts':[a.get('factKey') for a in assertions if a.get('kind')=='fact' and mappings.get(a['id'],{}).get('status')=='unsupported'],
            'replacementRequired':sample.get('purpose',{}).get('source')=='independent-container-audit-v1'})
    case_answers=[a for s in result['samples'] for a in s['answers'] if answer_scopes.get(a['id'],{}).get('mode')!='reference']
    summary={'samples':len(result['samples']),'facts':len(facts),'newFacts':sum(a['id'] not in original for a in facts),
        'known':sum(a['valueState']=='known' for a in facts),'pendingValues':sum(a['valueState'] in {'unknown','unreadable'} for a in facts),
        'withoutGT':sum(not s['answers'] for s in result['samples']),'parserIssues':errors,
        'caseScenarios':sum(bool(x['assertions']) for x in scenarios),'caseAssertions':len(case_answers),
        'missingScenarios':[x['caseId'] for x in scenarios if not x['assertions']],
        'unresolvedCaseFacts':sum(len(x['pendingFacts']) for x in scenarios),
        'mappedCaseFacts':sum(a.get('kind')=='fact' and mappings.get(a['id'],{}).get('status')=='mapped' for a in case_answers),
        'unsupportedCaseFacts':sum(a.get('kind')=='fact' and mappings.get(a['id'],{}).get('status')=='unsupported' for a in case_answers),
        'replacementRequired':[x['caseId'] for x in scenarios if x['replacementRequired']],
        'conflicts':sum(len(s.get('factFindings',[])) for s in result['samples']),'existingAnswersUnchanged':True}
    atomic(folder/'summary.json',summary);atomic(folder/'scenario-audit.json',{'summary':summary,'scenarios':scenarios})
    lines=['# Casework GT 场景审计','',f"- 样本：{summary['samples']}；有场景：{summary['caseScenarios']}；必要断言：{summary['caseAssertions']}",
        f"- 已映射 Probe 字段：{summary['mappedCaseFacts']}；产品暂未支持：{summary['unsupportedCaseFacts']}；仍需独立核定：{summary['unresolvedCaseFacts']}",'']
    if summary['replacementRequired']:
        lines+=['## 需要替换或重新定性的样本','']+[f"- {x['title']}（{x['format']}）：当前内容与扩展名不符。" for x in scenarios if x['replacementRequired']]+['']
    if summary['unresolvedCaseFacts']:
        lines+=['## 尚待补充独立依据','']+[f"- {x['title']}：{', '.join(x['pendingFacts'])}" for x in scenarios if x['pendingFacts']]+['']
    (folder/'scenario-audit.zh-CN.md').write_text('\n'.join(lines),encoding='utf-8');(folder/'scenario-audit.zh-CN.md').chmod(0o600)
    print(json.dumps(summary))


if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1]=='inspect':atomic(Path(sys.argv[4]),inspect(sys.argv[2],sys.argv[3]))
    else:run()
