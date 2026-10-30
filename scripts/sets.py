#!/usr/bin/env python3
"""Plugin sets of this repository: index, carry-over, rehearsal signing and the pointer.

A set is one GitHub release: "common-<n>" (kernel-independent plugins) or
"kernel-<kernel package>-<n>" (plugins for one exact Debian kernel). Its
index.json names every plugin with the hashes TitanOS checks; the pointer
catalog.json in the fixed release "catalog" names the current sets. Format and
checks: docs/PLUGIN-REPO.md in TitanOS.

Releases are signed only by TitanOS (scripts/sign-plugin-set.py there); no
code of this repository runs next to the release key. Signing here is for
rehearsals and tests with a disposable key without a password.

  sets.py index   <kind> <tag> <plugins dir> <image dir> <base> <set dir>
  sets.py carry   <set dir> <previous set dir>
  sets.py rehearsal-sign <set dir> <disposable key>
  sets.py verify  <set dir> [keys dir]
  sets.py next    <kind> <kernel package or -> <existing tags file>
  sets.py kernel  <image dir>
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEYS = ROOT / "keys"
COMMON = {"intel-gpu-tools", "coral-usb", "tailscale", "netbird"}
# Files of a kernel set besides the plugins' own.
KERNEL_EXTRAS = ["nvidia-kernel-sources.tar.gz", "nvidia-build-sdk.tar.zst", "nvidia-build-sdk.json",
                 "nvidia-build-sdk-sources.txt"]
TAG = re.compile(r"(common|kernel-[0-9][0-9A-Za-z._~-]*)-([1-9][0-9]*)")


def tag_package(package):
    """A "+" in a Debian version would need escaping in download URLs."""
    return package.replace("+", "_")
MAX_KERNELS = 64

# What a kernel-independent plugin is built from, besides the TitanOS catalog
# entry and the image. The same inputs mean the previous build is kept.
INPUTS = {
    "tailscale": ["plugins/tailscale", "scripts/make-tailscale-plugin.py"],
    "netbird": ["plugins/netbird", "scripts/make-netbird-plugin.py"],
    "coral-usb": ["plugins/coral", "scripts/make-tools-plugins.sh"],
    "intel-gpu-tools": ["plugins/intel-gpu-tools", "scripts/tools-plugin-stage.py", "scripts/make-tools-plugins.sh"],
}


def digest(path):
    with open(path, "rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def inputs(name, titanos):
    """A hash over everything a kernel-independent plugin is built from."""
    files = []
    for entry in INPUTS[name] + ["scripts/make-plugin.sh", "LICENSE.md"]:
        path = ROOT / entry
        files += sorted(p for p in path.rglob("*") if p.is_file()) if path.is_dir() else [path]
    total = hashlib.sha256()
    for path in files:
        total.update(str(path.relative_to(ROOT)).encode() + b"\0" + digest(path).encode() + b"\0")
    catalog = Path(titanos) / "plugins/catalog" / (name + ".json")
    if catalog.is_file():
        total.update(b"catalog\0" + digest(catalog).encode())
    return total.hexdigest()


def image_identity(image):
    """Kernel, its Debian package version, Debian codename and sysext level."""
    image = Path(image)
    kernel = (image / "kernel-version").read_text().strip()
    package = ""
    for block in (image / "rootfs/var/lib/dpkg/status").read_text().split("\n\n"):
        fields = dict(re.findall(r"^(Package|Version|Status): (.*)$", block, re.M))
        if fields.get("Package") == f"linux-image-{kernel}" and fields.get("Status") == "install ok installed":
            package = fields["Version"]
    if not package:
        raise SystemExit(f"linux-image-{kernel} is not installed in the image")
    release = dict(re.findall(r'^([A-Z_]+)="?([^"\n]*)"?$', (image / "rootfs/usr/lib/os-release").read_text(), re.M))
    return kernel, package, release.get("VERSION_CODENAME", ""), release.get("SYSEXT_LEVEL", "")


def plugin_files(plugins, name):
    names = [name + ".raw", name + ".plugin.json", name + "-licenses.tar.gz"]
    if (plugins / (name + "-sources.tar.gz")).exists():
        names.append(name + "-sources.tar.gz")
    return names


def write_index(directory, index):
    index["assets"] = sorted(({"name": p.name, "sha256": digest(p), "size": p.stat().st_size}
                              for p in directory.iterdir() if p.is_file() and not p.name.startswith("index.json")
                              and not p.name.endswith(".minisig")), key=lambda a: a["name"])
    (directory / "index.json").write_text(json.dumps(index, indent=2, ensure_ascii=False) + "\n")


def item(directory, name):
    manifest_path = directory / (name + ".plugin.json")
    manifest = json.loads(manifest_path.read_text())
    if manifest["name"] != name or digest(directory / (name + ".raw")) != manifest["sha256"]:
        raise SystemExit(f"{name}: manifest and image do not match")
    return {"name": name, "version": manifest["version"], "manifest": digest(manifest_path),
            "sha256": manifest["sha256"], "size": manifest["size"]}


def index(kind, tag, plugins, image, base, out):
    match = TAG.fullmatch(tag)
    if not match or (kind == "common") != (match[1] == "common"):
        raise SystemExit(f"tag {tag} is not a {kind} set")
    plugins, out = Path(plugins), Path(out)
    kernel, package, debian, level = image_identity(image)
    if kind == "kernel" and match[1] != f"kernel-{tag_package(package)}":
        raise SystemExit(f"tag {tag} does not name the kernel package {package}")
    names = sorted(p.name.removesuffix(".plugin.json") for p in plugins.glob("*.plugin.json"))
    names = [n for n in names if (n in COMMON) == (kind == "common")]
    if not names:
        raise SystemExit("no plugins for this set")
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    entries = []
    for name in names:
        manifest = json.loads((plugins / (name + ".plugin.json")).read_text())
        if kind == "kernel" and manifest.get("kernel") != kernel:
            raise SystemExit(f"{name} is not built for {kernel}")
        if kind == "common" and manifest.get("kernel"):
            raise SystemExit(f"{name} is bound to a kernel")
        for file in plugin_files(plugins, name):
            shutil.copy2(plugins / file, out / file)
        entry = item(out, name)
        if kind == "common":
            entry["inputs"] = inputs(name, os.environ.get("TITANOS", ""))
        entries.append(entry)
    if kind == "kernel":
        for file in KERNEL_EXTRAS:
            shutil.copy2(plugins / file, out / file)
    write_index(out, {"tag": tag, "debian": debian, "sysextLevel": level,
                      "kernel": kernel if kind == "kernel" else "", "kernelPackage": package if kind == "kernel" else "",
                      "minBase": base, "plugins": entries})
    print(f"{tag}: {', '.join(names)} (debian {debian}, sysext {level}, kernel {kernel} {package})")


def carry(directory, previous):
    """Keep the previous build of every plugin whose inputs did not change, so
    that its version (and what NAS have installed) stays the same. Prints the
    names that were rebuilt; none means the set need not be published."""
    directory, previous = Path(directory), Path(previous)
    new = json.loads((directory / "index.json").read_text())
    old = {p["name"]: p for p in json.loads((previous / "index.json").read_text())["plugins"]}
    changed = []
    for position, entry in enumerate(new["plugins"]):
        before = old.get(entry["name"])
        if before and before.get("inputs") == entry["inputs"]:
            for file in plugin_files(previous, entry["name"]):
                shutil.copy2(previous / file, directory / file)
            new["plugins"][position] = item(directory, entry["name"]) | {"inputs": entry["inputs"]}
        else:
            changed.append(entry["name"])
    new["plugins"] = sorted(new["plugins"], key=lambda p: p["name"])
    write_index(directory, new)
    print(" ".join(changed))


def sign(path, key):
    """Signs with a disposable key; the release key never comes here."""
    if os.environ.get("MINISIGN_PASSWORD") is not None:
        raise SystemExit("releases are signed by TitanOS (scripts/sign-plugin-set.py), not here")
    subprocess.run(["minisign", "-S", "-s", str(key), "-m", str(path), "-t", "TitanOS plugins: " + path.name],
                   stdin=subprocess.DEVNULL, check=True, stdout=subprocess.DEVNULL)


def verified(path, keys):
    for key in sorted(Path(keys).glob("*.pub")):
        if subprocess.run(["minisign", "-V", "-q", "-p", str(key), "-m", str(path)],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
            return True
    return False


def sign_set(directory, key):
    directory = Path(directory)
    for path in sorted(directory.glob("*.plugin.json")) + [directory / "index.json"]:
        sign(path, key)


def verify(directory, keys=KEYS):
    directory = Path(directory)
    if not verified(directory / "index.json", keys):
        raise SystemExit("index.json: untrusted signature")
    index = json.loads((directory / "index.json").read_text())
    for asset in index["assets"]:
        path = directory / asset["name"]
        if digest(path) != asset["sha256"] or path.stat().st_size != asset["size"]:
            raise SystemExit(f"{asset['name']}: does not match the index")
    for entry in index["plugins"]:
        path = directory / (entry["name"] + ".plugin.json")
        if not verified(path, keys) or item(directory, entry["name"]) | {k: entry[k] for k in ("inputs",) if k in entry} != entry:
            raise SystemExit(f"{entry['name']}: signature or hashes")
    print(f"{index['tag']}: verified")


def pointer(directory, current, output, key):
    """catalog.json with the new set, serial one higher than the current
    (tests only; TitanOS writes the real pointer)."""
    directory, output = Path(directory), Path(output)
    index = json.loads((directory / "index.json").read_text())
    ref = {"tag": index["tag"], "index": digest(directory / "index.json")}
    catalog = {"serial": 0, "debian": index["debian"], "sysextLevel": index["sysextLevel"], "common": None, "kernels": []}
    if current != "-":
        path = Path(current) / "catalog.json"
        if not verified(path, KEYS):
            raise SystemExit("current catalog.json: untrusted signature")
        catalog = json.loads(path.read_text())
    if (catalog["debian"], catalog["sysextLevel"]) != (index["debian"], index["sysextLevel"]):
        # Another Debian release or sysext level starts a new catalog.
        catalog.update(debian=index["debian"], sysextLevel=index["sysextLevel"], common=None, kernels=[])
    if index["kernel"]:
        ref = {"kernel": index["kernel"], "kernelPackage": index["kernelPackage"]} | ref
        catalog["kernels"] = [k for k in catalog["kernels"]
                              if (k["kernel"], k["kernelPackage"]) != (index["kernel"], index["kernelPackage"])]
        catalog["kernels"] = (catalog["kernels"] + [ref])[-MAX_KERNELS:]
    else:
        catalog["common"] = ref
    catalog["serial"] += 1
    output.mkdir(parents=True, exist_ok=True)
    (output / "catalog.json").write_text(json.dumps(catalog, indent=2) + "\n")
    sign(output / "catalog.json", key)
    print(f"catalog.json serial {catalog['serial']}")


def next_tag(kind, package, tags):
    prefix = "common" if kind == "common" else f"kernel-{tag_package(package)}"
    numbers = [int(m[2]) for t in Path(tags).read_text().split() if (m := TAG.fullmatch(t)) and m[1] == prefix]
    print(f"{prefix}-{max(numbers, default=0) + 1}")


def main(args):
    commands = {
        "index": (6, lambda a: index(*a)),
        "carry": (2, lambda a: carry(*a)),
        "rehearsal-sign": (2, lambda a: sign_set(*a)),
        "verify": (None, lambda a: verify(*a)),
        "next": (3, lambda a: next_tag(*a)),
        "kernel": (1, lambda a: print(json.dumps(dict(zip(("kernel", "kernelPackage", "debian", "sysextLevel"), image_identity(a[0])))))),
    }
    if not args or args[0] not in commands:
        raise SystemExit(__doc__)
    count, run = commands[args[0]]
    if (count is not None and len(args) - 1 != count) or (count is None and len(args) not in (2, 3)):
        raise SystemExit(__doc__)
    run(args[1:])


if __name__ == "__main__":
    main(sys.argv[1:])
