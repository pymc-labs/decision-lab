"""
Command-line interface for dlab.
"""

import argparse
import difflib
import os
import shutil
import signal
import stat
import subprocess
import sys
import threading
import time as _time
from pathlib import Path
from typing import Any, Callable

from rich.console import Console
from rich.live import Live
from rich.padding import Padding
from rich.panel import Panel
from rich.spinner import Spinner
from rich.text import Text

from dlab.config import load_dpack_config
from dlab.model_fallback import preflight_check

# Note: Console must be created per-call (not module-level) so pytest capsys
# can capture output. Use _make_console() in command functions.
from dlab.docker import (
    build_image,
    count_dangling_images,
    exec_command,
    needs_rebuild,
    run_opencode,
    start_container,
    stop_container,
)
from dlab.session import copy_hook_scripts, create_session, setup_opencode_config
from dlab.timeline import run_timeline


def _make_console() -> Console:
    """Create a Console that writes to current sys.stdout (for testability)."""
    return Console(highlight=False)


def _run_with_log_spinner(
    console: Console,
    indent: str,
    logs_dir: Path,
    run_fn: Callable[[], tuple[int, str, str]],
) -> tuple[int, str, str]:
    """
    Run a blocking function while showing a spinner with log entry count.

    Monitors all .log files in logs_dir (recursively) in a background
    thread and updates a Rich spinner inline with the total line count.

    Parameters
    ----------
    console : Console
        Rich console for output.
    indent : str
        Indentation prefix for the spinner text.
    logs_dir : Path
        Directory containing log files (searched recursively).
    run_fn : Callable
        Blocking function that returns (exit_code, stdout, stderr).

    Returns
    -------
    tuple[int, str, str]
        (exit_code, stdout, stderr) from run_fn.
    """
    line_count: int = 0
    running: bool = True
    spinner: Spinner = Spinner("dots", style="dim")

    def _count_lines() -> None:
        nonlocal line_count
        while running:
            try:
                total: int = 0
                for log_file in logs_dir.rglob("*.log"):
                    try:
                        total += sum(1 for _ in open(log_file))
                    except (IOError, OSError):
                        pass
                line_count = total
            except (IOError, OSError):
                pass
            _time.sleep(0.5)

    counter = threading.Thread(target=_count_lines, daemon=True)
    counter.start()

    def _make_renderable() -> Text:
        text = Text(indent)
        text.append_text(spinner.render(_time.time()))
        text.append(f" » {line_count} ", style="dim")
        text.append("msgs", style="#555555")
        return text

    with Live(_make_renderable(), console=console, refresh_per_second=10, transient=True) as live:
        def _tick() -> None:
            while running:
                live.update(_make_renderable())
                _time.sleep(0.1)

        ticker = threading.Thread(target=_tick, daemon=True)
        ticker.start()

        result = run_fn()
        running = False

    return result


WRAPPER_TEMPLATE: str = '''#!/usr/bin/env python3
"""
Auto-generated wrapper for {dpack_name}.
Created by: dlab install
"""

import subprocess
import sys

CONFIG_DIR = "{config_dir}"


def main() -> None:
    cmd = ["dlab", "--dpack", CONFIG_DIR] + sys.argv[1:]
    result = subprocess.run(cmd)
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
'''


