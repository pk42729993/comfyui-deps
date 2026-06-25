"""Configuration management module."""

import json
import os
import sys
from pathlib import Path
from typing import List, Optional

import yaml

from .models import Config

CONFIG_DIR = str(Path.home() / ".comfyui-deps")
DEFAULT_CONFIG_NAME = "default"
CURRENT_NAME_FILE = "current.json"


def _get_config_path(name: str = "") -> str:
    if not name:
        name = _get_current_name()
    return os.path.join(CONFIG_DIR, f"config.{name}.yaml")


def _get_current_name() -> str:
    try:
        p = os.path.join(CONFIG_DIR, CURRENT_NAME_FILE)
        if os.path.isfile(p):
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("name", DEFAULT_CONFIG_NAME)
    except Exception:
        pass
    return DEFAULT_CONFIG_NAME


def _set_current_name(name: str) -> None:
    os.makedirs(CONFIG_DIR, exist_ok=True)
    p = os.path.join(CONFIG_DIR, CURRENT_NAME_FILE)
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"name": name}, f)


def list_configs() -> List[dict]:
    os.makedirs(CONFIG_DIR, exist_ok=True)
    current_name = _get_current_name()
    configs = []
    seen = set()
    for fname in sorted(os.listdir(CONFIG_DIR)):
        if not fname.startswith("config.") or not fname.endswith(".yaml"):
            continue
        name = fname[len("config."):-len(".yaml")]
        if name in seen:
            continue
        seen.add(name)
        try:
            with open(os.path.join(CONFIG_DIR, fname), "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except Exception:
            data = {}
        paths = data.get("paths", {})
        configs.append({
            "name": name,
            "active": name == current_name,
            "comfyui_root": paths.get("comfyui_root", ""),
            "custom_nodes": paths.get("custom_nodes", ""),
        })
    return configs


def switch_config(name: str) -> Config:
    _set_current_name(name)
    return load_config(name)


def create_config(name: str) -> Config:
    cfg = Config(name=name)
    save_config(cfg, name)
    return cfg


def delete_config(name: str) -> bool:
    p = _get_config_path(name)
    if os.path.isfile(p):
        os.remove(p)
        return True
    return False


def load_config(name: str = "") -> Config:
    path = _get_config_path(name)
    config_name = name or _get_current_name()
    if not os.path.isfile(path):
        if name:
            return Config(name=config_name)
        # 兼容旧 config.yaml
        old_path = os.path.join(CONFIG_DIR, "config.yaml")
        if os.path.isfile(old_path):
            with open(old_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            cfg = _build_config(data, config_name)
            save_config(cfg, config_name)
            return cfg
        return Config(name=config_name)
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return _build_config(data, config_name)


def _build_config(data: dict, config_name: str) -> Config:
    paths = data.get("paths", {})
    return Config(
        name=config_name,
        comfyui_root=paths.get("comfyui_root", ""),
        custom_nodes=paths.get("custom_nodes", ""),
        python_exe=paths.get("python_exe", ""),
        python_home=paths.get("python_home", ""),
        git_exe=paths.get("git_exe", ""),
        backup_dir=paths.get("backup_dir", ""),
        log_dir=paths.get("log_dir", ""),
        cache_dir=paths.get("cache_dir", ""),
        core_libs=data.get("core_libs", ["torch", "xformers", "onnxruntime"]),
    )


def save_config(config: Config, name: str = "") -> None:
    if not name:
        name = config.name or _get_current_name()
    path = _get_config_path(name)
    config.name = name
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    data = {
        "paths": {
            "comfyui_root": config.comfyui_root,
            "custom_nodes": config.custom_nodes,
            "python_exe": config.python_exe,
            "python_home": config.python_home,
            "git_exe": config.git_exe,
            "backup_dir": config.backup_dir,
            "log_dir": config.log_dir,
            "cache_dir": config.cache_dir,
        },
        "core_libs": config.core_libs,
    }
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


def _prompt(prompt_text: str, default: str = "") -> str:
    if default:
        text = input(f"{prompt_text} [{default}]: ")
    else:
        text = input(f"{prompt_text}: ")
    return text.strip() or default


def init_config_interactive() -> Config:
    print("=" * 60)
    print("  ComfyUI Dependency Manager - Configuration Setup")
    print("=" * 60)
    print()

    config = Config()

    config.comfyui_root = _prompt("ComfyUI root directory (e.g. G:\\Comfyui\\ComfyUI)")
    if config.comfyui_root:
        defaults_custom = os.path.join(config.comfyui_root, "custom_nodes")
    else:
        defaults_custom = ""
    config.custom_nodes = _prompt("Custom nodes (plugins) directory", defaults_custom)

    if config.custom_nodes:
        defaults_backup = os.path.join(os.path.dirname(config.custom_nodes.rstrip("\\/")), "backups")
    else:
        defaults_backup = ""
    config.backup_dir = _prompt("Backup storage directory", defaults_backup)

    detected_python = detect_python_exe()
    if detected_python:
        print(f"  Detected: {detected_python}")
    config.python_exe = _prompt("Python executable path (python.exe)", detected_python or "")

    if config.python_exe:
        defaults_pyhome = os.path.dirname(config.python_exe)
    else:
        defaults_pyhome = ""
    config.python_home = _prompt("Python installation directory (to locate python.exe)", defaults_pyhome)

    detected_git = detect_git_exe()
    if detected_git:
        print(f"  Detected: {detected_git}")
    config.git_exe = _prompt("Git executable path (git.exe)", detected_git or "git")

    defaults_log = config.comfyui_root if config.comfyui_root else ""
    config.log_dir = _prompt("ComfyUI log directory", defaults_log)

    print()
    print("Configuration complete. Saving...")
    save_config(config)

    return config


def validate_config(config: Config) -> List[str]:
    errors: List[str] = []

    if not config.comfyui_root:
        errors.append("comfyui_root is not set")
    elif not os.path.isdir(config.comfyui_root):
        errors.append(f"comfyui_root does not exist: {config.comfyui_root}")

    if not config.custom_nodes:
        errors.append("custom_nodes is not set")
    elif not os.path.isdir(config.custom_nodes):
        errors.append(f"custom_nodes does not exist: {config.custom_nodes}")

    if config.python_exe and not os.path.isfile(config.python_exe):
        errors.append(f"python_exe does not exist: {config.python_exe}")

    if config.git_exe and config.git_exe != "git" and not os.path.isfile(config.git_exe):
        errors.append(f"git_exe does not exist: {config.git_exe}")

    return errors


def _check_file_candidates(base_dir: str, filename: str) -> Optional[str]:
    candidate = os.path.join(base_dir, filename)
    if os.path.isfile(candidate):
        return candidate
    return None


def detect_python_exe() -> Optional[str]:
    import shutil
    import string

    if sys.platform == "win32":
        for letter in string.ascii_uppercase:
            drive = f"{letter}:\\"
            if not os.path.exists(drive):
                continue
            for dirname in ["Comfyui", "ComfyUI"]:
                search_base = os.path.join(drive, dirname)
                if not os.path.isdir(search_base):
                    continue
                for root, dirs, _ in os.walk(search_base):
                    dirs[:] = [d for d in dirs if d not in ["__pycache__", "node_modules"]]
                    py_path = os.path.join(root, "python.exe")
                    if os.path.isfile(py_path):
                        return py_path
    else:
        for candidate in ["/usr/bin/python3", "/usr/local/bin/python3"]:
            if os.path.isfile(candidate):
                return candidate

    for path_dir in os.environ.get("PATH", "").split(os.pathsep):
        py_name = "python.exe" if sys.platform == "win32" else "python3"
        py_path = os.path.join(path_dir, py_name)
        if os.path.isfile(py_path):
            return py_path

    if sys.platform == "win32":
        for base in ["C:\\Python312", "C:\\Python311", "C:\\Python310",
                      "C:\\Program Files\\Python312", "C:\\Program Files\\Python311"]:
            py_path = os.path.join(base, "python.exe")
            if os.path.isfile(py_path):
                return py_path

    path_python = shutil.which("python3") or shutil.which("python")
    if path_python:
        return path_python

    return None


def detect_git_exe() -> Optional[str]:
    if sys.platform == "win32":
        candidates = [
            "C:\\Program Files\\Git\\bin\\git.exe",
            "C:\\Program Files (x86)\\Git\\bin\\git.exe",
            os.path.expandvars("%LOCALAPPDATA%\\Programs\\Git\\bin\\git.exe"),
        ]
        for candidate in candidates:
            if os.path.isfile(candidate):
                return candidate

    import shutil
    git_path = shutil.which("git")
    if git_path:
        return git_path

    return None
