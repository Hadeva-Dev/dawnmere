"""The product name is one token: it appears only where the brand is allowed to live."""
import re
import subprocess
import sys
from pathlib import Path

import pytest

CLI = Path(__file__).resolve().parents[1]
ALLOWED = {
    "src/lflabs_memory_cli/brand.py",  # the token itself
    "pyproject.toml",                   # the console script's name
}


def test_product_name_only_in_brand_files():
    pattern = re.compile(r"dawnmere", re.I)
    offenders = []
    for path in [*CLI.glob("src/**/*.py"), *CLI.glob("tools/*.py"), CLI / "pyproject.toml"]:
        rel = path.relative_to(CLI).as_posix()
        if rel not in ALLOWED and pattern.search(path.read_text()):
            offenders.append(rel)
    assert offenders == []


def test_wordmark_art_is_current():
    pytest.importorskip("PIL")
    r = subprocess.run([sys.executable, str(CLI / "tools" / "make_wordmark.py"), "--check"])
    assert r.returncode == 0, "banner_art.py is stale: run tools/make_wordmark.py"