def create_parser() -> argparse.ArgumentParser:
    """
    Build argument parser with subcommands.

    Returns
    -------
    argparse.ArgumentParser
        Configured argument parser.
    """
    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        prog="dlab",
        description="Run opencode in automated mode, sandboxed with Docker",
    )

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # Run mode (default) - no subcommand needed, uses main parser args
    parser.add_argument(
        "--dpack",
        metavar="PATH",
        help="Path to decision-pack config directory",
    )
    parser.add_argument(
        "--data",
        nargs="+",
        metavar="PATH",
        help="Data files or directory to copy into the workspace",
    )
    parser.add_argument(
        "--model",
        metavar="MODEL",
        help="Model to use (overrides default_model from config)",
    )
    parser.add_argument(
        "--prompt",
        metavar="TEXT",
        help="Prompt text for the agent",
    )
    parser.add_argument(
        "--prompt-file",
        metavar="PATH",
        help="Path to file containing prompt text",
    )
    parser.add_argument(
        "--work-dir",
        metavar="PATH",
        help="Explicit work directory path",
    )
    parser.add_argument(
        "--continue-dir",
        metavar="PATH",
        help="Continue an interrupted session from this work directory",
    )
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="Force rebuild Docker image",
    )
    parser.add_argument(
        "--env-file",
        metavar="PATH",
        help="Path to environment file (passed to Docker container)",
    )
    parser.add_argument(
        "--no-sandboxing",
        action="store_true",
        help="Run opencode locally without Docker (no container isolation)",
    )

    # Install subcommand
    install_parser = subparsers.add_parser(
        "install",
        help="Install a decision-pack as a wrapper script",
    )
    install_parser.add_argument(
        "dpack_path",
        metavar="PATH",
        help="Path to decision-pack config directory",
    )
    install_parser.add_argument(
        "--bin-dir",
        metavar="PATH",
        default=os.path.expanduser("~/.local/bin"),
        help="Directory to install wrapper script (default: ~/.local/bin)",
    )

    # Connect subcommand
    connect_parser = subparsers.add_parser(
        "connect",
        help="Connect to a running or completed session (TUI monitor)",
    )
    connect_parser.add_argument(
        "work_dir",
        metavar="WORK_DIR",
        help="Path to session work directory",
    )
    connect_parser.add_argument(
        "--log",
        action="store_true",
        help="Show rich formatted log output",
    )
    connect_parser.add_argument(
        "--log-json",
        action="store_true",
        help="Show raw JSON log output",
    )

    # Create parallel agent subcommand
    create_pa_parser = subparsers.add_parser(
        "create-parallel-agent",
        help="Interactive wizard to create a parallel agent configuration",
    )
    create_pa_parser.add_argument(
        "dpack",
        metavar="DPACK_DIR",
        nargs="?",
        default=".",
        help="Path to decision-pack config directory (default: current directory)",
    )

    # Timeline subcommand
    timeline_parser = subparsers.add_parser(
        "timeline",
        help="Display execution timeline and Gantt chart for a session",
    )
    timeline_parser.add_argument(
        "work_dir",
        metavar="WORK_DIR",
        nargs="?",
        default=None,
        help="Path to session work directory (default: cwd if it has _opencode_logs)",
    )

    # View subcommand (browser-based session viewer)
    view_parser = subparsers.add_parser(
        "view",
        help="Open browser-based session viewer with DAG visualization",
    )
    view_parser.add_argument(
        "work_dir",
        metavar="WORK_DIR",
        help="Path to session work directory",
    )
    view_parser.add_argument(
        "--port",
        type=int,
        default=0,
        help="Port for the viewer server (default: auto-select)",
    )
    view_parser.add_argument(
        "--no-open",
        action="store_true",
        help="Start server without opening browser",
    )

    # Create decision-pack subcommand
    create_dpack_parser = subparsers.add_parser(
        "create-dpack",
        help="Interactive wizard to create a new decision-pack directory",
    )
    create_dpack_parser.add_argument(
        "output_dir",
        metavar="OUTPUT_DIR",
        nargs="?",
        default=".",
        help="Directory where the decision-pack will be created (default: current directory)",
    )

    return parser


