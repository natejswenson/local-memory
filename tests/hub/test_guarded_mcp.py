import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest

spec = importlib.util.spec_from_file_location(
    "guarded_mcp", Path(__file__).resolve().parents[2] / "scripts/guarded_mcp.py"
)
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


class GuardTests(unittest.TestCase):
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
