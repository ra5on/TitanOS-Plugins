#!/usr/bin/env python3
"""Select a coherent NVIDIA package set from authenticated Debian metadata.

Only CI/build machines use this: NAS devices download signed, compiled sysexts.
The pinned NVIDIA archive key authenticates InRelease, which authenticates the
compressed package index. No apt install or maintainer script is executed.
"""
import argparse
import datetime
import email.utils
import gzip
import hashlib
import json
import re
import subprocess
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = 'https://developer.download.nvidia.com/compute/cuda/repos/debian13/x86_64/'
FINGERPRINT = '02182E60104FCDC26EAE1B8597A5D4CB8793F200'
TOOLKIT = {'libnvidia-container-tools','libnvidia-container1','nvidia-container-toolkit','nvidia-container-toolkit-base'}

def download(url, limit):
    with urllib.request.urlopen(url, timeout=120) as response:
        if not response.url.startswith('https://'):
            raise ValueError('insecure NVIDIA redirect')
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError('NVIDIA metadata exceeds size limit')
    return data

def authenticate(inrelease, compressed, key):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        source, plain, ring = root/'InRelease', root/'Release', root/'trusted.gpg'
        source.write_bytes(inrelease)
        subprocess.run(['gpg','--batch','--yes','--homedir',tmp,'--dearmor','--output',str(ring),str(key)],check=True,stdout=subprocess.DEVNULL)
        result = subprocess.run(['gpgv','--homedir',tmp,'--keyring',str(ring),'--status-fd','1','--output',str(plain),str(source)],check=True,capture_output=True,text=True)
        if '[GNUPG:] VALIDSIG '+FINGERPRINT+' ' not in result.stdout:
            raise ValueError('unexpected NVIDIA signing key')
        release = plain.read_text()
    date = re.search(r'^Date: (.+)$',release,re.M)
    if not date:
        raise ValueError('NVIDIA release has no date')
    when = email.utils.parsedate_to_datetime(date[1])
    now = datetime.datetime.now(datetime.timezone.utc)
    if when > now + datetime.timedelta(days=1) or when < now-datetime.timedelta(days=45):
        raise ValueError('NVIDIA release metadata is stale or from the future')
    section = release.split('\nSHA256:\n',1)[-1].split('\n\n',1)[0]
    matches = re.findall(r'^ ([0-9a-f]{64})\s+(\d+)\s+Packages.gz$',section,re.M)
    if len(matches)!=1 or int(matches[0][1])!=len(compressed) or hashlib.sha256(compressed).hexdigest()!=matches[0][0]:
        raise ValueError('NVIDIA package index checksum mismatch')
    import io
    with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as stream:
        data=stream.read((32<<20)+1)
    if len(data)>32<<20:
        raise ValueError('decompressed package index too large')
    return data.decode('utf-8')

def version_key(version):
    if not re.fullmatch(r'\d+(?:\.\d+)*(?:-\d+)?',version):
        raise ValueError('unsupported package version: '+version)
    return tuple(int(n) for n in re.split('[.-]',version))

def select(lock, text, driver='latest'):
    wanted = {p['name'] for p in lock['packages']}
    packages = {name:{} for name in wanted}
    for record in text.split('\n\n'):
        fields = dict(line.split(': ',1) for line in record.splitlines() if ': ' in line and not line[0].isspace())
        name,version = fields.get('Package'),fields.get('Version','')
        if name not in wanted or fields.get('Architecture') not in ('amd64','all'):
            continue
        if not re.fullmatch(r'\d+(?:\.\d+)*(?:-\d+)?',version):
            continue
        filename = fields.get('Filename','').removeprefix('./')
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.+_-]*\.deb',filename) or not re.fullmatch('[0-9a-f]{64}',fields.get('SHA256','')):
            raise ValueError('invalid NVIDIA package path or hash')
        if version in packages[name]:
            raise ValueError('duplicate NVIDIA package version')
        packages[name][version]={'name':name,'version':version,'file':filename,'sha256':fields['SHA256']}
    groups=[]
    for group in (wanted-TOOLKIT, wanted&TOOLKIT):
        common=set.intersection(*(set(packages[name]) for name in group))
        if group == wanted-TOOLKIT and driver!='latest':
            common={v for v in common if v.split('-')[0]==driver}
        if not common:
            raise ValueError('no complete matching NVIDIA package set')
        chosen=max(common,key=version_key)
        # Daily latest checks never automatically downgrade either package group.
        previous=next(p['version'] for p in lock['packages'] if p['name'] in group)
        if driver=='latest' and version_key(chosen)<version_key(previous):
            raise ValueError('NVIDIA package set went backwards')
        groups.append((group,chosen))
    output=dict(lock,repository=REPOSITORY,driver=groups[0][1].split('-')[0],toolkit=groups[1][1].split('-')[0])
    versions={name:ver for group,ver in groups for name in group}
    output['packages']=[packages[p['name']][versions[p['name']]] for p in lock['packages']]
    return output

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--driver',default='latest',help='latest or an explicitly requested upstream version')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    lock=json.loads((ROOT/'plugins/nvidia/packages.lock.json').read_text())
    index=authenticate(download(REPOSITORY+'InRelease',1<<20),download(REPOSITORY+'Packages.gz',8<<20),ROOT/'plugins/nvidia/repository.pub')
    updated=select(lock,index,args.driver)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(updated,indent=2)+'\n')
    print('Selected NVIDIA',updated['driver'],'and Toolkit',updated['toolkit'])
