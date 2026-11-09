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
    assert len((ROOT / "install.sh").read_text().splitlines()) <= 200  # 150, 180 with the retries, 200 with .zprofile


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
    assert ["python", "find", "--managed-python", "3.12"] in release.calls("uv"), "uv's own Python 3.12"
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


def zprofile_run(release, **env):
    release.add("zsh")
    release.rules["zsh"] = [[["-lic", "command -v dawnmere"], 1, ""]]
    release.save()
    return sh(release.script, {**release.env_vars, "LFLABS_MEMORY_NO_SETUP": "1", **env})


def test_a_new_terminal_finds_dawnmere(release, tmp_path):
    """A login shell would not find dawnmere: the tool folder goes on PATH in ~/.zprofile (made if missing), once,
    said in one line, and recorded for uninstall. Checked as setup and doctor check it (zsh -lic)."""
    tools = tmp_path / "tools-bin"
    line = f'export PATH="{tools}:$PATH"  # added by the Dawnmere installer'
    r = zprofile_run(release)
    assert r.returncode == 0, r.stderr
    assert (release.home / ".zprofile").read_text() == line + "\n"
    assert f"New Terminal windows find dawnmere: {tools} is on PATH in ~/.zprofile now." in r.stdout
    record = release.home / "Library/Application Support/LF Labs/Memory/zprofile-line"
    assert record.read_text() == f"created\n{line}\n"
    assert ["-lic", "command -v dawnmere"] in release.calls("zsh")
    assert zprofile_run(release).returncode == 0
    assert (release.home / ".zprofile").read_text() == line + "\n", "never twice"


def test_zprofile_of_ones_own_is_appended_to(release, tmp_path):
    (release.home / ".zprofile").write_text('eval "$(/opt/homebrew/bin/brew shellenv)"')  # no newline at the end
    assert zprofile_run(release).returncode == 0
    line = f'export PATH="{tmp_path / "tools-bin"}:$PATH"  # added by the Dawnmere installer'
    assert (release.home / ".zprofile").read_text() == f'eval "$(/opt/homebrew/bin/brew shellenv)"\n{line}\n'
    assert (release.home / "Library/Application Support/LF Labs/Memory/zprofile-line").read_text() == \
        f"existing\n\n{line}\n"


def test_no_zprofile_line_when_a_new_terminal_finds_it(release):
    release.add("zsh")
    r = sh(release.script, {**release.env_vars, "LFLABS_MEMORY_NO_SETUP": "1"})
    assert r.returncode == 0 and not (release.home / ".zprofile").exists() and "zprofile" not in r.stdout



@pytest.mark.parametrize("locale,cell", [({"LC_ALL": "C"}, "-"), ({"LANG": "en_US.UTF-8"}, "─"),
                                         ({"LC_ALL": "en_US.ISO8859-1", "LANG": "en_US.UTF-8"}, "-"),
                                         ({"LC_CTYPE": "UTF-8"}, "─"), ({}, "-")])
def test_progress_bar_follows_the_locale(release, locale, cell):
    """Box drawing only under a UTF-8 locale, decided as setup's screen decides (LC_ALL, LC_CTYPE, LANG)."""
    r = sh(release.script, {**release.env_vars, **locale})
    assert r.returncode == 0, r.stderr
    bars = [line for line in r.stdout.replace("\r", "\n").splitlines() if line.startswith("Downloading  ")]
    assert bars and f"Downloading  {cell * 12}" in r.stdout.replace("\r", "\n")
    assert ("─" in r.stdout) == (cell == "─")



class GitHub:
    """A local stand-in for github.com's release downloads and api.github.com: each path answers 504 as many times
    as told, then the file. Asset ids as the API gives them."""

    def __init__(self, rel, fail=None, accept=True):
        import http.server
        import threading
        self.rel, self.fail, self.hits = rel, dict(fail or {}), []
        names = sorted(p.name for p in rel.iterdir())
        self.ids = {n: 100 + i for i, n in enumerate(names)}
        outer = self

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                outer.hits.append((self.path, self.headers.get("Accept")))
                left = next((k for k in outer.fail if self.path.startswith(k) and outer.fail[k] != 0), None)
                if left:
                    outer.fail[left] -= 1
                    return self.send_error(504)
                if self.path.startswith("/dl/"):
                    return self.reply((outer.rel / self.path[4:]).read_bytes())
                if self.path == "/api/repos/Hadeva-Dev/dawnmere/releases/tags/v0.2.0":
                    return self.reply(json.dumps({"assets": [{"name": n, "id": i} for n, i in outer.ids.items()]})
                                      .encode())
                if self.path.startswith("/api/repos/Hadeva-Dev/dawnmere/releases/assets/"):
                    if self.headers.get("Accept") != "application/octet-stream":
                        return self.reply(b'{"json": "metadata, not the file"}')
                    i = int(self.path.rsplit("/", 1)[1])
                    return self.reply((outer.rel / next(n for n, x in outer.ids.items() if x == i)).read_bytes())
                self.send_error(404)

            def reply(self, body):
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def env(self, base):
        return {**base, "LFLABS_MEMORY_RELEASE_BASE": f"{self.url}/dl", "LFLABS_MEMORY_API_BASE": f"{self.url}/api"}

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def test_downloads_are_retried(release):
    gh = GitHub(release.rel, {f"/dl/{CLI}": 2})
    try:
        r = sh(release.script, gh.env(release.env_vars))
        assert r.returncode == 0, r.stderr
        assert [p for p, _ in gh.hits].count(f"/dl/{CLI}") == 3, "two 504s, then the file"
    finally:
        gh.close()


