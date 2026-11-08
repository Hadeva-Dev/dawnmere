"""The setup screen (spec 9.1): Kip, the live steps, the memory moment.

The posts are the progress bar. Kip, the kingfisher, waits on a stump over the water; each app setup finds gets a post,
and when setup connects that app its cap turns orange and Kip hops onto it. When the work is done Kip dives and comes
back with one of the user's own notes, which is now in every app. Every frame comes from one pure function,
frame(t, state). Animator draws those frames in place, at most 30 a second, redrawing only the rows that changed, while
the caller does the work and reports it with step(), apps(), memory() and finish(). The screen never delays the work:
a row stays up for at least FLOOR seconds so a 5 ms check is readable, and nothing else waits.
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

from .banner_art import WORDMARK
from .brand import COMMAND, PRODUCT
from .kip_art import SPRITES

BLOCK = 67                # the art block (Kip's scene): the header is centred on it
MARGIN = " "              # the block's left margin
IND = "  "                # the body's left edge
LABEL = 16                # every result starts in one column: IND + mark + space + LABEL
HOW = 13                  # a tree leaf's "how" column, then its hint
FLOOR = 0.35              # each row is on screen at least this long
INTRO = 2.2               # the steps appear once the water, the posts, Kip and the wordmark are in
SLOW = 1.5                # a self-check slower than this is a warning
TAGLINE = "one memory for every AI app you use"
SPIN = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
STILL_SPIN = "•"
MIN_WIDTH = 70            # narrower: the compact header (one name line and the tagline) instead of the art

# xterm-256 colours. Orange is Kip's own and marks what the user must do; green is only the tick; grey is finished
# work. Kip's blues and the beak's grey appear only in Kip.
ORANGE = 202
GREEN, AMBER, RED = 114, 214, 167
GREY, DIM, DIMMER = 245, 243, 240
ACTIVE, WORD, NAME, BRIGHT = 253, 252, 252, 255
WHITE = 231
SCENE = {"b": 68, "w": 25, "o": ORANGE, "k": 245, "f": 147,      # Kip: blue, wing, mask and belly, beak, fish
         "water": 67, "post": 60, "cap_off": 239, "cap_on": ORANGE, "white": WHITE}
_WEIGHT = {"o": 1.7, "f": 1.5, "k": 1.4}   # thin features win their cell, so the band and the beak survive

# Kip's scene: 67 x 11 cells = 134 x 44 braille dots.
SCENE_ROWS = 11
_DW, _DH = BLOCK * 2, SCENE_ROWS * 4
WATER_Y, POST_TOP = 41, 31   # dot rows: the water line, the top of every post (where Kip's feet go)
STUMP = 14                   # dot x of the stump Kip waits on
POSTS = (46, 108)            # the posts spread evenly between these dot x
MAX_POSTS = 4                # 5 or more apps: the first three posts, then "+k more"
HOP, ARC = 0.6, 9            # a hop: seconds, and dots high
WATER_REST = 1               # the water's phase when it stands still, as in the design's last frame
_BITS = ((0, 0, 0x01), (0, 1, 0x02), (0, 2, 0x04), (1, 0, 0x08), (1, 1, 0x10), (1, 2, 0x20), (0, 3, 0x40),
         (1, 3, 0x80))
_HEADER_ROWS = SCENE_ROWS + 1 + 1 + len(WORDMARK) + 1 + 1   # scene, names, gap, wordmark, tagline, gap


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
    expect_apps: int = 3           # the apps setup found: one post each, before they are wired


# ---------- timeline: when each row is on screen ----------

@dataclass
class _Timeline:
    steps: list   # (start, end or None) per step shown
    leaves: list  # (start, end or None) per app leaf shown
    end: float | None  # when the screen catches up with finished work


def _intro_len(state):
    if not (state.intro and _moving_at_all(state)) or _header(state) != "full":
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


# ---------- the scene: posts, hops, the dive ----------

@dataclass
class _Scene:
    posts: list         # dot x of each post shown
    lit: list           # per post: when its cap turns orange (its app's leaf settled), or None
    hops: list          # (leaf settled, hop start, from x, to x): Kip hops once each app is connected
    dive: float | None  # when Kip dives (None: it does not, because setup failed or connected nothing)
    more: int           # apps without a post: "+k more"


def post_xs(n):
    """Dot x of the posts for n apps: 46, 78, 108 for three; 2 to 4 spread evenly; 5 or more show three."""
    n = 3 if n > MAX_POSTS else n
    if n < 2:
        return [78] * n
    lo, hi = POSTS
    return [2 * int((lo + (hi - lo) * i / (n - 1)) / 2 + 0.5) for i in range(n)]  # even x: a post fills one cell


def _scene(state, tl):
    found = max(state.expect_apps, len(state.apps))
    xs = post_xs(found)
    lit, hops, x = [None] * len(xs), [], STUMP
    for j, (_, le) in enumerate(tl.leaves):
        if j >= len(xs) or le is None or state.apps[j].status != "ok":
            continue
        lit[j] = le
        start = le if not hops else max(le, hops[-1][1] + HOP)   # never before the leaf settles
        hops.append((le, start, x, xs[j]))
        x = xs[j]
    dive = None
    if tl.end is not None and hops and not _failed(state):
        dive = max(tl.end, hops[-1][1] + HOP)
    return _Scene(xs, lit, hops, dive, max(0, found - len(xs)))


def _ending(state, tl, sc):
    """When the ending's clock starts: the dive, or the end of the work when Kip does not dive."""
    return sc.dive if sc.dive is not None else tl.end


