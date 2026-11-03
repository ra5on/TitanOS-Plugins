#!/bin/bash
# Build a separate sysext against the exact kernel of the already built image
# ($TITANOS/build/mkosi.output). The plugin is version <driver>-<set revision>;
# NVIDIA_REVISION marks an independent driver update of a kernel set.
# NVIDIA_PLUGIN=nvidia-legacy builds the proprietary 580 driver for Maxwell,
# Pascal and Volta instead of the open modules (plugins/nvidia-legacy): same
# runtime and CDI service, no GSP firmware, no build environment for the NAS.
# Run as root (or with sudo). Never installs NVIDIA packages on the build host.
set -euo pipefail
export PATH="$PATH:/usr/sbin:/sbin"
cd "$(dirname "$0")/.."
set_revision=${1:?usage: make-nvidia-plugin.sh <set revision>}
[[ $set_revision =~ ^(0|[1-9][0-9]{0,5})$ ]]
titanos=${TITANOS:?TITANOS must name the TitanOS checkout with the built image}
label=${SET_TAG:-test}
[[ $(id -u) == 0 ]] || { echo "Run with sudo; only the disposable build root is changed" >&2; exit 1; }
kernel=${NVIDIA_KERNEL:-$(cat "$titanos/build/mkosi.output/kernel-version")}
[[ $kernel =~ ^[A-Za-z0-9][A-Za-z0-9.+_-]{0,100}$ ]]
revision=${NVIDIA_REVISION:-0}
[[ $revision =~ ^[0-9]+$ ]]
plugin=${NVIDIA_PLUGIN:-nvidia}
case $plugin in
    nvidia) dkms=nvidia-kernel-open-dkms sources=nvidia-kernel-sources.tar.gz ;;
    nvidia-legacy) dkms=nvidia-kernel-dkms sources=nvidia-legacy-sources.tar.gz
        [[ $revision == 0 ]] || { echo "driver updates exist only for the open NVIDIA plugin" >&2; exit 1; } ;;
    *) echo "unknown NVIDIA_PLUGIN $plugin" >&2; exit 1 ;;
esac
lock=plugins/$plugin/packages.lock.json
driver=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["driver"])' "$lock")
work=$(realpath -m "out/$plugin-build")
packages=$(realpath -m "out/$plugin-packages")
output=$(realpath -m out/plugins)
mkdir -p "$work" "$packages" "$output"
python3 scripts/fetch-nvidia.py "$lock" "$packages"
rm -rf "$work/plugin"
mkdir -p "$work/plugin"
mkosi --directory plugins/nvidia/build --output-directory "$work" \
    --package-cache-directory "$packages/mkosi-cache" --cache-directory "$work/cache" \
    --package "linux-headers-$kernel" --force build
root=$work/root
stage=$work/plugin
if [[ $plugin == nvidia ]]; then
    # Only the open modules can be rebuilt on the NAS ("Prepare driver").
    python3 scripts/make-nvidia-sdk.py "$root" "$kernel" "$label" "$output"
fi

while read -r file; do
    if [[ $file == "$dkms"_* ]]; then
        dpkg-deb -x "$packages/$file" "$root"
    else
        dpkg-deb -x "$packages/$file" "$stage"
    fi
done < <(python3 -c 'import json,sys; print("\n".join(p["file"] for p in json.load(open(sys.argv[1]))["packages"]))' "$lock")

# Compile the sources inside Debian with its matching compiler and headers.
# No DKMS post-install script, modprobe, or driver installation runs on the host.
test -d "$root/usr/src/nvidia-$driver" || { echo "$dkms brought no /usr/src/nvidia-$driver" >&2; ls "$root/usr/src" >&2; exit 1; }
tar -C "$root/usr/src" -czf "$output/$sources" "nvidia-$driver"
# Debian splits generated headers (build) from shared source headers (source).
# A private mount namespace supplies /dev/null for compiler feature probes,
# and its own /proc: objtool of Linux 7.x reads /proc while linking.
unshare --mount --pid --fork --propagation private sh -c 'mount --bind /dev "$1/dev"; mkdir -p "$1/proc"; mount -t proc proc "$1/proc"; exec chroot "$@"' sh \
    "$root" make -C "/usr/src/nvidia-$driver" -j"${NVIDIA_BUILD_JOBS:-2}" \
    modules KERNEL_UNAME="$kernel" SYSSRC="/lib/modules/$kernel/source" SYSOUT="/lib/modules/$kernel/build"
