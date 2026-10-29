#!/usr/bin/env python3
"""Build/publish independent NVIDIA driver updates for a kernel set.

The updates are appended to the kernel set release; its plugins, index and
the catalog pointer stay unchanged. Only nvidia-updates.json is replaced."""
import argparse
import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
KEYS=ROOT/'keys'
REPO=os.environ.get('PLUGIN_RELEASES','https://github.com/ra5on/TitanOS-Plugins/releases/download/')
TAG=re.compile(r'kernel-[0-9][0-9A-Za-z._~-]*-[1-9][0-9]*')
HASH=re.compile('[0-9a-f]{64}')

def digest(path):
    with path.open('rb') as f: return hashlib.file_digest(f,'sha256').hexdigest()

def verify(path,keys=KEYS):
    for key in sorted(keys.glob('*.pub')):
        if subprocess.run(['minisign','-V','-q','-p',str(key),'-m',str(path)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode==0:
            return
    raise ValueError('untrusted signature: '+path.name)

def fetch(base,name,limit=65536,optional=False):
    try:
        with urllib.request.urlopen(base+name,timeout=120) as response:
            if not response.url.startswith('https://'): raise ValueError('insecure redirect')
            data=response.read(limit+1)
    except urllib.error.HTTPError as e:
        if optional and e.code==404: return None
        raise
    if len(data)>limit: raise ValueError('metadata too large')
    return data

def signed(base,name,optional=False,limit=65536):
    data=fetch(base,name,limit,optional=optional)
    if data is None: return None
    sig=fetch(base,name+'.minisig',4096)
    with tempfile.TemporaryDirectory() as tmp:
        path=Path(tmp)/name;path.write_bytes(data);path.with_name(name+'.minisig').write_bytes(sig);verify(path)
    return json.loads(data)

def channel(base,kernel,package):
    data=signed(base,'nvidia-updates.json',True)
    if data is None: return dict(titanos='',kernel=kernel,kernelPackage=package,versions=[])
    if data.get('titanos')!='' or data.get('kernel')!=kernel or data.get('kernelPackage')!=package or len(data.get('versions',[]))>32: raise ValueError('wrong driver channel')
    seen,revisions=set(),set()
    for item in data['versions']:
        if not HASH.fullmatch(item['sha256']) or item['sha256'] in seen or type(item['revision']) is not int or item['revision']<1 or item['revision'] in revisions:
            raise ValueError('invalid driver inventory')
        seen.add(item['sha256']);revisions.add(item['revision'])
    return data

def prepare(tag,lock,output,force=False):
    if not TAG.fullmatch(tag): raise ValueError('invalid kernel set')
    base=REPO+tag+'/'
    index=signed(base,'index.json',limit=262144)
    kernel,package=index.get('kernel',''),index.get('kernelPackage','')
    if index.get('tag')!=tag or not package or not re.fullmatch('[A-Za-z0-9][A-Za-z0-9.+_-]{0,100}',kernel): raise ValueError('wrong kernel set identity')
    package_set=hashlib.sha256(json.dumps(json.loads(lock.read_text()),sort_keys=True).encode()).hexdigest()
    previous=channel(base,kernel,package)
    needed=True
    if previous['versions']:
        latest=next(v for v in previous['versions'] if v['sha256']==previous['recommended'])
        p=signed(base,'nvidia-update-'+latest['sha256']+'.plugin.json')
        needed=p.get('packageSet')!=package_set
    result=dict(tag=tag,kernel=kernel,kernelPackage=package,packageSet=package_set,needed=needed or force)
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(result,indent=2)+'\n')
    return result

def pack(target,source,destination):
    metadata=json.loads(target.read_text());manifest=json.loads((source/'nvidia.plugin.json').read_text())
    if manifest.get('titanos') or manifest['kernel']!=metadata['kernel'] or manifest.get('revision',0)<1: raise ValueError('plugin targets another OS/kernel')
    raw=source/'nvidia.raw'
    if digest(raw)!=manifest['sha256'] or raw.stat().st_size!=manifest['size']: raise ValueError('plugin image integrity')
    destination.mkdir(parents=True,exist_ok=True)
    prefix='nvidia-update-'+manifest['sha256']
    shutil.copyfile(raw,destination/(prefix+'.raw'))
    manifest['packageSet']=metadata['packageSet']
    today=datetime.date.today()
    try: apache=today.replace(year=today.year+2)
    except ValueError: apache=today.replace(year=today.year+2,day=28)
    manifest['license']='FSL-1.1-ALv2 (TitanOS integration); third-party licenses in archives'
    manifest['apacheFrom']=apache.isoformat()
    manifest['archives']={}
    for name in ('licenses','kernel-sources'):
        path=source/('nvidia-'+name+'.tar.gz');asset=prefix+'-'+name+'.tar.gz'
        shutil.copyfile(path,destination/asset)
        manifest['archives'][asset]=dict(sha256=digest(path),size=path.stat().st_size)
    (destination/(prefix+'.plugin.json')).write_text(json.dumps(manifest,indent=2)+'\n')
    # The kernel set the update belongs to, for signing; never uploaded.
    shutil.copyfile(target,destination/'target.json')
    return manifest

def sign(path,key):
    password=os.environ.get('MINISIGN_PASSWORD')
    subprocess.run(['minisign','-S','-s',str(key),'-m',str(path)],input=None if password is None else password+'\n',text=True,check=True)
    verify(path)

def sign_channel(directory,key):
    manifests=list(directory.glob('nvidia-update-*.plugin.json'))
    if len(manifests)!=1: raise ValueError('expected exactly one new plugin')
    path=manifests[0];p=json.loads(path.read_text())
    target=json.loads((directory/'target.json').read_text())
    if not TAG.fullmatch(target['tag']) or p['kernel']!=target['kernel'] or p.get('titanos'): raise ValueError('invalid target')
    verify_package(directory,p)
    previous=channel(REPO+target['tag']+'/',target['kernel'],target['kernelPackage'])
    if any(v['revision']>=p['revision'] for v in previous['versions']): raise ValueError('revision must increase; start a new workflow run')
    sign(path,key)
    previous['versions'].append({k:p[k] for k in ('version','sha256','revision','size','driver','toolkit')})
    previous['versions']=sorted(previous['versions'],key=lambda v:v['revision'],reverse=True)[:32]
    def version_key(item):
        return (tuple(int(n) for n in item['driver'].split('.')),tuple(int(n) for n in item['toolkit'].split('.')),item['revision'])
    previous['recommended']=max(previous['versions'],key=version_key)['sha256']
    index=directory/'nvidia-updates.json';index.write_text(json.dumps(previous,indent=2)+'\n');sign(index,key)

def verify_package(directory,p):
    hash=p['sha256']
    if not HASH.fullmatch(hash): raise ValueError('invalid image hash')
    image=directory/('nvidia-update-'+hash+'.raw')
    if digest(image)!=hash or image.stat().st_size!=p['size']: raise ValueError('driver image mismatch')
    expected={'nvidia-update-'+hash+'-'+n+'.tar.gz' for n in ('licenses','kernel-sources')}
    if set(p.get('archives',{}))!=expected: raise ValueError('missing source/license archives')
    for name,info in p['archives'].items():
        if digest(directory/name)!=info['sha256'] or (directory/name).stat().st_size!=info['size']: raise ValueError('archive checksum mismatch')

def verify_directory(directory,keys=KEYS):
    """Return the individually authenticated driver update assets of a kernel set."""
    assets=set()
    index=directory/'nvidia-updates.json'
    if index.exists():
        verify(index,keys);assets.update({index.name,index.name+'.minisig'})
    for path in directory.glob('nvidia-update-*.plugin.json'):
        verify(path,keys);p=json.loads(path.read_text())
        if path.name!='nvidia-update-'+p['sha256']+'.plugin.json': raise ValueError('driver filename mismatch')
        verify_package(directory,p)
        assets.update({path.name,path.name+'.minisig','nvidia-update-'+p['sha256']+'.raw',*p['archives']})
    return assets

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('prepare');p.add_argument('tag');p.add_argument('lock',type=Path);p.add_argument('output',type=Path);p.add_argument('--force',action='store_true')
    p=sub.add_parser('pack');p.add_argument('target',type=Path);p.add_argument('source',type=Path);p.add_argument('output',type=Path)
    p=sub.add_parser('sign');p.add_argument('directory',type=Path);p.add_argument('key',type=Path)
    p=sub.add_parser('verify');p.add_argument('directory',type=Path)
    args=parser.parse_args()
    if args.command=='prepare': print(json.dumps(prepare(args.version,args.lock,args.output,args.force)))
    elif args.command=='pack': pack(args.target,args.source,args.output)
    elif args.command=='sign': sign_channel(args.directory,args.key)
    else: verify_directory(args.directory)
