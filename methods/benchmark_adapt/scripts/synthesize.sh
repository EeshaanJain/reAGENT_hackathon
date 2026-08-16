#!/usr/bin/env bash
# Usage: scripts/synthesize.sh path/to/model_contract.yaml [path/to/execution_log.json] [--execute ...]
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

if [ $# -lt 1 ]; then
  echo "usage: $0 <path/to/model_contract.yaml> [path/to/execution_log.json] [-- extra args, e.g. --execute --model ...]" >&2
  exit 2
fi

CONTRACT="$1"; shift
EXEC_LOG_ARGS=()
if [ $# -gt 0 ] && [[ "$1" != --* ]]; then
  EXEC_LOG_ARGS=(--execution-log "$1")
  shift
fi

python -m harness.synthesize_adapter --contract "$CONTRACT" "${EXEC_LOG_ARGS[@]}" "$@"
