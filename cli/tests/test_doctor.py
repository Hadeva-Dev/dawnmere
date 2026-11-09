"""dawnmere doctor, export/import and update (Task 11)."""
import hashlib
import json
import os
import re
import sqlite3
import time

import pytest

import store

from lflabs_memory_cli import backend, doctor, export, layout, models, update

MEMS = [("we deploy on Fridays", "project", "projects"), ("use pnpm, never npm", "feedback", "prefs"),
        ("I live in Berkeley at 12 Elm St", "user", "personal"),
        ("the staging password is hunter2", "reference", "reference", "words")]


def healthy(mac, monkeypatch, tmp_path, backend_name="claude-cli"):
    """A Mac where everything works: service running, models in place, apps wired, a store with memories."""
    h = mac.home
    data = layout.data_dir()
    data.mkdir(parents=True, mode=0o700)
    data.parent.chmod(0o700)
    (data / "config.toml").write_text(f'version = 1\n[llm]\nbackend = "{backend_name}"\n')
    day = time.strftime("%Y-%m-%d")
    store.make(data / "memory.db", MEMS, ["c1", "c2"], [(day, "extract", 41, 6200, 1100, 0.1)])
    (data / "backup").mkdir()
    snap = data / "backup/memory-x-daily.db"
    snap.write_text("")
    os.utime(snap, (time.time() - 6 * 3600,) * 2)
    files = {}
    for name in ("embed", "rerank"):
        (data / "models" / name).mkdir(parents=True)
        body = f"{name} weights".encode()
        (data / "models" / name / "model.onnx").write_bytes(body)
        files[name] = [{"file": "model.onnx", "url": "x", "size": len(body), "sha256": hashlib.sha256(body).hexdigest()}]
    monkeypatch.setattr(models, "manifest", lambda: {"release": "models-x", "models": files})
    monkeypatch.setattr(backend, "engine_status", lambda ping=False: None)
    monkeypatch.setattr(doctor, "version", lambda dist: {"lflabs-memory-engine": "1.0.0b1"}.get(dist, "1.0.0b1"))
    mac.on("launchctl", ["print"], 0, "\tstate = running\n\tpid = 4120\n")
    mac.on("ps", [], 0, " 2-03:04:05\n")
    mac.add("ps")
    mac.add("lflabs-memory")
    for prog in ("node", "npx", "zsh"):
        mac.add(prog)
    layout.engine_record().write_text(f"{mac.bin}/lflabs-memory\n")
    mac.on("node", ["--version"], 0, "v20.11.0\n")
    mac.on("claude", ["--version"], 0, "2.1.301 (Claude Code)\n")
    mac.on("claude", ["plugin", "list"], 0, "  lflabs-memory@lflabs  1.0.0b1  enabled\n")
    mac.on("claude", ["-p"], 0, '{"is_error": false, "result": "ok"}')
    for d in (".claude", ".codex", ".cursor"):
        (h / d).mkdir()
    (h / ".codex/config.toml").write_text('[mcp_servers.lflabs-memory]\nargs = ["-y", "dawnmere-connector@0.1.0"]\n')
    (h / ".codex/hooks.json").write_text('{"hooks": {"UserPromptSubmit": [{"hooks": [{"command": "lflabs-memory hook-prompt"}]}]}}')
    (h / ".cursor/mcp.json").write_text('{"mcpServers": {"lflabs-memory": {"args": ["-y", "dawnmere-connector@0.1.0"]}}}')
    (h / ".cursor/hooks.json").write_text('{"version": 1, "hooks": {"sessionStart": [{"command": "x/lflabs-memory hook-cursor-start"}]}}')


GOLDEN = """\
engine        ok    1.0.0b1, running (pid 4120), up 2 d
data          ok    ~/Library/Application Support/LF Labs/Memory  (4 memories, 2 claims, 0 MB)
models        ok    embed, rerank: checksums match
hook speed    ok    recall in N s (limit 1.5 s)
connector     ok    lflabs-memory/1 on SOCK
Node.js       ok    v20.11.0
model         ok    Claude Code 2.1.301, logged in, Haiku
budget        ok    today 41 of 200 calls; last 7 days 0.9k in / 0.2k out tokens a day
backlog       ok    0 sessions waiting to be read
Claude Code   ok    plugin lflabs-memory 1.0.0b1, hooks on
Codex         ok    MCP + hook (Codex asks you to trust the hook once: /hooks)
Cursor        ok    MCP, work only (change it: dawnmere access cursor)
dawnmere      ok    on your PATH
privacy       ok    local only; Codex sessions off; chat index off; no telemetry
backups       ok    last local snapshot 6 h ago (1 kept)"""


