"""Rollback module for recovering from failed updates."""

import os
import shutil
from datetime import datetime
from typing import List, Optional, Tuple

from .deps import resolve_python_exe, restore_from_snapshot
from .models import Config, BackupEntry


def rollback_directory(target_path: str, backup_path: str) -> bool:
    if not os.path.isdir(backup_path):
        return False
    if not os.path.exists(target_path):
        return False

    target_parent = os.path.dirname(target_path.rstrip(os.sep))
    target_name = os.path.basename(target_path.rstrip(os.sep))
    date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    failed_name = f"{target_name}_failed_{date_str}"
    failed_path = os.path.join(target_parent, failed_name)

    counter = 1
    while os.path.exists(failed_path):
        failed_name = f"{target_name}_failed_{date_str}_{counter}"
        failed_path = os.path.join(target_parent, failed_name)
        counter += 1

    os.rename(target_path, failed_path)
    os.rename(backup_path, target_path)

    return True


def rollback_dependencies(
    config: Config, snapshot_path: str, force: bool = False
) -> Tuple[bool, str]:
    python_exe = resolve_python_exe(config.python_exe or "", config.python_home)
    return restore_from_snapshot(python_exe, snapshot_path, force=force)
