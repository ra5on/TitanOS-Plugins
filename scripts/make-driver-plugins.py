#!/usr/bin/env python3
"""Build the driver plugins (plugins/drivers/drivers.json) for the exact image kernel.

Usage (as root, with the TitanOS image built in $TITANOS): make-driver-plugins.py <set revision> [name ...]

Kernel drivers are compiled from Debian's linux-source package of exactly
the version of the image's linux-image package, against the matching
headers, in a disposable mkosi root; nothing is installed on the host.
External sources and firmware are pinned by commit and SHA-256. The build
stops on any mismatch: package versions, kernel source version, vermagic of
every module, and the module aliases against the hardware rules of the
catalog (plugins/catalog/<name>.json), which the image uses to recommend
the plugin. Output in out/plugins: <name>.raw, <name>.plugin.json,
<name>-licenses.tar.gz and <name>-sources.tar.gz (the exact compiled sources).
"""
import gzip
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
EPOCH = 0


def fail(message):
    raise SystemExit("driver plugins: " + message)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def image_kernel(image):
    """The kernel release and the Debian version of its linux-image package."""
    kernel = (image / "kernel-version").read_text().strip()
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+\+[a-z0-9]+-[a-z0-9]+", kernel):
        fail(f"unexpected kernel release {kernel!r}")
    status = (image / "rootfs/var/lib/dpkg/status").read_text()
    for block in status.split("\n\n"):
        fields = dict(re.findall(r"^(Package|Version|Status): (.*)$", block, re.M))
        if fields.get("Package") == f"linux-image-{kernel}" and fields.get("Status") == "install ok installed":
            return kernel, fields["Version"]
    fail(f"linux-image-{kernel} is not installed in the image")


def fetch(url, expected, cache):
    """Download once into cache and insist on the pinned SHA-256."""
    target = cache / expected
    if target.is_file() and sha256(target.read_bytes()) == expected:
        return target.read_bytes()
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "TitanOS build"}), timeout=120) as response:
        data = response.read(64 << 20)
    if sha256(data) != expected:
        fail(f"{url}: SHA-256 {sha256(data)} instead of the pinned {expected}")
    cache.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return data


def epoch():
    """A fixed time for archives and images: SOURCE_DATE_EPOCH or the commit's."""
    if os.environ.get("SOURCE_DATE_EPOCH"):
        return int(os.environ["SOURCE_DATE_EPOCH"])
    result = subprocess.run(["git", "log", "-1", "--format=%ct"], capture_output=True, text=True)
    return int(result.stdout.strip() or 0)


def normalized(info):
    """Tar entries without builder-specific owners or times."""
    info.uid = info.gid = 0
    info.uname = info.gname = ""
    info.mtime = EPOCH
    return info


class DeterministicTar:
    """A gzip'd tar whose bytes do not depend on when or by whom it was made."""

    def __init__(self, path):
        self.raw = open(path, "wb")
        self.zipped = gzip.GzipFile(filename="", mode="wb", fileobj=self.raw, mtime=EPOCH)
        self.archive = tarfile.open(fileobj=self.zipped, mode="w", format=tarfile.GNU_FORMAT)

    def __enter__(self):
        return self.archive

    def __exit__(self, *exc):
        self.archive.close()
        self.zipped.close()
        self.raw.close()


def chroot(root, *command, capture=False):
    """Run inside the build root with /dev available (compiler probes need /dev/null)."""
    args = ["unshare", "--mount", "--propagation", "private", "sh", "-c",
            'mount --rbind /dev "$1/dev" && exec chroot "$@"', "sh", str(root), *command]
    if capture:
        return subprocess.check_output(args, text=True)
    subprocess.run(args, check=True)


def modinfo(root, path):
    fields = {}
    for line in chroot(root, "modinfo", path, capture=True).splitlines():
        key, _, value = line.partition(":")
        fields.setdefault(key.strip(), []).append(value.strip())
    return fields