def run_doctor(**kw):
    out = []
    code = doctor.main(out=out.append, **kw)
    text = "\n".join(out)
    text = re.sub(r"recall in \d+\.\d+ s", "recall in N s", text)
    return code, text


def test_doctor_lines_golden(mac, monkeypatch, tmp_path, connector):
    healthy(mac, monkeypatch, tmp_path)
    code, text = run_doctor()
    assert text.replace(connector.path, "SOCK") == GOLDEN
    assert code == 0


def test_doctor_without_node(mac, monkeypatch, tmp_path, connector):
    """No Node.js: its own row says what to install, and every app's row says it cannot use memory's tools."""
    healthy(mac, monkeypatch, tmp_path)
    mac.remove("node")
    mac.remove("npx")
    code, text = run_doctor()
    lines = {line[:14].strip(): line for line in text.splitlines() if len(line) > 14}
    assert lines["Node.js"].startswith("Node.js       warn  Node.js is not installed")
    for app in ("Claude Code", "Codex", "Cursor"):
        assert lines[app][14:20] == "warn  ", lines[app]
        assert f"{app} cannot use memory's tools until Node.js 18 or later is installed" in lines[app]
    assert "\nNode.js: install Node.js 18 or later from nodejs.org" in text
    assert text.count("nodejs.org") == 1, "one fix line, not one per app"


def test_doctor_node_too_old(mac, monkeypatch, tmp_path, connector):
    healthy(mac, monkeypatch, tmp_path)
    mac.rules["node"] = [[["--version"], 0, "v16.20.2\n"]]
    mac.save()
    code, text = run_doctor()
    assert "Node.js       warn  Node.js v16.20.2 is too old" in text
    assert "Codex cannot use memory's tools until Node.js 18 or later is installed" in text
    assert "\nNode.js: install Node.js 18 or later from nodejs.org" in text


def test_doctor_path_row(mac, monkeypatch, tmp_path, connector):
    """The same check and advice as setup and install.sh: zsh as a new Terminal window starts it, ~/.zshrc."""
    healthy(mac, monkeypatch, tmp_path)
    mac.on("zsh", ["-lic"], 1, "")
    code, text = run_doctor()
    assert "dawnmere      warn  not on your PATH: a new Terminal window will not find it" in text
    assert '\ndawnmere: add this line to ~/.zshrc, then open a new Terminal window: export PATH="' in text
    assert ["-lic", "command -v dawnmere"] in mac.calls("zsh")


def test_doctor_checks_the_lf_labs_folder(mac, monkeypatch, tmp_path, connector):
    healthy(mac, monkeypatch, tmp_path)
    layout.data_dir().parent.chmod(0o755)
    code, text = run_doctor()
    assert "data          warn  ~/Library/Application Support/LF Labs/Memory" in text
    assert "\ndata: the folder is readable by others: chmod 700 '" + str(layout.data_dir().parent) + "'" in text


def test_doctor_none_mode_line(mac, monkeypatch, tmp_path, connector):
    healthy(mac, monkeypatch, tmp_path, backend_name="none")
    code, text = run_doctor()
    assert ("model         ok    none: recall and remember work; automatic saving, claims, handoffs and "
            "translation are off") in text
    assert not [c for c in mac.calls("claude") if c[:1] == ["-p"]], "none mode never calls claude"


def test_doctor_fails_when_service_down(mac, monkeypatch, tmp_path):
    healthy(mac, monkeypatch, tmp_path)
    mac.rules["launchctl"] = [[["print"], 113, ""]]
    mac.save()
    code, text = run_doctor()
    assert code == 1 and "engine        fail" in text and "connector     fail" in text
    assert "\nengine: run dawnmere setup" in text


def test_doctor_report_counts_only(mac, monkeypatch, tmp_path, connector):
    healthy(mac, monkeypatch, tmp_path)
    code, text = run_doctor(as_report=True)
    assert code == 0 and "memories kind=project: 1" in text and "claims: 2" in text
    for leak in ("Fridays", "pnpm", "Berkeley", "hunter2", "shop", str(mac.home), "/Users/"):
        assert leak not in text


