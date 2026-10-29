"""Exercise the real Debian payload path used by the confined NAS builder."""
import importlib.util
import io
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("fetch_nvidia", Path(__file__).resolve().parents[1]/"fetch-nvidia.py")
fetcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fetcher)


@unittest.skipUnless(shutil.which("dpkg-deb") and shutil.which("ar"), "Debian archive tools required")
class NvidiaExtraction(unittest.TestCase):
    def package(self, root, unsafe=False):
        (root/"debian-binary").write_bytes(b"2.0\n")
        with tarfile.open(root/"control.tar", "w") as archive:
            content = b"Package: test-nvidia\nVersion: 1.0\nArchitecture: amd64\nMaintainer: Test <test@example.invalid>\nDescription: extraction fixture\n"
            item = tarfile.TarInfo("control"); item.size = len(content)
            archive.addfile(item, io.BytesIO(content))
        with tarfile.open(root/"data.tar", "w") as archive:
            item = tarfile.TarInfo("."); item.type = tarfile.DIRTYPE; item.mode = 0o644
            archive.addfile(item)
            item = tarfile.TarInfo("usr/bin/nvidia-modprobe"); item.mode = 0o4755; item.size = 4
            archive.addfile(item, io.BytesIO(b"test"))
            if unsafe:
                item = tarfile.TarInfo("escape"); item.type = tarfile.SYMTYPE; item.linkname = "../outside"
                archive.addfile(item)
        subprocess.run(["ar", "qc", "fixture.deb", "debian-binary", "control.tar", "data.tar"], cwd=root, check=True)
        return root/"fixture.deb"

    def test_modes_are_safe_and_payload_is_unchanged(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); destination = root/"stage"
            package = self.package(root)
            fetcher.extract(package, destination)
            fetcher.extract(package, destination)  # still traversable for subsequent packages
            binary = destination/"usr/bin/nvidia-modprobe"
            self.assertEqual(binary.read_bytes(), b"test")
            self.assertEqual(binary.stat().st_mode & 0o7777, 0o755)
            self.assertTrue(destination.stat().st_mode & 0o100)

    def test_links_outside_staging_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaises(tarfile.FilterError):
                fetcher.extract(self.package(root, unsafe=True), root/"stage")
            self.assertFalse((root/"outside").exists())
