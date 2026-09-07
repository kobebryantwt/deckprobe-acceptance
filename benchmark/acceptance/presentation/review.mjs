'use strict';
const data=JSON.parse(document.getElementById('review-data').textContent);
if(data.managerUrl){document.getElementById('manager-entry').hidden=false;document.getElementById('manager-link').href=data.managerUrl;}
const $=id=>document.getElementById(id);
const names={pending:'待审核',approved:'已批准',rejected:'已拒绝'};
let family='全部';
function el(tag,cls,text){const n=document.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=text;return n;}
function badge(text,cls=''){return el('span','badge '+cls,text);}
function link(text,href){const n=el('a','',text);n.href=href;return n;}
function card(row){
 const d=el('details','answer');d.id=row.id;
 const s=el('summary'),copy=el('div','question');copy.append(el('strong','',row.question),el('span','sample',row.sample));
 s.append(copy,el('div','expected-short',row.expectedText),badge(names[row.review],row.review));d.append(s);
 const grid=el('div','answer-grid'),left=el('section'),right=el('section');
 left.append(el('small','',row.review==='approved'?'预期答案 · 已批准':'预期答案 · 待你核对'),el('p','expected',row.expectedText));
 left.append(el('p','',`${row.formatName}（.${row.format}） · ${data.scenarios[row.scenario][0]}`));
 if(row.href)left.append(link('打开这份测试文件 ↗',row.href));else left.append(el('p','warning','样本与答案哈希未绑定，源文件链接不可用。'));
 left.append(el('div','id-label','反馈时可引用此 ID'),el('code','answer-id',row.id));
 right.append(el('small','','独立依据 · 怎样得到这个答案'));
 const ul=el('ul');row.basis.forEach(t=>ul.append(el('li','',t)));right.append(ul);
 right.append(el('div','tool','取证工具 / 方法：'+row.tool));
 if(row.limitation)right.append(el('p','warning',row.limitation));
 grid.append(left,right);d.append(grid);
 const raw=el('details','raw');raw.append(el('summary','','技术记录：原始依据、请求参数、样本与答案哈希'));
 raw.addEventListener('toggle',()=>{if(raw.open&&!raw.dataset.loaded){raw.append(el('pre','',JSON.stringify(row.raw,null,2)));raw.dataset.loaded='true';}});
 d.append(raw);return d;
}
function render(){
 const q=$('search').value.toLowerCase().trim(),review=$('review').value,grouping=$('grouping').value;
 const rows=data.rows.filter(r=>(family==='全部'||r.family===family)&&(review==='all'||r.review===review)&&(!q||JSON.stringify(r).toLowerCase().includes(q)));
 $('count').textContent=`显示 ${rows.length} / ${data.rows.length} 条答案 · ${new Set(rows.map(r=>r.raw.caseId)).size} 份样本`;
 $('empty').hidden=!!rows.length;$('groups').replaceChildren();
 const buckets=new Map();for(const r of rows){const k=r[grouping];if(!buckets.has(k))buckets.set(k,[]);buckets.get(k).push(r);}
 let i=0;for(const [key,items] of buckets){
  const group=el('details','group');group.open=i++===0;const s=el('summary');
  const title=grouping==='format'?`${items[0].formatName} · .${key}`:data.scenarios[key][0];
  s.append(el('strong','',title),badge(`${items.length} 条答案`),el('span','group-status',`${items.filter(r=>r.review==='pending').length} 条待审`));group.append(s);
  if(grouping==='scenario')group.append(el('p','group-description',data.scenarios[key][1]));
  // Keep related questions together while retaining every individual assertion.
  const sorted=[...items].sort((a,b)=>a.scenario.localeCompare(b.scenario)||a.raw.caseId.localeCompare(b.raw.caseId));
  let prior=null;for(const r of sorted){if(grouping==='format'&&r.scenario!==prior){group.append(el('h3','',data.scenarios[r.scenario][0]));prior=r.scenario;}group.append(card(r));}
  $('groups').append(group);
 }
 document.querySelectorAll('#families button').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.family===family)));
}
for(const f of ['全部',...new Set(data.rows.map(r=>r.family))]){const b=el('button','',f);b.dataset.family=f;b.append(badge(data.rows.filter(r=>f==='全部'||r.family===f).length));b.onclick=()=>{family=f;render();};$('families').append(b);}
for(const [key,title] of [['all','全部答案'],['pending','待审核'],['approved','已批准'],['rejected','已拒绝']]){const n=key==='all'?data.rows.length:data.rows.filter(r=>r.review===key).length;const box=el('div');box.append(el('strong','',n),el('span','',title));$('totals').append(box);}
const gapNames={'Legacy Excel 独立 sheet/数据事实':'旧版 Excel 的独立工作表与数据事实','有效签名 OOXML':'含有效数字签名的 OOXML 文档','加密与签名 PDF':'加密 PDF 与含数字签名的 PDF','真实旧 XML iWork':'由旧版 iWork 软件生成的真实 XML 文档','IWA 深层独立事实':'现代 iWork（IWA）的深层结构独立取证','全 target 语义与边界':'全部目标字段的含义、正常值与边界情况'};
data.gaps.forEach(t=>$('gaps').append(el('li','',gapNames[t]||t)));
$('search').oninput=render;$('grouping').onchange=render;$('review').onchange=render;
$('reset').onclick=()=>{family='全部';$('search').value='';$('review').value='all';$('grouping').value='format';render();};
$('expand').onclick=()=>document.querySelectorAll('.group').forEach(g=>g.open=true);
$('collapse').onclick=()=>document.querySelectorAll('.group').forEach(g=>g.open=false);
render();
