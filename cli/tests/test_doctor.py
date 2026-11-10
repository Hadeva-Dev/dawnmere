"""dawnmere doctor, export/import and update (Task 11)."""
import hashlib
import json
import os
import re
import sys
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
    for prog in ("node", "npx", "zsh", "npm"):
        mac.add(prog)
    mac.on("npm", ["view"], 0, f"{layout.CONNECTOR_VERSION}\n")
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
privacy       ok    memory stored on this Mac; background reading on; Codex sessions off; chat index off; no telemetry
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
    """The same check and advice as setup and install.sh: zsh as a new Terminal window starts it, ~/.zprofile."""
    healthy(mac, monkeypatch, tmp_path)
    mac.on("zsh", ["-lic"], 1, "")
    code, text = run_doctor()
    assert "dawnmere      warn  not on your PATH: a new Terminal window will not find it" in text
    assert '\ndawnmere: add this line to ~/.zprofile, then open a new Terminal window: export PATH="' in text
    assert ["-lic", "command -v dawnmere"] in mac.calls("zsh")


def test_doctor_checks_the_lf_labs_folder(mac, monkeypatch, tmp_path, connector):
    healthy(mac, monkeypatch, tmp_path)
    layout.data_dir().parent.chmod(0o755)
    code, text = run_doctor()
    assert "data          warn  ~/Library/Application Support/LF Labs/Memory" in text
    assert "\ndata: the folder is readable by others: chmod 700 '" + str(layout.data_dir().parent) + "'" in text


def test_doctor_warns_when_claude_moved(mac, monkeypatch, tmp_path, connector):
    healthy(mac, monkeypatch, tmp_path)
    cfg = layout.data_dir() / "config.toml"
    cfg.write_text(cfg.read_text() + f'claude_path = "{tmp_path}/gone/claude"\n')
    code, text = run_doctor()
    assert f"model         warn  Claude Code is not at {tmp_path}/gone/claude any more" in text
    assert "\nmodel: run dawnmere setup again: it finds claude again" in text
    cfg.write_text(cfg.read_text().replace(f"{tmp_path}/gone/claude", f"{mac.bin}/claude"))
    assert "model         ok" in run_doctor()[1]
    mac.remove("claude")
    cfg.write_text(cfg.read_text().replace(f'claude_path = "{mac.bin}/claude"\n', ""))
    code, text = run_doctor()
    assert "model         warn  Claude Code is not installed" in text


def test_privacy_row_says_what_leaves_the_mac(mac, monkeypatch, tmp_path, connector):
    """Never "local only": with background reading on, conversations go to the user's own model."""
    healthy(mac, monkeypatch, tmp_path, backend_name="none")
    code, text = run_doctor()
    assert ("privacy       ok    memory stored on this Mac; background reading off; Codex sessions off; chat index "
            "off; no telemetry") in text
    assert "local only" not in text


def test_doctor_says_when_the_connector_is_not_on_npm(mac, monkeypatch, tmp_path, connector):
    """Every app's MCP entry runs npx dawnmere-connector@X: if X is not published, none of them can start it."""
    healthy(mac, monkeypatch, tmp_path)
    mac.rules["npm"] = [[["view"], 1, "npm error code E404\nnpm error 404 No match found for version 9.9.9\n"]]
    mac.save()
    code, text = run_doctor()
    want = f"the connector dawnmere-connector@{layout.CONNECTOR_VERSION} is not on npm yet: apps cannot start memory's tools"
    for app in ("Claude Code", "Codex", "Cursor"):
        assert next(x for x in text.splitlines() if x.startswith(app)).endswith(want) and f"{app:<14}warn" in text
    assert ["view", f"dawnmere-connector@{layout.CONNECTOR_VERSION}", "version"] in mac.calls("npm")


def test_doctor_offline_could_not_check_npm(mac, monkeypatch, tmp_path, connector):
    healthy(mac, monkeypatch, tmp_path)
    mac.rules["npm"] = [[["view"], 1, "npm error code ENOTFOUND\n"]]
    mac.save()
    code, text = run_doctor()
    assert f"Node.js       ok    v20.11.0; could not check dawnmere-connector@{layout.CONNECTOR_VERSION} on npm" in text
    assert "Codex         ok" in text and code == 0


