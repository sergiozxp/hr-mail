"""Download the pinned Mercury and Pat releases into bin/ (sha256-checked).

Usage: python tools/fetch_bins.py [--dest bin]
"""

import argparse
import hashlib
import io
import json
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def fetch(name: str, spec: dict, dest: Path) -> None:
    print(f"{name} {spec['version']}: {spec['url']}")
    with urllib.request.urlopen(spec["url"], timeout=120) as resp:
        data = resp.read()
    digest = hashlib.sha256(data).hexdigest()
    if digest != spec["sha256"]:
        sys.exit(f"{name}: sha256 mismatch\n  expected {spec['sha256']}\n  got      {digest}")

    out = dest / name
    out.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        # Flatten: keep the files of the folder that holds the main exe.
        exe_entry = next(n for n in zf.namelist() if n.endswith("/" + spec["exe"]) or n == spec["exe"])
        prefix = exe_entry[: -len(spec["exe"])]
        for entry in zf.namelist():
            if not entry.startswith(prefix) or entry.endswith("/"):
                continue
            rel = entry[len(prefix):]
            if "/" in rel or rel in spec["exclude"]:
                continue
            (out / rel).write_bytes(zf.read(entry))
            print(f"  {name}/{rel}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dest", default=str(ROOT / "bin"))
    args = parser.parse_args()
    specs = json.loads((ROOT / "bins.json").read_text(encoding="utf-8"))
    for name, spec in specs.items():
        fetch(name, spec, Path(args.dest))


if __name__ == "__main__":
    main()