def done_at(state):
    """When the last frame is up (None while setup still works). The full show ends 2.6 s after the dive."""
    tl = _timeline(state)
    if tl.end is None:
        return None
    if state.plain or not state.intro or not _moving_at_all(state):
        return tl.end
    if state.skipped is not None:
        return max(tl.end, state.skipped)
    sc = _scene(state, tl)
    if _failed(state):   # Kip stays where it is, but lands first
        return max([tl.end] + [start + HOP for _, start, _, _ in sc.hops])
    return _ending(state, tl, sc) + 2.6


def _smooth(x):
    x = min(1.0, max(0.0, x))
    return x * x * (3 - 2 * x)


def kip_at(state, t):
    """(dot x, dot y, sprite or None): where Kip is at time t, and in which pose."""
    tl = _timeline(state)
    return _kip(state, tl, _scene(state, tl), t)


def _kip(state, tl, sc, t):
    catch = "fish" if state.memory else "perch"   # no note: Kip comes up with nothing
    if not _moving(state, t):
        x = STUMP
        for settled, _, _, to in sc.hops:
            if t >= settled:
                x = to
        return x, POST_TOP, catch if sc.dive is not None and t >= tl.end else "perch"
    x, y, hopping = STUMP, POST_TOP, False
    for _, start, x0, x1 in sc.hops:
        if t >= start:
            p = _smooth((t - start) / HOP)
            x, y, hopping = x0 + (x1 - x0) * p, POST_TOP - ARC * math.sin(math.pi * p), p < 1
    waiting = not hopping and (sc.dive is None or t < sc.dive)
    sprite = "blink" if waiting and t % 3.1 < 0.14 else "perch"
    if sc.dive is not None and t >= sc.dive:
        k = t - sc.dive
        if k < 0.25:                                   # gather
            y = POST_TOP - 3 * _smooth(k / 0.25)
        elif k < 0.55:                                 # beak first into the water
            sprite, y = "dive", POST_TOP - 6 + (WATER_Y + 2 - (POST_TOP - 6)) * _smooth((k - 0.25) / 0.3)
        elif k < 0.85:                                 # under
            sprite = None
        elif k < 1.25:                                 # back up onto the post
            sprite, y = catch, POST_TOP - 7 * math.sin(math.pi * _smooth((k - 0.85) / 0.4))
        else:
            sprite = catch
    if state.intro:
        if t < 0.9:
            sprite = None
        elif t < 1.3:                                  # drops onto the stump
            y -= 14 * (1 - _smooth((t - 0.9) / 0.4))
    return x, y, sprite


def cap_lit(state, t):
    """Per post: whether its cap is orange at time t."""
    tl = _timeline(state)
    return [at is not None and t >= at for at in _scene(state, tl).lit]


