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
            self.assertNotIn(("one.md", "one"), rank.vectors)
            self.assertEqual(len(provider.documents), 2)
            self.assertEqual(rank([], "sign in"), {})
            self.assertEqual(rank.vectors, {})
