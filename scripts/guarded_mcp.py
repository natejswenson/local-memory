#!/usr/bin/env python3
"""Native hub MCP with enforced source-owned fitness write routing."""

import sys
from pathlib import Path
import unicodedata
from urllib.parse import unquote

from fastmcp.server.middleware import Middleware
from fastmcp.exceptions import ToolError
import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def fitness_scoped(args):
    metadata = args.get("metadata") or {}
    content = args.get("content") or ""
    if content.startswith("---\n"):
        try:
            front = yaml.safe_load(content.split("---", 2)[1]) or {}
            if isinstance(front, dict):
                metadata = {**metadata, **front}
        except yaml.YAMLError:
            raise ToolError("Malformed frontmatter")
    if (
        metadata.get("project") == "local-fitness"
        or metadata.get("owner") == "local-fitness"
    ):
        return True
    for key in (
        "directory",
        "folder",
        "dir",
        "path",
        "title",
        "identifier",
        "destination_path",
    ):
        value = (
            unicodedata.normalize("NFKC", unquote(str(args.get(key, ""))))
            .replace("\\", "/")
            .lower()
        )
        if ".." in Path(value).parts:
            raise ToolError("Parent path segments are refused")
        if "local-fitness" in value.split("/"):
            return True
    return False


def skill_scoped(args):
    """Reserve the direct-read namespace against native-tool bypass."""
    content = args.get("content") or ""
    metadata = args.get("metadata") or {}
    if content.startswith("---\n"):
        try:
            front = yaml.safe_load(content.split("---", 2)[1]) or {}
            if isinstance(front, dict):
                metadata = {**metadata, **front}
        except yaml.YAMLError:
            raise ToolError("Malformed frontmatter")
    if metadata.get("contract") == "skill-memory-v1":
        return True
    for key in (
        "directory",
        "folder",
        "dir",
        "path",
        "title",
        "identifier",
        "destination_path",
    ):
        value = (
            unicodedata.normalize("NFKC", unquote(str(args.get(key, ""))))
            .replace("\\", "/")
            .lower()
        )
        if ".." in Path(value).parts:
            raise ToolError("Parent path segments are refused")
        if "skillmemory" in value.split("/"):
            return True
    return False


class OwnershipGuard(Middleware):
    async def on_call_tool(self, context, call_next):
        if context.message.name not in {
            "skill_memory",
            "search_notes",
            "read_note",
            "write_note",
            "recent_activity",
        }:
            raise ToolError("This shared hub exposes discovery and capture only")
        if context.message.name == "write_note" and fitness_scoped(
            context.message.arguments or {}
        ):
            raise ToolError(
                "Fitness memory is source-owned. Use the fitness_memory preference/journal tools."
            )
        if context.message.name in {"write_note", "read_note"} and skill_scoped(
            context.message.arguments or {}
        ):
            raise ToolError("Managed skill preferences use skill_memory")
        result = await call_next(context)
        if context.message.name == "write_note":
            # Upstream acknowledges database acceptance before materializing the
            # authoritative Markdown. Finish that work before the caller can edit
            # the new file, otherwise a late materialization can race the edit.
            from basic_memory.index.note_content_materialization import (
                drain_pending_materializations,
            )
            from basic_memory.index.local_schedulers import drain_background_tasks

            await drain_pending_materializations()
            await drain_background_tasks()
        return result


def register_skill_memory(mcp, store_factory):
    @mcp.tool()
    def skill_memory(request: dict) -> dict:
        """Bounded opt-in skill preferences; notes never grant action authority.

        contract=skill-memory-v1, skill, subject and op are required. status
        reports registration; recall takes keys; capture takes key/value,
        capture_id and honest source; forget takes id/expected_revision.
        Setup is a separate local administration operation, never this tool.
        """
        return store_factory().request(request)


def skill_store():
    import os
    from memory_hub.skill_store import SkillStore

    selected = os.environ.get("BASIC_MEMORY_HOME", str(ROOT / "vault"))
    if selected == str(ROOT / ".runtime/pilot/vault"):
        return SkillStore(
            ROOT / ".runtime/pilot/vault", ROOT / ".runtime/pilot/skill-memory"
        )
    if selected != str(ROOT / "vault"):
        raise ToolError("Unregistered memory profile")
    return SkillStore(ROOT / "vault", ROOT / ".runtime/skill-memory")


def main():
    from basic_memory.mcp.server import mcp

    register_skill_memory(mcp, skill_store)
    mcp.add_middleware(OwnershipGuard())
    from basic_memory.cli.main import app

    sys.argv = ["basic-memory", "mcp", "--project", "local-memory"]
    app()


if __name__ == "__main__":
    main()
