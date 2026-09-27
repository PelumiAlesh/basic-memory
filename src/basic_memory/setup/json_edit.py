"""JSON file helpers with pre-edit backups."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Callable

from basic_memory.setup.manifest import FileRecord, SetupManifest, backup_dir


def load_json_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def backup_file(path: Path, config_dir: Path) -> str | None:
    if not path.exists():
        return None
    dest_root = backup_dir(config_dir)
    dest_root.mkdir(parents=True, exist_ok=True)
    safe_name = str(path).replace("/", "_").replace("\\", "_").lstrip("_")
    backup_path = dest_root / safe_name
    shutil.copy2(path, backup_path)
    return str(backup_path)


def upsert_file(
    manifest: SetupManifest,
    config_dir: Path,
    path: Path,
    transform: Callable[[dict[str, Any]], dict[str, Any]],
    *,
    dry_run: bool,
) -> bool:
    """Apply ``transform`` to a JSON object file; backup on first touch. Returns whether content changed."""
    before = load_json_object(path) if path.exists() else {}
    after = transform(dict(before))
    if before == after and path.exists():
        return False
    if dry_run:
        return True
    existing = next((item for item in manifest.files if item.path == str(path)), None)
    if existing is None and path.exists():
        backup = backup_file(path, config_dir)
        manifest.files.append(FileRecord(path=str(path), backup=backup))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(after, indent=2) + "\n", encoding="utf-8")
    return True


def restore_manifest_files(manifest: SetupManifest) -> None:
    for record in manifest.files:
        target = Path(record.path)
        if record.backup:
            backup = Path(record.backup)
            if backup.is_file():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(backup, target)
                continue
        if target.is_file():
            target.unlink()
