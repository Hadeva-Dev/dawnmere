"""The setup screen (spec 9.1): the sunrise intro, the live steps, the memory moment.

The logo is the progress bar: the sun rises out of the water as setup does real work. Every frame comes from one pure
function, frame(t, state). Animator draws those frames in place, at most 30 a second, redrawing only the rows that
changed, while the caller does the work and reports it with step(), apps(), memory() and finish(). The screen never
delays the work: a row stays up for at least FLOOR seconds so a 5 ms check is readable, and nothing else waits.
"""
import atexit
import math
import os
import re
import select
import shutil
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field

from .banner_art import ASCII_LOGO, WORDMARK
from .brand import COMMAND, PRODUCT

BLOCK = len(WORDMARK[0])  # 67: the header is centred on this block, and the body starts at its left edge
IND = " "                 # the body's left edge, under the wordmark's first stroke
LABEL = 16                # every result starts in one column: IND + mark + space + LABEL
HOW = 13                  # a tree leaf's "how" column, then its hint
FLOOR = 0.35              # each row is on screen at least this long
INTRO = 2.2               # the steps appear once the ring, horizon and wordmark have drawn
SLOW = 1.5                # a self-check slower than this is a warning
TAGLINE = "one memory for every AI app you use"
SPIN = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
STILL_SPIN = "•"
MIN_WIDTH = 70            # narrower: one spaced name line instead of the art

# xterm-256 colours. Orange is the sun and what the user must do; green is only the tick; grey is finished work.
ORANGE, TRAIL, RIPPLE = 208, 130, 94
GREEN, AMBER, RED = 72, 214, 167
GREY, DIM, DIMMER = 245, 243, 240
ACTIVE, WORD, NAME, BRIGHT = 253, 252, 254, 255
WHITE, CREAM = 231, 223
FLASH = (208, 214, 215, 222, 223, 230)
TAG_FADE = (237, 239, 241, DIM)

# Logo geometry: 22 x 11 braille cells = 44 x 44 dots.
LOGO_COLS, LOGO_ROWS = 22, 11
_W, _H = LOGO_COLS * 2, LOGO_ROWS * 4
_CX, _CY = _W / 2 - 0.5, _H / 2 - 0.5
_R = min(_W, _H) / 2 - 0.5
_HY = 6 * 4 + 1.5                    # horizon: the middle dot rows of cell row 6
_Y1, _Y2 = 7 * 4 + 1.5, 8 * 4 + 1.5  # the two reflection ripples
_SUN_R = 0.42 * _R
SUN_START = 9.5                      # dots below the horizon before any work is done
_BITS = ((0x01, 0x08), (0x02, 0x10), (0x04, 0x20), (0x40, 0x80))


# ---------- state ----------

@dataclass
class Step:
    label: str
    weight: float = 1.0
    apps: bool = False            # this step grows the app tree
    status: str = "pending"       # pending, running, ok, warn, failed
    note: str = ""
    started: float | None = None  # screen clock: seconds since Animator.start()
    ended: float | None = None
    progress: list = field(default_factory=list)  # [(time, bytes done, bytes total)] for a download


@dataclass
class AppResult:
    name: str
    how: str = ""                 # how it was wired: "plugin", "MCP + hook"
    hint: str | None = None       # what the user must do, in orange: "restart Cursor"
    status: str = "pending"       # pending, running, ok, failed
    started: float | None = None
    ended: float | None = None


@dataclass
class ScreenState:
    steps: list
    apps: list = field(default_factory=list)
    memory: str | None = None
    finished: float | None = None  # when setup's work ended
    skipped: float | None = None   # when a key was pressed: jump to the end
    width: int = 80
    height: int = 40
    color: bool = True
    unicode: bool = True
    motion: bool = True            # False: still frames (Reduce Motion, --no-animation)
    plain: bool = False            # plain lines only: no art, colour or escapes
    intro: bool = True             # the full show; False is the short version for a re-run
    expect_apps: int = 3           # for the height check, before the apps are known


# ---------- timeline: when each row is on screen ----------

@dataclass
class _Timeline:
    steps: list   # (start, end or None) per step shown
    leaves: list  # (start, end or None) per app leaf shown
    end: float | None  # when the screen catches up with finished work


def _intro_len(state):
    if not (state.intro and _moving_at_all(state)) or _header(state) == "compact":
        return 0.0
    return INTRO if state.skipped is None else min(INTRO, state.skipped)


