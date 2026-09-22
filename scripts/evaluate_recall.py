#!/usr/bin/env python3
"""Reproducible synthetic relevance/latency/bytes evaluation; never reads a live vault."""
import json
from pathlib import Path
import statistics
import sys
import tempfile
import time
import uuid
import argparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from memory_hub.recall import encoded, recall_context


def evaluate(mode="lexical", minimum=.65, fixtures=None, cache_dir=None):
    from memory_hub.semantic import LocalRanker
    ranker = LocalRanker(cache_dir or ROOT / ".runtime/models", minimum=minimum) if mode == "hybrid" else None
    results = []
    for fixture in (fixtures or ("recall-cases.json", "recall-advanced.json")):
        corpus = json.loads((ROOT / "tests/fixtures" / fixture).read_text())
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            for note in corpus["notes"]:
                meta = {"type": "note", "status": "active", "project": "local-memory",
                        "source": "Synthetic relevance fixture", "capture_id": str(uuid.uuid4()),
                        "permalink": "local-memory/" + note["id"], "title": note["id"], **note.get("metadata", {})}
                path = vault / (note["id"] + ".md")
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(note["raw"] if "raw" in note else "---\n" + json.dumps(meta) + "\n---\n" + note["body"] + "\n")
            for case in corpus["cases"]:
                start = time.perf_counter()
                response = recall_context(vault, subject=case.get("subject", "local-memory"), query=case["query"],
                                          keys=case.get("keys"), semantic_ranker=ranker)
                elapsed = (time.perf_counter() - start) * 1000
                ids = [r["identity"].removeprefix("local-memory/") for r in response["records"]]
                expected = case.get("hybrid_expected", case["expected"]) if mode == "hybrid" else case["expected"]
                ideal = set(case.get("hybrid_expected", case["expected"]))
                matched = set(ids) == set(expected) if case.get("unordered") else ids == expected
                passed = matched and response["status"] == case.get("status", "ok")
                results.append({"case": case["name"], "passed": passed, "latency_ms": round(elapsed, 3),
                                "payload_bytes": len(encoded(response)), "actual": ids, "expected": expected,
                                "status": response["status"], "relevant_found": len(set(ids) & ideal),
                                "relevant_total": len(ideal), "unexpected": len(set(ids) - ideal),
                                "abstention": not ideal, "correct_abstention": not ideal and not ids})
    latencies = sorted(r["latency_ms"] for r in results)
    relevant = sum(r["relevant_found"] for r in results)
    total = sum(r["relevant_total"] for r in results)
    unexpected = sum(r["unexpected"] for r in results)
    return {"scope": "synthetic retrieval only; excludes model answer quality and MCP startup", "mode": mode,
            "cases": len(results), "passed": sum(r["passed"] for r in results),
            "median_ms": statistics.median(latencies), "p95_ms": latencies[int(.95 * (len(latencies) - 1))],
            "max_payload_bytes": max(r["payload_bytes"] for r in results),
            "evidence_recall": round(relevant / total, 3),
            "evidence_precision": round(relevant / (relevant + unexpected), 3) if relevant + unexpected else 1,
            "unexpected_records": unexpected,
            "abstention_accuracy": round(sum(r["correct_abstention"] for r in results) / sum(r["abstention"] for r in results), 3),
            "results": results}


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--mode", choices=["lexical", "hybrid"], default="lexical")
    p.add_argument("--minimum", type=float, default=.65)
    p.add_argument("--output", type=Path)
    p.add_argument("--details", action="store_true")
    p.add_argument("--held-out", action="store_true")
    p.add_argument("--cache-dir", type=Path)
    args = p.parse_args()
    result = evaluate(args.mode, args.minimum, ["recall-held-out.json"] if args.held_out else None, args.cache_dir)
    if args.output:
        args.output.write_text(json.dumps(result, indent=2) + "\n")
    if not args.details:
        result["failures"] = [r for r in result.pop("results") if not r["passed"]]
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["passed"] == result["cases"] else 1)
