"""Headless boot smoke test for the `dlab connect` TUI.

Unit tests cover the pure helpers (add_event dedup, completion detection),
but nothing else boots the Textual app end-to-end. This test mounts
ConnectApp against a synthetic work directory via Textual's headless
run_test harness and asserts it loads agents, ingests events (including a
same-millisecond pair — the #58 dedup path — through the live watcher),
handles key bindings, and exits without writing a crash log.
"""

import asyncio
import json
from pathlib import Path

import pytest

from dlab.tui.app import ConnectApp


def _line(event_type: str, ts: int, **part: object) -> str:
    return json.dumps({"type": event_type, "timestamp": ts, "part": part})


def _make_workdir(tmp_path: Path) -> Path:
    """A minimal completed session: main agent + one 2-instance parallel run."""
    logs = tmp_path / "_opencode_logs"
    logs.mkdir()

    # main.log — two events share the millisecond 1700000001000 (the #58 case:
    # both must survive into the TUI, not collapse to one).
    main = [
        _line("step_start", 1700000000000, id="p0", type="step-start"),
        _line("text", 1700000001000, id="p1", type="text", text="First thought."),
        _line("text", 1700000001000, id="p2", type="text", text="Second, same ms."),
        _line("step_finish", 1700000002000, reason="stop", cost=0.01),
    ]
    (logs / "main.log").write_text("\n".join(main) + "\n")

    run = logs / "poet-parallel-run-1700000000000"
    run.mkdir()
    for i in (1, 2):
        inst = [
            _line("step_start", 1700000000000 + i, id=f"s{i}", type="step-start"),
            _line("text", 1700000001000 + i, id=f"t{i}", type="text", text=f"poem {i}"),
            _line("step_finish", 1700000002000 + i, reason="stop", cost=0.005),
        ]
        (run / f"instance-{i}.log").write_text("\n".join(inst) + "\n")
    return tmp_path


@pytest.mark.asyncio
async def test_connect_tui_boots_and_loads_agents(tmp_path: Path) -> None:
    work_dir = _make_workdir(tmp_path)
    app = ConnectApp(work_dir)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await asyncio.sleep(0.6)  # let the log watcher ingest
        await pilot.pause()

        agents = app._state.agents
        # main + two instances = 3 agents discovered from the logs.
        assert len(agents) >= 3, f"expected >=3 agents, got {list(agents)}"
        assert "main" in agents

        # #58 through the live path: the two same-millisecond main texts both
        # survive (distinct content ⇒ not deduped).
        main_texts = [
            e for e in agents["main"].events
            if e.event_type == "text" and "same ms" in (e.raw.get("part", {}).get("text", ""))
        ]
        assert main_texts, "same-millisecond text event was dropped by dedup"

    # No crash log means _mount_impl did not raise.
    assert not (work_dir / ".dlab_tui_crash.log").exists(), (
        (work_dir / ".dlab_tui_crash.log").read_text()
    )


@pytest.mark.asyncio
async def test_connect_tui_keybindings_do_not_crash(tmp_path: Path) -> None:
    work_dir = _make_workdir(tmp_path)
    app = ConnectApp(work_dir)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await asyncio.sleep(0.3)
        for key in ("a", "j", "k", "e", "c"):  # artifacts, nav, expand/collapse
            await pilot.press(key)
            await pilot.pause()
    assert not (work_dir / ".dlab_tui_crash.log").exists()
