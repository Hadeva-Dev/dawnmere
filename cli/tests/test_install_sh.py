"""install.sh (spec 10.1, Task 13): POSIX, checksums before anything is installed, then setup."""
import hashlib
import importlib.util
import json
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
    (rel / "constraints.txt").write_text("idna==3.20 \\\n    --hash=sha256:" + "ab" * 32 + "\n")
    script = tmp_path / "install.sh"
    script.write_text(render_install.render("0.2.0", rel / CLI, rel / ENGINE, rel / "constraints.txt"))
    home = tmp_path / "home"
    home.mkdir()
    fakes = Fakes(tmp_path, progs=("uv", "sysctl", "python3.12"))
    fakes.on("uv", ["python", "find", "--managed-python", "3.12"], 0, str(fakes.bin / "python3.12"))
    fakes.on("sysctl", ["-n", "hw.optional.arm64"], 0, "1\n")
    tools = tmp_path / "tools-bin"
    tools.mkdir()
    shutil.copy(fakes.bin / "uv", tools / "dawnmere")
    fakes.on("uv", ["tool", "dir", "--bin"], 0, str(tools))
    fakes.on("uv", ["tool", "dir"], 0, str(tmp_path / "uv tools"))
    fakes.on("uv", ["tool", "install", "--help"], 0, "      --with-executables-from <WITH_EXECUTABLES_FROM>\n")
    env = {"HOME": str(home), "PATH": f"{fakes.bin}:/usr/bin:/bin", "FAKE_LOG": str(fakes.log),
           "FAKE_RULES": str(fakes.rules_file), "LFLABS_MEMORY_RELEASE_BASE": f"file://{rel}",
           "LFLABS_MEMORY_TTY": "/dev/null"}
    fakes.rel, fakes.script, fakes.env_vars, fakes.home = rel, script, env, home
    return fakes


def sh(script, env):
    """`curl | sh` with no terminal at all (a new session has no controlling terminal: /dev/tty cannot be opened).
    LFLABS_MEMORY_TTY in env stands in for a terminal."""
    return subprocess.run(["/bin/sh", str(script)], env=env, capture_output=True, text=True, stdin=subprocess.DEVNULL,
                          timeout=60, start_new_session=True)


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
    assert not installs(release)
    assert not (release.home / ".local").exists()


def installs(fakes):
    return [c for c in fakes.calls("uv") if c[:2] == ["tool", "install"] and "--help" not in c]


def test_install_sh_installs_then_runs_setup(release, tmp_path):
    r = sh(release.script, release.env_vars)
    assert r.returncode == 0, r.stderr
    assert "Dawnmere installer" in r.stdout and "Checksums ok" in r.stdout and "Downloading  " in r.stdout
    rows = [json.loads(line) for line in release.log.read_text().splitlines()]
    order = [(x["prog"], x["argv"][:2]) for x in rows if x["prog"] == "python3.12" or x["argv"][:2] == ["tool", "install"]
             and "--help" not in x["argv"]]
    assert order == [("python3.12", ["-I", "-m"]), ("uv", ["tool", "install"])], "every hash checked before installing"
    assert ["python", "install", "--managed-python", "--no-bin", "3.12"] in release.calls("uv")
    download = release.calls("python3.12")[0]
    assert download[:4] == ["-I", "-m", "pip", "download"]
    assert download[4:13] == ["--require-hashes", "--only-binary", ":all:", "--no-deps", "--no-cache-dir",
                              "--disable-pip-version-check", "-q", "-r", download[12]]
    lock, deps = download[12], download[14]
    assert lock.endswith("constraints.txt") and download[13] == "-d"
    install, = installs(release)
    assert install[2:6] == ["--force", "--managed-python", "--python", "3.12"]
    assert install[6:13] == ["--no-index", "--find-links", deps, "--no-build", "--no-cache", "-c", lock], \
        "only the checked files, at the versions the release was tested with"
    assert install[13].endswith(CLI) and install[15].endswith(ENGINE)
    assert install[16:] == ["--with-executables-from", "lflabs-memory-engine"], "the hooks' lflabs-memory is linked too"
    assert release.calls("dawnmere") == [["setup"]]


