"""Changing another app's config file safely: the engine's connect_apps rules (its "Safe by construction" list),
kept here so the installer never imports the engine just to edit a file (importing it creates the data folder, which
uninstall must not do).

- a file is changed only when the new text parses and holds our entry, only while it still holds what was read (an app
  that rewrote it meanwhile wins), never when it is read-only, and never when it is not plain JSON (comments, a BOM,
  duplicate keys) or not valid TOML: then the lines to add are printed instead;
- the first change to a file copies it first, next to it: <file>.lflabs-backup-<UTC time>, at most 0600 (the user's
  original, which uninstall puts back; a file that already holds a key is never copied);
- TOML is appended to in the file's own line endings; JSON is loaded and written back whole, keeping key order, the
  indent and the line endings;
- a symlinked config is written through the link.
"""
import hashlib
import json
import os
import re
import shutil
import time
import tomllib
from pathlib import Path

from .layout import BACKUP_TAG


class Skip(Exception):
    """A file left as it is, with why (a sentence the user can act on)."""


def read(path):
    """The file's text with its own line endings, or None when there is no file. Raises Skip if it cannot be read."""
    try:
        with open(path, encoding="utf-8", newline="") as f:
            return f.read()
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError) as e:
        raise Skip(f"cannot be read ({type(e).__name__}): left alone")


def sha256(text):
    return hashlib.sha256((text or "").encode()).hexdigest() if text is not None else None


def eol(text):
    return "\r\n" if text and "\r\n" in text else "\n"


def _indent(text):
    m = re.search(r"\n([ \t]+)\S", text or "")
    if not m:
        return 2
    return "\t" if m.group(1).startswith("\t") else len(m.group(1))


def load_json(text):
    """The object in a JSON config, {} for no file or an empty one. Raises Skip for comments, a BOM, duplicate keys or
    a top level that is not an object."""
    if not text or not text.strip():
        return {}
    if text.startswith("﻿"):
        raise Skip("starts with a byte-order mark: left alone; add this by hand")

    def pairs(kv):
        keys = [k for k, _ in kv]
        if len(keys) != len(set(keys)):
            raise Skip("has a key twice: left alone; add this by hand")
        return dict(kv)
    try:
        data = json.loads(text, object_pairs_hook=pairs)
    except ValueError:
        raise Skip("is not plain JSON (comments?): left alone; add this by hand")
    if not isinstance(data, dict):
        raise Skip("is not a JSON object: left alone; add this by hand")
    return data


def dump_json(data, original):
    out = json.dumps(data, indent=_indent(original), ensure_ascii=False)
    out = out + "\n" if not original or original.endswith("\n") else out
    return out.replace("\n", "\r\n") if eol(original) == "\r\n" else out


def load_toml(text):
    try:
        return tomllib.loads(text or "")
    except tomllib.TOMLDecodeError:
        raise Skip("does not parse as TOML: left alone; add these lines by hand")


def append_toml(text, block):
    """text with block appended after one blank line, in the file's own line endings. Raises Skip if it would not
    parse."""
    e = eol(text)
    new = (text or "") + (e if text and not text.endswith(("\n", "\r")) else "") + (e if text else "")
    new += block.replace("\n", e)
    load_toml(new)
    return new


def backup_name(real):
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    b, n = real.with_name(f"{real.name}.{BACKUP_TAG}-{stamp}"), 1
    while b.exists():
        b, n = real.with_name(f"{real.name}.{BACKUP_TAG}-{stamp}-{n}"), n + 1
    return b


def write(path, new, old, secret=False, backup=True):
    """Back up (unless backup is False) and replace one file (through a symlink, keeping its mode), only if it still
    holds `old` and is not read-only. new=None deletes it. secret: the new text holds a key, so the file is made
    readable by its owner only (a stricter mode is kept, never loosened). Returns the backup's path, or None when
    there was none. Raises Skip, and leaves no temp file behind."""
    real = Path(os.path.realpath(path))
    want_backup, mode, backup = backup, 0o600, None
    tmp = real.with_name(real.name + ".lflabs-tmp")
    try:
        if real.exists():
            st = real.stat()
            if not st.st_mode & 0o200:
                raise Skip("is read-only: left alone")
            mode = st.st_mode & 0o777
        if secret:
            mode &= 0o600
        if read(real) != old:
            raise Skip("changed while I was reading it (the app wrote it?): left alone; run this again")
        if old is not None and want_backup:
            backup = backup_name(real)
            shutil.copy2(real, backup)
            os.chmod(backup, real.stat().st_mode & 0o600)
        if new is None:
            real.unlink()
            return backup
        real.parent.mkdir(parents=True, exist_ok=True)
        with os.fdopen(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w", encoding="utf-8",
                       newline="") as f:
            f.write(new)
        os.chmod(tmp, mode)
        if read(real) != old:  # last look: an app that wrote it since wins
            raise Skip("changed while I was writing it: left alone; run this again")
        os.replace(tmp, real)
    except (OSError, UnicodeEncodeError) as e:
        raise Skip(f"not written ({type(e).__name__}); the file is as it was")
    finally:
        tmp.unlink(missing_ok=True)
    return backup


def restore(path, backup, expect):
    """Put a file back from its backup, only while it still holds exactly what we wrote (sha256 `expect`). True when
    restored; False when the user or the app changed it since (then our entries are removed by hand instead)."""
    real = Path(os.path.realpath(path))
    try:
        if sha256(read(real)) != expect or not Path(backup).exists():
            return False
        tmp = real.with_name(real.name + ".lflabs-tmp")
        shutil.copy2(backup, tmp)
        os.chmod(tmp, real.stat().st_mode & 0o777)  # the file's own mode, not the backup's 0600
        if sha256(read(real)) != expect:
            tmp.unlink(missing_ok=True)
            return False
        os.replace(tmp, real)
        return True
    except (OSError, Skip):
        return False
