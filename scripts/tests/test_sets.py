import hashlib
import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("sets", ROOT / "scripts/sets.py")
sets = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sets)

KERNEL, PACKAGE = "6.12.113+deb13-amd64", "6.12.113-1"


def image(root):
    (root / "rootfs/var/lib/dpkg").mkdir(parents=True)
    (root / "rootfs/usr/lib").mkdir(parents=True)
    (root / "kernel-version").write_text(KERNEL + "\n")
    (root / "rootfs/var/lib/dpkg/status").write_text(
        f"Package: linux-image-{KERNEL}\nStatus: install ok installed\nVersion: {PACKAGE}\n\nPackage: bash\nStatus: install ok installed\nVersion: 5\n")
    (root / "rootfs/usr/lib/os-release").write_text('NAME="TitanOS"\nSYSEXT_LEVEL=1\nVERSION_CODENAME=trixie\n')
    return root


def plugin(directory, name, version, kernel="", content=None):
    raw = directory / (name + ".raw")
    raw.write_bytes(content or ("image of " + name + version).encode())
    manifest = {"name": name, "version": version, "kernel": kernel,
                "sha256": hashlib.sha256(raw.read_bytes()).hexdigest(), "size": raw.stat().st_size}
    (directory / (name + ".plugin.json")).write_text(json.dumps(manifest))
    (directory / (name + "-licenses.tar.gz")).write_bytes(b"licenses")


class SetsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.keys = self.tmp / "keys"
        self.keys.mkdir()
        self.key = self.tmp / "test.key"
        subprocess.run(["minisign", "-G", "-W", "-s", str(self.key), "-p", str(self.keys / "test.pub")],
                       check=True, capture_output=True)
        self.image = image(self.tmp / "image")
        self.plugins = self.tmp / "plugins"
        self.plugins.mkdir()
        patcher = patch.object(sets, "KEYS", self.keys)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_common_set_index_sign_verify_pointer(self):
        plugin(self.plugins, "tailscale", "1.90.0-1")
        plugin(self.plugins, "nvidia", "615.71.09-1", KERNEL)
        out = self.tmp / "common"
        sets.index("common", "common-1", self.plugins, self.image, "0.36.0", out)
        index = json.loads((out / "index.json").read_text())
        self.assertEqual([p["name"] for p in index["plugins"]], ["tailscale"])
        self.assertEqual((index["debian"], index["sysextLevel"], index["kernel"], index["minBase"]), ("trixie", "1", "", "0.36.0"))
        self.assertIn("inputs", index["plugins"][0])
        self.assertFalse((out / "nvidia.raw").exists())
        sets.sign_set(out, self.key)
        sets.verify(out, self.keys)
        sets.pointer(out, "-", self.tmp / "catalog", self.key)
        catalog = json.loads((self.tmp / "catalog/catalog.json").read_text())
        self.assertEqual(catalog["serial"], 1)
        self.assertEqual(catalog["common"], {"tag": "common-1", "index": sets.digest(out / "index.json")})
        # Tampering with an image is noticed.
        (out / "tailscale.raw").write_bytes(b"changed")
        with self.assertRaises(SystemExit):
            sets.verify(out, self.keys)

    def test_kernel_set_needs_matching_tag_and_kernel(self):
        plugin(self.plugins, "nvidia", "615.71.09-1", KERNEL)
        for extra in sets.KERNEL_EXTRAS:
            (self.plugins / extra).write_bytes(b"x")
        with self.assertRaises(SystemExit):
            sets.index("kernel", "kernel-6.12.112-1-1", self.plugins, self.image, "0.36.0", self.tmp / "k")
        sets.index("kernel", f"kernel-{PACKAGE}-1", self.plugins, self.image, "0.36.0", self.tmp / "k")
        sets.sign_set(self.tmp / "k", self.key)
        sets.pointer(self.tmp / "k", "-", self.tmp / "c1", self.key)
        # A second kernel set of the same kernel replaces the entry.
        sets.index("kernel", f"kernel-{PACKAGE}-2", self.plugins, self.image, "0.36.0", self.tmp / "k2")
        sets.sign_set(self.tmp / "k2", self.key)
        sets.pointer(self.tmp / "k2", self.tmp / "c1", self.tmp / "c2", self.key)
        catalog = json.loads((self.tmp / "c2/catalog.json").read_text())
        self.assertEqual(catalog["serial"], 2)
        self.assertEqual([k["tag"] for k in catalog["kernels"]], [f"kernel-{PACKAGE}-2"])
        plugin(self.plugins, "nvidia", "615.71.09-1", "6.12.0-other")
        with self.assertRaises(SystemExit):
            sets.index("kernel", f"kernel-{PACKAGE}-3", self.plugins, self.image, "0.36.0", self.tmp / "k3")

    def test_carry_keeps_unchanged_plugins(self):
        plugin(self.plugins, "tailscale", "1.90.0-1")
        plugin(self.plugins, "netbird", "0.60.0-1")
        sets.index("common", "common-1", self.plugins, self.image, "0.36.0", self.tmp / "s1")
        # Rebuilt from the same inputs; only the squashfs bytes differ.
        plugin(self.plugins, "tailscale", "1.90.0-2", content=b"rebuilt")
        plugin(self.plugins, "netbird", "0.60.0-2", content=b"rebuilt netbird")
        sets.index("common", "common-2", self.plugins, self.image, "0.36.0", self.tmp / "s2")
        index = json.loads((self.tmp / "s2/index.json").read_text())
        index["plugins"][0]["inputs"] = "changed"  # netbird changed
        (self.tmp / "s2/index.json").write_text(json.dumps(index))
        sets.carry(self.tmp / "s2", self.tmp / "s1")
        versions = {p["name"]: p["version"] for p in json.loads((self.tmp / "s2/index.json").read_text())["plugins"]}
        self.assertEqual(versions, {"netbird": "0.60.0-2", "tailscale": "1.90.0-1"})
        sets.sign_set(self.tmp / "s2", self.key)
        sets.verify(self.tmp / "s2", self.keys)

    def test_next_tag(self):
        tags = self.tmp / "tags"
        tags.write_text(f"common-1\ncommon-3\nkernel-{PACKAGE}-1\ncatalog\n")
        with patch("builtins.print") as out:
            sets.next_tag("common", "-", tags)
            sets.next_tag("kernel", PACKAGE, tags)
            sets.next_tag("kernel", "6.12.120-1", tags)
        self.assertEqual([c.args[0] for c in out.call_args_list], ["common-4", f"kernel-{PACKAGE}-2", "kernel-6.12.120-1-1"])


if __name__ == "__main__":
    unittest.main()
