'use strict';
const $=id=>document.getElementById(id),labels={pending:'待审核',approved:'已批准',rejected:'已拒绝',deferred:'暂缓',stale:'文件已变 · 需重核'};
let project,selected,token,canApply=false,formAction,formAnswer,formAnswers=[],detailView='scenarios',factFilter='all';
const e=(tag,cls,text)=>{const x=document.createElement(tag);if(cls)x.className=cls;if(text!==undefined)x.textContent=text;return x;};
const pretty=v=>JSON.stringify(v,null,2);
function badge(text,kind=''){return e('span','badge '+kind,text);}
function button(text,fn,cls=''){const b=e('button',cls,text);b.type='button';b.onclick=fn;return b;}
function note(text,bad=false){$('toast').textContent=text;$('toast').className=bad?'error':'success';$('toast').hidden=false;}
async function api(path,body){const r=await fetch(path,body?{method:'POST',headers:{'Content-Type':'application/json','X-Casework-Token':token},body:JSON.stringify(body)}:{});const d=await r.json();if(!r.ok)throw Error(d.error||'请求失败');return d;}
function current(){return project.samples.find(s=>s.id===selected);}
function actor(){const a=$('actor').value.trim();if(!a)throw Error('请先在右上角填写操作者姓名');localStorage.setItem('casework-actor',a);return a;}
async function load(){project=await api('/api/project?id='+encodeURIComponent($('project').value));if(!project.samples.some(s=>s.id===selected))selected=project.samples[0]?.id;render();}
async function mutate(fields){await api('/api/action',{project:project.id,revision:project.revision,actor:actor(),...fields});await load();note('已保存到本机。审批和内容修改均已记录历史。');}
function raw(title,value){const d=e('details','raw');d.append(e('summary','',title));d.addEventListener('toggle',()=>{if(d.open&&!d.dataset.loaded){d.append(e('pre','',pretty(value)));d.dataset.loaded='1';}});return d;}
function human(a){return a.display?.question||a.question;}
const valueLabels={known:'已有独立答案',unknown:'待核定',unreadable:'暂无法取证',not_applicable:'不适用'};
function expected(a){return a.kind==='fact'&&a.valueState!=='known'?(valueLabels[a.valueState]||'待核定'):a.display?.expectedText||pretty(a.expected);}
function inCase(a){return project.answerScopes?.[a.id]?.mode!=='reference';}
function caseAnswers(s){return s.answers.filter(inCase);}
function editScope(a){formAnswer=a;begin(inCase(a)?'移为参考取证':'纳入本 case 的 GT','set_answer_scope');$('edit-fields').append(e('p','',human(a)),e('p','form-hint',inCase(a)?'保留答案、依据和审批历史；不计入待审 GT，也不参与下一轮比对。':'确认这条问题服务于本样本的用途。已有审批保持原状态，产品映射仍需单独配置。'));}
function ruleKey(a){return a.factKey||pretty(a.check||{});}
function scenarioTitle(s,aa){
 const keys=new Set(aa.map(ruleKey)),fmt=s.format.toUpperCase();
 if(aa.some(a=>a.check?.type==='error'))return fmt+' 异常输入与错误隔离';
 if([...keys].some(k=>/signature/.test(k)))return fmt+' 数字签名识别';
 if([...keys].some(k=>/encrypted/.test(k)))return fmt+' 加密与密码保护识别';
 if([...keys].some(k=>/external|links\./.test(k)))return fmt+' 外链识别与统计';
 if([...keys].some(k=>/form_field|annotation/.test(k)))return fmt+' 表单与注释结构';
 if([...keys].some(k=>/macros/.test(k)))return fmt+' 宏能力识别';
 if(keys.size===1&&[...keys][0].includes('page_count'))return fmt+' 页面数量边界';
 if(keys.size===1&&[...keys][0].includes('slide_count'))return fmt+' 幻灯片数量边界';
 if(keys.size===1&&[...keys][0].includes('sheet_count'))return fmt+' 工作表数量边界';
 return s.title+'的专用验收';
}
function scenarios(){return project.samples.filter(s=>caseAnswers(s).length).map(s=>({sample:s,answers:caseAnswers(s)}));}
function scenarioStatus(aa){return aa.some(a=>a.status==='stale')?'stale':aa.some(a=>['unknown','unreadable'].includes(a.valueState))?'deferred':aa.every(a=>a.status==='approved')?'approved':aa.some(a=>a.status==='rejected')?'rejected':'pending';}
function ruleCoverage(a){return new Set(project.samples.filter(s=>caseAnswers(s).some(x=>ruleKey(x)===ruleKey(a))).map(s=>s.id)).size;}
function editScenarioReview(s,aa){formAnswer=null;formAnswers=aa;begin('审核场景 · '+scenarioTitle(s,aa),'review_scenario');const list=e('div','scenario-review-list');for(const a of aa){const row=e('div','scenario-review-row');row.append(e('strong','',human(a)),e('span','',expected(a)),badge(labels[a.status],a.status));list.append(row);}$('edit-fields').append(list);select('decision','审核决定',[['approved','批准场景内全部断言'],['rejected','拒绝，需要修改'],['deferred','暂缓，需要更多证据']],aa.some(a=>['unknown','unreadable'].includes(a.valueState))?'deferred':'approved');field('confirm','我已核对场景内全部断言、答案和依据','','checkbox',true);}
function renderScenarios(s,root){const aa=caseAnswers(s);if(!aa.length){root.append(e('div','empty','这个 case 尚无专用验收场景。参考取证不能代替场景 GT。'));return;}const status=scenarioStatus(aa),card=e('section','scenario-card'),head=e('div','scenario-head');head.append(e('div','',scenarioTitle(s,aa)),badge(labels[status],status),badge(aa.length+' 项必要断言','known'));card.append(head,e('p','scenario-purpose',s.purpose?.summary||'按样本用途组织必要断言。'));
 const rows=e('div','scenario-assertions');for(const a of aa){const d=e('details','scenario-assertion'),sum=e('summary');sum.append(e('strong','',human(a)),e('span','scenario-value',expected(a)),badge(labels[a.status],a.status));d.append(sum);const meta=e('div','scenario-meta');meta.append(e('p','',a.kind==='fact'?'统计口径：'+(a.definition||'待补充'):'版本契约断言'),e('p','',`同类规则覆盖 ${ruleCoverage(a)} 个 case；本条绑定当前文件哈希。`),e('p','',`依据：${a.evidence.method||'待补充'} ${a.evidence.location||''}`));const controls=e('div','review-controls');controls.append(button('修改断言',()=>editAnswer(a)),button('单独审核',()=>editReview(a)),button('移为参考',()=>editScope(a)));meta.append(controls);d.append(meta);rows.append(d);}card.append(rows);const foot=e('div','scenario-footer');foot.append(e('span','',`场景状态：${labels[status]}`),button('审核整个场景',()=>editScenarioReview(s,aa),'primary'));card.append(foot);root.append(card);
 const families=e('details','rule-matrix');families.append(e('summary','',`查看共享规则矩阵 · ${new Set(aa.map(ruleKey)).size} 类规则`));for(const a of aa){const n=ruleCoverage(a),row=e('div','matrix-row');row.append(e('code','',ruleKey(a)),e('span','',n+' 个 case 复用'),e('span','',n>1?'共享规则，不重复定义':'本场景专用'));families.append(row);}root.append(families);}
