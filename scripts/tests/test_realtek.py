"""The Realtek vendor driver plugins r8125 and r8126: device hand-over and pins."""
import hashlib
import importlib.util
import io
import json
import os
import re
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
DRIVERS = json.loads((ROOT / "plugins/drivers/drivers.json").read_text())
REBIND = ROOT / "plugins/r8125/root/usr/lib/titanos/realtek-rebind"
TITANOS = os.environ.get("TITANOS", "")

spec = importlib.util.spec_from_file_location("pin", ROOT / "scripts/pin-driver-source.py")
pin = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pin)


def device(sys, address, device_id, driver=None, vendor="0x10ec"):
    path = sys / "bus/pci/devices" / address
    path.mkdir(parents=True)
    (path / "vendor").write_text(vendor + "\n")
    (path / "device").write_text(device_id + "\n")
    (path / "driver_override").write_text("(null)\n")
    if driver:
        target = sys / "bus/pci/drivers" / driver
        target.mkdir(parents=True, exist_ok=True)
        (target / "unbind").touch()
        (path / "driver").symlink_to(target)
    return path


class RebindTest(unittest.TestCase):
    def run_rebind(self, sys, *args):
        return subprocess.run(["sh", str(REBIND), *args], env={"SYSFS": str(sys), "PATH": os.environ["PATH"]},
                              capture_output=True, text=True)

    def test_only_listed_chips_with_r8169_move(self):
        with tempfile.TemporaryDirectory() as tmp:
            sys = Path(tmp)
            (sys / "bus/pci").mkdir(parents=True)
            (sys / "bus/pci/drivers_probe").touch()
            nic = device(sys, "0000:03:00.0", "0x8125", "r8169")
            onboard = device(sys, "0000:04:00.0", "0x8168", "r8169")      # RTL8111: stays
            vm = device(sys, "0000:05:00.0", "0x8125", "vfio-pci")        # a VM's card: stays
            intel = device(sys, "0000:06:00.0", "0x8125", "e1000e", vendor="0x8086")
            result = self.run_rebind(sys, "start", "r8125", "8125", "3000")
            # Without a kernel nothing binds: the script gives the chip back.
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertEqual((sys / "bus/pci/drivers/r8169/unbind").read_text(), "0000:03:00.0\n")
            self.assertEqual((sys / "bus/pci/drivers_probe").read_text(), "0000:03:00.0\n")
            self.assertEqual((nic / "driver_override").read_text(), "\n")
            for untouched in (onboard, vm, intel):
                self.assertEqual((untouched / "driver_override").read_text(), "(null)\n")
            self.assertEqual((sys / "bus/pci/drivers/vfio-pci/unbind").read_text(), "")
            self.assertIn("left with vfio-pci", result.stdout)

    def test_stop_hands_vendor_bound_chips_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            sys = Path(tmp)
            (sys / "bus/pci").mkdir(parents=True)
            (sys / "bus/pci/drivers_probe").touch()
            nic = device(sys, "0000:03:00.0", "0x3000", "r8125")
            other = device(sys, "0000:04:00.0", "0x8125", "r8169")
            result = self.run_rebind(sys, "stop", "r8125", "8125", "3000")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((nic / "driver_override").read_text(), "\n")
            self.assertEqual((sys / "bus/pci/drivers/r8125/unbind").read_text(), "0000:03:00.0\n")
            self.assertEqual((other / "driver_override").read_text(), "(null)\n")
            self.assertNotEqual(self.run_rebind(sys, "start", "r8125").returncode, 0)

    def test_services_and_scripts_match_the_spec(self):
        for name in ("r8125", "r8126"):
            with self.subTest(plugin=name):
                plugin = DRIVERS["plugins"][name]
                root = ROOT / plugin["root"]
                self.assertEqual((root / "usr/lib/titanos/realtek-rebind").read_bytes(), REBIND.read_bytes())
                self.assertTrue(os.access(root / "usr/lib/titanos/realtek-rebind", os.X_OK))
                unit = (root / "usr/lib/systemd/system" / plugin["services"][0]).read_text()
                ids = " ".join(plugin["rebind"])
                self.assertIn(f"ExecStart=/usr/lib/titanos/realtek-rebind start {name} {ids}\n", unit)
                self.assertIn(f"ExecStop=/usr/lib/titanos/realtek-rebind stop {name} {ids}\n", unit)
                self.assertEqual(plugin["build"], "upstream")
                self.assertEqual(DRIVERS["external"][plugin["external"]]["license"], "GPL-2.0-only")

    @unittest.skipUnless(TITANOS and (Path(TITANOS) / "plugins/catalog").is_dir(), "TITANOS names no TitanOS checkout")
    def test_rebind_ids_are_the_catalog_rules(self):
        for name in ("r8125", "r8126"):
            with self.subTest(plugin=name):
                entry = json.loads((Path(TITANOS) / "plugins/catalog" / f"{name}.json").read_text())
                rules = {rule["modalias"] for rule in entry["hardware"]}
                self.assertEqual(rules, {f"pci:v000010ECd0000{i}sv*sd*bc*sc*i*" for i in DRIVERS["plugins"][name]["rebind"]})


class PinTest(unittest.TestCase):
    def archive(self, files):
        data = io.BytesIO()
        with tarfile.open(fileobj=data, mode="w:gz") as archive:
            for name, content in files.items():
                info = tarfile.TarInfo("rtl8125-abc/" + name)
                info.size = len(content)
                archive.addfile(info, io.BytesIO(content))
        return data.getvalue()

    def test_unpinned_sources_are_reported_and_refused(self):
        for name in ("r8125", "r8126"):
            external = DRIVERS["external"][name]
            if not pin.pinned(external):
                self.assertEqual(external["commit"], "")
        self.assertFalse(pin.pinned({"commit": "", "sha256": "", "url": ""}))
        self.assertTrue(pin.pinned({"commit": "a" * 40, "sha256": "b" * 64, "url": "x/" + "a" * 40 + ".tar.gz"}))
        source = (ROOT / "scripts/make-driver-plugins.py").read_text()
        self.assertIn("is not pinned yet", source)

    def test_pin_writes_only_the_four_values(self):
        data = self.archive({"src/Makefile": b"obj-m := r8125.o\n", "src/r8125_n.c": b"/* GPL-2.0 */\n", "README": b"x"})
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "drivers.json"
            original = (ROOT / "plugins/drivers/drivers.json").read_text()
            target.write_text(original)

            class Response(io.BytesIO):
                def __enter__(self):
                    return self

                def __exit__(self, *exc):
                    return False
            commit = "0123456789abcdef0123456789abcdef01234567"
            with patch.object(pin, "DRIVERS", target), \
                    patch.object(pin.urllib.request, "urlopen", lambda *a, **k: Response(data)), \
                    patch("sys.argv", ["pin", "r8125", commit, "--date", "2026-10-31"]):
                self.assertEqual(pin.main(), 0)
            after = json.loads(target.read_text())["external"]["r8125"]
            self.assertEqual(after["commit"], commit)
            self.assertEqual(after["sha256"], hashlib.sha256(data).hexdigest())
            self.assertEqual(after["url"], f"https://github.com/openwrt/rtl8125/archive/{commit}.tar.gz")
            self.assertTrue(pin.pinned(after))
            changed = [line for line in target.read_text().splitlines() if line not in original.splitlines()]
            self.assertEqual(len(changed), 4, changed)
            with self.assertRaises(SystemExit):
                pin.check_archive(self.archive({"README": b"x"}), after)


if __name__ == "__main__":
    unittest.main()
