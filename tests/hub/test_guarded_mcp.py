import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
import tempfile
from fastmcp import FastMCP, Client

spec = importlib.util.spec_from_file_location(
    "guarded_mcp", Path(__file__).resolve().parents[2] / "scripts/guarded_mcp.py"
)
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


class GuardTests(unittest.TestCase):
    def test_live_surface_uses_validated_capture_and_refuses_raw_write(self):
        from memory_hub.capture import CaptureStore
        async def run(root):
            vault = root / "vault"
            vault.mkdir()
            server = FastMCP("synthetic-capture")
            guard.register_capture(server, lambda: CaptureStore(vault, root / "control"))
            @server.tool()
            def write_note():
                return "must not run"
            server.add_middleware(guard.OwnershipGuard())
            async with Client(server) as client:
                self.assertEqual([t.name for t in await client.list_tools()], ["capture_memory"])
                with self.assertRaises(Exception):
                    await client.call_tool("write_note", {})
                result = await client.call_tool("capture_memory", dict(title="Synthetic claim", body="A synthetic preference.",
                    subject="global", source="Synthetic user instruction", capture_id="31eb9a58-4c77-45b9-b292-309d6a864e60"))
                self.assertTrue(result.data["verified"])
        with tempfile.TemporaryDirectory() as tmp:
            asyncio.run(run(Path(tmp).resolve()))

    def test_advertised_tools_and_bounded_recall(self):
        async def run(vault):
            server = FastMCP("synthetic-hub", instructions=guard.HUB_INSTRUCTIONS)
            guard.register_recall(server, lambda: vault)

            @server.tool()
            def delete_note():
                """Must not be advertised."""
                return "bad"

            server.add_middleware(guard.OwnershipGuard())
            async with Client(server) as client:
                tools = await client.list_tools()
                self.assertEqual([t.name for t in tools], ["recall_context"])
                self.assertNotIn("At the start of a session", tools[0].description)
                result = await client.call_tool("recall_context", {"query": "deployment"})
                self.assertEqual(result.data["status"], "ok")
                self.assertEqual(result.data["records"], [])

        with tempfile.TemporaryDirectory() as tmp:
            asyncio.run(run(Path(tmp).resolve()))

    def test_subject_path_and_frontmatter_routing(self):
        for args in (
            {"metadata": {"project": "local-fitness"}},
            {"directory": "Projects/local-fitness/Preferences"},
            {"directory": "Projects/%6cocal-fitness/Preferences"},
            {"content": "---\nowner: local-fitness\n---\nfixture"},
        ):
            self.assertTrue(guard.fitness_scoped(args))
        self.assertFalse(
            guard.fitness_scoped(
                {"directory": "Preferences", "metadata": {"project": "global"}}
            )
        )

    def test_no_bypass_through_unadvertised_mutator(self):
        calls = []

        async def next_handler(context):
            calls.append(context)
            return "called"

        with self.assertRaises(guard.ToolError):
            asyncio.run(
                guard.OwnershipGuard().on_call_tool(
                    SimpleNamespace(
                        message=SimpleNamespace(name="delete_note", arguments={})
                    ),
                    next_handler,
                )
            )
        self.assertEqual(calls, [])

    def test_rejects_before_downstream_write(self):
        calls = []

        async def next_handler(context):
            calls.append(context)
            return "called"

        with self.assertRaises(guard.ToolError):
            asyncio.run(
                guard.OwnershipGuard().on_call_tool(
                    SimpleNamespace(
                        message=SimpleNamespace(
                            name="write_note",
                            arguments={"metadata": {"project": "local-fitness"}},
                        )
                    ),
                    next_handler,
                )
            )
        self.assertEqual(calls, [])
