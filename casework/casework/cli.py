import argparse
import json
from pathlib import Path
from .store import Store
from .server import serve
from .evidence import import_records


def main():
    p=argparse.ArgumentParser(description='Casework · 本地样本与 GT 管理（不执行被测产品）')
    p.add_argument('--data',type=Path,required=True)
    sub=p.add_subparsers(dest='command',required=True)
    s=sub.add_parser('serve');s.add_argument('--port',type=int,default=8767)
    i=sub.add_parser('import');i.add_argument('file',type=Path)
    e=sub.add_parser('export');e.add_argument('project');e.add_argument('output',type=Path)
    m=sub.add_parser('migrate-facts');m.add_argument('project')
    x=sub.add_parser('import-evidence');x.add_argument('project');x.add_argument('file',type=Path);x.add_argument('--actor',default='evidence import')
    args=p.parse_args()
    if args.command=='serve':serve(args.data,args.port)
    elif args.command=='import':
        result=Store(args.data).import_bundle(json.loads(args.file.read_text()))
        print(json.dumps({'project':result['id'],'samples':len(result['samples'])},ensure_ascii=False))
    elif args.command=='migrate-facts':
        store=Store(args.data);project=store.get(args.project)
        if project.get('factSchema')!=2:
            store.act(args.project,{'action':'migrate_facts','revision':project['revision'],
                'actor':'Casework migration','note':'拆分事实与映射，保留原 GT 摘要和审批。'})
        print('Fact schema v2 ready')
    elif args.command=='import-evidence':
        print(json.dumps(import_records(Store(args.data),args.project,args.file,args.actor),ensure_ascii=False))
    else:args.output.write_text(json.dumps(Store(args.data).export(args.project),ensure_ascii=False,indent=2))


if __name__=='__main__':main()