function mapping(a){return project.mappings?.[a.id]||{status:'unmapped'};}
function mappingLabel(a){return {mapped:'已配置产品映射',unsupported:'产品暂未支持',unmapped:'映射口径待确认'}[mapping(a).status]||'未映射产品字段';}
function render(){
 $('project-title').textContent=project.name;$('export').href='/api/export?id='+encodeURIComponent(project.id);$('apply').hidden=!canApply;
 const answers=project.samples.flatMap(caseAnswers),scene=scenarios();$('stats').replaceChildren();
 const currState=$('state').value;
 const statCards=[
  [project.samples.length,'维护样本','all'],
  [scene.length,'验收场景','all'],
  [answers.length,'底层断言','all'],
  [answers.filter(a=>a.status==='approved').length,'已批准断言','approved'],
  [answers.filter(a=>['pending','stale'].includes(a.status)).length,'待审核断言','pending']
 ];
 for(const [n,t,st] of statCards){
  const isActive=(st==='pending'&&currState==='pending')||(st==='approved'&&currState==='approved');
  const box=e('div',isActive?'active':'');
  box.append(e('strong','',n),e('span','',t));
  box.title='点击按「'+t+'」快速筛选列表';
  box.onclick=()=>{
   $('state').value=st;
   renderList();
   const visible=project.samples.filter(s=>{
    const f=$('format').value, q=$('search').value.toLowerCase();
    return (f==='all'||s.format===f)&&(!q||JSON.stringify([s.id,s.title,s.tags,s.answers.map(a=>[human(a),a.id])]).toLowerCase().includes(q))&&(st==='all'||st==='pending'&&caseAnswers(s).some(a=>['pending','stale'].includes(a.status))||st==='approved'&&caseAnswers(s).some(a=>a.status==='approved'));
   });
   if(visible.length&&!visible.some(s=>s.id===selected)){
    selected=visible[0].id;
    renderDetail();
   }
   render();
  };
  $('stats').append(box);
 }
 const previous=$('format').value;$('format').replaceChildren(new Option('全部格式','all'));[...new Set(project.samples.map(s=>s.format))].sort().forEach(f=>$('format').append(new Option(f.toUpperCase(),f)));$('format').value=[...$('format').options].some(o=>o.value===previous)?previous:'all';renderList();renderDetail();
}
function renderList(){
 const q=$('search').value.toLowerCase(),f=$('format').value,state=$('state').value;
 const rows=project.samples.filter(s=>(f==='all'||s.format===f)&&(!q||JSON.stringify([s.id,s.title,s.tags,s.answers.map(a=>[human(a),a.id])]).toLowerCase().includes(q))&&(state==='all'||state==='active'&&s.active||state==='inactive'&&!s.active||state==='no_gt'&&!caseAnswers(s).length||state==='pending'&&caseAnswers(s).some(a=>['pending','stale'].includes(a.status))||state==='approved'&&caseAnswers(s).some(a=>a.status==='approved')||state==='missing'&&s.health!=='ok'||state==='unknown'&&caseAnswers(s).some(a=>['unknown','unreadable'].includes(a.valueState))||state==='unmapped'&&caseAnswers(s).some(a=>a.kind==='fact'&&mapping(a).status!=='mapped')));
 $('sample-count').textContent=`${rows.length} / ${project.samples.length} 份样本`;$('samples').replaceChildren();
 for(const s of rows){const b=button('',()=>{selected=s.id;detailView='scenarios';renderList();renderDetail();},'sample '+(selected===s.id?'selected':''));b.append(badge(s.format.toUpperCase()),e('strong','',s.title),e('small','',`${caseAnswers(s).length?'1 场景 · '+caseAnswers(s).length+' 项断言':'缺少专用场景'} · ${s.active?'启用':'停用'} · ${s.private?'私有':'公开 / 生成'}`));if(s.health!=='ok')b.append(badge('文件需要重新定位','stale'));$('samples').append(b);}
}
function purposeCurrent(s){return s.purpose && ['sha256','format','inputName'].every(k=>s.purpose.binding?.[k]===s[k]);}
function purposeMatch(c,a){
 if(c.factKey||c.factKeys)return a.kind==='fact'&&(c.factKey===a.factKey||c.factKeys?.includes(a.factKey));
 if(c.type==='contract')return a.kind==='contract'||a.check?.type==='error'||a.expected===c.target;
 if(c.target)return (a.kind==='fact'&&(a.factKey===c.target||a.factKey?.endsWith('.'+c.target)||(c.target.includes('.')&&c.target.endsWith(a.factKey))))||(a.check?.target===c.target);
 return !!c.type && a.check?.type===c.type && (!c.target||a.check?.target===c.target);
}
function isPrimary(s,a){return purposeCurrent(s)&&(s.purpose.checks||[]).some(c=>purposeMatch(c,a));}
function renderPurpose(s,root){
 const box=e('section','purpose-panel'),head=e('div','answer-heading');head.append(e('h3','','这个样本主要验证什么'),button('维护用途',()=>editPurpose()));box.append(head);
 if(!purposeCurrent(s)){box.append(e('p','warning',s.purpose?'文件版本已变化，样本用途需要重新核对。':'尚未登记样本用途。已有 GT 不代表覆盖完整。'));root.append(box);return;}
 box.append(e('p','',s.purpose.summary));
 for(const c of s.purpose.checks||[]){const row=e('div','purpose-row'),matches=caseAnswers(s).filter(a=>purposeMatch(c,a));row.append(e('strong','',c.label));
 const state=!matches.length?'事实 / 依据待补充':matches.some(a=>['unknown','unreadable'].includes(a.valueState))?'答案待核定':matches.some(a=>a.status==='approved')?'已有已审 GT':'GT 待审核';
 row.append(badge(state,matches.some(a=>a.status==='approved')?'approved':'pending'));if(c.note)row.append(e('p','',c.note));box.append(row);}
 box.append(e('small','','这里只说明出题与审核覆盖，不代表产品已通过验收。'));root.append(box);
}
function editPurpose(){begin('维护样本用途','save_purpose');const p=current().purpose;field('purpose-summary','这个文件用于验证什么',p?.summary||'','textarea',true);field('purpose-checks','主要验证项（JSON 列表；label 为中文问题，type / target 对应检查）',pretty(p?.checks||[]),'textarea');const advanced=e('details','raw');advanced.append(e('summary','','主要验证项（高级配置）'),$('purpose-checks').parentElement);$('edit-fields').append(advanced);$('edit-fields').append(e('p','form-hint','用途用于组织问题和提示缺口，不改写 GT 答案或已有审批。没有自动检查接口的事项只记录 label 和 note。'));}
function factCategory(a){const k=a.factKey||'';return /external|links\./.test(k)?'外链':/image/.test(k)?'图片':/table/.test(k)?'表格':/formula|math/.test(k)?'公式':/^security\./.test(k)?'安全特征':'结构与基础';}
function renderDetail(){
 const root=$('detail');root.replaceChildren();const s=current();if(!s){root.append(e('p','empty','尚无样本，请添加。'));return;}
 const head=e('div','detail-head');head.append(e('small','',s.id),e('h2','',s.title));const tags=e('div','tags');tags.append(badge(s.format.toUpperCase()),badge(s.active?'启用中':'已停用',s.active?'approved':'deferred'),badge(s.private?'私有文件':'公开 / 生成',s.private?'private':'public'),badge('文件版本 '+s.version));head.append(tags);root.append(head);
 const actions=e('div','actions');const file=e('a','','取得源文件 ↗');file.href='/api/file?project='+encodeURIComponent(project.id)+'&sample='+encodeURIComponent(s.id);actions.append(file,button('重新定位',()=>editFile('relink')),button('替换内容',()=>editFile('replace')),button(s.active?'停用样本':'重新启用',()=>editStatus()),button('版本历史',()=>showHistory(s.id)));root.append(actions);
 const loc=e('div','locations');loc.append(e('p','','登记位置：'+s.location),e('p','','内容缓存：'+s.path),e('p','','SHA-256：'+s.sha256),e('p','','逻辑文件名：'+s.inputName+' · '+s.bytes.toLocaleString()+' bytes'));root.append(loc);
 if(!s.active)root.append(e('p','warning','此样本已停用。相关 GT 与历史仍保留，下一轮验收不扫描此样本。'));
 if(s.health!=='ok')root.append(e('p','warning','缓存文件缺失或已变化。请重新定位，不能在此状态下批准答案。'));
 if(s.factFindings?.length){root.append(e('p','warning','新取证与 '+s.factFindings.length+' 项已有 GT 存在差异，请人工核定；原答案未被覆盖。'),raw('查看取证差异',s.factFindings));}
 renderPurpose(s,root);
 const tabs=e('div','actions');for(const [v,t] of [['scenarios','验收场景'],['technical','底层断言'],['mappings','产品字段映射'],['reference','参考取证（'+s.answers.filter(a=>!inCase(a)).length+'）']])tabs.append(button(t,()=>{detailView=v;renderDetail();},detailView===v?'primary':''));root.append(tabs);
 if(detailView==='scenarios'){renderScenarios(s,root);return;}
 if(detailView==='mappings'){renderMappings(s,root);return;}
 if(detailView==='reference')root.append(e('p','reference-hint','这些结果不属于当前 case 的验收范围，不计入待审 GT、不执行比对。按需要纳入即可，无需逐条审核。'));
 if(detailView==='technical'){const filter=e('select');filter.setAttribute('aria-label','事实分类');for(const v of ['all','图片','表格','公式','外链','安全特征','结构与基础'])filter.append(new Option(v==='all'?'全部事实类别':v,v));filter.value=factFilter;filter.onchange=()=>{factFilter=filter.value;renderDetail();};root.append(filter);}
 if(detailView==='reference')root.append(e('h3','','参考取证 · 按需取用'));
 const ah=e('div','answer-heading');ah.append(e('h3','',detailView==='technical'?'底层断言 · 场景中的可执行比较项':'版本契约预期'),button('＋ 新增事实',()=>{const v=detailView;detailView='facts';editAnswer();detailView=v;}),button('＋ 新增契约预期',()=>{const v=detailView;detailView='contracts';editAnswer();detailView=v;}));if(detailView!=='reference')root.append(ah);
 if(!caseAnswers(s).length&&detailView!=='reference')root.append(e('div','empty','本 case 尚无匹配用途的 GT。请依据上方用例目的补充；通用取证不代替覆盖。'));
 let section='';const ordered=s.answers.filter(a=>detailView==='reference'?!inCase(a):inCase(a)&&(detailView==='technical'?(factFilter==='all'||a.kind!=='fact'||factCategory(a)===factFilter):a.kind!=='fact')).sort((a,b)=>Number(isPrimary(s,b))-Number(isPrimary(s,a))||factCategory(a).localeCompare(factCategory(b),'zh'));
 if(!ordered.length&&caseAnswers(s).length)root.append(e('p','empty',detailView==='technical'?'此分类下没有底层断言。':'此分类下没有条目。'));
 for(const a of ordered){const group=detailView==='reference'?(a.kind==='fact'?factCategory(a):'参考契约'):purposeCurrent(s)?(isPrimary(s,a)?'主要验证项':detailView==='technical'?(a.kind==='fact'?factCategory(a):'契约预期'):'其他契约预期'):'已有问题';if(section!==group){root.append(e('h3','gt-group',group));section=group;}const card=e('details','answer');card.open=detailView!=='reference'&&(purposeCurrent(s)?isPrimary(s,a):caseAnswers(s).length<=2||a.status==='stale');const summary=e('summary');summary.append(e('strong','',human(a)),badge(inCase(a)?labels[a.status]:'参考 · 无需审核',inCase(a)?a.status:'reference'));if(a.kind==='fact')summary.append(badge(valueLabels[a.valueState]||'已有答案',a.valueState==='known'?'known':'pending'));card.append(summary);
 const grid=e('div','answer-grid'),left=e('section'),right=e('section');left.append(e('small','',a.kind==='fact'?'文件事实 / 标准答案':'契约预期'),e('pre','value',expected(a)),e('small','','技术 ID'),e('code','',a.id));right.append(e('small','','独立依据'));
 if(a.display?.basis){const ul=e('ul');a.display.basis.forEach(t=>ul.append(e('li','',t)));right.append(ul);if(a.display.limitation)right.append(e('p','warning',a.display.limitation));}
 else {right.append(e('p','',a.evidence.method||'尚未填写取证方法'),e('p','',a.evidence.location||''),e('p','',a.evidence.notes||''));}
 if(a.kind==='fact'){left.append(e('small','','统计口径'),e('p','',a.definition||'批准前请补充统计口径'),badge(mappingLabel(a),'mapping-'+mapping(a).status));}grid.append(left,right);card.append(grid);
 if(a.status==='stale')card.append(e('p','warning','文件内容或逻辑文件名已变化。请修改答案与依据，保存新版本后重新审核。'));
 if(a.review)card.append(e('p','review-stamp',`${labels[a.status]} · ${a.review.actor} · ${a.review.at}\n${a.review.note}`));
 if(a.lastResult)card.append(raw('导入时的历史诊断（不是当前版本的判定）',a.lastResult));
 card.append(raw('查看完整答案、绑定条件与版本',{...a}));
 const controls=e('div','review-controls');controls.append(button('修改答案 / 依据',()=>editAnswer(a)),...(inCase(a)?[button('审核这版 GT',()=>editReview(a),'primary')]:[]),button(inCase(a)?'移为参考取证':'纳入本 case GT',()=>editScope(a)),button('答案历史',()=>showHistory(a.id)));card.append(controls);root.append(card);}
}
function field(id,label,value='',type='text',required=false){const l=e('label'),caption=e('span','',label),x=e(type==='textarea'?'textarea':'input');if(required)caption.append(e('span','required-mark',' *'));l.append(caption);x.id=id;if(type!=='textarea')x.type=type;x.value=value;x.required=required;l.append(x);$('edit-fields').append(l);return x;}
function select(id,label,values,value){const l=e('label','',label),s=e('select');s.id=id;values.forEach(([v,t])=>s.append(new Option(t,v)));s.value=value;l.append(s);$('edit-fields').append(l);return s;}
function begin(title,action){formAction=action;$('edit-title').textContent=title;$('edit-fields').replaceChildren();$('edit-note').value='';$('form-error').textContent='';$('editor').showModal();}
function fileFields(){$('edit-fields').append(e('p','form-hint','文件路径与选择文件至少填写一项。'));field('file-path','文件所在的绝对路径（或在下方选择文件）');field('file-upload','选择本机文件','','file');}
function editFile(action){begin(action==='relink'?'重新定位同一文件':'替换文件内容，建立新版本',action);fileFields();if(action==='replace')select('privacy','新文件属性',[['private','私有（默认）'],['public','公开或可分发的生成样本']],'private');$('edit-fields').append(e('p','warning',action==='relink'?'必须与当前 SHA-256 和后缀相同。逻辑文件名保持不变，审批可以沿用。':'内容、后缀或逻辑文件名改变后，已有 GT 将标为需要重新核验。旧版本保留。'));}
function editStatus(){begin(current().active?'停用样本':'重新启用样本','sample_status');$('edit-fields').append(e('p','',current().active?'停用后不删除文件、答案或历史。下一轮不执行相关样本。':'恢复纳入维护与执行范围。'));}
function editAnswer(a){formAnswer=a;const fact=a?a.kind==='fact':detailView==='facts';begin(a?'修改 · 保存为新草案':fact?'新增文档事实':'新增版本契约预期','save_answer');field('question',fact?'事实问题':'契约问题',a?human(a):'','text',true);
 if(fact){field('definition','统计口径（批准前需填写）',a?.definition||'','textarea');select('value-state','答案状态',[['known','已有答案'],['unknown','待核定'],['unreadable','暂无法取证'],['not_applicable','不适用']],a?.valueState||'known');field('fact-key','事实标识（自动生成，一般无需修改）',a?.factKey||'custom.'+Date.now());}
 const value=a?.expected;select('expected-type','答案类型',[['string','文字'],['number','数字'],['boolean','是 / 否'],['json','列表 / 对象 / null']],typeof value==='number'?'number':typeof value==='boolean'?'boolean':value===null||typeof value==='object'?'json':'string');
 field('expected','答案（是 / 否请填 true / false）',a?(typeof value==='string'?value:pretty(value)):'','textarea',true);
 if(fact){const refreshValue=()=>{$('expected').required=$('value-state').value==='known';$('expected').disabled=$('value-state').value!=='known';$('expected').parentElement.querySelector('.required-mark').hidden=$('value-state').value!=='known';};$('value-state').onchange=refreshValue;refreshValue();}
 field('method','取证工具 / 方法（批准前需补齐）',a?.evidence.method||'');field('location','依据位置',a?.evidence.location||'');field('evidence-notes','依据说明',a?.evidence.notes||'','textarea');
 if(!fact){field('check','检查定义（JSON）',a?.check?pretty(a.check):'','textarea');field('options','请求参数（JSON 字符串列表）',a?.options?pretty(a.options):'','textarea');field('requirement','所属要求 / 分组',a?.requirement||'');}
 $('edit-fields').append(e('p','warning',fact?'事实与产品支持情况分开。未知答案不能当作 0；没有产品映射也可以审核已取证事实。':'契约预期依赖产品版本，不能作为通用文档事实。'));}
