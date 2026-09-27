"""First-run setup for the Pelumi fork: pin a project, wire local clients, and prepare HTTP MCP."""

from __future__ import annotations

import json
import secrets
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import typer

from basic_memory.cli.app import app
from basic_memory.config import ConfigManager, ProjectEntry, ProjectMode
from basic_memory.utils import shell_command

DEFAULT_PROJECT_NAME = "main"
DEFAULT_PROJECT_DIR = Path.home() / "Documents" / "AI Memory"


@dataclass(frozen=True, slots=True)
class SetupPlan:
    """Files and config mutations ``bm setup`` will apply."""

    project_name: str
    project_path: Path
    binary: Path
    shared_token: str
    client_tokens: dict[str, str]
    mcp_port: int
    config_dir: Path
    cursor_routing: Path
    codex_routing: Path
    cursor_mcp: Path
    launchd_label: str


def default_project_path() -> Path:
    """Prefer the user's Documents vault when that folder exists or can be created."""
    documents = Path.home() / "Documents" / "AI Memory"
    legacy = Path.home() / "basic-memory"
    if documents.exists():
        return documents
    if legacy.exists():
        return legacy
    return documents


def resolve_cli_binary(explicit: Path | None) -> Path:
    """Return an absolute path to the Basic Memory CLI used in hook and MCP configs."""
    if explicit is not None:
        resolved = explicit.expanduser().resolve()
        if not resolved.is_file():
            raise ValueError(f"CLI binary not found: {resolved}")
        return resolved
    argv0 = Path(sys.argv[0]).resolve()
    if argv0.is_file() and argv0.name in {"basic-memory", "bm", "python", "python3"}:
        if argv0.name in {"basic-memory", "bm"}:
            return argv0
    for candidate in ("basic-memory", "bm"):
        found = shutil.which(candidate)
        if found:
            return Path(found).resolve()
    raise ValueError(
        "Could not find basic-memory on PATH. Pass --binary with the absolute path "
        "to your fork install (for example ~/.local/bin/basic-memory)."
    )


def _new_token() -> str:
    return secrets.token_urlsafe(32)


def build_setup_plan(
    *,
    project_name: str,
    project_path: Path,
    binary: Path,
    mcp_port: int,
    config_dir: Path,
) -> SetupPlan:
    shared = _new_token()
    clients = {
        "cursor": _new_token(),
        "claude-code": _new_token(),
        "codex": _new_token(),
    }
    return SetupPlan(
        project_name=project_name,
        project_path=project_path,
        binary=binary,
        shared_token=shared,
        client_tokens=clients,
        mcp_port=mcp_port,
        config_dir=config_dir,
        cursor_routing=Path.home() / ".cursor" / "basic-memory.json",
        codex_routing=Path.home() / ".codex" / "basic-memory.json",
        cursor_mcp=Path.home() / ".cursor" / "mcp.json",
        launchd_label="com.pelumi.basic-memory-mcp",
    )


def routing_document(primary_project: str) -> dict[str, Any]:
    return {"primaryProject": primary_project}


def mcp_stdio_entry(binary: Path) -> dict[str, Any]:
    return {
        "command": str(binary),
        "args": ["mcp"],
    }


def merge_mcp_servers(existing: dict[str, Any], entry: dict[str, Any]) -> dict[str, Any]:
    merged = dict(existing)
    servers = dict(merged.get("mcpServers", {}))
    servers["basic-memory"] = entry
    merged["mcpServers"] = servers
    return merged


def load_json_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def write_json_object(path: Path, payload: dict[str, Any], *, dry_run: bool) -> None:
    if dry_run:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def apply_fork_config(
    manager: ConfigManager,
    plan: SetupPlan,
    *,
    dry_run: bool,
) -> None:
    config = manager.config.model_copy(deep=True)
    config.auto_update = False
    config.verify_writes = True
    config.mcp_http_host = "127.0.0.1"
    config.mcp_http_token = plan.shared_token
    config.mcp_http_client_tokens = dict(plan.client_tokens)
    config.default_project = plan.project_name
    project_path = plan.project_path.expanduser().resolve().as_posix()
    if plan.project_name not in config.projects:
        config.projects[plan.project_name] = ProjectEntry(
            path=project_path,
            mode=ProjectMode.LOCAL,
        )
    else:
        entry = config.projects[plan.project_name]
        if not entry.path:
            entry.path = project_path
        entry.mode = ProjectMode.LOCAL
    if not dry_run:
        plan.project_path.mkdir(parents=True, exist_ok=True)
        manager.save_config(config)


def launchd_plist(plan: SetupPlan) -> str:
    """Return a launchd unit that keeps the loopback HTTP MCP server running."""
    binary = plan.binary
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>{plan.launchd_label}</string>
  <key>ProgramArguments</key>
  <array>
    <string>{binary}</string>
    <string>mcp</string>
    <string>--transport</string>
    <string>streamable-http</string>
    <string>--port</string>
    <string>{plan.mcp_port}</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>{plan.config_dir / "mcp-http.log"}</string>
  <key>StandardErrorPath</key>
  <string>{plan.config_dir / "mcp-http.err"}</string>
