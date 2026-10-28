#!/usr/bin/env python3
"""Record the exact plugin packages and their unmodified license notices."""
import json
import sys
from pathlib import Path

stage, kernel, version = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
lock = json.loads(Path("plugins/nvidia/packages.lock.json").read_text())
notices = stage / "usr/share/titanos/nvidia"
sources = [f"TitanOS NVIDIA plugin for {version}, kernel {kernel}", "",
           "Open kernel modules: nvidia-kernel-sources.tar.gz accompanies this plugin.",
           f"https://github.com/NVIDIA/open-gpu-kernel-modules/tree/{lock['driver']}",
           f"https://github.com/NVIDIA/nvidia-modprobe/tree/{lock['driver']}",
           f"https://github.com/NVIDIA/nvidia-persistenced/tree/{lock['driver']}",
           f"https://github.com/NVIDIA/nvidia-container-toolkit/tree/v{lock['toolkit']}",
           f"https://github.com/NVIDIA/libnvidia-container/tree/v{lock['toolkit']}", "",
           "Proprietary driver libraries and GSP firmware retain NVIDIA's license.",
           "Their binary files are unmodified; the original agreements are in doc/*/copyright.", ""]
for package in lock["packages"]:
    notice = stage / "usr/share/doc" / package["name"] / "copyright"
    if not notice.is_file():
        raise ValueError("missing original license for " + package["name"])
    sources.extend([f"{package['name']} {package['version']}",
                    lock["repository"] + package["file"], "SHA256: " + package["sha256"], ""])
(notices / "SOURCES.txt").write_text("\n".join(sources))
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
(stage / "plugin.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
