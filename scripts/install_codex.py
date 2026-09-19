#!/usr/bin/env python3
"""Install the hub registration and shared skill without replacing user settings."""
import argparse
import copy
import json
import os
from pathlib import Path
import tempfile
import tomllib

ROOT = Path(__file__).resolve().parents[1]
BEGIN = "# BEGIN LOCAL MEMORY HUB"
END = "# END LOCAL MEMORY HUB"


def reject_symlinks(path):
    """Refuse redirection, including dangling links and intermediate directories."""
    for item in [*reversed(path.parents), path]:
        if item.is_symlink():
            raise ValueError(f"Refusing symlink: {item}")


def unrelated_settings(settings):
    result = copy.deepcopy(settings)
    servers = result.get("mcp_servers", {})
    servers.pop("local_memory_hub", None)
    if not servers:
        result.pop("mcp_servers", None)
    return result


def managed(text, block):
    if BEGIN in text or END in text:
        if text.count(BEGIN) != 1 or text.count(END) != 1:
            raise ValueError("Ambiguous managed markers; manual review needed")
        start, finish = text.index(BEGIN), text.index(END) + len(END)
        if finish < start:
            raise ValueError("Invalid managed marker order")
        return text[:start] + block + text[finish:]
    return text.rstrip() + ("\n\n" if text.strip() else "") + block + "\n"


def atomic(path, content):
    reject_symlinks(path)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".memory-install-")
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        reject_symlinks(path)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def install(home, apply=False, mode=None):
    home = Path(home).expanduser().absolute()
    config, agents = home / "config.toml", home / "AGENTS.md"
    override = home / "AGENTS.override.md"
    backups = home / "local-memory-install-backup"
    skill = home / "skills/local-memory"
    # Validate every destination before any writes. Only the owned final skill
    # link is permitted; its parent directories must be ordinary directories.
    for path in (home, config, agents, override, backups, backups / config.name,
                 backups / agents.name, skill.parent):
        reject_symlinks(path)
    if override.exists() and override.read_text().strip():
        raise ValueError("AGENTS.override.md is active; merge the bootstrap there explicitly first")
    old_cfg = config.read_text() if config.exists() else ""
    old_agents = agents.read_text() if agents.exists() else ""
    previous = tomllib.loads(old_cfg)
    if "local_memory_hub" in previous.get("mcp_servers", {}) and BEGIN not in old_cfg:
        raise ValueError("Unmanaged local_memory_hub registration already exists")
    current = previous.get("mcp_servers", {}).get("local_memory_hub", {})
    if mode is None:
        mode = ("pilot" if "--pilot" in current.get("args", []) else "live") if current.get("enabled", False) else "disabled"
    if mode not in {"disabled", "pilot", "live"}:
        raise ValueError("Invalid installation mode")
    if mode == "live" and not (ROOT / ".runtime/live/activation.json").is_file():
        raise ValueError("Run memory-hub activate after the desktop round-trip first")
    block = "\n".join([BEGIN, "[mcp_servers.local_memory_hub]",
                       f"command = {json.dumps(str(ROOT / 'bin/memory-hub'))}",
                       "args = " + json.dumps(["mcp", "--pilot"] if mode == "pilot" else ["mcp"]),
                       "enabled = " + ("false" if mode == "disabled" else "true"), "startup_timeout_sec = 90",
                       'enabled_tools = ["search_notes", "read_note", "write_note", "recent_activity"]', END])
    new_cfg = managed(old_cfg, block)
    parsed = tomllib.loads(new_cfg)
    if unrelated_settings(previous) != unrelated_settings(parsed):
        raise ValueError("Unrelated configuration would change")
    bootstrap = "\n".join([BEGIN,
        "For shared durable preferences, project decisions, and cross-session recall, use the",
        "local-memory skill. Before personal capture/recall, check readiness with:",
        f"`{ROOT / 'bin/memory-hub'} doctor`.",
        "Use doctor to distinguish enabled synthetic pilot from activated personal memory. Synthetic test",
        "notes are never evidence about the user. Current instructions override recalled notes.", END])
    new_agents = managed(old_agents, bootstrap)
    source = ROOT / "skills/local-memory"
    if skill.exists() or skill.is_symlink():
        if not skill.is_symlink() or skill.resolve() != source:
            raise ValueError("An unrelated local-memory skill already exists")
    summary = {"codex_home": str(home), "server": "local_memory_hub", "enabled": mode != "disabled", "mode": mode,
               "skill": str(skill), "applied": apply}
    if not apply:
        return summary
    home.mkdir(parents=True, exist_ok=True)
    # Preserve originals once; re-running never replaces the first backup.
    reject_symlinks(backups)
    backups.mkdir(mode=0o700, exist_ok=True)
    for path, old in [(config, old_cfg), (agents, old_agents)]:
        saved = backups / path.name
        reject_symlinks(saved)
        if not saved.exists():
            with saved.open("x") as stream:
                stream.write(old)
            saved.chmod(0o600)
    atomic(config, new_cfg)
    atomic(agents, new_agents)
    reject_symlinks(skill.parent)
    skill.parent.mkdir(parents=True, exist_ok=True)
    if not skill.is_symlink():
        skill.symlink_to(source, target_is_directory=True)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex-home", default=os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--mode", choices=["disabled", "pilot", "live"])
    args = parser.parse_args()
    try:
        print(json.dumps(install(args.codex_home, args.apply, args.mode), indent=2))
    except (OSError, ValueError) as error:
        parser.exit(1, str(error) + "\n")
