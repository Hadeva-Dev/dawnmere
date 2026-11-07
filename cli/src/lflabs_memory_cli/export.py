"""export / import: your memory as one file, to keep or to move Macs (spec 9.5).

Secrets (memories the engine marked `secret`) never leave: they are left out and counted. Import goes through the
engine's own remember(), so a memory already there is not added twice; imported memories are labelled "unknown"
origin, never "your own words" (a file can say anything about where it came from).
"""
import json
import os
import sqlite3
import time
from collections import defaultdict
from pathlib import Path

from .brand import COMMAND
from .layout import data_dir, home, short

FORMAT = "lflabs-memory-export/1"
FIELDS = ("id", "content", "kind", "project", "section", "origin", "created", "updated")


def _db():
    p = data_dir() / "memory.db"
    if not p.exists():
        return None
    db = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    return db


def collect(db, include_claims=False):
    """(memories, claims, secrets left out): active ones only."""
    rows = db.execute("select * from memories where status = 'active' order by id").fetchall()
    secrets = sum(1 for r in rows if "secret" in r.keys() and r["secret"])
    mems = [{k: r[k] for k in FIELDS} for r in rows if not ("secret" in r.keys() and r["secret"])]
    claims = []
    if include_claims:
        try:
            claims = [{"id": f"c{r['id']}", "content": r["content"], "kind": r["kind"], "section": r["section"],
                       "said_on": r["said_on"], "created": r["created"]}
                      for r in db.execute("select * from claims where status = 'active' order by id")]
        except sqlite3.Error:
            claims = []
    return mems, claims, secrets


def markdown(mems):
    by = defaultdict(list)
    for m in mems:
        by[m["section"] or "not yet filed"].append(m)
    out = [f"# Memory export, {time.strftime('%Y-%m-%d')}", ""]
    for section in sorted(by):
        out += [f"## {section}", ""]
        for m in by[section]:
            when = time.strftime("%Y-%m-%d", time.localtime(m["updated"]))
            tag = f" ({m['project']})" if m["project"] else ""
            out.append(f"- #{m['id']} {m['kind']}{tag}, {when}: " + m["content"].replace("\n", "\n  "))
        out.append("")
    return "\n".join(out)


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f:
        f.write(text)
    os.chmod(path, 0o600)


def export(out_file=None, fmt="json", include_claims=False, say=print):
    db = _db()
    if db is None:
        say(f"No memory to export yet (run {COMMAND} setup first).")
        return 1
    try:
        mems, claims, secrets = collect(db, include_claims)
    finally:
        db.close()
    ext = "md" if fmt == "md" else "json"
    path = Path(out_file).expanduser() if out_file else \
        home() / "Downloads" / f"{COMMAND}-export-{time.strftime('%Y-%m-%d')}.{ext}"
    if fmt == "md":
        _write(path, markdown(mems))
    else:
        doc = {"format": FORMAT, "exported": time.time(), "memories": mems}
        if include_claims:
            doc["claims"] = claims
        _write(path, json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
    say(f"Exported {len(mems)} memor{'y' if len(mems) == 1 else 'ies'}" +
        (f" and {len(claims)} claim{'' if len(claims) == 1 else 's'}" if include_claims else "") +
        f" to {short(path)} (only you can read it).")
    if secrets:
        say(f"{secrets} secret{'s' if secrets != 1 else ''} left out: they never leave the engine.")
    return 0


def _engine_remember():
    """remember(content, kind, project) through the engine, on its own store."""
    from lflabs_memory import mem  # noqa: the engine is installed with this CLI
    db = mem.connect()

    def save(content, kind, project):
        return mem.remember(db, content, kind, project, origin="unknown", via="import")
    return save


def load_file(path):
    doc = json.loads(Path(path).expanduser().read_text())
    if not isinstance(doc, dict) or doc.get("format") != FORMAT or not isinstance(doc.get("memories"), list):
        raise ValueError(f"not a {FORMAT} file")
    return doc


def import_file(path, say=print, remember=None):
    try:
        doc = load_file(path)
    except (OSError, ValueError) as e:
        say(f"Cannot import {path}: {e}.")
        return 1
    save = remember or _engine_remember()
    added = same = refused = 0
    for m in doc["memories"]:
        content = m.get("content") if isinstance(m, dict) else None
        if not isinstance(content, str) or not content.strip():
            refused += 1
            continue
        mid, action = save(content, m.get("kind") or "note", m.get("project"))
        if mid is None:
            refused += 1
        elif action == "added":
            added += 1
        else:
            same += 1
    say(f"Imported {added} new memor{'y' if added == 1 else 'ies'}; {same} {'was' if same == 1 else 'were'} already "
        "here" + (f"; {refused} refused" if refused else "") + ".")
    return 0
