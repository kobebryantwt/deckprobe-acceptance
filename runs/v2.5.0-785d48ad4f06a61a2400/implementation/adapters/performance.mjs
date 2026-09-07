import fs from 'node:fs';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
import {spawn} from 'node:child_process';
import http from 'node:http';

const [root,input,binary,level,warmupText='5',samplesText='30']=process.argv.slice(2);
const warmup=Number(warmupText),samples=Number(samplesText);
const pkg=path.join(root,'node_modules/@deckflow/deckprobe');
const bytes=fs.readFileSync(input),name=path.basename(input),options={name,level,targets:['@all']};
const modes=[];

async function measure(name,fn){
  const points=[];
  for(let i=0;i<warmup+samples;i++){
    const start=performance.now();let result,error;
    try{result=await fn();}catch(e){error=String(e);}
    const point={durationMs:performance.now()-start,status:result?.status,error:error||null};
    if(i>=warmup)points.push(point);
  }
  modes.push({mode:name,warmup,samples:points});
}

const child=spawn(binary,['--jsonl','-l',level,'-t','@all'],{stdio:['pipe','pipe','pipe']});
let buffer='',next=null;
child.stderr.resume();
child.stdout.on('data',b=>{
  buffer+=b;let end;
  while((end=buffer.indexOf('\n'))>=0){const line=buffer.slice(0,end);buffer=buffer.slice(end+1);if(next){const p=next;next=null;clearTimeout(p.timer);try{p.resolve(JSON.parse(line));}catch(e){p.reject(e);}}}
});
child.on('error',e=>{if(next){clearTimeout(next.timer);next.reject(e);next=null;}});
function jsonl(){return new Promise((resolve,reject)=>{
  const timer=setTimeout(()=>{next=null;reject(new Error('JSONL deadline'));child.kill();},30000);
  next={resolve,reject,timer};child.stdin.write(JSON.stringify({path:input})+'\n');
});}

let browser,server;
try{
  await measure('persistent-jsonl',jsonl);
  child.stdin.end();
  const freshNodeScript=`
    import fs from 'node:fs';
    import {pathToFileURL} from 'node:url';
    const api=await import(pathToFileURL(${JSON.stringify(path.join(pkg,'dist/index.node.js'))}).href);
    const bytes=fs.readFileSync(${JSON.stringify(input)});
    const result=await api.probe(bytes,${JSON.stringify(options)});
    if(result?.status==='error')process.exitCode=2;
  `;
  await measure('node-fresh-process-wasm-initialization',()=>new Promise((resolve,reject)=>{
    const p=spawn(process.execPath,['--input-type=module','-e',freshNodeScript],{stdio:['ignore','ignore','pipe']});
    let error='';p.stderr.on('data',b=>error+=b);p.on('error',reject);p.on('close',code=>code===0?resolve({status:'ok'}):reject(new Error(error||`fresh Node exit ${code}`)));
  }));
  const api=await import(pathToFileURL(path.join(pkg,'dist/index.node.js')).href);
  await measure('node-warm-wasm',()=>api.probe(bytes,options));
  const {chromium}=await import(pathToFileURL(path.join(root,'node_modules/playwright/index.mjs')).href);
  server=http.createServer((req,res)=>{
    const url=new URL(req.url,'http://localhost');
    if(url.pathname==='/'){res.setHeader('Content-Type','text/html');res.end('<!doctype html><title>Performance observation</title>');return;}
    const file=path.resolve(pkg,'.'+decodeURIComponent(url.pathname));
    if(!file.startsWith(pkg+path.sep)||!fs.existsSync(file)){res.writeHead(404);res.end();return;}
    res.setHeader('Content-Type',file.endsWith('.wasm')?'application/wasm':'text/javascript');fs.createReadStream(file).pipe(res);
  });
  await new Promise(r=>server.listen(0,'127.0.0.1',r));
  browser=await chromium.launch({headless:true});
  const origin=`http://127.0.0.1:${server.address().port}`;
  await measure('browser-page-wasm-initialization',async()=>{
    const fresh=await browser.newPage();
    try{
      await fresh.route('**/*',r=>r.request().url().startsWith(origin+'/')?r.continue():r.abort());
      await fresh.goto(origin);
      return await fresh.evaluate(async ({data,options})=>{
        const api=await import('/dist/index.js');return api.probe(new Uint8Array(data),options);
      },{data:Array.from(bytes),options});
    }finally{await fresh.close();}
  });
  const page=await browser.newPage();
  await page.route('**/*',r=>r.request().url().startsWith(origin+'/')?r.continue():r.abort());
  await page.goto(origin);
  const browserModes=await page.evaluate(async ({data,options,warmup,samples})=>{
    const api=await import('/dist/index.js');const {createDeckProbeWorker}=await import('/dist/worker.js');
    const bytes=new Uint8Array(data),modes=[];
    async function sample(mode,fn){const points=[];for(let i=0;i<warmup+samples;i++){const start=performance.now();let result,error;try{result=await fn();}catch(e){error=String(e);}if(i>=warmup)points.push({durationMs:performance.now()-start,status:result?.status,error:error||null});}modes.push({mode,warmup,samples:points});}
    await sample('browser-warm-main',()=>api.probe(bytes,options));
    await sample('worker-initialization',async()=>{const worker=createDeckProbeWorker();try{return await worker.probe(bytes,options);}finally{worker.terminate();}});
    const worker=createDeckProbeWorker();
    try{await sample('worker-warm',()=>worker.probe(bytes,options));}finally{worker.terminate();}
    return modes;
  },{data:Array.from(bytes),options,warmup,samples});
  modes.push(...browserModes);
  process.stdout.write(JSON.stringify({level,name,modes,context:'background observation; filesystem cache uncontrolled'})+'\n');
}catch(e){process.stderr.write(String(e.stack||e)+'\n');process.exitCode=1;}
finally{child.kill();await browser?.close();if(server)await new Promise(r=>server.close(r));}