function renderMappings(s,root){root.append(e('p','form-hint','这里只列本 case 纳入验收的事实。映射连接事实与产品字段。修改映射不改变事实答案或审批；运行前会冻结映射版本。'));
 for(const a of caseAnswers(s).filter(a=>a.kind==='fact')){const box=e('div','mapping-row'),m=mapping(a);box.append(e('strong','',human(a)),badge(mappingLabel(a),'mapping-'+mapping(a).status),e('p','',m.check?.target||'尚无可比较字段'),e('p','form-hint',m.note||''),e('small','',m.ruleVersion?('映射规则：'+m.ruleVersion+' · 产品版本：'+m.productVersion):''),button('维护映射',()=>editMapping(a)));root.append(box);}}
function editMapping(a){formAnswer=a;const m=mapping(a);begin('产品字段映射 · '+human(a),'save_mapping');$('edit-fields').append(e('p','',a.definition||''));select('mapping-status','映射状态',[['mapped','配置对应字段'],['unmapped','暂不映射'],['unsupported','产品暂未支持']],m.status);field('mapping-target','产品 target',m.check?.target||'','text',true);field('mapping-options','请求参数（JSON）',pretty(m.options||[]),'textarea');field('mapping-requirement','验收要求',m.requirement||'');field('mapping-note','映射说明',m.note||'','textarea');field('mapping-confirm','我已确认产品字段与上述事实统计口径一致','','checkbox',true);const refreshRequired=()=>{for(const id of ['mapping-target','mapping-confirm']){const x=$(id);x.required=$('mapping-status').value==='mapped';x.parentElement.querySelector('.required-mark').hidden=!x.required;}};$('mapping-status').onchange=refreshRequired;refreshRequired();}
function editReview(a){formAnswer=a;begin('审核当前版本 · '+human(a),'review_answer');$('edit-fields').append(e('pre','value',expected(a)));select('decision','审核决定',[['approved','批准当前答案与依据'],['rejected','拒绝，需要修改'],['deferred','暂缓，需要更多证据']],a.status==='stale'||['unknown','unreadable'].includes(a.valueState)?'deferred':'approved');field('confirm','我已核对当前样本、答案和依据','','checkbox',true);}
async function fileData(){const f=$('file-upload')?.files[0],path=$('file-path')?.value.trim();if(path)return {path};if(!f)throw Error('请选择文件或填写绝对路径');if(f.size>128*1024*1024)throw Error('单文件上限为 128 MB');const data=await new Promise((ok,no)=>{const r=new FileReader();r.onload=()=>ok(r.result.split(',')[1]);r.onerror=no;r.readAsDataURL(f);});return {data,filename:f.name};}
$('edit-form').onsubmit=async ev=>{ev.preventDefault();$('save').disabled=true;$('form-error').textContent='';try{
 const request={action:formAction,note:$('edit-note').value,sampleId:selected};
 if(['add_sample','relink','replace'].includes(formAction))Object.assign(request,await fileData());
 if(formAction==='add_sample'){request.title=$('sample-title').value;request.private=$('privacy').value==='private';}
 if(formAction==='replace')request.private=$('privacy').value==='private';
  if(formAction==='review_scenario')Object.assign(request,{answers:formAnswers.map(a=>({id:a.id,digest:a.digest})),status:$('decision').value,confirm:$('confirm').checked});
  if(formAction==='review_all_scenarios')Object.assign(request,{status:$('decision').value,confirm:$('confirm').checked});
  if(formAction==='set_answer_scope')Object.assign(request,{answerId:formAnswer.id,mode:inCase(formAnswer)?'reference':'case'});
 if(formAction==='sample_status')request.active=!current().active;
 if(formAction==='save_purpose')request.purpose={summary:$('purpose-summary').value,checks:JSON.parse($('purpose-checks').value.trim()||'[]')};
 if(formAction==='save_mapping')request.mapping={status:$('mapping-status').value,check:{type:'target',target:$('mapping-target').value},options:JSON.parse($('mapping-options').value||'[]'),requirement:$('mapping-requirement').value,note:$('mapping-note').value};
 if(formAction==='save_mapping'){request.answerId=formAnswer.id;request.confirm=$('mapping-confirm').checked;}
 if(formAction==='save_answer'){
  let v=$('expected').value;const unknown=$('value-state')&&$('value-state').value!=='known';const t=$('expected-type').value;if(unknown){v=null;}else if(t==='number'){if(!v.trim()||!Number.isFinite(Number(v)))throw Error('请填写有效数字');v=Number(v);}else if(t==='boolean'){if(!['true','false'].includes(v.trim()))throw Error('是 / 否请填写 true 或 false');v=v.trim()==='true';}else if(t==='json')v=JSON.parse(v);
  request.answerId=formAnswer?.id;request.answer={question:$('question').value,expected:v,evidence:{...(formAnswer?.evidence||{}),method:$('method').value,location:$('location').value,notes:$('evidence-notes').value}};if($('value-state'))Object.assign(request.answer,{kind:'fact',factKey:$('fact-key').value,definition:$('definition').value,valueState:$('value-state').value});else Object.assign(request.answer,{check:JSON.parse($('check').value.trim()||'{}'),options:JSON.parse($('options').value.trim()||'[]'),requirement:$('requirement').value});
 }
 if(formAction==='review_answer')Object.assign(request,{answerId:formAnswer.id,answerDigest:formAnswer.digest,status:$('decision').value,confirm:$('confirm').checked});
 await mutate(request);$('editor').close();
 }catch(err){$('form-error').textContent=err.message;}finally{$('save').disabled=false;}};