def main():
    if len(sys.argv) < 2 or not re.fullmatch(r"0|[1-9][0-9]{0,5}", sys.argv[1]):
        fail("usage: make-driver-plugins.py <set revision> [name ...]")
    if not os.environ.get("TITANOS"):
        fail("TITANOS must name the TitanOS checkout with the built image")
    if os.geteuid() != 0:
        fail("run in an isolated root/user namespace or with sudo")
    revision, only = sys.argv[1], set(sys.argv[2:])
    label = os.environ.get("SET_TAG", "test")
    os.chdir(REPO)
    global EPOCH
    EPOCH = epoch()
    os.environ["SOURCE_DATE_EPOCH"] = str(EPOCH)  # mksquashfs in make-plugin.sh
    spec = json.loads(Path("plugins/drivers/drivers.json").read_text())
    unknown = only - set(spec["plugins"])
    if unknown:
        fail("unknown plugins: " + ", ".join(sorted(unknown)))
    kernel, package_version = image_kernel(Path(os.environ.get("IMAGE", os.path.join(os.environ["TITANOS"], "build/mkosi.output"))))
    upstream = kernel.split("+")[0]                      # 6.12.113
    series = ".".join(upstream.split(".")[:2])           # 6.12
    work = Path("out/driver-build").resolve()
    output = Path("out/plugins").resolve()
    output.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)

    # The build root, with headers and sources of exactly this kernel.
    subprocess.run(["mkosi", "--directory", "plugins/drivers/build", "--output-directory", str(work),
                    "--cache-directory", str(work / "cache"), "--package-cache-directory", str(work / "packages"),
                    "--package", f"linux-headers-{kernel}={package_version}",
                    "--package", f"linux-source-{series}={package_version}", "--force", "build"], check=True)
    root = work / "root"
    for package in (f"linux-headers-{kernel}", f"linux-source-{series}"):
        installed = chroot(root, "dpkg-query", "-W", "-f=${Version}", package, capture=True).strip()
        if installed != package_version:
            fail(f"{package} {installed} does not match linux-image-{kernel} {package_version}")
    build = root / "build"
    shutil.rmtree(build, ignore_errors=True)
    build.mkdir()
    linux = build / f"linux-source-{series}"
    dirs = sorted({entry["dir"] for p in spec["plugins"].values() for entry in p.get("kernel", [])}
                  | {entry["include"] for p in spec["plugins"].values() for entry in p.get("kernel", []) if "include" in entry})
    chroot(root, "tar", "-C", "/build", "-xaf", f"/usr/src/linux-source-{series}.tar.xz",
           f"linux-source-{series}/Makefile", *(f"linux-source-{series}/{d}" for d in dirs))
    makefile = (linux / "Makefile").read_text()
    source_version = ".".join(re.search(rf"^{key} = (\d+)$", makefile, re.M)[1] for key in ("VERSION", "PATCHLEVEL", "SUBLEVEL"))
    if source_version != upstream:
        fail(f"linux-source {source_version} is not the kernel {upstream}")
    headers = f"/usr/src/linux-headers-{kernel}"
    cache = work / "downloads"

    built_plugins = []
    for name, plugin in spec["plugins"].items():
        if only and name not in only:
            continue
        # The catalog entries live in TitanOS; the image recommends drivers with them.
        catalog = json.loads((Path(os.environ["TITANOS"]) / "plugins/catalog" / f"{name}.json").read_text())
        stage = work / "stage" / name
        shutil.rmtree(stage, ignore_errors=True)
        modules_dir = stage / f"usr/lib/modules/{kernel}/updates/titanos-{name}"
        modules_dir.mkdir(parents=True)
        notices = stage / f"usr/share/titanos/{name}"
        notices.mkdir(parents=True)
        sources_path = work / f"{name}-sources.tar.gz"
        source_links = [f"https://snapshot.debian.org/package/linux/{package_version}/"]
        compiled = []                                        # (directory in the build root, its .ko files)
        with DeterministicTar(sources_path) as archive:
            for entry in plugin.get("kernel", []):
                target = build / name / Path(entry["dir"]).name
                shutil.rmtree(target, ignore_errors=True)
                shutil.copytree(linux / entry["dir"], target)
                archive.add(target, arcname=f"linux-source-{series}/{entry['dir']}", filter=normalized)
                flags = [f"{key}={value}" for key, value in entry["config"].items()]
                if "include" in entry:
                    archive.add(linux / entry["include"], arcname=f"linux-source-{series}/{entry['include']}", filter=normalized)
                    flags.append(f"ccflags-y=-I/build/linux-source-{series}/{entry['include']}")
                chroot(root, "make", "-C", headers, f"M=/{target.relative_to(root)}", *flags, "modules",
                       f"-j{os.environ.get('DRIVER_BUILD_JOBS', '2')}")
                compiled.append(target)
            if "external" in plugin:
                external = spec["external"][plugin["external"]]
                data = fetch(external["url"], external["sha256"], cache)
                target = build / name / plugin["external"]
                shutil.rmtree(target, ignore_errors=True)
                target.mkdir(parents=True)
                with tarfile.open(fileobj=io.BytesIO(data)) as upstream_archive:
                    members = {Path(m.name).relative_to(Path(m.name).parts[0]).as_posix(): m
                               for m in upstream_archive.getmembers() if len(Path(m.name).parts) > 1}
                    for wanted in plugin["files"] + external["notices"]:
                        member = members.get(wanted)
                        if member is None or not member.isfile():
                            fail(f"{wanted} missing in {external['url']}")
                        (target / wanted).write_bytes(upstream_archive.extractfile(member).read())
                (target / "Kbuild").write_text(f"obj-m := {' '.join(m + '.o' for m in plugin['built'])}\n")
                # The upstream Makefile derives the version from git; pin it to the commit.
                short = external["commit"][:12]
                chroot(root, "make", "-C", headers, f"M=/{target.relative_to(root)}",
                       f'ccflags-y=-DIT87_DRIVER_VERSION="\\"{short}\\""', "modules",
                       f"-j{os.environ.get('DRIVER_BUILD_JOBS', '2')}")
                # The files compiled, with their license and the Kbuild file; the
                # full upstream archive (datasheets and more) stays at the pinned commit.
                for file in sorted(target.iterdir()):
                    if file.name in [*plugin["files"], *external["notices"], "Kbuild"]:
                        archive.add(file, arcname=f"{plugin['external']}-{external['commit']}/{file.name}", filter=normalized)
                for notice in external["notices"]:
                    shutil.copyfile(target / notice, notices / notice)
                source_links = [f"{external['repository']}/tree/{external['commit']}", f"{name}-sources.tar.gz"]
                compiled.append(target)
            recipe = json.dumps({"kernel": kernel, "linux-image": package_version, "plugin": plugin}, indent=2).encode()
            info = normalized(tarfile.TarInfo("BUILD.json"))
            info.size = len(recipe)
            archive.addfile(info, io.BytesIO(recipe))
        if "external" not in plugin:
            source_links.append(f"{name}-sources.tar.gz")

        # Exactly the expected modules, for exactly this kernel.
        found = {ko.stem: ko for directory in compiled for ko in directory.rglob("*.ko")}
        if sorted(found) != sorted(plugin["built"]):
            fail(f"{name}: built {sorted(found)}, expected {sorted(plugin['built'])}")
        aliases = set()
        for module, path in sorted(found.items()):
            chroot(root, "strip", "--strip-debug", f"/{path.relative_to(root)}")
            fields = modinfo(root, f"/{path.relative_to(root)}")
            if fields.get("vermagic", [""])[0].split(" ")[0] != kernel:
                fail(f"{module}: vermagic {fields.get('vermagic')} is not {kernel}")
            aliases.update(fields.get("alias", []))
            shutil.copyfile(path, modules_dir / f"{module}.ko")
        rules = {rule["modalias"] for rule in catalog.get("hardware", [])}
        if rules != aliases:
            fail(f"{name}: $TITANOS/plugins/catalog/{name}.json hardware rules differ from the module aliases "
                 f"(missing {sorted(aliases - rules)}, extra {sorted(rules - aliases)})")

        firmware = spec.get("firmware", {})
        for path in plugin.get("firmware", []) + plugin.get("notices", []):
            pin = firmware["files"][path]
            data = fetch(f"{firmware['repository']}/-/raw/{firmware['commit']}/{path}", pin["sha256"], cache)
            if "install" in pin:
                target = stage / "usr/lib/firmware" / pin["install"]
            else:
                target = notices / Path(path).name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        if plugin.get("firmware"):
            source_links.append(f"{firmware['repository']}/-/tree/{firmware['tag']} (firmware, binary only)")
        if "root" in plugin:
            shutil.copytree(plugin["root"], stage, dirs_exist_ok=True)
            shutil.copytree(plugin["root"], notices / "integration-source", dirs_exist_ok=True)
        shutil.copyfile("LICENSE.md", notices / "TitanOS-LICENSE.md")
        shutil.copytree(root / "usr/share/common-licenses", stage / "usr/share/common-licenses", dirs_exist_ok=True)
        (notices / "SOURCES.txt").write_text(
            f"TitanOS plugin {name} ({label}) for kernel {kernel} (linux-image {package_version})\n\n"
            + "\n".join(source_links) + "\n")
        if "external" in plugin:
            pinned = spec["external"][plugin["external"]]["commit"][:12]
        else:
            pinned = f"{upstream} (Debian {package_version})"
        manifest = {"kernel": kernel, "modules": plugin["modules"], "services": plugin.get("services", []),
                    "upstream": {"version": pinned}, "sources": source_links}
        (stage / "plugin.json").write_text(json.dumps(manifest, indent=2) + "\n")
        subprocess.run(["chmod", "-R", "go-w", str(stage)], check=True)
        subprocess.run(["scripts/make-plugin.sh", name, f"{upstream}-{revision}", str(stage), str(output)], check=True)
        shutil.copyfile(sources_path, output / f"{name}-sources.tar.gz")
        with DeterministicTar(output / f"{name}-licenses.tar.gz") as archive:
            archive.add(notices, arcname=f"titanos/{name}", filter=normalized)
            archive.add(stage / "usr/share/common-licenses", arcname="common-licenses", filter=normalized)
        built_plugins.append(name)
    print(f"Built {', '.join(built_plugins)} ({label}) for kernel {kernel} (linux-image {package_version})")


if __name__ == "__main__":
    main()