def _art(t, state, tl, sc):
    """The scene's 11 rows and the names row under it, each [(char, colour or None)]."""
    moving = _moving(state, t)
    intro = state.intro and moving
    done = done_at(state)
    dots = {}

    def put(x, y, part):
        if 0 <= x < _DW and 0 <= y < _DH:
            dots[(x, y)] = part

    reveal = _smooth(t / 0.9) * _DW / 2 if intro else _DW / 2
    phase = int(t * 8) if moving and (done is None or t < done) else WATER_REST
    for x in range(_DW):
        if abs(x - _DW / 2) <= reveal and (x + phase) % 5:
            put(x, WATER_Y, "water")
    rise = _smooth((t - 0.6) / 0.6) if intro else 1.0
    top = WATER_Y - (WATER_Y - POST_TOP) * rise
    for px in [STUMP, *sc.posts]:
        for y in range(int(top) + 2, WATER_Y):
            put(px, y, "post")
            put(px + 1, y, "post")
    if rise >= 1:
        for i, px in enumerate(sc.posts):
            glint = sc.dive is not None and moving and 0 <= t - (sc.dive + 1.3 + i * 0.12) < 0.12
            part = "white" if glint else "cap_on" if sc.lit[i] is not None and t >= sc.lit[i] else "cap_off"
            for x in range(px - 1, px + 3):
                put(x, POST_TOP, part)
                put(x, POST_TOP + 1, part)
    if sc.dive is not None and moving and 0.5 <= t - sc.dive < 1.1:   # the splash ring
        r = 3 + 10 * _smooth((t - sc.dive - 0.5) / 0.6)
        at = sc.hops[-1][3]
        for x in range(_DW):
            if abs(abs(x - at) - r) < 1.2:
                put(x, WATER_Y - 1, "white")
    x, y, sprite = _kip(state, tl, sc, t)
    if sprite:
        sp = SPRITES[sprite]
        for dy, row in enumerate(sp["rows"]):
            for dx, part in enumerate(row):
                if part != ".":
                    put(round(x) - sp["ax"] + dx, round(y) - sp["ay"] + dy, part)
    rows = []
    for cy in range(SCENE_ROWS):
        row = []
        for cx in range(BLOCK):
            bits, votes = 0, {}
            for dx, dy, bit in _BITS:
                part = dots.get((cx * 2 + dx, cy * 4 + dy))
                if part:
                    bits |= bit
                    votes[part] = votes.get(part, 0) + _WEIGHT.get(part, 1.0)
            row.append((chr(0x2800 + bits), SCENE[max(votes, key=votes.get)]) if bits else (" ", None))
        rows.append(row)
    names = [(" ", None)] * BLOCK
    end = 0
    for i, px in enumerate(sc.posts):
        if sc.lit[i] is not None and t >= sc.lit[i]:
            name = state.apps[i].name
            col = max(0, min(BLOCK - len(name), px // 2 + 1 - len(name) // 2))
            names[col:col + len(name)] = [(ch, NAME) for ch in name]
            end = col + len(name)
    if sc.more and sc.lit[-1] is not None and t >= sc.lit[-1]:
        tail = f"  +{sc.more} more"[:BLOCK - end]
        names[end:end + len(tail)] = [(ch, GREY) for ch in tail]
    return rows + [names]


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


def _lead(pad, text):
    """pad + text, or an empty line when there is nothing to show (no trailing blanks)."""
    return pad + text if text else ""


def _moving_at_all(state):
    return state.motion and state.unicode and not state.plain


def _moving(state, t):
    """Animated at time t: not still frames, and no key pressed yet."""
    return _moving_at_all(state) and (state.skipped is None or t < state.skipped)


def _needed_rows(state):
    """The full screen's height, with the line the cursor returns to."""
    apps = max(state.expect_apps, len(state.apps))
    memory = 2 if apps == 1 else 1
    finish = 3 if state.width >= 80 else 4        # "Try it" wraps below 80 columns
    return _HEADER_ROWS + len(state.steps) + apps + 1 + memory + 1 + finish + 1


def _header(state):
    """full: Kip's scene and the wordmark. compact: one name line and the tagline (too narrow or too short for the
    art: a screen taller than the window leaves ghost copies of Kip when it redraws). ascii: no UTF-8. none: re-run."""
    if not state.intro:
        return "none"
    if not state.unicode:
        return "ascii"
    if state.width < MIN_WIDTH or state.height < _needed_rows(state):
        return "compact"
    return "full"


# ---------- the frame ----------

def frame(t, state):
    """Every line on screen at time t (seconds since the first frame). Pure: same t and state, same lines."""
    if state.plain:
        return plain_lines(state)
    tl = _timeline(state)
    sc = _scene(state, tl)
    lines = _header_lines(t, state, tl, sc) + _body(t, state, tl) + _finale(t, state, tl, sc)
    if not state.unicode:
        lines = [_ascii(line) for line in lines]
    return lines


def _header_lines(t, state, tl, sc):
    kind = _header(state)
    paint = _paint(state)
    if kind == "none":
        return []
    if kind in ("compact", "ascii"):
        name = PRODUCT.lower() if kind == "compact" else " ".join(PRODUCT.lower())
        return [IND + paint(WORD, name), IND + paint(GREY, TAGLINE), ""]
    intro = state.intro and _moving(state, t)
    out = [_lead(MARGIN, _cells(row, state)) for row in _art(t, state, tl, sc)]
    out.append("")
    width = len(WORDMARK[0])
    pad = MARGIN + " " * ((BLOCK - width) // 2)
    wipe = _smooth((t - 1.0) / 1.0) * width if intro else width
    for row in WORDMARK:
        out.append(_lead(pad, _cells([(ch if i <= wipe else " ", WORD) for i, ch in enumerate(row)], state)))
    show_tag = not intro or t >= 1.95
    out.append(MARGIN + " " * ((BLOCK - len(TAGLINE)) // 2) + paint(GREY, TAGLINE) if show_tag else "")
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
                done, total = seen[-1][1], seen[-1][2]
                fill = round(min(1.0, done / total) * 20) if total else 0
                row += paint(ORANGE, "─" * fill) + paint(DIMMER, "─" * (20 - fill))
                row += paint(GREY, f"  {done / 1e6:4.1f} / {total / 1e6:.0f} MB")
            elif s.apps and state.apps:
                done = sum(1 for _, le in tl.leaves if le is not None and t >= le)
                row += paint(GREY, f"{done} of {len(state.apps)}")
            out.append(row.rstrip())
        else:
            mark = {"ok": (GREEN, "✓"), "warn": (AMBER, "!"), "failed": (RED, "✗")}.get(s.status, (GREEN, "✓"))
            # one row: the next row would be drawn over a wrapped tail
            text = cut((label + s.note).rstrip(), min(BLOCK, state.width) - len(IND) - 2)
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
        branch = IND + "  " + paint(DIMMER, "└" if last else "├") + " "
        if active:
            out.append(branch + spin + " " + paint(ACTIVE, a.name))
        elif a.status == "failed":
            out.append(branch + paint(GREY, a.name.ljust(LABEL - 2)) + paint(RED, a.how or "failed"))
        else:
            text = a.name.ljust(LABEL - 2) + (a.how.ljust(HOW) if a.hint else a.how)
            out.append(branch + paint(GREY, text) + (paint(ORANGE, a.hint) if a.hint else ""))
    return out


def _connected(state):
    return [a.name for a in state.apps if a.status == "ok"]


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


def _finale(t, state, tl, sc):
    end = tl.end
    if end is None or _failed(state):
        return []
    paint = _paint(state)
    bold = (lambda s: f"\x1b[1;38;5;{WORD}m{s}\x1b[0m") if state.color else (lambda s: f"\x1b[1m{s}\x1b[0m")
    is_on = bold(f"{PRODUCT} is on.")
    if not state.intro:
        return ["", IND + is_on]
    moving = _moving(state, t)
    at = _ending(state, tl, sc)
    names = _connected(state)
    out = []
    if names and (not moving or t >= at + 1.3):
        out += [""] + _memory_lines(state, names)
    if not moving or t >= at + 2.6:
        out += ["", IND + is_on]
        if names:
            tries, eg = _try_lines(state.width, names)
            out += [IND + paint(GREY, line) for line in tries] + [IND + paint(DIMMER, eg)]
    return out


def _memory_lines(state, names):
    """The memory moment's line: the note Kip came back with is now in every app (spec 9.1)."""
    paint = _paint(state)
    room = BLOCK - len(IND)
    mem = state.memory
    if len(names) == 1:
        later = [n for n in ("Cursor", "Codex", "Claude Code") if n not in names][:2]
        first = (paint(NAME, f"“{cut(mem, room - 12)}”") + paint(GREY, "  is saved")) if mem \
            else paint(GREY, f"Memory is on in {names[0]}")
        add = paint(GREY, f"Add {' or '.join(later)} later: ") + paint(ORANGE, f"{COMMAND} setup")
        return [IND + first, IND + add]
    if not mem:
        return [IND + paint(GREY, "Anything you tell one of them now reaches the others.")]
    tail = "  is now in both" if len(names) == 2 else f"  is now in all {len(names)}"
    return [IND + paint(NAME, f"“{cut(mem, room - 2 - len(tail))}”") + paint(GREY, tail)]


_ASCII = str.maketrans({"✓": "+", "✗": "x", "─": "-", "├": "|", "└": "`", "•": "*",
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
    """(status, note) for the self-check: the measured hook time in hundredths; slower than SLOW is a warning."""
    note = f"recall in {seconds:.2f} s"  # hundredths: Hao, 2026-10-28 (reads as fast and precise)
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
        self._write(HIDE)   # no blank line first: the full screen is exactly as tall as the window allows
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
