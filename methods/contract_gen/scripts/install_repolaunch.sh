#!/usr/bin/env bash
# Installs RepoLaunch into its own Python 3.12+ venv, separate from the shared `reagent` conda
# env (RepoLaunch requires Python >= 3.12; reagent is 3.11 -- confirmed via RepoLaunch's own
# pyproject.toml). Not on PyPI, so this vendors + installs from the pinned git submodule instead.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

if [ ! -d "RepoLaunch" ] || [ -z "$(ls -A RepoLaunch 2>/dev/null)" ]; then
  echo "Initializing RepoLaunch submodule..."
  git -C ../.. submodule update --init methods/contract_gen/RepoLaunch
fi

cd RepoLaunch

if ! command -v uv >/dev/null 2>&1; then
  echo "uv not found -- install it first: https://docs.astral.sh/uv/" >&2
  exit 1
fi

uv venv .venv --python 3.12
uv pip install --python .venv/bin/python -e .

echo
echo "RepoLaunch installed. Verify with:"
echo "  methods/contract_gen/RepoLaunch/.venv/bin/launch --help"
echo
echo "Still needed before running it for real:"
echo "  export ANTHROPIC_API_KEY=...   # RepoLaunch's own agent needs an LLM provider"
echo "  export TAVILY_API_KEY=...      # RepoLaunch's web-search tool, required"
echo "  docker info                    # must succeed -- RepoLaunch builds real images"
