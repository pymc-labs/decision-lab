"""
OTEL post-processing exporter for dlab sessions.

Reads completed session logs (NDJSON) and emits OpenTelemetry traces + logs
to an OTLP endpoint (default: OpenLIT at http://localhost:4318).

Usage
-----
    from dlab.otel_exporter import export_session
    export_session("/path/to/work_dir")

Or via CLI:
    dlab trace /path/to/work_dir

Span hierarchy
--------------
    session (root span, one per dlab run)
    └── agent:<name> (one per SessionNode)
        ├── tool:<tool_name>:<callID> (tool_use events, paired start/end)
        └── step (step_start / step_finish pairs)

All LogEvents are also emitted as OTEL log records attached to their
nearest parent span, with full semconv attributes where available.

Attribute conventions
---------------------
- gen_ai.system = "opencode"
- gen_ai.request.model = model string from dlab_start
- gen_ai.agent.name = agent name from SessionNode
- gen_ai.tool.name = tool name from tool_use event
- dlab.session.outcome = success | error | interrupted (from dlab_end)
- dlab.event.type = raw LogEvent.event_type
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from dlab.opencode_logparser import (
    LogEvent,
    SessionNode,
    build_session_graph,
    parse_log_file,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NS_PER_MS = 1_000_000  # LogEvent.timestamp is milliseconds → OTEL nanoseconds


def _ms_to_ns(ts_ms: int | None) -> int:
    """Convert millisecond timestamp to nanoseconds. Returns now() if None."""
    if ts_ms is None:
        return time.time_ns()
    return ts_ms * _NS_PER_MS


def _get_dlab_end(events: list[LogEvent]) -> dict[str, Any] | None:
    """Return the dlab_end sentinel payload, or None if not present."""
    for ev in reversed(events):
        if ev.event_type == "dlab_end":
            return ev.raw
    return None


def _session_start_ns(events: list[LogEvent]) -> int:
    """Return the timestamp of the first timed event in nanoseconds."""
    for ev in events:
        if ev.timestamp is not None:
            return _ms_to_ns(ev.timestamp)
    return time.time_ns()


def _session_end_ns(events: list[LogEvent]) -> int:
    """Return the timestamp of the last timed event in nanoseconds."""
    last: int | None = None
    for ev in events:
        if ev.timestamp is not None:
            last = ev.timestamp
    return _ms_to_ns(last) if last is not None else time.time_ns()


# ---------------------------------------------------------------------------
# Core export
# ---------------------------------------------------------------------------

def export_session(
    work_dir: str | Path,
    otlp_endpoint: str = "http://localhost:4318",
    service_name: str = "dlab",
) -> None:
    """
    Export a completed dlab session as OTEL traces and logs.

    Parameters
    ----------
    work_dir : str | Path
        Path to the dlab session work directory (contains _opencode_logs/).
    otlp_endpoint : str
        OTLP/HTTP endpoint URL. Default: http://localhost:4318 (OpenLIT).
    service_name : str
        OTEL service.name attribute.

    Raises
    ------
    ImportError
        If opentelemetry-sdk or opentelemetry-exporter-otlp-proto-http
        are not installed. Install with: pip install 'dlab[otel]'
    FileNotFoundError
        If work_dir/_opencode_logs/ does not exist.
    """
    # Lazy imports — keep otel as an optional dependency
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource, SERVICE_NAME
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry._logs import set_logger_provider
        from opentelemetry.sdk._logs import LoggerProvider
        from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
        from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
        from opentelemetry.sdk._logs import LogRecord
        from opentelemetry.trace import NonRecordingSpan, SpanContext, TraceFlags
    except ImportError as exc:
        raise ImportError(
            "OpenTelemetry packages are required for `dlab trace`.\n"
            "Install them with:  pip install 'dlab[otel]'\n"
            f"Missing: {exc.name}"
        ) from exc

    work_dir = Path(work_dir).resolve()
    logs_dir = work_dir / "_opencode_logs"
    if not logs_dir.exists():
        raise FileNotFoundError(f"No _opencode_logs directory found in {work_dir}")

    # --- Build session graph ---
    graph: SessionNode | None = build_session_graph(logs_dir)
    if graph is None:
        raise ValueError(f"Could not parse session graph from {logs_dir}")

    # --- OTEL resource ---
    resource = Resource(attributes={SERVICE_NAME: service_name})

    # --- Tracer provider ---
    tracer_provider = TracerProvider(resource=resource)
    span_exporter = OTLPSpanExporter(endpoint=f"{otlp_endpoint}/v1/traces")
    tracer_provider.add_span_processor(BatchSpanProcessor(span_exporter))
    tracer = tracer_provider.get_tracer("dlab.otel_exporter")

    # --- Logger provider ---
    logger_provider = LoggerProvider(resource=resource)
    log_exporter = OTLPLogExporter(endpoint=f"{otlp_endpoint}/v1/logs")
    logger_provider.add_log_record_processor(BatchLogRecordProcessor(log_exporter))
    set_logger_provider(logger_provider)
    otel_logger = logger_provider.get_logger("dlab.otel_exporter")

    # --- Root span: session ---
    main_events: list[LogEvent] = graph.events
    dlab_end = _get_dlab_end(main_events)
    session_start_ns = _session_start_ns(main_events)
    session_end_ns = _session_end_ns(main_events)
    outcome = (dlab_end or {}).get("outcome", "unknown")

    root_attrs: dict[str, Any] = {
        "gen_ai.system": "opencode",
        "dlab.session.work_dir": str(work_dir),
        "dlab.session.outcome": outcome,
    }
    if graph.model:
        root_attrs["gen_ai.request.model"] = graph.model

    with tracer.start_as_current_span(
        f"session:{work_dir.name}",
        start_time=session_start_ns,
        attributes=root_attrs,
    ) as root_span:
        root_span.set_status(
            trace.StatusCode.OK if outcome == "success" else trace.StatusCode.ERROR
        )

        # Emit log records for main events
        _emit_log_records(otel_logger, main_events, root_span)

        # --- Child spans: one per agent node ---
        _export_node(tracer, otel_logger, graph, root_span)

        # Force end time on root span
        root_span.end(end_time=session_end_ns)

    # Flush all pending data
    tracer_provider.force_flush()
    logger_provider.force_flush()
    tracer_provider.shutdown()
    logger_provider.shutdown()


# ---------------------------------------------------------------------------
# Node recursion
# ---------------------------------------------------------------------------

def _export_node(
    tracer: Any,
    otel_logger: Any,
    node: SessionNode,
    parent_span: Any,
) -> None:
    """Recursively emit spans for a SessionNode and its children."""
    from opentelemetry import trace
    from opentelemetry import context as otel_context
    from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

    events = node.events
    start_ns = _session_start_ns(events)
    end_ns = _session_end_ns(events)

    agent_attrs: dict[str, Any] = {
        "gen_ai.system": "opencode",
        "gen_ai.agent.name": node.agent_name or node.name,
        "dlab.agent.is_consolidator": node.is_consolidator,
        "dlab.agent.log": node.log_path,
    }
    if node.model:
        agent_attrs["gen_ai.request.model"] = node.model

    span_name = f"agent:{node.agent_name or node.name}"

    # Use parent span context to build child span
    ctx = trace.set_span_in_context(parent_span)
    with tracer.start_as_current_span(
        span_name,
        context=ctx,
        start_time=start_ns,
        attributes=agent_attrs,
    ) as agent_span:
        # Emit tool spans
        _emit_tool_spans(tracer, otel_logger, events, agent_span)

        # Emit log records for this agent
        _emit_log_records(otel_logger, events, agent_span)

        # Recurse into children
        for child in node.children:
            _export_node(tracer, otel_logger, child, agent_span)

        agent_span.end(end_time=end_ns)


# ---------------------------------------------------------------------------
# Tool spans
# ---------------------------------------------------------------------------

def _emit_tool_spans(
    tracer: Any,
    otel_logger: Any,
    events: list[LogEvent],
    parent_span: Any,
) -> None:
    """Emit one child span per tool call (matched by callID)."""
    from opentelemetry import trace

    # Group tool_use events by callID
    by_call: dict[str, list[LogEvent]] = {}
    for ev in events:
        if ev.event_type == "tool_use":
            call_id = ev.part.get("callID") or ev.raw.get("callID") or "unknown"
            by_call.setdefault(call_id, []).append(ev)

    for call_id, call_events in by_call.items():
        tool_name = call_events[0].part.get("tool") or "unknown"
        start_ns = _ms_to_ns(call_events[0].timestamp)
        end_ns = _ms_to_ns(call_events[-1].timestamp)
        if end_ns <= start_ns:
            end_ns = start_ns + 1  # ensure non-zero duration

        ctx = trace.set_span_in_context(parent_span)
        with tracer.start_as_current_span(
            f"tool:{tool_name}",
            context=ctx,
            start_time=start_ns,
            attributes={
                "gen_ai.tool.name": tool_name,
                "gen_ai.tool.call_id": call_id,
                "dlab.tool.state": call_events[-1].part.get("state", "unknown"),
            },
        ) as tool_span:
            tool_span.end(end_time=end_ns)


# ---------------------------------------------------------------------------
# Log records
# ---------------------------------------------------------------------------

_SEVERITY_MAP = {
    "text": 9,        # INFO
    "reasoning": 9,   # INFO
    "tool_use": 9,    # INFO
    "step_start": 9,  # INFO
    "step_finish": 9, # INFO
    "error": 17,      # ERROR
    "raw_text": 5,    # DEBUG
    "additional_output": 5,  # DEBUG
    "dlab_start": 9,  # INFO
    "dlab_end": 9,    # INFO
}


def _emit_log_records(
    otel_logger: Any,
    events: list[LogEvent],
    span: Any,
) -> None:
    """Emit one OTEL log record per LogEvent, attached to span context."""
    from opentelemetry import trace
    from opentelemetry.sdk._logs import LogRecord
    from opentelemetry._logs.severity import SeverityNumber

    span_ctx = span.get_span_context()

    for ev in events:
        if ev.timestamp is None:
            continue  # skip raw_text without timestamps

        body = ev.part.get("text") or ev.part.get("tool") or ev.event_type
        severity = _SEVERITY_MAP.get(ev.event_type, 9)

        attrs: dict[str, Any] = {
            "dlab.event.type": ev.event_type,
            "gen_ai.system": "opencode",
        }
        if ev.session_id:
            attrs["session.id"] = ev.session_id

        record = LogRecord(
            timestamp=_ms_to_ns(ev.timestamp),
            observed_timestamp=_ms_to_ns(ev.timestamp),
            trace_id=span_ctx.trace_id,
            span_id=span_ctx.span_id,
            trace_flags=span_ctx.trace_flags,
            severity_number=SeverityNumber(severity),
            severity_text=SeverityNumber(severity).name,
            body=str(body),
            attributes=attrs,
            resource=otel_logger._instrumentation_scope if hasattr(otel_logger, "_instrumentation_scope") else None,
        )
        otel_logger.emit(record)
