"""Versioned, conservative mapping reconciliation; never grants GT approval."""
import json
import zipfile
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from .common import DEFAULT_HOME, ROOT, atomic, digest, locked, read, sha
from .maintenance import modules, sync

VERSION_SUFFIX='-mapping-v2'
# Explicit semantic matches; similar names alone never confer equivalence.
EXACT={k:k for k in ['pdf.page_count','pdf.annotation_count','pdf.form_field_count','pdf.attachment_count','pdf.has_xmp','pdf.linearized',
 'word.paragraph_count','word.table_count','word.comment_part_count','word.page_count','word.word_count','word.character_count','word.is_template',
 'excel.sheet_count','excel.sheet_names','excel.hidden_sheet_count','excel.table_count','excel.chart_part_count',
 'excel.pivot_table_part_count','excel.is_template','excel.binary_workbook',
 'powerpoint.slide_count','powerpoint.hidden_slide_count','powerpoint.comment_part_count',
 'powerpoint.chart_part_count','powerpoint.notes_slide_count','powerpoint.presentation_kind',
 'powerpoint.aspect_ratio','powerpoint.slide_size','powerpoint.orientation',
 'numbers.sheet_count','numbers.sheet_names','office.cfb_container',
 'keynote.slide_size','keynote.aspect_ratio','keynote.orientation',
 'pages.section_count','pages.section_names','pages.cached_page_count','pages.body_text_length','pages.body_paragraph_break_count','pages.page_size','pages.orientation',
 'document.mime_type','document.title','document.author','document.subject','document.keywords',
 'security.encrypted','security.has_macros','security.has_digital_signature','security.signature_count',
 'security.has_embedded_files','security.has_external_relationships','security.has_javascript']}
EXACT['file.size_bytes']='document.file_size'
# These facts have narrower scopes than related targets, or ambiguous definitions.
REVIEW={'document.detected_format_profile','document.extension_matches','office.cfb_entry_count',
 'tables.iwork.logical_table_count','iwork.build_count','iwork.transition_slide_count',
 'powerpoint.unique_media_asset_count','pages.header_count','pages.footer_count'}
NO_EQUIVALENT={'images.package.unique_image_bytes_count','images.package.image_part_count',
 'images.pdf.image_xobject_count','links.external_reference_count','links.external_unique_targets',
 'pdf.attachment_names','macros.vba_project_count','embedded.package_part_count','embedded.cfb_storage_count',
 'formulas.excel.stored_formula_cell_count','formulas.powerpoint.math_object_count','formulas.word.math_object_count',
 'comments.word.comment_count','comments.powerpoint.comment_count','word.header_part_count','word.footer_part_count',
 'word.chart_part_count','powerpoint.transition_slide_count','numbers.filter_rule_count'}

def resolve(sample,fact,catalog):
 key=fact['factKey'];fmt=sample['format'];target=EXACT.get(key)
 if key=='office.package_entry_count':target='iwork.package_entry_count' if fmt in {'key','numbers','pages'} else 'office.package_entry_count'
 for family,prefix in [('word','word'),('excel','xl'),('powerpoint','ppt')]:
  if key==f'images.{family}.typed_asset_parts':target=f'{family}.unique_image_asset_count'
 if key=='media.powerpoint.typed_asset_parts':target='powerpoint.unique_media_asset_count'
 profiles={'dot':'doc','xlt':'xls','pps':'ppt','pot':'ppt'}.get(fmt,fmt)
 entry=catalog['targets'].get(target,{}) if target else {}
 details=entry.get('profile_details',{}).get(profiles,{})
 tool_ver=catalog.get('tool_version','2.5.0')
 base={'adapter':'deckprobe','ruleVersion':tool_ver+VERSION_SUFFIX,'catalogDigest':digest(catalog),
       'productVersion':tool_ver,'definitionDigest':digest(fact.get('definition','')),
       'factKey':key,'requirement':'PRO-R03'}
 if target and 'deep' in details.get('supported_levels',[]):
  return {**base,'status':'mapped','check':{'type':'target','target':target},'options':['-l','deep','-t',target],
          'note':'按集中规则匹配统计口径；GT 的已知值与人工审批仍独立检查。'}
 if key in NO_EQUIVALENT:
  return {**base,'status':'unsupported','check':{},'options':[], 'note':'当前目录无同口径字段；保留独立 GT，不拿相似字段代替。'}
 return {**base,'status':'unmapped','check':{},'options':[],
         'note':'统计范围或格式适用性尚需核定，暂停比较；不能据此认定产品不支持。'}

