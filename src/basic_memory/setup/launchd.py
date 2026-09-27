"""Install and remove the loopback MCP launchd agent on macOS."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from basic_memory.setup.paths import launch_agents_dir


def launchd_plist_content(binary: Path, port: int, label: str, log_dir: Path) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>{label}</string>
  <key>ProgramArguments</key>
  <array>
    <string>{binary}</string>
    <string>mcp</string>
    <string>--transport</string>
    <string>streamable-http</string>
    <string>--port</string>
    <string>{port}</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>{log_dir / "mcp-http.log"}</string>
  <key>StandardErrorPath</key>
  <string>{log_dir / "mcp-http.err"}</string>
</dict>
</plist>
"""


def install_launchd(
    *,
    label: str,
    plist_body: str,
    template_path: Path,
) -> str | None:
    """Write plist template, copy to LaunchAgents, and bootstrap. Returns installed plist path."""
    template_path.parent.mkdir(parents=True, exist_ok=True)
    template_path.write_text(plist_body, encoding="utf-8")
    if sys.platform != "darwin":
        return None
    agents = launch_agents_dir()
    agents.mkdir(parents=True, exist_ok=True)
    dest = agents / f"{label}.plist"
    shutil.copy2(template_path, dest)
    subprocess.run(
        ["launchctl", "bootout", f"gui/{_gui_uid()}", str(dest)],
        capture_output=True,
        check=False,
    )
    subprocess.run(
        ["launchctl", "bootstrap", f"gui/{_gui_uid()}", str(dest)],
        check=True,
    )
    return str(dest)


def uninstall_launchd(label: str, installed_plist: str | None) -> None:
    if sys.platform != "darwin":
        return
    path = Path(installed_plist) if installed_plist else launch_agents_dir() / f"{label}.plist"
    subprocess.run(
        ["launchctl", "bootout", f"gui/{_gui_uid()}", str(path)],
        capture_output=True,
        check=False,
    )
    path.unlink(missing_ok=True)


def _gui_uid() -> int:
    import os

    return os.getuid()