</dict>
</plist>
"""


def describe_plan(plan: SetupPlan) -> str:
    lines = [
        f"Project: {plan.project_name} -> {plan.project_path}",
        f"CLI binary: {plan.binary}",
        "Config: auto_update=false, verify_writes=true, loopback HTTP tokens written to config.json",
        f"Cursor routing: {plan.cursor_routing}",
        f"Codex routing: {plan.codex_routing}",
        f"Cursor MCP (stdio): {plan.cursor_mcp}",
        f"HTTP MCP URL (after launchd): http://127.0.0.1:{plan.mcp_port}/mcp",
        "Per-client bearer tokens: cursor, claude-code, codex (see config.json)",
        f"Launchd unit label: {plan.launchd_label}",
    ]
    return "\n".join(lines)


def run_setup(
    *,
    project_name: str,
    project_path: Path,
    binary: Path | None,
    mcp_port: int,
    install_hooks: bool,
    dry_run: bool,
) -> SetupPlan:
    resolved_binary = resolve_cli_binary(binary)
    manager = ConfigManager()
    plan = build_setup_plan(
        project_name=project_name,
        project_path=project_path,
        binary=resolved_binary,
        mcp_port=mcp_port,
        config_dir=manager.config_dir,
    )
    apply_fork_config(manager, plan, dry_run=dry_run)

    routing = routing_document(plan.project_name)
    write_json_object(plan.cursor_routing, routing, dry_run=dry_run)
    write_json_object(plan.codex_routing, routing, dry_run=dry_run)

    cursor_mcp = merge_mcp_servers(
        load_json_object(plan.cursor_mcp) if plan.cursor_mcp.exists() else {},
        mcp_stdio_entry(plan.binary),
    )
    write_json_object(plan.cursor_mcp, cursor_mcp, dry_run=dry_run)

    if install_hooks and not dry_run:
        from basic_memory.cli.commands.hook import Harness
        from basic_memory.cli.commands.hook import install as install_hooks_cmd

        install_hooks_cmd(Harness.claude)
        install_hooks_cmd(Harness.codex)

    return plan


@app.command("setup")
def setup_command(
    project: str = typer.Option(
        DEFAULT_PROJECT_NAME,
        "--project",
        help="Project name to pin as the default memory vault",
    ),
    path: Path | None = typer.Option(
        None,
        "--path",
        help=f"Vault directory (default: {DEFAULT_PROJECT_DIR})",
    ),
    binary: Path | None = typer.Option(
        None,
        "--binary",
        help="Absolute path to the fork's basic-memory binary (recommended on macOS GUI apps)",
    ),
    port: int = typer.Option(8000, "--port", help="Loopback HTTP MCP port for launchd"),
    install_hooks: bool = typer.Option(
        True,
        "--install-hooks/--no-install-hooks",
        help="Install Claude and Codex user-level lifecycle hooks",
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print the plan without writing files"),
    yes: bool = typer.Option(False, "--yes", help="Apply without confirmation"),
) -> None:
    """Pin a local vault, wire Cursor/Codex routing, and prepare loopback HTTP MCP tokens.

    This is the fork's one-shot bootstrap: it disables PyPI auto-update, turns on write
    verification, writes per-client HTTP bearer tokens, pins ``primaryProject`` for Cursor
    and Codex, merges a stdio MCP entry that uses an absolute CLI path, and prints a
    launchd unit you can install to keep ``basic-memory mcp --transport streamable-http``
    on loopback.
    """
    project_path = (path or default_project_path()).expanduser()
    try:
        plan = build_setup_plan(
            project_name=project,
            project_path=project_path,
            binary=resolve_cli_binary(binary),
            mcp_port=port,
            config_dir=ConfigManager().config_dir,
        )
    except ValueError as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(1)

    typer.echo(describe_plan(plan))
    if dry_run:
        typer.echo("\n(dry run — no files written)")
        return
    if not yes and not typer.confirm("Apply this setup plan?", default=False):
        raise typer.Abort()

    try:
        plan = run_setup(
            project_name=project,
            project_path=project_path,
            binary=binary,
            mcp_port=port,
            install_hooks=install_hooks,
            dry_run=False,
        )
    except ValueError as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(1)

    plist_path = plan.config_dir / "basic-memory-mcp.plist"
    plist_path.write_text(launchd_plist(plan), encoding="utf-8")
    typer.echo("\nSetup complete.")
    typer.echo(f"Saved launchd template: {plist_path}")
    typer.echo(
        "Install on macOS with:\n"
        + shell_command(
            "cp",
            str(plist_path),
            f"~/Library/LaunchAgents/{plan.launchd_label}.plist",
        )
    )
    typer.echo(
        shell_command(
            "launchctl",
            "load",
            "-w",
            f"~/Library/LaunchAgents/{plan.launchd_label}.plist",
        )
    )
    typer.echo(
        "\nPoint HTTP clients at the loopback URL and send the matching bearer token "
        "(see `bm config get mcp_http_client_tokens`)."
    )