def typed_assets(sample):
 """Content-Type and scoped unique part names; never hash-deduplicate bytes."""
 path=Path(sample['path'])
 if not zipfile.is_zipfile(path):return []
 with zipfile.ZipFile(path) as z:
  if '[Content_Types].xml' not in z.namelist():return []
  root=ET.fromstring(z.read('[Content_Types].xml'));defaults={};overrides={}
  for x in root:
   if x.tag.endswith('Default'):defaults[x.get('Extension','').lower()]=x.get('ContentType','').lower()
   elif x.tag.endswith('Override'):overrides[x.get('PartName','').lstrip('/').lower()]=x.get('ContentType','').lower()
  names={n.lower() for n in z.namelist()};rows=[]
  for family,prefix in [('word','word'),('excel','xl'),('powerpoint','ppt')]:
   if not any(n.startswith(prefix+'/') for n in names):continue
   for kind,mimes in [('images',('image/',)),('media',('audio/','video/'))]:
    if kind=='media' and family!='powerpoint':continue
    chosen=sorted(n for n in names if n.startswith(prefix+'/media/') and overrides.get(n,defaults.get(n.rsplit('.',1)[-1],'')).startswith(mimes))
    rows.append({'kind':'fact','factKey':f'{kind}.{family}.typed_asset_parts','question':('图片' if kind=='images' else '音视频')+'资源部件有多少个（按部件名去重）？',
      'definition':f'{prefix}/media/ 内按 Content-Type 识别的部件名数量；名称小写去重，不按内容去重，不含其他目录。',
      'expected':len(chosen),'valueState':'known','evidence':{'method':'Python zipfile + ElementTree',
      'location':'[Content_Types].xml + '+prefix+'/media/','parts':chosen,'sourceSha256':sample['sha256'],
      'inspectorSha256':sha(__file__)}})
 return rows

def run(home=DEFAULT_HOME):
 home=Path(home);Store,_=modules();store=Store(home/'casework');pid=read(home/'maintenance.json')['project']
 catalog=read(ROOT/'格式测试数据集/DeckProbe字段目录.json')
 if not catalog.get('targets'):raise ValueError('Catalog does not declare any targets')
 p=store.get(pid);before={a['id']:a for s in p['samples'] for a in s['answers']};drafts=[];scopes=[];updates={};protected=[]
 for s in p['samples']:
  if sha(s['path'])!=s['sha256']:raise ValueError('Sample hash changed: '+s['id'])
  relevant=[a for a in s['answers'] if p.get('answerScopes',{}).get(a['id'],{}).get('mode')!='reference']
  need_images=any('image' in a.get('factKey','') for a in relevant)
  need_media=any('media' in a.get('factKey','') for a in relevant)
  for fact in typed_assets(s):
   if (fact['factKey'].startswith('images.') and need_images) or (fact['factKey'].startswith('media.') and need_media):
    drafts.append({'sampleId':s['id'],'sourceSha256':s['sha256'],'fact':fact})
 drafts=[r for r in drafts if not any(a.get('factKey')==r['fact']['factKey'] for s in p['samples'] if s['id']==r['sampleId'] for a in s['answers'])]
 if drafts:p=store.act(pid,{'revision':p['revision'],'action':'import_fact_drafts','actor':'mapping-reconciler','drafts':drafts,'note':'新增部件计数口径；不改变原答案或审批'})
 new_keys={(r['sampleId'],r['fact']['factKey']) for r in drafts}
 for s in p['samples']:
  for a in s['answers']:
   if a.get('kind')!='fact':continue
   current=p.get('mappings',{}).get(a['id'],{})
   actor=current.get('actor','')
   if actor and not actor.startswith('Codex') and actor!='mapping-reconciler':protected.append(a['id']);continue
   suggested=resolve(s,a,catalog)
   # Avoid changing manual definitions under an existing fact key.
   if a.get('revision',1)>1 and a.get('factVersion')==2 and (not current.get('ruleVersion') or current.get('definitionDigest')!=digest(a.get('definition',''))):
    suggested={**suggested,'status':'unmapped','check':{},'options':[],'note':'事实曾被人工修订；保留答案，需核对新统计口径后恢复映射。'}
   clean={k:v for k,v in current.items() if k not in {'revision','actor','at'}}
   if clean!=suggested:updates[a['id']]=suggested
   if (s['id'],a['factKey']) in new_keys and a['id'] not in before:
    scopes.append({'answerId':a['id'],'mode':'case','reason':'与原图片/媒体用途对应的精确部件计数'})
 if scopes or updates:p=store.act(pid,{'revision':p['revision'],'action':'set_case_scopes','actor':'mapping-reconciler',
   'scopes':scopes,'mappingUpdates':updates,'confirmMappings':True,'note':'按集中版本规则修正映射；保留 GT、审批与人工范围'})
 assert all(a==before[a['id']] for s in p['samples'] for a in s['answers'] if a['id'] in before)
 with locked(home):sync(home)
 active=[a for s in p['samples'] for a in s['answers'] if a.get('kind')=='fact' and p['answerScopes'].get(a['id'],{}).get('mode')!='reference']
 report={'ruleVersion':VERSION,'revision':p['revision'],'newFacts':sum(a['id'] not in before for a in active),
  'changedMappings':len(updates),'protectedManualMappings':protected,'caseMappings':dict(Counter(p['mappings'][a['id']]['status'] for a in active)),
  'answersAndApprovalsPreserved':True}
 atomic(home/'mapping-audit.json',report);return report

if __name__=='__main__':print(json.dumps(run(),ensure_ascii=False))
