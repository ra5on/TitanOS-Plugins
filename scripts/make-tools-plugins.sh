#!/bin/bash
# Builds the kernel-independent plugins: Intel GPU Tools in an isolated Debian
# root (never on the host; only libraries missing from the TitanOS image in
# $TITANOS/build/mkosi.output are added), Coral USB, Tailscale and NetBird.
# Each plugin is version <upstream>-<set revision>.
set -euo pipefail
export PATH="$PATH:/usr/sbin:/sbin"
cd "$(dirname "$0")/.."
revision=${1:?usage: make-tools-plugins.sh <set revision>}
[[ $revision =~ ^(0|[1-9][0-9]{0,5})$ ]]
titanos=${TITANOS:?TITANOS must name the TitanOS checkout with the built image}
[[ $(id -u) == 0 ]] || { echo 'Run in an isolated root/user namespace or with sudo' >&2; exit 1; }
work=$(realpath -m out/tools-build)
mkdir -p "$work" out/plugins
mkosi --directory plugins/intel-gpu-tools/build --output-directory "$work" \
    --cache-directory "$work/cache" --package-cache-directory "$work/packages" --force build
python3 scripts/tools-plugin-stage.py "$work/root" "$titanos/build/mkosi.output/rootfs" "$work/stage" "$revision"
chmod -R go-w "$work/stage"
upstream=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["upstream"]["version"])' "$work/stage/plugin.json")
scripts/make-plugin.sh intel-gpu-tools "$upstream-$revision" "$work/stage" out/plugins
tar -C "$work/stage/usr/share" -czf out/plugins/intel-gpu-tools-licenses.tar.gz doc common-licenses titanos/intel-gpu-tools
rm -rf "$work/coral"
cp -a plugins/coral/root "$work/coral"
mkdir -p "$work/coral/usr/share/titanos/coral"
cp LICENSE.md "$work/coral/usr/share/titanos/coral/"
chmod -R go-w "$work/coral"
scripts/make-plugin.sh coral-usb "$(cat plugins/coral/version)-$revision" "$work/coral" out/plugins
tar -C "$work/coral/usr/share" -czf out/plugins/coral-usb-licenses.tar.gz titanos/coral

python3 scripts/make-tailscale-plugin.py "$revision"
python3 scripts/make-netbird-plugin.py "$revision"
