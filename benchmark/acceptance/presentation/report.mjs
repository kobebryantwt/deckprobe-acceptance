'use strict';
const model = JSON.parse(document.getElementById('report-data').textContent);
const sourceMap = new Map(model.sources.map(s => [s.id, s]));
const categories = [
 ['PRO-R01','发布追溯','发布包、版本、来源证明和许可证，逐项对照已冻结的发布资产。'],
 ['PRO-R02','安全边界','隔离与监控证据单独呈现；未采集不等于没有异常行为。'],
 ['PRO-R03','格式与限制','逐文件查看独立 GT、预期答案和实际值。一致的草案仍需人工审核。'],
 ['PRO-R04','Target 语义','对照 schema、状态、置信度和证据约束，展开查看系统完整输出。'],
 ['PRO-R05','路径与共享','比较成组请求的事实、成本和允许路径；明确区分规则与独立 GT。'],
 ['PRO-R06','性能观察','逐文件、逐运行方式展示观测值。后台测量不用于正式性能签核。'],
 ['PRO-R07','集成表面','CLI、Node、WASM、Worker、MCP 的文件结果与基准输出。'],
 ['PRO-R08','平台覆盖','区分资产验证和真实平台执行，缺少 runner 的项目保留未完成。'],
 ['PRO-R09','报告入口','对照私密报告要求、实际设置与访问证据。'],
 ['files','文件索引','列出本轮语料中的全部文件、源地址和关联验收项；没有执行记录的文件明确标注。']
];
const kinds = {matched:'一致 / 满足规则',different:'不一致',blocked:'证据不足',unexecuted:'未执行',review:'待判断'};
const statuses = {passed:'PASS',failed:'FAIL',review:'REVIEW',blocked:'BLOCKED'};
const $ = id => document.getElementById(id);
const has = (o,k) => Object.prototype.hasOwnProperty.call(o,k);
const pretty = v => v === undefined ? '字段缺失' : JSON.stringify(v,null,2);
const short = v => {const s=pretty(v); return s.length>95?s.slice(0,95)+'…':s;};
function el(tag,cls,text){const n=document.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=text;return n;}
function a(text,href){const n=el('a','',text);n.href=href;return n;}
function badge(text,kind){return el('span','badge '+kind,text);}
function label(parent,text){parent.append(el('span','field-label',text));}
function jsonBlock(title,value){
 const d=el('details','raw-block'),s=el('summary','',title);d.append(s);
 d.addEventListener('toggle',()=>{if(d.open&&!d.dataset.loaded){d.append(el('pre','raw',pretty(value)));d.dataset.loaded='true';}});return d;
}
function valueBox(parent,value,present=true){
 if(!present){parent.append(el('div','answer-value string','字段缺失'));return;}
 if(Array.isArray(value)&&value.length===0){parent.append(el('div','answer-value string','✓ 0 项差异 / 违规（完全符合契约）'));return;}
 if(value!==null&&typeof value==='object'){
  const text=pretty(value),box=el('div','answer-value');
  if(text.length<=750)box.append(el('pre','',text));
  else {box.append(el('div','',Array.isArray(value)?`${value.length} 项记录`:`${Object.keys(value).length} 个字段`));box.append(jsonBlock('展开完整值 · 不省略字段',value));}
  parent.append(box);
 }else parent.append(el('div','answer-value '+(typeof value==='number'||typeof value==='boolean'||value===null?'scalar':'string'),typeof value==='string'?value:pretty(value)));
}
function meta(parent,items){const dl=el('dl','meta-grid');for(const [k,v] of items){dl.append(el('dt','',k),el('dd','',String(v??'未归档')));}parent.append(dl);}
function sourceBox(parent,source){
 const box=el('div','source-box');box.append(el('div','source-name',source.id));
 const links=el('div','source-links');if(source.href)links.append(a('打开测试文件 ↗',source.href));if(source.originHref)links.append(a('原始来源 ↗',source.originHref));box.append(links);
 box.append(el('div','path',source.path),el('div','path','SHA-256  '+source.sha256));
 box.append(el('div','hint',`${source.format.toUpperCase()} · ${source.bytes.toLocaleString()} bytes · ${source.private?'私有，仅本机':'公开 / 生成样例'}`));parent.append(box);
}
function parsedOutput(data){
 if(data&&typeof data.stdout==='string'){
  try{return JSON.parse(data.stdout);}catch{try{return data.stdout.trim().split('\n').filter(Boolean).map(x=>JSON.parse(x));}catch{return data;}}
 }return data;
}
function reportsIn(value,found=[],path='output'){
 if(!value||typeof value!=='object')return found;
 if(value.results&&typeof value.results==='object'&&value.schema_version!==undefined){found.push({path,report:value});return found;}
 if(Array.isArray(value)){value.forEach((v,i)=>reportsIn(v,found,`${path}[${i}]`));}
 else for(const [k,v] of Object.entries(value)){
  if((k==='text'||k==='stdout')&&typeof v==='string'){try{reportsIn(JSON.parse(v),found,path+'.'+k);}catch{}}
  else if(v&&typeof v==='object')reportsIn(v,found,path+'.'+k);
 }return found;
}
function table(headers,rows){const wrap=el('div','table-wrap'),t=el('table'),head=el('thead'),hr=el('tr');headers.forEach(x=>hr.append(el('th','',x)));head.append(hr);t.append(head);const body=el('tbody');for(const row of rows){const tr=el('tr');row.forEach((v,i)=>{const td=el('td',i===0?'key':'');td.append(el('pre','',typeof v==='string'?v:pretty(v)));tr.append(td);});body.append(tr);}t.append(body);wrap.append(t);return wrap;}
function evidenceBlock(name,baseline=false){
 const data=model.evidence[name],d=el('details','raw-block');d.append(el('summary','',(baseline?'查看比较基准':'查看系统完整输出')+' · '+name.split('/').pop()));
 d.addEventListener('toggle',()=>{
  if(!d.open||d.dataset.loaded)return;d.dataset.loaded='true';
  const output=parsedOutput(data);
  if(name==='evidence/performance.json'&&Array.isArray(output)){
   d.append(el('p','hint',`${output.length} 组配置；逐组展开可查看全部原始测量点。`));
   output.forEach(m=>d.append(jsonBlock(`${m.caseId} · ${m.level} · ${m.mode}`,m)));
   d.append(a('打开全部性能原始记录 ↗',name));return;
  }
  const reports=reportsIn(output);
  if(data&&has(data,'exitCode'))meta(d,[['退出码',data.exitCode],['耗时',data.durationMs===undefined?'未记录':data.durationMs.toFixed(2)+' ms'],['超时',data.timedOut===true?'是':'否']]);
  reports.forEach(({path,report})=>{d.append(el('div','hint',`${path} · ${report.status} · ${report.tool_version||''}`));
   d.append(table(['Target','状态','实际值','置信度'],Object.entries(report.results).map(([key,v])=>[key,v.status,has(v,'value')?v.value:'字段缺失',v.confidence])));
  });
  d.append(jsonBlock('完整原始记录（含路径、证据、stdout / stderr）',data));
  if(!reports.length)d.append(jsonBlock('展开全部输出内容',output));
  d.append(a('打开归档 JSON ↗',name));
 });return d;
}
function targetDetail(row){
 if(row.targetObservation?.kind==='target')return row.targetObservation.result;
 if(!row.answer||row.answer.check.type!=='target')return null;
 const key=row.answer.check.target;
 for(const name of row.evidence){for(const r of reportsIn(parsedOutput(model.evidence[name]))){if(has(r.report.results,key))return r.report.results[key];}}
 return null;
}
function comparisonFields(parent,left,right){
 if(!left||!right||Array.isArray(left)||Array.isArray(right)||typeof left!=='object'||typeof right!=='object')return;
 const keys=[...new Set([...Object.keys(left),...Object.keys(right)])].sort();
 if(keys.length>40)return;
 const differences=keys.filter(k=>has(left,k)!==has(right,k)||pretty(left[k])!==pretty(right[k]));
 if(!differences.length)return;
 const d=el('details','raw-block');d.append(el('summary','',`${differences.length} 个字段值不同（辅助查看，以验收规则判定为准）`));
 const t=table(['字段','预期','实际'],differences.map(k=>[k,has(left,k)?left[k]:'字段缺失',has(right,k)?right[k]:'字段缺失']));
 t.querySelectorAll('tbody tr').forEach(tr=>tr.className='delta');d.append(t);parent.append(d);
}
function proofReferences(parent,references){
 for(const ref of references||[]){
  if(!ref.path)continue;
  const wrap=el('div','proof-reference');wrap.append(a((ref.label||'证据')+' ↗',ref.path));
  if(ref.locator)wrap.append(el('div','path','位置：'+ref.locator));
  const doc=model.documents?.[ref.path];
  if(doc){
   wrap.append(el('div','path','原始文件 SHA-256：'+doc.sha256+' · 换行：'+doc.lineEndings));
   wrap.append(el('pre','document-excerpt',doc.text.trim().slice(0,260)+(doc.text.trim().length>260?'\n…':'')));
   const full=el('details','raw-block');full.append(el('summary','', '展开文件全文'));
   full.addEventListener('toggle',()=>{if(full.open&&!full.dataset.loaded){full.append(el('pre','raw',doc.text));full.dataset.loaded='true';}});wrap.append(full);
  }
  parent.append(wrap);
 }
}
function textList(parent,items,cls='protocol-list'){
 if(!items?.length)return;
 const list=el('ul',cls);items.forEach(text=>list.append(el('li','',text)));parent.append(list);
}
function protocolPlan(parent,row){
 const p=row.protocol;if(!p)return;
 label(parent,'测试动作');textList(parent,p.method);
 label(parent,p.criteriaLabel||'什么结果才满足本项规则');textList(parent,p.criteria,'protocol-list criteria-list');
 if(p.basis?.length){
  const d=el('details','raw-block');d.append(el('summary','','规则依据 · 本轮冻结实现'));
  p.basis.forEach(([path,location])=>{const block=el('div','proof-reference');block.append(a(location+' ↗',path));d.append(block);});parent.append(d);
 }
}
function protocolIntro(row){
 const p=row.protocol,head=el('div','protocol-intro');if(!p)return head;
 head.append(el('span','','测试类型'),badge(p.kind,''));return head;
}
function auditBody(row){
 const audit=row.details.audit,body=el('div','audit-body'),intro=el('div','audit-intro');
 body.append(protocolIntro(row));protocolPlan(intro,row);
 intro.append(el('strong','',audit.summary));if(!row.protocol)intro.append(el('p','',audit.scope));
 const counts=audit.counts||{};intro.append(el('div','hint',`字段核对：${counts.passed||0} 项通过 · ${counts.failed||0} 项失败 · ${counts.blocked||0} 项缺证据`));
 const expand=el('button','','展开所有组件'),collapse=el('button','','折叠所有组件'),controls=el('div','audit-controls');
 expand.onclick=()=>body.querySelectorAll('.audit-group').forEach(g=>g.open=true);collapse.onclick=()=>body.querySelectorAll('.audit-group').forEach(g=>g.open=false);controls.append(expand,collapse);intro.append(controls);body.append(intro);
 audit.groups.forEach((group,index)=>{
  const d=el('details','audit-group'),summary=el('summary'),passed=group.rows.filter(r=>r.status==='passed').length;
  summary.append(el('strong','',group.title),badge(`${passed} / ${group.rows.length} 项通过`,passed===group.rows.length?'matched':'review'));d.append(summary);
  d.open=index===0||group.rows.some(r=>r.status!=='passed');
  for(const f of group.rows){
   const field=el('section','audit-field '+(f.status==='failed'?'audit-different':''));
   const heading=el('div','audit-field-heading');heading.append(el('strong','',f.label),badge(statuses[f.status]||f.status,f.status==='passed'?'matched':f.status==='failed'?'different':f.status));field.append(heading);
   const grid=el('div','audit-values'),left=el('div','audit-expected'),right=el('div','audit-actual');
   left.append(el('div','pane-title','预期 / 已冻结的要求'));right.append(el('div','pane-title','实际 / 本轮取得的证据'));
   valueBox(left,f.expected,f.expected!==null);valueBox(right,f.actual,f.actual!==null);
   proofReferences(left,f.expectedEvidence);proofReferences(right,f.actualEvidence);
   grid.append(left,right);field.append(grid);if(f.note)field.append(el('div','audit-note',f.note));d.append(field);
  }body.append(d);
 });
 if(audit.log){
  const log=el('section','audit-log');log.append(el('h3','','签名验证的原始命令与输出'));
  meta(log,[['命令',(audit.log.command||[]).join(' ')],['执行时间',audit.log.startedAt],['依赖目录',audit.log.cwd]]);
  log.append(el('pre','raw',audit.log.stdout||'stdout 为空'),el('p','hint',audit.log.stderr?'stderr：'+audit.log.stderr:'stderr：空'));body.append(log);
 }
 const refs=el('div','evidence-links');(row.evidence||[]).forEach(n=>refs.append(a('本项结构化核对记录 ↗',n)));(audit.evidence||[]).forEach(n=>refs.append(a('原始验证记录 ↗',n)));body.append(refs);
 const footer=el('div','case-footer');footer.append(el('span','',row.id),el('span','',`${statuses[row.status]} · 各字段的预期与实际单独绑定证据`));body.append(footer);return body;
}
function caseBody(row){
 if(row.details?.audit)return auditBody(row);
 const body=el('div'),grid=el('div','compare-grid'),left=el('section','pane expected-pane'),right=el('section','pane actual-pane');
 const p=row.protocol||{};
 body.append(protocolIntro(row));
 left.append(el('div','pane-title',row.answer?'01 / 预期答案与取证依据':'01 / 测试设计与通过条件'));right.append(el('div','pane-title','02 / 本轮执行与结果'));
 protocolPlan(left,row);
 if(p.showExpected||row.answer){label(left,p.expectedLabel||'预期答案');valueBox(left,row.expected,has(row,'expected'));}
 label(right,row.comparison==='unexecuted'?'执行状态':p.actualLabel||'本轮观察');
 if(row.comparison==='unexecuted')valueBox(right,row.executionReason||'本轮尚未执行。');
 else if(row.targetObservation?.kind==='error'){
  valueBox(right,'未返回目标值 · '+(row.targetObservation.error?.code||'error'));
  meta(right,[['系统状态','error'],['错误说明',row.targetObservation.error?.message]]);
 }else if(row.targetObservation?.kind==='missing')valueBox(right,'系统输出中缺少该 target');
 else if(row.targetObservation?.kind==='target')valueBox(right,row.targetObservation.result.value,row.targetObservation.valuePresent);
 else if(p.observed||p.observedFields){
  if(p.observed)right.append(el('p','observation-summary',p.observed));
  if(p.observedFields?.length)right.append(table(['观察项','本轮记录'],p.observedFields.map(([k,v])=>[k,v===undefined?'未记录':v])));
 }else valueBox(right,row.actual,has(row,'actual'));
 textList(right,p.observations,'protocol-list observations');
 if(p.limitation){const limit=el('div','scope-note');limit.append(el('strong','','这项结论的范围'),el('p','',p.limitation));right.append(limit);}
 const target=targetDetail(row);
 if(target)meta(right,[['Target 状态',target.status],['置信度',`${target.confidence??'未记录'} / ${has(target,'confidence_score')?target.confidence_score:'未记录'}`],['解析路径',target.path],['系统证据来源',target.source]]);
 if(row.answer){
  label(left,'GT · 独立依据');
  meta(left,[['取证方法',row.answer.evidence.method],['依据位置',row.answer.evidence.location],['答案审核',row.approval==='approved'?'已审核':'待逐条审核'],['答案哈希',row.answer.answerDigest]]);
  left.append(jsonBlock('完整 GT（答案、依据、请求参数）',row.answer));
 }else if(row.approval==='draft')left.append(el('div','notice','答案独立依据未与当前归档绑定；不能用后来修改的 GT 补作证明。'));
 if(row.sourceIds.length){
  const sources=el('details','source-details');sources.open=row.sourceIds.length<=2;
  sources.append(el('summary','',`${row.id==='private_sources_protected'?'受保护、未扫描的文件':'关联测试文件'} · ${row.sourceIds.length} 份`));
  row.sourceIds.forEach(id=>sourceBox(sources,sourceMap.get(id)));left.append(sources);
 }
 row.baselineEvidence.forEach(n=>left.append(evidenceBlock(n,true)));
 if(row.comparison==='matched'&&row.approval==='draft')right.append(el('div','notice','实际值与草案一致；GT 仍待审核，正式状态保持 REVIEW。'));
 if(row.comparison==='different'&&row.approval==='draft')right.append(el('div','notice','实际值与草案不一致；需复核 GT 与依据，尚未形成正式失败结论。'));
 if(row.id==='background_performance'){
  const measurements=model.evidence['evidence/performance.json']||[];
  right.append(table(['文件 / 配置','样本数','p50 / p95 (ms)','状态'],measurements.map(m=>[
   `${m.caseId}\n${m.level} · ${m.mode}`,m.samples?.length??0,
   `${m.p50Ms?.toFixed(3)??'—'} / ${m.p95Ms?.toFixed(3)??'—'}`,m.complete?'后台观察':'单点 / 未完成'
  ])));
 }
 if(row.id==='performance_pair'&&row.details?.distributions?.length){
  const fixed=v=>typeof v==='number'?v.toFixed(3):'—';
  const change=(ms,relative)=>`${fixed(ms)} ms / ${typeof relative==='number'?(relative*100).toFixed(1)+'%':'—'}`;
  right.append(table(['文件 / 配置','前版 p50 / p95 (ms)','候选版 p50 / p95 (ms)','变化 p50 / p95','结论'],row.details.distributions.map(m=>[
   `${m.caseId}\n${m.level} · ${m.mode}`,
   `${fixed(m.previousP50Ms)} / ${fixed(m.previousP95Ms)}`,
   `${fixed(m.candidateP50Ms)} / ${fixed(m.candidateP95Ms)}`,
   `${change(m.p50DeltaMs,m.p50RelativeDelta)}\n${change(m.p95DeltaMs,m.p95RelativeDelta)}`,
   m.status==='review'?'需复核':'趋势观察'
  ])));
 }
 if(p.showExpected||row.answer)comparisonFields(right,row.expected,row.actual);
 row.evidence.forEach(n=>right.append(evidenceBlock(n)));
 if(!row.evidence.length)right.append(el('div','hint','本项没有归档原始输出；以上为原验收记录中的结果或缺口说明。'));
 if(row.command?.length)right.append(jsonBlock('复现命令（逐参数记录）',row.command));
 right.append(jsonBlock('原始判定记录 · 保留机器值与原结论',{id:row.id,title:row.title,status:row.status,expected:row.expected,actual:row.actual}));
 grid.append(left,right);body.append(grid);
 const foot=el('div','case-footer');foot.append(el('span','',row.id),el('span','',`${row.id.startsWith('schema_')&&row.status==='passed'?'契约通过':statuses[row.status]} · ${row.role==='observation'?'仅观察':row.scope==='full'?'完整手册':'本机必须项'}`));body.append(foot);return body;
}
function caseCard(row,forceOpen=false){
 const d=el('details','case');d.id='case-'+row.id;d.dataset.comparison=row.comparison;d.dataset.status=row.status;
 const summary=el('summary'),heading=el('div','case-heading');
 const first=sourceMap.get(row.sourceIds[0]);
 summary.append(el('span','chevron','›'),el('span','case-icon',first?first.format.toUpperCase():row.requirement.replace('PRO-','')));
 heading.append(el('div','case-title',row.protocol?.question||row.title),el('div','case-sub',row.sourceIds.length>2?`${row.protocol?.kind||row.id} · ${row.sourceIds.length} 份关联文件`:row.sourceIds.length?row.sourceIds.join(' · '):row.id));summary.append(heading);
 if(row.answer)summary.append(el('span','summary-value',`${short(row.expected)} → ${row.comparison==='unexecuted'?'未执行':row.targetObservation?.kind==='error'?(row.targetObservation.error?.code||'error'):row.targetObservation?.kind==='missing'?'target 缺失':row.targetObservation?.valuePresent===false?'value 缺失':short(row.actual)}`));
 else if(Array.isArray(row.expected)&&row.expected.length===0&&Array.isArray(row.actual)&&row.actual.length===0)summary.append(el('span','summary-value','0 差异 · 契约完全符合'));
 const badges=el('div','badges');badges.append(badge(kinds[row.comparison],row.comparison));
 if(row.approval==='draft')badges.append(badge('GT 待审核','review'));else badges.append(badge(row.id.startsWith('schema_')&&row.status==='passed'?'契约通过':statuses[row.status],row.status==='failed'?'different':row.status==='blocked'?'blocked':''));summary.append(badges);d.append(summary);
 function populate(){if(!d.dataset.loaded){d.append(caseBody(row));d.dataset.loaded='true';}}
 d.addEventListener('toggle',()=>{if(d.open)populate();});
 d.open=forceOpen||row.comparison!=='matched';if(d.open)populate();return d;
}
let selected='PRO-R03',fileFocus=null;
function categoryRows(){return model.rows.filter(r=>r.requirement===selected);}
function rowMatches(row){
 const q=$('search').value.toLowerCase().trim(),state=$('state-filter').value,format=$('format-filter').value;
 if(fileFocus&&!row.sourceIds.includes(fileFocus))return false;
 if(q&&!JSON.stringify([row.title,row.id,row.sourceIds,row.expected,row.actual,row.answer,row.protocol]).toLowerCase().includes(q))return false;
 if(format!=='all'&&!row.sourceIds.some(id=>sourceMap.get(id)?.format===format))return false;
 if(state==='attention'&&row.comparison==='matched')return false;
 if(state==='different'&&row.comparison!=='different')return false;
 if(state==='matched'&&row.comparison!=='matched')return false;
 if(state==='draft'&&row.approval!=='draft')return false;return true;
}
function sourceCard(source){
 const card=el('article','source-card'),head=el('div','source-card-head');head.append(el('h3','',source.id),badge(source.private?'私有 · 本机':'公开 / 生成',''));card.append(head);sourceBox(card,source);
 const rows=model.rows.filter(r=>r.sourceIds.includes(source.id));
 const observed=rows.some(r=>r.evidence.length&&r.comparison!=='unexecuted');
 card.append(el('p','source-result',`${rows.length} 条关联断言 · ${observed?'有执行证据':'未执行 / 无可绑定的执行证据'}`));
 if(!rows.length)card.append(el('p','empty-note',source.private?'本轮未扫描该私有文件；等待安全隔离、监控能力及 GT 准备完成。':'本轮没有该文件的可绑定断言。GT 与实际结果缺口待补齐。'));
 for(const row of rows){const l=a(`${row.requirement.replace('PRO-','')} · ${row.title}`,`#${row.requirement}/${encodeURIComponent(row.id)}`);l.className='source-case-link';l.append(badge(kinds[row.comparison],row.comparison));card.append(l);}
 return card;
}
function renderRows(forceId=null){
 const root=$('cases');root.replaceChildren();
 if(selected==='files'){
  const q=$('search').value.toLowerCase().trim(),format=$('format-filter').value;
  const sources=model.sources.filter(s=>(format==='all'||s.format===format)&&JSON.stringify(s).toLowerCase().includes(q));
  sources.forEach(s=>root.append(sourceCard(s)));$('section-count').textContent=`${sources.length} / ${model.sources.length} 份文件`;$('empty').hidden=!!sources.length;
 }else{
  const all=categoryRows(),order={different:0,unexecuted:1,blocked:2,review:3,matched:4},rows=all.filter(rowMatches).sort((a,b)=>order[a.comparison]-order[b.comparison]);rows.forEach(r=>root.append(caseCard(r,r.id===forceId)));
  $('section-count').textContent=`${rows.length} / ${all.length} 条断言`;$('empty').hidden=!!rows.length;
 }
 if(forceId){const card=document.getElementById('case-'+forceId);if(card)requestAnimationFrame(()=>card.scrollIntoView({block:'start'}));}
}
function selectCategory(id,focusId=null){
 selected=categories.some(c=>c[0]===id)?id:'PRO-R03';fileFocus=null;
 document.querySelectorAll('[role=tab]').forEach(t=>{t.setAttribute('aria-selected',String(t.dataset.category===selected));t.tabIndex=t.dataset.category===selected?0:-1;});
 const def=categories.find(c=>c[0]===selected);$('section-kicker').textContent=selected==='files'?'SOURCE INVENTORY':selected+' / ACCEPTANCE CASES';$('section-title').textContent=def[1];$('section-description').textContent=def[2];$('panel').setAttribute('aria-labelledby','tab-'+selected);
 $('state-filter').disabled=selected==='files';$('column-guide').hidden=selected==='files';$('expand').disabled=selected==='files';$('collapse').disabled=selected==='files';
 if(focusId){$('search').value='';$('state-filter').value='all';$('format-filter').value='all';}renderRows(focusId);
}
function reset(){fileFocus=null;$('search').value='';$('state-filter').value='all';$('format-filter').value='all';renderRows();}
$('run-label').textContent=`${model.targetVersion} · ${model.mode==='diagnostic'?'样本诊断':'正式验收'} · ${new Date(model.createdAt).toLocaleString('zh-CN')} · ${model.rows.length} 条断言`;
$('verdict').textContent=`${model.quality.localDecision} / ${model.quality.releaseDecision}`;
$('notice').textContent=(model.mode==='diagnostic'?'这是已归档的样本诊断：可查看实际值，但未审 GT 仍为 REVIEW。':'这是已归档的正式验收：未审 GT 的实际值保留“未执行”。')+' 一致项默认折叠，差异与未完成项默认展开。'+(!model.context.corpusBound||!model.context.answersBound?' 部分样本 / GT 元数据未能与原运行绑定，页面明确保留缺口。':'');
for(const [key,name,sub,cls] of [['passed','已通过','验收规则已满足','green'],['failed','已失败','确定性必须项失败','red'],['review','待审核','含 GT 草案与观察项',''],['blocked','未完成','缺少环境或可靠证据','']]){
 const card=el('div','metric '+cls),copy=el('div');copy.append(el('span','label',name),el('span','',sub));card.append(copy,el('strong','',model.counts[key]??model.rows.filter(r=>r.status===key).length));$('metrics').append(card);
}
for(const [id,title] of categories){const b=el('button','tab');b.id='tab-'+id;b.dataset.category=id;b.setAttribute('role','tab');b.setAttribute('aria-controls','panel');b.append(el('small','',id==='files'?'ALL':id.replace('PRO-','')),document.createTextNode(title),el('em','',id==='files'?model.sources.length:model.rows.filter(r=>r.requirement===id).length));b.onclick=()=>{location.hash=id;selectCategory(id);};$('tabs').append(b);}
$('tabs').addEventListener('keydown',event=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;event.preventDefault();const tabs=[...$('tabs').children],i=tabs.indexOf(document.activeElement);let next=event.key==='Home'?0:event.key==='End'?tabs.length-1:(i+(event.key==='ArrowRight'?1:-1)+tabs.length)%tabs.length;tabs[next].focus();tabs[next].click();});
for(const f of [...new Set(model.sources.map(s=>s.format))].sort()){$('format-filter').append(new Option(f.toUpperCase(),f));}
$('search').addEventListener('input',()=>renderRows());$('state-filter').onchange=()=>renderRows();$('format-filter').onchange=()=>renderRows();$('reset').onclick=reset;$('clear-empty').onclick=reset;
$('expand').onclick=()=>document.querySelectorAll('.case').forEach(d=>d.open=true);$('collapse').onclick=()=>document.querySelectorAll('.case').forEach(d=>d.open=false);
function hashRoute(){const [id,focus]=location.hash.slice(1).split('/');let decoded=null;try{decoded=focus?decodeURIComponent(focus):null;}catch{}selectCategory(id||'PRO-R03',decoded);}
window.addEventListener('hashchange',hashRoute);hashRoute();
