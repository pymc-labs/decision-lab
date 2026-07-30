"""
Extract a conversation slice from a Claude Code session transcript (JSONL).

Used to preserve feature-spec discussions verbatim for traceability.
Only plain text turns are extracted (tool calls, tool results, and thinking
blocks are omitted); text is otherwise reproduced verbatim.

Usage:
    python extract_spec_conversation.py <session.jsonl> <start-marker> <output.md> [title]

The slice starts at the first *user* message containing <start-marker>
and runs to the end of the transcript.
"""

import json
import sys
from datetime import datetime


def extract_texts(content) -> list[str]:
    """Return the plain-text blocks of a message content payload."""
    if isinstance(content, str):
        return [content]
    texts: list[str] = []
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text", "")
                if text and text.strip():
                    texts.append(text)
    return texts


def main() -> int:
    if len(sys.argv) < 4:
        print(__doc__, file=sys.stderr)
        return 1
    transcript, marker, out_path = sys.argv[1], sys.argv[2], sys.argv[3]
    title: str = sys.argv[4] if len(sys.argv) > 4 else "Spec conversation (verbatim)"

    turns: list[tuple[str, str]] = []
    started: bool = False
    with open(transcript) as f:
        for line in f:
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            role = obj.get("type")
            if role not in ("user", "assistant"):
                continue
            texts = extract_texts(obj.get("message", {}).get("content"))
            if not texts:
                continue
            text = "\n\n".join(texts)
            if not started:
                if role == "user" and marker in text:
                    started = True
                else:
                    continue
            turns.append((role, text))

    if not turns:
        print(f"Marker not found in transcript: {marker!r}", file=sys.stderr)
        return 1

    with open(out_path, "w") as f:
        f.write(f"# {title}\n\n")
        f.write(
            f"Extracted verbatim from Claude Code session transcript "
            f"`{transcript.rsplit('/', 1)[-1]}` on "
            f"{datetime.now():%Y-%m-%d} for full traceability. "
            f"Tool calls and tool results are omitted; the dialogue text is unedited.\n\n---\n\n"
        )
        for role, text in turns:
            speaker = "**Ben**" if role == "user" else "**Claude**"
            f.write(f"## {speaker}\n\n{text}\n\n---\n\n")
    print(f"Wrote {len(turns)} turns to {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
