#!/usr/bin/env python3
"""Record the exact plugin packages and their unmodified license notices.

  nvidia-plugin-metadata.py <stage> <kernel> <set tag> [nvidia|nvidia-legacy]
"""
import json
import sys
from pathlib import Path

stage, kernel, version = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
plugin = sys.argv[4] if len(sys.argv) > 4 else "nvidia"
if plugin not in ("nvidia", "nvidia-legacy"):
    raise SystemExit("unknown NVIDIA plugin " + plugin)
lock = json.loads(Path(f"plugins/{plugin}/packages.lock.json").read_text())
notices = stage / "usr/share/titanos" / plugin
if plugin == "nvidia":
    sources = [f"TitanOS NVIDIA plugin for {version}, kernel {kernel}", "",
               "Open kernel modules: nvidia-kernel-sources.tar.gz accompanies this plugin.",
               f"https://github.com/NVIDIA/open-gpu-kernel-modules/tree/{lock['driver']}"]
else:
    sources = [f"TitanOS NVIDIA legacy plugin for {version}, kernel {kernel}", "",
               "Proprietary kernel module (580 branch): nvidia-legacy-sources.tar.gz holds exactly what was",
               "compiled, the kernel interface sources and NVIDIA's binary core as shipped in nvidia-kernel-dkms."]
sources += [f"https://github.com/NVIDIA/nvidia-modprobe/tree/{lock['driver']}",
            f"https://github.com/NVIDIA/nvidia-persistenced/tree/{lock['driver']}",
            f"https://github.com/NVIDIA/nvidia-container-toolkit/tree/v{lock['toolkit']}",
            f"https://github.com/NVIDIA/libnvidia-container/tree/v{lock['toolkit']}", "",
            "Proprietary driver libraries" + (" and GSP firmware" if plugin == "nvidia" else "") + " retain NVIDIA's license.",
            "Their binary files are unmodified; the original agreements are in doc/*/copyright.", ""]
for package in lock["packages"]:
    notice = stage / "usr/share/doc" / package["name"] / "copyright"
    if not notice.is_file():
        raise ValueError("missing original license for " + package["name"])
    sources.extend([f"{package['name']} {package['version']}",
                    lock["repository"] + package["file"], "SHA256: " + package["sha256"], ""])
(notices / "SOURCES.txt").write_text("\n".join(sources))
if plugin == "nvidia":
    manifest = {
        "title": "NVIDIA",
        "driver": lock["driver"],
        "toolkit": lock["toolkit"],
        "description": {
            "de": "Offene NVIDIA-Kernelmodule für Turing und neuer, CUDA, NVENC/NVDEC und GPU-Container. Echte Hardwaretests stehen noch aus.",
            "en": "Open NVIDIA kernel modules for Turing and newer, CUDA, NVENC/NVDEC and GPU containers. Physical hardware testing is still pending."
        },
        "kernel": kernel,
        "upstream": {"version": lock["driver"]},
        "contains": {
            "de": ["Offene Kernelmodule (MIT/GPL-2.0)", "CUDA-, NVENC-/NVDEC-Bibliotheken und GSP-Firmware (NVIDIA-Lizenz)", "NVIDIA Container Toolkit (Apache-2.0), Docker via CDI", "Originale Lizenztexte und passende Kernelquellen als Release-Dateien"],
            "en": ["Open kernel modules (MIT/GPL-2.0)", "CUDA, NVENC/NVDEC libraries and GSP firmware (NVIDIA license)", "NVIDIA Container Toolkit (Apache-2.0), Docker via CDI", "Original license notices and matching kernel sources as release assets"]
        },
        "modules": ["nvidia", "nvidia_uvm"],
        "services": ["titanos-nvidia.service"]
    }
else:
    manifest = {
        "title": "NVIDIA (ältere Karten)",
        "driver": lock["driver"],
        "toolkit": lock["toolkit"],
        "description": {
            "de": "Proprietärer NVIDIA-Treiber der Reihe 580 für Maxwell, Pascal und Volta (z. B. GTX 9xx, GTX 10xx, Titan V): CUDA, NVENC/NVDEC und GPU-Container. Echte Hardwaretests stehen noch aus.",
            "en": "Proprietary NVIDIA driver of the 580 branch for Maxwell, Pascal and Volta (e.g. GTX 9xx, GTX 10xx, Titan V): CUDA, NVENC/NVDEC and GPU containers. Physical hardware testing is still pending."
        },
        "kernel": kernel,
        "upstream": {"version": lock["driver"]},
        "contains": {
            "de": ["Proprietäres Kernelmodul der Reihe 580 (NVIDIA-Lizenz, Schnittstelle zum Kernel offen)", "CUDA-, NVENC-/NVDEC-Bibliotheken (NVIDIA-Lizenz)", "NVIDIA Container Toolkit (Apache-2.0), Docker via CDI", "Originale Lizenztexte und die übersetzten Modulquellen als Release-Dateien"],
            "en": ["Proprietary kernel module of the 580 branch (NVIDIA license, open kernel interface)", "CUDA, NVENC/NVDEC libraries (NVIDIA license)", "NVIDIA Container Toolkit (Apache-2.0), Docker via CDI", "Original license notices and the compiled module sources as release assets"]
        },
        "modules": ["nvidia", "nvidia_uvm"],
        "services": ["titanos-nvidia.service"],
        # Both bring a module called nvidia: TitanOS never enables them together.
        "conflicts": ["nvidia"],
        "sources": [f"https://developer.download.nvidia.com/compute/cuda/repos/debian13/x86_64/{p['file']}"
                    for p in lock["packages"] if p["name"] == "nvidia-kernel-dkms"] + ["nvidia-legacy-sources.tar.gz"]
    }
(stage / "plugin.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
