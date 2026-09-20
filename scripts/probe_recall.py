#!/usr/bin/env python3
"""Exercise the installed MCP stack in the synthetic pilot, including offline startup."""
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import time
import uuid

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]


def payload(result):
    if result.is_error:
        raise RuntimeError("MCP tool error")
    value = result.structured_content
    if value is None:
        value = json.loads(result.content[0].text)
    return value.get("result", value)


async def run():
    run_id = str(uuid.uuid4())
    marker = "recallprobe" + run_id.replace("-", "")
    folder = ROOT / ".runtime/pilot/vault/RecallProbe"
    if not folder.parent.is_dir():
        raise RuntimeError("Initialize synthetic pilot first")
    folder.mkdir(exist_ok=True)
    paths = []
    old_id = "local-memory/recall-probe/" + run_id + "-old"
    for label, body, extra in [
        ("old", marker + " uses old wording.", {}),
        ("new", "Current synthetic decision.", {"supersedes": old_id}),
    ]:
        m = {"title": run_id + "-" + label, "type": "note", "project": "global", "status": "active",
             "capture_id": str(uuid.uuid4()), "source": "Synthetic MCP recall probe",
             "key": "probe.recall." + run_id,
             "permalink": "local-memory/recall-probe/" + run_id + "-" + label, **extra}
        path = folder / (run_id + "-" + label + ".md")
        path.write_text("---\n" + json.dumps(m) + "\n---\n" + body + "\n")
        paths.append(path)
    report = {"scope": "synthetic local MCP; no desktop interaction", "run_id": run_id,
              "at": datetime.now(timezone.utc).isoformat(), "checks": {}}
    start = time.perf_counter()
    params = StdioServerParameters(command=str(ROOT / "bin/memory-hub"), args=["mcp", "--pilot"], cwd=ROOT)
    with (ROOT / ".runtime/recall-probe.stderr.log").open("a") as log:
        async with stdio_client(params, errlog=log) as (reader, writer):
            async with ClientSession(reader, writer) as client:
                init = await client.initialize()
                report["startup_ms"] = round((time.perf_counter() - start) * 1000, 2)
                tools = (await client.list_tools()).tools
                report["checks"]["bounded_surface"] = {t.name for t in tools} == {
                    "recall_context", "capture_memory", "record_activity", "recall_activity", "skill_memory", "search_notes", "read_note", "write_note", "recent_activity"}
                report["checks"]["aligned_instructions"] = "recall_context" in (init.instructions or "") and all(
                    "At the start of a session" not in (t.description or "") for t in tools)
                args = {"project": "local-memory", "subject": "global", "query": marker}
                begin = time.perf_counter()
                result = payload(await client.call_tool("recall_context", args))
                report["recall_ms"] = round((time.perf_counter() - begin) * 1000, 2)
                report["payload_bytes"] = len(json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode())
                report["checks"]["correction_first_read"] = (result["status"] == "ok" and len(result["records"]) == 1
                    and result["records"][0]["content"] == "Current synthetic decision.")
                paths[1].write_text(paths[1].read_text().replace("Current synthetic decision.", "Edited synthetic decision."))
                edited = payload(await client.call_tool("recall_context", args))
                report["checks"]["immediate_external_edit"] = edited["records"][0]["content"] == "Edited synthetic decision."
                capture = dict(project="local-memory", subject="global", title="Synthetic durable capture " + run_id,
                    body="Capture marker " + marker + " durabletest.", source="Synthetic MCP probe",
                    capture_id=str(uuid.uuid4()), status="active")
                saved = payload(await client.call_tool("capture_memory", capture))
                report["checks"]["validated_capture"] = saved.get("verified") and saved.get("status") == "created"
                report["checks"]["retry_same_identity"] = payload(await client.call_tool("capture_memory", capture)).get("status") == "already_created"
                changed = payload(await client.call_tool("capture_memory", {**capture, "body": "Different synthetic claim."}))
                report["checks"]["changed_retry_refused"] = changed.get("error") == "CAPTURE_ID_CONFLICT"
                report["checks"]["capture_immediate_recall"] = saved.get("identity") in [r["identity"] for r in
                    payload(await client.call_tool("recall_context", {"subject": "global", "query": "durabletest " + marker}))["records"]]
        async with stdio_client(params, errlog=log) as (reader, writer):
            async with ClientSession(reader, writer) as client:
                await client.initialize()
                retried = payload(await client.call_tool("capture_memory", capture))
                report["checks"]["retry_after_restart_and_reindex"] = (
                    retried.get("verified") and retried.get("status") == "already_created"
                    and retried.get("identity") == saved.get("identity"))
    # Keep uniquely identified synthetic fixtures as reproducible pilot evidence.
    destination = ROOT / ".runtime/recall-mcp-evidence.json"
    destination.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return all(report["checks"].values())


if __name__ == "__main__":
    raise SystemExit(0 if asyncio.run(run()) else 1)
