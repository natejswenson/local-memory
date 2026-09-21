import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import uuid
from datetime import date, timedelta
from memory_hub.skill_contract import CONTRACT, digest, policies, validate_value
from memory_hub.skill_store import SkillStore, atomic, put

ROOT = Path(__file__).resolve().parents[2]


class SkillMemoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.vault = self.root / "vault"
        self.vault.mkdir()
        self.control = self.root / "control"
        self.control.mkdir()
        self.source = self.root / "voice.md"
        self.source.write_text("Original voice.\n")
        self.repo = self.root / "repo"
        self.repo.mkdir()
        (self.repo / "policy.md").write_text("Verified constraint.")
        bindings = {
            s: {
                "fixture": {
                    "enabled": True,
                    "shared_profile": True,
                    "repo_path": str(self.repo),
                }
            }
            for s, p in policies().items()
            if p["mode"] != "deferred"
        }
        for s in ("ghostwriter", "ghostwriter-x"):
            bindings[s]["fixture"]["source_path"] = str(self.source)
        bindings["ghostwriter"]["fixture"]["readers"] = ["devlog"]
        bindings["devlog"]["fixture"].update(
            source_path=str(self.source),
            reads={"writing.hashtags": {"skill": "ghostwriter", "subject": "fixture"}},
        )
        put(self.control / "config.json", {"version": 1, "bindings": bindings})
        self.store = SkillStore(self.vault, self.control)

    def request(self, op="capture", skill="issuecreator", **kw):
        return self.store.request(
            {"contract": CONTRACT, "skill": skill, "subject": "fixture", "op": op, **kw}
        )

    def capture(self, **kw):
        return self.request(
            key="issue.acceptance-style",
            value="Use observable outcomes.",
            source="Synthetic instruction",
            capture_id=str(uuid.uuid4()),
            **kw,
        )

    def test_multi_key_recall_reads_scope_once_and_refreshes_next_request(self):
        saved = self.capture()
        with patch.object(self.store, "records", wraps=self.store.records) as scan:
            got = self.request("recall", keys=["issue.acceptance-style", "project.design-rationale"])
            self.assertEqual(scan.call_count, 1)
            self.assertEqual(got["records"][0]["value"], "Use observable outcomes.")
        path = self.store.path(saved["record"]["id"], "issuecreator", "fixture")
        path.write_text(path.read_text().replace("Use observable outcomes.", "Use measurable outcomes."))
        got = self.request("recall", keys=["issue.acceptance-style"])
        self.assertEqual(got["records"][0]["value"], "Use measurable outcomes.")

    def test_capture_recall_correction_forget_restart(self):
        a = self.capture()
        self.assertEqual(a["status"], "saved", a)
        b = self.capture(supersedes=a["record"]["id"])
        self.assertEqual(b["status"], "saved", b)
        got = self.request("recall", keys=["issue.acceptance-style"])
        self.assertEqual([b["record"]], got["records"])
        bad = self.request("forget", id=b["record"]["id"], expected_revision="stale")
        self.assertEqual(bad["status"], "conflict")
        gone = self.request(
            "forget", id=b["record"]["id"], expected_revision=b["record"]["revision"]
        )
        self.assertEqual(gone["status"], "forgotten")
        self.store = SkillStore(self.vault, self.control)
        self.assertEqual(
            self.request("recall", keys=["issue.acceptance-style"])["records"], []
        )
        self.assertFalse(list(self.store.notes.rglob("*.md")))

    def test_idempotency_lost_reply_and_payload_conflict(self):
        q = dict(
            key="issue.acceptance-style",
            value="Literal `$()`; never executed.",
            source="Synthetic instruction",
            capture_id=str(uuid.uuid4()),
        )
        a = self.request(**q)
        b = self.request(**q)
        self.assertEqual(a, b)
        c = self.request(**{**q, "value": "Changed"})
        self.assertEqual(c["status"], "conflict")
        self.assertEqual(len(list(self.store.notes.rglob("*.md"))), 1)

    def test_source_first_single_write_and_recall_staleness(self):
        q = dict(
            skill="ghostwriter",
            key="writing.hashtags",
            value="Avoid hashtags.",
            source="Synthetic correction",
            capture_id=str(uuid.uuid4()),
            expected_source_revision=digest(self.source.read_bytes()),
        )
        result = self.request(**q)
        self.assertEqual(result["status"], "saved", result)
        once = self.source.read_bytes()
        self.assertEqual(once.count(b"Avoid hashtags."), 1)
        self.assertEqual(self.request(**q), result)
        self.assertEqual(self.source.read_bytes(), once)
        self.source.write_text("External edit")
        self.assertEqual(
            self.request("recall", skill="ghostwriter", keys=["writing.hashtags"])[
                "status"
            ],
            "conflict",
        )

    def test_source_failure_cannot_claim_save(self):
        import memory_hub.skill_store as mod

        original = mod.atomic

        def fail(path, raw):
            if Path(path) == self.source:
                raise OSError("synthetic")
            return original(path, raw)

        q = dict(
            skill="ghostwriter",
            key="writing.hashtags",
            value="No hashtags.",
            source="Synthetic",
            capture_id=str(uuid.uuid4()),
            expected_source_revision=digest(self.source.read_bytes()),
        )
        with patch.object(mod, "atomic", side_effect=fail):
            result = self.request(**q)
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(self.source.read_text(), "Original voice.\n")
        self.assertEqual(
            self.request(**q)["status"], "conflict"
        )  # prepared event never overwrites source on replay

    def test_pending_mirror_recovers_without_reappending(self):
        import memory_hub.skill_store as mod

        original = mod.atomic

        def fail(path, raw):
            if self.store.notes in Path(path).parents:
                raise OSError("synthetic")
            return original(path, raw)

        q = dict(
            skill="ghostwriter-x",
            key="writing-x.hashtags",
            value="No hashtags.",
            source="Synthetic",
            capture_id=str(uuid.uuid4()),
            expected_source_revision=digest(self.source.read_bytes()),
        )
        with patch.object(mod, "atomic", side_effect=fail):
            result = self.request(**q)
        self.assertEqual(result["status"], "source_saved_memory_pending", result)
        once = self.source.read_bytes()
        self.assertEqual(self.request(**q)["status"], "saved")
        self.assertEqual(self.source.read_bytes(), once)

    def test_source_changed_while_pending_is_conflict(self):
        q = dict(
            skill="ghostwriter",
            key="writing.hashtags",
            value="No hashtags.",
            source="Synthetic",
            capture_id=str(uuid.uuid4()),
            expected_source_revision=digest(self.source.read_bytes()),
        )
        with patch.object(self.store, "recover_event", side_effect=OSError):
            self.assertEqual(self.request(**q)["status"], "source_saved_memory_pending")
        self.source.write_text("Manual change")
        self.assertEqual(self.request(**q)["status"], "conflict")
        self.assertEqual(self.source.read_text(), "Manual change")

    def test_sharing_requires_matching_source_reader_and_revision(self):
        self.request(
            skill="ghostwriter",
            key="writing.hashtags",
            value="No hashtags.",
            source="Synthetic",
            capture_id=str(uuid.uuid4()),
            expected_source_revision=digest(self.source.read_bytes()),
        )
        revision = digest(self.source.read_bytes())
        self.assertEqual(
            self.request(
                "recall",
                skill="devlog",
                keys=["writing.hashtags"],
                expected_source_revision=revision,
            )["status"],
            "ok",
        )
        self.assertEqual(
            self.request("recall", skill="devlog", keys=["writing.hashtags"])["status"],
            "conflict",
        )
        cfg = self.store.config()
        cfg["bindings"]["ghostwriter"]["fixture"]["readers"] = []
        put(self.control / "config.json", cfg)
        self.assertEqual(
            self.request(
                "recall",
                skill="devlog",
                keys=["writing.hashtags"],
                expected_source_revision=revision,
            )["status"],
            "conflict",
        )

    def test_rationale_live_revision_expiry_and_wrong_scope(self):
        q = dict(
            key="project.design-rationale",
            value="Use a single writer.",
            source="Synthetic checked file",
            capture_id=str(uuid.uuid4()),
            dependencies=[
                {
                    "path": "policy.md",
                    "revision": digest((self.repo / "policy.md").read_bytes()),
                }
            ],
            review_after=(date.today() + timedelta(days=5)).isoformat(),
        )
        self.assertEqual(self.request(**q)["status"], "saved")
        self.assertEqual(
            self.request("recall", keys=["project.design-rationale"])["status"], "ok"
        )
        (self.repo / "policy.md").write_text("Changed")
        self.assertEqual(
            self.request("recall", keys=["project.design-rationale"])["status"],
            "conflict",
        )
        self.assertEqual(
            self.store.request(
                {
                    "contract": CONTRACT,
                    "skill": "issuecreator",
                    "subject": "unknown",
                    "op": "recall",
                    "keys": ["project.design-rationale"],
                }
            )["status"],
            "disabled",
        )

    def test_deferred_and_unknown_keys_cannot_write(self):
        for skill, p in policies().items():
            if p["mode"] == "deferred":
                self.assertEqual(
                    self.request(
                        skill=skill,
                        key="invented.key",
                        value="test",
                        capture_id=str(uuid.uuid4()),
                        source="Synthetic",
                    )["status"],
                    "disabled",
                )
        self.assertEqual(
            self.request(
                key="writing.hashtags",
                value="test",
                capture_id=str(uuid.uuid4()),
                source="Synthetic",
            )["status"],
            "rejected",
        )
        self.assertFalse(self.store.notes.exists())

    def test_response_budget_manual_edit_and_secret_rejection(self):
        self.assertEqual(self.capture()["status"], "saved")
        result = self.request(
            "recall", keys=["issue.acceptance-style"], max_context_bytes=256
        )
        self.assertEqual(result["records"], [])
        self.assertIn("issue.acceptance-style", result["withheld_keys"])
        self.assertEqual(
            self.request(
                key="issue.acceptance-style",
                value="ghp_" + "x" * 30,
                source="Synthetic",
                capture_id=str(uuid.uuid4()),
            )["status"],
            "rejected",
        )

    def test_symlink_source_and_namespace_refused(self):
        self.source.unlink()
        self.source.symlink_to(self.repo / "policy.md")
        self.assertEqual(
            self.request("status", skill="ghostwriter")["status"], "rejected"
        )
        self.assertEqual(
            self.request("capture", directory="../../escape")["status"], "rejected"
        )

    def test_restore_cannot_resurrect_suppressed_note(self):
        a = self.capture()
        r = a["record"]
        raw = self.store.path(r["id"], "issuecreator", "fixture").read_bytes()
        self.request("forget", id=r["id"], expected_revision=r["revision"])
        atomic(self.store.path(r["id"], "issuecreator", "fixture"), raw)
        self.assertEqual(
            self.request("recall", keys=["issue.acceptance-style"])["records"], []
        )

    def test_admin_rejects_deferred_and_missing_consent(self):
        spec = importlib.util.spec_from_file_location(
            "skill_admin", ROOT / "scripts/skill_memory_admin.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        for config in (
            {
                "version": 1,
                "bindings": {
                    "netwatch": {"fixture": {"enabled": True, "shared_profile": True}}
                },
            },
            {
                "version": 1,
                "bindings": {"issuecreator": {"fixture": {"enabled": True}}},
            },
        ):
            with self.assertRaises(ValueError):
                mod.configure(self.store, config)
        self.assertTrue(mod.configure(self.store, self.store.config())["configured"])

    def test_forget_crash_suppresses_whole_lineage_and_retry_purges(self):
        a = self.capture()
        b = self.capture(supersedes=a["record"]["id"])
        r = b["record"]
        with patch.object(self.store, "finish_forget", side_effect=OSError("crash")):
            self.assertEqual(
                self.request("forget", id=r["id"], expected_revision=r["revision"])[
                    "status"
                ],
                "unavailable",
            )
        self.assertEqual(
            self.request("recall", keys=["issue.acceptance-style"])["records"], []
        )
        self.assertTrue(list(self.store.notes.rglob("*.md")))
        self.assertEqual(
            self.request("forget", id=r["id"], expected_revision=r["revision"])[
                "status"
            ],
            "forgotten",
        )
        self.assertFalse(list(self.store.notes.rglob("*.md")))

    def test_pending_advisory_cannot_create_second_root(self):
        q = dict(
            key="issue.acceptance-style",
            value="First candidate",
            source="Synthetic",
            capture_id=str(uuid.uuid4()),
        )
        with patch.object(self.store, "recover_event", side_effect=OSError("crash")):
            self.assertEqual(self.request(**q)["status"], "unavailable")
        self.assertEqual(self.capture()["status"], "saved")
        self.assertEqual(self.request(**q)["status"], "conflict")
        self.assertEqual(
            len(self.request("recall", keys=["issue.acceptance-style"])["records"]), 1
        )

    def test_owner_mirror_tampering_is_not_source_truth(self):
        a = self.request(
            skill="ghostwriter",
            key="writing.hashtags",
            value="No hashtags.",
            source="Synthetic",
            capture_id=str(uuid.uuid4()),
            expected_source_revision=digest(self.source.read_bytes()),
        )
        p = self.store.path(a["record"]["id"], "ghostwriter", "fixture")
        p.write_text(p.read_text().replace("No hashtags.", "Many hashtags."))
        self.assertEqual(
            self.request("recall", skill="ghostwriter", keys=["writing.hashtags"])[
                "status"
            ],
            "conflict",
        )

    def test_unrelated_malformed_scope_does_not_poison_recall(self):
        self.capture()
        bad = self.store.path(str(uuid.uuid4()), "ghostwriter", "other-subject")
        bad.parent.mkdir(parents=True)
        bad.write_text("not a valid note")
        self.assertEqual(
            self.request("recall", keys=["issue.acceptance-style"])["status"], "ok"
        )

    def test_irrelevant_oversize_metadata_rejected_before_persistence(self):
        self.assertEqual(self.capture(dependencies=["x" * 17000])["status"], "rejected")
        self.assertFalse(self.store.notes.exists())
        self.assertFalse((self.control / "events").exists())
        self.assertEqual(self.capture()["status"], "saved")

    def test_cross_skill_rationale_requires_explicit_binding_and_same_repo(self):
        q = dict(
            key="project.design-rationale",
            value="One writer.",
            source="Synthetic",
            capture_id=str(uuid.uuid4()),
            dependencies=[
                {
                    "path": "policy.md",
                    "revision": digest((self.repo / "policy.md").read_bytes()),
                }
            ],
            review_after=date.today().isoformat(),
        )
        self.assertEqual(self.request(**q)["status"], "saved")
        self.assertEqual(
            self.request(
                "recall", skill="issueflow", keys=["project.design-rationale"]
            )["records"],
            [],
        )
        c = self.store.config()
        c["bindings"]["issuecreator"]["fixture"]["readers"] = ["issueflow"]
        c["bindings"]["issueflow"]["fixture"]["reads"] = {
            "project.design-rationale": {"skill": "issuecreator", "subject": "fixture"}
        }
        put(self.control / "config.json", c)
        self.assertEqual(
            len(
                self.request(
                    "recall", skill="issueflow", keys=["project.design-rationale"]
                )["records"]
            ),
            1,
        )
        self.assertEqual(
            self.request(skill="issueflow", **q)["error"], "OWNER_REQUIRED"
        )

    def test_inspect_long_stale_history_returns_only_current_handle(self):
        current = None
        for _ in range(21):
            args = {"supersedes": current["id"]} if current else {}
            saved = self.request(
                skill="ghostwriter",
                key="writing.hashtags",
                value="Avoid hashtags.",
                source="Synthetic correction",
                capture_id=str(uuid.uuid4()),
                expected_source_revision=digest(self.source.read_bytes()),
                **args,
            )
            self.assertEqual(saved["status"], "saved", saved)
            current = saved["record"]
        self.source.write_text("External source edit")
        inspection = self.request(
            "inspect", skill="ghostwriter", keys=["writing.hashtags"]
        )
        self.assertEqual(inspection["status"], "inspection")
        self.assertEqual(len(inspection["records"]), 1)
        handle = inspection["records"][0]
        self.assertEqual(handle["id"], current["id"])
        self.assertEqual(handle["state"], "current")
        self.assertEqual(handle["evidence_state"], "stale")
        gone = self.request(
            "forget",
            skill="ghostwriter",
            id=handle["id"],
            expected_revision=handle["revision"],
        )
        self.assertEqual(gone["status"], "forgotten")

    def test_stale_owner_can_be_inspected_corrected_and_forgotten(self):
        a = self.request(
            skill="ghostwriter",
            key="writing.hashtags",
            value="No hashtags.",
            source="Synthetic",
            capture_id=str(uuid.uuid4()),
            expected_source_revision=digest(self.source.read_bytes()),
        )
        self.source.write_text(self.source.read_text() + "New unrelated voice note.\n")
        self.assertEqual(
            self.request("recall", skill="ghostwriter", keys=["writing.hashtags"])[
                "status"
            ],
            "conflict",
        )
        inspection = self.request(
            "inspect", skill="ghostwriter", keys=["writing.hashtags"]
        )
        self.assertEqual(inspection["status"], "inspection")
        self.assertEqual(inspection["records"][0]["id"], a["record"]["id"])
        self.assertNotIn("value", inspection["records"][0])
        b = self.request(
            skill="ghostwriter",
            key="writing.hashtags",
            value="Still no hashtags.",
            source="Synthetic correction",
            capture_id=str(uuid.uuid4()),
            supersedes=a["record"]["id"],
            expected_source_revision=digest(self.source.read_bytes()),
        )
        self.assertEqual(b["status"], "saved", b)
        self.assertEqual(
            self.request(
                "forget",
                skill="ghostwriter",
                id=b["record"]["id"],
                expected_revision=b["record"]["revision"],
            )["status"],
            "forgotten",
        )

    def test_malformed_metadata_and_config_are_bounded_rejections(self):
        a = self.capture()
        p = self.store.path(a["record"]["id"], "issuecreator", "fixture")
        p.write_text("---\n[]\n---\nbody\n")
        self.assertEqual(
            self.request("recall", keys=["issue.acceptance-style"])["status"],
            "conflict",
        )
        put(self.control / "config.json", [])
        self.assertEqual(self.request("status")["status"], "rejected")


