#!/usr/bin/env bash
# Thin wrapper for Linux/macOS CI and shells.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
if command -v uv >/dev/null 2>&1; then
  exec uv run python scripts/pull_images.py "$@"
fi
exec python3 scripts/pull_images.py "$@"
