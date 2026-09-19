#!/usr/bin/env python3
"""Measure indexer writes in disposable synthetic vaults, never the live hub."""

import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import subprocess


async def capture_probe(engine, root, env):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(
        command=str(engine), args=["mcp", "--project", "local-memory"], env=env
    )
    with (root / "capture.log").open("w") as log:
        async with stdio_client(params, errlog=log) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                reply = await session.call_tool(
                    "write_note",
                    {
                        "project": "local-memory",
                        "title": "Synthetic capture compatibility",
                        "directory": "Inbox",
                        "content": "Synthetic probe only",
                        "overwrite": False,
                        "output_format": "json",
                        "metadata": {
                            "project": "global",
                            "status": "active",
                            "capture_id": "synthetic-compatibility",
                            "source": "probe",
                        },
                    },
                )
                payload = json.loads(reply.content[0].text)
                return {
                    "created": not reply.is_error
                    and payload.get("action") == "created",
                    "permalink_present": bool(payload.get("permalink")),
                    "file_path_present": bool(payload.get("file_path")),
                }


def run_case(engine, root, readonly_settings=False, ignored_fitness=False):
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    vault, config = root / "vault", root / "config"
    vault.mkdir()
    config.mkdir()
    settings = {
        "projects": {"local-memory": {"path": str(vault), "mode": "local"}},
        "default_project": "local-memory",
        "semantic_search_enabled": False,
        "reranker_enabled": False,
        "auto_update": False,
        "logfire_enabled": False,
        "logfire_send_to_logfire": False,
    }
    if readonly_settings:
        settings.update(ensure_frontmatter_on_sync=False, disable_permalinks=True)
    (config / "config.json").write_text(json.dumps(settings))
    if ignored_fitness:
        from basic_memory.ignore_utils import DEFAULT_IGNORE_PATTERNS

        (config / ".bmignore").write_text(
            "\n".join(sorted(DEFAULT_IGNORE_PATTERNS | {"Projects/local-fitness"}))
            + "\n"
        )
        (vault / "Projects/local-fitness").mkdir(parents=True)
    cases = {
        "canonical.md": "---\ntitle: Canonical\ntype: note\npermalink: canonical\nproject: local-fitness\nstatus: active\n---\n\n  synthetic body with whitespace  \n\n",
        "missing-frontmatter.md": "  synthetic body with whitespace  \n\n",
        "missing-permalink.md": "---\ntitle: Missing permalink\ntype: note\n---\n\n  synthetic body with whitespace  \n\n",
        "duplicate-permalink.md": "---\ntitle: Duplicate\ntype: note\npermalink: canonical\n---\n\n  synthetic duplicate body  \n\n",
    }
    if ignored_fitness:
        cases = {
            f"Projects/local-fitness/{name}": content for name, content in cases.items()
        }
    for name, content in cases.items():
        (vault / name).write_text(content)
    env = {k: v for k, v in os.environ.items() if not k.startswith("BASIC_MEMORY_")}
    env.update(
        BASIC_MEMORY_CONFIG_DIR=str(config),
        BASIC_MEMORY_HOME=str(vault),
        BASIC_MEMORY_SEMANTIC_SEARCH_ENABLED="false",
        BASIC_MEMORY_AUTO_UPDATE="false",
        BASIC_MEMORY_LOGFIRE_ENABLED="false",
        BASIC_MEMORY_LOGFIRE_SEND_TO_LOGFIRE="false",
        HF_HUB_OFFLINE="1",
    )
    with (root / "engine.log").open("w") as log:
        run = subprocess.run(
            [str(engine), "reindex", "--search", "--project", "local-memory"],
            env=env,
            stdout=log,
            stderr=log,
            timeout=90,
        )
    results = []
    for name, content in cases.items():
        actual = (vault / name).read_bytes()
        results.append(
            {
                "case": name,
                "unchanged": actual == content.encode(),
                "before": hashlib.sha256(content.encode()).hexdigest(),
                "after": hashlib.sha256(actual).hexdigest(),
            }
        )
    return {
        "engine_exit": run.returncode,
        "standard_capture": asyncio.run(
            asyncio.wait_for(capture_probe(engine, root, env), 60)
        ),
        "settings": settings,
        "files": results,
        "all_unchanged": all(r["unchanged"] for r in results),
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--engine", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    args = p.parse_args()
    os.umask(0o077)
    root = args.output_dir.resolve()
    root.mkdir(parents=True, exist_ok=False)
    result = {
        "scope": "synthetic isolated engine; not a live cutover test",
        "default": run_case(args.engine.resolve(), root / "default"),
        "readonly_candidate": run_case(args.engine.resolve(), root / "readonly", True),
        "fitness_owner_exclusion": run_case(
            args.engine.resolve(), root / "excluded", ignored_fitness=True
        ),
    }
    (root / "report.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
