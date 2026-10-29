#!/usr/bin/env python3
"""Fetch only the reviewed, checksum-pinned NVIDIA packages, without installing them."""
import hashlib
import json
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def extract(package, destination):
    """Unpack authenticated payloads without importing package ownership/SUID.

    TitanOS services already run with their required privileges. The data
    filter also keeps archive directory modes from disabling traversal (the
    toolkit archive has a 0644 root) and rejects paths outside the build tree.
    """
    destination.mkdir(parents=True, exist_ok=True)
    with subprocess.Popen(["dpkg-deb", "--fsys-tarfile", str(package)], stdout=subprocess.PIPE) as process:
        try:
            with tarfile.open(fileobj=process.stdout, mode="r|") as archive:
                archive.extractall(destination, filter="data")
        finally:
            process.stdout.close()
        if process.wait() != 0:
            raise ValueError("NVIDIA package extraction failed: " + package.name)


def fetch(lock_path, destination):
    lock = json.loads(lock_path.read_text())
    destination.mkdir(parents=True, exist_ok=True)
    for package in lock["packages"]:
        target = destination / package["file"]
        if not target.exists() or digest(target) != package["sha256"]:
            partial = target.with_suffix(".part")
            print("Fetching", package["name"], package["version"], flush=True)
            with urllib.request.urlopen(lock["repository"] + package["file"], timeout=120) as response, partial.open("wb") as output:
                while block := response.read(1 << 20):
                    output.write(block)
            if digest(partial) != package["sha256"]:
                partial.unlink()
                raise ValueError("NVIDIA package checksum mismatch: " + package["name"])
            partial.replace(target)
        actual = subprocess.check_output(["dpkg-deb", "-f", str(target), "Package", "Version"], text=True)
        if f"Package: {package['name']}\n" not in actual or f"Version: {package['version']}\n" not in actual:
            raise ValueError("NVIDIA package identity mismatch")
    return lock


if __name__ == "__main__":
    fetch(Path(sys.argv[1]), Path(sys.argv[2]))
