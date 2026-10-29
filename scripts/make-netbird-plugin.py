#!/usr/bin/env python3
"""Stage the checksum-pinned upstream NetBird client, with original notices.

Only the client is shipped (BSD-3-Clause). NetBird's management, signal,
relay and combined servers are AGPL-3.0 and not part of this binary or plugin.
"""
import hashlib,json,os,shutil,subprocess,sys,tarfile,urllib.request
from pathlib import Path
repo=Path(__file__).resolve().parents[1]
revision=sys.argv[1]
if not revision.isdigit():raise SystemExit('usage: make-netbird-plugin.py <set revision>')
tag=os.environ.get('SET_TAG','main')
lock=json.loads((repo/'plugins/netbird/packages.lock.json').read_text())
work=repo/'out/netbird-build'; work.mkdir(parents=True,exist_ok=True)
archive=work/'netbird.tgz'
def digest(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
if not archive.exists() or digest(archive)!=lock['sha256']:
    part=archive.with_suffix('.part')
    with urllib.request.urlopen(lock['url'],timeout=120) as r,part.open('wb') as f:shutil.copyfileobj(r,f)
    if part.stat().st_size!=lock['size'] or digest(part)!=lock['sha256']:raise ValueError('NetBird checksum mismatch')
    part.replace(archive)
root=work/'root';shutil.rmtree(root,ignore_errors=True);shutil.copytree(repo/'plugins/netbird/root',root)
with tarfile.open(archive) as tar:
    member=tar.getmember('netbird')
    if not member.isfile():raise ValueError('not an executable file')
    path=root/'usr/bin/netbird';path.parent.mkdir(parents=True,exist_ok=True)
    with tar.extractfile(member) as f,path.open('wb') as out:shutil.copyfileobj(f,out)
    path.chmod(0o755)
    # The notices shipped upstream next to the binary must be the pinned ones.
    for name in ['LICENSE','LICENSES/BSD-3-Clause.txt']:
        with tar.extractfile(tar.getmember(name)) as f:
            if hashlib.sha256(f.read()).hexdigest()!=next(n['sha256'] for n in lock['notices'] if n['file']==Path(name).name):raise ValueError('upstream notice differs from the pinned one')
notices=root/'usr/share/titanos/netbird';shutil.copytree(repo/'plugins/netbird/licenses',notices)
for notice in lock['notices']:
    if digest(notices/notice['file'])!=notice['sha256']:raise ValueError('original license notice changed')
shutil.copy2(repo/'LICENSE.md',notices/'TitanOS-LICENSE.md');shutil.copy2(repo/'plugins/netbird/packages.lock.json',notices/'packages.lock.json')
(notices/'sources.txt').write_text('NetBird client '+lock['version']+' (BSD-3-Clause): '+lock['source']+'\nThe AGPL-3.0 server components (management, signal, relay, combined) are not included.\nGo module sources: see third-party.txt (one proxy.golang.org link per module)\nTitanOS integration: https://github.com/ra5on/TitanOS-Plugins/tree/'+tag+'/plugins/netbird\n')
(root/'plugin.json').write_text(json.dumps({'title':'NetBird','description':{'de':'Fernzugriff über ein NetBird-Netz, auch mit eigenem Management-Server.','en':'Remote access through a NetBird network, including self-hosted management.'},'contains':{'de':['NetBird-Client '+lock['version'],'Setup-Key-Anmeldung','Routen und DNS wählbar'],'en':['NetBird client '+lock['version'],'Setup key login','Selectable routes and DNS']},'modules':[],'services':['titanos-netbird.service'],'upstream':{'version':lock['version']}},indent=2,ensure_ascii=False)+'\n')
subprocess.run([str(repo/'scripts/make-plugin.sh'),'netbird',lock['version']+'-'+revision,str(root),str(repo/'out/plugins')],check=True)
with tarfile.open(repo/'out/plugins/netbird-licenses.tar.gz','w:gz') as tar:tar.add(notices,arcname='netbird')