def test_export_leaves_secrets_out(mac, monkeypatch, tmp_path):
    healthy(mac, monkeypatch, tmp_path)
    out = []
    assert export.export(say=out.append) == 0
    path = mac.home / "Downloads" / f"dawnmere-export-{time.strftime('%Y-%m-%d')}.json"
    doc = json.loads(path.read_text())
    assert doc["format"] == "lflabs-memory-export/1"
    assert [m["content"] for m in doc["memories"]] == [m[0] for m in MEMS[:3]]
    assert "hunter2" not in path.read_text()
    assert oct(path.stat().st_mode & 0o777) == "0o600"
    assert "1 secret left out: they never leave the engine." in out
    md = tmp_path / "out.md"
    export.export(md, "md", say=lambda s: None)
    assert "## prefs" in md.read_text() and "hunter2" not in md.read_text()


def test_export_import_roundtrip(mac, monkeypatch, tmp_path):
    healthy(mac, monkeypatch, tmp_path)
    f = tmp_path / "e.json"
    export.export(f, say=lambda s: None)
    saved = {}

    def remember(content, kind, project):  # the engine's remember(): dedup by text
        if content in saved:
            return saved[content], "unchanged"
        saved[content] = len(saved) + 1
        return saved[content], "added"
    out = []
    assert export.import_file(f, say=out.append, remember=remember) == 0
    assert out[-1] == "Imported 3 new memories; 0 were already here."
    export.import_file(f, say=out.append, remember=remember)
    assert out[-1] == "Imported 0 new memories; 3 were already here."
    assert set(saved) == {m[0] for m in MEMS[:3]}
    bad = tmp_path / "bad.json"
    bad.write_text('{"format": "other"}')
    assert export.import_file(bad, say=out.append, remember=remember) == 1


# ---------- update ----------

def fake_github(versions):
    """get(url) answering the release API and assets for {version: {asset name: bytes}}."""
    def assets(v):
        files = dict(versions[v])
        files["SHA256SUMS"] = "".join(f"{hashlib.sha256(b).hexdigest()}  {n}\n" for n, b in files.items()).encode()
        return files

    def get(url):
        latest = max(versions, key=update.vtuple)
        m = re.search(r"/releases/(latest|tags/v([\d.]+))$", url)
        if m:
            v = latest if m.group(1) == "latest" else m.group(2)
            return json.dumps({"tag_name": f"v{v}", "body": "Faster recall.\nFixes.",
                               "assets": [{"name": n, "browser_download_url": f"https://dl/{v}/{n}"}
                                          for n in assets(v)]}).encode()
        v, name = url.rsplit("/", 2)[-2:]
        return assets(v)[name]
    return get


def wheelset(v, constraints=True):
    return {f"lflabs_memory_cli-{v}-py3-none-any.whl": f"cli {v}".encode(),
            f"lflabs_memory_engine-{v}-py3-none-any.whl": f"engine {v}".encode(),
            **({"constraints.txt": f"idna==3.{v[-1]}\n".encode()} if constraints else {})}


def uv_installs(mac):
    return [c for c in mac.calls("uv") if c[:2] == ["tool", "install"]]


def with_python(mac, tmp_path):
    """uv's own Python 3.12, a fake that logs the pip download it is asked for."""
    mac.add("python3.12")
    mac.on("uv", ["python", "find", "--managed-python", "3.12"], 0, str(mac.bin / "python3.12"))
    mac.on("uv", ["tool", "dir"], 0, str(tmp_path / "tools"))


def failing_first_install(monkeypatch):
    """uv tool install fails once (after its files landed), then works."""
    real, failed = update.run, []

    def run(argv, **kw):
        if argv[1:3] == ["tool", "install"] and not failed:
            failed.append(argv)
            real(argv, **kw)
            return update.Result(1, "", "uv broke halfway")
        return real(argv, **kw)
    monkeypatch.setattr(update, "run", run)


