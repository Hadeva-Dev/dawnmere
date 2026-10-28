"""Write the engine's models.json for a models release (spec 10.2) from a folder laid out as <name>/<file>.

    python tools/make_models_json.py MODELS_DIR models-2026-10-28 > models.json

Every file becomes an asset of the engine release `models-<date>`, named <name>-<file> (release assets are flat);
models.json records each one's URL, size and sha256. The CLI downloads them into DATA_DIR/models/<name>/<file> and
refuses any file whose checksum differs.
"""
import hashlib
import json
import sys
from pathlib import Path

REPO = "Hadeva-Dev/lflabs-memory-engine"
NAMES = ("embed", "rerank", "sense")


def manifest(folder, release):
    out = {"release": release, "models": {}}
    for name in NAMES:
        d = Path(folder) / name
        if not d.is_dir():
            continue
        files = []
        for f in sorted(p for p in d.iterdir() if p.is_file() and not p.name.startswith(".")):
            h = hashlib.sha256(f.read_bytes()).hexdigest()
            files.append({"file": f.name, "url": f"https://github.com/{REPO}/releases/download/{release}/{name}-{f.name}",
                          "size": f.stat().st_size, "sha256": h})
        out["models"][name] = files
    return out


if __name__ == "__main__":
    json.dump(manifest(sys.argv[1], sys.argv[2]), sys.stdout, indent=2)
    print()
