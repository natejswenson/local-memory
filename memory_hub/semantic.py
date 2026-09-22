"""Optional offline candidate search using Basic Memory's local embedding provider.

Only revision-keyed vectors are cached, in process memory. Every request supplies
fresh, scoped Markdown; obsolete revisions are evicted during explicit reconciliation before ranking.
Model provisioning is a separate explicit command, never an implicit network call.
"""
import asyncio
import json
import math
import threading
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
import sys

from .skill_store import read, safe

MODEL = "BAAI/bge-small-en-v1.5"


class LocalRanker:
    def __init__(self, cache_dir, minimum=.65, provider=None, *, namespace='',
                 model_revision=MODEL, max_cache_bytes=64 * 1024 * 1024, timeout=None):
        if not .5 <= minimum <= 1:
            raise ValueError("Invalid semantic threshold")
        self.cache_dir, self.minimum = safe(cache_dir), minimum
        if type(max_cache_bytes) is not int or max_cache_bytes < 0:
            raise ValueError('Invalid cache budget')
        self.provider, self.vectors = provider, OrderedDict()
        self.namespace, self.model_revision = namespace, model_revision
        self.max_cache_bytes, self.cache_bytes = max_cache_bytes, 0
        self.timeout, self.executor, self.inflight = timeout, None, None
        self.dispatch_lock = threading.Lock()
        self.lock = threading.Lock()
        self.pending_inventory = None

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
        if self.timeout is not None:
            with self.dispatch_lock:
                if self.inflight is not None and not self.inflight.done():
                    raise TimeoutError('SEMANTIC_BUSY')
                if self.executor is None:
                    self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='memory-embedding')
                self.inflight = self.executor.submit(self._compute, rows, query)
                future = self.inflight
            try:
                return future.result(timeout=self.timeout)
            except FutureTimeout:
                raise TimeoutError('SEMANTIC_TIMEOUT') from None
        return self._compute(rows, query)

    def _compute(self, rows, query):
        with self.lock:
            if self.pending_inventory is not None:
                self._evict_absent(self.pending_inventory)
                self.pending_inventory = None
            if not rows:
                return {}
            return asyncio.run(self.rank(rows, query))

    def key(self, row):
        return (self.namespace, MODEL, self.model_revision, 'words-180-stride-150-v1',
                row['path'], row['revision'])

    @staticmethod
    def size(vectors):
        return sys.getsizeof(vectors) + sum(sys.getsizeof(v) + sum(sys.getsizeof(n) for n in v) for v in vectors)

    def _evict_absent(self, current):
        for key in list(self.vectors):
            if (key[-2], key[-1]) not in current:
                self.cache_bytes -= self.size(self.vectors.pop(key))

    def reconcile(self, current):
        """Complete inventory only. Never wait on an overdue embedding call."""
        self.pending_inventory = current
        if self.lock.acquire(blocking=False):
            try:
                self._evict_absent(current)
                self.pending_inventory = None
            finally:
                self.lock.release()

    def close(self):
        if self.executor is not None:
            self.executor.shutdown(wait=False, cancel_futures=True)

    async def rank(self, rows, query):
        provider = self.get_provider()
        while self.vectors and self.cache_bytes > self.max_cache_bytes:
            _, old = self.vectors.popitem(last=False)
            self.cache_bytes -= self.size(old)
        current_vectors, chunks, owners = {}, [], []
        for row in rows:
            key = self.key(row)
            for old in list(self.vectors):
                if old[:-1] == key[:-1] and old != key:
                    self.cache_bytes -= self.size(self.vectors.pop(old))
            if key in self.vectors:
                self.vectors.move_to_end(key)
                current_vectors[key] = self.vectors[key]
                continue
            words = row["body"].split()
            parts = [str(row["meta"].get("title", "")) + "\n" + " ".join(words[i:i + 180])
                     for i in range(0, max(1, len(words)), 150)]
            current_vectors[key] = []
            chunks.extend(parts); owners.extend([key] * len(parts))
        for start in range(0, len(chunks), 32):
            embedded = await provider.embed_documents(chunks[start:start + 32])
            if len(embedded) != len(chunks[start:start + 32]):
                raise ValueError('Embedding count mismatch')
            for key, vector in zip(owners[start:start + 32], embedded):
                current_vectors[key].append(vector)
        for key in dict.fromkeys(owners):
            vectors = current_vectors[key]
            size = self.size(vectors)
            if size > self.max_cache_bytes:
                continue
            while self.vectors and self.cache_bytes + size > self.max_cache_bytes:
                _, old = self.vectors.popitem(last=False)
                self.cache_bytes -= self.size(old)
            self.vectors[key] = vectors
            self.cache_bytes += size
        vector = await provider.embed_query(query)
        norm = math.sqrt(sum(n * n for n in vector))
        result = {}
        for row in rows:
            scores = []
            for other in current_vectors[self.key(row)]:
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
    return LocalRanker(root / ".runtime/models", minimum=config.get("minimum_similarity", .65),
                       namespace=str(root), timeout=2.0)
