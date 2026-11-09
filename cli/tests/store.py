"""A small store with the engine's tables (only the columns the CLI reads)."""
import sqlite3
import time

SCHEMA = """
create table memories(id integer primary key, content text not null, kind text not null default 'note', project text,
  hash text not null default '', status text not null default 'active', created real not null, updated real not null,
  section text, origin text, secret text);
create table claims(id integer primary key, content text not null, status text not null default 'active',
  kind text not null default 'user', section text, said_on text, created real not null);
create table llm_usage(day text, job text, calls int, in_tok int, out_tok int, usd real, primary key(day, job));
create table sessions(session_id text primary key, transcript text not null, cwd text, done_line integer not null
  default 0, activity real not null, final integer not null default 0);
create table saves(id integer primary key autoincrement, memory_id integer not null, at real not null, via text not null);
"""


def make(path, memories=(), claims=(), usage=()):
    db = sqlite3.connect(path)
    db.executescript(SCHEMA)
    now = time.time()
    for i, (content, kind, section, *rest) in enumerate(memories, 1):
        secret = rest[0] if rest else None
        db.execute("insert into memories(id, content, kind, section, origin, secret, created, updated, project) "
                   "values (?, ?, ?, ?, 'owner_typed', ?, ?, ?, ?)", (i, content, kind, section, secret, now, now,
                                                                     "shop" if section == "projects" else None))
        db.execute("insert into saves(memory_id, at, via) values (?, ?, 'claude-code')", (i, now))
    for i, c in enumerate(claims, 1):
        db.execute("insert into claims(id, content, created) values (?, ?, ?)", (i, c, now))
    for row in usage:
        db.execute("insert into llm_usage values (?, ?, ?, ?, ?, ?)", row)
    db.commit()
    db.close()
