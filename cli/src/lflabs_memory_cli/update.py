"""update: the newest release from GitHub, installed with its checksums checked (spec 9.6). Under the Homebrew formula
it only says how to update with brew (layout.homebrew).

The only network call is GitHub's release API (and the release's own files). Two halves:
1. this (old) program fetches the release, checks each wheel and constraints.txt against the release's SHA256SUMS and
   installs them with uv: every dependency first downloaded and checked against the hash the release recorded, then
   installed from those files only;
2. the newly installed program finishes (`update --finish FROM`): models whose checksum changed, the engine's schema
   migration on a stopped service with a snapshot first, the service restarted, the plugin moved to the new release's
   tag and the connector pins updated. A failed migration puts the snapshot back and reinstalls the old release.
"""
import hashlib
import http.client
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import time
import urllib.request
from importlib import metadata
from pathlib import Path

from . import apps, claude_settings, edits, install_record, launchd, layout, models, prompt
from .brand import COMMAND, PRODUCT, REPO
from .layout import (CLI_DIST, CONNECTOR, CONNECTOR_VERSION, ENGINE_DIST, LABEL, MARKETPLACE, OLD_MARKETPLACE,
                     OLD_SERVER, SERVER, data_dir, developer_tools, engine_bin, engine_record, home, short, uv_bin)
from .run import Result, run

API = f"https://api.github.com/repos/{REPO}/releases"
LOCK = "constraints.txt"   # every dependency of the two wheels, pinned with its hashes (RELEASING.md step 2)
NOT_VERIFIED = "a dependency could not be downloaded or did not match its hash"
INSTALL_LINE = f"curl -fsSL https://github.com/{REPO}/releases/latest/download/install.sh | sh"


def vtuple(v):
    return tuple(int(x) for x in re.findall(r"\d+", v or "0")[:3])


def installed_version():
    try:
        return metadata.version(CLI_DIST)
    except metadata.PackageNotFoundError:
        return "0"


