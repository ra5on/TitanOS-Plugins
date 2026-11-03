"""The kernel of the image that the driver plugins are built against."""
import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("drivers", ROOT / "scripts/make-driver-plugins.py")
drivers = importlib.util.module_from_spec(spec)
spec.loader.exec_module(drivers)


class ImageKernelTest(unittest.TestCase):
    def image(self, kernel, package_version):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        image = Path(tmp.name)
        (image / "rootfs/var/lib/dpkg").mkdir(parents=True)
        (image / "kernel-version").write_text(kernel + "\n")
        (image / "rootfs/var/lib/dpkg/status").write_text(
            f"Package: linux-image-{kernel}\nStatus: install ok installed\nVersion: {package_version}\n\n")
        return image

    def test_debian_and_backports_kernels(self):
        # 6.12.115 came with an ABI suffix ("+deb13.1"); the release of
        # 0.46.1 failed on it.
        for kernel, version in [("6.12.113+deb13-amd64", "6.12.113-1"),
                                ("6.12.115+deb13.1-amd64", "6.12.115-2"),
                                ("7.2.11+deb13-amd64", "7.2.11-1~bpo13+1")]:
            self.assertEqual(drivers.image_kernel(self.image(kernel, version)), (kernel, version))

    def test_realtek_only_for_the_stable_kernel(self):
        self.assertEqual(drivers.kernel_variant("6.12.115-2"), "stable")
        self.assertEqual(drivers.kernel_variant("7.2.11-1~bpo13+1"), "new")
        import json
        spec = json.loads((ROOT / "plugins/drivers/drivers.json").read_text())
        for name, plugin in spec["plugins"].items():
            with self.subTest(plugin=name):
                self.assertTrue(drivers.builds_for(plugin, "stable"))
                self.assertEqual(drivers.builds_for(plugin, "new"), name not in ("r8125", "r8126"))

    def test_odd_releases_are_refused(self):
        for kernel in ("6.12.113", "6.12.113+deb13-amd64/../x", "6.12.113 +deb13-amd64"):
            with self.assertRaises(SystemExit):
                drivers.image_kernel(self.image(kernel, "1"))


if __name__ == "__main__":
    unittest.main()
