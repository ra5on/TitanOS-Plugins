#!/usr/bin/env python3
"""Pin an external driver source of plugins/drivers/drivers.json to a commit.

  pin-driver-source.py <external> <commit> [--date YYYY-MM-DD]
  pin-driver-source.py --check        list the sources that are not pinned yet

Downloads <repository>/archive/<commit>.tar.gz once, checks that it holds
what the build takes from it (the "dir" with a Makefile or Kbuild, and the
listed notices) and writes url, commit, date and sha256. Review the diff and
the upstream changes before committing: the build trusts exactly this hash.
make-driver-plugins.py refuses a source without a complete pin.
"""
import argparse
import datetime
import hashlib
import io
import json
import re
import sys
import tarfile
import urllib.request
from pathlib import Path

DRIVERS = Path(__file__).resolve().parents[1] / "plugins/drivers/drivers.json"


def pinned(external):
    return bool(re.fullmatch(r"[0-9a-f]{40}", external.get("commit", "")) and
                re.fullmatch(r"[0-9a-f]{64}", external.get("sha256", "")) and
                external["commit"] in external.get("url", ""))


def check_archive(data, external):
    """The paths the build needs, relative to the archive's top directory."""
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        names = {Path(m.name).relative_to(Path(m.name).parts[0]).as_posix()
                 for m in archive.getmembers() if m.isfile() and len(Path(m.name).parts) > 1}
    missing = [n for n in external.get("notices", []) if n not in names]
    if "dir" in external:
        prefix = external["dir"].strip("/") + "/"
        if not {prefix + "Makefile", prefix + "Kbuild"} & names:
            missing.append(prefix + "Makefile")
    if missing:
        raise SystemExit("archive lacks " + ", ".join(missing))
    licenses = sorted(n for n in names if re.search(r"(^|/)(COPYING|LICEN[CS]E)[^/]*$", n))
    return licenses


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("external", nargs="?")
    parser.add_argument("commit", nargs="?")
    parser.add_argument("--date", help="commit date, default today")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    text = DRIVERS.read_text()
    spec = json.loads(text)
    if args.check:
        open_pins = [name for name, external in spec["external"].items() if not pinned(external)]
        for name in open_pins:
            print(f"{name}: not pinned ({spec['external'][name]['repository']})")
        return 1 if open_pins else 0
    if not args.external or not args.commit:
        parser.error("external and commit are needed")
    external = spec["external"].get(args.external)
    if external is None:
        raise SystemExit(f"unknown external source {args.external}")
    if not re.fullmatch(r"[0-9a-f]{40}", args.commit):
        raise SystemExit("commit must be the full 40-digit hash")
    url = f"{external['repository']}/archive/{args.commit}.tar.gz"
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "TitanOS build"}), timeout=120) as response:
        data = response.read((64 << 20) + 1)
    if len(data) > 64 << 20:
        raise SystemExit("archive larger than 64 MiB")
    licenses = check_archive(data, external)
    date = args.date or datetime.date.today().isoformat()
    # Keep the file's layout: only these four values change.
    for key, value in (("url", url), ("commit", args.commit), ("date", date), ("sha256", hashlib.sha256(data).hexdigest())):
        external[key] = value
    block = re.search(r'\n    "%s": \{.*?\n    \}' % re.escape(args.external), text, re.S)
    if not block:
        raise SystemExit("drivers.json layout not recognized")
    updated = block[0]
    for key in ("url", "commit", "date", "sha256"):
        updated = re.sub(r'("%s": )"[^"]*"' % key, lambda m, v=external[key]: m[1] + json.dumps(v), updated, count=1)
    text = text[:block.start()] + updated + text[block.end():]
    if json.loads(text)["external"][args.external] != external:
        raise SystemExit("could not update drivers.json")
    DRIVERS.write_text(text)
    print(f"{args.external}: {args.commit} sha256 {external['sha256']}")
    print("license files in the archive:", ", ".join(licenses) or "none (check the source headers)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