class MCPIntegrationTests(unittest.TestCase):
    setUp = SkillMemoryTests.setUp

    def test_real_fastmcp_transport_roundtrip_and_guard(self):
        import asyncio
        from fastmcp import FastMCP, Client

        spec = importlib.util.spec_from_file_location(
            "skill_guard", ROOT / "scripts/guarded_mcp.py"
        )
        g = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(g)
        server = FastMCP("synthetic-skill-memory")
        g.register_skill_memory(server, lambda: self.store)
        server.add_middleware(g.OwnershipGuard())

        async def check():
            async with Client(server) as client:
                tools = await client.list_tools()
                self.assertIn("skill_memory", [t.name for t in tools])
                q = {
                    "contract": CONTRACT,
                    "skill": "issuecreator",
                    "subject": "fixture",
                    "op": "capture",
                    "key": "issue.acceptance-style",
                    "value": "Observable outcomes",
                    "source": "Synthetic MCP test",
                    "capture_id": str(uuid.uuid4()),
                }
                result = await client.call_tool("skill_memory", {"request": q})
                self.assertEqual(result.data["status"], "saved")
                q = {k: q[k] for k in ("contract", "skill", "subject")}
                q.update(op="recall", keys=["issue.acceptance-style"])
                got = await client.call_tool("skill_memory", {"request": q})
                self.assertEqual(got.data["records"][0]["value"], "Observable outcomes")

        asyncio.run(check())

    def test_guard_and_pilot_do_not_bypass_managed_profile(self):
        spec = importlib.util.spec_from_file_location(
            "skill_guard", ROOT / "scripts/guarded_mcp.py"
        )
        g = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(g)
        for args in (
            {"directory": "SkillMemory"},
            {"identifier": "Skill%4demory/test"},
            {"content": "---\ncontract: skill-memory-v1\n---\nfixture"},
        ):
            self.assertTrue(g.skill_scoped(args))
        with (
            patch.object(g, "ROOT", self.root),
            patch.dict(
                "os.environ",
                {"BASIC_MEMORY_HOME": str(self.root / ".runtime/pilot/vault")},
            ),
        ):
            store = g.skill_store()
            self.assertEqual(store.control, self.root / ".runtime/pilot/skill-memory")
            self.assertNotEqual(store.vault, self.vault)

    def test_transport_aliases_cannot_bypass_reserved_namespaces(self):
        import asyncio
        from typing import Annotated
        from pydantic import Field, AliasChoices
        from fastmcp import FastMCP, Client
        from fastmcp.exceptions import ToolError

        spec = importlib.util.spec_from_file_location(
            "alias_guard", ROOT / "scripts/guarded_mcp.py"
        )
        g = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(g)
        server = FastMCP("synthetic-alias-test")
        calls = []

        @server.tool()
        def write_note(
            directory: Annotated[
                str,
                Field(
                    validation_alias=AliasChoices("directory", "folder", "dir", "path")
                ),
            ],
        ):
            calls.append(directory)
            return "should not run"

        server.add_middleware(g.OwnershipGuard())

        async def check():
            async with Client(server) as client:
                for alias in ("directory", "folder", "dir", "path"):
                    for value in ("SkillMemory", "Projects/local-fitness"):
                        with self.assertRaises(ToolError):
                            await client.call_tool("write_note", {alias: value})

        asyncio.run(check())
        self.assertEqual(calls, [])


class PublishedContractCases(unittest.TestCase):
    def test_all_22_policies_and_invented_cases(self):
        cases = json.loads(
            (ROOT / "tests/fixtures/skill-memory-cases.json").read_text()
        )
        self.assertEqual({r["skill"] for r in cases}, set(policies()))
        total = 0
        for row in cases:
            for good in row["allowed"]:
                validate_value(row["skill"], good["key"], good["value"])
                total += 1
            for bad in row["rejected"]:
                with self.assertRaises((ValueError, TypeError)):
                    validate_value(row["skill"], bad["key"], bad["value"])
                total += 1
        self.assertGreaterEqual(total, 114)


if __name__ == "__main__":
    unittest.main()
