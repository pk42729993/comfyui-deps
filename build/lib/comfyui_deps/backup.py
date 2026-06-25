"""Backup management module."""

import os
import re
import shutil
import subprocess
from datetime import datetime
from typing import List, Optional, Tuple

from .models import BackupEntry

_BACKUP_PATTERN = re.compile(r"^(.+)_backup_(\d{8})(?:_\d+)?$")


def backup_directory(target_path: str, backup_parent: str) -> str:
    if not os.path.isdir(target_path):
        raise FileNotFoundError(f"Target directory not found: {target_path}")

    target_name = os.path.basename(target_path.rstrip(os.sep))
    date_str = datetime.now().strftime("%Y%m%d")
    backup_name = f"{target_name}_backup_{date_str}"
    backup_path = os.path.join(backup_parent, "mulu", backup_name)

    counter = 1
    while os.path.exists(backup_path):
        backup_name = f"{target_name}_backup_{date_str}_{counter}"
        backup_path = os.path.join(backup_parent, "mulu", backup_name)
        counter += 1

    os.makedirs(os.path.join(backup_parent, "mulu"), exist_ok=True)
    shutil.copytree(target_path, backup_path, symlinks=False, dirs_exist_ok=True)
    return backup_path


def backup_pip_freeze(python_exe: str, output_dir: str) -> str:
    if not os.path.isfile(python_exe):
        raise FileNotFoundError(f"Python executable not found: {python_exe}")

    date_str = datetime.now().strftime("%Y%m%d")
    filename = f"requirements-backup{date_str}.txt"
    filepath = os.path.join(output_dir, "yilai", filename)

    counter = 1
    while os.path.exists(filepath):
        filename = f"requirements-backup{date_str}_{counter}.txt"
        filepath = os.path.join(output_dir, "yilai", filename)
        counter += 1

    os.makedirs(os.path.join(output_dir, "yilai"), exist_ok=True)
    proc = subprocess.run(
        [python_exe, "-m", "pip", "freeze"],
        capture_output=True,
        text=True,
        timeout=60,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        raise RuntimeError(f"pip freeze failed: {proc.stderr}")

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(proc.stdout)
    return filepath


def list_backups(target_name: str, backup_parent: str) -> List[BackupEntry]:
    mulu_dir = os.path.join(backup_parent, "mulu")
    if not os.path.isdir(mulu_dir):
        return []

    entries: List[BackupEntry] = []
    with os.scandir(mulu_dir) as it:
        for entry in it:
            if not entry.is_dir():
                continue
            match = _BACKUP_PATTERN.match(entry.name)
            if not match:
                continue
            if match.group(1) != target_name:
                continue
            stat = entry.stat()
            entries.append(BackupEntry(
                name=entry.name,
                path=entry.path,
                target_name=target_name,
                timestamp=match.group(2),
                created=datetime.fromtimestamp(stat.st_ctime),
            ))

    entries.sort(key=lambda e: e.created, reverse=True)
    return entries


def _remove_readonly_onerror(func, path, exc_info):
    import stat
    os.chmod(path, stat.S_IWRITE)
    func(path)


def clean_old_backups(
    target_name: str, backup_parent: str, keep: int
) -> int:
    entries = list_backups(target_name, backup_parent)
    if len(entries) <= keep:
        return 0

    deleted = 0
    for entry in entries[keep:]:
        shutil.rmtree(entry.path, ignore_errors=False, onerror=_remove_readonly_onerror)
        deleted += 1

    return deleted
