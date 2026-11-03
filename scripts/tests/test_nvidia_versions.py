"""Which NVIDIA driver versions a NAS can choose, and building a chosen one."""
import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("updater", ROOT / "scripts/update-nvidia-lock.py")
updater = importlib.util.module_from_spec(spec)
spec.loader.exec_module(updater)

LOCK = {"packages": [{"name": "nvidia-kernel-open-dkms", "version": "1"}, {"name": "libcuda1", "version": "1"},
                     {"name": "nvidia-container-toolkit", "version": "1.20.1-1"}]}


def record(name, version, n):
    return (f"Package: {name}\nVersion: {version}\nArchitecture: amd64\n"
            f"Filename: ./{name}_{version}_amd64.deb\nSHA256: {n:064x}")


def index(*entries):
    return "\n\n".join(record(name, version, n) for n, (name, version) in enumerate(entries))


INDEX = index(("nvidia-kernel-open-dkms", "615.71.09-1"), ("libcuda1", "615.71.09-1"),
              ("nvidia-kernel-open-dkms", "580.105.08-1"), ("libcuda1", "580.105.08-1"),
              ("nvidia-kernel-open-dkms", "590.44.01-1"), ("libcuda1", "590.44.01-1"),
              # Incomplete: libcuda1 of 575 is missing.
              ("nvidia-kernel-open-dkms", "575.64.05-1"),
              ("nvidia-container-toolkit", "1.20.1-1"), ("nvidia-container-toolkit", "1.19.0-1"))


class VersionsTest(unittest.TestCase):
    def test_complete_driver_versions_newest_first(self):
        self.assertEqual(updater.drivers(LOCK, INDEX), ["615.71.09", "590.44.01", "580.105.08"])

    def test_a_chosen_older_driver_with_the_newest_toolkit(self):
        lock = updater.select(LOCK, INDEX, "580.105.08")
        self.assertEqual((lock["driver"], lock["toolkit"]), ("580.105.08", "1.20.1"))
        self.assertEqual({p["version"] for p in lock["packages"] if p["name"] != "nvidia-container-toolkit"}, {"580.105.08-1"})

    def test_latest_and_refusals(self):
        self.assertEqual(updater.select(LOCK, INDEX)["driver"], "615.71.09")
        for driver in ("575.64.05", "999.1", "580.105.08; rm", "../1"):
            with self.subTest(driver), self.assertRaises(ValueError):
                updater.select(LOCK, INDEX, driver)


if __name__ == "__main__":
    unittest.main()
