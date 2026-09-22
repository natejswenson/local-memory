from pathlib import Path
import tempfile
import unittest

from memory_hub.semantic import LocalRanker


class SyntheticProvider:
    def __init__(self):
        self.documents = []

    async def embed_documents(self, texts):
        self.documents.extend(texts)
        return [[1., 0.] if "authentication" in t else [0., 1.] for t in texts]

    async def embed_query(self, text):
        return [1., 0.]


class SemanticTests(unittest.TestCase):
    def test_revision_cache_updates_and_evicts_deleted_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            provider = SyntheticProvider()
            rank = LocalRanker(Path(tmp).resolve(), provider=provider)
            first = {"path": "one.md", "revision": "one", "meta": {"title": "Synthetic"}, "body": "authentication"}
            self.assertEqual(rank([first], "sign in"), {"one.md": 1.})
            rank([first], "sign in")
            self.assertEqual(len(provider.documents), 1)
            second = {**first, "revision": "two", "body": "flowers"}
            self.assertEqual(rank([second], "sign in"), {})
            self.assertNotIn(rank.key(first), rank.vectors)
            self.assertEqual(len(provider.documents), 2)
            self.assertEqual(rank([], "sign in"), {})
            rank.reconcile(set())
            self.assertEqual(rank.vectors, {})

    def test_scope_switch_reuses_vectors_and_budget_evicts(self):
        with tempfile.TemporaryDirectory() as tmp:
            provider = SyntheticProvider()
            rank = LocalRanker(Path(tmp).resolve(), provider=provider)
            a = dict(path='a.md', revision='a1', meta={}, body='authentication')
            b = dict(path='b.md', revision='b1', meta={}, body='flowers')
            rank([a], 'login'); rank([b], 'login'); rank([a], 'login')
            self.assertEqual(len(provider.documents), 2)
            rank.max_cache_bytes = rank.size([[1., 0.]])
            rank([{**b, 'revision': 'b2'}], 'login')
            self.assertLessEqual(rank.cache_bytes, rank.max_cache_bytes)
            rank([a], 'login')
            self.assertEqual(len(provider.documents), 4)

    def test_missing_chunks_batch_across_notes(self):
        with tempfile.TemporaryDirectory() as tmp:
            class Provider(SyntheticProvider):
                calls = 0
                async def embed_documents(self, texts):
                    self.calls += 1
                    return await super().embed_documents(texts)
            provider = Provider()
            rank = LocalRanker(Path(tmp).resolve(), provider=provider)
            rows = [dict(path=str(i), revision='r', meta={}, body='authentication') for i in range(40)]
            rank(rows, 'login')
            self.assertEqual(provider.calls, 2)
