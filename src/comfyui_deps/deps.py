"""Python dependency management module."""

import os
import re
import subprocess
from typing import List, Optional, Tuple


def _run_pip(
    python_exe: str,
    args: list,
    timeout: int = 120,
) -> Tuple[int, str, str]:
    proc = subprocess.run(
        [python_exe, "-m", "pip"] + args,
        capture_output=True,
        text=True,
        timeout=timeout,
        encoding="utf-8",
        errors="replace",
    )
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def resolve_python_exe(config_python_exe: str, python_home: str) -> str:
    if config_python_exe and os.path.isfile(config_python_exe):
        return config_python_exe
    if python_home:
        candidate = os.path.join(python_home, "python.exe" if os.name == "nt" else "python3")
        if os.path.isfile(candidate):
            return candidate
        candidate = os.path.join(python_home, "python")
        if os.path.isfile(candidate):
            return candidate
        candidate = os.path.join(python_home, "Python", "python.exe" if os.name == "nt" else "python3")
        if os.path.isfile(candidate):
            return candidate
        candidate = os.path.join(python_home, "Python", "python")
        if os.path.isfile(candidate):
            return candidate
    import shutil
    py = shutil.which("python3") or shutil.which("python")
    if py:
        return py
    raise FileNotFoundError("Cannot resolve python executable path")


def install_requirements(
    python_exe: str,
    requirements_path: str,
    dry_run: bool = False,
    strategy: str = "only-if-needed",
) -> Tuple[bool, str]:
    if not os.path.isfile(requirements_path):
        return False, f"Requirements file not found: {requirements_path}"
    args = ["install", "-r", requirements_path, "--upgrade-strategy", strategy]
    if dry_run:
        args.append("--dry-run")
    code, stdout, stderr = _run_pip(python_exe, args)
    if code != 0:
        return False, stderr or stdout or "pip install failed"
    return True, stdout


def install_package(
    python_exe: str,
    package: str,
    dry_run: bool = False,
    strategy: str = "only-if-needed",
) -> Tuple[bool, str]:
    args = ["install", package, "--upgrade-strategy", strategy]
    if dry_run:
        args.append("--dry-run")
    code, stdout, stderr = _run_pip(python_exe, args)
    if code != 0:
        return False, stderr or stdout or "pip install failed"
    return True, stdout


def detect_core_lib_conflicts(
    dry_run_output: str, core_libs: List[str]
) -> List[str]:
    conflicts: List[str] = []
    lines = dry_run_output.splitlines()
    install_section = False
    for line in lines:
        line = line.strip()
        if "Would install" in line or "Will install" in line:
            install_section = True
        if not install_section:
            continue
        for lib in core_libs:
            lib_lower = lib.lower()
            if lib_lower in line.lower() or re.search(
                rf"\b{re.escape(lib_lower)}\b", line.lower()
            ):
                if line not in conflicts:
                    conflicts.append(line)
    return conflicts


def restore_from_snapshot(
    python_exe: str,
    snapshot_path: str,
    force: bool = False,
    dry_run: bool = False,
) -> Tuple[bool, str]:
    if not os.path.isfile(snapshot_path):
        return False, f"Snapshot file not found: {snapshot_path}"

    args = ["install", "-r", snapshot_path, "--upgrade-strategy", "only-if-needed"]
    if dry_run:
        args.append("--dry-run")
    if force:
        args.append("--force-reinstall")

    code, stdout, stderr = _run_pip(python_exe, args, timeout=300)
    if code != 0:
        return False, stderr or stdout or "pip restore failed"
    return True, stdout
