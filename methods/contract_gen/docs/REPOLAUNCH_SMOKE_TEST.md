# RepoLaunch Smoke Test

## Overview

Verifies that RepoLaunch's setup stage works end-to-end on the scAPE repository, using the real,
vendored RepoLaunch CLI via LiteLLM. This is the narrowest possible test of the RepoLaunch
integration in isolation, before trusting it inside the full orchestrator (`harness/orchestrator.py`).

## Files

- **Test script:** `smoke_tests/test_repolaunch_scape.py`
- **Reusable runner it exercises:** `harness/repolaunch_runner.py`
- **Fixtures:**
  - `fixtures/paperclip_scape_record.json` — the input, parsed via `harness/paperclip_intake.py`
    into a RepoLaunch instance (see the file's own `_note`: there's no real Paperclip output for
    scAPE, so this is a minimal, honestly-incomplete stand-in — only fields verified against the
    real repo are populated)
  - `fixtures/repolaunch_config_scape.json` — RepoLaunch configuration (model, steps, timeouts —
    orthogonal to the paperclip record, always required regardless of input path)
- **Result:** `smoke_tests/results/repolaunch_scape_result.json`

## How to run

### Prerequisites

1. **Docker daemon running** — `docker info`
2. **RepoLaunch installed** in its own env (see `../README.md` — it needs Python >= 3.12, separate
   from the shared `reagent` env): `ls ../RepoLaunch/.venv/bin/launch`
3. **Credentials set**:
   ```bash
   export ANTHROPIC_API_KEY="sk-ant-..."
   export TAVILY_API_KEY="tvly-..."   # RepoLaunch's own web-search tool, required
   ```
4. **Model access** — the default is `anthropic/claude-sonnet-5` (set in
   `fixtures/repolaunch_config_scape.json`). Your API key needs access to whatever model you set
   there.

### Run

```bash
cd methods/contract_gen
python smoke_tests/test_repolaunch_scape.py
```

### Check results

```bash
cat smoke_tests/results/repolaunch_scape_result.json
```

## Result statuses

- **PASS** — setup completed, a Docker image was built and verified with `docker image inspect`.
- **FAIL** — setup ran but did not complete, or the image is missing/invalid.
- **BLOCKED** — a prerequisite is missing (Docker, credentials, or the vendored `launch` binary).
  Distinguished from FAIL deliberately: BLOCKED means the test never got to attempt anything.

## What gets tested

1. Prerequisite checks (Docker, credentials, the vendored binary)
2. Repository resolution (current HEAD of scAPE, or a pinned commit if the instance specifies one)
3. Config + dataset.jsonl construction
4. Real `launch <config>` CLI invocation
5. `result.json` validation
6. `docker image inspect` on the resulting image

## What's out of scope for this smoke test

- Repo comprehension (`harness/orchestrator.py`'s heuristic stage, or real Serena)
- Contract synthesis
- Benchmark execution / adapter generation (that's `benchmark_adapt/`, Sei's lane)

## Notes

- No secrets in fixtures — API keys come from the environment only.
- All paths are repo-relative.
- `paperclip_intake.to_repolaunch_instance()` defaults `base_commit` to `"RESOLVED_AT_RUNTIME"` --
  the runner resolves it to scAPE's current HEAD SHA and records the resolved value in the result.
  For a real integration you'd pin an actual SHA instead (see `fixtures/paperclip_cpa_record.json`
  -> `harness.orchestrator`, which resolves CPA's commit via `git ls-remote` ahead of time).