def cmd_run(args: argparse.Namespace) -> int:
    """
    Handle run mode - create session and start agent.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed command-line arguments.

    Returns
    -------
    int
        Exit code (0 for success, non-zero for failure).
    """
    if not args.dpack:
        print("Error: --dpack is required for run mode", file=sys.stderr)
        return 1

    # Load config early so we can check requires_data
    try:
        config: dict[str, Any] = load_dpack_config(args.dpack)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    # Resolve execution mode: Docker vs local
    no_sandboxing: bool = getattr(args, "no_sandboxing", False)
    if not no_sandboxing:
        from dlab.local import is_docker_available
        if not is_docker_available():
            err: Console = Console(stderr=True, highlight=False)
            err.print(
                "Oops, couldn't find a running Docker daemon. "
                "decision-lab attempts to use Docker for sandboxing "
                "and locked environments by default.\n"
            )
            err.print(
                "To run locally without sandboxing, add the "
                "[cyan]--no-sandboxing[/cyan] flag to the command.\n"
            )
            err.print(
                "[yellow]Warning: without sandboxing, decision-lab "
                "will potentially have access to your whole system. "
                "Please be aware of the risk.[/yellow]"
            )
            return 1

    # Auto-default --env-file to decision-pack .env if present
    if not args.env_file:
        dpack_env: Path = Path(args.dpack).resolve() / ".env"
        if dpack_env.exists():
            args.env_file = str(dpack_env)

    env_file_missing: bool = not args.env_file

    # Check for continue mode vs new session mode
    continue_mode: bool = bool(args.continue_dir)
    requires_data: bool = config.get("requires_data", True)
    requires_prompt: bool = config.get("requires_prompt", True)

    if continue_mode:
        if args.data:
            print("Error: Cannot use --data with --continue-dir", file=sys.stderr)
            return 1
    else:
        if requires_data and not args.data:
            print("Error: --data is required (or use --continue-dir to resume)", file=sys.stderr)
            return 1
        if args.data:
            for data_path in args.data:
                if not Path(data_path).exists():
                    print(f"Error: Data path does not exist: {data_path}", file=sys.stderr)
                    return 1

    if requires_prompt and not args.prompt and not args.prompt_file:
        print("Error: --prompt or --prompt-file is required", file=sys.stderr)
        return 1

    if args.prompt and args.prompt_file:
        print("Error: Cannot specify both --prompt and --prompt-file", file=sys.stderr)
        return 1

    prompt: str = ""
    if args.prompt_file:
        prompt_path: Path = Path(args.prompt_file)
        if not prompt_path.exists():
            print(f"Error: Prompt file not found: {args.prompt_file}", file=sys.stderr)
            return 1
        prompt = prompt_path.read_text()
    elif args.prompt:
        prompt = args.prompt

    console: Console = _make_console()

    model: str = args.model if args.model else config["default_model"]
    fallback_msgs: list[str] = []

    # Pre-flight model validation (before any session/Docker work)
    pf_errors, pf_warnings = preflight_check(
        model, config["config_dir"], args.env_file, no_sandboxing,
    )
    if pf_errors:
        for err in pf_errors:
            console.print(f"[red]Error:[/red] {err}")
        return 1
    if pf_warnings:
        for warn in pf_warnings:
            console.print(f"[yellow]Model fallback:[/yellow] {warn}")

    if continue_mode:
        continue_dir = Path(args.continue_dir).resolve()
        if not continue_dir.exists():
            console.print(f"Oops, continue directory [bold]{args.continue_dir}[/bold] not found.")
            return 1

        if args.work_dir:
            # Copy continue-dir to work-dir, then continue from there
            work_path = Path(args.work_dir).resolve()
            if work_path.exists():
                console.print(
                    f"Oops, work directory [bold]{args.work_dir}[/bold] already exists.\n"
                    f"You can remove it with: [cyan]rm -rf {args.work_dir}[/cyan]"
                )
                return 1
            shutil.copytree(continue_dir, work_path)
            work_dir = str(work_path)
            print(f"Copied {continue_dir} to {work_dir}")
        else:
            # Continue in place - ask for confirmation
            work_dir = str(continue_dir)
            print(f"Will continue session in: {work_dir}")
            confirm = input("Continue? [y/N]: ").strip().lower()
            if confirm != "y":
                print("Aborted.")
                return 0

        # Overwrite .opencode with latest from decision-pack (agent prompts may have changed)
        opencode_dir = Path(work_dir) / ".opencode"
        if opencode_dir.exists():
            try:
                shutil.rmtree(opencode_dir)
            except PermissionError:
                # Docker mode: files may be root-owned (e.g. node_modules/)
                subprocess.run(
                    ["sudo", "rm", "-rf", str(opencode_dir)],
                    check=True,
                )
        fallback_msgs: list[str] = setup_opencode_config(
            config["config_dir"], work_dir, model, args.env_file,
            no_sandboxing,
        )

        # Refresh hook scripts from decision-pack
        hooks_dest: Path = Path(work_dir) / "_hooks"
        if hooks_dest.exists():
            shutil.rmtree(hooks_dest)
        copy_hook_scripts(config, work_dir)
    else:
        try:
            state: dict[str, Any] = create_session(
                config,
                args.data,
                work_dir=args.work_dir,
                orchestrator_model=model,
                env_file=args.env_file,
                no_sandboxing=no_sandboxing,
            )
        except ValueError as e:
            err_msg: str = str(e)
            if "already exists" in err_msg:
                # Extract the path from the error message
                work_path_str: str = err_msg.split(": ", 1)[-1] if ": " in err_msg else str(args.work_dir or "")
                console.print(
                    f"Oops, work directory [bold]{work_path_str}[/bold] already exists.\n"
                    f"You can remove it with: [cyan]rm -rf {work_path_str}[/cyan]"
                )
            else:
                print(f"Error: {e}", file=sys.stderr)
            return 1
        work_dir = state["work_dir"]
        fallback_msgs = state.get("model_fallback_messages", [])
    image_name: str = config["docker_image_name"]
    container_name: str = Path(work_dir).name  # Use session dir basename

    # --- Header ---
    I: str = "      "  # 6-space indent for content under phase labels
    if no_sandboxing:
        console.print(f"[bold]dlab[/bold] [dim]·[/dim] {config['name']} [dim]·[/dim] {model} [dim]·[/dim] [yellow]no sandboxing[/yellow]")
    else:
        console.print(f"[bold]dlab[/bold] [dim]·[/dim] {config['name']} [dim]·[/dim] {model}")
    if continue_mode:
        console.print(f"[dim]Continuing:[/dim] {work_dir}")
    else:
        console.print(f"[dim]Session:[/dim]    {work_dir}")
    if env_file_missing:
        console.print(f"{I}[yellow]Warning:[/yellow] No --env-file provided and no .env found in decision-pack.")
        console.print(f"{I}[yellow]         The agent may fail if it needs API keys.[/yellow]")
    console.print()

    # Compute step numbering
    hooks: dict[str, Any] = config.get("hooks", {})
    pre_run_hooks: list[str] = hooks.get("pre-run", [])
    post_run_hooks: list[str] = hooks.get("post-run", [])

    step: int = 0
    total_steps: int = 2  # setup + cleanup (always present)
    if not no_sandboxing and pre_run_hooks:
        total_steps += 1
    total_steps += 1  # running agent (always present)
    if not no_sandboxing and post_run_hooks:
        total_steps += 1

    def next_step(label: str) -> str:
        nonlocal step
        step += 1
        return f"[bold]\\[{step}/{total_steps}] {label}[/bold]"

    # =====================================================================
    # LOCAL MODE (--no-sandboxing)
    # =====================================================================
    if no_sandboxing:
        from dlab.local import (
            build_local_env,
            build_local_prompt,
            copy_docker_dir,
            run_opencode_local,
        )

        console.print(next_step("Setting up local environment"))

        # Check opencode is installed
        if shutil.which("opencode") is None:
            console.print(f"{I}[bold red]Error:[/bold red] opencode is not installed.")
            console.print(f"{I}Install with: [bold]curl -fsSL https://opencode.ai/install | bash[/bold]")
            console.print(f"{I}See: [dim]https://opencode.ai[/dim]")
            return 1

        # Copy docker/ as _docker/ so the agent can read it
        copy_docker_dir(config["config_dir"], work_dir)
        console.print(f"{I}[dim]Copied docker/ to _docker/[/dim]")

        env_file_path: str | None = getattr(args, "env_file", None)
        local_env: dict[str, str] = build_local_env(env_file=env_file_path)
        console.print(f"{I}[green]Ready[/green]")

        # Prepend system instructions to prompt
        local_prompt: str = build_local_prompt(prompt, config)

        console.print(next_step("Running agent ..."))
        hint_text: Text = Text()
        hint_text.append("dlab connect ", style="bold")
        hint_text.append(work_dir, style="dim")
        hint_text.append("\n  Live-monitor the run\n\n")
        hint_text.append("dlab timeline ", style="bold")
        hint_text.append(work_dir, style="dim")
        hint_text.append("\n  View execution timeline after the run")
        panel: Panel = Panel(hint_text, title="[dim]Monitoring[/dim]", border_style="dim", expand=False, padding=(0, 1))
        console.print(Padding(panel, (0, 0, 0, 6)))

        try:
            logs_dir_local: Path = Path(work_dir) / "_opencode_logs"
            exit_code, stdout, stderr = _run_with_log_spinner(
                console, I, logs_dir_local,
                lambda: run_opencode_local(work_dir, local_prompt, model, local_env),
            )
            if stderr:
                console.print(f"{I}[red]{stderr}[/red]", highlight=False)
        except KeyboardInterrupt:
            console.print(f"\n{I}[yellow]Interrupted.[/yellow]")
            exit_code = 130

        console.print(next_step("Cleanup"))
        if exit_code == 0:
            console.print(f"{I}[bold green]Done.[/bold green]")
        else:
            console.print(f"{I}[bold red]Done (exit code {exit_code}).[/bold red]")

        return exit_code

    # =====================================================================
    # DOCKER MODE (default)
    # =====================================================================
    force_rebuild: bool = getattr(args, "rebuild", False)
    opencode_version: str = config["opencode_version"]

    should_rebuild: bool
    rebuild_reason: str
    if force_rebuild:
        should_rebuild = True
        rebuild_reason = "--rebuild flag passed"
    else:
        should_rebuild, rebuild_reason = needs_rebuild(
            config["config_dir"], image_name, opencode_version,
        )

    console.print(next_step("Setting up environment"))
    if should_rebuild:
        console.print(f"{I}[yellow]Building image:[/yellow] {image_name}")
        console.print(f"{I}[dim]Reason: {rebuild_reason}[/dim]")
        console.print(f"{I}[dim]opencode version: {opencode_version}[/dim]")
        try:
            build_line_count: int = 0
            build_spinner: Spinner = Spinner("dots", style="dim")

            def _build_renderable() -> Text:
                text = Text(I)
                text.append_text(build_spinner.render(_time.time()))
                text.append(f" » {build_line_count} ", style="dim")
                text.append("msgs", style="#555555")
                return text

            build_running: bool = True

            with Live(_build_renderable(), console=console, refresh_per_second=10, transient=True) as build_live:
                def _build_tick() -> None:
                    while build_running:
                        build_live.update(_build_renderable())
                        _time.sleep(0.1)

                build_ticker = threading.Thread(target=_build_tick, daemon=True)
                build_ticker.start()

                def _on_build_output(line: str) -> None:
                    nonlocal build_line_count
                    build_line_count += 1

                build_image(config["config_dir"], image_name, opencode_version, on_output=_on_build_output)
                build_running = False

            console.print(f"{I}[green]Image built.[/green]")
        except ValueError as e:
            console.print(f"{I}[bold red]Error:[/bold red] {e}", highlight=False)
            return 1
    else:
        console.print(f"{I}[dim]Image:[/dim] {image_name} [dim](cached)[/dim]")

    dangling: int = count_dangling_images()
    if dangling > 0:
        console.print(f"{I}[yellow]Warning:[/yellow] {dangling} dangling Docker image(s) using disk space")
        console.print(f"{I}[dim]Clean up with: docker image prune -f[/dim]")

    env_file: str | None = getattr(args, "env_file", None)

    # Forward all DLAB_* env vars from host to container
    extra_env: dict[str, str] = {
        key: value
        for key, value in os.environ.items()
        if key.startswith("DLAB_")
    }
    for key, value in extra_env.items():
        console.print(f"{I}[dim]{key}={value}[/dim]")

    try:
        start_container(image_name, work_dir, container_name, env_file=env_file, extra_env=extra_env)
        console.print(f"{I}[green]Container started:[/green] {container_name}")
    except ValueError as e:
        console.print(f"{I}[bold red]Error:[/bold red] {e}", highlight=False)
        return 1

    # Set up signal handlers to ensure container cleanup on interrupt
    container_stopped: bool = False

    interrupted: bool = False

    def cleanup_handler(signum: int, frame: Any) -> None:
        nonlocal interrupted
        interrupted = True
        console.print(f"\n{I}[yellow]Interrupted — will stop after cleanup.[/yellow]")
        # Raise KeyboardInterrupt to break out of the blocking run_opencode call
        raise KeyboardInterrupt

    original_sigint = signal.signal(signal.SIGINT, cleanup_handler)
    original_sigterm = signal.signal(signal.SIGTERM, cleanup_handler)

    exit_code: int = 1
    try:
        # --- Pre-run hooks (optional step) ---
        if pre_run_hooks:
            console.print(next_step("Pre-run hooks"))
            for script in pre_run_hooks:
                console.print(f"{I}[cyan]{script}[/cyan]")
                hook_exit, hook_out, hook_err = exec_command(
                    container_name,
                    ["bash", "-c", f"chmod +x /workspace/_hooks/{script} && /workspace/_hooks/{script}"],
                )
                if hook_out:
                    for line in hook_out.rstrip("\n").split("\n"):
                        console.print(f"{I}  [dim]{line}[/dim]")
                if hook_err:
                    console.print(f"{I}  [red]{hook_err.rstrip()}[/red]")
                if hook_exit != 0:
                    console.print(f"{I}[bold red]ERROR:[/bold red] {script} failed (exit {hook_exit})")
                    exit_code = hook_exit
                    raise RuntimeError(f"Pre-run hook failed: {script}")

        # --- Running agent ---
        console.print(next_step("Running agent ..."))
        hint_text: Text = Text()
        hint_text.append("dlab connect ", style="bold")
        hint_text.append(work_dir, style="dim")
        hint_text.append("\n  Live-monitor the run\n\n")
        hint_text.append("dlab timeline ", style="bold")
        hint_text.append(work_dir, style="dim")
        hint_text.append("\n  View execution timeline after the run")
        panel: Panel = Panel(hint_text, title="[dim]Monitoring[/dim]", border_style="dim", expand=False, padding=(0, 1))
        console.print(Padding(panel, (0, 0, 0, 6)))

        logs_dir_path: Path = Path(work_dir) / "_opencode_logs"
        exit_code, stdout, stderr = _run_with_log_spinner(
            console, I, logs_dir_path,
            lambda: run_opencode(container_name, prompt, model),
        )
        if stderr:
            console.print(f"{I}[red]{stderr}[/red]", highlight=False)

        # --- Post-run hooks (optional step) ---
        if post_run_hooks:
            console.print(next_step("Post-run hooks"))
            for script in post_run_hooks:
                console.print(f"{I}[cyan]{script}[/cyan]")
                hook_exit, hook_out, hook_err = exec_command(
                    container_name,
                    ["bash", "-c", f"chmod +x /workspace/_hooks/{script} && /workspace/_hooks/{script}"],
                )
                if hook_out:
                    for line in hook_out.rstrip("\n").split("\n"):
                        console.print(f"{I}  [dim]{line}[/dim]")
                if hook_err:
                    console.print(f"{I}  [red]{hook_err.rstrip()}[/red]")
                if hook_exit != 0:
                    console.print(f"{I}[bold yellow]WARNING:[/bold yellow] {script} failed (exit {hook_exit})")
    except RuntimeError:
        pass  # Hook failure — exit_code already set
    except KeyboardInterrupt:
        exit_code = 130
    except Exception as e:
        console.print(f"{I}[bold red]Error:[/bold red] {e}", highlight=False)
    finally:
        # Restore original signal handlers so a second Ctrl+C during cleanup
        # does the default thing (hard exit) instead of looping
        signal.signal(signal.SIGINT, original_sigint)
        signal.signal(signal.SIGTERM, original_sigterm)

        # --- Cleanup ---
        console.print(next_step("Cleanup"))
        # Fix file ownership before stopping (container runs as root)
        uid_gid: str = f"{os.getuid()}:{os.getgid()}"
        exec_command(container_name, ["chown", "-R", uid_gid, "/workspace", "/_opencode_logs"])
        console.print(f"{I}[dim]Stopping container...[/dim]")
        stop_container(container_name)
        container_stopped = True
        if interrupted:
            console.print(f"{I}[yellow]Interrupted.[/yellow]")
        elif exit_code == 0:
            console.print(f"{I}[bold green]Done.[/bold green]")
        else:
            console.print(f"{I}[bold red]Done (exit code {exit_code}).[/bold red]")

    return exit_code


