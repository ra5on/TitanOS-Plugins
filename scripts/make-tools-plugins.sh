#!/bin/bash
# Builds optional userspace tools in an isolated Debian root, never on the host.
set -euo pipefail
export PATH="$PATH:/usr/sbin:/sbin"
cd "$(dirname "$0")/.."
version=${1:?usage: make-tools-plugins.sh <TitanOS version>}
[[ $version =~ ^[0-9]+\.[0-9]+\.[0-9]+(-[a-z0-9.]+)?$ ]]
[[ $(id -u) == 0 ]] || { echo 'Run in an isolated root/user namespace or with sudo' >&2; exit 1; }
work=$(realpath -m out/tools-build)
mkdir -p "$work" out/plugins
mkosi --directory plugins/intel-gpu-tools/build --output-directory "$work" \
    --cache-directory "$work/cache" --package-cache-directory "$work/packages" --force build
python3 scripts/tools-plugin-stage.py "$work/root" build/mkosi.output/rootfs "$work/stage" "$version"
chmod -R go-w "$work/stage"
scripts/make-plugin.sh intel-gpu-tools "$version" "$work/stage" out/plugins
tar -C "$work/stage/usr/share" -czf out/plugins/intel-gpu-tools-licenses.tar.gz doc common-licenses titanos/intel-gpu-tools
rm -rf "$work/coral"
cp -a plugins/coral/root "$work/coral"
mkdir -p "$work/coral/usr/share/titanos/coral"
cp LICENSE.md "$work/coral/usr/share/titanos/coral/"
chmod -R go-w "$work/coral"
scripts/make-plugin.sh coral-usb "$version" "$work/coral" out/plugins
tar -C "$work/coral/usr/share" -czf out/plugins/coral-usb-licenses.tar.gz titanos/coral
