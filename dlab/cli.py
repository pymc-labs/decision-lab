"""
Command-line interface for dlab.
"""

import os
import shutil
import signal
import stat
import subprocess
import sys
import threading
import time as _time
from pathlib import Path
from typing import Annotated, Any, Callable

import typer
from rich.console import Console
from rich.live import Live
from rich.padding import Padding
from rich.panel import Panel
from rich.spinner import Spinner
from rich.text import Text

from dlab.config import load_dpack_config

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
from dlab.model_fallback import preflight_check
from dlab.session import copy_hook_scripts, create_session, setup_opencode_config
from dlab.timeline import run_timeline

app = typer.Typer(
    name="dlab",
    help="Run opencode in automated mode, sandboxed with Docker",
    no_args_is_help=False,
    add_completion=False,
    suggest_commands=True,
)


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

    with Live(
        _make_renderable(), console=console, refresh_per_second=10, transient=True
    ) as live:

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


@app.callback(invoke_without_command=True)
def _main(
    ctx: typer.Context,
    dpack: Annotated[
        str | None,
        typer.Option(
            "--dpack", metavar="PATH", help="Path to decision-pack config directory"
        ),
    ] = None,
    data: Annotated[
        list[str] | None,
        typer.Option(
            "--data",
            metavar="PATH",
            help="Data file or directory to copy into the workspace "
            "(repeat for multiple: --data a.csv --data b.csv)",
        ),
    ] = None,
    model: Annotated[
        str | None,
        typer.Option(
            "--model",
            metavar="MODEL",
            help="Model to use (overrides default_model from config)",
        ),
    ] = None,
    prompt: Annotated[
        str | None,
        typer.Option("--prompt", metavar="TEXT", help="Prompt text for the agent"),
    ] = None,
    prompt_file: Annotated[
        str | None,
        typer.Option(
            "--prompt-file", metavar="PATH", help="Path to file containing prompt text"
        ),
    ] = None,
    work_dir: Annotated[
        str | None,
        typer.Option("--work-dir", metavar="PATH", help="Explicit work directory path"),
    ] = None,
    continue_dir: Annotated[
        str | None,
        typer.Option(
            "--continue-dir",
            metavar="PATH",
            help="Continue an interrupted session from this work directory",
        ),
    ] = None,
    rebuild: Annotated[
        bool,
        typer.Option("--rebuild", help="Force rebuild Docker image"),
    ] = False,
    env_file: Annotated[
        str | None,
        typer.Option(
            "--env-file",
            metavar="PATH",
            help="Path to environment file (passed to Docker container)",
        ),
    ] = None,
    no_sandboxing: Annotated[
        bool,
        typer.Option(
            "--no-sandboxing",
            help="Run opencode locally without Docker (no container isolation)",
        ),
    ] = False,
) -> None:
    """Run opencode in automated mode, sandboxed with Docker."""
    if ctx.resilient_parsing:
        return

    if ctx.invoked_subcommand is not None:
        return

    if any([dpack, data, prompt, prompt_file, continue_dir]):
        exit_code = cmd_run(
            dpack=dpack,
            data=data,
            model=model,
            prompt=prompt,
            prompt_file=prompt_file,
            work_dir=work_dir,
            continue_dir=continue_dir,
            rebuild=rebuild,
            env_file=env_file,
            no_sandboxing=no_sandboxing,
        )
        raise typer.Exit(code=exit_code)

    typer.echo(ctx.get_help())
    raise typer.Exit(code=0)


