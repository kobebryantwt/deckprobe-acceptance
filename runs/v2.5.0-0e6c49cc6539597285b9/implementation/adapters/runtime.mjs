import fs from 'node:fs';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
import {spawn} from 'node:child_process';
import http from 'node:http';

const [scenario, packageRoot, input, binary] = process.argv.slice(2);
const pkg=path.join(packageRoot,'node_modules/@deckflow/deckprobe');
const name=path.basename(input);
const options={targets:['@summary','@security'],level:'metadata'};
const importFile=p=>import(pathToFileURL(p).href);

async function nodeParity(){
  const api=await importFile(path.join(pkg,'dist/index.node.js'));
  const bytes=fs.readFileSync(input);
  const reports=[];
  reports.push(await api.probeFile(input,options));
  for (const shape of [bytes,new Uint8Array(bytes),bytes.buffer.slice(bytes.byteOffset,bytes.byteOffset+bytes.byteLength)])
    reports.push(await api.probe(shape,{...options,name}));
  return {reports,schema:await api.schema(),version:await api.version()};
}

async function browserParity(){
  const {chromium}=await importFile(path.join(packageRoot,'node_modules/playwright/index.mjs'));
  const requests=[];
  const server=http.createServer((req,res)=>{
    const relative=decodeURIComponent(new URL(req.url,'http://localhost').pathname);
    if(relative==='/'){res.setHeader('Content-Type','text/html');res.end('<!doctype html><title>Acceptance Worker responsiveness</title>');return;}
    const file=path.resolve(pkg,'.'+relative);
    if(!file.startsWith(pkg+path.sep)||!fs.existsSync(file)){res.writeHead(404);res.end();return;}
    res.setHeader('Content-Type',file.endsWith('.wasm')?'application/wasm':'text/javascript');
    fs.createReadStream(file).pipe(res);
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const origin=`http://127.0.0.1:${server.address().port}`;
  let browser;
  try{
    browser=await chromium.launch({headless:true});
    const page=await browser.newPage();
    await page.route('**/*',route=>{
      const url=route.request().url(); requests.push(url);
      return url.startsWith(origin+'/')?route.continue():route.abort();
    });
    const errors=[];page.on('pageerror',e=>errors.push(String(e)));
    await page.goto(origin);
    const result=await page.evaluate(async ({data,name,options})=>{
      const main=await import('/dist/index.js');
      const {createDeckProbeWorker}=await import('/dist/worker.js');
      const bytes=new Uint8Array(data);
      const direct=await main.probe(new File([bytes],name),options);
      const worker=createDeckProbeWorker();
      const off=await worker.probe(new File([bytes],name),options);
      const trace={idle:[],blocked:[],worker:[],longTasks:[]};
      let section='idle',last=performance.now();
      const interval=setInterval(()=>{const t=performance.now();trace[section].push(t-last);last=t;},10);
      let observer;
      if(PerformanceObserver.supportedEntryTypes.includes('longtask')){
        observer=new PerformanceObserver(list=>trace.longTasks.push(...list.getEntries().map(e=>({start:e.startTime,duration:e.duration,section}))));
        observer.observe({type:'longtask',buffered:true});
      }
      await new Promise(r=>setTimeout(r,200));
      section='blocked';last=performance.now();const until=last+180;
      while(performance.now()<until){}
      await new Promise(r=>setTimeout(r,40));
      section='worker';last=performance.now();
      const start=performance.now();let probes=0;
      while(performance.now()-start<250){await worker.probe(new File([bytes],name),{...options,level:'deep'});probes++;}
      await new Promise(r=>setTimeout(r,20));
      clearInterval(interval);observer?.disconnect();
      worker.terminate();
      let terminated=false;try{await worker.probe(new File([bytes],name),options);}catch{terminated=true;}
      return {reports:[direct,off],trace,probes,terminated,schema:await main.schema(),version:await main.version()};
    },{data:Array.from(fs.readFileSync(input)),name,options});
    return {...result,errors,requests,networkScope:'page interception only; not OS-level R02 proof'};
  }finally{await browser?.close();await new Promise(resolve=>server.close(resolve));}
}

async function mcpParity(){
  const entry=path.join(packageRoot,'node_modules/@deckflow/deckprobe-mcp/dist/main.js');
  const env={...process.env,DECKPROBE_MCP_ROOTS:path.dirname(input),DECKPROBE_MCP_TIMEOUT_MS:'30000'};
  delete env.DECKPROBE_MCP_BIN;
  if(scenario==='mcp-pinned')env.DECKPROBE_MCP_BIN=binary;
  if(scenario==='mcp-timeout'){env.DECKPROBE_MCP_BIN=binary;env.DECKPROBE_MCP_TIMEOUT_MS='1';}
  const proc=spawn(process.execPath,[entry],{cwd:packageRoot,env,stdio:['pipe','pipe','pipe']});
  const pending=new Map();let buffer='',stderr='',next=1;
  proc.stderr.on('data',b=>stderr+=b);
  proc.stdout.on('data',chunk=>{
    buffer+=chunk;let index;
    while((index=buffer.indexOf('\n'))>=0){
      const line=buffer.slice(0,index);buffer=buffer.slice(index+1);if(!line.trim())continue;
      try{const message=JSON.parse(line);const p=pending.get(message.id);if(p){clearTimeout(p.timer);pending.delete(message.id);p.resolve(message);}}
      catch(e){for(const p of pending.values()){clearTimeout(p.timer);p.reject(new Error('Non-JSON on MCP stdout: '+line.slice(0,100)));}pending.clear();}
    }
  });
  const rejectAll=err=>{for(const p of pending.values()){clearTimeout(p.timer);p.reject(err);}pending.clear();};
  proc.on('error',rejectAll);proc.on('exit',()=>rejectAll(new Error('MCP exited before response')));
  function request(method,params={}){
    const id=next++;
    return new Promise((resolve,reject)=>{
      const timer=setTimeout(()=>{pending.delete(id);reject(new Error('MCP response timeout: '+method));},35000);
      pending.set(id,{resolve,reject,timer});
      proc.stdin.write(JSON.stringify({jsonrpc:'2.0',id,method,params})+'\n');
    });
  }
  const responses={};
  try{
    responses.initialize=await request('initialize',{protocolVersion:'2025-06-18',capabilities:{},clientInfo:{name:'deckprobe-acceptance',version:'1.0.0'}});
    proc.stdin.write(JSON.stringify({jsonrpc:'2.0',method:'notifications/initialized'})+'\n');
    if(scenario==='mcp-timeout'){
      responses.probe=await request('tools/call',{name:'probe',arguments:{path:input,targets:['@all'],level:'deep',view:'report'}});
      return {responses,stderr,mode:scenario};
    }
    responses.tools=await request('tools/list');
    responses.formats=await request('tools/call',{name:'list_formats',arguments:{}});
    responses.targets=await request('tools/call',{name:'list_targets',arguments:{format:path.extname(input).slice(1),detail:'full'}});
    responses.schema=await request('resources/read',{uri:'deckprobe://schema'});
    responses.probe=await request('tools/call',{name:'probe',arguments:{path:input,...options,view:'report'}});
    responses.batch=await request('tools/call',{name:'probe_batch',arguments:{paths:[input,path.join(path.dirname(input),'missing.pdf'),input],...options,view:'report'}});
    responses.outside=await request('tools/call',{name:'probe',arguments:{path:'/etc/hosts'}});
    responses.invalid=await request('tools/call',{name:'probe',arguments:{path:42}});
    return {responses,stderr,mode:scenario};
  }finally{
    proc.stdin.end();proc.kill('SIGTERM');
    await Promise.race([new Promise(r=>proc.once('exit',r)),new Promise(r=>setTimeout(()=>{proc.kill('SIGKILL');r();},1000))]);
  }
}

try{
  const result=scenario==='node'?await nodeParity():scenario==='browser'?await browserParity():await mcpParity();
  process.stdout.write(JSON.stringify(result)+'\n');
}catch(e){process.stderr.write(String(e.stack||e)+'\n');process.exitCode=1;}
