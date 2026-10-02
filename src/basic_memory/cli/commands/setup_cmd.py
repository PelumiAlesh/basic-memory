"""First-run setup for the Pelumi fork: pin a project, wire local clients, and prepare HTTP MCP."""

from __future__ import annotations

import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import typer

from basic_memory.cli.app import app
from basic_memory.cli.commands.hook import _hook_launcher
from basic_memory.config import ConfigManager, ProjectEntry, ProjectMode
from basic_memory.config_models import CONFIG_FILE_NAME, resolve_data_dir
from basic_memory.setup import json_edit, launchd, manifest, paths, tokens
from basic_memory.setup.cursor_rule import cursor_brief_rule_file, cursor_rule_install_notice
from basic_memory.setup.hooks import (
    install_claude_hooks,
    install_cursor_hooks,
    remove_claude_hooks,
    remove_cursor_hooks,
)

DEFAULT_PROJECT_NAME = "main"
LAUNCHD_LABEL = "com.pelumi.basic-memory-mcp"


@dataclass(frozen=True, slots=True)
class SetupPlan:
    project_name: str
    project_path: Path
    binary: Path
    mcp_port: int
    config_dir: Path
    session_capture: bool
    install_launchd: bool
    brief_inject: bool = False


def resolve_cli_binary(explicit: Path | None) -> Path:
    if explicit is not None:
        resolved = explicit.expanduser().resolve()
        if not resolved.is_file():
            raise ValueError(f"CLI binary not found: {resolved}")
        return resolved
    argv0 = Path(sys.argv[0]).resolve()
    if argv0.is_file() and argv0.name in {"basic-memory", "bm"}:
        return argv0
    for candidate in ("basic-memory", "bm"):
        found = shutil.which(candidate)
        if found:
            return Path(found).resolve()
    raise ValueError(
        "Could not find basic-memory on PATH. Pass --binary with the absolute path "
        "to your fork install (for example ~/.local/bin/basic-memory)."
    )


def mcp_stdio_entry(binary: Path) -> dict[str, Any]:
    # Promo analytics reads BASIC_MEMORY_NO_PROMOS. BASIC_MEMORY_FORCE_LOCAL
    # keeps stdio on the in-process API even when a cloud key or a cloud-mode
    # project is still in config. A shell the owner starts later does not inherit these.
    return {
        "command": str(binary),
        "args": ["mcp"],
        "env": {"BASIC_MEMORY_NO_PROMOS": "1", "BASIC_MEMORY_FORCE_LOCAL": "1"},
    }


def cloud_setup_blockers(config: Any) -> list[str]:
    """Reasons setup must stop because a call could leave this Mac.

    The named project is forced local later. That does not clear a cloud API
    key, saved OAuth tokens, a default workspace, or another project's cloud mode.
    An unknown project name is routed to the cloud while any of those exist.
    """
    from basic_memory.cli.auth import CLIAuth

    reasons: list[str] = []
    if getattr(config, "cloud_api_key", None):
        reasons.append("a cloud API key is saved (cloud_api_key)")
    if getattr(config, "default_workspace", None):
        reasons.append("a default cloud workspace is set (default_workspace)")
    auth = CLIAuth(client_id=config.cloud_client_id, authkit_domain=config.cloud_domain)
    if auth.load_tokens() is not None:
        reasons.append("cloud OAuth tokens are saved")
    for name, entry in config.projects.items():
        if entry.mode == ProjectMode.CLOUD:
            reasons.append(f"project {name!r} is in cloud mode")
    return reasons


def refuse_cloud_setup(config: Any) -> None:
    reasons = cloud_setup_blockers(config)
    if not reasons:
        return
    detail = "\n- ".join(reasons)
    raise ValueError(
        "Refusing setup while cloud access is configured. "
        "Memory stays on this Mac only when nothing here can route a call to the cloud.\n"
        f"- {detail}"
    )


def routing_document(primary_project: str) -> dict[str, Any]:
    return {"primaryProject": primary_project}


def merge_mcp_servers(existing: dict[str, Any], entry: dict[str, Any]) -> dict[str, Any]:
    merged = dict(existing)
    servers = dict(merged.get("mcpServers", {}))
    servers["basic-memory"] = entry
    merged["mcpServers"] = servers
    return merged


def describe_plan(plan: SetupPlan) -> str:
    return "\n".join(
        [
            f"Project: {plan.project_name} -> {plan.project_path}",
            f"CLI binary: {plan.binary}",
            "Tokens: dedicated fork-mcp-tokens.json (reused on re-run, mode 0600)",
            f"Cursor MCP: {paths.cursor_mcp_path()}",
            f"Claude Desktop MCP: {paths.claude_desktop_mcp_path()}",
            f"Claude Code MCP: {paths.claude_code_mcp_path()} (user scope, not settings.json)",
            f"HTTP MCP URL: http://127.0.0.1:{plan.mcp_port}/mcp",
            f"Launchd: {'install' if plan.install_launchd else 'skip'} ({LAUNCHD_LABEL})",
            "Offline: BASIC_MEMORY_NO_PROMOS=1 and BASIC_MEMORY_FORCE_LOCAL=1 "
            "on every MCP entry and the launchd agent",
            "Logfire export: forced off (logfire_enabled and logfire_send_to_logfire)",
            f"Cursor rule file: {paths.cursor_user_rule_path()} (model-followed, not guaranteed)",
            f"Session capture: {'on' if plan.session_capture else 'off'}",
            f"Brief injection: {'on' if plan.brief_inject else 'off'}",
            "Hooks: brief hooks only with --brief; stop hooks only with --session-capture",
        ]
    )


