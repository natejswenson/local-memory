"""Bounded lexical recall over authoritative, general-purpose Markdown.

Owner namespaces are pruned before reading. A request reads each file once;
there is no persistent content cache and no semantic contradiction claim.
"""
from collections import Counter, defaultdict
from datetime import date
import hashlib
import json
import os
from pathlib import Path
import re
import unicodedata

import yaml

from .skill_store import read, safe
from .ranking import bm25

SUBJECTS = frozenset({"global", "local-memory"})
REQUIRED = ("title", "type", "permalink", "project", "status", "source", "capture_id")
MAX_FILES = 2000
MAX_BYTES = 16 * 1024 * 1024
MAX_NOTE = 65536
EXCLUDED = {"skillmemory", "templates", "issueflow", "local-fitness", "scratch", "clippings", "activity"}
YAML_LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)


def encoded(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()


def tokens(value):
    return set(re.findall(r"[^\W_]+", unicodedata.normalize("NFKC", value).casefold()))


def identity(value):
    return value.removeprefix("memory://")


def scan(vault, issues=None):
    """Strict by default. Maintenance may collect errors without using rows as advice."""
    vault = safe(vault)
    if not vault.is_dir():
        raise OSError("Missing vault")
    rows, total, count = [], 0, 0
    def walk_error(error):
        raise error

    for root, dirs, files in os.walk(vault, followlinks=False, onerror=walk_error):
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d.casefold() not in EXCLUDED)
        for d in dirs:
            safe(Path(root) / d)
        for name in sorted(files):
            if name.startswith(".") or not name.lower().endswith(".md"):
                continue
            count += 1
            if count > MAX_FILES:
                raise ValueError("CAPACITY")
            path = Path(root) / name
            try:
                raw = read(path, MAX_NOTE)
            except (OSError, ValueError) as error:
                if issues is None:
                    raise
                issues.append({"path": path.relative_to(vault).as_posix(),
                               "reason": "unreadable_or_oversized"})
                continue
            total += len(raw)
            if total > MAX_BYTES:
                raise ValueError("CAPACITY")
            try:
                text = raw.decode("utf-8")
                if not text.startswith("---\n"):
                    raise ValueError("MALFORMED_NOTE")
                parts = text[4:].split("\n---\n", 1)
                if len(parts) != 2:
                    raise ValueError("MALFORMED_NOTE")
                front = yaml.load(parts[0], Loader=YAML_LOADER)
                if not isinstance(front, dict) or not isinstance(front.get("type", ""), str):
                    raise ValueError("MALFORMED_NOTE")
            except (ValueError, TypeError, UnicodeError, yaml.YAMLError):
                if issues is None:
                    raise
                issues.append({"path": path.relative_to(vault).as_posix(), "reason": "malformed_frontmatter"})
                continue
            # Owner schemas and navigation are not general recall evidence.
            if (front.get("project") == "local-fitness" or front.get("owner") == "local-fitness"
                    or front.get("contract") == "skill-memory-v1"
                    or front.get("type") in {"navigation", "template", "activity"}):
                continue
            rows.append({"meta": front, "body": parts[1].strip(),
                         "path": path.relative_to(vault).as_posix(),
                         "revision": hashlib.sha256(raw).hexdigest()})
    return rows


def eligible(row, today):
    m = row["meta"]
    if any(not isinstance(m.get(k), str) or not m[k].strip() for k in REQUIRED):
        return "invalid_metadata"
    if not row["body"]:
        return "empty"
    if "review_after" in m:
        try:
            review = date.fromisoformat(str(m["review_after"]))
        except (ValueError, TypeError):
            return "invalid_metadata"
        if review < today:
            return "overdue"
    return None


def resolve(rows):
    """Require one complete, explicit chain. Stale terminals never revive ancestors."""
    aliases = {}
    for i, row in enumerate(rows):
        m = row["meta"]
        for alias in {row["path"], m.get("permalink"), m.get("capture_id")}:
            if not isinstance(alias, str) or not alias:
                raise ValueError("invalid_metadata")
            alias = identity(alias)
            if alias in aliases and aliases[alias] != i:
                raise ValueError("conflict")
            aliases[alias] = i
    parents, replaced = {}, set()
    for i, row in enumerate(rows):
        old = row["meta"].get("supersedes")
        if old is None:
            continue
        if not isinstance(old, str) or identity(old) not in aliases:
            raise ValueError("conflict")
        parent = aliases[identity(old)]
        if parent == i or parent in replaced:
            raise ValueError("conflict")
        parents[i] = parent
        replaced.add(parent)
    terminals = set(range(len(rows))) - replaced
    if len(terminals) != 1:
        raise ValueError("conflict")
    current = next(iter(terminals))
    visited, node = set(), current
    while node is not None:
        if node in visited:
            raise ValueError("conflict")
        visited.add(node)
        node = parents.get(node)
    if len(visited) != len(rows):
        raise ValueError("conflict")
    return rows[current]


