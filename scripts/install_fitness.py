#!/usr/bin/env python3
"""Prepare/apply local fitness writer wiring; does not migrate or start services.

Caller must drain old writers and initialize the store before applying. Originals
are saved privately. Service lifecycle and container rebuild remain explicit.
"""

import argparse
import copy
import json
import os
from pathlib import Path
import plistlib
import re
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from memory_hub.fitness_store import atomic, safe  # noqa: E402

BEGIN = "# BEGIN FITNESS VAULT MEMORY"
END = "# END FITNESS VAULT MEMORY"


def block(text, lines):
    replacement = BEGIN + "\n" + "\n".join(lines) + "\n" + END
    if BEGIN in text or END in text:
        if text.count(BEGIN) != 1 or text.count(END) != 1:
            raise ValueError("Ambiguous managed markers")
        start, finish = text.index(BEGIN), text.index(END) + len(END)
        if finish < start:
            raise ValueError("Invalid marker order")
        return text[:start] + replacement + text[finish:]
    return text.rstrip() + "\n\n" + replacement + "\n"


def mcp_configuration(text, repo):
    """One full coach connection, shared with the project-local server key."""
    old = tomllib.loads(text)
    owned = (
        text[text.index(BEGIN) : text.index(END)]
        if BEGIN in text and END in text
        else ""
    )
    for name in ("fitness", "fitness_memory"):
        if name in old.get("mcp_servers", {}) and f"[mcp_servers.{name}]" not in owned:
            raise ValueError(f"Unmanaged {name} MCP registration exists")
    new = block(
        text,
        [
            "[mcp_servers.fitness]",
            f"command = {json.dumps(str(repo / '.venv/bin/fitness'))}",
            'args = ["mcp-stdio"]',
            f"cwd = {json.dumps(str(repo))}",
            "enabled = true",
            "startup_timeout_sec = 60",
            "tool_timeout_sec = 120",
        ],
    )
    a, b = copy.deepcopy(old), tomllib.loads(new)
    for settings in (a, b):
        for name in ("fitness", "fitness_memory"):
            settings.get("mcp_servers", {}).pop(name, None)
    if a != b:
        raise ValueError("Unrelated Codex settings changed")
    return new


def install_mcp(repo, home, apply=False):
    """Repair only the owned MCP registration, without touching live services."""
    import uuid

    repo, home = safe(repo), safe(home)
    config = safe(home / ".codex/config.toml")
    original = config.read_text()
    updated = mcp_configuration(original, repo)
    if apply and updated != original:
        directory = safe(home / ".codex/local-memory-install-backup")
        directory.mkdir(mode=0o700, exist_ok=True)
        atomic(directory / f"fitness-mcp-{uuid.uuid4()}.toml", original.encode())
        atomic(config, updated.encode())
    return {
        "applied": apply,
        "server": "fitness",
        "surface": "full coach and memory",
        "changed": original != updated,
    }


