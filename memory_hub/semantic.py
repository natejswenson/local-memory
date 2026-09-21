"""Optional offline candidate search using Basic Memory's local embedding provider.

Only revision-keyed vectors are cached, in process memory. Every request supplies
fresh, scoped Markdown; absent/deleted revisions are evicted before ranking.
Model provisioning is a separate explicit command, never an implicit network call.
"""
import asyncio
import json
import math
import threading

from .skill_store import read, safe

MODEL = "BAAI/bge-small-en-v1.5"


class LocalRanker:
    def __init__(self, cache_dir, minimum=.65, provider=None):
        if not .5 <= minimum <= 1:
            raise ValueError("Invalid semantic threshold")
        self.cache_dir, self.minimum = safe(cache_dir), minimum
        self.provider, self.vectors = provider, {}
        self.lock = threading.Lock()

    def get_provider(self):
        if self.provider is None:
            from basic_memory.repository.fastembed_provider import FastEmbedEmbeddingProvider

            class OfflineProvider(FastEmbedEmbeddingProvider):
                def _create_model(inner):
                    import onnxruntime
                    onnxruntime.disable_telemetry_events()
                    from fastembed import TextEmbedding
                    return TextEmbedding(model_name=MODEL, cache_dir=str(self.cache_dir),
                                         local_files_only=True, threads=2, enable_cpu_mem_arena=False)

                def _purge_model_subdirs(inner, subdirs):
                    return False  # No destructive automatic cache repair.

            self.provider = OfflineProvider(model_name=MODEL, cache_dir=str(self.cache_dir), threads=2)
        return self.provider

    def __call__(self, rows, query):
        with self.lock:
            if not rows:
                self.vectors.clear()
                return {}
            return asyncio.run(self.rank(rows, query))

    async def rank(self, rows, query):
        provider = self.get_provider()
        current = {(r["path"], r["revision"]) for r in rows}
        self.vectors = {k: v for k, v in self.vectors.items() if k in current}
        for row in rows:
            key = (row["path"], row["revision"])
            if key in self.vectors:
                continue
            words = row["body"].split()
            chunks = [str(row["meta"].get("title", "")) + "\n" + " ".join(words[i:i + 180])
                      for i in range(0, max(1, len(words)), 150)]
            self.vectors[key] = await provider.embed_documents(chunks)
        vector = await provider.embed_query(query)
        norm = math.sqrt(sum(n * n for n in vector))
        result = {}
        for row in rows:
            scores = []
            for other in self.vectors[(row["path"], row["revision"])]:
                if len(other) != len(vector):
                    raise ValueError("Embedding dimension mismatch")
                denom = norm * math.sqrt(sum(n * n for n in other))
                scores.append(sum(a * b for a, b in zip(vector, other)) / denom if denom else 0)
            score = max(scores, default=0)
            if math.isfinite(score) and score >= self.minimum:
                result[row["path"]] = score
        return result


def configured_ranker(root):
    path = safe(root / ".runtime/retrieval.json")
    if not path.exists():
        return None
    config = json.loads(read(path))
    if config.get("mode") == "lexical":
        return None
    if config.get("mode") != "hybrid" or config.get("model") != MODEL:
        raise ValueError("Unsupported local retrieval configuration")
    return LocalRanker(root / ".runtime/models", minimum=config.get("minimum_similarity", .65))
