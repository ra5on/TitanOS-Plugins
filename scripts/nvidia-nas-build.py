#!/usr/bin/env python3
"""Runs ONLY in the downloaded, verified build root with /work on the data volume.

check authenticates NVIDIA metadata and downloads sources/binaries. build is
explicit, offline, and never loads a module or changes the live NAS /usr.
"""
import hashlib,importlib.util,json,os,re,shutil,subprocess,sys,tarfile
from pathlib import Path
recipe=Path('/usr/lib/titanos/nvidia-build');work=Path('/work')
work.mkdir(exist_ok=True);(work/'tmp').mkdir(exist_ok=True);os.environ['TMPDIR']='/work/tmp'
def module(name,file):
    spec=importlib.util.spec_from_file_location(name,recipe/'scripts'/file);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
updater=module('updater','update-nvidia-lock.py');fetcher=module('fetcher','fetch-nvidia.py')
target=json.loads((recipe/'target.json').read_text());kernel=target['kernel'];lockpath=work/'packages.lock.json'
# titand names the release it builds for: the SDK may stem from a plugin set
# made for an earlier release with the same kernel.
version=os.environ.get('TITANOS_VERSION') or target['version']
if not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+(?:-[a-z0-9.]+)?',version):raise ValueError('invalid TitanOS version')
base=json.loads((lockpath if lockpath.exists() else recipe/'plugins/nvidia/packages.lock.json').read_text())
def status(lock):
    (work/'source-status.json').write_text(json.dumps({'driver':lock['driver'],'toolkit':lock['toolkit'],'kernel':kernel,'version':version,'downloaded':True})+'\n')
if sys.argv[1]=='check':
    index=updater.authenticate(updater.download(updater.REPOSITORY+'InRelease',1<<20),updater.download(updater.REPOSITORY+'Packages.gz',8<<20),recipe/'plugins/nvidia/repository.pub')
    lock=updater.select(base,index)
    candidate=work/'candidate.json';candidate.write_text(json.dumps(lock,indent=2)+'\n')
    fetcher.fetch(candidate,work/'packages');candidate.replace(lockpath);status(lock)
    print('Downloaded authenticated NVIDIA',lock['driver'],flush=True);sys.exit(0)
if sys.argv[1]!='build':raise ValueError('unknown action')
if not lockpath.exists():raise ValueError('check/download required first')
lock=json.loads(lockpath.read_text());driver=lock['driver']
if not re.fullmatch(r'\d+(?:\.\d+){1,3}',driver):raise ValueError('invalid driver version')
# Recheck every package offline immediately before using it.
for p in lock['packages']:
    path=work/'packages'/p['file']
    if path.parent!=work/'packages':raise ValueError('unsafe package path')
    with path.open('rb') as f:sha=hashlib.file_digest(f,'sha256').hexdigest()
    if sha!=p['sha256']:raise ValueError('package integrity failure')
stage=work/'plugin';source=work/'sources';out=work/'result'
for folder in [stage,source,out]:shutil.rmtree(folder,ignore_errors=True);folder.mkdir()
for package in lock['packages']:
    destination=source if package['name']=='nvidia-kernel-open-dkms' else stage
    fetcher.extract(work/'packages'/package['file'],destination)
kernelsource=source/'usr/src'/('nvidia-'+driver)
with tarfile.open(out/'nvidia-kernel-sources.tar.gz','w:gz') as archive:archive.add(kernelsource,arcname='nvidia-'+driver)
subprocess.run(['make','-C',str(kernelsource),'-j2','modules','KERNEL_UNAME='+kernel,'SYSSRC=/lib/modules/'+kernel+'/source','SYSOUT=/lib/modules/'+kernel+'/build'],check=True)
modules=stage/'usr/lib/modules'/kernel/'updates/titanos-nvidia';modules.mkdir(parents=True)
for name in ['nvidia','nvidia-uvm','nvidia-modeset','nvidia-drm']:
    path=kernelsource/'kernel-open'/(name+'.ko')
    magic=subprocess.check_output(['modinfo','-F','vermagic',str(path)],text=True).split()[0]
    if magic!=kernel:raise ValueError('kernel module vermagic mismatch')
    shutil.copy2(path,modules)
if (stage/'lib').is_dir():shutil.copytree(stage/'lib',stage/'usr/lib',dirs_exist_ok=True);shutil.rmtree(stage/'lib')
for path in ['etc','var','usr/lib/systemd/system/nvidia-cdi-refresh.service.d']:
    shutil.rmtree(stage/path,ignore_errors=True)
for path in ['usr/lib/systemd/system/nvidia-cdi-refresh.service','usr/lib/systemd/system/nvidia-cdi-refresh.path','usr/lib/udev/rules.d/99-nvidia-cdi-refresh.rules']:(stage/path).unlink(missing_ok=True)
shutil.copytree(recipe/'plugins/nvidia/root',stage,dirs_exist_ok=True)
shutil.copytree(source/'usr/share/doc/nvidia-kernel-open-dkms',stage/'usr/share/doc/nvidia-kernel-open-dkms',dirs_exist_ok=True)
shutil.copytree('/usr/share/common-licenses',stage/'usr/share/common-licenses',dirs_exist_ok=True)
notices=stage/'usr/share/titanos/nvidia';notices.mkdir(parents=True,exist_ok=True)
shutil.copy2(lockpath,notices/'packages.lock.json');shutil.copy2(recipe/'LICENSE.md',notices/'TitanOS-LICENSE.md')
# Metadata generator reads the relative lock from a private work directory.
metadata=work/'metadata';(metadata/'plugins/nvidia').mkdir(parents=True,exist_ok=True);shutil.copy2(lockpath,metadata/'plugins/nvidia/packages.lock.json')
subprocess.run(['python3',str(recipe/'scripts/nvidia-plugin-metadata.py'),str(stage),kernel,version],cwd=metadata,check=True)
manifest=json.loads((stage/'plugin.json').read_text());manifest.update(titanos=version,localBuild=True);(stage/'plugin.json').write_text(json.dumps(manifest)+'\n')
subprocess.run([str(recipe/'scripts/make-plugin.sh'),'nvidia',driver+'-titanos-'+version+'-local',str(stage),str(out)],check=True)
with tarfile.open(out/'nvidia-licenses.tar.gz','w:gz') as archive:archive.add(stage/'usr/share',arcname='share')
status(lock);print('Local driver prepared; activation requires an explicit NAS reboot selection',flush=True)
