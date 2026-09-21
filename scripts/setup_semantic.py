#!/usr/bin/env python3
"""Provision Basic Memory's local model; explicit download, then offline trial."""
import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from memory_hub.semantic import MODEL, LocalRanker
from memory_hub.skill_store import atomic


def setup(download=False, enable=False, minimum=.65):
    cache = ROOT / ".runtime/models"
    if download:
        from fastembed import TextEmbedding
        cache.mkdir(parents=True, exist_ok=True, mode=0o700)
        TextEmbedding(model_name=MODEL, cache_dir=str(cache), threads=2)
    # Provisioning alone never proves retrieval. Smoke-test only synthetic data.
    os.environ["HF_HUB_OFFLINE"] = "1"
    ranker = LocalRanker(cache, minimum=minimum)
    rows = [
        {"path": "authentication.md", "revision": "synthetic-1", "meta": {"title": "Authentication"},
         "body": "Employees must use hardware security keys to authenticate to company accounts."},
        {"path": "garden.md", "revision": "synthetic-2", "meta": {"title": "Garden"},
         "body": "The garden has blue flowers."},
    ]
    positive = ranker(rows, "How should employees sign in?")
    negative = ranker(rows, "What is the Kubernetes rollback policy?")
    passed = "authentication.md" in positive and "garden.md" not in positive and not negative
    report = {"model": MODEL, "passed": passed, "positive": positive, "negative": negative,
              "minimum_similarity": minimum, "enabled": False, "scope": "synthetic offline smoke test"}
    if enable:
        if not passed:
            raise ValueError("Offline smoke test failed; retrieval configuration unchanged")
        atomic(ROOT / ".runtime/retrieval.json", json.dumps({"mode": "hybrid", "model": MODEL,
               "minimum_similarity": minimum}).encode())
        report["enabled"] = True
    atomic(ROOT / ".runtime/semantic-smoke.json", json.dumps(report, indent=2).encode())
    return report


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--download", action="store_true")
    p.add_argument("--enable", action="store_true")
    p.add_argument("--minimum", type=float, default=.65)
    a = p.parse_args()
    result = setup(a.download, a.enable, a.minimum)
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["passed"] else 1)
