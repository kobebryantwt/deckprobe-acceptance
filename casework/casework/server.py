from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs, quote
import json
import secrets

from .store import Store, Conflict, encoded, sha


def make_server(store, port=8767, on_apply=None, default_project=None):
    token=secrets.token_urlsafe(32)
    assets=Path(__file__).parent/'web'

    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args): pass  # Do not log document names or answer contents.

        def send(self, code, body, content_type='application/json; charset=utf-8', extra=None):
            if not isinstance(body,bytes):body=encoded(body).encode()
            self.send_response(code)
            self.send_header('Content-Type',content_type)
            self.send_header('Content-Length',str(len(body)))
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
            if extra:
                for k,v in extra.items():self.send_header(k,v)
            self.end_headers();self.wfile.write(body)

        def allowed(self, write=False):
            allowed={f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}'}
            if self.headers.get('Host') not in allowed:raise PermissionError('只接受本机地址')
            origin=self.headers.get('Origin')
            if origin and origin not in {'http://'+x for x in allowed}:raise PermissionError('拒绝跨站请求')
            if self.headers.get('Sec-Fetch-Site')=='cross-site':raise PermissionError('拒绝跨站请求')
            if write and self.headers.get('X-Casework-Token')!=token:raise PermissionError('操作令牌已失效，请刷新页面')

        def handle_error(self,e):
            self.send(409 if isinstance(e,Conflict) else 403 if isinstance(e,PermissionError) else 400,{'error':str(e)})

        def do_GET(self):
            try:
                self.allowed();url=urlparse(self.path);q=parse_qs(url.query)
                value=lambda key:q.get(key,[''])[0]
                if url.path in {'/','/app.js','/style.css'}:
                    name={'/':'index.html','/app.js':'app.js','/style.css':'style.css'}[url.path]
                    return self.send(200,(assets/name).read_bytes(),{'/':'text/html; charset=utf-8','/app.js':'text/javascript; charset=utf-8','/style.css':'text/css; charset=utf-8'}[url.path])
                if url.path=='/api/projects':return self.send(200,{'projects':store.projects(),'token':token,'canApply':on_apply is not None,'defaultProject':default_project})
                if url.path=='/api/project':
                    p=store.get(value('id'))
                    for s in p['samples']:
                        s['health']='ok' if Path(s['path']).is_file() and sha(s['path'])==s['sha256'] else 'missing_or_changed'
                    return self.send(200,p)
                if url.path=='/api/history':return self.send(200,store.history(value('id'),int(value('revision')) if value('revision') else None))
                if url.path=='/api/export':return self.send(200,store.export(value('id')),extra={'Content-Disposition':'attachment; filename="casework-export.json"'})
                if url.path=='/api/file':
                    p=store.get(value('project'));s=next((s for s in p['samples'] if s['id']==value('sample')),None)
                    if not s or not Path(s['path']).is_file() or sha(s['path'])!=s['sha256']:raise ValueError('样本缺失或哈希不一致')
                    return self.send(200,Path(s['path']).read_bytes(),'application/octet-stream',{'Content-Disposition':"attachment; filename*=UTF-8''"+quote(s['inputName'])})
                self.send(404,{'error':'没有这个入口'})
            except (ValueError,PermissionError,OSError) as e:self.handle_error(e)

        def do_POST(self):
            try:
                self.allowed(True)
                if self.headers.get('Content-Type','').split(';')[0]!='application/json':raise ValueError('只接受 JSON 请求')
                size=int(self.headers.get('Content-Length','0'))
                if size<=0 or size>180*1024*1024:raise ValueError('请求大小超出限制')
                r=json.loads(self.rfile.read(size));path=urlparse(self.path).path
                if path=='/api/action':return self.send(200,store.act(r['project'],r))
                if path=='/api/apply' and on_apply:
                    p=store.get(r['project'])
                    if p['revision']!=r.get('revision'):raise Conflict('项目已更新，请刷新后同步')
                    return self.send(200,on_apply(p))
                self.send(404,{'error':'没有这个操作'})
            except (ValueError,KeyError,TypeError,PermissionError,OSError,RuntimeError) as e:self.handle_error(e)

    return ThreadingHTTPServer(('127.0.0.1',port),Handler)


def serve(home,port=8767,on_apply=None,default_project=None):
    server=make_server(Store(home),port,on_apply,default_project)
    print(f'Casework: http://127.0.0.1:{server.server_port}',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()
