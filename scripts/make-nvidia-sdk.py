#!/usr/bin/env python3
"""Package the exact-kernel build environment; compilers stay off the NAS RAM image."""
import hashlib,json,shutil,subprocess,sys
from pathlib import Path
from urllib.parse import quote
root,kernel,version,out=Path(sys.argv[1]),sys.argv[2],sys.argv[3],Path(sys.argv[4])
repo=Path(__file__).resolve().parents[1]
# Fail before publishing an SDK if any recipe executable is unavailable in
# its root. A tool present on the CI host does not satisfy this requirement.
subprocess.run(['chroot',str(root),'/bin/sh','-ec',
    'for tool in python3 gpg gpgv dpkg-deb make gcc ld modinfo mksquashfs zstd tar; do command -v "$tool" >/dev/null; done'],check=True)
recipe=root/'usr/lib/titanos/nvidia-build'
for folder in ['scripts','plugins/nvidia']:(recipe/folder).mkdir(parents=True,exist_ok=True)
for name in ['update-nvidia-lock.py','fetch-nvidia.py','make-plugin.sh','nvidia-plugin-metadata.py','nvidia-nas-build.py']:
    shutil.copy2(repo/'scripts'/name,recipe/'scripts'/name)
for name in ['packages.lock.json','repository.pub']:shutil.copy2(repo/'plugins/nvidia'/name,recipe/'plugins/nvidia'/name)
shutil.copytree(repo/'plugins/nvidia/root',recipe/'plugins/nvidia/root',dirs_exist_ok=True)
shutil.copy2(repo/'LICENSE.md',recipe/'LICENSE.md')
(recipe/'target.json').write_text(json.dumps({'kernel':kernel,'version':version})+'\n')
notices=root/'usr/share/titanos/nvidia-build';notices.mkdir(parents=True,exist_ok=True)
sources=[]
for block in (root/'var/lib/dpkg/status').read_text().split('\n\n'):
    fields=dict(line.split(': ',1) for line in block.splitlines() if ': ' in line and not line[0].isspace())
    if fields.get('Status')!='install ok installed':continue
    name,pv=fields['Package'],fields['Version'];src=fields.get('Source',name);parts=src.split(' (');source=parts[0];sv=parts[1].rstrip(')') if len(parts)>1 else pv
    if not (root/'usr/share/doc'/name/'copyright').exists():raise ValueError('Missing SDK copyright: '+name)
    sources.append(name+' '+pv+'\nhttps://snapshot.debian.org/package/'+quote(source,safe='')+'/'+quote(sv,safe='')+'/\n')
(notices/'SOURCES.txt').write_text('\n'.join(sources));shutil.copy2(repo/'LICENSE.md',notices/'TitanOS-LICENSE.md')
resolver=root/'etc/resolv.conf'; resolver.unlink(missing_ok=True); resolver.touch()
asset=out/'nvidia-build-sdk.tar.zst'
subprocess.run(['tar','--zstd','-cf',str(asset),'-C',str(root),'.'],check=True)
with asset.open('rb') as f:sha=hashlib.file_digest(f,'sha256').hexdigest()
(out/'nvidia-build-sdk.json').write_text(json.dumps({'asset':asset.name,'kernel':kernel,'version':version,'sha256':sha,'size':asset.stat().st_size},indent=2)+'\n')
shutil.copy2(notices/'SOURCES.txt',out/'nvidia-build-sdk-sources.txt')
