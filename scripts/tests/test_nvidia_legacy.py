"""The proprietary NVIDIA 580 plugin (nvidia-legacy): lock, branch and build switches."""
import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def module(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / file)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


upstream = module("upstream_legacy", "update-nvidia-lock.py")
fetcher = module("fetcher_legacy", "fetch-nvidia.py")
LOCK = ROOT / "plugins/nvidia-legacy/packages.lock.json"


def records(versions):
    return "\n\n".join(f"Package: {n}\nVersion: {v}\nArchitecture: amd64\nFilename: ./{n}_{v}_amd64.deb\nSHA256: " + "a" * 64
                       for n, vs in versions.items() for v in vs)


class LegacyLockTest(unittest.TestCase):
    def test_lock_is_the_proprietary_580_set(self):
        lock = json.loads(LOCK.read_text())
        names = {p["name"] for p in lock["packages"]}
        self.assertEqual(lock["branch"], "580")
        self.assertIn("nvidia-kernel-dkms", names)
        self.assertNotIn("nvidia-kernel-open-dkms", names)
        self.assertNotIn("firmware-nvidia-gsp", names)  # no GSP before Turing
        self.assertTrue({"libcuda1", "libnvidia-encode1", "libnvcuvid1", "nvidia-container-toolkit"} <= names)

    def test_selection_stays_on_the_branch(self):
        lock = json.loads(LOCK.read_text())
        names = [p["name"] for p in lock["packages"]]
        versions = {n: ["1.17.8-1", "1.18.0-1"] if n in upstream.TOOLKIT else ["580.95.05-1", "580.105.08-1", "590.44.01-1"]
                    for n in names}
        chosen = upstream.select(lock, records(versions))
        self.assertEqual(chosen["driver"], "580.105.08")
        self.assertEqual(chosen["branch"], "580")
        self.assertTrue(all(p["sha256"] for p in chosen["packages"]))
        # Once filled, a later refresh never goes backwards either.
        versions = {n: v[:1] if n not in upstream.TOOLKIT else v for n, v in versions.items()}
        with self.assertRaisesRegex(ValueError, "backwards"):
            upstream.select(chosen, records(versions))
        # A package without a 580 version is named.
        versions = {n: ["1.18.0-1"] if n in upstream.TOOLKIT else ["580.105.08-1"] for n in names}
        versions["libnvidia-nvvm4"] = ["590.44.01-1"]
        with self.assertRaisesRegex(ValueError, "libnvidia-nvvm4"):
            upstream.select(lock, records(versions))

    def test_unfilled_lock_is_refused_before_any_download(self):
        lock = json.loads(LOCK.read_text())
        if all(p["sha256"] for p in lock["packages"]):
            self.skipTest("lock already filled")
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "update-nvidia-lock.py --plugin nvidia-legacy"):
                fetcher.fetch(LOCK, Path(tmp))
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_build_script_switches(self):
        script = (ROOT / "scripts/make-nvidia-plugin.sh").read_text()
        self.assertIn("nvidia-legacy) dkms=nvidia-kernel-dkms sources=nvidia-legacy-sources.tar.gz", script)
        subprocess.run(["bash", "-n", str(ROOT / "scripts/make-nvidia-plugin.sh")], check=True)
        # Not part of the sets for now (owner decision 3.11.2026): no 580
        # packages in NVIDIA's debian13 index.
        action = (ROOT / ".github/actions/build-sets/action.yml").read_text()
        self.assertNotIn("NVIDIA_PLUGIN=nvidia-legacy", action)

    def test_metadata_names_conflict_and_sources(self):
        lock = json.loads(LOCK.read_text())
        with tempfile.TemporaryDirectory() as tmp:
            stage = Path(tmp)
            (stage / "usr/share/titanos/nvidia-legacy").mkdir(parents=True)
            for package in lock["packages"]:
                (stage / "usr/share/doc" / package["name"]).mkdir(parents=True)
                (stage / "usr/share/doc" / package["name"] / "copyright").write_text("x")
            subprocess.run(["python3", str(ROOT / "scripts/nvidia-plugin-metadata.py"), str(stage), "6.12.0-test", "kernel-x-1",
                            "nvidia-legacy"], cwd=ROOT, check=True)
            manifest = json.loads((stage / "plugin.json").read_text())
            self.assertEqual(manifest["conflicts"], ["nvidia"])
            self.assertEqual(manifest["services"], ["titanos-nvidia.service"])
            self.assertEqual(manifest["sources"][-1], "nvidia-legacy-sources.tar.gz")
            self.assertEqual(manifest["kernel"], "6.12.0-test")


if __name__ == "__main__":
    unittest.main()
