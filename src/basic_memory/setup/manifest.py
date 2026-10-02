"""Persisted record of what ``bm setup`` changed (for idempotent uninstall)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from basic_memory.config_models import _secure_config_file

MANIFEST_VERSION = 1
MANIFEST_NAME = "fork-setup-manifest.json"
BACKUP_DIR_NAME = "fork-setup-backups"


@dataclass(slots=True)
class FileRecord:
    path: str
    backup: str | None


@dataclass(slots=True)
class SetupManifest:
    version: int
    launchd_label: str
    launchd_plist_installed: str | None
    files: list[FileRecord] = field(default_factory=list)
    session_capture_enabled: bool = False

    @classmethod
    def empty(cls, launchd_label: str) -> SetupManifest:
        return cls(
            version=MANIFEST_VERSION, launchd_label=launchd_label, launchd_plist_installed=None
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "launchd_label": self.launchd_label,
            "launchd_plist_installed": self.launchd_plist_installed,
            "session_capture_enabled": self.session_capture_enabled,
            "files": [{"path": item.path, "backup": item.backup} for item in self.files],
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> SetupManifest:
        files = [
            FileRecord(path=str(item["path"]), backup=item.get("backup"))
            for item in data.get("files", [])
            if isinstance(item, dict) and "path" in item
        ]
        return cls(
            version=int(data.get("version", MANIFEST_VERSION)),
            launchd_label=str(data.get("launchd_label", "com.pelumi.basic-memory-mcp")),
            launchd_plist_installed=data.get("launchd_plist_installed"),
            files=files,
            session_capture_enabled=bool(data.get("session_capture_enabled", False)),
        )


def manifest_path(config_dir: Path) -> Path:
    return config_dir / MANIFEST_NAME


def backup_dir(config_dir: Path) -> Path:
    return config_dir / BACKUP_DIR_NAME


def load_manifest(config_dir: Path) -> SetupManifest | None:
    path = manifest_path(config_dir)
    if not path.is_file():
        return None
    return SetupManifest.from_json(json.loads(path.read_text(encoding="utf-8")))


def save_manifest(config_dir: Path, manifest: SetupManifest) -> None:
    path = manifest_path(config_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(manifest.to_json(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    _secure_config_file(path)
