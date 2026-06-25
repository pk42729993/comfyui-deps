"""Core data models for comfyui-deps."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional


@dataclass
class Config:
    name: str = "default"
    comfyui_root: str = ""
    custom_nodes: str = ""
    python_exe: str = ""
    python_home: str = ""
    git_exe: str = ""
    backup_dir: str = ""
    log_dir: str = ""
    cache_dir: str = ""
    core_libs: List[str] = field(
        default_factory=lambda: ["torch", "xformers", "onnxruntime"]
    )


@dataclass
class PluginStatus:
    name: str
    path: str
    has_git: bool
    has_updates: bool
    commit_count: int
    remote_branch: str
    error: Optional[str] = None


@dataclass
class BackupEntry:
    name: str
    path: str
    target_name: str
    timestamp: str
    created: datetime