def _timeline(state):
    skip = state.skipped

    def floor_end(start):
        end = start + FLOOR
        return end if skip is None else min(end, max(start, skip))

    at, steps, leaves = _intro_len(state), [], []
    for s in state.steps:
        if s.started is None:
            break
        start = max(s.started, at)
        end = None if s.ended is None else max(s.ended, floor_end(start))
        if s.apps:
            leaf_at = start
            for a in state.apps:
                if a.started is None:
                    break
                ls = max(a.started, leaf_at)
                le = None if a.ended is None else max(a.ended, floor_end(ls))
                leaves.append((ls, le))
                if le is None:
                    end = None
                    break
                leaf_at = le
            if end is not None:
                end = max(end, leaf_at)
        steps.append((start, end))
        if end is None:
            break
        at = end
    done = state.finished is not None and (not steps or steps[-1][1] is not None)
    return _Timeline(steps, leaves, max(state.finished, at) if done else None)


def _failed(state):
    return any(s.status == "failed" for s in state.steps)


def done_at(state):
    """When the last frame is up (None while setup still works). The full show ends 3 s after the work."""
    tl = _timeline(state)
    if tl.end is None:
        return None
    if state.plain or _failed(state) or not state.intro or not _moving_at_all(state):
        return tl.end
    if state.skipped is not None:
        return max(tl.end, state.skipped)
    return tl.end + 3.0


# ---------- the sun ----------

def _target(state, tl, t, partial=True):
    """The finished share of the step weights at display time t (a download counts by bytes)."""
    total = sum(s.weight for s in state.steps) or 1.0
    done = 0.0
    for (start, end), s in zip(tl.steps, state.steps):
        if end is not None and t >= end:
            if s.status != "failed":
                done += s.weight
        elif partial and t >= start and s.progress:
            seen = [p for p in s.progress if p[0] <= t]
            if seen and seen[-1][2]:
                done += s.weight * min(1.0, seen[-1][1] / seen[-1][2])
    return min(1.0, done / total)


def _ease(x):
    x = min(1.0, max(0.0, x))
    return 1 - (1 - x) ** 3


def _ease_in_out(x):
    x = min(1.0, max(0.0, x))
    return 4 * x ** 3 if x < 0.5 else 1 - (-2 * x + 2) ** 3 / 2


SUN_EASE = 0.6  # seconds the sun takes to settle at a new height


def sun_progress(state, t):
    """How far the sun has risen, 0..1: the finished share, eased so the sun never jumps. Still frames: no easing."""
    tl = _timeline(state)
    if not _moving(state, t):
        return _target(state, tl, t, partial=False)
    times = sorted({e for _, e in tl.steps if e is not None and e <= t}
                   | {p[0] for (st, _), s in zip(tl.steps, state.steps) for p in s.progress if st <= p[0] <= t}
                   | {st for st, _ in tl.steps if st <= t})
    seg_t, seg_a, seg_b = 0.0, 0.0, 0.0
    for te in times:
        now = seg_a + (seg_b - seg_a) * _ease((te - seg_t) / SUN_EASE)
        seg_t, seg_a, seg_b = te, now, max(now, _target(state, tl, te))
    return seg_a + (seg_b - seg_a) * _ease((t - seg_t) / SUN_EASE)


def sun_offset(state, t):
    """sunOff: dots below the horizon. 9.5 before any work, 0 only once everything is done."""
    return SUN_START * (1 - sun_progress(state, t))


# ---------- drawing helpers ----------

_SGR = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def visible(line):
    """The text a line shows, without colour codes."""
    return _SGR.sub("", line)


def _paint(state):
    def paint(code, text):
        return f"\x1b[38;5;{code}m{text}\x1b[0m" if state.color and text and code is not None else text
    return paint


def _cells(cells, state):
    """[(char, colour or None)] -> one string, a colour code only where the colour changes."""
    if not state.color:
        return "".join(ch for ch, _ in cells).rstrip()
    out, cur = [], None
    for ch, code in cells:
        if ch != " " and code != cur:
            out.append("\x1b[0m" if code is None else f"\x1b[38;5;{code}m")
            cur = code
        out.append(ch)
    text = "".join(out).rstrip()
    return text + "\x1b[0m" if cur is not None else text


