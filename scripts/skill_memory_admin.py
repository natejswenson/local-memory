#!/usr/bin/env python3
"""Explicit local setup, never exposed to recalled content or MCP calls."""

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from memory_hub.skill_contract import policies  # noqa: E402 — local checkout import
from memory_hub.skill_store import SkillStore, safe, put  # noqa: E402 — local checkout import


def configure(store, config):
    if (
        not isinstance(config, dict)
        or set(config) != {"version", "bindings"}
        or config["version"] != 1
        or not isinstance(config["bindings"], dict)
    ):
        raise ValueError("INVALID_CONFIG")
    for skill, subjects in config["bindings"].items():
        if skill not in policies() or not isinstance(subjects, dict):
            raise ValueError("UNKNOWN_SKILL")
        if policies()[skill]["mode"] == "deferred":
            raise ValueError("SKILL_DISABLED")
        for subject, b in subjects.items():
            import re

            if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,79}", subject):
                raise ValueError("INVALID_SUBJECT")
            if not isinstance(b, dict) or set(b) - {
                "enabled",
                "shared_profile",
                "source_path",
                "repo_path",
                "reads",
                "readers",
            }:
                raise ValueError("INVALID_BINDING")
            if (
                type(b.get("enabled")) is not bool
                or b.get("shared_profile") is not True
            ):
                raise ValueError("SHARING_NOT_ACKNOWLEDGED")
            if policies()[skill]["mode"] == "owner" or b.get("source_path"):
                store.source(b)
            if b.get("repo_path"):
                p = safe(b["repo_path"])
                if not Path(b["repo_path"]).is_absolute() or not p.is_dir():
                    raise ValueError("REPOSITORY_UNREGISTERED")
            if set(b.get("reads", {})) - set(
                policies()[skill]["read_keys"] + policies()[skill]["keys"]
            ):
                raise ValueError("INVALID_READER")
            if any(x not in policies() for x in b.get("readers", [])):
                raise ValueError("INVALID_READER")
    with store.locked():
        path = store.control / "config.json"
        if safe(path).exists():
            import uuid
            from memory_hub.skill_store import atomic, read

            atomic(
                store.control / "config-backups" / f"{uuid.uuid4()}.json",
                read(path, 262144),
            )
        put(path, config)
        if store.config() != config:
            raise ValueError("READBACK_FAILED")
    return {
        "configured": True,
        "bindings": sum(len(x) for x in config["bindings"].values()),
        "data_migrated": False,
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("operation", choices=["configure", "status"])
    p.add_argument("--vault", type=Path, default=ROOT / "vault")
    p.add_argument("--control", type=Path, default=ROOT / ".runtime/skill-memory")
    args = p.parse_args()
    store = SkillStore(args.vault, args.control)
    if args.operation == "configure":
        result = configure(store, json.loads(sys.stdin.read(262145)))
    else:
        result = {
            "configured": (store.control / "config.json").exists(),
            "enabled_skills": sorted(
                k
                for k, v in store.config()["bindings"].items()
                if any(b.get("enabled") for b in v.values())
            ),
        }
    print(json.dumps(result))


if __name__ == "__main__":
    main()
