#!/bin/bash
# Build a separate sysext against the exact kernel of the already built image.
# Run as root (or with sudo). Never installs NVIDIA packages on the build host.
set -euo pipefail
export PATH="$PATH:/usr/sbin:/sbin"
cd "$(dirname "$0")/.."
version=${1:?usage: make-nvidia-plugin.sh <TitanOS version>}
[[ $version =~ ^[0-9]+\.[0-9]+\.[0-9]+(-[a-z0-9.]+)?$ ]]
[[ $(id -u) == 0 ]] || { echo "Run with sudo; only the disposable build root is changed" >&2; exit 1; }
kernel=${NVIDIA_KERNEL:-$(cat build/mkosi.output/kernel-version)}
[[ $kernel =~ ^[A-Za-z0-9][A-Za-z0-9.+_-]{0,100}$ ]]
revision=${NVIDIA_REVISION:-0}
[[ $revision =~ ^[0-9]+$ ]]
driver=$(python3 -c 'import json; print(json.load(open("plugins/nvidia/packages.lock.json"))["driver"])')
work=$(realpath -m out/nvidia-build)
packages=$(realpath -m out/nvidia-packages)
output=$(realpath -m out/plugins)
mkdir -p "$work" "$packages" "$output"
python3 scripts/fetch-nvidia.py plugins/nvidia/packages.lock.json "$packages"
rm -rf "$work/plugin"
mkdir -p "$work/plugin"
mkosi --directory plugins/nvidia/build --output-directory "$work" \
    --package-cache-directory "$packages/mkosi-cache" --cache-directory "$work/cache" \
    --package "linux-headers-$kernel" --force build
root=$work/root
stage=$work/plugin
python3 scripts/make-nvidia-sdk.py "$root" "$kernel" "$version" "$output"

while read -r file; do
    if [[ $file == nvidia-kernel-open-dkms_* ]]; then
        dpkg-deb -x "$packages/$file" "$root"
    else
        dpkg-deb -x "$packages/$file" "$stage"
    fi
done < <(python3 -c 'import json; print("\n".join(p["file"] for p in json.load(open("plugins/nvidia/packages.lock.json"))["packages"]))')

# Compile open sources inside Debian with its matching compiler and headers.
# No DKMS post-install script, modprobe, or driver installation runs on the host.
tar -C "$root/usr/src" -czf "$output/nvidia-kernel-sources.tar.gz" "nvidia-$driver"
# Debian splits generated headers (build) from shared source headers (source).
# A private mount namespace supplies /dev/null for compiler feature probes.
unshare --mount --propagation private sh -c 'mount --bind /dev "$1/dev"; exec chroot "$@"' sh \
    "$root" make -C "/usr/src/nvidia-$driver" -j"${NVIDIA_BUILD_JOBS:-2}" \
    modules KERNEL_UNAME="$kernel" SYSSRC="/lib/modules/$kernel/source" SYSOUT="/lib/modules/$kernel/build"
modules=$stage/usr/lib/modules/$kernel/updates/titanos-nvidia
mkdir -p "$modules"
for name in nvidia nvidia-uvm nvidia-modeset nvidia-drm; do
    module=$root/usr/src/nvidia-$driver/kernel-open/$name.ko
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

# Keep original runtime files and license texts byte-for-byte.
mkdir -p "$stage/usr/share/titanos/nvidia"
rm -rf "$stage/etc" "$stage/var"
cp -a plugins/nvidia/root/. "$stage/"
for tool in nvidia-smi nvidia-modprobe nvidia-ctk nvidia-cdi-hook; do
    test -x "$stage/usr/bin/$tool"
done
test -s "$stage/usr/lib/firmware/nvidia/$driver/gsp_tu10x.bin"
test -s "$stage/usr/lib/firmware/nvidia/$driver/gsp_ga10x.bin"
cp plugins/nvidia/packages.lock.json "$stage/usr/share/titanos/nvidia/"
cp LICENSE.md "$stage/usr/share/titanos/nvidia/TitanOS-LICENSE.md"
cp -a plugins/nvidia/root "$stage/usr/share/titanos/nvidia/integration-source"
# The original kernel sources accompany every binary plugin, not only a link.
cp -a "$root/usr/share/doc/nvidia-kernel-open-dkms" "$stage/usr/share/doc/"
cp -a "$root/usr/share/common-licenses" "$stage/usr/share/"
python3 scripts/nvidia-plugin-metadata.py "$stage" "$kernel" "$version"
chmod -R go-w "$stage"
plugin_version=$driver-titanos-$version
if [[ $revision != 0 ]]; then
    plugin_version=$plugin_version-r$revision
    python3 - "$stage/plugin.json" "$version" "$revision" <<'PYMETA'
import json,sys
from pathlib import Path
p=Path(sys.argv[1]); data=json.loads(p.read_text()); data.update(titanos=sys.argv[2],revision=int(sys.argv[3])); p.write_text(json.dumps(data,indent=2)+"\n")
PYMETA
fi
scripts/make-plugin.sh nvidia "$plugin_version" "$stage" "$output"
tar -C "$stage/usr/share" -czf "$output/nvidia-licenses.tar.gz" doc common-licenses titanos/nvidia
echo "Built NVIDIA $driver for TitanOS $version, kernel $kernel"
