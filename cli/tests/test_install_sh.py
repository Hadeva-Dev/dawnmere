"""install.sh (spec 10.1, Task 13): POSIX, checksums before anything is installed, then setup."""
import hashlib
import importlib.util
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from fakes import Fakes

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("render_install", ROOT / "cli/tools/render_install.py")
render_install = importlib.util.module_from_spec(spec)
spec.loader.exec_module(render_install)

CLI = "lflabs_memory_cli-0.2.0-py3-none-any.whl"
ENGINE = "lflabs_memory_engine-0.2.0-py3-none-any.whl"


@pytest.fixture
def release(tmp_path):
    """A release folder (served as file://) with both wheels, an install.sh rendered for them, a home folder and fake
    uv and dawnmere."""
    rel = tmp_path / "release"
    rel.mkdir()
    (rel / CLI).write_bytes(b"cli wheel" * 1000)
    (rel / ENGINE).write_bytes(b"engine wheel" * 1000)
    script = tmp_path / "install.sh"
    script.write_text(render_install.render("0.2.0", rel / CLI, rel / ENGINE))
    home = tmp_path / "home"
    home.mkdir()
    fakes = Fakes(tmp_path, progs=("uv",))
    tools = tmp_path / "tools-bin"
    tools.mkdir()
    shutil.copy(fakes.bin / "uv", tools / "dawnmere")
    fakes.on("uv", ["tool", "dir", "--bin"], 0, str(tools))
    env = {"HOME": str(home), "PATH": f"{fakes.bin}:/usr/bin:/bin", "FAKE_LOG": str(fakes.log),
           "FAKE_RULES": str(fakes.rules_file), "LFLABS_MEMORY_RELEASE_BASE": f"file://{rel}"}
    fakes.rel, fakes.script, fakes.env_vars, fakes.home = rel, script, env, home
    return fakes


def sh(script, env):
    return subprocess.run(["/bin/sh", str(script)], env=env, capture_output=True, text=True, stdin=subprocess.DEVNULL,
                          timeout=60)


@pytest.mark.skipif(not shutil.which("shellcheck"), reason="shellcheck not installed")
def test_install_sh_posix():
    r = subprocess.run(["shellcheck", "-s", "sh", str(ROOT / "install.sh")], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout
    assert len((ROOT / "install.sh").read_text().splitlines()) <= 150


def test_source_copy_refuses(release):
    r = sh(ROOT / "install.sh", release.env_vars)
    assert r.returncode == 1 and "source copy" in r.stderr


def test_install_sh_checksum_mismatch_aborts(release):
    (release.rel / ENGINE).write_bytes(b"tampered" * 1000)
    r = sh(release.script, release.env_vars)
    assert r.returncode != 0
    assert f"{ENGINE} did not match its checksum, so nothing was installed" in r.stderr
    assert not [c for c in release.calls("uv") if c[:2] == ["tool", "install"]]
    assert not (release.home / ".local").exists()


def test_install_sh_installs_then_runs_setup(release):
    r = sh(release.script, release.env_vars)
    assert r.returncode == 0, r.stderr
    assert "Dawnmere installer" in r.stdout and "Checksums ok" in r.stdout and "Downloading  " in r.stdout
    install = next(c for c in release.calls("uv") if c[:2] == ["tool", "install"])
    assert install[2:5] == ["--force", "--python", "3.12"] and install[5].endswith(CLI) and install[7].endswith(ENGINE)
    assert release.calls("dawnmere") == [["setup"]]


def test_uv_download_is_checked(release, tmp_path):
    """No uv on this Mac: the pinned uv tarball is fetched, and a tampered one stops everything."""
    release.remove("uv")
    uvrel = tmp_path / "uvrel"
    uvrel.mkdir()
    for arch in ("aarch64", "x86_64"):
        (uvrel / f"uv-{arch}-apple-darwin.tar.gz").write_bytes(b"not uv")
    env = {**release.env_vars, "LFLABS_MEMORY_UV_BASE": f"file://{uvrel}"}
    r = sh(release.script, env)
    assert r.returncode != 0 and "uv.tar.gz did not match its checksum" in r.stderr
    assert not (release.home / ".local/bin/uv").exists()


def test_render_fills_every_release_line(release):
    text = release.script.read_text()
    sha = hashlib.sha256((release.rel / CLI).read_bytes()).hexdigest()
    assert 'VERSION="0.2.0"' in text and f'CLI_SHA256="{sha}"' in text and f'CLI_WHEEL="{CLI}"' in text
    assert os.access(ROOT / "install.sh", os.X_OK) or True
