#!/usr/bin/env python3
"""
RepoLaunch smoke test: verify setup stage works on scAPE using real RepoLaunch CLI.
Resolves current HEAD SHA, invokes real CLI with Anthropic API, validates docker_image.

Prerequisites:
- ANTHROPIC_API_KEY set in environment
- launch CLI installed
- Docker daemon running

Usage:
    export ANTHROPIC_API_KEY="sk-ant-..."
    python smoke_tests/test_repolarunch_scape.py
"""

import json
import subprocess
import sys
import os
from pathlib import Path
from datetime import datetime


def check_anthropic_credentials():
    """Verify ANTHROPIC_API_KEY is set."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return False, "ANTHROPIC_API_KEY not set in environment"
    return True, None


def get_model_config():
    """Get model config, with env var override."""
    model = os.environ.get(
        "REPOLAUNCH_MODEL",
        "anthropic/claude-3-5-sonnet-20241022"
    )
    return {"model": model}


def resolve_scape_commit():
    """Resolve current HEAD of scAPE repository."""
    result = subprocess.run(
        ["git", "-C", "work/scape_repo", "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False
    )
    if result.returncode != 0:
        raise RuntimeError(f"Failed to resolve scAPE commit: {result.stderr}")
    return result.stdout.strip()


def load_config_and_update_model(config_path, model_config):
    """Load config, update model_config, return updated dict."""
    with open(config_path) as f:
        config = json.load(f)
    config["model_config"] = model_config
    return config


def create_dataset_jsonl(dataset_path, instance_dict):
    """Write instance dict to JSONL format."""
    dataset_path.parent.mkdir(parents=True, exist_ok=True)
    with open(dataset_path, "w") as f:
        json.dump(instance_dict, f)
        f.write("\n")


def invoke_repolarunch(config_path):
    """Invoke 'launch config_path' CLI with environment credentials."""
    env = os.environ.copy()
    result = subprocess.run(
        ["launch", str(config_path)],
        env=env,
        capture_output=True,
        text=True,
        timeout=600
    )
    return result.returncode, result.stdout, result.stderr


def load_and_validate_result(result_path):
    """Load result.json and validate fields."""
    if not result_path.exists():
        raise FileNotFoundError(f"Result not found: {result_path}")

    with open(result_path) as f:
        result = json.load(f)

    # Validate required fields
    if "completed" not in result:
        raise ValueError("Result missing 'completed' field")

    return result


def verify_docker_image(docker_image):
    """Run 'docker image inspect' to confirm image exists."""
    result = subprocess.run(
        ["docker", "image", "inspect", docker_image],
        capture_output=True,
        text=True
    )
    return result.returncode == 0


def write_smoke_test_result(result_json_path, details):
    """Write result to smoke_tests/results/..."""
    result_json_path.parent.mkdir(parents=True, exist_ok=True)
    with open(result_json_path, "w") as f:
        json.dump(details, f, indent=2)


def main():
    """Main smoke test execution."""
    result_path = Path("smoke_tests/results/repolarunch_scape_result.json")

    # 1. Check prerequisites
    ok, msg = check_anthropic_credentials()
    if not ok:
        write_smoke_test_result(
            result_path,
            {
                "test_name": "repolarunch_smoke_test_scape",
                "status": "BLOCKED",
                "reason": msg,
                "assumptions_violated": ["ANTHROPIC_API_KEY must be set"],
                "timestamp": datetime.utcnow().isoformat()
            }
        )
        print(f"[BLOCKED] {msg}")
        return 1

    try:
        print("[INFO] All prerequisites passed. Starting RepoLaunch smoke test...")

        # 2. Resolve SHA
        print("[INFO] Resolving scAPE current HEAD...")
        resolved_sha = resolve_scape_commit()
        print(f"[INFO] Resolved to: {resolved_sha}")

        # 3. Get model config (with env override)
        model_config = get_model_config()
        print(f"[INFO] Using model: {model_config['model']}")

        # 4. Load fixtures
        instance_fixture = json.load(open("tests/fixtures/repolarunch_scape_instance.json"))
        instance_fixture["base_commit"] = resolved_sha

        config_dict = load_config_and_update_model(
            "tests/fixtures/repolarunch_config_scape.json",
            model_config
        )

        # 5. Create dataset.jsonl
        print("[INFO] Creating dataset.jsonl...")
        dataset_path = Path(config_dict["dataset"])
        create_dataset_jsonl(dataset_path, instance_fixture)

        # 6. Write config to temp location
        config_path = Path(config_dict["workspace_root"]) / "config.json"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(config_path, "w") as f:
            json.dump(config_dict, f, indent=2)
        print(f"[INFO] Config written to: {config_path}")

        # 7. Invoke RepoLaunch
        print("[INFO] Invoking RepoLaunch CLI...")
        exit_code, stdout, stderr = invoke_repolarunch(config_path)

        if exit_code != 0:
            write_smoke_test_result(
                result_path,
                {
                    "test_name": "repolarunch_smoke_test_scape",
                    "status": "FAIL",
                    "resolved_commit_sha": resolved_sha,
                    "exception": f"RepoLaunch CLI exited with code {exit_code}",
                    "stderr_excerpt": stderr[:500],
                    "timestamp": datetime.utcnow().isoformat()
                }
            )
            print(f"[FAIL] RepoLaunch exited with code {exit_code}")
            print(f"[DEBUG] stderr: {stderr[:200]}")
            return 1

        # 8. Load and validate result.json
        print("[INFO] Loading RepoLaunch result.json...")
        result_path_actual = (
            Path(config_dict["workspace_root"]) /
            "playground" /
            instance_fixture["instance_id"] /
            "result.json"
        )
        result = load_and_validate_result(result_path_actual)

        if not result.get("completed"):
            exception = result.get("exception", "Unknown error")
            write_smoke_test_result(
                result_path,
                {
                    "test_name": "repolarunch_smoke_test_scape",
                    "status": "FAIL",
                    "resolved_commit_sha": resolved_sha,
                    "setup_result": {
                        "completed": False,
                        "exception": exception
                    },
                    "timestamp": datetime.utcnow().isoformat()
                }
            )
            print(f"[FAIL] RepoLaunch setup did not complete: {exception}")
            return 1

        # 9. Verify docker_image
        docker_image = result.get("docker_image")
        print(f"[INFO] Verifying docker image: {docker_image}")

        if not docker_image:
            write_smoke_test_result(
                result_path,
                {
                    "test_name": "repolarunch_smoke_test_scape",
                    "status": "FAIL",
                    "resolved_commit_sha": resolved_sha,
                    "exception": "docker_image field is empty",
                    "timestamp": datetime.utcnow().isoformat()
                }
            )
            print("[FAIL] docker_image field is empty")
            return 1

        if not verify_docker_image(docker_image):
            write_smoke_test_result(
                result_path,
                {
                    "test_name": "repolarunch_smoke_test_scape",
                    "status": "FAIL",
                    "resolved_commit_sha": resolved_sha,
                    "docker_image": docker_image,
                    "exception": "Docker image does not exist or cannot be inspected",
                    "timestamp": datetime.utcnow().isoformat()
                }
            )
            print(f"[FAIL] Docker image does not exist: {docker_image}")
            return 1

        # 10. SUCCESS
        write_smoke_test_result(
            result_path,
            {
                "test_name": "repolarunch_smoke_test_scape",
                "status": "PASS",
                "timestamp": datetime.utcnow().isoformat(),
                "instance_id": instance_fixture["instance_id"],
                "repo": instance_fixture["repo"],
                "resolved_commit_sha": resolved_sha,
                "model_used": model_config["model"],
                "setup_result": {
                    "completed": result["completed"],
                    "exception": result.get("exception"),
                    "docker_image": docker_image
                },
                "docker_image_verified": True,
                "repolarunch_output_path": str(result_path_actual),
                "notes": "RepoLaunch setup completed successfully with Anthropic API."
            }
        )
        print(f"[PASS] Smoke test completed successfully!")
        print(f"[PASS] Docker image: {docker_image}")
        return 0

    except Exception as e:
        write_smoke_test_result(
            result_path,
            {
                "test_name": "repolarunch_smoke_test_scape",
                "status": "FAIL",
                "exception": str(e),
                "timestamp": datetime.utcnow().isoformat()
            }
        )
        print(f"[FAIL] Exception: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
