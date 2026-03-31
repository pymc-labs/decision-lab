"""
Template for the parallel-agents.ts tool.

This module loads the parallel-agents TypeScript source from dlab/js/
and exposes it as PARALLEL_AGENTS_SOURCE for use by session setup.

WARNING: The template contains an evil hack (git init) to work around OpenCode's config
traversal behavior. See "Git Init Hack" section in CLAUDE.md for details.
This should be replaced with a proper solution when OpenCode supports
disabling parent directory config traversal.
"""

from importlib.resources import files


PARALLEL_AGENTS_SOURCE: str = (
    files("dlab.js").joinpath("parallel-agents.ts").read_text()
)
