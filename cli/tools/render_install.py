"""Fill install.sh's release lines with this release's wheels and constraints.txt (see RELEASING.md).

    python tools/render_install.py VERSION CLI_WHEEL ENGINE_WHEEL CONSTRAINTS OUT
"""
import hashlib
import re
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "install.sh"


def render(version, cli, engine, constraints, src=SRC):
    text = src.read_text()
    values = {"VERSION": version}
    for key, path in (("CLI", Path(cli)), ("ENGINE", Path(engine)), ("CONSTRAINTS", Path(constraints))):
        data = path.read_bytes()
        if key != "CONSTRAINTS":  # the constraints file keeps its name: install.sh fetches constraints.txt
            values[f"{key}_WHEEL"] = path.name
        values.update({f"{key}_SHA256": hashlib.sha256(data).hexdigest(), f"{key}_SIZE": str(len(data))})
    for key, value in values.items():
        text, n = re.subn(rf'(?m)^{key}=(""|0)$', f'{key}="{value}"' if not key.endswith("SIZE") else f"{key}={value}",
                          text)
        if n != 1:
            raise SystemExit(f"install.sh has no empty {key} line to fill")
    return text


if __name__ == "__main__":
    version, cli, engine, constraints, out = sys.argv[1:6]
    if Path(constraints).name != "constraints.txt":
        raise SystemExit("the constraints file must be named constraints.txt (its name on the release)")
    Path(out).write_text(render(version, cli, engine, constraints))
    Path(out).chmod(0o755)