def test_doctor_remembers_the_connector_is_published(mac, monkeypatch, tmp_path, connector):
    healthy(mac, monkeypatch, tmp_path)
    run_doctor()
    run_doctor()
    assert len([c for c in mac.calls("npm") if c[:1] == ["view"]]) == 1, "asked once, then remembered"


def test_doctor_counts_saves_held_back(mac, monkeypatch, tmp_path, connector):
    healthy(mac, monkeypatch, tmp_path)
    mac.on("lflabs-memory", ["held", "--count"], 0, "3\n")
    code, text = run_doctor()
    assert "held back     ok    3 app saves held back from prompts: lflabs-memory held shows them and their confirm " \
           "codes" in text
    mac.rules["lflabs-memory"] = [[["held", "--count"], 0, "0\n"]]
    mac.save()
    assert "held back" not in run_doctor()[1]


def test_signed_out_of_claude_code_is_a_warning(mac, monkeypatch, tmp_path, connector):
    """Background reading cannot run, but recall and remember still work: warn, exit 0."""
    healthy(mac, monkeypatch, tmp_path)
    mac.rules["claude"] = [r for r in mac.rules["claude"] if r[0][:1] != ["-p"]]
    mac.on("claude", ["-p"], 1, "Invalid API key · Please run /login")
    code, text = run_doctor()
    row = next(x for x in text.splitlines() if x.startswith("model "))
    assert row.startswith("model         warn") and "recall and remember still work" in row
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

    def remember(content, kind, project, origin="unknown"):  # the engine's remember(): dedup by text
        if content in saved:
            return saved[content], "unchanged"
        saved[content] = len(saved) + 1
        return saved[content], "added"
    out = []
    assert export.import_file(f, say=out.append, remember=remember) == 0
    assert "Imported 3 new memories; 0 were already here." in out
    export.import_file(f, say=out.append, remember=remember)
    assert out[-1] == "Imported 0 new memories; 3 were already here.", "none added, so nothing to trust"
    assert set(saved) == {m[0] for m in MEMS[:3]}
    bad = tmp_path / "bad.json"
    bad.write_text('{"format": "other"}')
    assert export.import_file(bad, say=out.append, remember=remember) == 1


def crafted(tmp_path, name="mine.json"):
    f = tmp_path / name
    f.write_text(json.dumps({"format": "lflabs-memory-export/1", "memories": [
        {"content": "a", "origin": "owner_typed"}, {"content": "b"}, {"content": "c", "origin": "app_confirmed"},
        {"content": "d", "origin": "owner_key"}, {"content": "here before", "origin": "owner_typed"}]}))
    return f


def importing(monkeypatch, agent=None):
    """remember() as the engine's ("here before" is already in the store), recording the origin each memory is saved
    with; an AI app's shell when asked."""
    from lflabs_memory_cli import access
    got = {}

    def remember(content, kind, project, origin="unknown"):
        if content == "here before":
            return 3, "unchanged"
        got[content] = origin
        return 10 + len(got), "added"
    for k in access.AGENT_ENV:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(access, "agent_ancestor", lambda: agent)
    return got, remember


def trust_calls(mac):
    return [c for c in mac.calls("lflabs-memory") if c[:1] == ["trust"]]