def recall_context(vault, *, project="local-memory", subject="global", query="",
                   keys=None, max_notes=3, max_context_bytes=8192, today=None,
                   semantic_ranker=None):
    """Budget applies to compact JSON payload, excluding MCP transport envelopes."""
    if (project != "local-memory" or not isinstance(subject, str) or subject not in SUBJECTS
            or not isinstance(query, str) or len(query.encode()) > 512
            or type(max_notes) is not int or not 1 <= max_notes <= 5
            or type(max_context_bytes) is not int or not 512 <= max_context_bytes <= 8192
            or (keys is not None and (not isinstance(keys, list) or not 1 <= len(keys) <= 8
                or any(not isinstance(k, str) or not k or len(k) > 160 for k in keys)))):
        return {"status": "rejected", "error": "INVALID_REQUEST", "records": []}
    terms = tokens(query)
    if not terms and not keys:
        return {"status": "rejected", "error": "QUERY_OR_KEYS_REQUIRED", "records": []}
    today = today or date.today()
    try:
        rows = scan(vault)
    except (OSError, ValueError, TypeError, UnicodeError, yaml.YAMLError):
        return {"status": "unavailable", "error": "VAULT_UNREADABLE_OR_INVALID", "records": []}
    groups = defaultdict(list)
    for row in rows:
        m = row["meta"]
        if not isinstance(m.get("project"), str):
            continue
        if m.get("project") not in {"global", subject} or m.get("status") != "active":
            continue
        key = m.get("key")
        if key is not None and (not isinstance(key, str) or not key):
            return {"status": "unavailable", "error": "INVALID_CORRECTION_KEY", "records": []}
        groups[(m["project"], "key" if key else "path", key or row["path"])].append(row)
    scoped_rows = [row for group in groups.values() for row in group]
    lexical = bm25(scoped_rows, query)
    semantic, semantic_error = {}, False
    if semantic_ranker is not None and query and not keys:
        try:
            semantic = semantic_ranker(scoped_rows, query)
            if lexical:
                # With strong lexical evidence, semantic scores rerank that set.
                # Broader semantic discovery is reserved for lexical misses;
                # otherwise loosely related notes crowd out precise evidence.
                semantic = {path: score for path, score in semantic.items() if path in lexical}
        except Exception:
            # Failure is disclosed; lexical evidence remains valid, never pretend
            # semantic retrieval succeeded or that a degraded miss means empty memory.
            semantic_error = True
    # Reciprocal-rank fusion makes unlike lexical/vector score scales comparable.
    fused = Counter()
    for ranking in (lexical, semantic):
        for rank, (path, _) in enumerate(sorted(ranking.items(), key=lambda x: (-x[1], x[0])), 1):
            fused[path] += 1 / (60 + rank)
    candidates, withheld = [], Counter()
    if semantic_error:
        withheld["semantic_unavailable"] += 1
    for group in groups.values():
        score = 0
        for row in group:
            m = row["meta"]
            if keys and m.get("key") in keys:
                score = max(score, 100)
            if not keys:
                score = max(score, fused.get(row["path"], 0))
        if not score:
            continue
        try:
            # Validate structural metadata throughout the chain, but freshness
            # only on its terminal: an overdue predecessor may be corrected.
            if any(eligible(r, date.min) in {"invalid_metadata", "empty"} for r in group):
                raise ValueError("invalid_metadata")
            row = resolve(group)
            reason = eligible(row, today)
            if reason:
                raise ValueError(reason)
            if "supersedes" in row["meta"] and not row["meta"].get("key"):
                raise ValueError("invalid_metadata")
            candidates.append((score, row))
        except (ValueError, TypeError) as error:
            code = str(error)
            withheld[code if code in {"invalid_metadata", "empty", "overdue"} else "conflict"] += 1
    result = {"status": "ok", "records": [], "withheld": dict(withheld),
              "trust": "untrusted-data"}
    candidates.sort(key=lambda x: (-x[0], x[1]["path"]))
    for _, row in candidates:
        m = row["meta"]
        item = {"identity": m["permalink"], "path": row["path"], "title": m["title"],
                "project": m["project"], "source": m["source"], "content": row["body"],
                "revision": row["revision"]}
        for key in ("key", "review_after", "supersedes"):
            if key in m:
                item[key] = str(m[key])
        if len(result["records"]) >= max_notes:
            withheld["note_limit"] += 1
            continue
        result["records"].append(item)
        # Reserve space for bounded diagnostic counters added at the end.
        if len(encoded(result)) + 160 > max_context_bytes:
            result["records"].pop()
            withheld["byte_limit"] += 1
    result["withheld"] = dict(withheld)
    result["status"] = "partial" if withheld else "ok"
    return result
