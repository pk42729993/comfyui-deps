"""Update orchestration module."""

import os
import sys
from datetime import datetime
from typing import List

from colorama import Fore, Style, init as colorama_init

from .backup import backup_directory, backup_pip_freeze
from .deps import (
    detect_core_lib_conflicts,
    install_requirements,
    resolve_python_exe,
)
from .git_ops import (
    check_updates,
    detect_remote_branch,
    fetch_origin,
    has_git,
    pull_updates,
)
from .models import Config

colorama_init(autoreset=True)


def _cprint(msg: str, color: str = "", bold: bool = False) -> None:
    prefix = ""
    if bold:
        prefix += Style.BRIGHT
    prefix += {"red": Fore.RED, "green": Fore.GREEN, "yellow": Fore.YELLOW,
                "cyan": Fore.CYAN, "white": Fore.WHITE}.get(color, "")
    print(f"{prefix}{msg}")


def _confirm(msg: str, auto_yes: bool = False) -> bool:
    if auto_yes:
        return True
    resp = input(f"{msg} [y/N]: ").strip().lower()
    return resp in ("y", "yes")


def update_target(
    config: Config,
    target_path: str,
    target_name: str = "",
    skip_backup: bool = False,
    skip_deps: bool = False,
    auto_confirm: bool = False,
) -> bool:
    if not target_name:
        target_name = os.path.basename(target_path.rstrip(os.sep))

    if not os.path.isdir(target_path):
        _cprint(f"Error: Target directory not found: {target_path}", "red")
        return False

    is_git = has_git(target_path)

    _cprint(f"\nUpdating: {target_name}", "cyan", bold=True)
    _cprint(f"  Path: {target_path}", "white")
    _cprint(f"  Type: {'Git' if is_git else 'Non-Git (ZIP)'}", "white")

    if not is_git:
        _cprint("  Non-Git projects require manual ZIP download.", "yellow")
        _cprint("  1. Download latest ZIP from the official repository", "white")
        _cprint("  2. Backup configuration files", "white")
        _cprint("  3. Extract ZIP and replace source files", "white")
        _cprint("  4. Run 'comfyui-deps deps install --target <name>' to install dependencies", "white")
        return False

    git_exe = config.git_exe if config.git_exe else None

    _cprint("\n[1/4] Checking for updates...", "cyan")
    ok, branch = detect_remote_branch(target_path, git_exe)
    if not ok:
        _cprint(f"  Error: {branch}", "red")
        return False

    fetch_origin(target_path, git_exe)
    ok, log_output = check_updates(target_path, branch, oneline=True, git_exe=git_exe)
    if not ok:
        _cprint(f"  Error: {log_output}", "red")
        return False

    if "Already up to date" in log_output:
        _cprint(f"  {log_output}", "green")
        return True

    _cprint("  Changes available:", "yellow")
    for line in log_output.splitlines():
        _cprint(f"    {line}", "white")

    if not _confirm("Proceed with update?", auto_confirm):
        _cprint("Update cancelled.", "yellow")
        return False

    if not skip_backup:
        _cprint("\n[2/4] Creating backup...", "cyan")
        if not config.backup_dir:
            config.backup_dir = os.path.join(
                os.path.dirname(config.custom_nodes.rstrip(os.sep)), "backups"
            )
        try:
            backup_path = backup_directory(target_path, config.backup_dir)
            _cprint(f"  Backup: {backup_path}", "green")
        except Exception as e:
            _cprint(f"  Backup failed: {e}", "red")
            if not _confirm("Continue without backup?", auto_confirm):
                return False

        if config.python_home or config.python_exe:
            try:
                python_exe = resolve_python_exe(config.python_exe or "", config.python_home)
                snapshot = backup_pip_freeze(python_exe, config.backup_dir)
                _cprint(f"  Pip snapshot: {snapshot}", "green")
            except Exception as e:
                _cprint(f"  Pip snapshot skipped: {e}", "yellow")
    else:
        _cprint("\n[2/4] Backup skipped.", "yellow")

    _cprint("\n[3/4] Pulling updates...", "cyan")
    ok, pull_result = pull_updates(target_path, branch, git_exe)
    if not ok:
        _cprint(f"  Error: {pull_result}", "red")
        _cprint("  Use 'comfyui-deps rollback' to restore from backup.", "yellow")
        return False
    _cprint(f"  {pull_result}", "green")

    if skip_deps:
        _cprint("\n[4/4] Dependencies skipped.", "yellow")
    else:
        req_file = os.path.join(target_path, "requirements.txt")
        if os.path.isfile(req_file):
            _cprint("\n[4/4] Installing dependencies...", "cyan")
            python_exe = resolve_python_exe(config.python_exe or "", config.python_home)

            ok, dry_result = install_requirements(
                python_exe, req_file, dry_run=True
            )
            if ok:
                conflicts = detect_core_lib_conflicts(dry_result, config.core_libs)
                if conflicts:
                    _cprint("  Core library conflicts detected:", "yellow")
                    for c in conflicts:
                        _cprint(f"    {c}", "yellow")
                    if not _confirm("Core libraries may be affected. Proceed anyway?", auto_confirm):
                        _cprint("Dependency installation skipped.", "yellow")
                        _cprint("Update complete.", "green")
                        return True

                ok, install_result = install_requirements(python_exe, req_file)
                if ok:
                    _cprint(f"  {install_result[:200]}", "green")
                else:
                    _cprint(f"  Install error: {install_result}", "red")
            else:
                _cprint(f"  Dry-run error: {dry_result}", "yellow")
                if _confirm("Dry-run failed. Force install?", auto_confirm):
                    ok, install_result = install_requirements(python_exe, req_file)
                    if ok:
                        _cprint(f"  {install_result[:200]}", "green")
                    else:
                        _cprint(f"  Install error: {install_result}", "red")
        else:
            _cprint(f"\n[4/4] No requirements.txt found.", "yellow")
            _cprint("  If ComfyUI reports ModuleNotFoundError, use:", "white")
            _cprint("    comfyui-deps deps add <package_name>", "white")

    _cprint("\nUpdate complete.", "green", bold=True)
    return True
