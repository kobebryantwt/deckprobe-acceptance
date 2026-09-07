#!/usr/bin/env python3
"""Operator-run macOS monitoring feasibility probe. Never scans private documents.

This probe deliberately reports blocked until every network route is demonstrably
blocked AND observed. PF UID matching alone cannot confine system DNS brokers.
It does not install a daemon, alter sudoers, disable SIP, or grant TCC permissions.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import pwd
import re
import signal
import subprocess
import sys
import tempfile
import time

ANCHOR='com.apple/deckprobe-acceptance'


def call(argv,**kw):
    p=subprocess.run(argv,capture_output=True,text=True,timeout=15,**kw)
    return {'command':argv,'exitCode':p.returncode,'stdout':p.stdout,'stderr':p.stderr}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--user',default='_deckprobe_accept')
    p.add_argument('--output')
    p.add_argument('--provision-user',action='store_true',help='Create the dedicated non-login test identity; requires operator-admin authorization')
    args=p.parse_args()
    if sys.platform!='darwin' or os.geteuid()!=0:raise SystemExit('Run on macOS with explicit operator-admin authorization')
    if args.provision_user:
        if args.user!='_deckprobe_accept':raise SystemExit('Provisioning is restricted to _deckprobe_accept')
        try:
            existing=pwd.getpwnam(args.user)
            print(json.dumps({'created':False,'uid':existing.pw_uid,'user':args.user}));return
        except KeyError:pass
        used={u.pw_uid for u in pwd.getpwall()}
        uid=next(i for i in range(501,60000) if i not in used)
        entry='/Users/'+args.user
        commands=[['/usr/bin/dscl','.','-create',entry]]
        for key,value in {'UniqueID':str(uid),'PrimaryGroupID':'20','UserShell':'/usr/bin/false',
                          'NFSHomeDirectory':'/var/empty','IsHidden':'1','Password':'*','RealName':'DeckProbe acceptance runner'}.items():
            commands.append(['/usr/bin/dscl','.','-create',entry,key,value])
        for command in commands:
            result=call(command)
            if result['exitCode']!=0:raise SystemExit('User provisioning stopped: '+result['stderr'])
        print(json.dumps({'created':True,'uid':uid,'user':args.user,'login':False}));return
    if not args.output:raise SystemExit('--output is required for a capability probe')
    user=pwd.getpwnam(args.user)
    if user.pw_uid==0:raise SystemExit('Test identity must not be root')
    output=Path(args.output).resolve()
    if output.exists():raise SystemExit('Use a new output directory; evidence is never overwritten')
    output.mkdir(parents=True,mode=0o700)
    record={'kind':'macos-capability-probe','status':'blocked','testUid':user.pw_uid,'steps':[],'rulesCleaned':False}
    active=call(['/sbin/pfctl','-a',ANCHOR,'-sr'])
    if active['stdout'].strip():raise SystemExit('Acceptance anchor already in use; refusing to replace it')
    logger=None;capture=None;token=None
    try:
        with tempfile.TemporaryDirectory(prefix='deckprobe-monitor-') as temp:
            temp=Path(temp);temp.chmod(0o755)
            rules=temp/'rules.conf'
            rules.write_text(f'block return out log quick proto {{ tcp udp }} user {user.pw_uid}\n')
            enabled=call(['/sbin/pfctl','-E']);record['steps'].append(enabled)
            match=re.search(r'Token\s*:\s*(\d+)',enabled['stderr']+' '+enabled['stdout'])
            if not match:raise RuntimeError('PF reference token unavailable; refusing to change rules')
            token=match.group(1)
            loaded=call(['/sbin/pfctl','-a',ANCHOR,'-f',str(rules)]);record['steps'].append(loaded)
            if loaded['exitCode']!=0:raise RuntimeError('PF anchor configuration failed')
            # Distinct sessions avoid eslogger suppressing the tested process group.
            with (output/'process-events.jsonl').open('w') as events, (output/'eslogger.stderr').open('w') as err:
                logger=subprocess.Popen(['/usr/bin/eslogger','exec','fork','exit','create'],stdout=events,stderr=err,start_new_session=True)
                with (output/'tcpdump.stderr').open('w') as neterr:
                    capture=subprocess.Popen(['/usr/sbin/tcpdump','-i','pktap,all','-U','-w',str(output/'network.pcap')],stdout=subprocess.DEVNULL,stderr=neterr,start_new_session=True)
                    time.sleep(1)
                    if logger.poll() is not None:raise RuntimeError('eslogger cannot collect; check responsible terminal Full Disk Access')
                    if capture.poll() is not None:raise RuntimeError('pktap collection unavailable')
                    code="""import socket,subprocess,json
out={}
for name,family,address in [('ipv4',socket.AF_INET,('192.0.2.1',9)),('ipv6',socket.AF_INET6,('2001:db8::1',9)),('loopback',socket.AF_INET,('127.0.0.1',9)),('proxy',socket.AF_INET,('127.0.0.1',7890))]:
 s=socket.socket(family,socket.SOCK_STREAM);s.settimeout(.5)
 try:s.connect(address);out[name]={'connected':True}
 except OSError as e:out[name]={'connected':False,'error':str(e),'errno':e.errno}
 finally:s.close()
try:socket.getaddrinfo('deckprobe-control.invalid',443);out['dns']={'resolved':True}
except OSError as e:out['dns']={'resolved':False,'error':str(e)}
subprocess.run(['/usr/bin/true'],check=True)
print(json.dumps(out))
"""
                    def lower():
                        os.setgroups([]);os.setgid(user.pw_gid);os.setuid(user.pw_uid)
                    # System Python may be absent; use the same interpreter path the operator invoked.
                    record['controls']=call([sys.executable,'-c',code],preexec_fn=lower,start_new_session=True)
                    record['ruleCounters']=call(['/sbin/pfctl','-a',ANCHOR,'-vvsr'])
                    record['limitations']=['Connection errors alone do not prove PF denial',
                        'DNS through system brokers requires separate attribution',
                        'No marker-file control or postflight control established by this feasibility probe',
                        'This output is not accepted as a live R02 session receipt']
    except Exception as e:
        record['error']=str(e)
    finally:
        for proc in [logger,capture]:
            if proc and proc.poll() is None:
                os.killpg(proc.pid,signal.SIGINT)
                try:proc.wait(timeout=5)
                except subprocess.TimeoutExpired:os.killpg(proc.pid,signal.SIGKILL);proc.wait()
        cleaned=call(['/sbin/pfctl','-a',ANCHOR,'-F','rules']) if token else None
        if token:record['disableReference']=call(['/sbin/pfctl','-X',token])
        record['rulesCleaned']=bool(cleaned and cleaned['exitCode']==0)
        (output/'probe.json').write_text(json.dumps(record,ensure_ascii=False,indent=2))
        # Only synthetic-control evidence belongs here; operator reviews broader captures locally.
    print(json.dumps({'status':record['status'],'output':str(output),'rulesCleaned':record['rulesCleaned']}))


if __name__=='__main__':main()
