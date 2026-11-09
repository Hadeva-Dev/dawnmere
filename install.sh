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

REPO="Hadeva-Dev/dawnmere"
BASE="${LFLABS_MEMORY_RELEASE_BASE:-https://github.com/$REPO/releases/download/v$VERSION}"
API="${LFLABS_MEMORY_API_BASE:-https://api.github.com}"
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
# Box drawing under a UTF-8 locale only, decided as setup's screen decides (the first of LC_ALL, LC_CTYPE, LANG).
case ${LC_ALL:-${LC_CTYPE:-${LANG:-}}} in *[Uu][Tt][Ff]-8* | *[Uu][Tt][Ff]8*) CELL="─" ;; *) CELL="-" ;; esac
TOTAL=0
progress() {
  got=$(cat "$TMP"/dl.* 2>/dev/null | wc -c | tr -d ' ')
  [ "$TOTAL" -gt 0 ] || return 0
  cells=$((got * 12 / TOTAL))
  [ "$cells" -le 12 ] || cells=12
  bar="" i=0
  while [ "$i" -lt 12 ]; do
    if [ "$i" -lt "$cells" ]; then bar="${bar}${CELL}"; else bar="$bar "; fi
    i=$((i + 1))
  done
  printf '\rDownloading  %s  %s / %s MB ' "$bar" \
    "$(awk "BEGIN { printf \"%.1f\", $got / 1000000 }")" "$(awk "BEGIN { printf \"%.1f\", $TOTAL / 1000000 }")"
}

# get CURL-ARGS...: curl, retried (GitHub has answered 504 for minutes at a time): curl's own --retry-all-errors
# (curl 7.71+; macOS 14 ships 8.x), else a loop here for an older curl.
RETRIES="${LFLABS_MEMORY_RETRIES:-5}"
RETRY="--retry $RETRIES --retry-delay 2 --connect-timeout 15" TRIES=$((RETRIES + 1))
if curl --help all 2>/dev/null | grep -q -- --retry-all-errors; then RETRY="$RETRY --retry-all-errors" TRIES=1; fi
get() {
  n=1
  # shellcheck disable=SC2086  # RETRY is several words
  until curl -fsSL $RETRY "$@"; do
    [ "$n" -lt "$TRIES" ] || return 1
    n=$((n + 1))
    sleep 2
  done
}

# api_get REPO TAG ASSET OUT: the same release file through GitHub's API (api.github.com), found by its asset id
api_get() {
  json=$(get "$API/repos/$1/releases/tags/$2") || return 1
  id=$(osascript -l JavaScript -e 'function run(a) { var x = JSON.parse(a[0]).assets.filter(function (s) {
    return s.name === a[1] })[0]; return x ? String(x.id) : "" }' "$json" "$3" 2>/dev/null) || return 1
  [ -n "$id" ] && get -H 'Accept: application/octet-stream' -o "$4" "$API/repos/$1/releases/assets/$id"
}

