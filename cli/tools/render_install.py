"""Fill install.sh's release lines with this release's wheels (run by .github/workflows/release.yml).

    python tools/render_install.py VERSION CLI_WHEEL ENGINE_WHEEL OUT
"""
import hashlib
import re
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "install.sh"


def render(version, cli, engine, src=SRC):
    text = src.read_text()
    values = {"VERSION": version}
    for key, wheel in (("CLI", Path(cli)), ("ENGINE", Path(engine))):
        data = wheel.read_bytes()
        values.update({f"{key}_WHEEL": wheel.name, f"{key}_SHA256": hashlib.sha256(data).hexdigest(),
                       f"{key}_SIZE": str(len(data))})
    for key, value in values.items():
        text, n = re.subn(rf'(?m)^{key}=(""|0)$', f'{key}="{value}"' if not key.endswith("SIZE") else f"{key}={value}",
                          text)
        if n != 1:
            raise SystemExit(f"install.sh has no empty {key} line to fill")
    return text


if __name__ == "__main__":
    version, cli, engine, out = sys.argv[1:5]
    Path(out).write_text(render(version, cli, engine))
    Path(out).chmod(0o755)
