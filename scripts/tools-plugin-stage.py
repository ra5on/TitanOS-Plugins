#!/usr/bin/env python3
"""Stage Intel tools and only dependencies absent from the base system."""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path


def stage(root, base, destination, version):
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)
    packages = {'intel-gpu-tools'}
    queue = []

    def copy(path):
        # Resolve symlinks inside the chroot using readlink there (absolute
        # links must not resolve against the build host).
        resolved = subprocess.check_output(['chroot', str(root), 'readlink', '-f', path], text=True).strip()
        source = root / resolved.lstrip('/')
        if not source.is_file():
            return
        target = destination / path.lstrip('/')
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        return target

    paths = subprocess.check_output(['chroot', str(root), 'dpkg-query', '-L', 'intel-gpu-tools'], text=True).splitlines()
    for path in paths:
        if path.startswith(('/usr/bin/', '/usr/sbin/', '/usr/lib/', '/usr/share/')):
            file = copy(path)
            if file and file.read_bytes()[:4] == b'\x7fELF':
                queue.append(path)
    seen = set()
    while queue:
        path = queue.pop()
        if path in seen:
            continue
        seen.add(path)
        result = subprocess.run(['chroot', str(root), 'ldd', path], text=True, capture_output=True)
        if 'not found' in result.stdout:
            raise ValueError('unresolved Intel tool dependency: ' + result.stdout)
        for dependency in re.findall(r'(?:=>\s+)?(/[^\s()]+)', result.stdout):
            relative = dependency.removeprefix('/')
            if relative.startswith('lib/'):
                relative = 'usr/' + relative
            if (base / relative).exists():
                continue
            copy('/' + relative)
            queue.append('/' + relative)
            owner = subprocess.check_output(['chroot', str(root), 'dpkg-query', '-S', '/' + relative], text=True).split(': ', 1)[0]
            packages.add(owner)
    notices = destination / 'usr/share/titanos/intel-gpu-tools'
    notices.mkdir(parents=True)
    sources = []
    for package in sorted(packages):
        fields = subprocess.check_output(['chroot', str(root), 'dpkg-query', '-W', '-f=${binary:Package}\t${Version}\t${source:Package}\t${source:Version}', package], text=True).split('\t')
        name, binary_version, source, source_version = fields
        doc = root / 'usr/share/doc' / name.split(':')[0]
        if not (doc / 'copyright').is_file():
            raise ValueError('missing copyright for ' + name)
        shutil.copytree(doc, destination / 'usr/share/doc' / name.split(':')[0], dirs_exist_ok=True)
        sources.append(f'{name} {binary_version}\nhttps://snapshot.debian.org/package/{source}/{source_version}/\n')
    shutil.copytree(root / 'usr/share/common-licenses', destination / 'usr/share/common-licenses', dirs_exist_ok=True)
    (notices / 'SOURCES.txt').write_text('\n'.join(sources))
    (destination / 'plugin.json').write_text(json.dumps({
        'title': 'Intel GPU Tools', 'description': {'de': 'Intel-GPU-Diagnosewerkzeuge aus Debian 13, einschließlich intel_gpu_top.', 'en': 'Intel GPU diagnostics from Debian 13, including intel_gpu_top.'},
        'contains': {'de': ['Intel GPU Tools und benötigte Zusatzbibliotheken', 'Originale Lizenzhinweise und genaue Debian-Quellpaketlinks'], 'en': ['Intel GPU Tools and required additional libraries', 'Original notices and exact Debian source package links']},
        'modules': [], 'services': [],
        'upstream': {'version': next(line.split()[1] for line in sources if line.startswith('intel-gpu-tools '))},
    }, indent=2) + '\n')

if __name__ == '__main__':
    stage(*(Path(p).resolve() for p in sys.argv[1:4]), sys.argv[4])