def test_update_pins_and_checks_every_dependency(mac, monkeypatch, tmp_path):
    """The release's constraints.txt, checked against SHA256SUMS; every dependency downloaded by pip with its hash
    checked, before anything is installed; uv tool install then takes only those files. Then the new program
    finishes."""
    monkeypatch.setattr(update, "installed_version", lambda: "0.1.0")
    with_python(mac, tmp_path)
    finished = []
    monkeypatch.setattr(update.os, "execvp", lambda prog, argv: finished.append(argv))
    seen = {}
    real = update.run

    def run(argv, **kw):
        if argv[1:3] == ["tool", "install"]:
            seen["lock"] = open(argv[argv.index("-c") + 1]).read()
            seen["order"] = list(mac.calls())
        return real(argv, **kw)
    monkeypatch.setattr(update, "run", run)
    update.main(yes=True, say=lambda s: None, get=fake_github({"0.2.0": wheelset("0.2.0")}))
    download = mac.calls("python3.12")[0]
    assert download[:12] == ["-I", "-m", "pip", "download", "--require-hashes", "--only-binary", ":all:", "--no-deps",
                             "--no-cache-dir", "--disable-pip-version-check", "-q", "-r"]
    assert download in seen["order"], "the hashes are checked before uv tool install runs"
    install, = uv_installs(mac)
    deps = download[download.index("-d") + 1]
    assert install[6:13] == ["--no-index", "--find-links", deps, "--no-build", "--no-cache", "-c", download[12]]
    assert seen["lock"] == "idna==3.0\n"
    assert finished and finished[0][1:] == ["update", "--finish", "0.1.0"]


def test_update_refuses_a_release_without_constraints(mac, monkeypatch):
    monkeypatch.setattr(update, "installed_version", lambda: "0.1.0")
    out = []
    assert update.main(yes=True, say=out.append, get=fake_github({"0.2.0": wheelset("0.2.0", False)})) == 1
    assert out[-1] == "Update stopped: the release has no checked constraints.txt: nothing was installed"
    assert uv_installs(mac) == []


def test_update_with_a_wrong_hash_installs_nothing(mac, monkeypatch, tmp_path):
    """pip refuses the file: uv tool install never runs, and the installed release is left as it was."""
    monkeypatch.setattr(update, "installed_version", lambda: "0.1.0")
    with_python(mac, tmp_path)
    mac.on("python3.12", ["-I", "-m", "pip", "download"], 1, "")
    out = []
    assert update.main(yes=True, say=out.append, get=fake_github({"0.2.0": wheelset("0.2.0")})) == 1
    assert out[-1].startswith("Update stopped: a dependency could not be downloaded or did not match its hash: "
                              "nothing was installed")
    assert uv_installs(mac) == [] and ["tool", "uninstall", "lflabs-memory-cli"] not in mac.calls("uv")


def test_update_failing_after_files_landed_puts_the_old_release_back(mac, monkeypatch, tmp_path):
    """Fail closed: the half-made environment is taken out first, then the old release goes back, checked."""
    monkeypatch.setattr(update, "installed_version", lambda: "0.1.0")
    with_python(mac, tmp_path)
    failing_first_install(monkeypatch)
    out = []
    get = fake_github({"0.1.0": wheelset("0.1.0"), "0.2.0": wheelset("0.2.0")})
    assert update.main(yes=True, say=out.append, get=get) == 1
    calls = [c for c in mac.calls("uv") if c[:2] in (["tool", "install"], ["tool", "uninstall"])]
    assert [c[:2] for c in calls] == [["tool", "install"], ["tool", "uninstall"], ["tool", "install"]]
    assert "lflabs_memory_cli-0.1.0-py3-none-any.whl" in calls[-1][13] and "--no-index" in calls[-1]
    assert len(mac.calls("python3.12")) == 2, "the old release's dependencies are checked too"
    assert out[-1] == "Back on 0.1.0."


def test_update_that_cannot_put_the_old_release_back_leaves_nothing(mac, monkeypatch, tmp_path):
    """The old release cannot be put back checked (here: it has no constraints.txt): nothing stays installed, and
    the install line is given."""
    monkeypatch.setattr(update, "installed_version", lambda: "0.1.0")
    with_python(mac, tmp_path)
    failing_first_install(monkeypatch)
    out = []
    get = fake_github({"0.1.0": wheelset("0.1.0", False), "0.2.0": wheelset("0.2.0")})
    assert update.main(yes=True, say=out.append, get=get) == 1
    assert len(uv_installs(mac)) == 1 and ["tool", "uninstall", "lflabs-memory-cli"] in mac.calls("uv")
    assert out[-2] == "Could not reinstall 0.1.0 (0.1.0 has no constraints.txt to check it against), so Dawnmere is " \
                      "uninstalled. Install it again with:"
    assert out[-1] == "  curl -fsSL https://github.com/Hadeva-Dev/dawnmere/releases/latest/download/install.sh | sh"