def test_import_saves_everything_unknown_then_asks_the_engine_to_trust(mac, monkeypatch, tmp_path):
    """Only memories this import added that the file calls the user's own go to the engine's `trust` (one dialog,
    its text the engine's); the rest, and any already here, stay as they are."""
    healthy(mac, monkeypatch, tmp_path)
    mac.on("lflabs-memory", ["trust"], 0, "trusted 2 as your own words\n")
    got, remember = importing(monkeypatch)
    out = []
    t0 = time.time()
    assert export.import_file(crafted(tmp_path), say=out.append, remember=remember) == 0
    assert set(got.values()) == {"unknown"}, "never saved as the user's by the CLI"
    (call,) = trust_calls(mac)
    assert call[:2] == ["trust", "--import-since"] and t0 <= float(call[2]) <= time.time()
    assert call[3:] == ["--", "11", "14"], "the added owner rows only: never 3, which was already here"
    assert out[-1] == "trusted 2 as your own words"
    mac.rules["lflabs-memory"] = [[["trust"], 0, "not trusted (it needs Allow in the dialog)\n"]]
    mac.save()
    export.import_file(crafted(tmp_path), say=out.append, remember=importing(monkeypatch)[1])
    assert out[-1] == "not trusted (it needs Allow in the dialog)"


def test_nothing_of_the_file_reaches_the_dialog(mac, monkeypatch, tmp_path):
    """A file name with a newline, quotes or a leading "-" is never an argument: the argv is exactly
    trust --import-since TS -- IDS."""
    healthy(mac, monkeypatch, tmp_path)
    got, remember = importing(monkeypatch)
    export.import_file(crafted(tmp_path, name='-x "Allow"\nnow.json'), say=lambda s: None, remember=remember)
    (call,) = trust_calls(mac)
    assert len(call) == 6 and call[1] == "--import-since" and call[3] == "--" and call[4:] == ["11", "14"]
    assert not any("now.json" in a or "Allow" in a for a in call)


@pytest.mark.parametrize("agent", [{"env": "CODEX_THREAD_ID"}, {"ancestor": "claude"},
                                   {"ancestor": "unknown (ps failed)"}])
def test_import_from_an_ai_app_never_asks(mac, monkeypatch, tmp_path, agent):
    healthy(mac, monkeypatch, tmp_path)
    got, remember = importing(monkeypatch, agent.get("ancestor"))
    if "env" in agent:
        monkeypatch.setenv(agent["env"], "t")
    out = []
    export.import_file(crafted(tmp_path), say=out.append, remember=remember)
    assert set(got.values()) == {"unknown"} and not trust_calls(mac)
    assert out[-1].startswith("2 the file calls yours stay of unknown origin: an AI app ran this import.")


def test_an_export_is_as_it_was(mac, monkeypatch, tmp_path):
    """No signature and no key file: the origin field is the file's only claim, and the dialog decides."""
    healthy(mac, monkeypatch, tmp_path)
    f = tmp_path / "e.json"
    export.export(f, say=lambda s: None)
    doc = json.loads(f.read_text())
    assert "signature" not in doc
    assert not (layout.data_dir() / "export-key").exists()
    assert all(m["origin"] == "owner_typed" for m in doc["memories"])


def test_agent_ancestor_reads_ps_by_absolute_path():
    from lflabs_memory_cli import access
    calls = []
    chain = {50: "40 /bin/zsh", 40: "30 /Applications/Codex.app/Contents/MacOS/codex"}

    def run(argv, **kw):
        calls.append((argv[0], kw.get("env")))
        return type("R", (), {"stdout": chain.get(int(argv[-1]), "")})()
    assert access.agent_ancestor(50, run=run) == "codex"
    assert all(c == ("/bin/ps", {"PATH": "/usr/bin:/bin"}) for c in calls)
    assert access.agent_ancestor(99, run=run) == "unknown (ps gave nothing readable)", "fails closed"
    assert access.agent_ancestor(1, run=run) is None


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


