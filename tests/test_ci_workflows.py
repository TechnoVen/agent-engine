from pathlib import Path
import yaml


def test_ci_workflow_validity_and_structure():
    """Verify that .github/workflows/ci.yml is valid YAML and defines required jobs."""
    ci_path = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "ci.yml"
    assert ci_path.exists(), f"CI workflow missing: {ci_path}"

    with open(ci_path, "r", encoding="utf-8") as f:
        ci_config = yaml.safe_load(f)

    assert ci_config is not None
    assert "jobs" in ci_config
    jobs = ci_config["jobs"]

    expected_jobs = [
        "lint-and-format",
        "test-python",
        "schema-validation",
        "monorepo-workspaces",
    ]
    for job_name in expected_jobs:
        assert job_name in jobs, f"Missing required CI job: {job_name}"

    # Verify multi-OS / python matrix in test-python
    test_job = jobs["test-python"]
    assert "strategy" in test_job
    matrix = test_job["strategy"]["matrix"]
    assert "ubuntu-latest" in matrix["os"]
    assert "macos-latest" in matrix["os"]
    assert "3.11" in matrix["python-version"]
    assert "3.12" in matrix["python-version"]

    # Verify triggers
    # on can be parsed as boolean True by YAML if written unquoted, or dict
    on_trigger = ci_config.get(True) or ci_config.get("on")
    assert on_trigger is not None, "Missing triggers ('on') in CI workflow"
    assert "push" in on_trigger
    assert "pull_request" in on_trigger


def test_release_workflow_validity_and_structure():
    """Verify that .github/workflows/release.yml is valid YAML and defines release steps."""
    release_path = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "release.yml"
    assert release_path.exists(), f"Release workflow missing: {release_path}"

    with open(release_path, "r", encoding="utf-8") as f:
        release_config = yaml.safe_load(f)

    assert release_config is not None
    assert "jobs" in release_config
    assert "build-and-release" in release_config["jobs"]

    on_trigger = release_config.get(True) or release_config.get("on")
    assert on_trigger is not None, "Missing triggers ('on') in Release workflow"
    assert "push" in on_trigger
    assert "tags" in on_trigger["push"]
    assert "v*.*.*" in on_trigger["push"]["tags"]
