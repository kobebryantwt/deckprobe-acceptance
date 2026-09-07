"""Grouped, Chinese GT presentation; never edits answers or approvals."""
from pathlib import Path
import json
from urllib.parse import urlparse

from .common import CODE, atomic, read
from .corpus import approved

FORMATS = {
    'pdf': ('PDF', 'PDF 文档'),
    'doc': ('Word', 'Word 旧版文档'), 'dot': ('Word', 'Word 旧版模板'),
    'docx': ('Word', 'Word 文档'), 'dotx': ('Word', 'Word 模板'),
    'docm': ('Word', 'Word 宏格式文档'), 'dotm': ('Word', 'Word 宏格式模板'),
    'xls': ('Excel', 'Excel 旧版工作簿'), 'xlt': ('Excel', 'Excel 旧版模板'),
    'xlsx': ('Excel', 'Excel 工作簿'), 'xltx': ('Excel', 'Excel 模板'),
    'xlsm': ('Excel', 'Excel 宏格式工作簿'), 'xltm': ('Excel', 'Excel 宏格式模板'),
    'xlsb': ('Excel', 'Excel 二进制工作簿'),
    'ppt': ('PowerPoint', 'PowerPoint 旧版演示文稿'), 'pps': ('PowerPoint', 'PowerPoint 旧版放映文件'),
    'pot': ('PowerPoint', 'PowerPoint 旧版模板'), 'pptx': ('PowerPoint', 'PowerPoint 演示文稿'),
    'ppsx': ('PowerPoint', 'PowerPoint 放映文件'), 'potx': ('PowerPoint', 'PowerPoint 模板'),
    'pptm': ('PowerPoint', 'PowerPoint 宏格式演示文稿'), 'ppsm': ('PowerPoint', 'PowerPoint 宏格式放映文件'),
    'potm': ('PowerPoint', 'PowerPoint 宏格式模板'),
    'key': ('iWork', 'Keynote 演示文稿'), 'numbers': ('iWork', 'Numbers 表格'), 'pages': ('iWork', 'Pages 文档'),
}
SCENARIOS = {
    'count': ('页数与数量', '核对 PDF 页数、幻灯片数或工作表数；零值也应与字段缺失区分。'),
    'macro': ('是否包含宏', '宏格式的扩展名不代表文件内一定有宏；这里核对 VBA 项目的存在性。'),
    'encryption': ('是否加密', '核对文件的加密标记；不执行密码破解或解密。'),
    'mismatch': ('后缀与内容不符', '同一段 HTML 内容使用不同文档后缀，逐项检查系统应如何拒绝或识别。'),
    'damaged': ('文件损坏', '文件内容被截断，检查应返回的错误。'),
    'legacy': ('旧格式限制', '以最小旧 XML 结构样例检查不支持行为；不能替代真实历史文档。'),
    'other': ('其他待审规则', '保留原始规则和证据，逐条核对。'),
}


