"""Command-line interface for comfyui-deps."""

import os
import sys
from typing import Optional

import click
from colorama import Fore, Style, init as colorama_init

from .backup import backup_directory, backup_pip_freeze, clean_old_backups, list_backups
from .config import (
    detect_git_exe,
    detect_python_exe,
    init_config_interactive,
    load_config,
    save_config,
    validate_config,
)
from .deps import (
    install_package,
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
from .rollback import rollback_dependencies, rollback_directory
from .scanner import list_plugins, scan_all_plugins, scan_plugins
from .updater import update_target

colorama_init(autoreset=True)

_EMOJI_OK = "OK"
_EMOJI_WARN = "!!"
_EMOJI_ERR = "XX"


def _ok(msg: str) -> str:
    return f"{Fore.GREEN}[{_EMOJI_OK}]{Style.RESET_ALL} {msg}"


def _warn(msg: str) -> str:
    return f"{Fore.YELLOW}[{_EMOJI_WARN}]{Style.RESET_ALL} {msg}"


def _err(msg: str) -> str:
    return f"{Fore.RED}[{_EMOJI_ERR}]{Style.RESET_ALL} {msg}"


def _load_config_or_exit(ctx) -> tuple[Config, str]:
    config_path = ctx.obj.get("config_path", "")
    try:
        config = load_config(config_path)
    except Exception as e:
        click.echo(_err(f"Failed to load config: {e}"))
        ctx.exit(1)
    if not config_path:
        from .config import _get_config_path
        config_path = _get_config_path()
    return config, config_path


def _resolve_target(config: Config, target: str) -> str:
    if not target:
        return config.comfyui_root
    if os.path.isabs(target):
        return target
    candidate = os.path.join(config.custom_nodes, target)
    if os.path.isdir(candidate):
        return candidate
    return target


def _display_scan_results(results) -> tuple:
    has_git_count = 0
    has_updates_count = 0

    for r in results:
        if r.has_git:
            has_git_count += 1
            if r.has_updates:
                has_updates_count += 1
                tag = f"{Fore.YELLOW}{r.commit_count} commits{Style.RESET_ALL}"
                click.echo(f"  {Fore.CYAN}git{Style.RESET_ALL} {Fore.GREEN}{r.name}{Style.RESET_ALL} [{tag}]")
            elif r.error:
                click.echo(f"  {Fore.CYAN}git{Style.RESET_ALL} {r.name} {Fore.RED}({r.error}){Style.RESET_ALL}")
            else:
                click.echo(f"  {Fore.CYAN}git{Style.RESET_ALL} {r.name} [{Fore.GREEN}up to date{Style.RESET_ALL}]")
        else:
            click.echo(f"  {Fore.MAGENTA}zip{Style.RESET_ALL} {r.name} [non-git]")

    return has_git_count, has_updates_count


@click.group(invoke_without_command=True)
@click.option("--config", "-c", "config_path", default="", help="Path to config file")
@click.pass_context
def main(ctx, config_path):
    """ComfyUI Plugin Dependency Manager - manage updates, backups, and dependencies."""
    ctx.ensure_object(dict)
    ctx.obj["config_path"] = config_path
    if ctx.invoked_subcommand is None:
        from .webui import create_app
        app = create_app()
        url = "http://127.0.0.1:8510"
        click.echo()
        click.echo(f"  {Fore.CYAN}ComfyUI Deps Web GUI{Style.RESET_ALL}")
        click.echo(f"  {'='*40}")
        click.echo(f"  Open your browser and visit:")
        click.echo(f"  {Fore.GREEN}{url}{Style.RESET_ALL}")
        click.echo(f"  Press Ctrl+C to stop.")
        click.echo()
        try:
            import webbrowser
            opened = webbrowser.open(url)
            if not opened:
                click.echo(f"  {Fore.YELLOW}Browser could not be opened automatically.{Style.RESET_ALL}")
                click.echo(f"  {Fore.YELLOW}Please manually open {url} in your browser.{Style.RESET_ALL}")
                click.echo()
        except Exception:
            pass
        try:
            app.run(host="127.0.0.1", port=8510, debug=False)
        except KeyboardInterrupt:
            click.echo()
            click.echo("Shutting down...")


@main.group()
def config_cmd():
    """Manage configuration (init / show / set)."""


@config_cmd.command("init")
@click.pass_context
def config_init_cmd(ctx):
    """Run interactive configuration setup."""
    config = init_config_interactive()
    config_path = ctx.obj.get("config_path", "")
    if not config_path:
        from .config import _get_config_path
        config_path = _get_config_path()
    save_config(config, config_path)
    click.echo(_ok(f"Configuration saved to {config_path}"))


@config_cmd.command("show")
@click.pass_context
def config_show_cmd(ctx):
    """Display current configuration."""
    config, config_path = _load_config_or_exit(ctx)
    click.echo(f"Config file: {config_path}")
    click.echo(f"  comfyui_root : {config.comfyui_root}")
    click.echo(f"  custom_nodes : {config.custom_nodes}")
    click.echo(f"  python_exe   : {config.python_exe}")
    click.echo(f"  python_home  : {config.python_home}")
    click.echo(f"  git_exe      : {config.git_exe}")
    click.echo(f"  backup_dir   : {config.backup_dir}")
    click.echo(f"  log_dir      : {config.log_dir}")
    click.echo(f"  core_libs    : {', '.join(config.core_libs)}")
    errors = validate_config(config)
    if errors:
        click.echo()
        for e in errors:
            click.echo(_warn(f"  {e}"))
    else:
        click.echo(_ok("  All paths valid"))


@config_cmd.command("set")
@click.argument("key")
@click.argument("value")
@click.pass_context
def config_set_cmd(ctx, key, value):
    """Set a configuration value. Use dot notation for nested keys."""
    config, config_path = _load_config_or_exit(ctx)
    key_lower = key.lower()
    if key_lower in ("comfyui_root", "custom_nodes", "python_exe",
                      "python_home", "git_exe", "backup_dir", "log_dir"):
        setattr(config, key_lower, value)
    else:
        click.echo(_err(f"Unknown config key: {key}"))
        return
    save_config(config, config_path)
    click.echo(_ok(f"Set {key} = {value}"))


@main.command()
@click.option("--target", "-t", default="", help="Target plugin name or path")
@click.option("--verbose", "-v", "verbose_", is_flag=True, help="Show detailed commit info")
@click.pass_context
def check_cmd(ctx, target, verbose_):
    """Check for available updates on a plugin or ComfyUI main program."""
    config, _ = _load_config_or_exit(ctx)
    target_path = _resolve_target(config, target)
    target_name = os.path.basename(target_path.rstrip(os.sep))

    if not os.path.isdir(target_path):
        click.echo(_err(f"Directory not found: {target_path}"))
        return

    if not has_git(target_path):
        click.echo(_warn(f"Not a Git repository. Use manual ZIP update."))
        return

    git_exe = config.git_exe if config.git_exe else None
    click.echo(f"Checking updates for: {Fore.CYAN}{target_name}{Style.RESET_ALL}")

    ok, branch = detect_remote_branch(target_path, git_exe)
    if not ok:
        click.echo(_err(f"Failed to detect remote branch: {branch}"))
        return

    fetch_origin(target_path, git_exe)
    ok, log_output = check_updates(
        target_path, branch, oneline=not verbose_, git_exe=git_exe
    )
    if not ok:
        click.echo(_err(f"Error: {log_output}"))
        return

    if "Already up to date" in log_output:
        click.echo(_ok(log_output))
    else:
        click.echo(f"\n{Fore.YELLOW}Updates available on branch '{branch}':{Style.RESET_ALL}")
        click.echo(log_output)


@main.command()
@click.option("--page-size", default=10, type=int, help="Number of plugins per page")
@click.option("--all", "show_all", is_flag=True, help="Show all plugins at once (no pagination)")
@click.pass_context
def scan_cmd(ctx, page_size, show_all):
    """Scan all plugins in custom_nodes for update status, paginated by default."""
    config, _ = _load_config_or_exit(ctx)

    if not config.custom_nodes or not os.path.isdir(config.custom_nodes):
        click.echo(_err("Custom nodes directory not configured or not found."))
        click.echo("Run 'comfyui-deps config init' to set up.")
        return

    all_plugins = list_plugins(config)
    if not all_plugins:
        click.echo(_warn("No plugins found."))
        return

    if show_all:
        click.echo(f"Scanning: {Fore.CYAN}{config.custom_nodes}{Style.RESET_ALL}")
        click.echo()
        results = scan_all_plugins(config)
        has_git, has_up = _display_scan_results(results)
        click.echo()
        click.echo(f"Total: {len(results)} plugins "
                   f"({has_git} git, {has_up} have updates)")
        return

    total_pages = max(1, (len(all_plugins) + page_size - 1) // page_size)
    current_page = 1
    scanned_cache: dict = {}
    git_exe = config.git_exe if config.git_exe else None

    click.echo(f"Scanning: {Fore.CYAN}{config.custom_nodes}{Style.RESET_ALL}")
    click.echo(f"Found {Fore.CYAN}{len(all_plugins)}{Style.RESET_ALL} plugins "
               f"({total_pages} page{'s' if total_pages > 1 else ''})")
    click.echo("Press Enter/n for next page, p for previous, q to quit.")

    while True:
        start = (current_page - 1) * page_size
        end = min(start + page_size, len(all_plugins))
        page_names = all_plugins[start:end]

        click.echo()
        click.echo(f"{'='*50}")
        click.echo(f"  Page {Fore.CYAN}{current_page}/{total_pages}{Style.RESET_ALL} "
                   f"(plugins {start+1}\u2013{end} of {len(all_plugins)})")
        click.echo(f"{'='*50}")
        click.echo()

        page_results = []
        for name in page_names:
            if name in scanned_cache:
                page_results.append(scanned_cache[name])
            else:
                path = os.path.join(config.custom_nodes, name)
                if os.path.isdir(path):
                    from .scanner import _scan_single
                    status = _scan_single(path, name, git_exe)
                    scanned_cache[name] = status
                    page_results.append(status)

        _display_scan_results(page_results)

        if total_pages <= 1:
            break

        click.echo()
        choice = click.prompt(
            f"Enter=next  n=next  p=prev  q=quit",
            default="",
            show_default=False,
            prompt_suffix=" > ",
        ).strip().lower()

        if choice in ("q", "quit", "exit"):
            break
        elif choice in ("n", "next"):
            if current_page < total_pages:
                current_page += 1
            else:
                click.echo(_warn("Already on the last page."))
        elif choice in ("p", "prev", "previous"):
            if current_page > 1:
                current_page -= 1
            else:
                click.echo(_warn("Already on the first page."))
        elif choice == "":
            if current_page < total_pages:
                current_page += 1
            else:
                click.echo(_warn("Already on the last page."))
        else:
            click.echo(_err(f"Invalid choice: '{choice}'. Use n/p/q."))

    has_git_total = 0
    has_up_total = 0
    for s in scanned_cache.values():
        if s.has_git:
            has_git_total += 1
            if s.has_updates:
                has_up_total += 1

    click.echo()
    click.echo(f"Total scanned: {len(scanned_cache)}/{len(all_plugins)} plugins "
               f"({has_git_total} git, {has_up_total} have updates)")


@main.command()
@click.option("--target", "-t", default="", help="Target plugin name or path")
@click.option("--yes", "-y", "auto_confirm", is_flag=True, help="Skip confirmation prompts")
@click.option("--skip-backup", is_flag=True, help="Skip directory backup")
@click.option("--skip-deps", is_flag=True, help="Skip dependency installation")
@click.pass_context
def update_cmd(ctx, target, auto_confirm, skip_backup, skip_deps):
    """Safely update a plugin or ComfyUI main program (backup + pull + deps)."""
    config, _ = _load_config_or_exit(ctx)
    target_path = _resolve_target(config, target)
    target_name = os.path.basename(target_path.rstrip(os.sep))

    success = update_target(
        config=config,
        target_path=target_path,
        target_name=target_name,
        skip_backup=skip_backup,
        skip_deps=skip_deps,
        auto_confirm=auto_confirm,
    )

    if not success:
        ctx.exit(1)


@main.group()
def backup_cmd():
    """Manage backups (dir / deps / list / clean)."""


@backup_cmd.command("dir")
@click.option("--target", "-t", default="", help="Target plugin name or path")
@click.pass_context
def backup_dir_cmd(ctx, target):
    """Create a directory backup."""
    config, _ = _load_config_or_exit(ctx)
    target_path = _resolve_target(config, target)

    if not config.backup_dir:
        config.backup_dir = os.path.join(
            os.path.dirname(config.custom_nodes.rstrip(os.sep)), "backups"
        )

    try:
        backup_path = backup_directory(target_path, config.backup_dir)
        click.echo(_ok(f"Backup created: {backup_path}"))
    except Exception as e:
        click.echo(_err(f"Backup failed: {e}"))


@backup_cmd.command("deps")
@click.pass_context
def backup_deps_cmd(ctx):
    """Create a pip freeze dependency snapshot."""
    config, _ = _load_config_or_exit(ctx)

    if not config.backup_dir:
        config.backup_dir = os.path.join(
            os.path.dirname(config.custom_nodes.rstrip(os.sep)), "backups"
        )

    try:
        python_exe = resolve_python_exe(config.python_exe, config.python_home)
        path = backup_pip_freeze(python_exe, config.backup_dir)
        click.echo(_ok(f"Dependency snapshot: {path}"))
    except Exception as e:
        click.echo(_err(f"Snapshot failed: {e}"))


@backup_cmd.command("list")
@click.option("--target", "-t", default="", help="Target plugin name or path")
@click.pass_context
def backup_list_cmd(ctx, target):
    """List available backups."""
    config, _ = _load_config_or_exit(ctx)

    if not config.backup_dir:
        config.backup_dir = os.path.join(
            os.path.dirname(config.custom_nodes.rstrip(os.sep)), "backups"
        )

    if not os.path.isdir(config.backup_dir):
        click.echo(_warn("No backup directory found."))
        return

    target_name = ""
    if target:
        target_path = _resolve_target(config, target)
        target_name = os.path.basename(target_path.rstrip(os.sep))

    entries = list_backups(target_name or "", config.backup_dir)
    if not entries:
        click.echo(_warn("No backups found."))
        return

    click.echo(f"Backups in {config.backup_dir}:")
    for e in entries:
        click.echo(f"  {e.name} ({e.created.strftime('%Y-%m-%d %H:%M')})")


@backup_cmd.command("clean")
@click.option("--target", "-t", default="", help="Target plugin name or path")
@click.option("--keep", "-k", default=5, type=int, help="Number of recent backups to keep")
@click.pass_context
def backup_clean_cmd(ctx, target, keep):
    """Clean up old backups, keeping the N most recent."""
    config, _ = _load_config_or_exit(ctx)

    if not config.backup_dir:
        click.echo(_err("Backup directory not configured."))
        return

    target_path = _resolve_target(config, target)
    target_name = os.path.basename(target_path.rstrip(os.sep))

    try:
        deleted = clean_old_backups(target_name, config.backup_dir, keep)
        click.echo(_ok(f"Removed {deleted} old backups for '{target_name}' (kept {keep})"))
    except Exception as e:
        click.echo(_err(f"Clean failed: {e}"))


@main.group()
def deps_cmd():
    """Manage Python dependencies (install / check / add)."""


@deps_cmd.command("install")
@click.option("--target", "-t", default="", help="Target plugin name or path")
@click.pass_context
def deps_install_cmd(ctx, target):
    """Install dependencies from a plugin's requirements.txt."""
    config, _ = _load_config_or_exit(ctx)
    target_path = _resolve_target(config, target)
    req_file = os.path.join(target_path, "requirements.txt")

    if not os.path.isfile(req_file):
        click.echo(_err(f"No requirements.txt found in {target_path}"))
        return

    python_exe = resolve_python_exe(config.python_exe, config.python_home)
    click.echo(f"Installing from: {Fore.CYAN}{req_file}{Style.RESET_ALL}")

    from .deps import detect_core_lib_conflicts

    ok, dry = install_requirements(python_exe, req_file, dry_run=True)
    if ok:
        conflicts = detect_core_lib_conflicts(dry, config.core_libs)
        if conflicts:
            click.echo(_warn("Core library updates detected:"))
            for c in conflicts:
                click.echo(f"  {c}")
            if not click.confirm("Continue?", default=False):
                return

    ok, result = install_requirements(python_exe, req_file)
    if ok:
        click.echo(_ok("Dependencies installed."))
    else:
        click.echo(_err(f"Install failed: {result}"))


@deps_cmd.command("check")
@click.option("--target", "-t", default="", help="Target plugin name or path")
@click.pass_context
def deps_check_cmd(ctx, target):
    """Dry-run check what dependencies would be installed."""
    config, _ = _load_config_or_exit(ctx)
    target_path = _resolve_target(config, target)
    req_file = os.path.join(target_path, "requirements.txt")

    if not os.path.isfile(req_file):
        click.echo(_err(f"No requirements.txt found in {target_path}"))
        return

    python_exe = resolve_python_exe(config.python_exe, config.python_home)
    click.echo(f"Dry-run check: {Fore.CYAN}{req_file}{Style.RESET_ALL}")

    ok, result = install_requirements(python_exe, req_file, dry_run=True)
    if ok:
        click.echo(result)
        from .deps import detect_core_lib_conflicts
        conflicts = detect_core_lib_conflicts(result, config.core_libs)
        if conflicts:
            click.echo(_warn("Core library updates would occur:"))
            for c in conflicts:
                click.echo(f"  {c}")
    else:
        click.echo(_err(f"Dry-run failed: {result}"))


@deps_cmd.command("add")
@click.argument("package")
@click.pass_context
def deps_add_cmd(ctx, package):
    """Install a single package into the configured Python environment."""
    config, _ = _load_config_or_exit(ctx)
    python_exe = resolve_python_exe(config.python_exe, config.python_home)

    click.echo(f"Installing: {Fore.CYAN}{package}{Style.RESET_ALL}")
    from .deps import detect_core_lib_conflicts

    ok, dry = install_package(python_exe, package, dry_run=True)
    if ok:
        conflicts = detect_core_lib_conflicts(dry, config.core_libs)
        if conflicts:
            click.echo(_warn("Core library updates detected:"))
            for c in conflicts:
                click.echo(f"  {c}")
            if not click.confirm("Continue?", default=False):
                return

    ok, result = install_package(python_exe, package)
    if ok:
        click.echo(_ok("Package installed."))
    else:
        click.echo(_err(f"Install failed: {result}"))


@main.command()
@click.option("--target", "-t", default="", help="Target plugin name or path")
@click.option("--list", "-l", "list_flag", is_flag=True, help="List available backups")
@click.option("--restore", "-r", default="", help="Backup name or path to restore from")
@click.option("--force", "-f", is_flag=True, help="Force reinstall for dependency rollback")
@click.pass_context
def rollback_cmd(ctx, target, list_flag, restore, force):
    """Rollback a failed update (directory or dependency snapshot)."""
    config, _ = _load_config_or_exit(ctx)

    if list_flag:
        if not config.backup_dir:
            click.echo(_err("Backup directory not configured."))
            return
        target_path = _resolve_target(config, target)
        target_name = os.path.basename(target_path.rstrip(os.sep))
        entries = list_backups(target_name, config.backup_dir)
        if not entries:
            click.echo(_warn("No backups found."))
        else:
            click.echo(f"Available backups for '{target_name}':")
            for e in entries:
                click.echo(f"  {e.name} ({e.created.strftime('%Y-%m-%d %H:%M')})")
        return

    if restore:
        backup_path = restore
        if not os.path.isdir(backup_path) and config.backup_dir:
            backup_path = os.path.join(config.backup_dir, restore)
        if os.path.isfile(backup_path):
            ok, msg = rollback_dependencies(config, backup_path, force=force)
            if ok:
                click.echo(_ok("Dependencies restored from snapshot."))
            else:
                click.echo(_err(f"Restore failed: {msg}"))
            return
        if os.path.isdir(backup_path):
            target_path = _resolve_target(config, target)
            ok = rollback_directory(target_path, backup_path)
            if ok:
                click.echo(_ok(f"Directory restored from: {backup_path}"))
            else:
                click.echo(_err("Directory rollback failed."))
            return
        click.echo(_err(f"Backup not found: {backup_path}"))
        return

    click.echo(_warn("Use --list to see available backups, --restore to rollback."))


@main.command()
@click.option("--host", default="127.0.0.1", help="Host to bind to")
@click.option("--port", default=8510, type=int, help="Port to listen on")
@click.option("--no-browser", is_flag=True, help="Do not open browser automatically")
def gui_cmd(host, port, no_browser):
    """Launch the web GUI interface."""
    from .webui import create_app
    app = create_app()
    url = f"http://{host}:{port}"
    click.echo()
    click.echo(f"  {Fore.CYAN}ComfyUI Deps Web GUI{Style.RESET_ALL}")
    click.echo(f"  {'='*40}")
    click.echo(f"  Open your browser and visit:")
    click.echo(f"  {Fore.GREEN}{url}{Style.RESET_ALL}")
    click.echo(f"  Press Ctrl+C to stop.")
    click.echo()
    if not no_browser:
        try:
            import webbrowser
            opened = webbrowser.open(url)
            if not opened:
                click.echo(f"  {Fore.YELLOW}Browser could not be opened automatically.{Style.RESET_ALL}")
                click.echo(f"  {Fore.YELLOW}Please manually open {url} in your browser.{Style.RESET_ALL}")
                click.echo()
        except Exception:
            pass
    try:
        app.run(host=host, port=port, debug=False)
    except KeyboardInterrupt:
        click.echo()
        click.echo("Shutting down...")


if __name__ == "__main__":
    main()