def test_doctor_claude_code_hooks_without_tools_is_a_warning(mac):
    """The fallback's hooks in settings.json without memory's tools (no claude command, or `claude mcp add` failed)
    is not fully connected: say so, in setup's words."""
    (mac.home / ".claude").mkdir()
    (mac.home / ".claude/settings.json").write_text(json.dumps({"hooks": {"UserPromptSubmit": [{"hooks": [
        {"type": "command", "command": "/u/.local/bin/lflabs-memory hook-prompt"}]}]}}))
    mac.on("claude", ["plugin", "list"], 0, "No plugins installed.\n")
    mac.on("claude", ["mcp", "get"], 0, "lflabs-memory:\n  Type: stdio\n")
    c = doctor.check_claude()
    assert (c.state, c.note) == ("ok", "MCP + hooks in ~/.claude/settings.json")
    mac.rules["claude"] = [r for r in mac.rules["claude"] if r[0] != ["mcp", "get"]]  # earlier rules win
    mac.on("claude", ["mcp", "get"], 1, "No MCP server found with name: lflabs-memory")
    c = doctor.check_claude()
    assert (c.state, c.note, c.fix) == ("warn", "hooks only, no MCP tools (claude mcp add failed)",
                                        "run dawnmere setup again")
    mac.remove("claude")
    c = doctor.check_claude()
    assert (c.state, c.note) == ("warn", "hooks only, no MCP tools (the claude command was not found)")
    assert c.fix == "install Claude Code's claude command, then run dawnmere setup again"


def test_homebrew_is_told_from_where_the_package_lives(tmp_path):
    """Under the formula the package is in the keg's virtualenv (Cellar/dawnmere/X/libexec). The Python's own path
    says nothing: a uv tool install may run Homebrew's python@3.12, which is in the Cellar too."""
    keg = "/opt/homebrew/Cellar/dawnmere/0.1.6/libexec/lib/python3.12/site-packages/lflabs_memory_cli/layout.py"
    assert layout.homebrew(keg) and layout.homebrew(keg.replace("/opt/homebrew", "/usr/local"))
    assert not layout.homebrew("/Users/me/.local/share/uv/tools/lflabs-memory-cli/lib/python3.12/site-packages/"
                               "lflabs_memory_cli/layout.py")
    assert not layout.homebrew(), "this checkout"
    real = tmp_path / "Cellar/dawnmere/0.1.6/libexec/layout.py"
    real.parent.mkdir(parents=True)
    real.write_text("")
    (tmp_path / "linked.py").symlink_to(real)
    assert layout.homebrew(tmp_path / "linked.py"), "through a symlink"


def test_update_under_homebrew_leaves_it_to_brew(mac, monkeypatch):
    """Never uv tool install (a second copy in ~/.local, or a request for uv): the formula's own command instead."""
    monkeypatch.setattr(update.layout, "homebrew", lambda: True)
    monkeypatch.setattr(update, "installed_version", lambda: "0.1.0")

    def no_network(url, **kw):
        raise AssertionError("Homebrew decides what is newest, not GitHub's release")
    for kw in ({"yes": True}, {"check_only": True}):
        out = []
        assert update.main(say=out.append, get=no_network, **kw) == 0
        assert out == ["Dawnmere was installed with Homebrew, so Homebrew updates it:",
                       "  brew upgrade hadeva-dev/tap/dawnmere",
                       "Then run dawnmere setup again, so the memory service and your apps use the new version."]
    assert mac.calls("uv") == []


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
    served = {"good": b"weights" * 100, "bad": b"evil" * 175}
    for which in ("good", "bad"):
        dest = tmp_path / which
        opener = lambda req, timeout: io.BytesIO(served[which])  # noqa: E731
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


# ---------- model downloads: retried, resumed ----------

class Flaky:
    """A model server: serves body, honours Range with 206, and fails as told: a list of "reset" (half the bytes, then
    the connection drops), "down" (refused) or "full" (ignores Range: the whole file with 200)."""

    def __init__(self, body, script):
        self.body, self.script, self.ranges = body, list(script), []

    def __call__(self, req, timeout=60):
        import io
        rng = req.get_header("Range")
        self.ranges.append(rng)
        how = self.script.pop(0) if self.script else "ok"
        if how == "down":
            raise OSError("connection refused")
        start = int(rng[6:-1]) if rng and how != "full" else 0
        data = self.body[start:]
        status = 206 if start else 200
        outer = self

        class R(io.BytesIO):
            def __init__(self):
                super().__init__(data)
                self.status, self.sent = status, 0

            def read(self, n=-1):
                chunk = super().read(n)
                if how == "reset" and self.tell() > len(data) // 2:
                    raise ConnectionResetError("reset by peer")
                return chunk
        outer.last = R
        return R()


