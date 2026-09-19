#!/usr/bin/env python3
"""Native hub MCP with enforced source-owned fitness write routing."""

import sys
from pathlib import Path
import unicodedata
from urllib.parse import unquote

from fastmcp.server.middleware import Middleware
from fastmcp.exceptions import ToolError
import yaml


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
    for key in ("directory", "title", "identifier", "destination_path"):
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


class OwnershipGuard(Middleware):
    async def on_call_tool(self, context, call_next):
        if context.message.name not in {
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


def main():
    from basic_memory.mcp.server import mcp

    mcp.add_middleware(OwnershipGuard())
    from basic_memory.cli.main import app

    sys.argv = ["basic-memory", "mcp", "--project", "local-memory"]
    app()


if __name__ == "__main__":
    main()