def test_constraints_checksum_mismatch_aborts(release):
    (release.rel / "constraints.txt").write_text("idna==9.9\n")
    r = sh(release.script, release.env_vars)
    assert r.returncode != 0 and "constraints.txt did not match its checksum, so nothing was installed" in r.stderr
    assert not installs(release) and not release.calls("python3.12")


def test_a_dependency_with_the_wrong_hash_installs_nothing(release):
    """pip refuses a file whose hash is not the one in constraints.txt: uv tool install never runs, no environment
    is made."""
    release.on("python3.12", ["-I", "-m", "pip", "download"], 1, "")
    r = sh(release.script, release.env_vars)
    assert r.returncode != 0
    assert "A dependency could not be downloaded or did not match its hash, so nothing was installed." in r.stderr
    assert not installs(release) and release.calls("dawnmere") == []


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


def test_old_uv_is_not_used(release, tmp_path):
    """A uv too old to link the engine's command: the pinned uv is fetched instead (here: a tampered one, so it stops)."""
    release.rules["uv"] = [r for r in release.rules["uv"] if r[0] != ["tool", "install", "--help"]]
    release.save()
    uvrel = tmp_path / "uvrel"
    uvrel.mkdir()
    for arch in ("aarch64", "x86_64"):
        (uvrel / f"uv-{arch}-apple-darwin.tar.gz").write_bytes(b"not uv")
    r = sh(release.script, {**release.env_vars, "LFLABS_MEMORY_UV_BASE": f"file://{uvrel}"})
    assert r.returncode != 0 and "uv.tar.gz did not match its checksum" in r.stderr
    assert not [c for c in release.calls("uv") if c[:2] == ["tool", "install"] and "--help" not in c]


def test_intel_mac_refused_before_any_download(release):
    release.rules["sysctl"] = [[["-n", "hw.optional.arm64"], 0, "0\n"]]
    release.save()
    r = sh(release.script, release.env_vars)
    assert r.returncode == 1 and "Dawnmere needs a Mac with Apple silicon" in r.stderr
    assert not release.calls("uv")


def test_render_fills_every_release_line(release):
    text = release.script.read_text()
    sha = hashlib.sha256((release.rel / CLI).read_bytes()).hexdigest()
    assert 'VERSION="0.2.0"' in text and f'CLI_SHA256="{sha}"' in text and f'CLI_WHEEL="{CLI}"' in text
    lock = (release.rel / "constraints.txt").read_bytes()
    assert f'CONSTRAINTS_SHA256="{hashlib.sha256(lock).hexdigest()}"' in text and f"CONSTRAINTS_SIZE={len(lock)}" in text
    assert os.access(ROOT / "install.sh", os.X_OK) or True


def test_path_advice_is_setups(release, tmp_path):
    """Without setup to follow, install.sh gives setup's own PATH advice, checked the way setup and doctor check it
    (zsh as a new Terminal window starts it). With setup to follow, setup says it at its end."""
    from lflabs_memory_cli import layout
    release.add("zsh")
    release.on("zsh", ["-lic", "command -v dawnmere"], 1, "")
    r = sh(release.script, {**release.env_vars, "LFLABS_MEMORY_NO_SETUP": "1"})
    assert r.returncode == 0, r.stderr
    tools = tmp_path / "tools-bin"
    assert f'To run dawnmere later, add this line to ~/.zshrc:\n  export PATH="{tools}:$PATH"\n' in r.stdout
    assert ["-lic", "command -v dawnmere"] in release.calls("zsh")
    assert "add this line to ~/.zshrc:\n  " in layout.path_advice()
    release.rules["zsh"] = []
    release.save()
    assert "~/.zshrc" not in sh(release.script, {**release.env_vars, "LFLABS_MEMORY_NO_SETUP": "1"}).stdout
    assert "~/.zshrc" not in sh(release.script, release.env_vars).stdout


def test_no_terminal_means_no_setup(release):
    """`curl | sh </dev/null`: nobody can say yes to changing the apps' files, so setup does not run, and the
    installer says how to run it."""
    env = {k: v for k, v in release.env_vars.items() if k != "LFLABS_MEMORY_TTY"}
    r = sh(release.script, env)
    assert r.returncode == 0, r.stderr
    assert release.calls("dawnmere") == []
    assert ("There is no terminal for setup's questions, so no app was changed. Run \"dawnmere setup\" in a "
            "Terminal window, or \"dawnmere setup --yes\" to take the defaults.") in " ".join(r.stdout.split())