def test_quarantine_moves_the_environment_aside_when_uv_cannot_uninstall(mac, tmp_path):
    mac.on("uv", ["tool", "uninstall"], 1, "")
    mac.on("uv", ["tool", "dir"], 0, str(tmp_path / "tools"))
    (tmp_path / "tools/lflabs-memory-cli/bin").mkdir(parents=True)
    update.quarantine()
    assert not (tmp_path / "tools/lflabs-memory-cli").exists()
    assert [p.name.startswith("lflabs-memory-cli.quarantined-") for p in (tmp_path / "tools").iterdir()] == [True]


def test_update_check_only(mac, monkeypatch):
    monkeypatch.setattr(update, "installed_version", lambda: "0.1.0")
    out = []
    assert update.main(check_only=True, say=out.append, get=fake_github({"0.1.0": wheelset("0.1.0"),
                                                                         "0.2.0": wheelset("0.2.0")})) == 0
    assert out[0] == "Dawnmere 0.2.0 is out (you have 0.1.0)." and "  Faster recall." in out
    assert mac.calls("uv") == []


def test_update_refuses_a_bad_checksum(mac, monkeypatch):
    monkeypatch.setattr(update, "installed_version", lambda: "0.1.0")
    get = fake_github({"0.2.0": wheelset("0.2.0")})

    def tampered(url):
        body = get(url)
        return b"evil" if url.endswith(".whl") and "cli" in url else body
    out = []
    assert update.main(yes=True, say=out.append, get=tampered) == 1
    assert "did not match its checksum" in out[-1] and mac.calls("uv") == []


def test_update_rolls_back_on_failed_migration(mac, monkeypatch):
    """finish(): the migration fails, so the snapshot goes back and the old release is reinstalled."""
    data = layout.data_dir()
    data.mkdir(parents=True)
    store.make(data / "memory.db", MEMS[:1])
    mac.add("lflabs-memory")

    def migrate_breaks(*a):  # the new engine's migrate changes the store, then fails
        db = sqlite3.connect(data / "memory.db")
        db.execute("delete from memories")
        db.commit()
        db.close()
    mac.on("lflabs-memory", ["migrate"], 1, "")
    real_run = update.run

    def run(argv, **kw):
        if argv[1:2] == ["migrate"]:
            migrate_breaks()
        return real_run(argv, **kw)
    monkeypatch.setattr(update, "run", run)
    monkeypatch.setattr(models, "manifest", lambda: None)
    get = fake_github({"0.1.0": wheelset("0.1.0", False), "0.2.0": wheelset("0.2.0")})
    out = []
    assert update.finish("0.1.0", say=out.append, get=get) == 1
    rows = sqlite3.connect(data / "memory.db").execute("select content from memories").fetchall()
    assert rows == [("we deploy on Fridays",)], "the store is back as it was"
    installs = [c for c in mac.calls("uv") if c[:2] == ["tool", "install"]]
    assert installs and "lflabs_memory_cli-0.1.0-py3-none-any.whl" in installs[-1][6] and "--managed-python" in installs[-1]
    assert installs[-1][-2:] == ["--with-executables-from", "lflabs-memory-engine"]
    assert "-c" not in installs[-1], "0.1.0 has no constraints.txt: back on it as it was installed"
    assert "0.1.0 has no constraints.txt, so it goes back without pinned dependencies, as it was installed." in out
    assert any("bootstrap" in c for c in mac.calls("launchctl")), "the service is started again"
    assert out[-1].startswith("Back on 0.1.0; your memory is as it was")
    assert list((data / "backup").glob("memory-*-before-update.db"))


