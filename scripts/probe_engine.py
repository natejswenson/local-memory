#!/usr/bin/env python3
"""Exercise the real pilot MCP engine using synthetic notes; retain JSON evidence."""
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time
import uuid

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "bin/memory-hub"
VAULT = ROOT / ".runtime/pilot/vault"
EVIDENCE = ROOT / ".runtime/engine-probe.json"
PROJECT = "local-memory"
RUN = uuid.uuid4().hex
REPORT = {"run_id": RUN, "started": datetime.now(timezone.utc).isoformat(),
          "scope": "synthetic local MCP only; no ChatGPT or production proof",
          "client_polling_override": os.environ.get("WATCHFILES_FORCE_POLLING", "launcher default"), "checks": []}


def save():
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text(json.dumps(REPORT, indent=2) + "\n")


def record(name, passed, **evidence):
    REPORT["checks"].append({"name": name, "passed": bool(passed), **evidence})
    save()


@asynccontextmanager
async def connect():
    env = {k: os.environ[k] for k in ("WATCHFILES_FORCE_POLLING",) if k in os.environ}
    params = StdioServerParameters(command=str(LAUNCHER), args=["mcp", "--pilot"], cwd=ROOT, env=env)
    with (ROOT / ".runtime/engine-probe.stderr.log").open("a") as log:
        async with stdio_client(params, errlog=log) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                yield session


async def call(session, name, **args):
    started = time.monotonic()
    result = await session.call_tool(name, {"project": PROJECT, **args})
    raw = result.model_dump(mode="json")
    texts = [part.get("text", "") for part in raw.get("content", [])]
    payload = raw.get("structuredContent")
    if payload is None and len(texts) == 1:
        try:
            payload = json.loads(texts[0])
        except json.JSONDecodeError:
            payload = texts[0]
    if payload is None:
        payload = texts
    return {"is_error": bool(result.is_error), "payload": payload,
            "elapsed_ms": round(1000 * (time.monotonic() - started), 2),
            "output_bytes": len(json.dumps(raw).encode())}


def created(reply):
    p = reply["payload"]
    return not reply["is_error"] and isinstance(p, dict) and p.get("action") == "created"


def contains(reply, value):
    return value in json.dumps(reply["payload"])


def write_args(label, body, status="active"):
    capture_id = f"{RUN}-{label}"
    return {"title": f"probe-{capture_id}", "directory": "Probe", "content": body,
            "overwrite": False, "output_format": "json",
            "metadata": {"capture_id": capture_id, "project": "global", "status": status,
                         "key": "probe-decision", "source": "synthetic engine probe"}}


async def read(session, identifier):
    return await call(session, "read_note", identifier=identifier,
                      include_frontmatter=True, output_format="json")


async def search(session, token, status="active"):
    return await call(session, "search_notes", query=token, status=status,
                      metadata_filters={"project": "global"}, page_size=5)


