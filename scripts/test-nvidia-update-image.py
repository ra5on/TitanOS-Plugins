#!/usr/bin/env python3
"""Inspect an independently built driver without loading it on the build host."""
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

spec=importlib.util.spec_from_file_location('driver_release',Path(__file__).with_name('nvidia-update-release.py'))
release=importlib.util.module_from_spec(spec);spec.loader.exec_module(release)

def check(directory):
    paths=list(directory.glob('nvidia-update-*.plugin.json'))
    if len(paths)!=1: raise ValueError('exactly one driver expected')
    p=json.loads(paths[0].read_text());release.verify_package(directory,p)
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp)/'root'
        subprocess.run(['unsquashfs','-no-progress','-d',str(root),str(directory/('nvidia-update-'+p['sha256']+'.raw'))],check=True,stdout=subprocess.DEVNULL)
        extension=(root/'usr/lib/extension-release.d/extension-release.nvidia').read_text()
        if 'ID=titanos\n' not in extension or 'SYSEXT_LEVEL=1\n' not in extension: raise ValueError('wrong sysext target')
        for module in ('nvidia','nvidia-uvm','nvidia-modeset','nvidia-drm'):
            path=root/'usr/lib/modules'/p['kernel']/'updates/titanos-nvidia'/(module+'.ko')
            kernel=subprocess.check_output(['modinfo','-F','vermagic',str(path)],text=True).split()[0]
            version=subprocess.check_output(['modinfo','-F','version',str(path)],text=True).strip()
            if kernel!=p['kernel'] or version!=p['driver']: raise ValueError('module ABI or version mismatch')
        for binary in ('nvidia-smi','nvidia-modprobe','nvidia-ctk','nvidia-cdi-hook'):
            if not (root/'usr/bin'/binary).is_file(): raise ValueError('missing '+binary)
        for name in ('gsp_tu10x.bin','gsp_ga10x.bin'):
            if not (root/'usr/lib/firmware/nvidia'/p['driver']/name).is_file(): raise ValueError('missing matching GSP firmware')
        lock=json.loads((root/'usr/share/titanos/nvidia/packages.lock.json').read_text())
        if lock['driver']!=p['driver'] or lock['toolkit']!=p['toolkit']: raise ValueError('mixed driver libraries')
    print('Driver image and exact kernel compatibility verified; physical GPU testing remains necessary.')

if __name__=='__main__': check(Path(sys.argv[1]))