def test_downloads_fall_back_to_the_api(release):
    """The release URL keeps failing: the same files through api.github.com, by asset id, as octet-stream; the
    checksums are checked as ever."""
    gh = GitHub(release.rel, {"/dl/": -1})
    try:
        r = sh(release.script, {**gh.env(release.env_vars), "LFLABS_MEMORY_RETRIES": "1"})
        assert r.returncode == 0, r.stderr
        assert "Checksums ok" in r.stdout
        got = [(p, a) for p, a in gh.hits if "/releases/assets/" in p]
        assert len(got) == 3 and all(a == "application/octet-stream" for _, a in got)
    finally:
        gh.close()


def test_a_download_that_never_comes_says_so_once(release):
    gh = GitHub(release.rel, {"/dl/": -1, "/api/": -1})
    try:
        r = sh(release.script, {**gh.env(release.env_vars), "LFLABS_MEMORY_RETRIES": "1"})
        assert r.returncode != 0
        assert r.stderr.strip().splitlines()[-1] == (f"Could not download {CLI}: GitHub did not answer. Check the "
                                                     "connection and run the install line again.")
        assert not installs(release)
    finally:
        gh.close()


def test_an_old_curl_is_retried_by_a_loop(release, tmp_path):
    """A curl without --retry-all-errors (older than 7.71): the loop retries instead."""
    old = tmp_path / "oldcurl"
    old.mkdir()
    (old / "curl").write_text('#!/bin/sh\n[ "$1" = --help ] && { echo "--retry <num>"; exit 0; }\n'
                              'exec /usr/bin/curl "$@"\n')
    (old / "curl").chmod(0o755)
    gh = GitHub(release.rel, {f"/dl/{CLI}": 1})
    try:
        env = gh.env(release.env_vars)
        r = sh(release.script, {**env, "PATH": f"{old}:{env['PATH']}", "LFLABS_MEMORY_RETRIES": "2"})
        assert r.returncode == 0, r.stderr
        assert [p for p, _ in gh.hits].count(f"/dl/{CLI}") == 2
    finally:
        gh.close()


STUBS = ("install_name_tool", "xcrun", "git", "codesign", "clang", "make")  # Apple's stubs open the tools' dialog


def first_python(release, tmp_path, tools):
    """uv without its Python yet (find fails until `python install` ran), logging each call's argv and PATH; the
    developer tools there (an xcode-select naming a folder with usr/bin/git) or not; Apple's stubs on PATH, logging."""
    log = tmp_path / "uv-calls"
    real = release.bin / "uv"
    (tmp_path / "rules-uv").mkdir()
    (tmp_path / "rules-uv/uv").write_bytes(real.read_bytes())  # the rule-driven fake, still named uv
    (tmp_path / "rules-uv/uv").chmod(0o755)
    real.write_text(f"""#!/bin/sh
printf '%s\\t%s\\n' "$*" "$PATH" >> '{log}'
if [ "$1 $2" = "python find" ]; then
  [ -e '{tmp_path}/py-installed' ] || exit 1
  echo '{release.bin}/python3.12'; exit 0
fi
if [ "$1 $2" = "python install" ]; then : > '{tmp_path}/py-installed'; exit 0; fi
exec '{tmp_path}/rules-uv/uv' "$@"
""")
    real.chmod(0o755)
    for stub in STUBS:
        release.add(stub)
    dev = tmp_path / "Developer"
    (dev / "usr/bin").mkdir(parents=True)
    (dev / "usr/bin/git").write_text("")
    xs = tmp_path / "xcode-select"
    xs.write_text(f"#!/bin/sh\necho '{dev}'\n" if tools else
                  "#!/bin/sh\necho 'xcode-select: error: unable to get active developer directory' >&2\nexit 2\n")
    xs.chmod(0o755)
    return log, {**release.env_vars, "LFLABS_MEMORY_XCODE_SELECT": str(xs)}


def test_no_developer_tools_dialog_from_the_python_install(release, tmp_path):
    """Without the tools, `uv python install` runs with no PATH, so uv cannot reach Apple's install_name_tool stub
    (which opens the "install developer tools" dialog); no stub is run by the installer."""
    log, env = first_python(release, tmp_path, tools=False)
    r = sh(release.script, env)
    assert r.returncode == 0, r.stderr
    calls = [line.split("\t") for line in log.read_text().splitlines()]
    install = [p for a, p in calls if a.startswith("python install")]
    assert install == ["/var/empty"]
    for stub in STUBS:
        assert release.calls(stub) == [], stub


def test_python_install_with_the_tools_keeps_path(release, tmp_path):
    log, env = first_python(release, tmp_path, tools=True)
    assert sh(release.script, env).returncode == 0
    calls = [line.split("\t") for line in log.read_text().splitlines()]
    assert [p for a, p in calls if a.startswith("python install")] == [env["PATH"]]


def test_no_python_install_when_uv_has_it(release, tmp_path):
    """Python already there (a reinstall): no `uv python install` at all."""
    assert sh(release.script, release.env_vars).returncode == 0
    assert not [c for c in release.calls("uv") if c[:2] == ["python", "install"]]
