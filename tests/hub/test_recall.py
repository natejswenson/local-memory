from datetime import date
import json
from pathlib import Path
import tempfile
import unittest
import uuid
import importlib.util

import yaml

from memory_hub.recall import encoded, recall_context


class RecallTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.vault = Path(self.tmp.name).resolve()

    def note(self, name, body="Synthetic deployment decision.", **metadata):
        m = dict(title=name, type="note", permalink=f"local-memory/{name}",
                 project="local-memory", status="active", source="Synthetic fixture",
                 capture_id=str(uuid.uuid4()))
        m.update(metadata)
        p = self.vault / f"{name}.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("---\n" + yaml.safe_dump(m) + "---\n" + body + "\n")
        return p

    def recall(self, query="deployment", **kw):
        return recall_context(self.vault, query=query, subject="local-memory",
                              today=date(2026, 9, 19), **kw)

    def test_scope_lifecycle_and_owner_exclusions(self):
        self.note("current")
        self.note("global", project="global")
        self.note("other", project="another-project")
        self.note("candidate", status="candidate")
        self.note("archived", status="archived")
        for path in ["SkillMemory/private.md", "Projects/local-fitness/private.md",
                     ".issueflow/private.md", "issueflow/private.md", "Templates/Decision.md",
                     "Scratch/plain.md", "Clippings/article.md", "Projects/Scratch/plain.md"]:
            p = self.vault / path
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("deliberately malformed private content")
        result = self.recall()
        self.assertEqual({r["title"] for r in result["records"]}, {"current", "global"})
        global_only = recall_context(self.vault, query="deployment")
        self.assertEqual([r["title"] for r in global_only["records"]], ["global"])

    def test_common_words_do_not_create_irrelevant_evidence(self):
        self.note("garden", "The garden has blue flowers.")
        self.assertEqual(self.recall("What is the Kubernetes rollback policy?")["records"], [])
        self.assertEqual(self.recall("the and how should we")["records"], [])

    def test_exact_keys_are_exclusive_even_when_query_matches_other_notes(self):
        self.note("intended", key="deployment.policy")
        self.note("other", "Deployment deployment deployment deployment.")
        self.assertEqual([r["title"] for r in self.recall(keys=["deployment.policy"])["records"]], ["intended"])

    def test_semantic_candidates_still_obey_scope_corrections_and_freshness(self):
        self.note("old", "Hardware security keys.", key="login")
        self.note("new", "Use passkeys.", key="login", supersedes="local-memory/old", review_after="2000-01-01")
        self.note("other", project="another-project")
        seen = []
        def rank(rows, query):
            seen.extend(r["path"] for r in rows)
            return {"old.md": .9, "other.md": 1.0}
        result = self.recall("employees sign in", semantic_ranker=rank)
        self.assertEqual(result["records"], [])
        self.assertEqual(result["withheld"], {"overdue": 1})
        self.assertNotIn("other.md", seen)

    def test_semantic_outage_is_disclosed_with_valid_lexical_results(self):
        self.note("current")
        def broken(rows, query):
            raise OSError("offline model unavailable")
        result = self.recall(semantic_ranker=broken)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["withheld"], {"semantic_unavailable": 1})
        self.assertEqual(len(result["records"]), 1)

    def test_correction_outside_discovery_window(self):
        self.note("old", "Deployment uses hashtags.", key="format")
        for i in range(8):
            self.note(f"filler-{i}", "Hashtags are a synthetic distractor.")
        self.note("new", "Use plain text only.", key="format", supersedes="local-memory/old")
        result = self.recall("hashtags", keys=["format"])
        self.assertIn("new", [r["title"] for r in result["records"]])
        self.assertNotIn("old", [r["title"] for r in result["records"]])
        # Exact-key selection also finds a differently worded replacement.
        self.assertEqual(self.recall("", keys=["format"])["records"][0]["title"], "new")

    def test_stale_terminal_withholds_entire_chain(self):
        self.note("old", key="deploy")
        self.note("new", key="deploy", supersedes="local-memory/old", review_after="2026-09-18")
        result = self.recall()
        self.assertEqual(result["records"], [])
        self.assertEqual(result["withheld"], {"overdue": 1})
        self.assertEqual(result["status"], "partial")

    def test_valid_terminal_can_replace_stale_predecessor(self):
        self.note("old", key="deploy", review_after="2020-01-01")
        self.note("new", key="deploy", supersedes="memory://local-memory/old",
                  review_after="2026-09-19")
        self.assertEqual(self.recall()["records"][0]["title"], "new")

    def test_forks_roots_cycles_and_missing_parents_withheld(self):
        for links in [None, {"a": "b", "b": "a"}, {"a": "missing"},
                      {"b": "a", "c": "a"}]:
            with self.subTest(links=links), tempfile.TemporaryDirectory() as tmp:
                prior, self.vault = self.vault, Path(tmp).resolve()
                try:
                    for name in ["a", "b", "c"]:
                        kw = {"supersedes": f"local-memory/{links[name]}"} if links and name in links else {}
                        self.note(name, key="deploy", **kw)
                    self.assertEqual(self.recall()["withheld"], {"conflict": 1})
                    self.assertEqual(self.recall()["records"], [])
                finally:
                    self.vault = prior

    def test_invalid_metadata_never_becomes_evidence(self):
        self.note("missing-source", source="")
        self.note("bad-date", review_after="yesterday")
        self.note("empty", body="")
        result = self.recall("", keys=["unused"])
        self.assertEqual(result["records"], [])
        result = self.recall()
        self.assertEqual(result["records"], [])
        self.assertEqual(result["withheld"], {"invalid_metadata": 2})

    def test_current_markdown_is_read_on_every_request(self):
        path = self.note("fresh", "Deployment marker FIRST.")
        one = self.recall()["records"][0]
        path.write_text(path.read_text().replace("FIRST", "SECOND"))
        two = self.recall()["records"][0]
        self.assertIn("SECOND", two["content"])
        self.assertNotEqual(one["revision"], two["revision"])
        path.unlink()
        self.assertEqual(self.recall()["records"], [])

    def test_budget_counts_utf8_and_omits_whole_notes(self):
        self.note("large", "Deployment " + "é" * 4000)
        self.note("small", "Deployment uses local checks.")
        for budget in [512, 1024, 4096, 8192]:
            result = self.recall(max_context_bytes=budget)
            self.assertLessEqual(len(encoded(result)), budget)
            self.assertNotIn("large", [r["title"] for r in result["records"]])
        self.assertIn("small", [r["title"] for r in self.recall(max_context_bytes=1024)["records"]])

    def test_malformed_oversized_and_symlink_fail_visibly(self):
        p = self.vault / "broken.md"
        for content in ["---\n[malformed\n---\n", "no frontmatter", "x" * 65537]:
            p.write_text(content)
            self.assertEqual(self.recall()["status"], "unavailable")
        p.unlink()
        p.symlink_to(self.vault / "missing")
        self.assertEqual(self.recall()["status"], "unavailable")

    def test_missing_vault_and_invalid_inputs_are_not_empty_success(self):
        self.assertEqual(recall_context(self.vault / "absent", query="x")["status"], "unavailable")
        for kw in [{"subject": "local-fitness"}, {"subject": "unregistered"},
                   {"subject": []}, {"max_context_bytes": 8193}, {"max_notes": True},
                   {"query": ""}, {"keys": [None]}, {"query": "x" * 513}]:
            args = {"query": "deployment", **kw}
            self.assertEqual(recall_context(self.vault, **args)["status"], "rejected")

    def test_same_key_different_projects_stays_explicit(self):
        self.note("global", key="format", project="global")
        self.note("local", key="format")
        result = self.recall("", keys=["format"])
        self.assertEqual({r["project"] for r in result["records"]}, {"global", "local-memory"})

    def test_synthetic_relevance_corpus(self):
        path = Path(__file__).parents[2] / "scripts/evaluate_recall.py"
        spec = importlib.util.spec_from_file_location("evaluate_recall", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        result = module.evaluate()
        self.assertEqual(result["cases"], 50)
        self.assertEqual(result["passed"], result["cases"], result)


if __name__ == "__main__":
    unittest.main()