def test_update_moves_the_plugin_to_the_new_tag(mac, monkeypatch, tmp_path):
    """The marketplace was added at the old release's tag: it is added again at the new one, the plugin reinstalled
    from it. And the plugin's hooks get the engine's path again."""
    data = layout.data_dir()
    data.mkdir(parents=True)
    mac.add("lflabs-memory")
    (mac.home / ".claude").mkdir()
    mac.on("claude", ["plugin", "list"], 0, "  lflabs-memory@lflabs  0.1.5  enabled\n")
    monkeypatch.setattr(models, "manifest", lambda: None)
    monkeypatch.setattr(update, "installed_version", lambda: "0.2.0")
    out = []
    assert update.finish("0.1.0", say=out.append, get=fake_github({"0.2.0": wheelset("0.2.0")})) == 0
    claude = mac.calls("claude")
    want = [["plugin", "marketplace", "remove", "lflabs"],
            ["plugin", "marketplace", "add", "Hadeva-Dev/dawnmere#v0.2.0", "--scope", "user"],
            ["plugin", "install", "lflabs-memory@lflabs", "--scope", "user", "-y"]]
    assert [c for c in claude if c[:2] != ["plugin", "list"]] == want
    assert "Claude Code's plugin: now v0.2.0 (restart Claude Code to load it)" in out
    assert layout.engine_record().read_text() == f"{mac.bin}/lflabs-memory\n"
    mac.on("claude", ["plugin", "marketplace", "add"], 1, "")
    update.finish("0.1.0", say=out.append, get=fake_github({"0.2.0": wheelset("0.2.0")}))
    assert "Claude Code's plugin could not move to v0.2.0: run dawnmere setup again" in out


def test_models_download_checks_checksums(tmp_path):
    import io

    from lflabs_memory import models as engine_models  # the engine writes models.json; the CLI downloads by it
    src = tmp_path / "src"
    (src / "embed").mkdir(parents=True)
    (src / "embed/model.onnx").write_bytes(b"weights" * 100)
    man = engine_models.build(src, "models-2026-10-28", files={"embed": ("model.onnx",)})
    assert man["models"]["embed"][0]["url"].endswith("/models-2026-10-28/embed-model.onnx")
    served = {"good": b"weights" * 100, "bad": b"evil" * 100}
    for which in ("good", "bad"):
        dest = tmp_path / which
        opener = lambda url, timeout: io.BytesIO(served[which])  # noqa: E731
        if which == "good":
            models.download(man, ["embed"], where=dest, opener=opener)
            assert models.check(man, dest) == {"embed": "ok"}
        else:
            with pytest.raises(models.ChecksumError):
                models.download(man, ["embed"], where=dest, opener=opener)
            assert not list(dest.rglob("*.onnx*")), "nothing half-downloaded is left"


def test_models_folder_is_the_engines(mac, monkeypatch, tmp_path):
    """LFLABS_MEMORY_MODELS, then config.toml's models, then DATA_DIR/models: the order the engine reads them in."""
    assert models.folder() == layout.data_dir() / "models"
    layout.data_dir().mkdir(parents=True)
    (layout.data_dir() / "config.toml").write_text(f'models = "{tmp_path / "cfg"}"\n')
    assert models.folder() == tmp_path / "cfg"
    monkeypatch.setenv("LFLABS_MEMORY_MODELS", str(tmp_path / "shared"))
    assert models.folder() == tmp_path / "shared"


def test_first_day_wording(mac, monkeypatch, tmp_path):
    """One memory reads "1 memory"; the plugin's version is found in claude 2.1.301's multi-line plugin list."""
    data = layout.data_dir()
    data.mkdir(parents=True, mode=0o700)
    store.make(data / "memory.db", MEMS[:1], ["c1"], [])
    db = doctor._db()
    try:
        assert "(1 memory, 1 claim, " in doctor.check_data(db).note
    finally:
        db.close()
    (mac.home / ".claude").mkdir()
    mac.on("claude", ["plugin", "list"], 0, "Installed plugins:\n\n  > lflabs-memory@lflabs\n    Version: 0.1.0\n"
           "    Scope: user\n    Status: enabled\n")
    mac.add("lflabs-memory")
    layout.engine_record().write_text(f"{mac.bin}/lflabs-memory\n")
    assert doctor.check_claude().note == "plugin lflabs-memory 0.1.0, hooks on"
    mac.remove("lflabs-memory")
    c = doctor.check_claude()
    assert c.state == "warn" and c.note.endswith("but its hooks cannot find the engine")
    assert c.fix == "run dawnmere setup again"
    out = []
    export.export(str(tmp_path / "x.json"), say=out.append)
    assert out[0].startswith("Exported 1 memory to ")
