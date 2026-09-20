#!/usr/bin/env python3
"""Compare safe YAML parsers and retrieval at synthetic vault sizes; no live data."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import statistics
import sys
import tempfile
import time
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from memory_hub import recall


def benchmark(sizes=(100, 500, 1500), repeats=3):
    if not sizes or any(type(n) is not int or not 2 <= n <= recall.MAX_FILES for n in sizes):
        raise ValueError("Sizes must be 2–2000")
    if type(repeats) is not int or not 1 <= repeats <= 10:
        raise ValueError("Repeats must be 1–10")
    results = []
    for size in sizes:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp).resolve()
            for i in range(size):
                m = {"title": f"Synthetic note {i}", "type": "note", "project": "local-memory",
                     "status": "active", "permalink": f"local-memory/n-{i}",
                     "source": "Synthetic benchmark", "capture_id": f"synthetic-{i}"}
                if i in (0, 1):
                    m["key"] = "synthetic.deployment"
                if i == 1:
                    m["supersedes"] = "local-memory/n-0"
                body = "Old quartz guidance." if i == 0 else "Current deployment decision." if i == 1 else "Unrelated synthetic reference. " * 20
                (vault / f"n-{i}.md").write_text("---\n" + yaml.safe_dump(m) + "---\n" + body + "\n")
            outputs = []
            for label, loader in [("python_safe", yaml.SafeLoader), ("installed_safe", recall.YAML_LOADER)]:
                timings = []
                with patch.object(recall, "YAML_LOADER", loader):
                    for _ in range(repeats):
                        start = time.perf_counter()
                        result = recall.recall_context(vault, subject="local-memory", query="quartz")
                        timings.append(1000 * (time.perf_counter() - start))
                outputs.append(result)
                results.append({"notes": size, "parser": label, "median_ms": round(statistics.median(timings), 2),
                                "runs_ms": [round(n, 2) for n in timings], "payload_bytes": len(recall.encoded(result)),
                                "correct_replacement": [r["identity"] for r in result["records"]] == ["local-memory/n-1"]})
            if outputs[0] != outputs[1]:
                raise ValueError("Parser behavior mismatch")
    return {"at": datetime.now(timezone.utc).isoformat(),
            "scope": "synthetic local function calls; excludes MCP startup and host overhead",
            "equivalent_results": True, "results": results}


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--sizes", type=int, nargs="+", default=[100, 500, 1500])
    p.add_argument("--repeats", type=int, default=3)
    a = p.parse_args()
    print(json.dumps(benchmark(a.sizes, a.repeats), indent=2))
