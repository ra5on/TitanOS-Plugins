"""Pinned downloads must reject corruption before extracting executable code."""
import hashlib
import importlib.util
import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("fetch_nvidia", Path(__file__).resolve().parents[1] / "fetch-nvidia.py")
fetcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fetcher)


class NvidiaDownloadTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.lock = self.root / "lock.json"
        self.lock.write_text(json.dumps(dict(repository="https://example.invalid/", packages=[dict(
            name="nvidia-test", version="1", file="nvidia-test.deb", sha256=hashlib.sha256(b"valid").hexdigest())])))

    def test_corrupt_download_is_not_promoted(self):
        with patch.object(fetcher.urllib.request, "urlopen", return_value=io.BytesIO(b"corrupt")), patch.object(fetcher.subprocess, "check_output") as identity:
            with self.assertRaisesRegex(ValueError, "checksum"):
                fetcher.fetch(self.lock, self.root)
            identity.assert_not_called()
        self.assertFalse((self.root / "nvidia-test.deb").exists())
        self.assertFalse((self.root / "nvidia-test.part").exists())

    def test_cached_package_still_requires_matching_identity(self):
        (self.root / "nvidia-test.deb").write_bytes(b"valid")
        with patch.object(fetcher.urllib.request, "urlopen") as network, patch.object(fetcher.subprocess, "check_output", return_value="Package: other\nVersion: 1\n"):
            with self.assertRaisesRegex(ValueError, "identity"):
                fetcher.fetch(self.lock, self.root)
            network.assert_not_called()


class NvidiaRuntimeTest(unittest.TestCase):
    def test_atomic_cdi_output_and_failed_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            binary = root / "bin"
            binary.mkdir()
            for tool in ("ldconfig", "nvidia-modprobe", "nvidia-smi"):
                path = binary / tool
                path.write_text("#!/bin/sh\nexit 0\n")
                path.chmod(0o755)
            # Match nvidia-ctk: a supplied non-YAML filename gets .yaml appended.
            # Without an output filename the specification is written to stdout.
            ctk = binary / "nvidia-ctk"
            ctk.write_text("""#!/usr/bin/env python3
import os, pathlib, sys
output = next((v.split('=', 1)[1] for v in sys.argv if v.startswith('--output=')), '')
if os.environ.get('FAIL_CDI'):
    print('partial output')
    sys.exit(1)
content = 'cdiVersion: 0.5.0\\nkind: nvidia.com/gpu\\n'
if output:
    pathlib.Path(output if output.endswith('.yaml') else output + '.yaml').write_text(content)
else:
    print(content)
""")
            ctk.chmod(0o755)
            source = Path(__file__).resolve().parents[2] / "plugins/nvidia/root/usr/lib/titanos/nvidia-runtime"
            script = root / "runtime"
            cdi = root / "cdi"
            script.write_text(source.read_text().replace('/run/cdi', str(cdi)).replace('/sbin/ldconfig', str(binary / 'ldconfig')))
            env = dict(os.environ, PATH=str(binary) + ':' + os.environ['PATH'])
            subprocess.run(['sh', str(script), 'start'], env=env, check=True)
            published = cdi / 'titanos-nvidia.yaml'
            original = published.read_text()
            self.assertIn('nvidia.com/gpu', original)
            self.assertEqual([p.name for p in cdi.iterdir()], ['titanos-nvidia.yaml'])
            result = subprocess.run(['sh', str(script), 'start'], env=dict(env, FAIL_CDI='1'))
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(published.read_text(), original)
            self.assertEqual([p.name for p in cdi.iterdir()], ['titanos-nvidia.yaml'])
            subprocess.run(['sh', str(script), 'stop'], env=env, check=True)
            self.assertEqual(list(cdi.iterdir()), [])
