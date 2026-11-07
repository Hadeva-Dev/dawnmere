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
    mac.on("claude", ["--version"], 0, "2.1.301 (Claude Code)\n")
    mac.on("claude", ["plugin", "list"], 0, "  lflabs-memory@lflabs  1.0.0b1  enabled\n")
    mac.on("claude", ["-p"], 0, '{"is_error": false, "result": "ok"}')
    for d in (".claude", ".codex", ".cursor"):
        (h / d).mkdir()
    (h / ".codex/config.toml").write_text('[mcp_servers.lflabs-memory]\nargs = ["-y", "lflabs-memory-connector@0.1.0"]\n')
    (h / ".codex/hooks.json").write_text('{"hooks": {"UserPromptSubmit": [{"hooks": [{"command": "lflabs-memory hook-prompt"}]}]}}')
    (h / ".cursor/mcp.json").write_text('{"mcpServers": {"lflabs-memory": {"args": ["-y", "lflabs-memory-connector@0.1.0"]}}}')
    (h / ".cursor/hooks.json").write_text('{"version": 1, "hooks": {"sessionStart": [{"command": "x/lflabs-memory hook-cursor-start"}]}}')


GOLDEN = """\
engine        ok    1.0.0b1, running (pid 4120), up 2 d
data          ok    ~/Library/Application Support/LF Labs/Memory  (4 memories, 2 claims, 0 MB)
models        ok    embed, rerank: checksums match
hook speed    ok    recall in N s (limit 1.5 s)
connector     ok    lflabs-memory/1 on SOCK
model         ok    Claude Code 2.1.301, logged in, Haiku
budget        ok    today 41 of 200 calls; last 7 days 0.9k in / 0.2k out tokens a day
backlog       ok    0 sessions waiting to be read
Claude Code   ok    plugin lflabs-memory 1.0.0b1, hooks on
Codex         ok    MCP + hook (Codex asks you to trust the hook once: /hooks)
Cursor        ok    MCP, work only (change it: dawnmere access cursor)
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


def wheelset(v):
    return {f"lflabs_memory_cli-{v}-py3-none-any.whl": f"cli {v}".encode(),
            f"lflabs_memory_engine-{v}-py3-none-any.whl": f"engine {v}".encode()}


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
    get = fake_github({"0.1.0": wheelset("0.1.0"), "0.2.0": wheelset("0.2.0")})
    out = []
    assert update.finish("0.1.0", say=out.append, get=get) == 1
    rows = sqlite3.connect(data / "memory.db").execute("select content from memories").fetchall()
    assert rows == [("we deploy on Fridays",)], "the store is back as it was"
    installs = [c for c in mac.calls("uv") if c[:2] == ["tool", "install"]]
    assert installs and "lflabs_memory_cli-0.1.0-py3-none-any.whl" in installs[-1][-3]
    assert any("bootstrap" in c for c in mac.calls("launchctl")), "the service is started again"
    assert out[-1].startswith("Back on 0.1.0; your memory is as it was")
    assert list((data / "backup").glob("memory-*-before-update.db"))


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