def cmd_install(args: argparse.Namespace) -> int:
    """
    Handle install mode - create wrapper script for a decision-pack.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed command-line arguments.

    Returns
    -------
    int
        Exit code (0 for success, non-zero for failure).
    """
    try:
        config: dict[str, Any] = load_dpack_config(args.dpack_path)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    dpack_name: str = config["name"]
    cli_name: str = config.get("cli_name", "") or dpack_name
    config_dir: str = config["config_dir"]

    bin_dir: Path = Path(args.bin_dir)
    if not bin_dir.exists():
        bin_dir.mkdir(parents=True)

    wrapper_path: Path = bin_dir / cli_name
    wrapper_content: str = WRAPPER_TEMPLATE.format(
        dpack_name=dpack_name,
        config_dir=config_dir,
    )

    wrapper_path.write_text(wrapper_content)

    current_mode: int = wrapper_path.stat().st_mode
    wrapper_path.chmod(current_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    print(f"Installed wrapper: {wrapper_path}")
    print(f"decision-pack: {dpack_name}")
    if cli_name != dpack_name:
        print(f"CLI name: {cli_name}")
    print(f"Config: {config_dir}")

    if str(bin_dir) not in os.environ.get("PATH", ""):
        print()
        print(f"Note: {bin_dir} may not be in your PATH")
        print(f"Add to your shell config: export PATH=\"{bin_dir}:$PATH\"")

    return 0


def cmd_connect(args: argparse.Namespace) -> int:
    """
    Handle connect mode - TUI monitor for running or completed sessions.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed command-line arguments.

    Returns
    -------
    int
        Exit code (0 for success, non-zero for failure).
    """
    work_dir: Path = Path(args.work_dir).resolve()

    if not work_dir.exists():
        print(f"Error: Work directory not found: {work_dir}", file=sys.stderr)
        return 1

    logs_dir: Path = work_dir / "_opencode_logs"
    if not logs_dir.exists():
        print(f"Error: No logs directory found: {logs_dir}", file=sys.stderr)
        print("Make sure this is a valid dlab session directory.", file=sys.stderr)
        return 1

    # Non-interactive modes (for scripting/piping)
    if args.log_json:
        print("Error: --log-json mode is not yet implemented", file=sys.stderr)
        return 1

    if args.log:
        print("Error: --log mode is not yet implemented", file=sys.stderr)
        return 1

    # Interactive TUI mode (default)
    from dlab.tui import ConnectApp

    app = ConnectApp(work_dir)
    app.run()
    return 0


def cmd_create_parallel_agent(args: argparse.Namespace) -> int:
    """
    Launch TUI wizard for creating a parallel agent configuration.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed command-line arguments.

    Returns
    -------
    int
        Exit code (0 for success).
    """
    from rich.console import Console

    from dlab.config import list_config_issues
    from dlab.create_parallel_agent_wizard import CreateParallelAgentApp

    dpack: str = getattr(args, "dpack", ".")
    is_default: bool = dpack == "."
    resolved: str = str(Path(dpack).resolve())

    issues: list[str] = list_config_issues(dpack)
    if issues:
        console: Console = Console(highlight=False)
        if is_default:
            console.print("[yellow]No decision-pack directory provided, checking current directory...[/yellow]")
        console.print(f"[red]{resolved} is not a valid decision-pack directory:[/red]")
        for issue in issues:
            console.print(f"  [dim]- {issue}[/dim]")
        if is_default:
            console.print()
            console.print("Usage: [bold]dlab create-parallel-agent <dpack-dir>[/bold]")
        return 1

    try:
        app: CreateParallelAgentApp = CreateParallelAgentApp(dpack)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    app.run()

    if app.created_files:
        console: Console = Console(highlight=False)
        console.print("[bold green]Created:[/bold green]")
        for f in app.created_files:
            console.print(f"  {f}")
    return 0


def cmd_view(args: argparse.Namespace) -> int:
    """
    Handle view mode - browser-based session viewer with DAG visualization.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed command-line arguments.

    Returns
    -------
    int
        Exit code (0 for success, non-zero for failure).
    """
    work_dir: Path = Path(args.work_dir).resolve()

    if not work_dir.exists():
        print(f"Error: Work directory not found: {work_dir}", file=sys.stderr)
        return 1

    logs_dir: Path = work_dir / "_opencode_logs"
    if not logs_dir.exists():
        print(f"Error: No logs directory found: {logs_dir}", file=sys.stderr)
        print("Make sure this is a valid dlab session directory.", file=sys.stderr)
        return 1

    try:
        from dlab.viewer import run_viewer
    except ImportError:
        print("Error: Viewer dependencies not installed.", file=sys.stderr)
        print("Install with: pip install 'dlab-cli[viewer]'", file=sys.stderr)
        return 1

    return run_viewer(
        work_dir,
        port=args.port,
        open_browser=not args.no_open,
    )


def cmd_timeline(args: argparse.Namespace) -> int:
    """
    Handle timeline mode - display execution timeline for a session.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed command-line arguments.

    Returns
    -------
    int
        Exit code (0 for success, non-zero for failure).
    """
    work_dir: Path | None = Path(args.work_dir) if args.work_dir else None
    return run_timeline(work_dir)


def cmd_create_dpack(args: argparse.Namespace) -> int:
    """
    Handle create-dpack mode - launch TUI wizard.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed command-line arguments.

    Returns
    -------
    int
        Exit code (0 for success).
    """
    from dlab.create_dpack_wizard import CreateDpackApp

    output_dir: str = getattr(args, "output_dir", ".")
    app: CreateDpackApp = CreateDpackApp(output_dir)
    app.run()
    return 0


def _suggest_corrections(unknown_args: list[str], parser: argparse.ArgumentParser) -> None:
    """
    Print fuzzy-match suggestions for unknown CLI arguments and exit.

    Parameters
    ----------
    unknown_args : list[str]
        Unrecognized arguments from parse_known_args.
    parser : argparse.ArgumentParser
        The argument parser (used to extract valid flags and subcommands).
    """
    valid_flags: list[str] = [
        opt
        for action in parser._actions
        for opt in action.option_strings
        if opt.startswith("--")
    ]
    valid_subcommands: list[str] = []
    for action in parser._subparsers._actions:
        if hasattr(action, "choices") and action.choices:
            valid_subcommands = list(action.choices.keys())
            break

    # Skip values that follow unknown flags (e.g., "out" after "--workdir out").
    # These aren't separate errors — they're the value of the preceding unknown flag.
    skip_next: bool = False
    for i, arg in enumerate(unknown_args):
        if skip_next:
            skip_next = False
            continue

        if arg.startswith("--"):
            matches: list[str] = difflib.get_close_matches(
                arg, valid_flags, n=1, cutoff=0.6,
            )
            if matches:
                print(f"Unknown argument: {arg}. Did you mean {matches[0]}?", file=sys.stderr)
            else:
                print(f"Unknown argument: {arg}", file=sys.stderr)
            # If next arg doesn't start with '-', it's likely this flag's value
            if i + 1 < len(unknown_args) and not unknown_args[i + 1].startswith("-"):
                skip_next = True
        elif not arg.startswith("-") and valid_subcommands:
            matches = difflib.get_close_matches(
                arg, valid_subcommands, n=1, cutoff=0.6,
            )
            if matches:
                print(f"Unknown command: {arg}. Did you mean {matches[0]}?", file=sys.stderr)
            else:
                print(f"Unknown argument: {arg}", file=sys.stderr)
        else:
            print(f"Unknown argument: {arg}", file=sys.stderr)
    sys.exit(2)


def main() -> None:
    """
    Entry point for the CLI.
    """
    parser: argparse.ArgumentParser = create_parser()

    # Override argparse's error handler so misspelled subcommands don't produce
    # a generic "invalid choice" message before we can suggest corrections.
    # We collect bad subcommand values and merge them with unknown flags.
    import re

    class _BadSubcommand(Exception):
        """Raised when argparse detects an invalid subcommand choice."""
        def __init__(self, value: str) -> None:
            self.value = value

    original_error = parser.error

    def custom_error(message: str) -> None:
        match = re.search(r"invalid choice: '([^']+)'", message)
        if match:
            raise _BadSubcommand(match.group(1))
        original_error(message)

    parser.error = custom_error  # type: ignore[assignment]

    args: argparse.Namespace
    unknown: list[str]
    try:
        args, unknown = parser.parse_known_args()
    except _BadSubcommand as e:
        # Argparse caught a bad subcommand. This often happens when an unknown
        # flag's value (e.g., "out" from "--workdir out") gets interpreted as a
        # positional subcommand argument. Re-parse with subcommands disabled so
        # valid flags are recognized and only truly unknown flags remain.
        parser_no_sub: argparse.ArgumentParser = create_parser()
        # Remove subparsers action so positionals don't trigger subcommand matching
        parser_no_sub._subparsers._actions[:] = [
            a for a in parser_no_sub._subparsers._actions
            if not hasattr(a, "choices")
        ]
        _, unknown = parser_no_sub.parse_known_args()
        # The bad subcommand value was likely a flag's argument — don't report
        # it separately unless it looks like it was meant as a subcommand
        if e.value not in unknown:
            matches = difflib.get_close_matches(
                e.value,
                [c for a in parser._subparsers._actions
                 if hasattr(a, "choices") and a.choices
                 for c in a.choices.keys()],
                n=1, cutoff=0.6,
            )
            if matches:
                unknown.append(e.value)
        if unknown:
            _suggest_corrections(unknown, parser)
        else:
            # Nothing unknown after re-parse — the "bad subcommand" was just
            # a value trailing an unknown flag. Report the original error.
            original_error(f"argument command: invalid choice: '{e.value}'")

    if unknown:
        _suggest_corrections(unknown, parser)

    if args.command == "install":
        exit_code: int = cmd_install(args)
    elif args.command == "connect":
        exit_code = cmd_connect(args)
    elif args.command == "create-parallel-agent":
        exit_code = cmd_create_parallel_agent(args)
    elif args.command == "create-dpack":
        exit_code = cmd_create_dpack(args)
    elif args.command == "timeline":
        exit_code = cmd_timeline(args)
    elif args.command == "view":
        exit_code = cmd_view(args)
    elif args.dpack or args.data or args.prompt or args.prompt_file or args.continue_dir:
        exit_code = cmd_run(args)
    else:
        parser.print_help()
        exit_code = 0

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