def prepare(repo, compose, control, home):
    repo, compose, control, home = map(safe, (repo, compose, control, home))
    config = json.loads((control / "config.json").read_text())
    if config["fitness_repo"] != str(repo) or config["port"] != 8766:
        raise ValueError("Writer configuration mismatch")
    changes = {}
    env = repo / ".env"
    settings = {
        "LOCAL_FITNESS_PREFERENCES_BACKEND": "vault",
        "LOCAL_FITNESS_JOURNAL_BACKEND": "vault",
        "LOCAL_FITNESS_MEMORY_URL": "http://127.0.0.1:8766/memory",
        "LOCAL_FITNESS_MEMORY_TOKEN_FILE": str(control / "token"),
    }
    original = env.read_text()
    unmanaged = original.split(BEGIN)[0]
    if any(
        re.search(r"^\s*(?:export\s+)?" + k + r"\s*=", unmanaged, re.M)
        for k in settings
    ):
        raise ValueError("Unmanaged fitness backend settings exist")
    changes[env] = block(
        original, [f"{k}={json.dumps(v)}" for k, v in settings.items()]
    ).encode()
    codex = home / ".codex/config.toml"
    changes[codex] = mcp_configuration(codex.read_text(), repo).encode()
    compose_path = compose / "docker-compose.yml"
    text = compose_path.read_text()
    start = text.index("  local-fitness:\n")
    end = re.search(r"^  [a-zA-Z][\w-]*:\s*$", text[start + 20 :], re.M)
    finish = start + 20 + end.start() if end else len(text)
    section = text[start:finish]
    if "LOCAL_FITNESS_MEMORY_URL" not in section:
        section = section.replace(
            "    environment:\n",
            "    environment:\n"
            + "".join(
                "      - " + line + "\n"
                for line in (
                    "LOCAL_FITNESS_PREFERENCES_BACKEND=vault",
                    "LOCAL_FITNESS_JOURNAL_BACKEND=vault",
                    "LOCAL_FITNESS_MEMORY_URL=http://host.docker.internal:8766/memory",
                    "LOCAL_FITNESS_MEMORY_TOKEN_FILE=/run/secrets/fitness-memory-token",
                )
            ),
        )
        section = section.replace(
            "    volumes:\n",
            "    volumes:\n      - ${FITNESS_MEMORY_TOKEN_FILE}:/run/secrets/fitness-memory-token:ro\n",
        )
    changes[compose_path] = (text[:start] + section + text[finish:]).encode()
    compose_env = compose / ".env"
    changes[compose_env] = block(
        compose_env.read_text(),
        [f"FITNESS_MEMORY_TOKEN_FILE={json.dumps(str(control / 'token'))}"],
    ).encode()
    agents = home / "Library/LaunchAgents"
    for path in sorted(agents.glob("com.localfitness.*.plist")):
        # Existing XML comments contain illegal '--'. Remove comments only;
        # preserve the parsed command, schedule, environment, and log paths.
        parsed = plistlib.loads(
            re.sub(r"<!--.*?-->", "", path.read_text(), flags=re.S).encode()
        )
        if parsed.get("RunAtLoad") or parsed.get("KeepAlive"):
            raise ValueError("Scheduler could run immediately on reload")
        changes[path] = plistlib.dumps(parsed)
    daemon = {
        "Label": "com.local-memory-hub.fitness",
        "ProgramArguments": [
            str(ROOT / ".venv/bin/python"),
            "-m",
            "memory_hub.fitness_service",
            "--config",
            str(control / "config.json"),
        ],
        "WorkingDirectory": str(ROOT),
        "RunAtLoad": True,
        "KeepAlive": True,
        "ThrottleInterval": 10,
        "EnvironmentVariables": {"PYTHONUNBUFFERED": "1"},
        "StandardOutPath": str(control / "writer.stdout.log"),
        "StandardErrorPath": str(control / "writer.stderr.log"),
    }
    changes[agents / "com.local-memory-hub.fitness.plist"] = plistlib.dumps(daemon)
    return changes


def install(repo, compose, control, home, apply=False):
    changes = prepare(repo, compose, control, home)
    backup = safe(control) / "installation-backup"
    if apply:
        backup.mkdir(mode=0o700, exist_ok=False)
        manifest = []
        for index, (path, data) in enumerate(changes.items()):
            path = safe(path)
            name = f"{index}-{path.name}"
            if path.exists():
                atomic(backup / name, path.read_bytes())
            manifest.append(
                {"path": str(path), "backup": name if path.exists() else None}
            )
        atomic(backup / "manifest.json", json.dumps(manifest).encode())
        for path, data in changes.items():
            atomic(path, data)
    return {
        "applied": apply,
        "files": [str(p) for p in changes],
        "services_started": False,
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("repo", "compose", "control"):
        p.add_argument("--" + name, type=Path, required=name == "repo")
    p.add_argument("--home", type=Path, default=Path.home())
    p.add_argument("--apply", action="store_true")
    p.add_argument("--mcp-only", action="store_true")
    a = p.parse_args()
    os.umask(0o077)
    if a.mcp_only:
        result = install_mcp(a.repo, a.home, a.apply)
    else:
        if not a.compose or not a.control:
            p.error("--compose and --control are required for a full installation")
        result = install(a.repo, a.compose, a.control, a.home, a.apply)
    print(json.dumps(result, indent=2))
