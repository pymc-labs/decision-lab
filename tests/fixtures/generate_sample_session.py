"""
Generate the committed golden session fixture at tests/fixtures/sample_session/.

This is a small but structurally faithful COMPLETED dlab run — main
orchestrator + a two-instance parallel fan-out with a consolidator — used by
tests/test_sample_session.py to exercise the log parser, session graph,
timeline, viewer, and connect TUI end-to-end against real files.

Re-run after changing the fixture shape:
    python tests/fixtures/generate_sample_session.py

Timestamps and IDs are fixed so the fixture is deterministic and diffable.
Binary/oversized artifacts are NOT committed (some are gitignored, and large
files should not live in the repo); tests synthesize those at runtime.
"""

import base64
import json
import shutil
from pathlib import Path

FIXTURE = Path(__file__).parent / "sample_session"
TS = 1700000000000  # fixed base timestamp (ms)
RUN = f"poet-parallel-run-{TS}"

# Minimal valid 1x1 transparent PNG.
_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


def _line(event_type: str, ts: int, **body: object) -> str:
    return json.dumps({"type": event_type, "timestamp": ts, **body})


def _agent_log(model: str, agent: str, texts: list[str], base_ts: int) -> str:
    lines = [
        _line("dlab_start", base_ts, model=model, agent=agent),
        _line("step_start", base_ts, part={"type": "step-start"}),
    ]
    for i, t in enumerate(texts):
        lines.append(_line("text", base_ts + 100 + i, part={"type": "text", "text": t}))
    lines.append(
        _line("step_finish", base_ts + 1000, part={"type": "step-finish", "reason": "stop", "cost": 0.004})
    )
    return "\n".join(lines) + "\n"


def _main_log() -> str:
    lines = [
        _line("dlab_start", TS, model="anthropic/claude-sonnet-4-5", agent="main"),
        _line("step_start", TS, part={"type": "step-start"}),
        _line("text", TS + 100, part={"type": "text", "text": "I'll fan out three poets and consolidate."}),
        # The parallel-agents tool call that links the poet run dir.
        _line(
            "tool_use",
            TS + 200,
            part={
                "tool": "parallel-agents",
                "state": {
                    "status": "completed",
                    "input": {"agent": "poet", "prompts": ["haiku", "sonnet"]},
                    "time": {"start": TS + 200, "end": TS + 5000},
                },
            },
        ),
        _line("text", TS + 6000, part={"type": "text", "text": "Consolidated; writing final_poem.md."}),
        _line("step_finish", TS + 7000, part={"type": "step-finish", "reason": "stop", "cost": 0.021}),
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    if FIXTURE.exists():
        shutil.rmtree(FIXTURE)
    logs = FIXTURE / "_opencode_logs"
    run_logs = logs / RUN
    run_logs.mkdir(parents=True)

    (logs / "main.log").write_text(_main_log())
    (run_logs / "instance-1.log").write_text(
        _agent_log("anthropic/claude-sonnet-4-5", "poet", ["A haiku about config."], TS + 300)
    )
    (run_logs / "instance-2.log").write_text(
        _agent_log("anthropic/claude-sonnet-4-5", "poet", ["A sonnet about logs."], TS + 400)
    )
    (run_logs / "consolidator.log").write_text(
        _agent_log("anthropic/claude-sonnet-4-5", "consolidator", ["Instance 2 was best."], TS + 5000)
    )

    # Parallel instance work dirs + summaries.
    run_work = FIXTURE / "parallel" / f"run-{TS}"
    (run_work / "instance-1").mkdir(parents=True)
    (run_work / "instance-2").mkdir(parents=True)
    (run_work / "instance-1" / "summary.md").write_text("# Instance 1\nA haiku.\n")
    (run_work / "instance-1" / "poem.txt").write_text("config in yaml / ...\n")
    (run_work / "instance-2" / "summary.md").write_text("# Instance 2\nA sonnet.\n")
    (run_work / "consolidated_summary.md").write_text("Instance 2 chosen.\n")

    # Root artifacts — a mix of curated and non-curated (expander) types.
    (FIXTURE / "final_poem.md").write_text("# Final poem\nLogs in the dark...\n")
    (FIXTURE / "report.md").write_text("# Report\nDone.\n")
    (FIXTURE / "data.csv").write_text("word,count\nconfig,3\nlog,5\n")
    (FIXTURE / "results.json").write_text(json.dumps({"chosen": "instance-2"}, indent=2))
    (FIXTURE / "plot.png").write_bytes(_PNG)
    # Small binary artifact (fake parquet magic) — exercises the binary card.
    (FIXTURE / "predictions.parquet").write_bytes(b"PAR1" + bytes(range(256)) + b"PAR1")

    (FIXTURE / ".state.json").write_text(
        json.dumps({"dpack_name": "poem", "status": "completed", "model": "anthropic/claude-sonnet-4-5"}, indent=2)
    )

    print(f"Wrote sample session fixture to {FIXTURE}")


if __name__ == "__main__":
    main()
