#!/usr/bin/env python3
"""Local equivalent of the MCP recall tool; useful before clients reload tools."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from memory_hub.recall import recall_context
from memory_hub.semantic import configured_ranker


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--vault", type=Path, default=ROOT / "vault")
    p.add_argument("--subject", default="global")
    p.add_argument("--query", default="")
    p.add_argument("--key", action="append", dest="keys")
    p.add_argument("--max-context-bytes", type=int, default=8192)
    p.add_argument("--lexical", action="store_true", help="Explicit comparison baseline")
    a = p.parse_args()
    result = recall_context(a.vault, subject=a.subject, query=a.query, keys=a.keys,
                            max_context_bytes=a.max_context_bytes,
                            semantic_ranker=None if a.lexical else configured_ranker(ROOT))
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    raise SystemExit(0 if result["status"] in {"ok", "partial"} else 1)