def apply_config(
    manager: ConfigManager,
    plan: SetupPlan,
    fork_tokens: tokens.ForkTokens,
    *,
    dry_run: bool,
) -> None:
    config = manager.config.model_copy(deep=True)
    config.auto_update = False
    config.verify_writes = True
    # Trigger: setup is what launches the local MCP processes.
    # Why: Logfire export and the CLI cloud promo are the other network exits
    # that are on unless the owner opts out. Both flags already default off;
    # setup writes them off so a previous config cannot leave them on.
    # Outcome: uninstall restores the previous config.json, including these flags.
    config.logfire_enabled = False
    config.logfire_send_to_logfire = False
    config.cloud_promo_opt_out = True
    config.mcp_http_host = "127.0.0.1"
    config.mcp_http_token = fork_tokens.shared_token
    config.mcp_http_client_tokens = dict(fork_tokens.client_tokens)
    config.default_project = plan.project_name
    config.session_capture_enabled = plan.session_capture
    config.brief_inject_enabled = plan.brief_inject
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


def _backup_config_if_needed(
    setup_manifest: manifest.SetupManifest, config_file: Path, config_dir: Path
) -> None:
    if any(item.path == str(config_file) for item in setup_manifest.files):
        return
    if not config_file.is_file():
        return
    backup = json_edit.backup_file(config_file, config_dir)
    setup_manifest.files.append(manifest.FileRecord(path=str(config_file), backup=backup))


def run_setup(plan: SetupPlan, *, dry_run: bool) -> manifest.SetupManifest:
    config_file = plan.config_dir / CONFIG_FILE_NAME
    existing = manifest.load_manifest(plan.config_dir)
    setup_manifest = existing or manifest.SetupManifest.empty(LAUNCHD_LABEL)
    setup_manifest.session_capture_enabled = plan.session_capture
    # Trigger: this machine has no config.json yet.
    # Why: ConfigManager creates a default file on first read, which is not the
    # user's file. Recording the absence lets uninstall delete that file.
    # Outcome: a setup that created config.json removes it; an existing file is restored.
    if not dry_run and not config_file.exists():
        json_edit.remember_original(setup_manifest, plan.config_dir, config_file)

    manager = ConfigManager()
    # Trigger: any project is cloud-mode, or cloud credentials are saved.
    # Why: FORCE_LOCAL on the entries we write is not enough if setup still
    # finishes and leaves those credentials in place for another process.
    # Outcome: setup writes nothing else and tells the owner what to clear.
    refuse_cloud_setup(manager.config)
    fork_tokens = tokens.ensure_tokens(manager.config_dir)
    if not dry_run:
        _backup_config_if_needed(setup_manifest, manager.config_file, manager.config_dir)
    apply_config(manager, plan, fork_tokens, dry_run=dry_run)

    entry = mcp_stdio_entry(plan.binary)
    routing = routing_document(plan.project_name)

    json_edit.upsert_file(
        setup_manifest,
        manager.config_dir,
        paths.cursor_routing_path(),
        lambda data: {**data, **routing},
        dry_run=dry_run,
    )
    json_edit.upsert_file(
        setup_manifest,
        manager.config_dir,
        paths.codex_routing_path(),
        lambda data: {**data, **routing},
        dry_run=dry_run,
    )
    json_edit.upsert_file(
        setup_manifest,
        manager.config_dir,
        paths.cursor_mcp_path(),
        lambda data: merge_mcp_servers(data, entry),
        dry_run=dry_run,
    )
    json_edit.upsert_file(
        setup_manifest,
        manager.config_dir,
        paths.claude_desktop_mcp_path(),
        lambda data: merge_mcp_servers(data, entry),
        dry_run=dry_run,
    )
    json_edit.upsert_file(
        setup_manifest,
        manager.config_dir,
        paths.claude_code_mcp_path(),
        lambda data: merge_mcp_servers(data, entry),
        dry_run=dry_run,
    )

    if not dry_run:
        launcher = _hook_launcher()
        if plan.binary.is_file():
            launcher = str(plan.binary)
        json_edit.remember_original(setup_manifest, manager.config_dir, paths.cursor_hooks_path())
        json_edit.remember_original(
            setup_manifest, manager.config_dir, paths.claude_code_settings_path()
        )
        install_cursor_hooks(
            launcher,
            session_capture=plan.session_capture,
            brief_inject=plan.brief_inject,
        )
        install_claude_hooks(
            launcher,
            session_capture=plan.session_capture,
            brief_inject=plan.brief_inject,
        )

        rule_path = paths.cursor_user_rule_path()
        json_edit.remember_original(setup_manifest, manager.config_dir, rule_path)
        rule_path.parent.mkdir(parents=True, exist_ok=True)
        rule_path.write_text(
            cursor_brief_rule_file(
                float(manager.config.brief_refresh_hours),
                inject=plan.brief_inject,
            ),
            encoding="utf-8",
        )

        plist_body = launchd.launchd_plist_content(
            plan.binary, plan.mcp_port, LAUNCHD_LABEL, manager.config_dir
        )
        template = manager.config_dir / "basic-memory-mcp.plist"
        json_edit.remember_original(setup_manifest, manager.config_dir, template)
        if plan.install_launchd:
            installed = launchd.install_launchd(
                label=LAUNCHD_LABEL,
                plist_body=plist_body,
                template_path=template,
            )
            setup_manifest.launchd_plist_installed = installed
        else:
            template.write_text(plist_body, encoding="utf-8")

        manifest.save_manifest(manager.config_dir, setup_manifest)

    return setup_manifest


