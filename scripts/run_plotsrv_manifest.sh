#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
MANIFEST_FILE="${PLOTSRV_MANIFEST_FILE:-$PROJECT_ROOT/plotsrv-release.toml}"
PTOP_DB_PATH="${PTOP_DB:-$PROJECT_ROOT/.ptop/plotsrv.sqlite3}"

die() {
  echo "error: $*" >&2
  exit 2
}

command -v ptop >/dev/null 2>&1 || die "ptop is not installed or not on PATH"
command -v uv >/dev/null 2>&1 || die "uv is not installed or not on PATH"
[[ -f "$MANIFEST_FILE" ]] || die "manifest not found: $MANIFEST_FILE"

mkdir -p "$(dirname "$PTOP_DB_PATH")"

echo "Running plotsrv ptop manifest"
echo "  manifest: $MANIFEST_FILE"
echo "  database: $PTOP_DB_PATH"

exec ptop --db "$PTOP_DB_PATH" manifest run "$MANIFEST_FILE" "$@"