def cmd_run(
    dpack: str | None = None,
    data: list[str] | None = None,
    model: str | None = None,
    prompt: str | None = None,
    prompt_file: str | None = None,
    work_dir: str | None = None,
    continue_dir: str | None = None,
    rebuild: bool = False,
    env_file: str | None = None,
    no_sandboxing: bool = False,
) -> int:
    """
    Handle run mode - create session and start agent.

    Returns
    -------
    int
        Exit code (0 for success, non-zero for failure).
    """
    if not dpack:
        print("Error: --dpack is required for run mode", file=sys.stderr)
        return 1

    # Load config early so we can check requires_data
    try:
        config: dict[str, Any] = load_dpack_config(dpack)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    # Resolve execution mode: Docker vs local
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
    if not env_file:
        dpack_env: Path = Path(dpack).resolve() / ".env"
        if dpack_env.exists():
            env_file = str(dpack_env)

    env_file_missing: bool = not env_file

    # Check for continue mode vs new session mode
    continue_mode: bool = bool(continue_dir)
    requires_data: bool = config.get("requires_data", True)
    requires_prompt: bool = config.get("requires_prompt", True)

    if continue_mode:
        if data:
            print("Error: Cannot use --data with --continue-dir", file=sys.stderr)
            return 1
    else:
        if requires_data and not data:
            print(
                "Error: --data is required (or use --continue-dir to resume)",
                file=sys.stderr,
            )
            return 1
        if data:
            for data_path in data:
                if not Path(data_path).exists():
                    print(
                        f"Error: Data path does not exist: {data_path}", file=sys.stderr
                    )
                    return 1

    if requires_prompt and not prompt and not prompt_file:
        print("Error: --prompt or --prompt-file is required", file=sys.stderr)
        return 1

    if prompt and prompt_file:
        print("Error: Cannot specify both --prompt and --prompt-file", file=sys.stderr)
        return 1

    resolved_prompt: str = ""
    if prompt_file:
        prompt_path: Path = Path(prompt_file)
        if not prompt_path.exists():
            print(f"Error: Prompt file not found: {prompt_file}", file=sys.stderr)
            return 1
        resolved_prompt = prompt_path.read_text()
    elif prompt:
        resolved_prompt = prompt

    console: Console = _make_console()

    if not model:
        model = config["default_model"]
    fallback_msgs: list[str] = []

    # Pre-flight model validation (before any session/Docker work)
    pf_errors, pf_warnings = preflight_check(
        model,
        config["config_dir"],
        env_file,
        no_sandboxing,
    )
    if pf_errors:
        for err in pf_errors:
            console.print(f"[red]Error:[/red] {err}")
        return 1
    if pf_warnings:
        for warn in pf_warnings:
            console.print(f"[yellow]Model fallback:[/yellow] {warn}")

    if continue_mode:
        _continue_dir: Path = Path(continue_dir).resolve()
        if not _continue_dir.exists():
            console.print(
                f"Oops, continue directory [bold]{continue_dir}[/bold] not found."
            )
            return 1

        if work_dir:
            # Copy continue-dir to work-dir, then continue from there
            work_path = Path(work_dir).resolve()
            if work_path.exists():
                console.print(
                    f"Oops, work directory [bold]{work_dir}[/bold] already exists.\n"
                    f"You can remove it with: [cyan]rm -rf {work_dir}[/cyan]"
                )
                return 1
            shutil.copytree(_continue_dir, work_path)
            work_dir = str(work_path)
            print(f"Copied {_continue_dir} to {work_dir}")
        else:
            # Continue in place - ask for confirmation
            work_dir = str(_continue_dir)
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
            config["config_dir"],
            work_dir,
            model,
            env_file,
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
                data,
                work_dir=work_dir,
                orchestrator_model=model,
                env_file=env_file,
                no_sandboxing=no_sandboxing,
            )
        except ValueError as e:
            err_msg: str = str(e)
            if "already exists" in err_msg:
                # Extract the path from the error message
                work_path_str: str = (
                    err_msg.split(": ", 1)[-1]
                    if ": " in err_msg
                    else str(work_dir or "")
                )
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
        console.print(
            f"[bold]dlab[/bold] [dim]·[/dim] {config['name']} [dim]·[/dim] {model} [dim]·[/dim] [yellow]no sandboxing[/yellow]"
        )
    else:
        console.print(
            f"[bold]dlab[/bold] [dim]·[/dim] {config['name']} [dim]·[/dim] {model}"
        )
    if continue_mode:
        console.print(f"[dim]Continuing:[/dim] {work_dir}")
    else:
        console.print(f"[dim]Session:[/dim]    {work_dir}")
    if env_file_missing:
        console.print(
            f"{I}[yellow]Warning:[/yellow] No --env-file provided and no .env found in decision-pack."
        )
        console.print(
            f"{I}[yellow]         The agent may fail if it needs API keys.[/yellow]"
        )
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
            console.print(
                f"{I}Install with: [bold]curl -fsSL https://opencode.ai/install | bash[/bold]"
            )
            console.print(f"{I}See: [dim]https://opencode.ai[/dim]")
            return 1

        # Copy docker/ as _docker/ so the agent can read it
        copy_docker_dir(config["config_dir"], work_dir)
        console.print(f"{I}[dim]Copied docker/ to _docker/[/dim]")

        local_env: dict[str, str] = build_local_env(env_file=env_file)
        console.print(f"{I}[green]Ready[/green]")

        # Prepend system instructions to prompt
        local_prompt: str = build_local_prompt(resolved_prompt, config)

        console.print(next_step("Running agent ..."))
        hint_text: Text = Text()
        hint_text.append("dlab connect ", style="bold")
        hint_text.append(work_dir, style="dim")
        hint_text.append("\n  Live-monitor the run\n\n")
        hint_text.append("dlab timeline ", style="bold")
        hint_text.append(work_dir, style="dim")
        hint_text.append("\n  View execution timeline after the run")
        panel: Panel = Panel(
            hint_text,
            title="[dim]Monitoring[/dim]",
            border_style="dim",
            expand=False,
            padding=(0, 1),
        )
        console.print(Padding(panel, (0, 0, 0, 6)))

        try:
            logs_dir_local: Path = Path(work_dir) / "_opencode_logs"
            exit_code, stdout, stderr = _run_with_log_spinner(
                console,
                I,
                logs_dir_local,
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
    force_rebuild: bool = rebuild
    opencode_version: str = config["opencode_version"]

    should_rebuild: bool
    rebuild_reason: str
    if force_rebuild:
        should_rebuild = True
        rebuild_reason = "--rebuild flag passed"
    else:
        should_rebuild, rebuild_reason = needs_rebuild(
            config["config_dir"],
            image_name,
            opencode_version,
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

            with Live(
                _build_renderable(),
                console=console,
                refresh_per_second=10,
                transient=True,
            ) as build_live:

                def _build_tick() -> None:
                    while build_running:
                        build_live.update(_build_renderable())
                        _time.sleep(0.1)

                build_ticker = threading.Thread(target=_build_tick, daemon=True)
                build_ticker.start()

                def _on_build_output(line: str) -> None:
                    nonlocal build_line_count
                    build_line_count += 1

                build_image(
                    config["config_dir"],
                    image_name,
                    opencode_version,
                    on_output=_on_build_output,
                )
                build_running = False

            console.print(f"{I}[green]Image built.[/green]")
        except ValueError as e:
            console.print(f"{I}[bold red]Error:[/bold red] {e}", highlight=False)
            return 1
    else:
        console.print(f"{I}[dim]Image:[/dim] {image_name} [dim](cached)[/dim]")

    dangling: int = count_dangling_images()
    if dangling > 0:
        console.print(
            f"{I}[yellow]Warning:[/yellow] {dangling} dangling Docker image(s) using disk space"
        )
        console.print(f"{I}[dim]Clean up with: docker image prune -f[/dim]")

    # Forward all DLAB_* env vars from host to container
    extra_env: dict[str, str] = {
        key: value for key, value in os.environ.items() if key.startswith("DLAB_")
    }
    for key, value in extra_env.items():
        console.print(f"{I}[dim]{key}={value}[/dim]")

    try:
        start_container(
            image_name, work_dir, container_name, env_file=env_file, extra_env=extra_env
        )
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
                    [
                        "bash",
                        "-c",
                        f"chmod +x /workspace/_hooks/{script} && /workspace/_hooks/{script}",
                    ],
                )
                if hook_out:
                    for line in hook_out.rstrip("\n").split("\n"):
                        console.print(f"{I}  [dim]{line}[/dim]")
                if hook_err:
                    console.print(f"{I}  [red]{hook_err.rstrip()}[/red]")
                if hook_exit != 0:
                    console.print(
                        f"{I}[bold red]ERROR:[/bold red] {script} failed (exit {hook_exit})"
                    )
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
        panel: Panel = Panel(
            hint_text,
            title="[dim]Monitoring[/dim]",
            border_style="dim",
            expand=False,
            padding=(0, 1),
        )
        console.print(Padding(panel, (0, 0, 0, 6)))

        logs_dir_path: Path = Path(work_dir) / "_opencode_logs"
        exit_code, stdout, stderr = _run_with_log_spinner(
            console,
            I,
            logs_dir_path,
            lambda: run_opencode(container_name, resolved_prompt, model),
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
                    [
                        "bash",
                        "-c",
                        f"chmod +x /workspace/_hooks/{script} && /workspace/_hooks/{script}",
                    ],
                )
                if hook_out:
                    for line in hook_out.rstrip("\n").split("\n"):
                        console.print(f"{I}  [dim]{line}[/dim]")
                if hook_err:
                    console.print(f"{I}  [red]{hook_err.rstrip()}[/red]")
                if hook_exit != 0:
                    console.print(
                        f"{I}[bold yellow]WARNING:[/bold yellow] {script} failed (exit {hook_exit})"
                    )
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
        exec_command(
            container_name, ["chown", "-R", uid_gid, "/workspace", "/_opencode_logs"]
        )
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


@app.command("install")
def _cmd_install(
    dpack_path: Annotated[
        str,
        typer.Argument(metavar="PATH", help="Path to decision-pack config directory"),
    ],
    bin_dir: Annotated[
        str,
        typer.Option(
            "--bin-dir",
            metavar="PATH",
            help="Directory to install wrapper script (default: ~/.local/bin)",
        ),
    ] = os.path.expanduser("~/.local/bin"),
) -> None:
    """Install a decision-pack as a wrapper script."""
    exit_code = cmd_install(dpack_path=dpack_path, bin_dir=bin_dir)
    raise typer.Exit(code=exit_code)


def cmd_install(
    dpack_path: str,
    bin_dir: str = os.path.expanduser("~/.local/bin"),
) -> int:
    """
    Handle install mode - create wrapper script for a decision-pack.

    Returns
    -------
    int
        Exit code (0 for success, non-zero for failure).
    """
    try:
        config: dict[str, Any] = load_dpack_config(dpack_path)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    dpack_name: str = config["name"]
    cli_name: str = config.get("cli_name", "") or dpack_name
    config_dir: str = config["config_dir"]

    bin_dir: Path = Path(bin_dir)
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
        print(f'Add to your shell config: export PATH="{bin_dir}:$PATH"')

    return 0


@app.command("connect")
def _cmd_connect(
    work_dir: Annotated[
        str,
        typer.Argument(metavar="WORK_DIR", help="Path to session work directory"),
    ],
    log: Annotated[
        bool,
        typer.Option("--log", help="Show rich formatted log output"),
    ] = False,
    log_json: Annotated[
        bool,
        typer.Option("--log-json", help="Show raw JSON log output"),
    ] = False,
) -> None:
    """Connect to a running or completed session (TUI monitor)."""
    exit_code = cmd_connect(work_dir=work_dir, log=log, log_json=log_json)
    raise typer.Exit(code=exit_code)


def cmd_connect(
    work_dir: str,
    log: bool = False,
    log_json: bool = False,
) -> int:
    """
    Handle connect mode - TUI monitor for running or completed sessions.

    Returns
    -------
    int
        Exit code (0 for success, non-zero for failure).
    """
    work_dir_path: Path = Path(work_dir).resolve()

    if not work_dir_path.exists():
        print(f"Error: Work directory not found: {work_dir_path}", file=sys.stderr)
        return 1

    logs_dir: Path = work_dir_path / "_opencode_logs"
    if not logs_dir.exists():
        print(f"Error: No logs directory found: {logs_dir}", file=sys.stderr)
        print("Make sure this is a valid dlab session directory.", file=sys.stderr)
        return 1

    # Non-interactive modes (for scripting/piping)
    if log_json:
        print("Error: --log-json mode is not yet implemented", file=sys.stderr)
        return 1

    if log:
        print("Error: --log mode is not yet implemented", file=sys.stderr)
        return 1

    # Interactive TUI mode (default)
    from dlab.tui import ConnectApp

    tui = ConnectApp(work_dir_path)
    tui.run()
    return 0


@app.command("create-parallel-agent")
def _cmd_create_parallel_agent(
    dpack: Annotated[
        str,
        typer.Argument(
            metavar="DPACK_DIR",
            help="Path to decision-pack config directory (default: current directory)",
        ),
    ] = ".",
) -> None:
    """Interactive wizard to create a parallel agent configuration."""
    exit_code = cmd_create_parallel_agent(dpack=dpack)
    raise typer.Exit(code=exit_code)


def cmd_create_parallel_agent(dpack: str = ".") -> int:
    """
    Launch TUI wizard for creating a parallel agent configuration.

    Returns
    -------
    int
        Exit code (0 for success).
    """
    from rich.console import Console

    from dlab.config import list_config_issues
    from dlab.create_parallel_agent_wizard import CreateParallelAgentApp

    is_default: bool = dpack == "."
    resolved: str = str(Path(dpack).resolve())

    issues: list[str] = list_config_issues(dpack)
    if issues:
        console: Console = Console(highlight=False)
        if is_default:
            console.print(
                "[yellow]No decision-pack directory provided, checking current directory...[/yellow]"
            )
        console.print(f"[red]{resolved} is not a valid decision-pack directory:[/red]")
        for issue in issues:
            console.print(f"  [dim]- {issue}[/dim]")
        if is_default:
            console.print()
            console.print("Usage: [bold]dlab create-parallel-agent <dpack-dir>[/bold]")
        return 1

    try:
        wizard: CreateParallelAgentApp = CreateParallelAgentApp(dpack)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    wizard.run()

    if wizard.created_files:
        console: Console = Console(highlight=False)
        console.print("[bold green]Created:[/bold green]")
        for f in wizard.created_files:
            console.print(f"  {f}")
    return 0


@app.command("view")
def _cmd_view(
    work_dir: Annotated[
        str,
        typer.Argument(metavar="WORK_DIR", help="Path to session work directory"),
    ],
    port: Annotated[
        int,
        typer.Option(
            "--port", help="Port for the viewer server (default: auto-select)"
        ),
    ] = 0,
    no_open: Annotated[
        bool,
        typer.Option("--no-open", help="Start server without opening browser"),
    ] = False,
    export: Annotated[
        str | None,
        typer.Option(
            "--export",
            metavar="FILE",
            help="Export self-contained HTML file instead of starting server",
        ),
    ] = None,
) -> None:
    """Open browser-based session viewer with DAG visualization."""
    exit_code = cmd_view(work_dir=work_dir, port=port, no_open=no_open, export=export)
    raise typer.Exit(code=exit_code)


def cmd_view(
    work_dir: str,
    port: int = 0,
    no_open: bool = False,
    export: str | None = None,
) -> int:
    """
    Handle view mode - browser-based session viewer with DAG visualization.

    Returns
    -------
    int
        Exit code (0 for success, non-zero for failure).
    """
    work_dir_path: Path = Path(work_dir).resolve()

    if not work_dir_path.exists():
        print(f"Error: Work directory not found: {work_dir_path}", file=sys.stderr)
        return 1

    logs_dir: Path = work_dir_path / "_opencode_logs"
    if not logs_dir.exists():
        print(f"Error: No logs directory found: {logs_dir}", file=sys.stderr)
        print("Make sure this is a valid dlab session directory.", file=sys.stderr)
        return 1

    # Export mode — no server dependencies needed
    if export:
        from dlab.viewer.server import export_viewer

        output_path: Path = Path(export)
        return export_viewer(work_dir_path, output_path)

    from dlab.viewer import run_viewer

    return run_viewer(
        work_dir_path,
        port=port,
        open_browser=not no_open,
    )


@app.command("timeline")
def _cmd_timeline(
    work_dir: Annotated[
        str | None,
        typer.Argument(
            metavar="WORK_DIR",
            help="Path to session work directory "
            "(default: cwd if it contains _opencode_logs)",
        ),
    ] = None,
) -> None:
    """Display execution timeline and Gantt chart for a session."""
    exit_code = cmd_timeline(work_dir=work_dir)
    raise typer.Exit(code=exit_code)


def cmd_timeline(work_dir: str | None = None) -> int:
    """..."""
    work_dir_path: Path | None = Path(work_dir) if work_dir else None
    return run_timeline(work_dir_path)


@app.command("create-dpack")
def _cmd_create_dpack(
    output_dir: Annotated[
        str,
        typer.Argument(
            metavar="OUTPUT_DIR",
            help="Directory where the decision-pack will be created "
            "(default: current directory)",
        ),
    ] = ".",
) -> None:
    """Interactive wizard to create a new decision-pack directory."""
    exit_code = cmd_create_dpack(output_dir=output_dir)
    raise typer.Exit(code=exit_code)


def cmd_create_dpack(output_dir: str = ".") -> int:
    """..."""
    from dlab.create_dpack_wizard import CreateDpackApp

    app_wiz: CreateDpackApp = CreateDpackApp(output_dir)
    app_wiz.run()
    return 0


if __name__ == "__main__":
    app()
