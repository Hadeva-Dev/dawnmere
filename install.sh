#!/bin/sh
# Installs Dawnmere on a Mac: uv if it is missing, then the CLI and the engine, each file checked against the
# sha256 written below, then `dawnmere setup` (spec 10.1).
#
#   curl -fsSL https://github.com/Hadeva-Dev/dawnmere/releases/latest/download/install.sh | sh
#
# The release workflow fills the release lines below; the copy in the source tree refuses to run.
set -eu

# --- filled by .github/workflows/release.yml ---
VERSION=""
CLI_WHEEL=""
CLI_SHA256=""
CLI_SIZE=0
ENGINE_WHEEL=""
ENGINE_SHA256=""
ENGINE_SIZE=0
# --- end ---

UV_VERSION="0.12.5"
UV_SHA256_arm64="5bb0e5fe008a773c3dbcb97ff79cd89e1241464fe9d2f986d52ad8f1b037bd62"
UV_SIZE_arm64=18518284
UV_SHA256_x86_64="b3b2137477cf96c9686ebfb71524614cec780c673fd73e59bce099aef02e70e8"
UV_SIZE_x86_64=20848713

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
command -v curl >/dev/null 2>&1 || fail "curl is missing, so nothing can be downloaded."

printf 'Dawnmere installer\n'
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT INT TERM

# One progress line for everything downloaded, redrawn in place: "Downloading  ──────      12.4 / 31 MB".
TOTAL=0
progress() {
  got=$(cat "$TMP"/dl.* 2>/dev/null | wc -c | tr -d ' ')
  [ "$TOTAL" -gt 0 ] || return 0
  cells=$((got * 12 / TOTAL))
  [ "$cells" -le 12 ] || cells=12
  bar="" i=0
  while [ "$i" -lt 12 ]; do
    if [ "$i" -lt "$cells" ]; then bar="$bar─"; else bar="$bar "; fi
    i=$((i + 1))
  done
  printf '\rDownloading  %s  %s / %s MB ' "$bar" \
    "$(awk "BEGIN { printf \"%.1f\", $got / 1000000 }")" "$(awk "BEGIN { printf \"%.0f\", $TOTAL / 1000000 }")"
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
if [ -z "$UV" ]; then
  case $(uname -m) in
    arm64) arch=aarch64 uv_sha=$UV_SHA256_arm64 uv_size=$UV_SIZE_arm64 ;;
    x86_64) arch=x86_64 uv_sha=$UV_SHA256_x86_64 uv_size=$UV_SIZE_x86_64 ;;
    *) fail "This Mac's processor ($(uname -m)) is not supported." ;;
  esac
  TOTAL=$uv_size
fi
TOTAL=$((TOTAL + CLI_SIZE + ENGINE_SIZE))

if [ -z "$UV" ]; then
  fetch "$UV_BASE/uv-$arch-apple-darwin.tar.gz" uv.tar.gz
  check uv.tar.gz "$uv_sha"
fi
fetch "$BASE/$CLI_WHEEL" "$CLI_WHEEL"
fetch "$BASE/$ENGINE_WHEEL" "$ENGINE_WHEEL"
check "$CLI_WHEEL" "$CLI_SHA256"
check "$ENGINE_WHEEL" "$ENGINE_SHA256"
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
if ! "$UV" tool install --force --python 3.12 "$TMP/$CLI_WHEEL" --with "$TMP/$ENGINE_WHEEL" >"$TMP/uv.log" 2>&1; then
  tail -n 5 "$TMP/uv.log" >&2
  fail "Could not install Dawnmere (uv stopped; its last lines are above)."
fi

TOOLS=$("$UV" tool dir --bin 2>/dev/null || printf '%s' "$BIN")
# shellcheck disable=SC2016  # the line to paste keeps a literal $PATH
case ":$PATH:" in
  *":$TOOLS:"*) ;;
  *) printf 'To run dawnmere later, add this line to ~/.zshrc:\n  export PATH="%s:$PATH"\n' "$TOOLS" ;;
esac

[ -z "${LFLABS_MEMORY_NO_SETUP:-}" ] || exit 0
rm -rf "$TMP"
trap - EXIT INT TERM
# Under `curl | sh` our stdin is the script itself: setup asks its questions on the terminal.
if (exec </dev/tty) 2>/dev/null; then
  exec "$TOOLS/dawnmere" setup </dev/tty
fi
exec "$TOOLS/dawnmere" setup