def run_uninstall() -> None:
    manager = ConfigManager()
    setup_manifest = manifest.load_manifest(manager.config_dir)
    if setup_manifest is None:
        typer.echo("No fork setup manifest found; nothing to uninstall.")
        raise typer.Exit(0)

    remove_cursor_hooks()
    remove_claude_hooks()
    launchd.uninstall_launchd(setup_manifest.launchd_label, setup_manifest.launchd_plist_installed)
    json_edit.restore_manifest_files(setup_manifest)
    manifest_path = manifest.manifest_path(manager.config_dir)
    manifest_path.unlink(missing_ok=True)
    tokens.token_file_path(manager.config_dir).unlink(missing_ok=True)
    typer.echo("Fork setup removed (backed-up files restored where available).")


@app.command("setup")
def setup_command(
    project: str = typer.Option(DEFAULT_PROJECT_NAME, "--project", help="Default project name"),
    path: Path | None = typer.Option(
        None,
        "--path",
        help=f"Vault directory (default: {paths.default_vault_path()})",
    ),
    binary: Path | None = typer.Option(None, "--binary", help="Absolute path to the fork CLI"),
    port: int = typer.Option(8000, "--port", help="Loopback HTTP MCP port"),
    session_capture: bool = typer.Option(
        False,
        "--session-capture",
        help="Enable local session capture hooks (off by default)",
    ),
    brief: bool = typer.Option(
        False,
        "--brief",
        help="Inject the memory brief into new Cursor chats and Claude Code prompts (off by default)",
    ),
    install_launchd: bool = typer.Option(
        True,
        "--launchd/--no-launchd",
        help="Install and bootstrap the loopback MCP launchd agent (macOS)",
    ),
    uninstall: bool = typer.Option(False, "--uninstall", help="Reverse fork setup changes"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print the plan without writing files"),
    yes: bool = typer.Option(False, "--yes", help="Apply without confirmation"),
) -> None:
    """Pin the fork vault, wire MCP clients, tokens, hooks, and loopback HTTP MCP."""
    if uninstall:
        run_uninstall()
        return

    project_path = (path or paths.default_vault_path()).expanduser()
    try:
        resolved_binary = resolve_cli_binary(binary)
    except ValueError as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(1)

    # Resolve the directory without loading config. The first ConfigManager()
    # call creates config.json, and a dry run must not do that.
    plan = SetupPlan(
        project_name=project,
        project_path=project_path,
        binary=resolved_binary,
        mcp_port=port,
        config_dir=resolve_data_dir(),
        session_capture=session_capture,
        install_launchd=install_launchd,
        brief_inject=brief,
    )
    config_file = plan.config_dir / CONFIG_FILE_NAME
    if config_file.is_file():
        try:
            refuse_cloud_setup(ConfigManager().config)
        except ValueError as error:
            typer.echo(f"Error: {error}", err=True)
            raise typer.Exit(1)
    typer.echo(describe_plan(plan))
    if dry_run:
        typer.echo("\n(dry run — no files written)")
        typer.echo(cursor_rule_install_notice(6.0, paths.cursor_user_rule_path(), inject=brief))
        return
    if not yes and not typer.confirm("Apply this setup plan?", default=False):
        raise typer.Abort()

    try:
        run_setup(plan, dry_run=False)
    except ValueError as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(1)

    typer.echo("\nSetup complete.")
    if brief:
        typer.echo(
            "Claude Code adds the brief on UserPromptSubmit, including a resumed session. "
            "Cursor sessionStart briefs a new chat only."
        )
    else:
        typer.echo("Brief injection is off. Re-run with --brief to put note text in host prompts.")
    hours = float(ConfigManager().config.brief_refresh_hours)
    typer.echo(cursor_rule_install_notice(hours, paths.cursor_user_rule_path(), inject=brief))
