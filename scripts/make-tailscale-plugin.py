#!/usr/bin/env python3
"""Stage the checksum-pinned upstream static binaries, with original notices."""
import hashlib,json,shutil,subprocess,sys,tarfile,urllib.request
from pathlib import Path
repo=Path(__file__).resolve().parents[1]
version=sys.argv[1]
lock=json.loads((repo/'plugins/tailscale/packages.lock.json').read_text())
work=repo/'out/tailscale-build'; work.mkdir(parents=True,exist_ok=True)
archive=work/'tailscale.tgz'
def digest(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
if not archive.exists() or digest(archive)!=lock['sha256']:
    part=archive.with_suffix('.part')
    with urllib.request.urlopen(lock['url'],timeout=120) as r,part.open('wb') as f:shutil.copyfileobj(r,f)
    if part.stat().st_size!=lock['size'] or digest(part)!=lock['sha256']:raise ValueError('Tailscale checksum mismatch')
    part.replace(archive)
root=work/'root';shutil.rmtree(root,ignore_errors=True);shutil.copytree(repo/'plugins/tailscale/root',root)
with tarfile.open(archive) as tar:
    for name,folder in [('tailscale','bin'),('tailscaled','sbin')]:
        member=tar.getmember('tailscale_'+lock['version']+'_amd64/'+name)
        if not member.isfile():raise ValueError('not an executable file')
        path=root/'usr'/folder/name;path.parent.mkdir(parents=True,exist_ok=True)
        with tar.extractfile(member) as f,path.open('wb') as out:shutil.copyfileobj(f,out)
        path.chmod(0o755)
notices=root/'usr/share/titanos/tailscale';shutil.copytree(repo/'plugins/tailscale/licenses',notices)
for notice in lock['notices']:
    if digest(notices/notice['file'])!=notice['sha256']:raise ValueError('original license notice changed')
shutil.copy2(repo/'LICENSE.md',notices/'TitanOS-LICENSE.md');shutil.copy2(repo/'plugins/tailscale/packages.lock.json',notices/'packages.lock.json')
(notices/'sources.txt').write_text('Tailscale '+lock['version']+' (BSD-3-Clause): '+lock['source']+'\nThird-party notices: https://tailscale.com/licenses/tailscale\nTitanOS integration: https://github.com/ra5on/TitanOS/tree/v'+version+'/plugins/tailscale\n')
(root/'plugin.json').write_text(json.dumps({'title':'Tailscale','description':{'de':'Fernzugriff mit Subnet-Routing und wählbarem Exit Node.','en':'Remote access with subnet routing and selectable exit node.'},'contains':{'de':['Tailscale '+lock['version'],'Subnet-Router','Exit Node'],'en':['Tailscale '+lock['version'],'Subnet router','Exit node']},'modules':[],'services':['titanos-tailscale.service'],'upstream':{'version':lock['version']}},indent=2)+'\n')
subprocess.run([str(repo/'scripts/make-plugin.sh'),'tailscale',version,str(root),str(repo/'out/plugins')],check=True)
with tarfile.open(repo/'out/plugins/tailscale-licenses.tar.gz','w:gz') as tar:tar.add(notices,arcname='tailscale')
