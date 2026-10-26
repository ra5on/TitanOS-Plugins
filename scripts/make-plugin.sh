#!/bin/sh
# Packs a folder into a TitanOS plugin: a systemd-sysext image and its
# manifest.
#
# Usage: scripts/make-plugin.sh <name> <version> <folder> [output folder]
#
# <folder> holds what the plugin adds to the system, as it lies below "/":
# usr/bin/…, usr/lib/modules/<kernel>/…, usr/lib/systemd/system/…. Only
# /usr (and /opt) can be extended. A file <folder>/plugin.json may carry
# more for the manifest: title, description, contains, kernel, modules,
# services.
#
# The result is <name>.raw and <name>.plugin.json. Put both into a share
# of the NAS; the plugin then shows up under "Plugins". To make it count as
# official, sign the manifest with a key the image trusts:
#   minisign -S -s titanos-plugins.key -m <name>.plugin.json
# and put the .minisig next to it.
set -eu

[ $# -ge 3 ] || { sed -n '2,17p' "$0" | sed 's/^# \{0,1\}//'; exit 2; }
name=$1 version=$2 source=$3 out=${4:-.}

case $name in
    *[!a-z0-9-]* | -* | "") echo "the name may only hold a-z, 0-9 and -" >&2; exit 2 ;;
esac
[ -d "$source/usr" ] || [ -d "$source/opt" ] || { echo "$source has neither usr/ nor opt/" >&2; exit 2; }

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
cp -a "$source/." "$work/root"
rm -f "$work/root/plugin.json"

# systemd only lays an extension over a system it is meant for. Which
# kernel a plugin fits is checked by TitanOS from the manifest.
mkdir -p "$work/root/usr/lib/extension-release.d"
printf 'ID=titanos\nSYSEXT_LEVEL=1\n' > "$work/root/usr/lib/extension-release.d/extension-release.$name"

extra='{}'
[ -f "$source/plugin.json" ] && extra=$(cat "$source/plugin.json")

# Kernel modules only load into the kernel they were built for. A plugin
# that carries modules has to name that kernel, and only that one.
python3 - "$work/root/usr/lib/modules" "$extra" <<'PY'
import json, os, sys
modules, extra = sys.argv[1:3]
if os.path.isdir(modules):
    kernels = sorted(os.listdir(modules))
    kernel = json.loads(extra).get("kernel", "")
    if not kernel:
        sys.exit("the plugin carries kernel modules but plugin.json names no kernel")
    if kernels != [kernel]:
        sys.exit(f"modules for {', '.join(kernels) or 'no kernel'}, but plugin.json names {kernel}")
PY

mkdir -p "$out"
rm -f "$out/$name.raw"
mksquashfs "$work/root" "$out/$name.raw" -comp zstd -all-root -noappend -quiet -processors "${SQUASHFS_PROCESSORS:-2}"

python3 - "$name" "$version" "$out/$name.raw" "$extra" > "$out/$name.plugin.json" <<'PY'
import hashlib, json, os, sys
name, version, image, extra = sys.argv[1:5]
manifest = json.loads(extra)
digest = hashlib.sha256()
with open(image, "rb") as f:
    for block in iter(lambda: f.read(1 << 20), b""):
        digest.update(block)
manifest.update(name=name, version=version, sha256=digest.hexdigest(), size=os.path.getsize(image))
json.dump(manifest, sys.stdout, ensure_ascii=False, indent=2)
print()
PY
echo "$out/$name.raw ($(du -h "$out/$name.raw" | cut -f1)) and $out/$name.plugin.json"