def _logo(ring, horizon, sun_off, rip, phase):
    """Rows of [(char, part)], part one of "sun", "rip", "line", "" (spec 9.1 geometry)."""
    rows = []
    for r in range(LOGO_ROWS):
        row = []
        for c in range(LOGO_COLS):
            v, part = 0, ""
            for dy in range(4):
                for dx in range(2):
                    x, y = c * 2 + dx, r * 4 + dy
                    p = _dot(x, y, ring, horizon, sun_off, rip, phase)
                    if p:
                        v |= _BITS[dy][dx]
                        if p == "sun" or (p == "rip" and part != "sun") or not part:
                            part = p
            row.append((chr(0x2800 + v) if v else " ", part))
        rows.append(row)
    return rows


def _dot(x, y, ring, horizon, sun_off, rip, phase):
    dx = x - _CX
    d = math.hypot(dx, y - _CY)
    if _R - 2 <= d <= _R:
        a = math.atan2(dx, -(y - _CY))
        if a < 0:
            a += 2 * math.pi
        if a <= ring * 2 * math.pi + 0.001:
            return "line"
    if y < _HY - 0.6 and math.hypot(dx, y - (_HY + sun_off)) <= _SUN_R:
        return "sun"
    if abs(y - _HY) < 0.6 and d < _R - 3.5 and abs(dx) <= horizon * (_R - 3.5):
        return "line"
    if rip > 0 and abs(y - _Y1) < 0.6 and abs(dx) <= 0.34 * _R * min(1, rip * 2) and (x + phase) % 5:
        return "rip"
    if rip > 0.5 and abs(y - _Y2) < 0.6 and abs(dx) <= 0.16 * _R and (x + phase + 2) % 5:
        return "rip"
    return None


def _moving_at_all(state):
    return state.motion and state.unicode and not state.plain


def _moving(state, t):
    """Animated at time t: not still frames, and no key pressed yet."""
    return _moving_at_all(state) and (state.skipped is None or t < state.skipped)


def _needed_rows(state, logo_rows):
    steps = len(state.steps) + max(state.expect_apps, len(state.apps))
    # logo, gap, wordmark, gap, tagline, gap, steps, gap, app line, memory line, gap, finish (3), the cursor line
    return logo_rows + 1 + len(WORDMARK) + 1 + 1 + 1 + steps + 1 + 2 + 1 + 3 + 1


def _header(state):
    if not state.intro:
        return "none"
    if state.width < MIN_WIDTH:
        return "compact"
    rows = LOGO_ROWS if state.unicode else len(ASCII_LOGO)
    logo = state.height >= max(34, _needed_rows(state, rows))
    if not state.unicode:
        return "ascii" if logo else "ascii-nologo"
    return "full" if logo else "nologo"


def _spaced():
    return " ".join(PRODUCT.upper())


# ---------- the frame ----------

def frame(t, state):
    """Every line on screen at time t (seconds since the first frame). Pure: same t and state, same lines."""
    if state.plain:
        return plain_lines(state)
    tl = _timeline(state)
    lines = _header_lines(t, state, tl) + _body(t, state, tl) + _finale(t, state, tl)
    if not state.unicode:
        lines = [_ascii(line) for line in lines]
    return lines


