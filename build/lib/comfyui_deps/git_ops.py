"""Git operation module for ComfyUI updates."""

import os
import subprocess
from typing import Optional, Tuple


def find_git_exe(config_git_exe: str) -> str:
    if config_git_exe and config_git_exe != "git":
        if os.path.isfile(config_git_exe):
            return config_git_exe
    return "git"


def _run_git(
    path: str,
    args: list,
    git_exe: Optional[str] = None,
    timeout: int = 60,
) -> Tuple[int, str, str]:
    exe = find_git_exe(git_exe or "")
    cmd = [exe] + args
    proc = subprocess.run(
        cmd,
        cwd=path,
        capture_output=True,
        text=True,
        timeout=timeout,
        encoding="utf-8",
        errors="replace",
    )
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def fetch_origin(path: str, git_exe: Optional[str] = None) -> Tuple[bool, str]:
    code, stdout, stderr = _run_git(path, ["fetch", "origin"], git_exe)
    if code != 0:
        return False, stderr or stdout or "git fetch failed"
    return True, stdout


def list_remote_branches(path: str, git_exe: Optional[str] = None) -> Tuple[bool, list]:
    code, stdout, stderr = _run_git(path, ["branch", "-r"], git_exe)
    if code != 0:
        return False, []
    heads = []
    for line in stdout.splitlines():
        line = line.strip()
        if " -> " in line:
            continue
        if line.startswith("origin/"):
            branch = line[len("origin/"):]
            if branch not in ("HEAD",):
                heads.append(branch)
    return True, heads


def detect_remote_branch(path: str, git_exe: Optional[str] = None) -> Tuple[bool, str]:
    code, stdout, stderr = _run_git(path, ["branch", "-r"], git_exe)
    if code != 0:
        return False, stderr or "Failed to list remote branches"

    heads = []
    for line in stdout.splitlines():
        line = line.strip()
        if " -> " in line:
            continue
        if line.startswith("origin/"):
            branch = line[len("origin/"):]
            if branch not in ("HEAD",):
                heads.append(branch)

    if not heads:
        return False, "No remote branches found"

    if "main" in heads:
        return True, "main"
    if "master" in heads:
        return True, "master"
    return True, heads[0]


def check_updates(
    path: str,
    branch: str = "main",
    oneline: bool = True,
    git_exe: Optional[str] = None,
) -> Tuple[bool, str]:
    fmt = "--oneline" if oneline else "--stat"
    args = ["log", f"HEAD..origin/{branch}", fmt]
    code, stdout, stderr = _run_git(path, args, git_exe)
    if code != 0:
        err_msg = stderr or stdout or "git log failed"
        if "unknown revision" in err_msg.lower():
            err_msg = (
                f"Remote branch 'origin/{branch}' not found. "
                "Run 'git fetch origin' first or check branch name."
            )
        return False, err_msg
    if not stdout:
        return True, "Already up to date."
    return True, stdout


def pull_updates(
    path: str,
    branch: str = "main",
    git_exe: Optional[str] = None,
) -> Tuple[bool, str]:
    args = ["pull", "origin", branch]
    code, stdout, stderr = _run_git(path, args, git_exe, timeout=120)
    if code != 0:
        return False, stderr or stdout or "git pull failed"
    return True, stdout


def has_git(path: str) -> bool:
    dot_git = os.path.join(path, ".git")
    return os.path.isdir(dot_git)
