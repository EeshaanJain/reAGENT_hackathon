# RepoLaunch Smoke Test Documentation

## Overview

This smoke test verifies that RepoLaunch's setup stage works end-to-end on the scAPE repository. It tests the real RepoLaunch CLI integration with Anthropic API via LiteLLM.

## Files

- **Test script:** `smoke_tests/test_repolarunch_scape.py`
- **Fixtures:** 
  - `tests/fixtures/repolarunch_scape_instance.json` — instance metadata
  - `tests/fixtures/repolarunch_config_scape.json` — RepoLaunch configuration
- **Result:** `smoke_tests/results/repolarunch_scape_result.json`

## How to Run

### Prerequisites

1. **Docker daemon running**
   ```bash
   docker info
   ```

2. **RepoLaunch CLI installed**
   ```bash
   which launch
   ```

3. **Anthropic API key set**
   ```bash
   export ANTHROPIC_API_KEY="sk-ant-..."
   ```

4. **Available Anthropic model** — Your API key must have access to at least one of:
   - `claude-3-5-sonnet-20241022`
   - `claude-3-opus-20240229`
   - `claude-3-sonnet-20240229`
   - `claude-3-haiku-20240307`

### Run the Test

```bash
# Set credentials
export ANTHROPIC_API_KEY="sk-ant-..."
export TAVILY_API_KEY="tvly-..."  # if needed

# Optional: override default model
export REPOLAUNCH_MODEL="anthropic/claude-3-sonnet-20240229"

# Run the test
python smoke_tests/test_repolarunch_scape.py
```

### Check Results

```bash
cat smoke_tests/results/repolarunch_scape_result.json
```

## Result Statuses

### PASS
- RepoLaunch setup stage completed successfully
- Docker image was built and verified
- Example:
  ```json
  {
    "status": "PASS",
    "docker_image": "repolaunch/scape-test:scAPE_smoke_test_linux"
  }
  ```

### FAIL
- RepoLaunch setup completed but failed
- Docker image not found or invalid
- Example:
  ```json
  {
    "status": "FAIL",
    "exception": "Setup stage failed: ..."
  }
  ```

### BLOCKED
- A prerequisite is missing (Docker, RepoLaunch CLI, API key, or available model)
- Cannot proceed with the test
- Example:
  ```json
  {
    "status": "BLOCKED",
    "reason": "Anthropic API model not found",
    "assumptions_violated": ["Available Anthropic model"]
  }
  ```

## Model Configuration

The default model is `anthropic/claude-3-5-sonnet-20241022`. To use a different model:

1. **Option 1: Environment variable**
   ```bash
   export REPOLAUNCH_MODEL="anthropic/claude-3-sonnet-20240229"
   python smoke_tests/test_repolarunch_scape.py
   ```

2. **Option 2: Edit fixture**
   ```bash
   # Edit tests/fixtures/repolarunch_config_scape.json
   # Change "model_config": {"model": "anthropic/..."}
   ```

## Troubleshooting

### "Model not found" Error

If you see:
```
litellm.NotFoundError: AnthropicException - model: claude-3-5-sonnet-20241022 not found
```

Your ANTHROPIC_API_KEY doesn't have access to that model. Check:

1. **View available models:** https://console.anthropic.com/account/usage
2. **Try a different model:**
   ```bash
   export REPOLAUNCH_MODEL="anthropic/claude-3-haiku-20240307"
   python smoke_tests/test_repolarunch_scape.py
   ```

### "Docker not running" Error

```bash
docker info  # Start Docker if needed
```

### "launch not found" Error

RepoLaunch CLI not installed. Check:
```bash
which launch
```

If not found, the RepoLaunch venv may be needed:
```bash
source /Users/zhwu_cecilia/Documents/reAGENT_hackathon/methods/RepoLaunch/.venv/bin/activate
python smoke_tests/test_repolarunch_scape.py
```

## What Gets Tested

1. **Prerequisite checks:** Docker, launch CLI, ANTHROPIC_API_KEY
2. **Repository resolution:** Resolves current HEAD of scAPE
3. **Config creation:** Builds RepoLaunch config with resolved SHA
4. **CLI invocation:** Calls real `launch config_path` command
5. **Result validation:** Checks result.json exists and has required fields
6. **Docker image:** Verifies `docker image inspect` succeeds

## What Gets Skipped (Not in Smoke Test Scope)

- Serena repository analysis
- mini-SWE-agent model contract synthesis
- Organize stage (only tests setup)
- Benchmark execution
- Adapter generation

## Integration with Main Orchestrator

The smoke test validates the RepoLaunch interface independently. When integrating into the main method-integration orchestrator:

1. The test establishes that RepoLaunch can be invoked with:
   - Instance dict: `{instance_id, repo, base_commit}`
   - Config JSON: RepoLaunch format
   - Environment: ANTHROPIC_API_KEY + optional REPOLAUNCH_MODEL

2. The result schema shows what to expect:
   ```json
   {
     "completed": bool,
     "exception": str | null,
     "docker_image": str,
     "docker_image_layers": {...},
     "setup_commands": [...]
   }
   ```

3. The orchestrator will wrap RepoLaunch to:
   - Handle instance dict creation
   - Manage workspace directories
   - Capture and normalize results
   - Map statuses to the handoff contract

## Notes

- **No secrets in fixtures:** API keys come from environment only
- **Portable paths:** All paths are repo-relative
- **Current HEAD:** Resolves scAPE's latest commit at runtime, not pinned
- **Real CLI:** Uses actual `launch` command, not Python API directly
- **Timeout:** Configured for up to 10 minutes per RepoLaunch run

## Future Work

After this smoke test passes, the next steps are:

1. Integrate RepoLaunch into main orchestrator
2. Add Serena analysis stage (post-environment)
3. Add mini-SWE-agent for model contract synthesis
4. Implement handoff to Sei's adapter lane
