"""
Test that the published dlab-cli skill bundle is in sync with its sources.

The Claude Code skills in .claude/skills/ are the source of truth; four of
them are republished (frontmatter stripped) under skills/dlab-cli/references/.
This test fails when someone edits one copy without the other.

Fix drift with: python scripts/sync_skills.py --write
"""

import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
SYNC_SCRIPT = REPO_ROOT / "scripts" / "sync_skills.py"


def test_sync_script_exists() -> None:
    assert SYNC_SCRIPT.exists(), f"missing {SYNC_SCRIPT}"


def test_skill_bundle_in_sync() -> None:
    result = subprocess.run(
        [sys.executable, str(SYNC_SCRIPT)],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, (
        "skills/dlab-cli/references/ has drifted from .claude/skills/ — "
        "edit the source in .claude/skills/ and run "
        "'python scripts/sync_skills.py --write'.\n\n"
        f"{result.stdout}"
    )
