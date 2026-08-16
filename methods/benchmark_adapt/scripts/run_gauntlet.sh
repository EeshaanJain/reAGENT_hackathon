#!/usr/bin/env bash
# Usage: scripts/run_gauntlet.sh path/to/script.py [extra pytest args...]
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

if [ $# -lt 1 ]; then
  echo "usage: $0 <path/to/script.py> [extra pytest args...]" >&2
  exit 2
fi

ADAPTER="$1"; shift
if [ ! -f "fixtures/data/fixture_manifest.json" ]; then
  echo "fixture not found -- building it first"
  python fixtures/make_tiny_fixture.py
fi

python -m pytest gauntlet --adapter "$ADAPTER" -v "$@"