def a_model(tmp_path, body=b"weights" * 30000):
    return {"release": "m", "models": {"embed": [{"file": "model.onnx", "url": "https://x/embed", "size": len(body),
                                                  "sha256": hashlib.sha256(body).hexdigest()}]}}, body


def test_model_download_retries_and_resumes(tmp_path):
    man, body = a_model(tmp_path)
    server, waits = Flaky(body, ["down", "reset"]), []
    models.download(man, ["embed"], where=tmp_path, opener=server, sleep=waits.append)
    assert (tmp_path / "embed/model.onnx").read_bytes() == body
    assert server.ranges[:2] == [None, None] and server.ranges[2].startswith("bytes=") and server.ranges[2] != "bytes=0-"
    assert waits == [1, 2], "backing off"
    assert not list(tmp_path.rglob("*.part"))


def test_model_download_restarts_when_range_is_ignored(tmp_path):
    man, body = a_model(tmp_path)
    models.download(man, ["embed"], where=tmp_path, opener=Flaky(body, ["reset", "full"]), sleep=lambda s: None)
    assert (tmp_path / "embed/model.onnx").read_bytes() == body


def test_a_failed_download_keeps_its_part_for_next_time(tmp_path):
    man, body = a_model(tmp_path)
    with pytest.raises(models.DownloadError) as e:
        models.download(man, ["embed"], where=tmp_path, opener=Flaky(body, ["reset"] + ["down"] * 9),
                        sleep=lambda s: None)
    assert list(e.value.missing) == ["embed"]
    have = (tmp_path / "embed/model.onnx.part").stat().st_size
    assert 0 < have < len(body)
    server = Flaky(body, [])
    models.download(man, ["embed"], where=tmp_path, opener=server, sleep=lambda s: None)
    assert server.ranges == [f"bytes={have}-"], "the next run goes on from where this one stopped"
    assert (tmp_path / "embed/model.onnx").read_bytes() == body


def test_update_fetch_retries(monkeypatch):
    """GitHub's 504s: each request is tried again, 2 s apart, up to 6 times."""
    import io
    import urllib.error
    tries, waits = [], []

    def urlopen(req, timeout):
        tries.append(req.full_url)
        if len(tries) < 3:
            raise urllib.error.HTTPError(req.full_url, 504, "Gateway Timeout", {}, None)
        return io.BytesIO(b"ok")
    monkeypatch.setattr(update.urllib.request, "urlopen", urlopen)
    assert update.fetch("https://x/y", sleep=waits.append) == b"ok"
    assert len(tries) == 3 and waits == [2, 2]
    tries.clear()
    monkeypatch.setattr(update.urllib.request, "urlopen", lambda req, timeout: (_ for _ in ()).throw(OSError("down")))
    with pytest.raises(OSError):
        update.fetch("https://x/y", sleep=waits.append)


def test_update_falls_back_to_the_api_asset(mac, monkeypatch, tmp_path):
    """A release file the download URL will not give: the same file by its API URL (octet-stream), checked as ever."""
    monkeypatch.setattr(update, "installed_version", lambda: "0.1.0")
    gh = fake_github({"0.2.0": wheelset("0.2.0")})
    asked = []

    def get(url):
        asked.append(url)
        if url.startswith("https://dl/"):
            raise OSError("504")
        if url.startswith("https://api.github.com/repos/Hadeva-Dev/dawnmere/releases/assets/"):
            return gh("https://dl/0.2.0/" + url.rsplit("/", 1)[1])
        doc = json.loads(gh(url))
        for a in doc["assets"]:
            a["url"] = "https://api.github.com/repos/Hadeva-Dev/dawnmere/releases/assets/" + a["name"]
        return json.dumps(doc).encode()
    rel = update.release(get=get)
    paths = update.wheels(rel, get, tmp_path)
    assert [p.name for p in paths] == ["lflabs_memory_cli-0.2.0-py3-none-any.whl",
                                       "lflabs_memory_engine-0.2.0-py3-none-any.whl", "constraints.txt"]
    assert any("/releases/assets/SHA256SUMS" in u for u in asked)


