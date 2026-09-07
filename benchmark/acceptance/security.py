"""Fail-closed capability checks; a saved self-test is never a live run attestation."""
from __future__ import annotations
import os
from pathlib import Path
import platform
try:
    import pwd
except ImportError:  # Windows has no POSIX account database.
    pwd = None
import shutil
import importlib.metadata
from .common import CODE, atomic, now, process, read, sha

CONTROL_NAMES=['ipv4','ipv6','dns','loopback','proxy','child_exec','marker_file']


def validate_session(session, run_id, artifact_hash, corpus_hash):
    problems=[]
    if not session or session.get('runId')!=run_id: return ['No live monitor session bound to this run']
    for key,expected in [('artifactSha256',artifact_hash),('cohortHash',corpus_hash)]:
        if session.get(key)!=expected:problems.append(key+' binding mismatch')
    if session.get('phase')!='closed':problems.append('monitor session incomplete')
    for phase in ['preflight','postflight']:
        controls=session.get(phase,{})
        for name in CONTROL_NAMES:
            c=controls.get(name,{})
            if not c.get('observed') or (name not in {'child_exec','marker_file'} and not c.get('blocked')):
                problems.append(phase+': '+name+' unproven')
    if session.get('droppedEvents')!=0 or session.get('droppedPackets')!=0:problems.append('capture loss or unknown loss count')
    if not session.get('rulesCleaned'):problems.append('isolation cleanup not confirmed')
    if not session.get('independentCollectors'):problems.append('collectors not independent')
    return problems


def doctor(home):
    tools={n:shutil.which(n) for n in ['node','npm','gh','tcpdump','eslogger','pfctl']}
    sudo=process(['/usr/bin/sudo','-n','/usr/bin/true'],timeout=5) if platform.system()=='Darwin' else {'exitCode':None}
    try:
        user = pwd.getpwnam('_deckprobe_accept') if pwd is not None else None
        identity = {'uid': user.pw_uid, 'gid': user.pw_gid} if user is not None else None
    except KeyError:
        identity = None
    blockers=[]
    if platform.system()!='Darwin':blockers.append('This runner is configured for macOS; select a native platform adapter')
    if platform.machine()!='arm64':blockers.append('Locked native platform requires Apple Silicon')
    if sudo['exitCode']!=0:blockers.append('Native monitoring requires operator-admin authorization; noninteractive sudo unavailable')
    if identity is None:blockers.append('Dedicated low-privilege account _deckprobe_accept is not provisioned')
    blockers.append('Full Disk Access and live pre/post network/process controls must be demonstrated per monitored run')
    versions={}
    for name in ['pypdf','xlrd','jsonschema']:
        try:versions[name]=importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:versions[name]=None
    node=process(['node','--version'],timeout=10)
    checks={'python':platform.python_version(),'pythonDependencies':versions,'nodeVersion':node.get('stdout','').strip(),
            'system':platform.platform(),'machine':platform.machine(),
            'tools':tools,'testIdentity':identity,'noninteractiveAdmin':sudo['exitCode']==0,
            'privateScanAllowed':False,'securityStatus':'blocked','blockers':blockers,
            'monitorHelper':str(CODE/'monitor_macos.py'),'helperSha256':sha(CODE/'monitor_macos.py') if (CODE/'monitor_macos.py').exists() else None}
    atomic(Path(home)/'doctor.json',{'checkedAt':now(),**checks})
    return checks