def _header_lines(t, state, tl):
    kind = _header(state)
    paint = _paint(state)
    if kind == "none":
        return []
    if kind == "compact":
        name = _spaced()
        return [" " * max(0, (state.width - len(name)) // 2) + paint(WORD, name), ""]
    tag_pad = " " * ((BLOCK - len(TAGLINE)) // 2)
    logo_pad = " " * ((BLOCK - LOGO_COLS) // 2)
    if kind.startswith("ascii"):
        name = _spaced()
        out = [logo_pad + row for row in ASCII_LOGO] + [""] if kind == "ascii" else []
        return out + [" " * ((BLOCK - len(name)) // 2) + paint(WORD, name), "", tag_pad + paint(DIM, TAGLINE), ""]

    moving = _moving(state, t)
    intro = state.intro and moving
    end, failed = tl.end, _failed(state)
    out = []
    if kind == "full":
        settled = end is not None and t >= end + 3.0
        lit = end is not None and not failed and t >= end
        logo = _logo(
            ring=_ease(t / 0.9) if intro else 1.0,
            horizon=_ease((t - 0.7) / 0.4) if intro else 1.0,
            sun_off=sun_offset(state, t),
            rip=(_ease((t - end) / 0.6) if moving else 1.0) if lit else 0.0,
            phase=int(t * 8) if moving and not settled else 0,
        )
        sun = ORANGE
        if moving and lit and t < end + 1.0:
            sun = FLASH[round(math.sin(math.pi * (t - end)) * (len(FLASH) - 1))]
        colours = {"sun": sun, "rip": RIPPLE, "line": None, "": None}
        out += [logo_pad + _cells([(ch, colours[p]) for ch, p in row], state) for row in logo]
        out.append("")
    reveal = round(_ease((t - 1.0) / 1.0) * BLOCK) if intro else BLOCK
    shine = None
    if moving and end is not None and not failed and end + 0.2 < t < end + 1.6:
        shine = (t - end - 0.2) / 1.4 * (BLOCK + 12) - 6
    for row in WORDMARK:
        cells = []
        for i, ch in enumerate(row):
            if i >= reveal:
                cells.append((" ", None))
                continue
            d = abs(i - shine) if shine is not None else 99
            cells.append((ch, WHITE if d < 2 else CREAM if d < 6 else WORD))
        out.append(_cells(cells, state))
    out.append("")
    if not intro or t >= 1.95:
        fade = TAG_FADE[min(len(TAG_FADE) - 1, int((t - 1.95) / 0.1))] if intro else DIM
        out.append(tag_pad + paint(fade, TAGLINE))
    else:
        out.append("")
    out.append("")
    return out


def _shimmer(label, t, state):
    pos = (t * 18) % (len(label) + 10) - 5
    return _cells([(ch, WHITE if abs(i - pos) < 1 else BRIGHT if abs(i - pos) < 2.5 else ACTIVE)
                   for i, ch in enumerate(label)], state) + (" " * (len(label) - len(label.rstrip())))


def _body(t, state, tl):
    paint = _paint(state)
    moving = _moving(state, t)
    spin = paint(ORANGE, SPIN[int(t * 12) % len(SPIN)] if moving else STILL_SPIN)
    out = []
    for i, ((start, end), s) in enumerate(zip(tl.steps, state.steps)):
        if t < start:
            break
        active = end is None or t < end
        label = s.label.ljust(LABEL)
        if active:
            row = IND + spin + " " + (_shimmer(label, t, state) if moving else paint(ACTIVE, label))
            seen = [p for p in s.progress if p[0] <= t]
            if seen:
                frac = min(1.0, seen[-1][1] / seen[-1][2]) if seen[-1][2] else 0.0
                fill = round(frac * 20)
                row += paint(TRAIL, "─" * fill) + paint(DIM, "─" * (20 - fill))
                row += "  " + paint(DIM, f"{seen[-1][1] / 1e6:.0f} MB")
            elif s.apps and state.apps:
                done = sum(1 for _, le in tl.leaves if le is not None and t >= le)
                row += paint(DIM, f"{done} of {len(state.apps)}")
            out.append(row.rstrip())
        else:
            mark = {"ok": (GREEN, "✓"), "warn": (AMBER, "!"), "failed": (RED, "✗")}.get(s.status, (GREEN, "✓"))
            text = (label + s.note).rstrip()
            out.append(IND + paint(*mark) + " " + paint(ACTIVE if s.status == "failed" else GREY, text))
        if s.apps:
            out += _leaves(t, state, tl, active, spin)
    return out


def _leaves(t, state, tl, parent_active, spin):
    paint = _paint(state)
    shown = [(j, ls, le) for j, (ls, le) in enumerate(tl.leaves) if t >= ls]
    out = []
    for n, (j, ls, le) in enumerate(shown):
        a = state.apps[j]
        active = le is None or t < le
        last = n == len(shown) - 1 and (active or not parent_active or j == len(state.apps) - 1)
        branch = "└" if last else "├"
        if active:
            out.append(IND + "  " + paint(DIM, branch) + " " + spin + " " + paint(ACTIVE, a.name))
        elif a.status == "failed":
            out.append(IND + "  " + paint(GREY, f"{branch} {a.name.ljust(LABEL - 2)}") + paint(RED, a.how or "failed"))
        else:
            text = f"{branch} {a.name.ljust(LABEL - 2)}" + (a.how.ljust(HOW) if a.hint else a.how)
            out.append(IND + "  " + paint(GREY, text) + (paint(ORANGE, a.hint) if a.hint else ""))
    return out


def _connected(state):
    return [a.name for a in state.apps if a.status == "ok"]


def track(names, room=BLOCK - len(IND)):
    """(nodes, wire length) for the app line: up to 4 apps, else the first 3 and "+k more"; wires 3 to 9 cells."""
    nodes = list(names) if len(names) <= 4 else list(names[:3]) + [f"+{len(names) - 3} more"]
    if len(nodes) < 2:
        return nodes, 0
    used = sum(len(n) + 2 for n in nodes)
    return nodes, max(3, min(9, (room - used) // (len(nodes) - 1) - 2))


def _app_line(state, names, p, room):
    paint = _paint(state)
    nodes, wire = track(names, room)
    segs, x = [], 0
    for i, n in enumerate(nodes):
        segs.append((n, x))
        x += len(n) + 2
        if i < len(nodes) - 1:
            segs.append((None, x + 1))
            x += wire + 2
    head = p * x
    line = ""
    for name, sx in segs:
        if name is not None:
            lit = head >= sx
            line += paint(ORANGE if lit else DIM, "◉") + " " + paint(NAME if lit else DIM, name)
            continue
        line += " "
        for i in range(wire):
            cx = sx + i
            if abs(cx - head) < 0.6 and p < 1:
                line += paint(WHITE, "●")
            else:
                line += paint(TRAIL if cx < head else DIM, "─")
        line += " "
    return IND + line


def cut(text, limit):
    """At most limit characters, cut at a word boundary with an ellipsis."""
    if len(text) <= limit:
        return text
    head = text[:limit - 1]
    if " " in head:
        head = head[:head.rfind(" ")]
    return head.rstrip(" ,.;:-") + "…"


def _try_lines(width, names):
    first = "Claude Code" if "Claude Code" in names else names[0]
    others = [n for n in names if n != first]
    other = "Cursor" if "Cursor" in others else others[0] if others else "it"
    head, tail = f"Try it: in {first}, say “remember that …”,", f"then ask {other} in a new chat."
    pad = " " * len("Try it: ")
    lines = [head + " " + tail] if len(IND) + len(head) + 1 + len(tail) < width else [head, pad + tail]
    return lines, pad + "e.g. remember that we deploy on Fridays"


def _finale(t, state, tl):
    end = tl.end
    if end is None or _failed(state):
        return []
    paint = _paint(state)
    bold = (lambda s: f"\x1b[1;38;5;{BRIGHT}m{s}\x1b[0m") if state.color else (lambda s: f"\x1b[1m{s}\x1b[0m")
    is_on = bold(f"{PRODUCT} is on.")
    if not state.intro:
        return ["", IND + is_on]
    moving = _moving(state, t)
    out = []
    names = _connected(state)
    room = min(BLOCK, state.width) - len(IND)
    if names and (t >= end + 0.3 or not moving):
        p = 1.0 if len(names) == 1 or not moving else _ease_in_out((t - end - 0.6) / 2.0)
        out += ["", _app_line(state, names, p, room)]
        if p >= 1:
            out += _memory_lines(state, names, room)
    if t >= end + 3.0 or not moving:
        out += ["", IND + is_on]
        if names:
            tries, eg = _try_lines(state.width, names)
            out += [IND + paint(DIM, line) for line in tries] + [IND + paint(DIMMER, eg)]
    return out


def _memory_lines(state, names, room):
    paint = _paint(state)
    mem = state.memory
    if len(names) == 1:
        later = [n for n in ("Cursor", "Codex", "Claude Code") if n not in names][:2]
        first = (paint(NAME, f"“{cut(mem, room - 10)}”") + paint(DIM, " saved")) if mem \
            else paint(DIM, f"Memory is on in {names[0]}")
        return [IND + "  " + first,
                IND + "  " + paint(DIM, f"Add {' or '.join(later)} later: ") + paint(ORANGE, f"{COMMAND} setup")]
    if not mem:
        return [IND + "  " + paint(DIM, "Anything you tell one of them now reaches the others.")]
    tail = " is now in both" if len(names) == 2 else f" is now in all {len(names)}"
    return [IND + "  " + paint(NAME, f"“{cut(mem, room - 4 - len(tail))}”") + paint(DIM, tail)]


_ASCII = str.maketrans({"✓": "+", "✗": "x", "─": "-", "├": "|", "└": "`", "◉": "o", "●": "*", "•": "*",
                        "“": '"', "”": '"', "…": "..."})


def _ascii(line):
    return line.translate(_ASCII)


# ---------- plain lines (not a terminal, CI, --plain, TERM=dumb) ----------

def plain_lines(state):
    """Finished steps as plain lines, then the finish. No art, colour or escapes."""
    tags = {"ok": "[ok]", "warn": "[warn]", "failed": "[fail]"}
    out = []
    for s in state.steps:
        if s.ended is None or s.status not in tags:
            break
        out.append(f"{tags[s.status]} {s.label}: {s.note}".rstrip(": "))
        if s.apps:
            for a in state.apps:
                if a.status in ("ok", "failed"):
                    out.append(f"     {a.name}: {a.how or a.status}" + (f" ({a.hint})" if a.hint else ""))
    if state.finished is not None and not _failed(state):
        out.append(f"{PRODUCT} is on.")
        names = _connected(state)
        if names and state.intro:
            tries, eg = _try_lines(999, names)
            out += tries + [eg]
    return out if state.unicode else [_ascii(line) for line in out]


# ---------- the self-check row and the memory moment ----------

def self_check_row(seconds):
    """(status, note) for the self-check: the measured hook time, one decimal; slower than SLOW is a warning."""
    note = f"recall in {seconds:.1f} s"
    return ("ok", note) if seconds <= SLOW else ("warn", f"{note} (slow: {COMMAND} doctor)")


@dataclass
class Memory:
    text: str
    kind: str            # from the memory file's frontmatter: feedback, project, reference, user
    section: str         # where it is filed: projects, prefs, reference, about, personal, ...
    created: float = 0.0
    secret: bool = False
    private: bool = False  # a sensitivity label made it private


KIND_ORDER = {"feedback": 0, "project": 1, "reference": 2}  # a working rule first
WORK_SECTIONS = {"projects", "prefs", "reference", "about"}  # what a work-only app may see
MEMORY_MAX = 48
CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")  # C0 and C1 controls (ESC, CSI, ...), not newline or tab

# Health and money words, and private details, as the engine has them (mem.py WITHHELD_RE and REDACT). Copied until
# the engine is its own package (spec 5); then this imports them.
WITHHELD_RE = (
    re.compile(r"\bdr\.|\b(?:health|doctors?|physicians?|nurses?|clinics?|hospital\w*|urgent care|diagnos\w*|symptoms?|"
               r"prescri\w*|medications?|meds|medicines?|pills?|doses?|dosage|\d+ ?(?:mg|mcg|ml)\b|therap\w*|"
               r"counsel+ors?|counsel+ing|psychiatr\w*|psycholog\w*|mental health|anxiety|depress\w*|adhd|surgery|"
               r"surgeon|biopsy|blood (?:test|work|draw|pressure)|lab results|test results|allerg\w*|pregnan\w*|"
               r"fertility|ivf|miscarr\w*|thyroid|hypothyroid\w*|diabet\w*|cancer|tumou?rs?|asthma|physio\w*|"
               r"vaccin\w*|insulin|chemo\w*|rehab|dermatolog\w*|cardiolog\w*|gynecolog\w*|ob-?gyn|patient portal|"
               r"pathology|mammogram|mri|x-ray|ultrasound|sick|illness|infection)\b", re.I),
    re.compile(r"\b(?:salary|salaries|income|paychecks?|pay raise|bonus(?:es)?|debts?|loans?|mortgage|credit (?:score|"
               r"card)s?|bank(?:ing)?|account balance|savings|401\(?k\)?|ira|invest\w*|stocks?|equity|taxe?s|irs|"
               r"net worth|owe[sd]?|overdra\w+|budget\w*|rent is|deposit)\b|[$€£]\s?\d|"
               r"\b\d+(?:\.\d+)?\s?(?:k|dollars|bucks)\b", re.I))
REDACT = [
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}"), "[email]"),
    # +country numbers in any grouping, 8 digits or more
    (re.compile(r"(?<![\w+])\+\d[\d ().-]{6,}\d(?!\w)"),
     lambda m: "[phone]" if sum(c.isdigit() for c in m.group(0)) >= 8 else m.group(0)),
    (re.compile(r"(?<![\w.+-])(?:1[ .-]?)?(?:\(\d{3}\) ?|\d{3}[ .-])\d{3}[ .-]\d{4}(?![\w-])"), "[phone]"),
    (re.compile(r"(?i)\b(ending(?:\s+(?:in|with))?|ends\s+(?:in|with)|last\s*-?\s*(?:4|four)(?:\s+digits?)?"
                r"(?:\s+(?:is|are|of))?)(\s*[:#]?\s*)\d{4}(?!\d)"), r"\1\2[last4]"),
    (re.compile(r"([•*]{2,}|\.{3}|…) ?\d{4}(?!\d)"), r"\1[last4]"),
    (re.compile(r"(?<!\d)\d{4}(?:[ -]\d{4}){2,3}(?!\d)"), "[number]"),
    (re.compile(r"(?<!\d)\d{6,}(?!\d)"), "[number]"),
]


def redact(text):
    """Phones, emails and long numbers replaced by placeholders."""
    for pat, repl in REDACT:
        text = pat.sub(repl, text)
    return text


def pick_memory(imported):
    """The note the memory moment shows, or None: a working rule first, then a project fact, then a reference, only
    one a work-only app may see. Its first line, redacted, at most 48 characters. Ties: the shortest, then the newest."""
    best = None
    for m in imported:
        if m.kind not in KIND_ORDER or m.section not in WORK_SECTIONS or m.secret or m.private:
            continue
        if any(r.search(m.text) for r in WITHHELD_RE):
            continue
        text = CONTROL.sub(" ", m.text)  # outside text on the user's terminal: no escape codes, ever
        lines = [ln.strip().lstrip("#-* ").strip() for ln in text.strip().splitlines()]
        first = next((ln for ln in lines if ln), "").rstrip(".")
        if not first:
            continue
        text = cut(redact(first), MEMORY_MAX)
        key = (KIND_ORDER[m.kind], len(text), -m.created)
        if best is None or key < best[0]:
            best = (key, text)
    return best[1] if best else None


# ---------- the terminal ----------

def reduce_motion():
    """macOS Reduce Motion (System Settings, Accessibility, Display)."""
    if sys.platform != "darwin":
        return False
    try:
        r = subprocess.run(["defaults", "read", "com.apple.universalaccess", "reduceMotion"],
                           capture_output=True, text=True, timeout=2)
        return r.stdout.strip() == "1"
    except (OSError, subprocess.SubprocessError):
        return False


def utf8_locale(env, out):
    for key in ("LC_ALL", "LC_CTYPE", "LANG"):
        if env.get(key):
            return "utf-8" in env[key].lower() or "utf8" in env[key].lower()
    return (getattr(out, "encoding", "") or "").lower().replace("-", "") == "utf8"


def detect(out=None, env=None, plain=False, animate=True):
    """What this terminal gets, as ScreenState fields (spec 9.1, Fallbacks)."""
    out = out or sys.stdout
    env = os.environ if env is None else env
    tty = hasattr(out, "isatty") and out.isatty()
    size = shutil.get_terminal_size((80, 24))
    unicode = utf8_locale(env, out)
    return {
        "plain": plain or not tty or bool(env.get("CI")) or env.get("TERM") == "dumb",
        "unicode": unicode,
        "color": not env.get("NO_COLOR"),
        "motion": animate and unicode and not reduce_motion(),
        "width": size.columns,
        "height": size.lines,
    }


HIDE, SHOW, CLEAR_LINE = "\x1b[?25l", "\x1b[?25h", "\r\x1b[2K"


class Animator:
    """Draws frame(t, state) in place while the caller does the work.

    ui = Animator(state); ui.start()
    ui.step("Search models", "running", progress=(bytes_done, bytes_total)) ... ui.step("Search models", "ok", "57 MB")
    ui.apps([AppResult("Codex", status="running"), ...]); ui.memory(text); ui.finish()
    """

    FPS = 30

    def __init__(self, state, out=None, clock=time.monotonic, keys=None):
        self.state = state
        self.out = out or sys.stdout
        self._clock = clock
        self._keys = keys          # a file descriptor to read key presses from; None: stdin when it is a terminal
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread = None
        self._t0 = None
        self._prev = []
        self._printed = 0          # plain mode: lines already written
        self._saved_tty = None
        self._saved_handlers = {}
        self._restored = True

    def _now(self):
        return self._clock() - self._t0

    # ----- the caller's side -----

    def start(self):
        self._t0 = self._clock()
        if self.state.plain:
            return
        self._restored = False
        self._setup_terminal()
        self._write(HIDE + "\n")
        self._thread = threading.Thread(target=self._run, name="setup-screen", daemon=True)
        self._thread.start()

    def step(self, label, status, note=None, progress=None):
        with self._lock:
            s = next(s for s in self.state.steps if s.label == label)
            now = self._now()
            if s.started is None:
                s.started = now
            if progress is not None and (not s.progress or now - s.progress[-1][0] >= 0.05 or
                                         progress[0] >= progress[1]):
                s.progress.append((now, progress[0], progress[1]))
            if status in ("ok", "warn", "failed"):
                s.ended = now
            s.status = status
            if note is not None:
                s.note = note
            if status == "failed":
                self.state.finished = now
        self._flush_plain()

    def apps(self, apps):
        """The apps to wire, in order, each with its status. Call again whenever one starts or finishes."""
        with self._lock:
            now = self._now()
            known = {a.name: a for a in self.state.apps}
            merged = []
            for a in apps:
                cur = known.get(a.name) or AppResult(a.name)
                if a.status != "pending" and cur.started is None:
                    cur.started = now
                if a.status in ("ok", "failed") and cur.ended is None:
                    cur.ended = now
                cur.how, cur.hint, cur.status = a.how, a.hint, a.status
                merged.append(cur)
            self.state.apps = merged

    def memory(self, text):
        with self._lock:
            self.state.memory = text

    def finish(self):
        """Setup's work is done: play the ending (it waits for it), then give the terminal back."""
        with self._lock:
            if self.state.finished is None:
                self.state.finished = self._now()
        if self.state.plain:
            self._flush_plain()
            return
        if self._thread:
            self._thread.join()
        self._restore(newline=True)

    def abort(self):
        """Stop drawing now (an error or Ctrl-C): show the cursor, clear the line, give the terminal back."""
        self._stop.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=1)
        self._restore(newline=False)

    # ----- drawing -----

    def _run(self):
        key_fd = self._key_fd()
        while not self._stop.is_set():
            with self._lock:
                t = self._now()
                lines = frame(t, self.state)
                end = done_at(self.state)
            self._draw(lines)
            if end is not None and t >= end:
                return
            if key_fd is not None:
                try:
                    ready = select.select([key_fd], [], [], 1 / self.FPS)[0]
                except (OSError, ValueError):
                    ready, key_fd = [], None
                if ready:
                    os.read(key_fd, 64)
                    with self._lock:
                        if self.state.skipped is None:
                            self.state.skipped = self._now()
            else:
                self._stop.wait(1 / self.FPS)

    def _draw(self, lines):
        """Rewrite the rows that changed (cursor up, line clear), then add the new ones below."""
        if self._stop.is_set():
            return
        prev, buf = self._prev, []
        n = len(prev)
        lines = lines + [""] * (n - len(lines))
        reach = max(1, self.state.height - 1)  # rows that scrolled off the top cannot be redrawn
        for i in range(n):
            if lines[i] != prev[i] and n - i <= reach:
                up = n - i
                buf.append(f"\x1b[{up}A\r{lines[i]}\x1b[K\x1b[{up}B\r")
        for line in lines[n:]:
            buf.append(f"\r{line}\x1b[K\n")
        self._prev = lines
        if buf:
            self._write("".join(buf))

    def _flush_plain(self):
        if not self.state.plain:
            return
        with self._lock:
            lines = plain_lines(self.state)
        new = lines[self._printed:]
        self._printed = len(lines)
        if new:
            self._write("\n".join(new) + "\n")

    def _write(self, text):
        try:
            self.out.write(text)
            self.out.flush()
        except (OSError, ValueError):
            pass

    # ----- the terminal: keys, cursor, Ctrl-C -----

    def _key_fd(self):
        if self._keys is not None:
            return self._keys
        return self._saved_tty[0] if self._saved_tty else None

    def _setup_terminal(self):
        try:
            import termios
            import tty
            fd = sys.stdin.fileno()
            if self._keys is None and os.isatty(fd):
                self._saved_tty = (fd, termios.tcgetattr(fd))
                tty.setcbreak(fd)  # keys arrive one at a time and are not echoed; Ctrl-C still interrupts
        except (ImportError, OSError, ValueError, AttributeError):
            self._saved_tty = None
        atexit.register(self._restore)
        if threading.current_thread() is threading.main_thread():
            for sig in (signal.SIGINT, signal.SIGTERM):
                self._saved_handlers[sig] = signal.signal(sig, self._on_signal)

    def _on_signal(self, signum, _frame):
        self.abort()
        if signum == signal.SIGINT:
            raise KeyboardInterrupt
        sys.exit(128 + signum)

    def _restore(self, newline=False):
        if self._restored:
            return
        self._restored = True
        self._stop.set()
        self._write(("\n" if newline else CLEAR_LINE) + SHOW)
        if self._saved_tty:
            try:
                import termios
                termios.tcsetattr(self._saved_tty[0], termios.TCSADRAIN, self._saved_tty[1])
            except (ImportError, OSError):
                pass
        for sig, handler in self._saved_handlers.items():
            try:
                signal.signal(sig, handler)
            except (ValueError, TypeError):
                pass
        self._saved_handlers = {}