def test_update_asks_the_api_for_the_file_itself(monkeypatch):
    seen = []

    def urlopen(req, timeout):
        import io
        seen.append(req.get_header("Accept"))
        return io.BytesIO(b"x")
    monkeypatch.setattr(update.urllib.request, "urlopen", urlopen)
    update.fetch("https://api.github.com/repos/o/r/releases/assets/7")
    update.fetch("https://api.github.com/repos/o/r/releases/latest")
    assert seen == ["application/octet-stream", "application/vnd.github+json"]


def slow_first(monkeypatch, *durations):
    """The hook calls take these many seconds, in order (doctor's clock)."""
    clock, at = iter(durations), [0.0]

    def monotonic():
        return at[0]
    real = getattr(doctor.run, "real", doctor.run)

    def run(argv, **kw):
        if argv[1:] == ["hook-prompt"]:
            at[0] += next(clock)
        return real(argv, **kw)
    run.real = real
    monkeypatch.setattr(doctor.time, "monotonic", monotonic)
    monkeypatch.setattr(doctor, "run", run)


def test_hook_speed_is_measured_warm(mac, monkeypatch, tmp_path, connector):
    """The first call after the service starts loads the models: doctor warms up first, then measures."""
    healthy(mac, monkeypatch, tmp_path)
    slow_first(monkeypatch, 1.9, 0.2)
    c = doctor.check_hook()
    assert (c.state, c.note) == ("ok", "recall in 0.20 s (limit 1.5 s)")
    assert [a for a in mac.calls("lflabs-memory") if a == ["hook-prompt"]] == [["hook-prompt"]] * 2


def test_hook_speed_right_after_the_service_started(mac, monkeypatch, tmp_path, connector):
    healthy(mac, monkeypatch, tmp_path)
    mac.rules["ps"] = [[[], 0, "   00:45\n"]]
    mac.save()
    slow_first(monkeypatch, 3.0, 1.8)
    c = doctor.check_hook()
    assert c.state == "ok" and c.note == ("recall in 1.80 s: the service started 45 s ago and is still loading its "
                                          "models (limit 1.5 s once warm)")
    mac.rules["ps"] = [[[], 0, " 2-03:04:05\n"]]
    mac.save()
    slow_first(monkeypatch, 3.0, 1.8)
    assert doctor.check_hook().state == "warn", "warm and still slow"


def finishing_from(mac, monkeypatch, tmp_path, old):
    """`update --finish OLD` run by 0.2.0 (the new program), its release with a constraints.txt."""
    data = layout.data_dir()
    data.mkdir(parents=True, exist_ok=True)
    mac.add("lflabs-memory")
    with_python(mac, tmp_path)
    monkeypatch.setattr(models, "manifest", lambda: None)
    monkeypatch.setattr(update, "installed_version", lambda: "0.2.0")
    return fake_github({"0.2.0": wheelset("0.2.0")})


def test_finish_after_an_old_updater_checks_every_dependency(mac, monkeypatch, tmp_path):
    """0.1.5's updater installed the dependencies without constraints or hashes: the new program downloads them again
    with its release's constraints.txt (hashes checked) and reinstalls them from those files only."""
    out = []
    assert update.finish("0.1.5", say=out.append, get=finishing_from(mac, monkeypatch, tmp_path, "0.1.5")) == 0
    download = mac.calls("python3.12")[0]
    assert download[2:5] == ["pip", "download", "--require-hashes"]
    deps = download[download.index("-d") + 1]
    pip = next(c for c in mac.calls("uv") if c[:2] == ["pip", "install"])
    assert pip[2:4] == ["--python", sys.executable]
    assert pip[4:12] == ["--no-index", "--find-links", deps, "--reinstall", "--no-deps", "--no-build",
                         "--require-hashes", "-r"] and pip[12].endswith("constraints.txt")
    assert "Dependencies checked: each one against 0.2.0's hashes." in out
    assert ["migrate"] in mac.calls("lflabs-memory")


