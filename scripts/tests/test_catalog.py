"""Driver pins and the merge of TitanOS catalog entries into manifests.

The catalog entries live in TitanOS (plugins/catalog); these tests need its
checkout in $TITANOS and are skipped without it.
"""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TITANOS = os.environ.get("TITANOS", "")


@unittest.skipUnless(TITANOS and (Path(TITANOS) / "plugins/catalog").is_dir(), "TITANOS names no TitanOS checkout")
class CatalogTest(unittest.TestCase):
    def setUp(self):
        self.catalog = Path(TITANOS) / "plugins/catalog"
        self.drivers = json.loads((REPO / "plugins/drivers/drivers.json").read_text())

    def test_driver_plugins_have_hardware_rules_and_pins(self):
        for name, plugin in self.drivers["plugins"].items():
            with self.subTest(plugin=name):
                entry = json.loads((self.catalog / f"{name}.json").read_text())
                self.assertTrue(entry["hardware"])
                self.assertTrue(set(plugin["modules"]) <= set(plugin["built"]))
                for path in plugin.get("firmware", []) + plugin.get("notices", []):
                    self.assertRegex(self.drivers["firmware"]["files"][path]["sha256"], r"^[0-9a-f]{64}$")
                if "external" in plugin:
                    external = self.drivers["external"][plugin["external"]]
                    self.assertRegex(external["commit"], r"^[0-9a-f]{40}$")
                    self.assertRegex(external["sha256"], r"^[0-9a-f]{64}$")
                    self.assertIn(external["commit"], external["url"])
                if name != "it87-extended":
                    # Drivers: recommended only while no driver has the device.
                    self.assertTrue(all(rule.get("unbound") for rule in entry["hardware"]))

    def test_make_plugin_merges_catalog_under_build_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            stage = Path(tmp) / "stage"
            (stage / "usr/share").mkdir(parents=True)
            (stage / "plugin.json").write_text(json.dumps({"upstream": {"version": "1.2.3"}, "modules": [], "services": []}))
            subprocess.run([str(REPO / "scripts/make-plugin.sh"), "tailscale", "1.2.3-1", str(stage), tmp],
                           check=True, capture_output=True, env=os.environ | {"TITANOS": TITANOS})
            manifest = json.loads((Path(tmp) / "tailscale.plugin.json").read_text())
            self.assertEqual(manifest["category"], "remote")
            self.assertEqual(manifest["upstream"], {"name": "Tailscale", "url": "https://github.com/tailscale/tailscale", "version": "1.2.3"})
            self.assertEqual(manifest["details"]["en"]["hardware"], ["No special hardware"])
            self.assertEqual(manifest["version"], "1.2.3-1")


if __name__ == "__main__":
    unittest.main()
