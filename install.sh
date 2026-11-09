#!/bin/sh
# Installs Dawnmere on a Mac: uv if it is missing, then the CLI and the engine, each file checked against the
# sha256 written below, their dependencies pinned and hash-checked by constraints.txt, then `dawnmere setup`.
#
#   curl -fsSL https://github.com/Hadeva-Dev/dawnmere/releases/latest/download/install.sh | sh
#
# The release workflow fills the release lines below; the copy in the source tree refuses to run.
set -eu

# --- filled by cli/tools/render_install.py at release time (RELEASING.md) ---
VERSION=""
CLI_WHEEL=""
CLI_SHA256=""
CLI_SIZE=0
ENGINE_WHEEL=""
ENGINE_SHA256=""
ENGINE_SIZE=0
CONSTRAINTS_SHA256=""
CONSTRAINTS_SIZE=0
# --- end ---

UV_VERSION="0.12.5"
UV_SHA256_arm64="5bb0e5fe008a773c3dbcb97ff79cd89e1241464fe9d2f986d52ad8f1b037bd62"
UV_SIZE_arm64=18518284

BASE="${LFLABS_MEMORY_RELEASE_BASE:-https://github.com/Hadeva-Dev/dawnmere/releases/download/v$VERSION}"
UV_BASE="${LFLABS_MEMORY_UV_BASE:-https://github.com/astral-sh/uv/releases/download/$UV_VERSION}"
BIN="$HOME/.local/bin"

fail() {
  printf '\n%s\n' "$1" >&2
  exit 1
}

[ -n "$VERSION" ] || fail "This install.sh is the source copy. Use the one attached to a release."
[ "$(uname -s)" = Darwin ] || fail "Dawnmere runs on macOS only."
os=$(sw_vers -productVersion)
[ "${os%%.*}" -ge 14 ] 2>/dev/null || fail "Dawnmere needs macOS 14 or later (this Mac has $os)."
# The engine's onnxruntime has no Intel Mac wheels. hw.optional.arm64 is 1 on Apple silicon even under Rosetta.
[ "$(PATH="$PATH:/usr/sbin" sysctl -n hw.optional.arm64 2>/dev/null)" = 1 ] || fail "Dawnmere needs a Mac with Apple silicon (M1 or later)."
command -v curl >/dev/null 2>&1 || fail "curl is missing, so nothing can be downloaded."

printf 'Dawnmere installer\n'
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT INT TERM

# One progress line for everything downloaded, redrawn in place: "Downloading  ──────      12.4 / 31.0 MB".
TOTAL=0
progress() {
  got=$(cat "$TMP"/dl.* 2>/dev/null | wc -c | tr -d ' ')
  [ "$TOTAL" -gt 0 ] || return 0
  cells=$((got * 12 / TOTAL))
  [ "$cells" -le 12 ] || cells=12
  bar="" i=0
  while [ "$i" -lt 12 ]; do
    if [ "$i" -lt "$cells" ]; then bar="${bar}─"; else bar="$bar "; fi
    i=$((i + 1))
  done
  printf '\rDownloading  %s  %s / %s MB ' "$bar" \
    "$(awk "BEGIN { printf \"%.1f\", $got / 1000000 }")" "$(awk "BEGIN { printf \"%.1f\", $TOTAL / 1000000 }")"
}

# fetch URL NAME: download into $TMP/dl.NAME, keeping the progress line moving.
fetch() {
  curl -fsSL -o "$TMP/dl.$2" "$1" &
  pid=$!
  while kill -0 "$pid" 2>/dev/null; do
    progress
    sleep 0.2
  done
  wait "$pid" || fail "Could not download $1. Check the connection and run the install line again."
  progress
}

# check NAME SHA256: the download matches, or nothing is installed.
check() {
  [ "$(shasum -a 256 "$TMP/dl.$1" | cut -d ' ' -f 1)" = "$2" ] ||
    fail "$1 did not match its checksum, so nothing was installed. Run the install line again."
}

UV=$(command -v uv 2>/dev/null || true)
# an older uv cannot link the engine's command (below): the pinned one is used instead
"$UV" tool install --help 2>/dev/null | grep -q -- --with-executables-from || UV=""
if [ -z "$UV" ]; then
  arch=aarch64 uv_sha=$UV_SHA256_arm64 uv_size=$UV_SIZE_arm64
  TOTAL=$uv_size
