"""
OpenTelemetry export of dlab sessions, opt-in through the environment.

Nothing here runs unless ``OTEL_EXPORTER_OTLP_ENDPOINT`` is set: with it
unset, no OpenTelemetry package is imported and ``dlab run`` behaves as it
always has, so tests and laptops never need a collector. With it set, a
session exports itself when it ends, and with ``DLAB_OTEL_FOLLOW=1`` it
streams while it runs.

The source of truth is what opencode already writes: the NDJSON event stream
dlab tees into ``_opencode_logs/`` (one file per agent process, bracketed by
dlab's own ``dlab_start`` and ``dlab_end`` records). This module turns that
stream into spans, log records and metrics and pushes them over OTLP/HTTP.
It never instruments the agent process itself. Recent opencode releases
(1.17 and later; the mmm pack still pins 1.2.10, which predates it) export
their own traces over OTLP when the same ``OTEL_*`` variables reach them;
those traces stay separate and join this one on ``dlab.session.id``. The log
stream carries everything the spans here need either way.

Span tree
---------
    session                    one per dlab run; ends with the outcome
    └── agent:<name>           one per log file (main, modeler/instance-N,
                               modeler/run2/instance-N, consolidator)
        └── step               one per LLM turn (step_start .. step_finish),
            └── tool:<name>    carrying tokens and cost
                               one per tool call (tool_use), under its step

Spans carry the OpenTelemetry GenAI attributes (``gen_ai.*``) so any backend
that knows them, OpenLIT, Cloud Trace, Grafana, renders model, agent, tool,
tokens and cost without custom configuration. Error and stderr events are
also emitted as OTLP log records (prompt, agent text, reasoning and tool
output too when ``DLAB_OTEL_PROMPTS=1``), and tokens and cost
feed two counters, so a "cost so far" panel works from metrics while spans
are still open.

Follow mode
-----------
OTLP has no partial spans: a span is exported when it ends. Follow mode
therefore keeps the session and agent spans open in memory (their ids are
fixed from the start, so children attach correctly) and exports steps and
tools as soon as they finish, plus log records and metrics as they happen.
Mid-session, a backend shows every completed step and the running cost; the
root arrives when the run ends.

Environment
-----------
OTEL_EXPORTER_OTLP_ENDPOINT   OTLP/HTTP base URL (e.g. http://localhost:4318).
                              Unset = telemetry off.
OTEL_SERVICE_NAME             service.name (default "dlab").
DLAB_OTEL_FOLLOW              "1"/"true" = stream during the run.
DLAB_OTEL_INTERVAL            seconds between polls in follow mode (default 15).
DLAB_OTEL_PROMPTS             "1" = include prompt, agent text and tool output in
                              log records (off by default: they may hold data).
TRACEPARENT                   W3C context of whatever launched dlab (a
                              Metaflow step, for example); recorded as a span
                              link on the session root, which stays a root.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote

from dlab.opencode_logparser import LogEvent, is_log_complete, parse_line

# The OpenTelemetry packages are the optional `otel` extra. Importing them at
# the top keeps the repo's import rule; the guard keeps `dlab run` working
# without them, and SessionTelemetry raises a clear ImportError when used.
try:
    from opentelemetry import context as otel_context
    from opentelemetry import metrics as otel_metrics
    from opentelemetry import trace as otel_trace
    from opentelemetry._logs import LogRecord, SeverityNumber
    from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
    from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk._logs import LoggerProvider
    from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.sdk.trace.id_generator import IdGenerator, RandomIdGenerator
    from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

    OTEL_IMPORT_ERROR: ImportError | None = None
except ImportError as _e:  # pragma: no cover - exercised when the extra is absent
    OTEL_IMPORT_ERROR = _e

logger = logging.getLogger(__name__)

_NS_PER_MS = 1_000_000
_BODY_LIMIT = 4_000  # characters kept from a text/tool body in a log record
GEN_AI_SYSTEM = "opencode"


# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------


def otlp_endpoint() -> str | None:
    """The OTLP/HTTP base URL to export to, or None when telemetry is off."""
    value = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip().rstrip("/")
    return value or None


def is_enabled() -> bool:
    """Whether a session should export at all."""
    return otlp_endpoint() is not None


def follow_enabled() -> bool:
    """Whether to stream during the run rather than export once at the end."""
    return os.environ.get("DLAB_OTEL_FOLLOW", "").strip().lower() in ("1", "true", "yes")


def follow_interval() -> float:
    """Seconds between polls in follow mode."""
    try:
        return max(1.0, float(os.environ.get("DLAB_OTEL_INTERVAL", "15")))
    except ValueError:
        return 15.0


def include_prompts() -> bool:
    """Whether prompt text and tool output go into log records."""
    return os.environ.get("DLAB_OTEL_PROMPTS", "").strip().lower() in ("1", "true", "yes")


def service_name() -> str:
    return os.environ.get("OTEL_SERVICE_NAME", "dlab")


SESSION_ID_FILE = ".dlab_session_id"


def session_id(work_dir: str | Path) -> str:
    """The id every span of this session carries as ``dlab.session.id``.

    ``DLAB_SESSION_ID`` when set (an Argo workflow sets it to the workflow
    name), otherwise a random id minted once per work dir and kept in
    ``.dlab_session_id`` there, so a re-export of the same work dir lands in
    the same trace. The work-dir NAME is not used: dlab numbers work dirs
    ``dlab-<pack>-workdir-001`` and up, so everyone's first run of a pack
    would share one trace on a shared collector. When the work dir does not
    exist yet the id is random and not persisted.
    """
    forced = os.environ.get("DLAB_SESSION_ID", "").strip()
    if forced:
        return forced
    path = Path(work_dir) / SESSION_ID_FILE
    try:
        existing = path.read_text(encoding="utf-8").strip()
        if existing:
            return existing
    except OSError:
        pass
    return new_session_id(work_dir)


def new_session_id(work_dir: str | Path) -> str:
    """Mint a fresh session id for ``work_dir`` and persist it when possible.

    Called when a session is continued (``--continue-dir``): the continued
    run is a new session with its own trace, not more spans on the old one.
    With ``DLAB_SESSION_ID`` set the variable would still win, so it is
    re-pointed at ``<id>-c<8 hex>`` in this process's environment, which the
    agent processes inherit.
    """
    fresh = uuid.uuid4().hex
    forced = os.environ.get("DLAB_SESSION_ID", "").strip()
    if forced:
        base = forced.split("-c", 1)[0] if "-c" in forced else forced
        fresh = f"{base}-c{fresh[:8]}"
        os.environ["DLAB_SESSION_ID"] = fresh
    path = Path(work_dir) / SESSION_ID_FILE
    try:
        if path.parent.is_dir():
            path.write_text(fresh + "\n", encoding="utf-8")
    except OSError:
        logger.debug("could not persist session id", exc_info=True)
    return fresh


def parse_resource_attributes(value: str) -> dict[str, str]:
    """Parse ``OTEL_RESOURCE_ATTRIBUTES`` the way the SDKs and opencode do.

    Comma-separated ``key=value`` entries, value percent-decoded. Malformed
    entries are dropped one by one here; opencode drops the WHOLE variable
    on the first bad entry, which is why :func:`resource_env` always
    re-serialises a clean string.
    """
    attrs: dict[str, str] = {}
    for entry in value.split(","):
        key, sep, raw = entry.partition("=")
        key = key.strip()
        if not sep or not key:
            continue
        attrs[key] = unquote(raw.strip())
    return attrs


def format_resource_attributes(attrs: dict[str, str]) -> str:
    """Serialise for ``OTEL_RESOURCE_ATTRIBUTES``; values percent-encoded."""
    return ",".join(f"{k}={quote(str(v), safe='')}" for k, v in attrs.items())


def resource_env(
    env: dict[str, str],
    *,
    session_id: str,
    dpack: str,
    role: str = "orchestrator",
) -> dict[str, str]:
    """Return ``env`` with the session's resource attributes merged in.

    Adds ``pymc.workload=dlab``, ``dlab.session.id``, ``dlab.dpack`` and
    ``dlab.role`` to ``OTEL_RESOURCE_ATTRIBUTES`` only where the key is
    absent: keys the platform already set (an Argo template, a launcher)
    win. Also pins ``DLAB_SESSION_ID`` so parallel instances, which inherit
    the variable through the instance allowlist, agree on the id. Untouched
    when no OTLP endpoint is set.
    """
    if not env.get("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip():
        return env
    attrs = parse_resource_attributes(env.get("OTEL_RESOURCE_ATTRIBUTES", ""))
    for key, value in (
        ("pymc.workload", "dlab"),
        ("dlab.session.id", session_id),
        ("dlab.dpack", dpack),
        ("dlab.role", role),
    ):
        attrs.setdefault(key, value)
    out = dict(env)
    out["OTEL_RESOURCE_ATTRIBUTES"] = format_resource_attributes(attrs)
    out.setdefault("DLAB_SESSION_ID", session_id)
    return out


def session_trace_ids(session_id: str) -> tuple[int, int]:
    """Deterministic (trace id, root span id) for a session id.

    The first 16 bytes of ``sha256(session_id)`` are the trace id and the
    next 8 the root span id, so follow-mode spans, the final root span and a
    later re-export of the same work dir all land in ONE trace without any
    state passed around. That holds with ``TRACEPARENT`` set too: the parent
    becomes a span link, never the trace id. opencode's own traces stay
    separate (it ignores TRACEPARENT) and join on ``dlab.session.id``.
    """
    digest = hashlib.sha256(session_id.encode("utf-8")).digest()
    trace_id = int.from_bytes(digest[:16], "big") or 1
    span_id = int.from_bytes(digest[16:24], "big") or 1
    return trace_id, span_id


# ---------------------------------------------------------------------------
# Log-file tailing
# ---------------------------------------------------------------------------


@dataclass
class _FileCursor:
    """Read position in one log file, tolerant of a truncated last line."""

    path: Path
    position: int = 0
    inode: int = 0
    pending: bytes = b""  # a partial trailing line, kept until its newline arrives

    def read_new_lines(self) -> list[str]:
        try:
            st = self.path.stat()
        except FileNotFoundError:
            return []
        if st.st_ino != self.inode or st.st_size < self.position:
            # Replaced (temp + rename) or truncated: start over.
            self.position = 0
            self.pending = b""
            self.inode = st.st_ino
        if st.st_size == self.position:
            return []
        # Bytes, decoded per complete line: a multibyte character split by
        # the poll boundary would be mangled by text-mode reads.
        with open(self.path, "rb") as f:
            f.seek(self.position)
            chunk = f.read()
            self.position = f.tell()
        data = self.pending + chunk
        lines = data.split(b"\n")
        # Without a trailing newline the last element is an incomplete line.
        self.pending = lines.pop() if not data.endswith(b"\n") else b""
        if data.endswith(b"\n"):
            lines.pop()  # the empty string after the final newline
        return [line.decode("utf-8", errors="replace") for line in lines]


# ---------------------------------------------------------------------------
# The exporter
# ---------------------------------------------------------------------------


@dataclass
class _AgentState:
    """Open spans and counters for one log file (one agent process)."""

    name: str
    span: Any
    model: str | None = None
    last_ts_ns: int = 0
    open_steps: dict[str, Any] = field(default_factory=dict)  # messageID -> span
    open_tools: dict[str, Any] = field(default_factory=dict)  # callID -> span
    events: list[LogEvent] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    cost: float = 0.0


class _SessionIdGenerator(IdGenerator if OTEL_IMPORT_ERROR is None else object):  # type: ignore[misc]
    """Fixed trace id for the session; fixed id for the first (root) span."""

    def __init__(self, session: str) -> None:
        self._trace_id, self._root_span_id = session_trace_ids(session)
        self._random = RandomIdGenerator()
        self._root_used = False

    def generate_trace_id(self) -> int:
        return self._trace_id

    def generate_span_id(self) -> int:
        if not self._root_used:
            self._root_used = True
            return self._root_span_id
        return self._random.generate_span_id()


class SessionTelemetry:
    """
    Turn a dlab session's log stream into OTLP traces, logs and metrics.

    One instance per session. Either drive it incrementally (``start()`` ..
    ``finish()``) while the session runs, or call :func:`export_session` on a
    finished work directory.

    Parameters
    ----------
    work_dir : str | Path
        The session work directory (holds ``_opencode_logs/``).
    endpoint : str | None
        OTLP/HTTP base URL. None means "use the injected exporters" (tests).
    service : str
        ``service.name`` resource attribute.
    attributes : dict, optional
        Extra resource attributes (``dlab.dpack``, ``dlab.model``).
    span_exporter, log_exporter, metric_reader
        Injection points for tests; when given, no OTLP exporter is built.
    """

    def __init__(
        self,
        work_dir: str | Path,
        endpoint: str | None,
        service: str = "dlab",
        attributes: dict[str, str] | None = None,
        *,
        run_started_ms: int | None = None,
        span_exporter: Any = None,
        log_exporter: Any = None,
        metric_reader: Any = None,
    ) -> None:
        if OTEL_IMPORT_ERROR is not None:
            raise ImportError(
                "OpenTelemetry is not installed; install the extra: pip install 'dlab-cli[otel]'"
            ) from OTEL_IMPORT_ERROR

        self.work_dir = Path(work_dir)
        self.logs_dir = self.work_dir / "_opencode_logs"
        self._include_bodies = include_prompts()
        # When the CLI passes the moment it started this run, logs older than
        # that are never read, even before the agent rewrote main.log (Docker
        # startup can outlast the first follow-mode poll).
        self._run_started_ms = run_started_ms

        if endpoint is not None:
            span_exporter = OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces")
            log_exporter = OTLPLogExporter(endpoint=f"{endpoint}/v1/logs")
            metric_reader = PeriodicExportingMetricReader(
                OTLPMetricExporter(endpoint=f"{endpoint}/v1/metrics"),
                export_interval_millis=int(follow_interval() * 1000),
            )

        self.session_id = session_id(self.work_dir)
        resource = Resource.create(
            {
                "service.name": service,
                "dlab.work_dir": str(self.work_dir),
                "pymc.workload": "dlab",
                "dlab.session.id": self.session_id,
                "dlab.role": "orchestrator",
                **(attributes or {}),
            }
        )
        # Providers are per instance, never global: a test or a host process
        # that already has its own tracer keeps it.
        self._tracer_provider = TracerProvider(
            resource=resource, id_generator=_SessionIdGenerator(self.session_id)
        )
        self._tracer_provider.add_span_processor(BatchSpanProcessor(span_exporter))
        self._tracer = self._tracer_provider.get_tracer("dlab.telemetry")

        self._logger_provider = LoggerProvider(resource=resource)
        self._logger_provider.add_log_record_processor(BatchLogRecordProcessor(log_exporter))
        self._otel_logger = self._logger_provider.get_logger("dlab.telemetry")

        self._meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
        meter = self._meter_provider.get_meter("dlab.telemetry")
        self._token_counter = meter.create_counter(
            "gen_ai.client.token.usage", unit="{token}", description="Tokens by type"
        )
        self._cost_counter = meter.create_counter(
            "dlab.cost.usd", unit="USD", description="LLM cost accumulated by dlab sessions"
        )

        # TRACEPARENT (W3C) from a launcher becomes a LINK on the session span,
        # not its parent: a parent would replace the deterministic trace id,
        # and a re-export without the variable would then land elsewhere.
        self._parent_links: list[Any] = []
        carrier = {k.lower(): v for k, v in os.environ.items() if k.lower() in ("traceparent", "tracestate")}
        if carrier:
            parent = otel_trace.get_current_span(TraceContextTextMapPropagator().extract(carrier))
            if parent.get_span_context().is_valid:
                self._parent_links.append(otel_trace.Link(parent.get_span_context()))

        self._trace = otel_trace
        self._metrics = otel_metrics
        self._session_span: Any = None
        self._agents: dict[Path, _AgentState] = {}
        self._cursors: dict[Path, _FileCursor] = {}
        self._parallel_runs: dict[str, list[str]] = {}  # agent -> run timestamps seen, in order
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._finished = False

    # -- lifecycle ---------------------------------------------------------

    def start(self, interval: float | None = None) -> None:
        """Open the session span and poll the logs in a background thread."""
        self._ensure_session_span()
        interval = follow_interval() if interval is None else interval

        def _loop() -> None:
            while not self._stop.wait(interval):
                try:
                    self.poll()
                except Exception:  # noqa: BLE001 - telemetry must never break a run
                    logger.exception("telemetry poll failed")

        self._thread = threading.Thread(target=_loop, name="dlab-telemetry", daemon=True)
        self._thread.start()

    def poll(self) -> int:
        """Ingest whatever the logs gained since the last call. Returns events seen."""
        with self._lock:
            self._ensure_session_span()
            n = 0
            for path in self._log_paths():
                cursor = self._cursors.setdefault(path, _FileCursor(path))
                for line in cursor.read_new_lines():
                    event = parse_line(line)
                    if event is None:
                        continue
                    self._ingest(path, event)
                    n += 1
            return n

    def finish(self, outcome: str | None = None, exit_code: int | None = None) -> None:
        """Final poll, close everything, flush, shut the providers down."""
        if self._finished:
            return
        self._finished = True
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=30)
        with self._lock:
            self._ensure_session_span()
            # Whatever arrived after the last poll.
            for path in self._log_paths():
                cursor = self._cursors.setdefault(path, _FileCursor(path))
                for line in cursor.read_new_lines():
                    event = parse_line(line)
                    if event is not None:
                        self._ingest(path, event)
            end_ns = self._latest_ts_ns() or time.time_ns()
            for state in self._agents.values():
                self._close_agent(state, end_ns)
            if outcome is None:
                outcome = self._derive_outcome()
            self._session_span.set_attribute("dlab.session.outcome", outcome)
            if exit_code is not None:
                self._session_span.set_attribute("dlab.session.exit_code", int(exit_code))
            totals = self._totals()
            for k, v in totals.items():
                self._session_span.set_attribute(k, v)
            if outcome not in ("success", "unknown"):
                self._session_span.set_status(self._trace.StatusCode.ERROR, outcome)
            self._session_span.end(end_time=end_ns)
        self._tracer_provider.force_flush()
        self._logger_provider.force_flush()
        self._meter_provider.force_flush()
        self._tracer_provider.shutdown()
        self._logger_provider.shutdown()
        self._meter_provider.shutdown()

    def _log_paths(self) -> list[Path]:
        """Every log file of THIS run, sorted.

        A continued work dir (``--continue-dir``) keeps the parallel-run
        folders of earlier runs while ``main.log`` starts over, so instance
        logs that predate this run's ``dlab_start`` are skipped: re-reading
        them would duplicate their spans and count their cost again.
        """
        if not self.logs_dir.exists():
            return []
        start_ms = self._run_started_ms or self._run_start_ms()
        paths = []
        for path in sorted(self.logs_dir.rglob("*.log")):
            if start_ms and path.parent != self.logs_dir:
                run_ms = _parallel_run_ms(path.parent.name)
                if run_ms is not None and run_ms < start_ms:
                    continue
            elif self._run_started_ms and path.parent == self.logs_dir:
                first = _first_event_ms(path)
                if first is not None and first < self._run_started_ms:
                    continue  # the previous run's log, not rewritten yet
            paths.append(path)
        return paths

    def _run_start_ms(self) -> int | None:
        """Timestamp of this run's ``dlab_start`` in main.log, if there is one."""
        main = self.logs_dir / "main.log"
        try:
            with open(main, "rb") as f:
                first = f.readline().decode("utf-8", errors="replace")
        except OSError:
            return None
        ev = parse_line(first)
        if ev is not None and ev.event_type == "dlab_start" and ev.timestamp:
            return int(ev.timestamp)
        return None

    # -- span construction ---------------------------------------------------

    def _ensure_session_span(self) -> None:
        if self._session_span is not None:
            return
        if self._run_started_ms:
            start_ns = self._run_started_ms * _NS_PER_MS
        else:
            start_ns = self._first_ts_ns() or time.time_ns()
        self._session_span = self._tracer.start_span(
            "session",
            context=otel_context.Context(),  # a root: never the host process's span
            links=self._parent_links,
            start_time=start_ns,
            attributes={
                "gen_ai.system": GEN_AI_SYSTEM,
                "gen_ai.operation.name": "invoke_agent",
                "dlab.session.name": self.work_dir.name,
                "dlab.session.id": self.session_id,
            },
        )

    def _agent_for(self, path: Path, event: LogEvent) -> _AgentState:
        state = self._agents.get(path)
        if state is not None:
            return state
        name = path.stem
        if path.parent != self.logs_dir:
            # instance-1 under modeler-parallel-run-<ts>/ -> "modeler/instance-1";
            # a second parallel run of the same agent -> "modeler/run2/instance-1".
            agent, _, stamp = path.parent.name.partition("-parallel-run-")
            runs = self._parallel_runs.setdefault(agent, [])
            if stamp not in runs:
                runs.append(stamp)
            ordinal = runs.index(stamp) + 1
            name = f"{agent}/{path.stem}" if ordinal == 1 else f"{agent}/run{ordinal}/{path.stem}"
        start_ns = _ts_ns(event) or time.time_ns()
        ctx = self._trace.set_span_in_context(self._session_span)
        span = self._tracer.start_span(
            f"agent:{name}",
            context=ctx,
            start_time=start_ns,
            attributes={
                "gen_ai.system": GEN_AI_SYSTEM,
                "gen_ai.operation.name": "invoke_agent",
                "gen_ai.agent.name": name,
                "dlab.log_file": str(path.relative_to(self.logs_dir)),
            },
        )
        state = _AgentState(name=name, span=span, last_ts_ns=start_ns)
        self._agents[path] = state
        return state

    def _ingest(self, path: Path, event: LogEvent) -> None:
        state = self._agent_for(path, event)
        state.events.append(event)
        ts = _ts_ns(event)
        if ts:
            state.last_ts_ns = max(state.last_ts_ns, ts)
        kind = event.event_type

        if kind == "dlab_start":
            model = event.raw.get("model") or event.part.get("model")
            agent = event.raw.get("agent")
            if model:
                state.model = model
                state.span.set_attribute("gen_ai.request.model", model)
                if self._session_span.is_recording() and "main" in state.name:
                    self._session_span.set_attribute("gen_ai.request.model", model)
            if agent:
                state.span.set_attribute("dlab.agent", agent)
            if self._include_bodies and event.raw.get("prompt"):
                self._log(state, event, "dlab_start", str(event.raw["prompt"]), "INFO")

        elif kind == "step_start":
            msg = event.part.get("messageID") or event.session_id
            ctx = self._trace.set_span_in_context(state.span)
            state.open_steps[msg] = self._tracer.start_span(
                "step",
                context=ctx,
                start_time=ts or state.last_ts_ns,
                attributes={"gen_ai.system": GEN_AI_SYSTEM, "gen_ai.operation.name": "chat"},
            )

        elif kind == "step_finish":
            msg = event.part.get("messageID") or event.session_id
            span = state.open_steps.pop(msg, None)
            if span is None:
                ctx = self._trace.set_span_in_context(state.span)
                span = self._tracer.start_span(
                    "step",
                    context=ctx,
                    start_time=ts or state.last_ts_ns,
                    attributes={"gen_ai.system": GEN_AI_SYSTEM, "gen_ai.operation.name": "chat"},
                )
            attrs = _usage_attributes(event)
            for k, v in attrs.items():
                span.set_attribute(k, v)
            if state.model:
                span.set_attribute("gen_ai.request.model", state.model)
            reason = event.part.get("reason")
            if reason:
                span.set_attribute("gen_ai.response.finish_reasons", [reason])
            span.end(end_time=ts or state.last_ts_ns)
            self._record_usage(state, attrs)

        elif kind == "tool_use":
            self._ingest_tool(state, event, ts)

        elif kind == "text":
            # Agent output is where a client's numbers end up: same switch as prompts.
            body = event.part.get("text") or ""
            if body and self._include_bodies:
                self._log(state, event, "text", body, "INFO")

        elif kind == "reasoning":
            body = event.part.get("text") or ""
            if body and self._include_bodies:
                self._log(state, event, "reasoning", body, "DEBUG")

        elif kind == "error":
            body = str(event.part.get("error") or event.part.get("message") or event.raw)
            self._log(state, event, "error", body, "ERROR")
            state.span.set_status(self._trace.StatusCode.ERROR, body[:200])

        elif kind == "dlab_end":
            outcome = event.raw.get("outcome")
            if outcome:
                state.span.set_attribute("dlab.session.outcome", outcome)

        elif kind == "raw_text":
            body = event.part.get("text") or ""
            if body.startswith("[STDERR]"):
                self._log(state, event, "stderr", body, "WARN")

    def _ingest_tool(self, state: _AgentState, event: LogEvent, ts: int | None) -> None:
        part = event.part
        call_id = part.get("callID") or f"anon-{len(state.open_tools)}"
        tool = part.get("tool") or "tool"
        st = part.get("state") or {}
        status = st.get("status")
        times = st.get("time") or {}
        start_ns = (times.get("start") or 0) * _NS_PER_MS or ts or state.last_ts_ns
        end_ns = (times.get("end") or 0) * _NS_PER_MS or ts or state.last_ts_ns

        span = state.open_tools.get(call_id)
        if span is None:
            # Parent: the open step if there is one, else the agent.
            parent = next(reversed(state.open_steps.values()), None) or state.span
            ctx = self._trace.set_span_in_context(parent)
            span = self._tracer.start_span(
                f"tool:{tool}",
                context=ctx,
                start_time=start_ns,
                attributes={
                    "gen_ai.system": GEN_AI_SYSTEM,
                    "gen_ai.operation.name": "execute_tool",
                    "gen_ai.tool.name": tool,
                    "gen_ai.tool.call_id": call_id,
                },
            )
            state.open_tools[call_id] = span

        if status in ("completed", "error"):
            span.set_attribute("dlab.tool.status", status)
            if status == "error":
                err = str(st.get("error") or "")
                span.set_status(self._trace.StatusCode.ERROR, err[:200])
                self._log(state, event, f"tool:{tool}", err or "tool error", "ERROR")
            elif self._include_bodies and st.get("output"):
                self._log(state, event, f"tool:{tool}", str(st["output"]), "INFO")
            span.end(end_time=end_ns)
            state.open_tools.pop(call_id, None)

    def _close_agent(self, state: _AgentState, end_ns: int) -> None:
        end = state.last_ts_ns or end_ns
        for span in list(state.open_tools.values()):
            span.set_attribute("dlab.tool.status", "unfinished")
            span.end(end_time=end)
        state.open_tools.clear()
        for span in list(state.open_steps.values()):
            span.end(end_time=end)
        state.open_steps.clear()
        state.span.set_attribute("gen_ai.usage.input_tokens", state.input_tokens)
        state.span.set_attribute("gen_ai.usage.output_tokens", state.output_tokens)
        state.span.set_attribute("gen_ai.usage.cost", round(state.cost, 6))
        state.span.set_attribute("dlab.agent.complete", is_log_complete(state.events))
        state.span.end(end_time=end)

    # -- signals -------------------------------------------------------------

    def _log(self, state: _AgentState, event: LogEvent, kind: str, body: str, severity: str) -> None:
        # The API-level LogRecord is what Logger.emit takes across SDK
        # versions; the SDK's own class moved in 1.4x.
        sev = {
            "DEBUG": SeverityNumber.DEBUG,
            "INFO": SeverityNumber.INFO,
            "WARN": SeverityNumber.WARN,
            "ERROR": SeverityNumber.ERROR,
        }[severity]
        span_ctx = state.span.get_span_context()
        ts = _ts_ns(event) or state.last_ts_ns or time.time_ns()
        record = LogRecord(
            timestamp=ts,
            observed_timestamp=time.time_ns(),
            trace_id=span_ctx.trace_id,
            span_id=span_ctx.span_id,
            trace_flags=span_ctx.trace_flags,
            severity_text=severity,
            severity_number=sev,
            body=body[:_BODY_LIMIT],
            attributes={
                "gen_ai.system": GEN_AI_SYSTEM,
                "gen_ai.agent.name": state.name,
                "dlab.event.type": kind,
            },
        )
        self._otel_logger.emit(record)

    def _record_usage(self, state: _AgentState, attrs: dict[str, Any]) -> None:
        labels = {"gen_ai.system": GEN_AI_SYSTEM, "gen_ai.agent.name": state.name}
        if state.model:
            labels["gen_ai.request.model"] = state.model
        for key, kind in (
            ("gen_ai.usage.input_tokens", "input"),
            ("gen_ai.usage.output_tokens", "output"),
            ("dlab.usage.reasoning_tokens", "reasoning"),
            ("dlab.usage.cache_read_tokens", "cache_read"),
            ("dlab.usage.cache_write_tokens", "cache_write"),
        ):
            n = attrs.get(key, 0)
            if n:
                self._token_counter.add(n, {**labels, "gen_ai.token.type": kind})
        cost = attrs.get("gen_ai.usage.cost", 0.0)
        if cost:
            self._cost_counter.add(cost, labels)
        state.input_tokens += attrs.get("gen_ai.usage.input_tokens", 0)
        state.output_tokens += attrs.get("gen_ai.usage.output_tokens", 0)
        state.cost += cost

    # -- helpers ---------------------------------------------------------------

    def _totals(self) -> dict[str, Any]:
        return {
            "gen_ai.usage.input_tokens": sum(a.input_tokens for a in self._agents.values()),
            "gen_ai.usage.output_tokens": sum(a.output_tokens for a in self._agents.values()),
            "gen_ai.usage.cost": round(sum(a.cost for a in self._agents.values()), 6),
            "dlab.agent.count": len(self._agents),
        }

    def _derive_outcome(self) -> str:
        main = self._agents.get(self.logs_dir / "main.log")
        if main is None:
            return "unknown"
        for ev in reversed(main.events):
            if ev.event_type == "dlab_end":
                return str(ev.raw.get("outcome") or "unknown")
        if any(ev.event_type == "error" for ev in main.events):
            return "error"
        return "success" if is_log_complete(main.events) else "unknown"

    def _first_ts_ns(self) -> int | None:
        main = self.logs_dir / "main.log"
        if not main.exists():
            return None
        try:
            with open(main, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    ev = parse_line(line)
                    if ev is not None and ev.timestamp:
                        return ev.timestamp * _NS_PER_MS
        except OSError:
            return None
        return None

    def _latest_ts_ns(self) -> int:
        return max((a.last_ts_ns for a in self._agents.values()), default=0)


def _ts_ns(event: LogEvent) -> int | None:
    return event.timestamp * _NS_PER_MS if event.timestamp else None


def _first_event_ms(path: Path) -> int | None:
    """Timestamp of the first event in a log file, if any."""
    try:
        with open(path, "rb") as f:
            first = f.readline().decode("utf-8", errors="replace")
    except OSError:
        return None
    ev = parse_line(first)
    return int(ev.timestamp) if ev is not None and ev.timestamp else None


def _parallel_run_ms(dir_name: str) -> int | None:
    """The ``Date.now()`` suffix of a ``<agent>-parallel-run-<ms>`` folder."""
    _, sep, stamp = dir_name.partition("-parallel-run-")
    return int(stamp) if sep and stamp.isdigit() else None


def _usage_attributes(event: LogEvent) -> dict[str, Any]:
    """gen_ai.usage.* from a step_finish event's tokens and cost."""
    tokens = event.part.get("tokens") or {}
    cache = tokens.get("cache") or {}
    attrs: dict[str, Any] = {}
    if tokens.get("input"):
        attrs["gen_ai.usage.input_tokens"] = int(tokens["input"])
    if tokens.get("output"):
        attrs["gen_ai.usage.output_tokens"] = int(tokens["output"])
    if tokens.get("reasoning"):
        attrs["dlab.usage.reasoning_tokens"] = int(tokens["reasoning"])
    if cache.get("read"):
        attrs["dlab.usage.cache_read_tokens"] = int(cache["read"])
    if cache.get("write"):
        attrs["dlab.usage.cache_write_tokens"] = int(cache["write"])
    cost = event.part.get("cost")
    if cost:
        attrs["gen_ai.usage.cost"] = float(cost)
    return attrs


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


def export_session(
    work_dir: str | Path,
    endpoint: str | None = None,
    service: str | None = None,
    outcome: str | None = None,
    exit_code: int | None = None,
    attributes: dict[str, str] | None = None,
) -> dict[str, Any]:
    """
    Export a finished session in one go. Returns the usage totals.

    ``endpoint`` and ``service`` default to the environment. Raises
    ImportError when the ``otel`` extra is missing.
    """
    endpoint = endpoint or otlp_endpoint()
    if endpoint is None:
        raise ValueError("no OTLP endpoint: set OTEL_EXPORTER_OTLP_ENDPOINT or pass endpoint")
    t = SessionTelemetry(work_dir, endpoint, service or service_name(), attributes)
    t.poll()
    totals = t._totals()
    t.finish(outcome=outcome, exit_code=exit_code)
    return totals


def write_end_sentinel(work_dir: str | Path, outcome: str, exit_code: int, interrupted: bool) -> None:
    """Append dlab's ``dlab_end`` record to main.log; never raises."""
    try:
        main_log = Path(work_dir) / "_opencode_logs" / "main.log"
        if not main_log.exists():
            return
        record = {
            "type": "dlab_end",
            "timestamp": int(time.time() * 1000),
            "outcome": outcome,
            "exit_code": exit_code,
            "interrupted": interrupted,
        }
        with open(main_log, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except Exception:  # noqa: BLE001 - never let the sentinel break cleanup
        logger.debug("could not write dlab_end sentinel", exc_info=True)