# fetch URL NAME REPO TAG ASSET: download into $TMP/dl.NAME, keeping the progress line moving; then the API's copy.
fetch() {
  get -o "$TMP/dl.$2" "$1" &
  pid=$!
  while kill -0 "$pid" 2>/dev/null; do
    progress
    sleep 0.2
  done
  wait "$pid" || api_get "$3" "$4" "$5" "$TMP/dl.$2" ||
    fail "Could not download $5: GitHub did not answer. Check the connection and run the install line again."
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
  fetch "$UV_BASE/uv-$arch-apple-darwin.tar.gz" uv.tar.gz astral-sh/uv "$UV_VERSION" "uv-$arch-apple-darwin.tar.gz"
  check uv.tar.gz "$uv_sha"
fi
fetch "$BASE/$CLI_WHEEL" "$CLI_WHEEL" "$REPO" "v$VERSION" "$CLI_WHEEL"
fetch "$BASE/$ENGINE_WHEEL" "$ENGINE_WHEEL" "$REPO" "v$VERSION" "$ENGINE_WHEEL"
fetch "$BASE/constraints.txt" constraints.txt "$REPO" "v$VERSION" constraints.txt
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
# The dependencies first, each file downloaded by pip and checked against its hash in constraints.txt (uv tool
# install does not check those hashes), with uv's own Python 3.12 (its download checked by uv); nothing of theirs
# runs. A mismatch stops here, before anything is installed.
LOCK="$TMP/dl.constraints.txt"
if ! { "$UV" python install --managed-python --no-bin 3.12 && PY=$("$UV" python find --managed-python 3.12) &&
  "$PY" -I -m pip download --require-hashes --only-binary :all: --no-deps --no-cache-dir \
    --disable-pip-version-check -q -r "$LOCK" -d "$TMP/deps"; } >"$TMP/uv.log" 2>&1; then
  tail -n 5 "$TMP/uv.log" >&2
  fail "A dependency could not be downloaded or did not match its hash, so nothing was installed."
fi
# Then the install takes only those files (--no-index) and the two wheels checked above.
# --managed-python: uv's own arm64 Python, never an x86_64 one on PATH (onnxruntime has no Intel Mac wheels);
# --with-executables-from: the engine's lflabs-memory command too, which the Claude Code plugin's hooks run
if ! "$UV" tool install --force --managed-python --python 3.12 --no-index --find-links "$TMP/deps" --no-build \
  --no-cache -c "$LOCK" "$TMP/$CLI_WHEEL" --with "$TMP/$ENGINE_WHEEL" --with-executables-from lflabs-memory-engine \
  >"$TMP/uv.log" 2>&1; then
  tail -n 5 "$TMP/uv.log" >&2
  fail "Could not install Dawnmere (uv stopped; its last lines are above)."
fi

TOOLS=$("$UV" tool dir --bin 2>/dev/null || printf '%s' "$BIN")
rm -rf "$TMP"
trap - EXIT INT TERM
# New Terminal windows find dawnmere: unless zsh started as Terminal starts it already does (setup and doctor check it
# the same way), the tool folder goes on PATH in ~/.zprofile, once, recorded so `dawnmere uninstall` takes out exactly
# that line (and the file, if this made it and nothing else is in it).
if ! zsh -lic 'command -v dawnmere' </dev/null >/dev/null 2>&1; then
  ZP="$HOME/.zprofile" DATA="${LFLABS_MEMORY_HOME:-$HOME/Library/Application Support/LF Labs/Memory}"
  LINE="export PATH=\"$TOOLS:\$PATH\"  # added by the Dawnmere installer"
  if ! grep -qxF "$LINE" "$ZP" 2>/dev/null; then
    if [ -e "$ZP" ]; then was=existing; else was=created; fi
    ADD="$LINE"
    if [ -s "$ZP" ] && [ -n "$(tail -c 1 "$ZP")" ]; then ADD="
$LINE"; fi
    if printf '%s\n' "$ADD" >>"$ZP" 2>/dev/null; then
      mkdir -p "$DATA" && chmod 700 "$DATA" && printf '%s\n%s\n' "$was" "$ADD" >"$DATA/zprofile-line"
      printf 'New Terminal windows find dawnmere: %s is on PATH in ~/.zprofile now.\n' "$TOOLS"
    else
      # shellcheck disable=SC2016  # the line to paste keeps a literal $PATH
      printf 'To run dawnmere later, add this line to ~/.zprofile:\n  export PATH="%s:$PATH"\n' "$TOOLS"
    fi
  fi
fi
if [ -z "${LFLABS_MEMORY_NO_SETUP:-}" ]; then
  # Under `curl | sh` our stdin is the script itself: setup asks its questions on the terminal. No terminal: nobody
  # can say yes to changing the apps' files.
  TTY="${LFLABS_MEMORY_TTY:-/dev/tty}"
  if (exec <"$TTY") 2>/dev/null; then exec "$TOOLS/dawnmere" setup <"$TTY"; fi
  printf '\nThere is no terminal for setup'\''s questions, so no app was changed. Run "dawnmere setup" in a\n'
  printf 'Terminal window, or "dawnmere setup --yes" to take the defaults.\n'
fi