fi
TOTAL=$((TOTAL + CLI_SIZE + ENGINE_SIZE + CONSTRAINTS_SIZE))

if [ -z "$UV" ]; then
  fetch "$UV_BASE/uv-$arch-apple-darwin.tar.gz" uv.tar.gz
  check uv.tar.gz "$uv_sha"
fi
fetch "$BASE/$CLI_WHEEL" "$CLI_WHEEL"
fetch "$BASE/$ENGINE_WHEEL" "$ENGINE_WHEEL"
fetch "$BASE/constraints.txt" constraints.txt
check "$CLI_WHEEL" "$CLI_SHA256"
check "$ENGINE_WHEEL" "$ENGINE_SHA256"
check constraints.txt "$CONSTRAINTS_SHA256"
printf '\nChecksums ok\n'

if [ -z "$UV" ]; then
  mkdir -p "$BIN"
  tar -xzf "$TMP/dl.uv.tar.gz" -C "$TMP"
  cp "$TMP/uv-$arch-apple-darwin/uv" "$TMP/uv-$arch-apple-darwin/uvx" "$BIN/"
  UV="$BIN/uv"
fi

# uv wants the wheels under their own names
cp "$TMP/dl.$CLI_WHEEL" "$TMP/$CLI_WHEEL"
cp "$TMP/dl.$ENGINE_WHEEL" "$TMP/$ENGINE_WHEEL"
# --managed-python: uv's own arm64 Python, never an x86_64 one on PATH (onnxruntime has no Intel Mac wheels);
# -c: every dependency at the version this release was tested with (uv tool install ignores the hashes there);
# --with-executables-from: the engine's lflabs-memory command too, which the Claude Code plugin's hooks run
LOCK="$TMP/dl.constraints.txt"
if ! "$UV" tool install --force --managed-python --python 3.12 --no-build -c "$LOCK" "$TMP/$CLI_WHEEL" \
  --with "$TMP/$ENGINE_WHEEL" --with-executables-from lflabs-memory-engine >"$TMP/uv.log" 2>&1; then
  tail -n 5 "$TMP/uv.log" >&2
  fail "Could not install Dawnmere (uv stopped; its last lines are above)."
fi
# Each dependency again, its hash checked this time; a mismatch takes the install out before anything runs it.
if ! "$UV" pip install --python "$("$UV" tool dir)/lflabs-memory-cli/bin/python" --reinstall --no-deps --no-build \
  --require-hashes -r "$LOCK" >"$TMP/uv.log" 2>&1; then
  tail -n 5 "$TMP/uv.log" >&2
  "$UV" tool uninstall lflabs-memory-cli >/dev/null 2>&1 || true
  fail "A dependency did not match the hashes this release was tested with, so Dawnmere was taken out again."
fi

TOOLS=$("$UV" tool dir --bin 2>/dev/null || printf '%s' "$BIN")
rm -rf "$TMP"
trap - EXIT INT TERM
if [ -z "${LFLABS_MEMORY_NO_SETUP:-}" ]; then
  # Under `curl | sh` our stdin is the script itself: setup asks its questions on the terminal (and gives the
  # PATH advice below at its end). No terminal: nobody can say yes to changing the apps' files.
  TTY="${LFLABS_MEMORY_TTY:-/dev/tty}"
  if (exec <"$TTY") 2>/dev/null; then exec "$TOOLS/dawnmere" setup <"$TTY"; fi
  printf '\nThere is no terminal for setup'\''s questions, so no app was changed. Run "dawnmere setup" in a\n'
  printf 'Terminal window, or "dawnmere setup --yes" to take the defaults.\n'
fi
# setup's PATH advice, checked as setup and doctor check it: zsh as a new Terminal window starts it
# shellcheck disable=SC2016  # the line to paste keeps a literal $PATH
zsh -lic 'command -v dawnmere' </dev/null >/dev/null 2>&1 ||
  printf 'To run dawnmere later, add this line to ~/.zshrc:\n  export PATH="%s:$PATH"\n' "$TOOLS"