async def run():
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    marker = f"original{RUN}"
    args = write_args("primary", f"# Synthetic decision\n\n{marker}\n")
    async with connect() as session:
        listing = await session.list_tools()
        names = [tool.name for tool in listing.tools]
        record("tools", {"write_note", "read_note", "search_notes"}.issubset(names), names=names)
        initial = await call(session, "write_note", **args)
        record("create", created(initial), reply=initial)
        if not created(initial):
            return
        identity = initial["payload"]["permalink"]
        file = (VAULT / initial["payload"]["file_path"]).resolve()
        if not file.is_relative_to(VAULT.resolve()):
            raise RuntimeError("Engine returned a path outside the synthetic vault")
        got = await read(session, identity)
        frontmatter = got["payload"].get("frontmatter", {}) if isinstance(got["payload"], dict) else {}
        record("read_metadata", contains(got, marker) and all(frontmatter.get(k) == v
               for k, v in args["metadata"].items()), reply=got)
        found = await search(session, marker)
        record("search_active", contains(found, args["title"]), reply=found)
        candidate = write_args("candidate", f"# Candidate\n\n{marker}\n", "candidate")
        candidate_write = await call(session, "write_note", **candidate)
        filtered = await search(session, marker)
        record("status_filter", created(candidate_write) and contains(filtered, args["title"])
               and not contains(filtered, candidate["title"]), reply=filtered)
        duplicate = await call(session, "write_note", **args)
        differing = await call(session, "write_note", **{**args, "content": "DIFFERENT BODY"})
        retained = await read(session, identity)
        record("repeat_guard", not created(duplicate) and not created(differing)
               and contains(retained, marker) and not contains(retained, "DIFFERENT BODY"),
               exact_repeat=duplicate, different_body=differing,
               interpretation="A rejected duplicate is a conflict, not native idempotent success.")
        fresh = f"external{RUN}"
        file.write_text(file.read_text().replace(marker, fresh))
        deadline = time.monotonic() + 5
        refreshed = await search(session, fresh)
        while not contains(refreshed, args["title"]) and time.monotonic() < deadline:
            await asyncio.sleep(0.25)
            refreshed = await search(session, fresh)
        record("external_edit_within_5s", contains(refreshed, args["title"]), reply=refreshed)
    # Edit with every probe server stopped; the next FIRST read must see it.
    offline = f"offline{RUN}"
    file.write_text(file.read_text().replace(fresh, offline))
    fresh = offline
    async with connect() as first:
        persisted = await read(first, identity)
        record("restart_persistence", contains(persisted, args["metadata"]["capture_id"]), reply=persisted)
        record("first_read_sees_offline_edit", contains(persisted, fresh), reply=persisted)
        refreshed = await search(first, fresh)
        record("external_edit_after_restart", contains(refreshed, args["title"]), reply=refreshed)
        reread = await read(first, identity)
        record("read_after_fresh_search", contains(reread, fresh), reply=reread)
        warm = f"warmedit{RUN}"
        file.write_text(file.read_text().replace(fresh, warm))
        edited_at = time.monotonic()
        deadline = edited_at + 5
        observed = await search(first, warm)
        while not contains(observed, args["title"]) and time.monotonic() < deadline:
            await asyncio.sleep(0.25)
            observed = await search(first, warm)
        record("warm_external_edit_within_5s", contains(observed, args["title"]), reply=observed)
        while not contains(observed, args["title"]) and time.monotonic() - edited_at < 30:
            await asyncio.sleep(1)
            observed = await search(first, warm)
        record("warm_external_edit_within_30s", contains(observed, args["title"]),
               elapsed_seconds=round(time.monotonic() - edited_at, 2), reply=observed)
        async with connect() as second:
            concurrent = write_args("concurrent", "race body A")
            replies = await asyncio.gather(
                call(first, "write_note", **concurrent),
                call(second, "write_note", **{**concurrent, "content": "race body B"}),
                return_exceptions=True)
            serial = [({"exception": repr(r)} if isinstance(r, BaseException) else r) for r in replies]
            successes = [r for r in serial if "exception" not in r and created(r)]
            final = await read(first, concurrent["title"])
            winner = "race body A" if serial[0] in successes else "race body B"
            record("same_id_race", len(successes) == 1 and contains(final, winner),
                   replies=serial, final=final,
                   interpretation="Single observed race only; does not prove transactional safety.")
            separate = await asyncio.gather(
                call(first, "write_note", **write_args("independent-a", "independent A")),
                call(second, "write_note", **write_args("independent-b", "independent B")),
                return_exceptions=True)
            serial = [({"exception": repr(r)} if isinstance(r, BaseException) else r) for r in separate]
            record("independent_concurrent_creates", all("exception" not in r and created(r)
                   for r in serial), replies=serial)
    durable = []
    for index, reply in enumerate(serial):
        if "exception" in reply or not created(reply):
            durable.append(False)
            continue
        path = (VAULT / reply["payload"]["file_path"]).resolve()
        durable.append(path.is_relative_to(VAULT.resolve()) and path.is_file()
                       and f"independent {'AB'[index]}" in path.read_text())
    record("independent_captures_materialized_after_shutdown", all(durable), preserved=durable)
    REPORT["completed"] = datetime.now(timezone.utc).isoformat()
    save()


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except BaseException as exc:
        REPORT["fatal_error"] = repr(exc)
        save()
        raise
    print(json.dumps({"evidence": str(EVIDENCE), "checks": [
        {"name": c["name"], "passed": c["passed"]} for c in REPORT["checks"]]}, indent=2))
    raise SystemExit(0 if all(c["passed"] for c in REPORT["checks"]) else 1)
