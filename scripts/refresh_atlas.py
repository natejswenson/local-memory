#!/usr/bin/env python3
"""Preview or refresh the human-readable memory map."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from memory_hub.atlas import refresh
from memory_hub.projects import resolve_subject

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vault', type=Path, default=ROOT / 'vault')
    parser.add_argument('--control', type=Path, default=ROOT / '.runtime/general-memory')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--resolve', type=Path, help='Resolve an exact configured repository/worktree scope')
    args = parser.parse_args()
    result = {'subject': resolve_subject(args.vault, args.resolve)} if args.resolve else refresh(args.vault, args.control, args.apply)
    print(json.dumps(result, ensure_ascii=False))
