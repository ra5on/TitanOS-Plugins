import hashlib
import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
def module(name,file):
    spec=importlib.util.spec_from_file_location(name,ROOT/'scripts'/file)
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value
upstream=module('upstream','update-nvidia-lock.py')
release=module('driver_release','nvidia-update-release.py')

class UpstreamTest(unittest.TestCase):
    def setUp(self):
        self.names=['nvidia-kernel-open-dkms','firmware-nvidia-gsp','libcuda1','libnvidia-container1']
        self.lock=dict(packages=[dict(name=n,version='1.0-1') for n in self.names])
    def records(self,versions):
        return '\n\n'.join(f'Package: {n}\nVersion: {v}\nArchitecture: amd64\nFilename: ./{n}_{v}_amd64.deb\nSHA256: '+ 'a'*64 for n,vs in versions.items() for v in vs)
    def test_only_complete_same_version_sets_are_selected(self):
        versions={n:['1.0-1','2.0-1'] for n in self.names};versions['firmware-nvidia-gsp']=['1.0-1']
        chosen=upstream.select(self.lock,self.records(versions))
        self.assertEqual(chosen['driver'],'1.0');self.assertEqual(chosen['toolkit'],'2.0')
        with self.assertRaisesRegex(ValueError,'complete'): upstream.select(self.lock,self.records(versions),'2.0')
    def test_explicit_old_version_and_traversal(self):
        data=self.records({n:['1.0-1','2.0-1'] for n in self.names})
        self.assertEqual(upstream.select(self.lock,data,'1.0')['driver'],'1.0')
        with self.assertRaisesRegex(ValueError,'path'): upstream.select(self.lock,data.replace('Filename: ./','Filename: ../../'))
    def test_signature_failure_cannot_reach_package_selection(self):
        with patch.object(upstream.subprocess,'run',side_effect=subprocess.CalledProcessError(1,'gpg')):
            with self.assertRaises(subprocess.CalledProcessError): upstream.authenticate(b'forged',b'bad',ROOT/'plugins/nvidia/repository.pub')

class DriverPublicationTest(unittest.TestCase):
    def test_signed_append_only_assets_and_tamper_rejection(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'plugin';source.mkdir();out=root/'release';keys=root/'keys';keys.mkdir()
            key=keys/'test.key'
            subprocess.run(['minisign','-G','-W','-s',str(key),'-p',str(keys/'test.pub')],check=True,capture_output=True)
            image=b'compiled exact-kernel driver';checksum=hashlib.sha256(image).hexdigest()
            p=dict(name='nvidia',version='2-titanos-1.0.0-r2',driver='2.0',toolkit='1.0',titanos='1.0.0',kernel='test-kernel',revision=2,sha256=checksum,size=len(image))
            (source/'nvidia.raw').write_bytes(image);(source/'nvidia.plugin.json').write_text(json.dumps(p))
            for name in ('licenses','kernel-sources'): (source/('nvidia-'+name+'.tar.gz')).write_bytes(b'archive '+name.encode())
            target=root/'target.json';target.write_text(json.dumps(dict(version='1.0.0',kernel='test-kernel',packageSet='a'*64)))
            release.pack(target,source,out)
            previous=dict(titanos='1.0.0',kernel='test-kernel',versions=[dict(version='newer-upstream',driver='3.0',toolkit='1.0',sha256='b'*64,revision=1,size=40)],recommended='b'*64)
            with patch.object(release,'channel',return_value=previous),patch.object(release,'verify',side_effect=lambda p:verify_with_keys(p,keys)):
                release.sign_channel(out,key)
            menu=json.loads((out/'nvidia-updates.json').read_text())
            self.assertEqual(menu['recommended'],'b'*64,'publishing an older version must not recommend a downgrade')
            assets=release.verify_directory(out,keys)
            self.assertEqual(len(assets),7)
            self.assertFalse((out/'manifest.json').exists());self.assertFalse((out/'nvidia.raw').exists())
            (out/('nvidia-update-'+checksum+'.raw')).write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'mismatch'): release.verify_directory(out,keys)

def verify_with_keys(path,keys):
    for key in keys.glob('*.pub'):
        if subprocess.run(['minisign','-V','-q','-p',str(key),'-m',str(path)],capture_output=True).returncode==0:return
    raise ValueError('untrusted signature')
