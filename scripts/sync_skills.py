"""
Sync check for the published dlab-cli skill bundle.

The Claude Code skills in ``.claude/skills/`` are the source of truth.
Four of them are republished (frontmatter stripped) as reference files of
the consolidated ``skills/dlab-cli`` skill. This script verifies the
published copies are byte-identical to their sources, and can regenerate
them.

Usage:
    python scripts/sync_skills.py           # check, exit 1 on drift
    python scripts/sync_skills.py --write   # regenerate references from sources
"""

import argparse
import difflib
import sys
from pathlib import Path


REPO_ROOT: Path = Path(__file__).resolve().parent.parent

# source skill (in .claude/skills/) -> published reference (in skills/dlab-cli/)
SKILL_MAPPING: dict[str, str] = {
    ".claude/skills/create-dpack/SKILL.md": "skills/dlab-cli/references/create-dpack.md",
    ".claude/skills/create-dpack-interactive/SKILL.md": "skills/dlab-cli/references/create-dpack-interactive.md",
    ".claude/skills/run-analyzer/SKILL.md": "skills/dlab-cli/references/run-analyzer.md",
    ".claude/skills/create-agents/SKILL.md": "skills/dlab-cli/references/agent-design.md",
}


def strip_frontmatter(text: str) -> str:
    """
    Remove a leading YAML frontmatter block from markdown text.

    Parameters
    ----------
    text : str
        Markdown file content.

    Returns
    -------
    str
        Content without the leading ``---`` ... ``---`` block. Returned
        unchanged if no frontmatter is present.
    """
    lines: list[str] = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return text
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            return "\n".join(lines[i + 1 :])
    return text


def check_sync(write: bool = False) -> int:
    """
    Compare (or regenerate) published references against their sources.

    Parameters
    ----------
    write : bool
        If True, overwrite each reference file with the frontmatter-stripped
        source instead of reporting drift.

    Returns
    -------
    int
        0 if everything is in sync (or was rewritten), 1 on drift or
        missing files in check mode.
    """
    exit_code: int = 0
    for src_rel, ref_rel in SKILL_MAPPING.items():
        src_path: Path = REPO_ROOT / src_rel
        ref_path: Path = REPO_ROOT / ref_rel
        if not src_path.exists():
            print(f"MISSING SOURCE: {src_rel}")
            exit_code = 1
            continue

        expected: str = strip_frontmatter(src_path.read_text())
        if write:
            ref_path.write_text(expected)
            print(f"wrote {ref_rel}")
            continue

        if not ref_path.exists():
            print(f"MISSING REFERENCE: {ref_rel}")
            exit_code = 1
            continue

        actual: str = ref_path.read_text()
        if actual != expected:
            exit_code = 1
            print(f"OUT OF SYNC: {ref_rel} != {src_rel} (minus frontmatter)")
            diff = difflib.unified_diff(
                expected.splitlines(keepends=True),
                actual.splitlines(keepends=True),
                fromfile=f"{src_rel} (stripped)",
                tofile=ref_rel,
                n=1,
            )
            sys.stdout.writelines(list(diff)[:40])
            print()

    if exit_code == 1:
        print(
            "\nSkill bundle out of sync. Edit the source in .claude/skills/ "
            "and run: python scripts/sync_skills.py --write"
        )
    return exit_code


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write",
        action="store_true",
        help="Regenerate skills/dlab-cli/references/ from .claude/skills/",
    )
    args = parser.parse_args()
    return check_sync(write=args.write)


if __name__ == "__main__":
    sys.exit(main())
