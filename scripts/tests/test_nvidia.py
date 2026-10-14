"""Pinned downloads must reject corruption before extracting executable code."""
import hashlib
import importlib.util
import io
import json
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