def fetch(url, timeout=30, tries=6, sleep=None):
    """GET url, tried up to `tries` times 2 s apart (GitHub has answered 504 for minutes at a time). An API asset URL
    asks for the file itself (octet-stream), anything else for the API's JSON."""
    accept = "application/octet-stream" if "/releases/assets/" in url else "application/vnd.github+json"
    req = urllib.request.Request(url, headers={"Accept": accept, "User-Agent": f"{CLI_DIST}/{installed_version()}"})
    for n in range(1, tries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except (OSError, http.client.HTTPException):
            if n == tries:
                raise
            (sleep or time.sleep)(2)


def release(tag=None, get=fetch):
    """The latest release (or one tag's): {"version", "notes", "assets": {name: url}, "api": {name: API url}}."""
    doc = json.loads(get(f"{API}/tags/{tag}" if tag else f"{API}/latest"))
    return {"version": doc["tag_name"].lstrip("v"), "notes": doc.get("body") or "",
            "assets": {a["name"]: a["browser_download_url"] for a in doc.get("assets", [])},
            "api": {a["name"]: a["url"] for a in doc.get("assets", []) if a.get("url")}}


def asset(rel, name, get=fetch):
    """One release file: from its download URL, else (that kept failing) the same file through the API."""
    try:
        return get(rel["assets"][name])
    except (OSError, http.client.HTTPException):
        if name not in rel.get("api", {}):
            raise
        return get(rel["api"][name])


def wheels(rel, get=fetch, where=None, need_lock=True):
    """Download the release's CLI and engine wheels and its constraints.txt into `where`, each checked against
    SHA256SUMS. [cli, engine, constraints] paths; constraints is None for a release without one when need_lock is
    False (one from before 0.1.6). Raises RuntimeError on a missing file or a checksum that differs."""
    sums = {}
    if "SHA256SUMS" not in rel["assets"]:
        raise RuntimeError("the release has no SHA256SUMS")
    for line in asset(rel, "SHA256SUMS", get).decode().splitlines():
        parts = line.split()
        if len(parts) == 2:
            sums[parts[1].lstrip("*")] = parts[0]
    out = []
    for kind, pick in (("lflabs_memory_cli-*.whl", lambda n: n.startswith("lflabs_memory_cli-") and n.endswith(".whl")),
                       ("lflabs_memory_engine-*.whl", lambda n: n.startswith("lflabs_memory_engine-") and
                        n.endswith(".whl")), (LOCK, lambda n: n == LOCK)):
        name = next((n for n in rel["assets"] if pick(n)), None)
        if not name or name not in sums:
            if kind == LOCK and not need_lock:
                out.append(None)
                continue
            raise RuntimeError(f"the release has no checked {kind}: nothing was installed")
        data = asset(rel, name, get)
        if hashlib.sha256(data).hexdigest() != sums[name]:
            raise RuntimeError(f"{name} did not match its checksum: nothing was installed")
        p = Path(where) / name
        p.write_bytes(data)
        out.append(p)
    return out


def verified_deps(lock, where):
    """Every dependency in lock downloaded into `where` by pip, each file checked against its hash there (uv tool
    install does not check the hashes in a constraints file, uv 0.12.5), with uv's own Python 3.12. Nothing of
    theirs runs and nothing is installed. A Result."""
    uv = uv_bin() or shutil.which("uv") or "uv"
    r = run([uv, "python", "find", "--managed-python", "3.12"], timeout=60)
    if not r.ok:  # `uv python install` runs install_name_tool, whose stub opens the developer-tools dialog: as in
        # install.sh, without the tools it runs with no PATH (uv then only warns that it could not rename the library)
        env = None if developer_tools() else {**os.environ, "PATH": "/var/empty"}
        r = run([uv, "python", "install", "--managed-python", "--no-bin", "3.12"], timeout=600, env=env)
        if r.ok:
            r = run([uv, "python", "find", "--managed-python", "3.12"], timeout=60)
    if not r.ok or not r.out.strip():
        return Result(r.code or 1, "", f"uv has no Python 3.12 ({(r.err or r.out).strip()[-200:]})")
    return run([r.out.strip(), "-I", "-m", "pip", "download", "--require-hashes", "--only-binary", ":all:", "--no-deps",
                "--no-cache-dir", "--disable-pip-version-check", "-q", "-r", str(lock), "-d", str(where)], timeout=900)


def install_wheels(cli_whl, engine_whl, lock=None):
    """(Result, landed): with a lock, the dependencies are downloaded and hash-checked first, and uv tool install then
    takes only those files (--no-index) and the two wheels, so only checked files can land. landed is False when it
    stopped before uv tool install ran (nothing was installed)."""
    pins = []
    if lock:
        deps = Path(lock).parent / "deps"
        d = verified_deps(lock, deps)
        if not d.ok:
            return Result(d.code, "", f"{NOT_VERIFIED}: nothing was installed ({(d.err or d.out).strip()[-300:]})"), \
                False
        pins = ["--no-index", "--find-links", str(deps), "--no-build", "--no-cache", "-c", str(lock)]
    r = run([uv_bin() or "uv", "tool", "install", "--force", "--managed-python", "--python", "3.12", *pins,
             str(cli_whl), "--with", str(engine_whl), "--with-executables-from", ENGINE_DIST], timeout=600)
    return r, True


def quarantine():
    """Take the installed programs out so nothing can load them: uv tool uninstall, else move the environment aside."""
    uv = uv_bin() or "uv"
    if run([uv, "tool", "uninstall", CLI_DIST], timeout=120).ok:
        return
    tools = run([uv, "tool", "dir"], timeout=30).out.strip()
    env = Path(tools) / CLI_DIST if tools else None
    if env and env.exists():
        env.rename(env.with_name(f"{CLI_DIST}.quarantined-{int(time.time())}"))


def reinstall(version, get, say, unpinned=False):
    """Put a release back, its dependencies checked as above. A release from before 0.1.6 has no constraints.txt: put
    back as it was installed when unpinned, else refused. Raises on failure."""
    with tempfile.TemporaryDirectory() as tmp:
        cli_whl, engine_whl, lock = wheels(release(f"v{version}", get), get, tmp, need_lock=False)
        if lock is None and not unpinned:
            raise RuntimeError(f"{version} has no {LOCK} to check it against")
        if lock is None:
            say(f"{version} has no {LOCK}, so it goes back without pinned dependencies, as it was installed.")
        r, _ = install_wheels(cli_whl, engine_whl, lock)
        if not r.ok:
            raise RuntimeError((r.err or r.out).strip()[:200])


def fail_closed(version, get, say):
    """After an install that went wrong once something had landed: never leave that environment in place. Take it out,
    then put `version` back the checked way; failing that, leave nothing installed and say how to install again."""
    quarantine()
    try:
        reinstall(version, get, say)
        say(f"Back on {version}.")
    except Exception as e:
        quarantine()
        say(f"Could not reinstall {version} ({e}), so {PRODUCT} is uninstalled. Install it again with:")
        say(f"  {INSTALL_LINE}")
    return 1


def main(check_only=False, yes=False, say=print, get=fetch):
    if layout.homebrew():  # the formula's files are Homebrew's: uv tool install would put a second copy in ~/.local
        say(f"{PRODUCT} was installed with Homebrew, so Homebrew updates it:")
        say(f"  brew upgrade {layout.BREW_FORMULA}")
        say(f"Then run {COMMAND} setup again, so the memory service and your apps use the new version.")
        return 0
    have = installed_version()
    try:
        rel = release(get=get)
    except Exception:
        say("Could not reach GitHub to check for an update. Try again later.")
        return 1
    if vtuple(rel["version"]) <= vtuple(have):
        say(f"{PRODUCT} {have} is the newest.")
        return 0
    say(f"{PRODUCT} {rel['version']} is out (you have {have}).")
    for line in [x for x in rel["notes"].splitlines() if x.strip()][:5]:
        say(f"  {line}")
    if check_only:
        return 0
    if not prompt.yes_no("Update now?", True, assume=True if yes else None):
        return 0
    with tempfile.TemporaryDirectory() as tmp:
        try:
            cli_whl, engine_whl, lock = wheels(rel, get, tmp)
        except Exception as e:
            say(f"Update stopped: {e}")
            return 1
        r, landed = install_wheels(cli_whl, engine_whl, lock)
        if not r.ok and not landed:
            say(f"Update stopped: {r.err}")  # you are still on `have`, untouched
            return 1
        if not r.ok:
            say(f"Update stopped: uv could not install it ({(r.err or r.out).strip()[:200]}). Putting {have} back.")
            return fail_closed(have, get, say)
    # the new program finishes: its models list, its migrations, its connector version
    new = Path(engine_bin() or "").with_name(COMMAND) if engine_bin() else None
    argv = [str(new) if new and new.exists() else COMMAND, "update", "--finish", have]
    os.execvp(argv[0], argv)


def snapshot():
    """A consistent copy of the store before the migration (None when there is no store)."""
    src = data_dir() / "memory.db"
    if not src.exists():
        return None
    dst = data_dir() / "backup" / f"memory-{time.strftime('%Y-%m-%d-%H%M%S')}-before-update.db"
    dst.parent.mkdir(parents=True, exist_ok=True)
    a, b = sqlite3.connect(src), sqlite3.connect(dst)
    try:
        a.backup(b)
    finally:
        a.close()
        b.close()
    os.chmod(dst, 0o600)
    return dst


def put_back(snap):
    db = data_dir() / "memory.db"
    for extra in ("-wal", "-shm"):
        Path(str(db) + extra).unlink(missing_ok=True)
    a, b = sqlite3.connect(snap), sqlite3.connect(db)
    try:
        a.backup(b)
    finally:
        a.close()
        b.close()


def rename_entries(say):
    """Our MCP entry under its name from before 0.1.10, in every app's file and in Claude Code's fallback (`claude mcp
    add`), renamed to SERVER; each file change recorded in install.json, as setup records its own."""
    rec = install_record.load()
    for app in ("codex", "cursor", *apps.MCP_ONLY):
        plan = apps.plan_rename(app)
        if plan is None:
            continue
        if plan.state != "add":
            say(f"{short(plan.path)}: {plan.note}")
            continue
        try:
            apps.apply(plan, rec if rec is not None else install_record.empty())
            say(f"{short(plan.path)}: {plan.note}")
        except edits.Skip as e:
            say(f"{short(plan.path)}: {e}")
    if rec is not None:
        install_record.save(rec)
    if shutil.which("claude") and apps.old_claude_mcp():
        add = ["claude", "mcp", "add", "--scope", "user", "--transport", "stdio", SERVER, "--", "npx",
               *apps.connector_args()]
        if run(["claude", "mcp", "remove", "--scope", "user", OLD_SERVER], timeout=30).ok and run(add, timeout=30).ok:
            if rec is not None:
                install_record.add_command(rec, add, True)
                install_record.save(rec)
            say(f"Claude Code: MCP entry {OLD_SERVER} renamed to {SERVER}")


def bump_pins(say, record=None):
    """Point Codex's and Cursor's entries at this version of the connector, each change recorded in install.json (so
    uninstall still puts the user's file back). record: the one setup holds; else install.json is loaded and saved."""
    pin = f"{CONNECTOR}@{CONNECTOR_VERSION}"
    rec = record if record is not None else install_record.load()
    old_pin = re.compile(re.escape(CONNECTOR) + r"@[0-9][\w.\-]*")
    for app, kind, path in (("codex", "codex-toml", home() / ".codex/config.toml"),
                            ("cursor", "mcp-json", home() / ".cursor/mcp.json"),
                            *((a, "mcp-json", home() / v[2]) for a, v in apps.MCP_ONLY.items())):
        try:
            old = edits.read(path)
        except edits.Skip:
            continue
        if not old or pin in old or f"{CONNECTOR}@" not in old:
            continue
        new = old_pin.sub(pin, old)
        plan = apps.Plan(app, kind, path, "add", f"connector now {CONNECTOR_VERSION}", new=new, old=old)
        prev = install_record.file_entry(rec, plan) if rec else None
        plan.added = old_pin.sub(pin, prev["added"]) if prev and prev.get("added") else ""
        try:
            (edits.load_toml if path.suffix == ".toml" else edits.load_json)(new)
            apps.apply(plan, rec if rec is not None else install_record.empty())
            say(f"{short(path)}: connector now {CONNECTOR_VERSION}")
        except edits.Skip as e:
            say(f"{short(path)}: {e}")
    if rec is not None and record is None:
        install_record.save(rec)


def move_plugin(say, listed=""):
    """The marketplace was added at the old release's tag, and a marketplace's ref cannot be changed in place: remove
    it (that uninstalls the plugin too), add it at this release's tag, install the plugin from it again. A plugin
    under its name from before 0.1.10 (listed: `claude plugin list`) goes with its marketplace the same way."""
    v = installed_version()
    gone = [["claude", "plugin", "uninstall", claude_settings.OLD_PLUGIN_ID, "--scope", "user"],
            ["claude", "plugin", "marketplace", "remove", OLD_MARKETPLACE]] \
        if claude_settings.OLD_PLUGIN_ID in listed else []
    gone += [["claude", "plugin", "marketplace", "remove", MARKETPLACE]] if claude_settings.PLUGIN_ID in listed else []
    for argv in gone:
        run(argv, timeout=120)
    steps = [["claude", "plugin", "marketplace", "add", apps.marketplace_source(v), "--scope", "user"],
             ["claude", "plugin", "install", claude_settings.PLUGIN_ID, "--scope", "user", "-y"]]
    if all(run(argv, timeout=120).ok for argv in steps):
        say(f"Claude Code's plugin: now v{v} (restart Claude Code to load it)")
    else:
        say(f"Claude Code's plugin could not move to v{v}: run {COMMAND} setup again")


FIRST_VERIFIED = (0, 1, 6)  # the first release whose updater checks every dependency against constraints.txt


def reverify(say, get=fetch):
    """For an update made by an older updater (before 0.1.6), which installed the dependencies unchecked: download
    them again with this release's constraints.txt, every hash checked, then reinstall them into this environment
    from those files only. False when a hash did not match (the environment is then taken out: quarantine)."""
    v = installed_version()
    with tempfile.TemporaryDirectory() as tmp:
        try:
            rel = release(f"v{v}", get)
            lock = wheels(rel, get, tmp)[2]
            deps = Path(tmp) / "deps"
            d = verified_deps(lock, deps)
        except Exception as e:
            d = Result(1, "", str(e))
        if d.ok:
            r = run([uv_bin() or "uv", "pip", "install", "--python", sys.executable, "--no-index", "--find-links",
                     str(deps), "--reinstall", "--no-deps", "--no-build", "--require-hashes", "-r", str(lock)],
                    timeout=900)
            if r.ok:
                say(f"Dependencies checked: each one against {v}'s hashes.")
                return True
            d = r
    why = (d.err or d.out).strip()
    if "DO NOT MATCH THE HASHES" in why or "Hash mismatch" in why:
        say(f"A dependency did not match {v}'s hashes, so {PRODUCT} is taken out. Install it again with:")
        say(f"  {INSTALL_LINE}")
        quarantine()
        return False
    say(f"Your dependencies came from the old updater, unchecked, and could not be checked now ({why[-200:]}). To "
        f"have them checked, run the install line again: {INSTALL_LINE}")
    return True


def finish(old_version, say=print, get=fetch):
    """Run by the newly installed program. 0 when updated; 1 after a rollback (or a dependency whose hash did not
    match, when an updater from before 0.1.6 installed this one)."""
    if vtuple(old_version) < FIRST_VERIFIED and not reverify(say, get):
        return 1
    man = models.manifest()
    if man:
        stale = [n for n, s in models.check(man).items() if s == "mismatch" or (s == "missing" and n not in
                                                                                 models.OPTIONAL + models.LAZY)]
        if stale:
            try:
                models.download(man, stale)
                say(f"Models updated: {', '.join(stale)}")
            except Exception as e:
                say(f"Models not updated ({e}); {COMMAND} doctor will say what to do.")
    eng = engine_bin()
    run(["launchctl", "bootout", f"{launchd.domain()}/{LABEL}"], timeout=30)
    snap = snapshot()
    r = run([eng, "migrate"], timeout=900) if eng else None
    if r is None or not r.ok:
        say("The new version could not update your memory's format: putting everything back.")
        if snap:
            put_back(snap)
        try:
            reinstall(old_version, get, say, unpinned=True)
        except Exception as e:
            say(f"Could not reinstall {old_version} ({e}): install it again with: {INSTALL_LINE}")
        run(["launchctl", "bootstrap", launchd.domain(), str(launchd.plist_path())], timeout=30)
        say(f"Back on {old_version}; your memory is as it was" + (f" (snapshot: {short(snap)})." if snap else "."))
        return 1
    run(["launchctl", "bootstrap", launchd.domain(), str(launchd.plist_path())], timeout=30)
    run(["launchctl", "kickstart", "-k", f"{launchd.domain()}/{LABEL}"], timeout=30)
    if eng and os.path.isabs(eng) and data_dir().is_dir():  # what the plugin's hooks run (plugin/scripts/engine)
        engine_record().write_text(eng + "\n")
    listed = run(["claude", "plugin", "list"], timeout=30).out if apps.installed("claude-code") else ""
    if claude_settings.PLUGIN_ID in listed or claude_settings.OLD_PLUGIN_ID in listed:
        move_plugin(say, listed)
    rename_entries(say)
    bump_pins(say)
    say(f"{PRODUCT} is updated ({old_version} to {installed_version()}).")
    return 0
