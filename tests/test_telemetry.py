"""Tests for dlab.telemetry: env gating, span tree, usage, follow mode.

Uses the OpenTelemetry SDK's in-memory exporters, so no collector is needed;
the OTLP exporters are never constructed here.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

otel = pytest.importorskip("opentelemetry.sdk")

try:  # SDK >= 1.4x renamed it; logs are not stable yet
    from opentelemetry.sdk._logs.export import InMemoryLogRecordExporter as InMemoryLogExporter  # noqa: E402
except ImportError:  # pragma: no cover
    from opentelemetry.sdk._logs.export import InMemoryLogExporter  # noqa: E402
from opentelemetry.sdk.metrics.export import InMemoryMetricReader  # noqa: E402
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (  # noqa: E402
    InMemorySpanExporter,
)

from dlab import telemetry  # noqa: E402


def _ev(kind: str, ts: int, session: str = "ses_1", **part) -> str:
    return json.dumps({"type": kind, "timestamp": ts, "sessionID": session, "part": part})


def _write_session(work_dir: Path, *, with_end: bool = True, parallel: bool = True) -> None:
    logs = work_dir / "_opencode_logs"
    logs.mkdir(parents=True)
    main = [
        json.dumps({"type": "dlab_start", "timestamp": 1000, "model": "anthropic/x", "agent": "main", "prompt": "hi"}),
        _ev("step_start", 1010, messageID="m1"),
        _ev("text", 1020, text="thinking about it"),
        _ev("tool_use", 1030, tool="skill", callID="c1",
            state={"status": "completed", "input": {}, "output": "ok", "time": {"start": 1025, "end": 1030}}),
        _ev("step_finish", 1040, messageID="m1", reason="tool-calls",
            tokens={"input": 10, "output": 5, "reasoning": 0, "cache": {"read": 3, "write": 4}}, cost=0.5),
        _ev("step_start", 1050, messageID="m2"),
        _ev("step_finish", 1060, messageID="m2", reason="stop", tokens={"input": 1, "output": 1}, cost=0.25),
    ]
    if with_end:
        main.append(json.dumps({"type": "dlab_end", "timestamp": 1070, "outcome": "success", "exit_code": 0, "interrupted": False}))
    (logs / "main.log").write_text("\n".join(main) + "\n")
    if parallel:
        run = logs / "modeler-parallel-run-1000"
        run.mkdir()
        inst = [
            json.dumps({"type": "dlab_start", "timestamp": 1031, "model": "anthropic/y", "agent": "modeler", "prompt": "p"}),
            _ev("step_start", 1032, session="ses_2", messageID="k1"),
            _ev("error", 1033, session="ses_2", error="boom"),
            _ev("step_finish", 1034, session="ses_2", messageID="k1", reason="error", tokens={"input": 2, "output": 2}, cost=0.1),
        ]
        (run / "instance-1.log").write_text("\n".join(inst) + "\n")


def _make(work_dir: Path):
    spans, logs, metrics = InMemorySpanExporter(), InMemoryLogExporter(), InMemoryMetricReader()
    t = telemetry.SessionTelemetry(
        work_dir, None, "dlab-test", {"dlab.dpack": "poem"},
        span_exporter=spans, log_exporter=logs, metric_reader=metrics,
    )
    return t, spans, logs, metrics


def test_disabled_without_endpoint(monkeypatch):
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    assert not telemetry.is_enabled()
    with pytest.raises(ValueError):
        telemetry.export_session("/nowhere")


def test_env_parsing(monkeypatch):
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://c:4318/")
    monkeypatch.setenv("DLAB_OTEL_FOLLOW", "true")
    monkeypatch.setenv("DLAB_OTEL_INTERVAL", "0.1")
    assert telemetry.otlp_endpoint() == "http://c:4318"
    assert telemetry.follow_enabled()
    assert telemetry.follow_interval() == 1.0  # floor


def test_one_shot_export_builds_the_tree(tmp_path):
    _write_session(tmp_path)
    t, spans, logs, metrics = _make(tmp_path)
    t.poll()
    t.finish()

    finished = {s.name: s for s in spans.get_finished_spans()}
    assert set(finished) >= {"session", "agent:main", "agent:modeler/instance-1", "step", "tool:skill"}
    session = finished["session"]
    assert session.attributes["dlab.session.outcome"] == "success"
    assert session.attributes["gen_ai.usage.input_tokens"] == 13
    assert session.attributes["gen_ai.usage.output_tokens"] == 8
    assert session.attributes["gen_ai.usage.cost"] == pytest.approx(0.85)
    assert session.attributes["dlab.agent.count"] == 2
    assert session.resource.attributes["service.name"] == "dlab-test"
    assert session.resource.attributes["dlab.dpack"] == "poem"

    main = finished["agent:main"]
    assert main.parent.span_id == session.context.span_id
    assert main.attributes["gen_ai.request.model"] == "anthropic/x"
    assert main.attributes["gen_ai.usage.cost"] == pytest.approx(0.75)

    # Timestamps come from the log, not from now().
    assert session.start_time == 1000 * 1_000_000
    tool = finished["tool:skill"]
    assert tool.start_time == 1025 * 1_000_000 and tool.end_time == 1030 * 1_000_000
    assert tool.attributes["gen_ai.tool.call_id"] == "c1"
    # The tool sits under the step that was open at the time.
    steps = [s for s in spans.get_finished_spans() if s.name == "step"]
    assert tool.parent.span_id in {s.context.span_id for s in steps}
    first_step = min(steps, key=lambda s: s.start_time)
    assert first_step.attributes["gen_ai.usage.input_tokens"] == 10
    assert first_step.attributes["dlab.usage.cache_write_tokens"] == 4

    # The failed instance is marked, and its error is a log record.
    inst = finished["agent:modeler/instance-1"]
    assert inst.status.status_code.name == "ERROR"
    bodies = [r.log_record.body for r in logs.get_finished_logs()]
    assert "boom" in bodies and "thinking about it" not in bodies  # text needs DLAB_OTEL_PROMPTS

    # Metrics: token counter by type, cost counter.
    data = metrics.get_metrics_data()
    names = {m.name for rm in data.resource_metrics for sm in rm.scope_metrics for m in sm.metrics}
    assert {"gen_ai.client.token.usage", "dlab.cost.usd"} <= names


def test_prompts_are_kept_out_of_logs_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv("DLAB_OTEL_PROMPTS", raising=False)
    _write_session(tmp_path, parallel=False)
    t, spans, logs, _ = _make(tmp_path)
    t.poll(); t.finish()
    bodies = [r.log_record.body for r in logs.get_finished_logs()]
    assert "hi" not in bodies and "ok" not in bodies


def test_follow_mode_exports_children_before_the_root(tmp_path):
    logs_dir = tmp_path / "_opencode_logs"
    logs_dir.mkdir()
    main = logs_dir / "main.log"
    main.write_text(json.dumps({"type": "dlab_start", "timestamp": 1000, "model": "m", "agent": "main"}) + "\n")

    t, spans, _, _ = _make(tmp_path)
    t.poll()
    assert spans.get_finished_spans() == ()  # session + agent open, nothing finished

    with open(main, "a") as f:
        f.write(_ev("step_start", 1010, messageID="m1") + "\n")
        f.write(_ev("step_finish", 1020, messageID="m1", reason="stop", tokens={"input": 1, "output": 1}, cost=0.1) + "\n")
        f.write('{"type":"text","timestamp":1030,"sessionID":"ses_1","part":{"te')  # truncated line
    t.poll()
    t._tracer_provider.force_flush()
    names = [s.name for s in spans.get_finished_spans()]
    assert names == ["step"]  # the completed step is out; root and agent still open

    with open(main, "a") as f:
        f.write('xt":"done"}}\n')  # the rest of the truncated line
    t.finish(outcome="success", exit_code=0)
    finished = {s.name: s for s in spans.get_finished_spans()}
    assert {"session", "agent:main", "step"} <= set(finished)
    assert finished["session"].attributes["dlab.session.exit_code"] == 0
    assert finished["session"].end_time >= finished["step"].end_time


def test_derive_outcome_without_sentinel(tmp_path):
    _write_session(tmp_path, with_end=False, parallel=False)
    t, spans, _, _ = _make(tmp_path)
    t.poll(); t.finish()
    session = next(s for s in spans.get_finished_spans() if s.name == "session")
    assert session.attributes["dlab.session.outcome"] == "success"  # last step_finish reason "stop"


def test_write_end_sentinel(tmp_path):
    logs = tmp_path / "_opencode_logs"; logs.mkdir()
    (logs / "main.log").write_text("{}\n")
    telemetry.write_end_sentinel(tmp_path, "error", 2, False)
    last = json.loads((logs / "main.log").read_text().splitlines()[-1])
    assert last == {"type": "dlab_end", "timestamp": last["timestamp"], "outcome": "error", "exit_code": 2, "interrupted": False}
    telemetry.write_end_sentinel(tmp_path / "missing", "x", 1, True)  # no main.log: silent


def test_session_id_is_random_persisted_and_overridable(tmp_path, monkeypatch):
    monkeypatch.delenv("DLAB_SESSION_ID", raising=False)
    a, b = tmp_path / "a" / "dlab-poem-workdir-001", tmp_path / "b" / "dlab-poem-workdir-001"
    a.mkdir(parents=True); b.mkdir(parents=True)
    first = telemetry.session_id(a)
    assert first == telemetry.session_id(a)  # stable: kept in the work dir
    assert (a / telemetry.SESSION_ID_FILE).read_text().strip() == first
    assert telemetry.session_id(b) != first  # same dir NAME, different session
    assert first not in ("dlab-poem-workdir-001", "")
    assert telemetry.new_session_id(a) != first  # a continued run gets a new id
    assert telemetry.session_id(tmp_path / "missing")  # no dir: random, not persisted
    monkeypatch.setenv("DLAB_SESSION_ID", "wf-abc")
    assert telemetry.session_id(a) == "wf-abc"


def test_continued_session_skips_earlier_parallel_runs(tmp_path, monkeypatch):
    monkeypatch.setenv("DLAB_SESSION_ID", "wf-cont")
    _write_session(tmp_path, parallel=True)  # run at ts 1000 with modeler-parallel-run-1000
    logs = tmp_path / "_opencode_logs"
    # A continued run: main.log starts over later, the old instance folder stays.
    (logs / "main.log").write_text(
        json.dumps({"type": "dlab_start", "timestamp": 5000, "model": "m", "agent": "main"}) + "\n"
        + _ev("step_start", 5010, messageID="n1") + "\n"
        + _ev("step_finish", 5020, messageID="n1", reason="stop", tokens={"input": 1, "output": 1}, cost=0.2) + "\n"
    )
    new_run = logs / "modeler-parallel-run-5005"
    new_run.mkdir()
    (new_run / "instance-1.log").write_text(
        json.dumps({"type": "dlab_start", "timestamp": 5006, "model": "m", "agent": "modeler"}) + "\n"
        + _ev("step_start", 5007, session="ses_9", messageID="q1") + "\n"
        + _ev("step_finish", 5008, session="ses_9", messageID="q1", reason="stop", tokens={"input": 1, "output": 1}, cost=0.3) + "\n"
    )
    t, spans, _, _ = _make(tmp_path)
    t.poll(); t.finish()
    finished = {s.name: s for s in spans.get_finished_spans()}
    assert set(finished) == {"session", "agent:main", "agent:modeler/instance-1", "step"} or \
        sorted(s.name for s in spans.get_finished_spans()).count("step") == 2
    files = {s.attributes.get("dlab.log_file") for s in spans.get_finished_spans() if s.name.startswith("agent:")}
    assert files == {"main.log", "modeler-parallel-run-5005/instance-1.log"}  # run-1000 skipped
    assert finished["session"].attributes["gen_ai.usage.cost"] == pytest.approx(0.5)  # not 0.5 + 0.75 + 0.1


def test_second_parallel_run_of_an_agent_gets_its_own_name(tmp_path, monkeypatch):
    monkeypatch.setenv("DLAB_SESSION_ID", "wf-two")
    _write_session(tmp_path, parallel=True)
    logs = tmp_path / "_opencode_logs"
    again = logs / "modeler-parallel-run-1050"
    again.mkdir()
    (again / "instance-1.log").write_text(
        json.dumps({"type": "dlab_start", "timestamp": 1051, "model": "m", "agent": "modeler"}) + "\n"
    )
    t, spans, _, _ = _make(tmp_path)
    t.poll(); t.finish()
    names = sorted(s.name for s in spans.get_finished_spans() if s.name.startswith("agent:"))
    assert names == ["agent:main", "agent:modeler/instance-1", "agent:modeler/run2/instance-1"]


def test_agent_text_is_behind_the_prompts_flag(tmp_path, monkeypatch):
    _write_session(tmp_path, parallel=False)
    monkeypatch.delenv("DLAB_OTEL_PROMPTS", raising=False)
    t, _, logs, _ = _make(tmp_path)
    t.poll(); t.finish()
    assert "thinking about it" not in [r.log_record.body for r in logs.get_finished_logs()]
    monkeypatch.setenv("DLAB_OTEL_PROMPTS", "1")
    t, _, logs, _ = _make(tmp_path)
    t.poll(); t.finish()
    assert "thinking about it" in [r.log_record.body for r in logs.get_finished_logs()]


def test_file_cursor_keeps_multibyte_chars_split_across_polls(tmp_path):
    path = tmp_path / "x.log"
    line = json.dumps({"type": "text", "part": {"text": "caf\u00e9 \u2014 ok"}}, ensure_ascii=False).encode()
    cut = line.index("\u00e9".encode()) + 1  # between the two bytes of "é"
    path.write_bytes(line[:cut])
    cursor = telemetry._FileCursor(path)
    assert cursor.read_new_lines() == []
    path.write_bytes(line + b"\n")
    assert cursor.read_new_lines() == [line.decode()]


def test_traceparent_becomes_a_link_not_the_parent(tmp_path, monkeypatch):
    monkeypatch.setenv("DLAB_SESSION_ID", "wf-linked")
    monkeypatch.setenv("TRACEPARENT", "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01")
    _write_session(tmp_path, parallel=False)
    t, spans, _, _ = _make(tmp_path)
    t.poll(); t.finish()
    session = next(s for s in spans.get_finished_spans() if s.name == "session")
    assert session.parent is None
    assert (session.context.trace_id, session.context.span_id) == telemetry.session_trace_ids("wf-linked")
    assert [link.context.trace_id for link in session.links] == [0x0af7651916cd43dd8448eb211c80319c]


def test_resource_env_merges_and_encodes():
    base = {"OTEL_EXPORTER_OTLP_ENDPOINT": "http://c:4318",
            "OTEL_RESOURCE_ATTRIBUTES": "pymc.run.id=wf-1,dlab.role=custom,broken,=novalue"}
    out = telemetry.resource_env(base, session_id="wf-1", dpack="a,b=c")
    attrs = telemetry.parse_resource_attributes(out["OTEL_RESOURCE_ATTRIBUTES"])
    assert attrs == {"pymc.run.id": "wf-1", "dlab.role": "custom", "pymc.workload": "dlab",
                     "dlab.session.id": "wf-1", "dlab.dpack": "a,b=c"}  # existing keys win, junk dropped
    assert "a%2Cb%3Dc" in out["OTEL_RESOURCE_ATTRIBUTES"]  # values encoded for opencode
    assert out["DLAB_SESSION_ID"] == "wf-1"
    assert base["OTEL_RESOURCE_ATTRIBUTES"].startswith("pymc.run.id")  # input untouched
    # No endpoint: nothing happens.
    assert telemetry.resource_env({"X": "1"}, session_id="s", dpack="d") == {"X": "1"}


def test_trace_id_is_stable_for_a_session(tmp_path, monkeypatch):
    monkeypatch.setenv("DLAB_SESSION_ID", "wf-stable")
    _write_session(tmp_path, parallel=False)
    ids = []
    for _ in range(2):
        t, spans, _, _ = _make(tmp_path)
        t.poll(); t.finish()
        session = next(s for s in spans.get_finished_spans() if s.name == "session")
        ids.append((session.context.trace_id, session.context.span_id))
        assert session.attributes["dlab.session.id"] == "wf-stable"
        assert session.resource.attributes["pymc.workload"] == "dlab"
        assert session.resource.attributes["dlab.role"] == "orchestrator"
        # Every span of the session shares the trace id.
        assert {s.context.trace_id for s in spans.get_finished_spans()} == {session.context.trace_id}
    assert ids[0] == ids[1] == (telemetry.session_trace_ids("wf-stable"))