def describe(answer, source):
    ext = answer['format']; family, format_name = FORMATS.get(ext, ('其他', ext.upper()))
    ev = answer.get('evidence', {}); provenance = source.get('provenance', {})
    params = ev.get('parameters') or provenance.get('parameters', {})
    check = answer['check']; target = check.get('target'); expected = answer['expected']
    scenario = 'other'; question = answer['question']; expectation = json.dumps(expected, ensure_ascii=False)
    explanation = []; limitation = ''
    sample = format_name + '样本'
    if provenance.get('type') == 'public-pinned':
        name = Path(urlparse(provenance.get('url', '')).path).name
        sample = '公开样本' + (' · ' + name if name else '')
    elif provenance.get('type') == 'generated':
        sample = '自动生成的最小结构样本'
        if 'pages' in params: sample = f'按 {params["pages"]} 页构造的 PDF 样本'
        elif 'structureCount' in params: sample = f'包含 {params["structureCount"]} 项结构的最小样本'
        if params.get('javascript'): sample = '带 JavaScript 结构的 PDF 样本'
        if params.get('externalLink') or params.get('externalRelationship'): sample = '含外链结构的样本'
    if params.get('container') == 'html':
        scenario = 'mismatch'; sample = f'HTML 内容，文件后缀改为 .{ext}'
        question = f'{format_name}：后缀是 .{ext}，内容却是 HTML，是否应拒绝解析？'
        expectation = '返回“输入损坏或格式不合法”错误（MALFORMED_INPUT）' if expected == 'MALFORMED_INPUT' else expectation
        explanation = ['按固定参数生成一段 HTML 文本，再保存为 .' + ext + ' 文件；这不是一个有效的 ' + format_name + '。',
                       '原始构造参数为 container = html，可据此复核后缀与内容不符的条件。']
        limitation = '构造参数说明样本条件；它本身不能证明应返回哪个错误码。错误码预期仍需结合该版本契约确认。'
    elif 'truncation' in params:
        scenario = 'damaged'; sample = f'仅保留开头 {params["truncation"]} 字节的文件'
        question = f'{format_name}被截断后，是否应报告输入损坏？'
        expectation = '返回“输入损坏或格式不合法”错误（MALFORMED_INPUT）' if expected == 'MALFORMED_INPUT' else expectation
        explanation = [f'从基础 OOXML 包仅保留开头 {params["truncation"]} 字节，完整包结构已被截断。']
        limitation = '这是构造方式记录；预期错误码仍需按版本契约审核。'
    elif params.get('legacyXML'):
        scenario = 'legacy'; sample = '自动生成的旧 XML 最小结构样例'
        question = f'{format_name}的旧 XML 结构样例，是否应报告不支持？'
        expectation = '返回“不支持该格式”错误（UNSUPPORTED_FORMAT）' if expected == 'UNSUPPORTED_FORMAT' else expectation
        explanation = ['按固定参数生成含旧 XML 入口的最小包；原始参数标记 legacyXML 与 structuralFixtureOnly。']
        limitation = '该样例不是由历史 iWork 软件导出的真实文档；预期状态仍需版本契约支持。'
    elif target in {'pdf.page_count', 'excel.sheet_count', 'powerpoint.slide_count'}:
        scenario = 'count'; noun, unit = {'pdf.page_count':('页面','页'), 'excel.sheet_count':('工作表','张'), 'powerpoint.slide_count':('幻灯片','张')}[target]
        question = f'这份{format_name}有多少{noun}？'; expectation = f'{expected} 页' if target == 'pdf.page_count' else f'{expected} {unit}{noun}'
        if target == 'pdf.page_count': explanation = ['使用 pypdf PdfReader 读取 PDF 页面树，统计 reader.pages 中的页面数。', '依据位置：PDF 的 /Root → /Pages 页面树。使用的解析器不同于产品中的 Rust lopdf。']
        elif target == 'excel.sheet_count' and 'xlrd' in ev.get('method',''): explanation = ['使用 xlrd 读取旧版 Excel 的 BIFF/CFB 结构，以 nsheets 获取工作表数量。', '依据位置：BIFF 的 BoundSheet 工作表记录。使用的解析器不同于产品中的 Rust office_oxide。']
        elif target == 'excel.sheet_count': explanation = ['使用 Python zipfile + ElementTree 打开文档包并读取 xl/workbook.xml，统计其中的 sheet 元素。']
        else: explanation = ['使用 Python zipfile + ElementTree 打开文档包并读取 ppt/presentation.xml，统计其中的 sldId 幻灯片引用。']
    elif target == 'security.has_macros':
        scenario = 'macro'; question = f'这份{format_name}内是否包含 VBA 宏项目？'
        expectation = '包含 VBA 宏项目（true）' if expected is True else '不包含 VBA 宏项目（false）' if expected is False else expectation
        explanation = ['使用 Python zipfile + ElementTree 检查文档包成员，查找文件名以 vbaProject.bin 结尾的项目。', '发现项目时，再检查文件开头是否具有 CFB 容器签名；不会执行宏。']
        limitation = '核对的是 VBA 项目的存在性，不是宏的用途或安全性；扩展名带 m 也不等于一定包含宏。'
    elif target == 'security.encrypted':
        scenario = 'encryption'; question = f'这份{format_name}是否被标记为加密？'
        expectation = '已加密（true）' if expected is True else '未加密（false）' if expected is False else expectation
        explanation = ['使用 pypdf PdfReader 的 is_encrypted 属性读取加密状态；不以是否能看到页面作为判定。', '原始证据的位置统一写作 PDF 页面树，没有单独记录加密字典位置；完整原记录保留在下方。']
    if not explanation: explanation = ['当前尚未提供该证据方法的中文释义，请展开原始记录核对。']
    # Unknown evidence methods must not inherit a confident description by target name.
    known = {'Python zipfile + ElementTree', 'pypdf PdfReader (independent of Rust lopdf)',
             'xlrd BIFF/CFB parser (independent of Rust office_oxide)', 'deterministic construction + independent inspection'}
    if ev.get('method') not in known:
        explanation = ['此取证方法尚未适配中文说明；下方保留原始依据。']
    tool = ev.get('method', '未记录')
    if tool == 'deterministic construction + independent inspection': tool = '固定参数构造与独立检查（原记录方法名）'
    elif tool.startswith('pypdf'): tool = 'pypdf PdfReader'
    elif tool.startswith('xlrd'): tool = 'xlrd BIFF/CFB parser'
    bound = source.get('sha256') == answer.get('sourceSha256')
    return {'id':answer['id'], 'family':family, 'format':ext, 'formatName':format_name,
            'scenario':scenario, 'question':question, 'sample':sample, 'expectedText':expectation,
            'basis':explanation, 'tool':tool, 'limitation':limitation, 'bound':bound,
            'href':f'../corpus/objects/{answer["sourceSha256"]}/input.{ext}' if bound else None,
            'raw':answer}


def review_model(home, manifest, answers):
    sources = {s['id']:s for s in manifest['sources']}
    rows = []
    for answer in answers:
        row = describe(answer, sources.get(answer['caseId'], {}))
        decision = read(Path(home)/'answers/decisions'/(answer['answerDigest']+'.json'),{})
        row['review'] = 'approved' if approved(home,answer) else 'rejected' if decision.get('decision') == 'rejected' else 'pending'
        rows.append(row)
    return {'rows':rows, 'scenarios':SCENARIOS, 'gaps':manifest.get('gaps',[])}


def render_grouped_review(home):
    home = Path(home)
    model = review_model(home, read(home/'corpus/manifest.json'), read(home/'answers/index.json')['answers'])
    model['managerUrl'] = read(home/'maintenance.json',{}).get('url')
    assets = CODE/'presentation'
    payload = json.dumps(model,ensure_ascii=False).replace('&','\\u0026').replace('<','\\u003c').replace('>','\\u003e')
    template = (assets/'templates/review.template.html').read_text()
    before, rest = template.split('<!-- TEMPLATE_ONLY_BEGIN -->', 1)
    _, after = rest.split('<!-- TEMPLATE_ONLY_END -->', 1)
    page = (before + after).replace('/*REVIEW_CSS*/',(assets/'review.css').read_text()).replace('/*REVIEW_JS*/',(assets/'review.mjs').read_text()).replace('REVIEW_DATA_JSON',payload)
    atomic(home/'answers/review.html',page)
