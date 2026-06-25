"""Web GUI for comfyui-deps using Flask."""

import json
import logging
import os
import subprocess
import sys
import time
from logging.handlers import RotatingFileHandler

from flask import Flask, jsonify, render_template, request, send_file

from .backup import backup_directory, backup_pip_freeze, clean_old_backups, list_backups
from .config import (
    _get_current_name,
    create_config,
    delete_config,
    list_configs,
    load_config,
    switch_config,
    validate_config,
)
from .deps import (
    detect_core_lib_conflicts,
    install_package,
    install_requirements,
    resolve_python_exe,
    restore_from_snapshot,
)
from .git_ops import (
    check_updates,
    detect_remote_branch,
    fetch_origin,
    has_git,
    list_remote_branches,
    pull_updates,
)
from .rollback import rollback_dependencies, rollback_directory
from .scanner import _scan_single, list_plugins, scan_plugins


def _load_config():
    try:
        cfg = load_config()
        return cfg
    except Exception as e:
        import sys
        print(f"[WARN] Failed to load config: {e}", file=sys.stderr)
        from .models import Config
        return Config()


def _setup_logging(cfg):
    logger = logging.getLogger("comfyui-deps")
    logger.setLevel(logging.DEBUG)
    # 移除已有的 handler
    logger.handlers.clear()

    # 控制台 handler
    ch = logging.StreamHandler(sys.stderr)
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s %(message)s", datefmt="%H:%M:%S"))
    logger.addHandler(ch)

    # 文件 handler（按配置名分目录）
    log_dir = cfg.log_dir or os.path.join(os.path.dirname(__file__), "..", "log")
    config_name = cfg.name or "default"
    log_subdir = os.path.join(log_dir, config_name)
    os.makedirs(log_subdir, exist_ok=True)
    log_file = os.path.join(log_subdir, "comfyui-deps.log")

    try:
        fh = RotatingFileHandler(log_file, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        logger.addHandler(fh)
    except OSError as e:
        logger.warning("无法写入日志文件 %s: %s", log_file, e)

    return logger


_logger = None


def get_logger():
    global _logger
    if _logger is None:
        _logger = logging.getLogger("comfyui-deps")
    return _logger


def create_app():
    app = Flask(__name__, template_folder="templates", static_folder="static")
    _config = _load_config()
    global _logger
    _logger = _setup_logging(_config)
    _logger.info("ComfyUI Deps Web GUI starting (config: %s)", _config.name)

    @app.errorhandler(500)
    def internal_error(e):
        import traceback
        orig = getattr(e, "original_exception", e)
        tb = traceback.format_exc()
        print(f"[ERROR] Unhandled exception: {orig}", flush=True)
        print(tb, flush=True)
        _logger.error("Unhandled exception: %s\n%s", orig, tb)
        return jsonify({"error": str(orig)[:500]}), 500

    def _get_config():
        try:
            return load_config()
        except Exception:
            return _config

    def _config_subpath(cfg, base_dir_key, fallback):
        base = getattr(cfg, base_dir_key, "") or fallback
        config_name = (cfg.name or "default").strip()
        return os.path.join(base, config_name) if config_name else base

    def _git_exe(cfg):
        return cfg.git_exe if cfg.git_exe else None

    def _cache_dir(cfg):
        if cfg.cache_dir:
            return _config_subpath(cfg, "cache_dir", "")
        base = cfg.comfyui_root or os.path.dirname(cfg.custom_nodes.rstrip(os.sep) or ".")
        return os.path.join(base, "cache", cfg.name or "default")

    def _cache_path(cfg, key):
        d = _cache_dir(cfg)
        os.makedirs(d, exist_ok=True)
        return os.path.join(d, key + ".json")

    def _cache_get(cfg, key):
        p = _cache_path(cfg, key)
        if os.path.isfile(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if time.time() - data.get("ts", 0) < 86400:
                    return data.get("value")
            except Exception:
                pass
        return None

    def _cache_set(cfg, key, value):
        p = _cache_path(cfg, key)
        try:
            with open(p, "w", encoding="utf-8") as f:
                json.dump({"ts": time.time(), "value": value}, f, ensure_ascii=False)
        except Exception:
            pass

    def _dir_size(path):
        total = 0
        try:
            for dirpath, dirnames, filenames in os.walk(path):
                for f in filenames:
                    fp = os.path.join(dirpath, f)
                    try:
                        total += os.path.getsize(fp)
                    except OSError:
                        pass
        except Exception:
            pass
        return total

    def _fmt_size(n):
        if n < 1024:
            return f"{n} B"
        elif n < 1024 * 1024:
            return f"{n / 1024:.1f} KB"
        elif n < 1024 * 1024 * 1024:
            return f"{n / (1024 * 1024):.1f} MB"
        else:
            return f"{n / (1024 * 1024 * 1024):.2f} GB"

    # ── Page ────────────────────────────────────────────────────────

    @app.route("/")
    def index():
        return render_template("index.html")

    # ── Config ──────────────────────────────────────────────────────

    @app.route("/api/config")
    def api_config():
        cfg = _get_config()
        errors = validate_config(cfg)
        return jsonify(
            {
                "config_name": cfg.name or "default",
                "comfyui_root": cfg.comfyui_root,
                "custom_nodes": cfg.custom_nodes,
                "python_exe": cfg.python_exe,
                "python_home": cfg.python_home,
                "git_exe": cfg.git_exe,
                "backup_dir": cfg.backup_dir,
                "log_dir": cfg.log_dir,
                "cache_dir": cfg.cache_dir,
                "core_libs": cfg.core_libs,
                "errors": errors,
                "configured": bool(cfg.comfyui_root),
            }
        )

    @app.route("/api/config/save", methods=["POST"])
    def api_config_save():
        data = request.get_json() or {}
        cfg = _get_config()

        for key in (
            "comfyui_root", "custom_nodes", "python_home",
            "git_exe", "backup_dir", "log_dir", "cache_dir",
        ):
            if key in data:
                setattr(cfg, key, data[key])

        if "core_libs" in data:
            cfg.core_libs = data["core_libs"]

        # 自动解析 python 可执行文件路径
        try:
            resolved = resolve_python_exe("", cfg.python_home or "")
            cfg.python_exe = resolved
        except FileNotFoundError:
            cfg.python_exe = ""

        # 创建日志和缓存目录
        for dkey in ("comfyui_root", "custom_nodes", "backup_dir", "log_dir", "cache_dir"):
            dpath = getattr(cfg, dkey, "")
            if dpath:
                try:
                    os.makedirs(dpath, exist_ok=True)
                except OSError:
                    pass

        from .config import save_config
        save_config(cfg)

        errors = validate_config(cfg)
        if not cfg.python_exe:
            errors.append("无法自动检测 Python 可执行文件，请在 Python 安装目录中填写正确的路径。")
        _logger.info("Config saved (name=%s, comfyui_root=%s, errors=%d)", cfg.name, cfg.comfyui_root, len(errors))
        return jsonify({"status": "ok", "errors": errors})

    # ── Config Management ──────────────────────────────────────────

    @app.route("/api/config/list")
    def api_config_list():
        configs = list_configs()
        return jsonify({"configs": configs})

    @app.route("/api/config/switch", methods=["POST"])
    def api_config_switch():
        data = request.get_json() or {}
        name = (data.get("name") or "").strip()
        if not name:
            return jsonify({"error": "No config name provided"}), 400
        try:
            cfg = switch_config(name)
            global _logger
            _logger = _setup_logging(cfg)
            _logger.info("Switched to config: %s", name)
            return jsonify({
                "status": "ok",
                "config_name": cfg.name,
                "comfyui_root": cfg.comfyui_root,
            })
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/config/create", methods=["POST"])
    def api_config_create():
        data = request.get_json() or {}
        name = (data.get("name") or "").strip()
        if not name:
            return jsonify({"error": "No config name provided"}), 400
        try:
            cfg = create_config(name)
            _logger.info("Created config: %s", name)
            return jsonify({"status": "ok", "config_name": cfg.name})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/config/delete", methods=["POST"])
    def api_config_delete():
        data = request.get_json() or {}
        name = (data.get("name") or "").strip()
        if not name:
            return jsonify({"error": "No config name provided"}), 400
        if name == "default":
            return jsonify({"error": "Cannot delete default config"}), 400
        try:
            ok = delete_config(name)
            if ok:
                current = _get_current_name()
                if current == name:
                    switch_config("default")
                    cfg = load_config()
                    global _logger
                    _logger = _setup_logging(cfg)
                    _logger.info("Deleted active config %s, switched to default", name)
                else:
                    _logger.info("Deleted config: %s", name)
            return jsonify({"status": "ok", "deleted": ok})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    # ── Plugins ─────────────────────────────────────────────────────

    @app.route("/api/plugins")
    def api_plugins():
        cfg = _get_config()
        plugins = list_plugins(cfg)
        # 统计备份计数
        backup_counts = {}
        try:
            from .backup import list_backups
            for p in plugins:
                entries = list_backups(p, cfg.backup_dir or "")
                backup_counts[p] = len(entries)
        except Exception:
            pass
        return jsonify({"plugins": plugins, "total": len(plugins), "backup_counts": backup_counts})

    @app.route("/api/scan", methods=["POST"])
    def api_scan():
        data = request.get_json() or {}
        names = data.get("names", [])
        if not names:
            return jsonify({"error": "No plugin names provided"}), 400

        cfg = _get_config()
        results = scan_plugins(cfg, names)
        items = []
        for r in results:
            items.append(
                {
                    "name": r.name,
                    "path": r.path,
                    "has_git": r.has_git,
                    "has_updates": r.has_updates,
                    "commit_count": r.commit_count,
                    "remote_branch": r.remote_branch,
                    "error": r.error,
                }
            )

        has_git = sum(1 for r in results if r.has_git)
        has_up = sum(1 for r in results if r.has_updates)
        return jsonify(
            {
                "results": items,
                "total": len(items),
                "has_git": has_git,
                "has_updates": has_up,
            }
        )

    # ── Check single ────────────────────────────────────────────────

    @app.route("/api/check", methods=["POST"])
    def api_check():
        data = request.get_json() or {}
        name = data.get("name", "")
        if not name:
            return jsonify({"error": "No plugin name provided"}), 400

        cfg = _get_config()
        target_path = os.path.join(cfg.custom_nodes, name)

        if not os.path.isdir(target_path):
            return jsonify({"error": f"Directory not found: {target_path}"}), 404

        if not has_git(target_path):
            return jsonify({"status": "non_git", "message": "Not a Git repository."})

        git_exe = _git_exe(cfg)
        ok, branch = detect_remote_branch(target_path, git_exe)
        if not ok:
            return jsonify({"status": "error", "message": f"Branch detection failed: {branch}"})

        ok_br, remote_branches = list_remote_branches(target_path, git_exe)

        fetch_origin(target_path, git_exe)

        verbose = data.get("verbose", False)
        ok, log_output = check_updates(
            target_path, branch, oneline=not verbose, git_exe=git_exe
        )
        if not ok:
            return jsonify({"status": "error", "message": log_output})

        base = {"branch": branch, "remote_branches": remote_branches if ok_br else []}
        if "Already up to date" in log_output:
            base["status"] = "up_to_date"
            base["message"] = log_output
            return jsonify(base)

        base["status"] = "updates"
        base["log"] = log_output
        return jsonify(base)

    # ── Update ──────────────────────────────────────────────────────

    @app.route("/api/update", methods=["POST"])
    def api_update():
        data = request.get_json() or {}
        name = data.get("name", "")
        skip_backup = data.get("skip_backup", False)
        skip_deps = data.get("skip_deps", False)
        branch_override = (data.get("branch") or "").strip()

        if not name:
            return jsonify({"error": "No plugin name provided"}), 400

        cfg = _get_config()
        target_path = os.path.join(cfg.custom_nodes, name)
        target_name = os.path.basename(target_path.rstrip(os.sep))

        if not os.path.isdir(target_path):
            return jsonify({"error": f"Directory not found: {target_path}"}), 404

        if not has_git(target_path):
            return jsonify({"error": "Not a Git repository."})

        git_exe = _git_exe(cfg)
        log_lines = []

        if branch_override:
            branch = branch_override
        else:
            ok, branch = detect_remote_branch(target_path, git_exe)
            if not ok:
                return jsonify({"error": branch}), 500

        fetch_origin(target_path, git_exe)

        ok, log_output = check_updates(target_path, branch, oneline=True, git_exe=git_exe)
        if not ok:
            return jsonify({"error": log_output}), 500

        if "Already up to date" in log_output:
            return jsonify({"status": "up_to_date", "steps": []})

        steps = [{"name": "Check", "status": "ok", "detail": "Updates found"}]

        if not skip_backup:
            backup_parent = cfg.backup_dir or os.path.join(
                os.path.dirname(cfg.custom_nodes.rstrip(os.sep)), "backups"
            )
            try:
                bp = backup_directory(target_path, backup_parent)
                steps.append({"name": "Backup", "status": "ok", "detail": bp})
            except Exception as e:
                steps.append({"name": "Backup", "status": "error", "detail": str(e)})
        else:
            steps.append({"name": "Backup", "status": "skipped"})

        ok, msg = pull_updates(target_path, branch, git_exe)
        if ok:
            steps.append({"name": "Pull", "status": "ok", "detail": msg[:300]})
        else:
            steps.append({"name": "Pull", "status": "error", "detail": msg})
            return jsonify({"status": "error", "steps": steps, "error": msg}), 500

        if not skip_deps:
            req_file = os.path.join(target_path, "requirements.txt")
            if os.path.isfile(req_file):
                try:
                    python_exe = resolve_python_exe(
                        cfg.python_exe or "", cfg.python_home
                    )
                    ok_deps, result = install_requirements(
                        python_exe, req_file, dry_run=True
                    )
                    conflicts = []
                    if ok_deps:
                        conflicts = detect_core_lib_conflicts(
                            result, cfg.core_libs
                        )
                    if not conflicts:
                        ok_deps, result = install_requirements(python_exe, req_file)
                        if ok_deps:
                            steps.append(
                                {"name": "Deps", "status": "ok", "detail": "Installed"}
                            )
                        else:
                            steps.append(
                                {"name": "Deps", "status": "error", "detail": result[:300]}
                            )
                    else:
                        steps.append(
                            {
                                "name": "Deps",
                                "status": "warning",
                                "detail": f"Core lib conflicts: {'; '.join(conflicts)}",
                            }
                        )
                except Exception as e:
                    steps.append({"name": "Deps", "status": "error", "detail": str(e)})
            else:
                steps.append({"name": "Deps", "status": "skipped", "detail": "No requirements.txt"})
        else:
            steps.append({"name": "Deps", "status": "skipped"})

        return jsonify({"status": "ok", "steps": steps, "branch": branch})

    # ── Backups ─────────────────────────────────────────────────────

    @app.route("/api/backups")
    def api_backups():
        cfg = _get_config()
        backup_dir = cfg.backup_dir or os.path.join(
            os.path.dirname(cfg.custom_nodes.rstrip(os.sep)), "backups"
        )
        target_name = request.args.get("target", "")
        entries = list_backups(target_name, backup_dir)
        return jsonify(
            {
                "backup_dir": backup_dir,
                "entries": [
                    {
                        "name": e.name,
                        "path": e.path,
                        "target": e.target_name,
                        "created": e.created.strftime("%Y-%m-%d %H:%M"),
                        "size": _dir_size(e.path),
                        "size_fmt": _fmt_size(_dir_size(e.path)),
                    }
                    for e in entries
                ],
            }
        )

    @app.route("/api/backups/create", methods=["POST"])
    def api_backups_create():
        data = request.get_json() or {}
        name = data.get("name", "")
        create_deps = data.get("deps", False)

        cfg = _get_config()
        target_path = os.path.join(cfg.custom_nodes, name) if name else cfg.comfyui_root

        if not os.path.isdir(target_path):
            return jsonify({"error": f"Directory not found: {target_path}"}), 404

        backup_dir = cfg.backup_dir or os.path.join(
            os.path.dirname(cfg.custom_nodes.rstrip(os.sep)), "backups"
        )

        results = []
        try:
            bp = backup_directory(target_path, backup_dir)
            results.append({"type": "dir", "path": bp})
        except Exception as e:
            return jsonify({"error": f"Backup failed: {e}"}), 500

        if create_deps:
            try:
                python_exe = resolve_python_exe(
                    cfg.python_exe or "", cfg.python_home
                )
                sp = backup_pip_freeze(python_exe, backup_dir)
                results.append({"type": "deps", "path": sp})
            except Exception as e:
                results.append({"type": "deps", "error": str(e)})

        return jsonify({"status": "ok", "results": results})

    @app.route("/api/backups/clean", methods=["POST"])
    def api_backups_clean():
        data = request.get_json() or {}
        name = data.get("name", "")
        keep = data.get("keep", 5)

        cfg = _get_config()
        backup_dir = cfg.backup_dir
        if not backup_dir:
            return jsonify({"error": "Backup directory not configured."}), 400

        try:
            deleted = clean_old_backups(name, backup_dir, keep)
            return jsonify({"status": "ok", "deleted": deleted, "kept": keep})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    # ── Rollback ────────────────────────────────────────────────────

    @app.route("/api/rollback", methods=["POST"])
    def api_rollback():
        data = request.get_json() or {}
        backup_path = data.get("backup", "")
        target_name = data.get("name", "")
        force = data.get("force", False)

        cfg = _get_config()
        backup_dir = cfg.backup_dir
        if backup_dir and not os.path.exists(backup_path):
            backup_path = os.path.join(backup_dir, backup_path)

        if not os.path.exists(backup_path):
            return jsonify({"error": f"Backup not found: {backup_path}"}), 404

        if os.path.isfile(backup_path):
            ok, msg = rollback_dependencies(cfg, backup_path, force=force)
            if ok:
                return jsonify({"status": "ok", "type": "deps"})
            return jsonify({"error": msg}), 500

        target_path = os.path.join(cfg.custom_nodes, target_name) if target_name else cfg.comfyui_root
        ok = rollback_directory(target_path, backup_path)
        if ok:
            return jsonify({"status": "ok", "type": "dir"})
        return jsonify({"error": "Directory rollback failed."}), 500

    # ── Dependencies ────────────────────────────────────────────────

    @app.route("/api/deps/install", methods=["POST"])
    def api_deps_install():
        data = request.get_json() or {}
        name = data.get("name", "")
        package = data.get("package", "")

        cfg = _get_config()
        python_exe = resolve_python_exe(cfg.python_exe or "", cfg.python_home)

        if package:
            ok, dry = install_package(python_exe, package, dry_run=True)
            if ok:
                conflicts = detect_core_lib_conflicts(dry, cfg.core_libs)
                if conflicts and not data.get("force", False):
                    return jsonify(
                        {
                            "status": "warning",
                            "conflicts": conflicts,
                            "message": "Core library conflicts detected.",
                        }
                    )
            ok, result = install_package(python_exe, package)
        elif name:
            target_path = os.path.join(cfg.custom_nodes, name)
            req_file = os.path.join(target_path, "requirements.txt")
            if not os.path.isfile(req_file):
                return jsonify({"error": "No requirements.txt found."}), 404
            ok, dry = install_requirements(python_exe, req_file, dry_run=True)
            if ok:
                conflicts = detect_core_lib_conflicts(dry, cfg.core_libs)
                if conflicts and not data.get("force", False):
                    return jsonify(
                        {
                            "status": "warning",
                            "conflicts": conflicts,
                            "message": "Core library conflicts detected.",
                        }
                    )
            ok, result = install_requirements(python_exe, req_file)
        else:
            return jsonify({"error": "Provide 'name' or 'package'."}), 400

        if ok:
            return jsonify({"status": "ok", "output": result})
        return jsonify({"error": result}), 500

    @app.route("/api/deps/check", methods=["POST"])
    def api_deps_check():
        data = request.get_json() or {}
        name = data.get("name", "")
        package = data.get("package", "")

        cfg = _get_config()
        python_exe = resolve_python_exe(cfg.python_exe or "", cfg.python_home)

        if package:
            ok, result = install_package(python_exe, package, dry_run=True)
        elif name:
            target_path = os.path.join(cfg.custom_nodes, name)
            req_file = os.path.join(target_path, "requirements.txt")
            if not os.path.isfile(req_file):
                return jsonify({"error": "No requirements.txt found."}), 404
            ok, result = install_requirements(python_exe, req_file, dry_run=True)
        else:
            return jsonify({"error": "Provide 'name' or 'package'."}), 400

        if not ok:
            return jsonify({"error": result}), 500

        conflicts = detect_core_lib_conflicts(result, cfg.core_libs)
        return jsonify(
            {
                "status": "ok",
                "output": result,
                "conflicts": conflicts,
            }
        )

    # ── Cache ──────────────────────────────────────────────────────

    @app.route("/api/cache/scan", methods=["POST"])
    def api_cache_save_scan():
        data = request.get_json() or {}
        key = data.get("key", "scan_results")
        value = data.get("value")
        if not value:
            return jsonify({"error": "No value provided"}), 400
        cfg = _get_config()
        _cache_set(cfg, key, value)
        return jsonify({"status": "ok"})

    @app.route("/api/cache/scan")
    def api_cache_load_scan():
        cfg = _get_config()
        key = request.args.get("key", "scan_results")
        value = _cache_get(cfg, key)
        return jsonify({"value": value})

    @app.route("/api/cache/check", methods=["POST"])
    def api_cache_save_check():
        data = request.get_json() or {}
        name = data.get("name", "")
        if not name:
            return jsonify({"error": "No name provided"}), 400
        cfg = _get_config()
        _cache_set(cfg, "check_" + name, data.get("value"))
        return jsonify({"status": "ok"})

    @app.route("/api/cache/check")
    def api_cache_load_check():
        cfg = _get_config()
        name = request.args.get("name", "")
        if not name:
            return jsonify({"error": "No name provided"}), 400
        value = _cache_get(cfg, "check_" + name)
        return jsonify({"value": value})

    # ── Deps freeze / restore ──────────────────────────────────────

    @app.route("/api/deps/freeze", methods=["POST"])
    def api_deps_freeze():
        data = request.get_json() or {}
        plugin_name = data.get("plugin_name", "")
        cfg = _get_config()
        python_exe = resolve_python_exe(cfg.python_exe or "", cfg.python_home)
        backup_dir = cfg.backup_dir or os.path.join(
            os.path.dirname(cfg.custom_nodes.rstrip(os.sep)), "backups"
        )
        try:
            sp = backup_pip_freeze(python_exe, backup_dir)
            # 写入插件名到备份记录
            record_path = sp + ".meta"
            try:
                with open(record_path, "w", encoding="utf-8") as f:
                    f.write(json.dumps({"plugin_name": plugin_name, "created": time.strftime("%Y-%m-%d %H:%M:%S")}))
            except Exception:
                pass
            return jsonify({"status": "ok", "freeze_path": sp})
        except Exception as e:
            return jsonify({"status": "error", "error": str(e)})

    @app.route("/api/deps/freeze-list")
    def api_deps_freeze_list():
        cfg = _get_config()
        backup_dir = cfg.backup_dir or os.path.join(
            os.path.dirname(cfg.custom_nodes.rstrip(os.sep)), "backups"
        )
        yilai_dir = os.path.join(backup_dir, "yilai")
        entries = []
        try:
            if os.path.isdir(yilai_dir):
                for fname in sorted(os.listdir(yilai_dir), reverse=True):
                    if not fname.startswith("requirements-backup") or not fname.endswith(".txt"):
                        continue
                    fp = os.path.join(yilai_dir, fname)
                    meta_fp = fp + ".meta"
                    plugin_name = ""
                    created = ""
                    if os.path.isfile(meta_fp):
                        try:
                            with open(meta_fp, "r", encoding="utf-8") as f:
                                meta = json.load(f)
                            plugin_name = meta.get("plugin_name", "")
                            created = meta.get("created", "")
                        except Exception:
                            pass
                    size = os.path.getsize(fp)
                    entries.append({
                        "path": fp,
                        "name": fname,
                        "size": size,
                        "size_fmt": _fmt_size(size),
                        "plugin_name": plugin_name,
                        "created": created,
                    })
        except Exception:
            pass
        return jsonify({"entries": entries})

    @app.route("/api/deps/restore", methods=["POST"])
    def api_deps_restore():
        data = request.get_json() or {}
        snapshot_path = data.get("snapshot_path", "")
        force = data.get("force", False)
        dry_run = data.get("dry_run", False)

        cfg = _get_config()
        python_exe = resolve_python_exe(cfg.python_exe or "", cfg.python_home)
        try:
            ok, result = restore_from_snapshot(
                python_exe, snapshot_path, force=force, dry_run=dry_run
            )
            if ok:
                return jsonify({"status": "ok", "output": result})
            return jsonify({"error": result}), 500
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/deps/freeze-delete", methods=["POST"])
    def api_deps_freeze_delete():
        data = request.get_json() or {}
        path = data.get("path", "")
        if not path or not os.path.isfile(path):
            return jsonify({"error": "File not found: " + path}), 404
        try:
            os.remove(path)
            # 删除 meta 文件
            meta_path = path + ".meta"
            if os.path.isfile(meta_path):
                os.remove(meta_path)
            return jsonify({"status": "ok"})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/dirs/size")
    def api_dirs_size():
        path = request.args.get("path", "")
        if not path or not os.path.isdir(path):
            return jsonify({"size": 0, "size_fmt": ""})
        s = _dir_size(path)
        return jsonify({"size": s, "size_fmt": _fmt_size(s)})

    @app.route("/api/backups/delete", methods=["POST"])
    def api_backups_delete():
        data = request.get_json() or {}
        path = data.get("path", "")
        if not path or not os.path.isdir(path):
            return jsonify({"error": "Backup not found: " + path}), 404
        try:
            import shutil
            import stat

            def _onerror(func, p, exc_info):
                os.chmod(p, stat.S_IWRITE)
                func(p)

            shutil.rmtree(path, ignore_errors=False, onerror=_onerror)
            return jsonify({"status": "ok"})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/open-folder", methods=["POST"])
    def api_open_folder():
        data = request.get_json(silent=True) or {}
        path = (data.get("path") or "").strip()
        if not path:
            return jsonify({"error": "No path provided"}), 400
        try:
            if sys.platform == "win32":
                os.startfile(path)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
            return jsonify({"ok": True})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    return app


def main(host="127.0.0.1", port=8510):
    """Start the web GUI server."""
    import webbrowser

    app = create_app()
    url = f"http://{host}:{port}"
    print(f"\n  ComfyUI Deps Web GUI")
    print(f"  {'='*40}")
    print(f"  Open: {url}")
    print()
    webbrowser.open(url)
    app.run(host=host, port=port, debug=False)