async function showHistory(entity){try{const rows=await api('/api/history?id='+encodeURIComponent(project.id));const owner=project.samples.find(s=>s.id===entity||s.answers.some(a=>a.id===entity));const related=new Set([entity,owner?.id,...(owner?.id===entity?owner.answers.map(a=>a.id):[])]);const actions={import:'初始导入',save_answer:'保存答案草案',review_answer:'审核答案',review_scenario:'审核验收场景',review_all_scenarios:'一键审核全部场景',replace:'替换文件版本',relink:'更新文件位置',sample_status:'调整启用状态',add_sample:'添加样本',save_purpose:'维护样本用途',set_answer_scope:'调整 GT 范围',set_case_scopes:'按用途整理 GT 范围',save_mapping:'维护产品映射',migrate_facts:'拆分事实与映射',import_fact_drafts:'导入独立事实草案'};$('history-content').replaceChildren();for(const h of rows.filter(h=>related.has(h.entity)||['import','import_fact_drafts','migrate_facts','set_case_scopes','review_all_scenarios'].includes(h.action))){const d=e('details','history-row');d.append(e('summary','',`版本 ${h.revision} · ${actions[h.action]||h.action} · ${h.actor} · ${h.at}`),e('p','',h.note));d.addEventListener('toggle',async()=>{if(d.open&&!d.dataset.loaded){try{const p=await api('/api/history?id='+encodeURIComponent(project.id)+'&revision='+h.revision);const s=p.samples.find(s=>s.id===entity||s.answers.some(a=>a.id===entity));d.append(e('pre','',pretty(s?.id===entity?s:s?.answers.find(a=>a.id===entity))));d.dataset.loaded='1';}catch(err){note(err.message,true);}}});$('history-content').append(d);}$('history').showModal();}catch(err){note(err.message,true);}}
$('add').onclick=()=>{begin('添加样本到维护范围','add_sample');field('sample-title','显示名称');fileFields();select('privacy','文件属性',[['private','私有（默认）'],['public','公开或可分发的生成样本']],'private');};
$('close').onclick=()=>$('editor').close();$('history-close').onclick=()=>$('history').close();
$('approve-all').onclick=()=>{
  actor();
  formAnswer=null;formAnswers=[];
  begin('一键审核全部场景 · 共 '+scenarios().length+' 个场景','review_all_scenarios');
  const total=project.samples.flatMap(caseAnswers).length;
  $('edit-fields').append(
    e('p','',`将批量批准当前全部启用样本的必要场景与底层断言（共 ${scenarios().length} 个场景、${total} 项必要断言）。`),
    e('p','form-hint','建议先在左侧通览核对各场景的标准答案与独立取证依据。若存在待核定、缺失或口径未定义的断言，批量审核将原子拦截。')
  );
  select('decision','审核决定',[['approved','批准全部场景与断言'],['rejected','批量拒绝'],['deferred','批量暂缓']],'approved');
  field('confirm','我已通篇核对全部场景、断言与依据','','checkbox',true);
};
$('refresh').onclick=()=>load().catch(err=>note(err.message,true));$('project').onchange=()=>{selected=null;load().catch(err=>note(err.message,true));};
for(const id of ['search','format','state'])$(id).addEventListener(id==='search'?'input':'change',renderList);
$('apply').onclick=async()=>{try{const r=await api('/api/apply',{project:project.id,revision:project.revision});note(r.message||'已同步到验收输入；历史报告未改动。');}catch(err){note(err.message,true);}};
(async()=>{try{const init=await api('/api/projects');token=init.token;canApply=init.canApply;$('actor').value=localStorage.getItem('casework-actor')||'';init.projects.forEach(p=>$('project').append(new Option(p.name,p.id)));if(init.defaultProject&&init.projects.some(p=>p.id===init.defaultProject))$('project').value=init.defaultProject;if(init.projects.length)await load();else{$('project-title').textContent='尚无项目';$('add').disabled=true;note('请先用 Casework CLI 导入项目数据。');}}catch(err){note(err.message,true);}})();
