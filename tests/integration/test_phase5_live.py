"""
Phase 5 live integration test: full pipeline end-to-end.

Run with: pytest -m integration
NOT included in the default test run.
"""

import json
import subprocess
import sys

import pytest


@pytest.mark.integration
def test_full_pipeline_hn_to_json(tmp_path):
    """Full end-to-end: classify → fetch → extract → JSON file output."""
    output_file = tmp_path / "test_output.json"
    result = subprocess.run(
        [
            sys.executable, "-m", "pluck.cli",
            "https://news.ycombinator.com/",
            "--auto",
            "--output", str(output_file),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, (
        f"CLI exited with code {result.returncode}\n"
        f"stdout: {result.stdout}\n"
        f"stderr: {result.stderr}"
    )
    assert output_file.exists(), "Output file was not created"
    data = json.loads(output_file.read_text(encoding="utf-8"))
    assert isinstance(data, list), "Output is not a JSON array"
    assert len(data) > 0, "No items were extracted"


@pytest.mark.integration
def test_dry_run_produces_no_output_file(tmp_path):
    """--dry-run should exit cleanly without creating an output file."""
    output_file = tmp_path / "should_not_exist.json"
    result = subprocess.run(
        [
            sys.executable, "-m", "pluck.cli",
            "https://news.ycombinator.com/",
            "--dry-run",
            "--output", str(output_file),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"CLI failed: {result.stderr}"
    assert not output_file.exists(), "Output file should not be created on --dry-run"