modules=$stage/usr/lib/modules/$kernel/updates/titanos-$plugin
mkdir -p "$modules"
for name in nvidia nvidia-uvm nvidia-modeset nvidia-drm; do
    # Open modules land in kernel-open/, the proprietary ones where its Kbuild puts them.
    mapfile -t found < <(find "$root/usr/src/nvidia-$driver" -name "$name.ko" -type f)
    [[ ${#found[@]} == 1 ]] || { echo "expected one $name.ko, found ${#found[@]}" >&2; exit 1; }
    module=${found[0]}
    if [[ $plugin == nvidia ]]; then test "$module" = "$root/usr/src/nvidia-$driver/kernel-open/$name.ko"; fi
    test "$(modinfo -F vermagic "$module" | cut -d' ' -f1)" = "$kernel"
    install -m 0644 "$module" "$modules/"
done

# Some upstream packages still use /lib. sysext only merges /usr and /opt;
# normalize the layout without modifying the original binaries or firmware.
if [[ -d $stage/lib ]]; then
    cp -a "$stage/lib/." "$stage/usr/lib/"
    rm -rf "$stage/lib"
fi
# TitanOS controls the CDI lifecycle. Upstream's automatic refresh service
# would create a second specification for the same devices on udev events.
rm -rf "$stage/usr/lib/systemd/system/nvidia-cdi-refresh.service" \
    "$stage/usr/lib/systemd/system/nvidia-cdi-refresh.service.d" \
    "$stage/usr/lib/systemd/system/nvidia-cdi-refresh.path" \
    "$stage/usr/lib/udev/rules.d/99-nvidia-cdi-refresh.rules"

# Keep original runtime files and license texts byte-for-byte. Both NVIDIA
# plugins share the runtime and titanos-nvidia.service (TitanOS restarts it
# to renew the CDI devices); they never run together (manifest "conflicts").
notices=$stage/usr/share/titanos/$plugin
mkdir -p "$notices"
rm -rf "$stage/etc" "$stage/var"
cp -a plugins/nvidia/root/. "$stage/"
for tool in nvidia-smi nvidia-modprobe nvidia-ctk nvidia-cdi-hook; do
    test -x "$stage/usr/bin/$tool"
done
if [[ $plugin == nvidia ]]; then
    test -s "$stage/usr/lib/firmware/nvidia/$driver/gsp_tu10x.bin"
    test -s "$stage/usr/lib/firmware/nvidia/$driver/gsp_ga10x.bin"
fi
cp "$lock" "$notices/"
cp LICENSE.md "$notices/TitanOS-LICENSE.md"
cp -a plugins/nvidia/root "$notices/integration-source"
# The original kernel sources accompany every binary plugin, not only a link.
cp -a "$root/usr/share/doc/$dkms" "$stage/usr/share/doc/"
cp -a "$root/usr/share/common-licenses" "$stage/usr/share/"
python3 scripts/nvidia-plugin-metadata.py "$stage" "$kernel" "$label" "$plugin"
chmod -R go-w "$stage"
plugin_version=$driver-$set_revision
if [[ $revision != 0 ]]; then
    # A driver update names no TitanOS release: it fits every base with this kernel.
    plugin_version=$plugin_version-r$revision
    python3 - "$stage/plugin.json" "$revision" <<'PYMETA'
import json,sys
from pathlib import Path
p=Path(sys.argv[1]); data=json.loads(p.read_text()); data.update(revision=int(sys.argv[2])); p.write_text(json.dumps(data,indent=2)+"\n")
PYMETA
fi
scripts/make-plugin.sh "$plugin" "$plugin_version" "$stage" "$output"
tar -C "$stage/usr/share" -czf "$output/$plugin-licenses.tar.gz" doc common-licenses "titanos/$plugin"
echo "Built $plugin $plugin_version for kernel $kernel"