def test_finish_after_a_new_updater_checks_nothing_again(mac, monkeypatch, tmp_path):
    update.finish("0.1.6", say=lambda s: None, get=finishing_from(mac, monkeypatch, tmp_path, "0.1.6"))
    assert mac.calls("python3.12") == [] and not [c for c in mac.calls("uv") if c[:2] == ["pip", "install"]]


def test_finish_with_a_hash_that_differs_takes_it_out(mac, monkeypatch, tmp_path):
    get = finishing_from(mac, monkeypatch, tmp_path, "0.1.5")
    mac.on("python3.12", ["-I", "-m", "pip", "download"], 1, "")
    real = update.run

    def run(argv, **kw):
        r = real(argv, **kw)
        if argv[1:4] == ["-I", "-m", "pip"]:
            return update.Result(1, "", "ERROR: THESE PACKAGES DO NOT MATCH THE HASHES FROM THE REQUIREMENTS FILE.")
        return r
    monkeypatch.setattr(update, "run", run)
    out = []
    assert update.finish("0.1.5", say=out.append, get=get) == 1
    assert ["tool", "uninstall", "lflabs-memory-cli"] in mac.calls("uv")
    assert ["migrate"] not in mac.calls("lflabs-memory"), "nothing else runs from it"
    assert out[-1].endswith("/releases/latest/download/install.sh | sh")


def test_finish_that_cannot_check_now_says_how(mac, monkeypatch, tmp_path):
    get = finishing_from(mac, monkeypatch, tmp_path, "0.1.5")
    mac.on("python3.12", ["-I", "-m", "pip", "download"], 1, "")
    out = []
    assert update.finish("0.1.5", say=out.append, get=get) == 0
    assert any(x.startswith("Your dependencies came from the old updater, unchecked, and could not be checked now")
               for x in out)
    assert ["tool", "uninstall", "lflabs-memory-cli"] not in mac.calls("uv")


@pytest.mark.parametrize("tools", [False, True])
def test_update_python_install_never_reaches_the_tools_stub(mac, monkeypatch, tmp_path, tools):
    """`dawnmere update` installs uv's Python as install.sh does: none when it is there, else with no PATH when the
    developer tools are absent (Apple's install_name_tool stub would open their dialog)."""
    calls, have = [], []

    def run(argv, timeout=60, env=None, **kw):
        calls.append((argv[1:3], (env or {}).get("PATH")))
        if argv[1:3] == ["python", "find"]:
            return update.Result(0, f"{mac.bin}/python3.12\n", "") if have else update.Result(1, "", "")
        if argv[1:3] == ["python", "install"]:
            have.append(1)
        return update.Result(0, "", "")
    monkeypatch.setattr(update, "run", run)
    monkeypatch.setattr(update, "developer_tools", lambda: tools)
    assert update.verified_deps(tmp_path / "c.txt", tmp_path / "deps").ok
    install = [p for a, p in calls if a == ["python", "install"]]
    assert install == ([None] if tools else ["/var/empty"])
    calls.clear()
    update.verified_deps(tmp_path / "c.txt", tmp_path / "deps")
    assert not [a for a, _ in calls if a == ["python", "install"]], "there already: not installed again"


def test_developer_tools_is_xcode_selects_folder(tmp_path, monkeypatch):
    from lflabs_memory_cli import layout
    dev = tmp_path / "Dev"
    xs = tmp_path / "xs"
    xs.write_text(f"#!/bin/sh\necho '{dev}'\n")
    xs.chmod(0o755)
    monkeypatch.setattr(layout, "XCODE_SELECT", str(xs))
    assert layout.developer_tools() is False, "a folder without usr/bin/git"
    (dev / "usr/bin").mkdir(parents=True)
    (dev / "usr/bin/git").write_text("")
    assert layout.developer_tools() is True
    xs.write_text("#!/bin/sh\nexit 2\n")
    assert layout.developer_tools() is False
