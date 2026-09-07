import fs from 'node:fs';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
import {spawn} from 'node:child_process';
import http from 'node:http';

const [candidateRoot,previousRoot,input,candidateBinary,previousBinary,level,warmupText='5',samplesText='30']=process.argv.slice(2);
const warmup=Number(warmupText),samples=Number(samplesText),bytes=fs.readFileSync(input),name=path.basename(input);
const roots={candidate:candidateRoot,previous:previousRoot},binaries={candidate:candidateBinary,previous:previousBinary};
const packages=Object.fromEntries(Object.entries(roots).map(([k,v])=>[k,path.join(v,'node_modules/@deckflow/deckprobe')]));
const options={name,level,targets:['@all']},modes=[];

async function pair(mode,fns){
  for(const label of ['candidate','previous'])for(let i=0;i<warmup;i++)await fns[label]();
  const points={candidate:[],previous:[]},order=[];
  for(let i=0;i<samples;i++)for(const label of (i%2?['previous','candidate']:['candidate','previous'])){
    const start=performance.now();let result,error;try{result=await fns[label]();}catch(e){error=String(e);}
    points[label].push({durationMs:performance.now()-start,status:result?.status,error:error||null});order.push(label);
  }
  modes.push({mode,warmup,samples:points,order});
}
function jsonl(binary){
  const child=spawn(binary,['--jsonl','-l',level,'-t','@all'],{stdio:['pipe','pipe','pipe']});let buffer='',next;
  child.stderr.resume();child.stdout.on('data',b=>{buffer+=b;let end;while((end=buffer.indexOf('\n'))>=0){const line=buffer.slice(0,end);buffer=buffer.slice(end+1);if(next){const p=next;next=null;clearTimeout(p.timer);try{p.resolve(JSON.parse(line));}catch(e){p.reject(e);}}}});
  const call=()=>new Promise((resolve,reject)=>{const timer=setTimeout(()=>{next=null;reject(new Error('JSONL deadline'));},30000);next={resolve,reject,timer};child.stdin.write(JSON.stringify({path:input})+'\n');});
  return {call,close:()=>child.kill()};
}
const streams={candidate:jsonl(binaries.candidate),previous:jsonl(binaries.previous)};
let browser,server;
try{
  await pair('persistent-jsonl',{candidate:streams.candidate.call,previous:streams.previous.call});
  const apis={};for(const label of ['candidate','previous'])apis[label]=await import(pathToFileURL(path.join(packages[label],'dist/index.node.js')).href);
  const fresh=label=>()=>new Promise((resolve,reject)=>{const script=`import fs from 'node:fs';import {pathToFileURL} from 'node:url';const a=await import(pathToFileURL(${JSON.stringify(path.join(packages[label],'dist/index.node.js'))}).href);const r=await a.probe(fs.readFileSync(${JSON.stringify(input)}),${JSON.stringify(options)});if(r?.status==='error')process.exitCode=2;`;const p=spawn(process.execPath,['--input-type=module','-e',script],{stdio:['ignore','ignore','pipe']});let e='';p.stderr.on('data',b=>e+=b);p.on('error',reject);p.on('close',c=>c===0?resolve({status:'ok'}):reject(new Error(e||`exit ${c}`)));});
  await pair('node-fresh-process-wasm-initialization',{candidate:fresh('candidate'),previous:fresh('previous')});
  await pair('node-warm-wasm',{candidate:()=>apis.candidate.probe(bytes,options),previous:()=>apis.previous.probe(bytes,options)});
  const {chromium}=await import(pathToFileURL(path.join(candidateRoot,'node_modules/playwright/index.mjs')).href);
  server=http.createServer((req,res)=>{const url=new URL(req.url,'http://localhost');if(url.pathname==='/'){res.end('<!doctype html>');return;}if(url.pathname==='/input'){res.setHeader('Content-Type','application/octet-stream');fs.createReadStream(input).pipe(res);return;}const m=url.pathname.match(/^\/(candidate|previous)(\/.*)$/);if(!m){res.writeHead(404);res.end();return;}const file=path.resolve(packages[m[1]],'.'+m[2]);if(!file.startsWith(packages[m[1]]+path.sep)||!fs.existsSync(file)){res.writeHead(404);res.end();return;}res.setHeader('Content-Type',file.endsWith('.wasm')?'application/wasm':'text/javascript');fs.createReadStream(file).pipe(res);});
  await new Promise(r=>server.listen(0,'127.0.0.1',r));browser=await chromium.launch({headless:true});const origin=`http://127.0.0.1:${server.address().port}`;
  const makePage=async()=>{const page=await browser.newPage();await page.route('**/*',r=>r.request().url().startsWith(origin+'/')?r.continue():r.abort());await page.goto(origin);return page;};
  const browserFresh=label=>async()=>{const page=await makePage();try{return await page.evaluate(async ({label,options})=>{const a=await import(`/${label}/dist/index.js`);const data=new Uint8Array(await (await fetch('/input')).arrayBuffer());return a.probe(data,options);},{label,options});}finally{await page.close();}};
  await pair('browser-page-wasm-initialization',{candidate:browserFresh('candidate'),previous:browserFresh('previous')});
  const page=await makePage();
  await page.evaluate(async()=>{globalThis.__acceptanceInput=new Uint8Array(await (await fetch('/input')).arrayBuffer());});
  const call=(label,workerMode)=>page.evaluate(async ({label,options,workerMode})=>{const data=globalThis.__acceptanceInput;if(workerMode){const {createDeckProbeWorker}=await import(`/${label}/dist/worker.js`);const w=createDeckProbeWorker();try{return await w.probe(data,options);}finally{w.terminate();}}const a=await import(`/${label}/dist/index.js`);return a.probe(data,options);},{label,options,workerMode});
  await pair('browser-warm-main',{candidate:()=>call('candidate',false),previous:()=>call('previous',false)});
  await pair('worker-initialization',{candidate:()=>call('candidate',true),previous:()=>call('previous',true)});
  await page.evaluate(async()=>{globalThis.__acceptanceWorkers={};for(const label of ['candidate','previous']){const {createDeckProbeWorker}=await import(`/${label}/dist/worker.js`);globalThis.__acceptanceWorkers[label]=createDeckProbeWorker();}});
  const warmWorker=label=>page.evaluate(async ({label,options})=>globalThis.__acceptanceWorkers[label].probe(globalThis.__acceptanceInput,options),{label,options});
  await pair('worker-warm',{candidate:()=>warmWorker('candidate'),previous:()=>warmWorker('previous')});
  await page.evaluate(()=>Object.values(globalThis.__acceptanceWorkers).forEach(x=>x.terminate()));
  await page.close();
  process.stdout.write(JSON.stringify({name,level,modes,context:'paired on one runner; filesystem cache uncontrolled'})+'\n');
}catch(e){process.stderr.write(String(e.stack||e)+'\n');process.exitCode=1;}
finally{for(const x of Object.values(streams))x.close();await browser?.close();if(server)await new Promise(r=>server.close(r));}
