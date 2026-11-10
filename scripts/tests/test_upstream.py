"""Newer upstream releases: which are found, what a bump pins, what it refuses."""
import contextlib
import hashlib
import importlib.util
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("upstream", ROOT / "scripts/upstream.py")
upstream = importlib.util.module_from_spec(spec)
spec.loader.exec_module(upstream)


class UpstreamTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = Path(tmp.name)
        for name in ("tailscale", "netbird"):
            shutil.copytree(ROOT / "plugins" / name, self.repo / "plugins" / name)
        self.old_repo, upstream.REPO = upstream.REPO, self.repo
        self.addCleanup(setattr, upstream, "REPO", self.old_repo)
        self.served = {}
        self.old_get, upstream.get = upstream.get, lambda url, limit=0: self.served[url]
        self.addCleanup(setattr, upstream, "get", self.old_get)
        self.latest = {name: plugin["latest"] for name, plugin in upstream.PLUGINS.items()}
        self.addCleanup(lambda: [upstream.PLUGINS[n].__setitem__("latest", f) for n, f in self.latest.items()])

    def lock(self, name):
        return json.loads((self.repo / "plugins" / name / "packages.lock.json").read_text())

    def run_check(self, tailscale, netbird):
        upstream.PLUGINS["tailscale"]["latest"] = lambda: tailscale
        upstream.PLUGINS["netbird"]["latest"] = lambda: netbird
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            upstream.check()
        return out.getvalue().splitlines()

    def test_only_newer_versions_are_reported(self):
        pinned = self.lock("tailscale")["version"]
        major, minor, patch = map(int, pinned.split("."))
        self.assertEqual(self.run_check(f"{major}.{minor}.{patch + 1}", self.lock("netbird")["version"]),
                         [f"tailscale={major}.{minor}.{patch + 1}", "names=tailscale"])
        self.assertEqual(self.run_check(pinned, "0.0.1"), ["names="])
        with self.assertRaises(ValueError):
            self.run_check("1.2.3-pre", "0.0.1")

    def serve_tailscale(self, version, license_text=None, checksum=None):
        archive = b"archive " + version.encode()
        self.served[f"https://pkgs.tailscale.com/stable/tailscale_{version}_amd64.tgz"] = archive
        self.served[f"https://pkgs.tailscale.com/stable/tailscale_{version}_amd64.tgz.sha256"] = \
            (checksum if checksum is not None else hashlib.sha256(archive).hexdigest()).encode()
        licenses = self.repo / "plugins/tailscale/licenses"
        self.served[f"https://raw.githubusercontent.com/tailscale/tailscale/v{version}/LICENSE"] = \
            license_text if license_text is not None else (licenses / "LICENSE").read_bytes()
        self.served["https://tailscale.com/licenses/tailscale"] = b"<html>new list</html>"
        return archive

    def test_bump_pins_archive_and_notices(self):
        archive = self.serve_tailscale("99.0.0")
        with contextlib.redirect_stdout(io.StringIO()):
            upstream.bump("tailscale", "99.0.0")
        lock = self.lock("tailscale")
        self.assertEqual((lock["version"], lock["size"], lock["sha256"]), ("99.0.0", len(archive), hashlib.sha256(archive).hexdigest()))
        self.assertEqual(lock["url"], "https://pkgs.tailscale.com/stable/tailscale_99.0.0_amd64.tgz")
        self.assertEqual(lock["source"], "https://github.com/tailscale/tailscale/tree/v99.0.0")
        notices = {n["file"]: n for n in lock["notices"]}
        self.assertEqual(notices["third-party.html"]["sha256"], hashlib.sha256(b"<html>new list</html>").hexdigest())
        self.assertEqual((self.repo / "plugins/tailscale/licenses/third-party.html").read_bytes(), b"<html>new list</html>")
        self.assertIn("v99.0.0/LICENSE", notices["LICENSE"]["url"])

    def test_a_changed_license_changes_nothing(self):
        before = (self.repo / "plugins/tailscale/packages.lock.json").read_text()
        self.serve_tailscale("99.0.0", b"Another license.\n")
        with self.assertRaises(upstream.LicenseChanged):
            upstream.bump("tailscale", "99.0.0")
        self.assertEqual((self.repo / "plugins/tailscale/packages.lock.json").read_text(), before)
        self.assertNotEqual((self.repo / "plugins/tailscale/licenses/third-party.html").read_bytes(), b"<html>new list</html>")

    def test_an_archive_the_publisher_does_not_name_is_not_pinned(self):
        before = (self.repo / "plugins/tailscale/packages.lock.json").read_text()
        self.serve_tailscale("99.0.0", checksum="0" * 64)
        with self.assertRaises(SystemExit):
            upstream.bump("tailscale", "99.0.0")
        self.assertEqual((self.repo / "plugins/tailscale/packages.lock.json").read_text(), before)

    def test_no_downgrade_and_only_known_plugins(self):
        with self.assertRaises(SystemExit):
            upstream.bump("tailscale", "0.0.1")
        with self.assertRaises(SystemExit):
            upstream.bump("nvidia", "999.0.0")


if __name__ == "__main__":
    unittest.main()
