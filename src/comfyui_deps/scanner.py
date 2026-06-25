"""Plugin scanning module for batch update checks."""

import os
import re
from typing import List, Optional

from .git_ops import check_updates, detect_remote_branch, fetch_origin, has_git
from .models import Config, PluginStatus


def list_plugins(config: Config) -> List[str]:
    """Fast listing of plugin directory names without any git operations."""
    plugins: List[str] = []

    if not config.custom_nodes or not os.path.isdir(config.custom_nodes):
        return plugins

    with os.scandir(config.custom_nodes) as it:
        for entry in sorted(it, key=lambda e: e.name.lower()):
            if not entry.is_dir():
                continue
            if entry.name.startswith(".") or entry.name.startswith("_"):
                continue
            plugins.append(entry.name)

    return plugins


def scan_all_plugins(config: Config) -> List[PluginStatus]:
    results: List[PluginStatus] = []

    if not config.custom_nodes or not os.path.isdir(config.custom_nodes):
        return results

    git_exe = config.git_exe if config.git_exe else None

    with os.scandir(config.custom_nodes) as it:
        for entry in sorted(it, key=lambda e: e.name.lower()):
            if not entry.is_dir():
                continue
            if entry.name.startswith(".") or entry.name.startswith("_"):
                continue

            status = _scan_single(entry.path, entry.name, git_exe)
            results.append(status)

    return results


def scan_plugins(config: Config, names: List[str]) -> List[PluginStatus]:
    """Scan only the specified plugins by name for update status."""
    results: List[PluginStatus] = []
    git_exe = config.git_exe if config.git_exe else None

    for name in names:
        path = os.path.join(config.custom_nodes, name)
        if not os.path.isdir(path):
            continue
        status = _scan_single(path, name, git_exe)
        results.append(status)

    return results


def _scan_single(
    path: str, name: str, git_exe: Optional[str] = None
) -> PluginStatus:
    if not has_git(path):
        return PluginStatus(
            name=name,
            path=path,
            has_git=False,
            has_updates=False,
            commit_count=0,
            remote_branch="",
        )

    try:
        fetch_origin(path, git_exe)
    except Exception:
        return PluginStatus(
            name=name,
            path=path,
            has_git=True,
            has_updates=False,
            commit_count=0,
            remote_branch="",
            error="git fetch failed",
        )

    ok, branch = detect_remote_branch(path, git_exe)
    if not ok:
        return PluginStatus(
            name=name,
            path=path,
            has_git=True,
            has_updates=False,
            commit_count=0,
            remote_branch="",
            error=branch,
        )

    ok, log_output = check_updates(path, branch, oneline=True, git_exe=git_exe)
    if not ok:
        return PluginStatus(
            name=name,
            path=path,
            has_git=True,
            has_updates=False,
            commit_count=0,
            remote_branch=branch,
            error=log_output,
        )

    if "Already up to date" in log_output:
        return PluginStatus(
            name=name,
            path=path,
            has_git=True,
            has_updates=False,
            commit_count=0,
            remote_branch=branch,
        )

    lines = [l for l in log_output.splitlines() if l.strip()]
    count = len(lines)
    return PluginStatus(
        name=name,
        path=path,
        has_git=True,
        has_updates=True,
        commit_count=count,
        remote_branch=branch,
    )
