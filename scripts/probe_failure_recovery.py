#!/usr/bin/env python3
"""Synthetic external-deletion and lost-reply recovery through the real engine."""
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import importlib.machinery
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import uuid

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / ".venv/bin/basic-memory"
EVIDENCE = ROOT / ".runtime/failure-recovery-evidence.json"
PROJECT = "local-memory"
loader = importlib.machinery.SourceFileLoader("failure_probe_hub", str(ROOT / "bin/memory-hub"))
spec = importlib.util.spec_from_loader(loader.name, loader)
hub = importlib.util.module_from_spec(spec)
loader.exec_module(hub)


async def call(session, name, **arguments):
    result = await session.call_tool(name, {"project": PROJECT, **arguments})
    raw = result.model_dump(mode="json", by_alias=True)
    payload = raw.get("structuredContent")
    if payload is None:
        text = "\n".join(part.get("text", "") for part in raw.get("content", []))
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            payload = text
    if isinstance(payload, dict) and set(payload) == {"result"}:
        payload = payload["result"]
    return {"is_error": bool(result.is_error), "payload": payload}


def write_args(label):
    capture_id = str(uuid.uuid4())
    return {"title": f"{label}-{capture_id}", "directory": "Probe",
            "content": f"# Synthetic {label}\n\nvalue-{capture_id}\n",
            "metadata": {"capture_id": capture_id, "status": "active", "project": "global",
                         "source": "isolated failure recovery probe"},
            "overwrite": False, "output_format": "json"}


def exact(reply, args):
    value = reply["payload"]
    return (not reply["is_error"] and isinstance(value, dict)
            and (value.get("content") or "").endswith(args["content"])
            and all(value.get("frontmatter", {}).get(k) == v for k, v in args["metadata"].items()))


def created(reply):
    return isinstance(reply["payload"], dict) and reply["payload"].get("action") == "created"


def reindex(env, log):
    subprocess.run([str(ENGINE), "reindex", "--search", "--project", PROJECT], env=env,
                   stdout=log, stderr=log, check=True, timeout=60)


@asynccontextmanager
async def connect(env, log):
    reindex(env, log)
    params = StdioServerParameters(command=str(ENGINE), args=["mcp", "--project", PROJECT], env=env)
    async with stdio_client(params, errlog=log) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            yield session


async def drop_reply(env, log, args, delay):
    """Send a write over stdio, then close input without ever reading its reply."""
    reindex(env, log)
    proc = await asyncio.create_subprocess_exec(str(ENGINE), "mcp", "--project", PROJECT,
                                              env=env, stdin=asyncio.subprocess.PIPE,
                                              stdout=asyncio.subprocess.PIPE, stderr=log)
    termination = "stdin closed"
    try:
        initialize = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-11-25", "capabilities": {},
            "clientInfo": {"name": "synthetic-lost-reply-probe", "version": "1"}}}
        proc.stdin.write((json.dumps(initialize) + "\n").encode())
        await proc.stdin.drain()
        async with asyncio.timeout(30):
            while True:
                line = await proc.stdout.readline()
                if not line:
                    raise RuntimeError("Server exited before initialize reply")
                message = json.loads(line)
                if message.get("id") == 1:
                    if "error" in message:
                        raise RuntimeError(str(message["error"]))
                    break
        for message in [
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
                "name": "write_note", "arguments": {"project": PROJECT, **args}}},
        ]:
            proc.stdin.write((json.dumps(message) + "\n").encode())
        await proc.stdin.drain()
        await asyncio.sleep(delay)
        proc.stdin.close()
        try:
            await asyncio.wait_for(proc.wait(), 5)
        except TimeoutError:
            termination = "SIGTERM after stdin-close timeout"
            proc.terminate()
            await asyncio.wait_for(proc.wait(), 5)
        return {"delay_seconds": delay, "termination": termination, "exit_code": proc.returncode,
                "write_response_consumed": False}
    finally:
        if proc.returncode is None:
            proc.kill()
            await proc.wait()


async def run():
    report = {"started": datetime.now(timezone.utc).isoformat(), "checks": [],
              "scope": "independent temporary synthetic engine; no pilot or production writes",
              "limits": "Stdio reply loss/disconnect, not SIGKILL, power-loss, or arbitrary crash safety."}
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(prefix="failure-probe-", dir=ROOT / ".runtime") as directory:
            hub.ROOT = Path(directory)
            hub.initialize(False)
            env = hub.environment(False)
            vault = hub.ROOT / "vault"
            with (ROOT / ".runtime/failure-recovery.stderr.log").open("a") as log:
                deletion = write_args("deletion")
                async with connect(env, log) as session:
                    written = await call(session, "write_note", **deletion)
                    if not created(written):
                        raise RuntimeError(f"Synthetic create failed: {written}")
                    identity = written["payload"]["permalink"]
                    before = await call(session, "read_note", identifier=identity,
                                        include_frontmatter=True, output_format="json")
                    if not exact(before, deletion):
                        raise RuntimeError("Synthetic initial readback failed")
                path = (vault / written["payload"]["file_path"]).resolve()
                if not path.is_relative_to(vault.resolve()) or not path.is_file():
                    raise RuntimeError("Unexpected synthetic note path")
                path.unlink()
                async with connect(env, log) as session:
                    after = await call(session, "read_note", identifier=identity,
                                       include_frontmatter=True, output_format="json")
                    search = await call(session, "search_notes", query=deletion["metadata"]["capture_id"],
                                        search_type="text", output_format="json")
                search_value = search["payload"]
                no_results = isinstance(search_value, dict) and search_value.get("results") == []
                report["checks"].append({"name": "external_delete_reindex_restart",
                    "passed": not path.exists() and not exact(after, deletion) and no_results,
                    "read": after, "search": search})
                for delay in (0, 0.1):
                    args = write_args("lost-reply")
                    dropped = await drop_reply(env, log, args, delay)
                    async with connect(env, log) as session:
                        observed = await call(session, "read_note", identifier=args["title"],
                                              include_frontmatter=True, output_format="json")
                        persisted_before_retry = exact(observed, args)
                        retry = None
                        if not persisted_before_retry:
                            retry = await call(session, "write_note", **args)
                        final = await call(session, "read_note", identifier=args["title"],
                                           include_frontmatter=True, output_format="json")
                    matches = [p for p in vault.rglob("*.md") if args["metadata"]["capture_id"] in p.read_text()]
                    report["checks"].append({"name": f"lost_reply_{delay}s",
                        "passed": exact(final, args) and len(matches) == 1,
                        "disconnect": dropped, "persisted_before_retry": persisted_before_retry,
                        "retry": retry, "matching_file_count": len(matches), "final": final})
        report["completed"] = datetime.now(timezone.utc).isoformat()
    except BaseException as exc:
        report["fatal_error"] = repr(exc)
        raise
    finally:
        report["ok"] = bool(report["checks"]) and not report.get("fatal_error") and all(c["passed"] for c in report["checks"])
        EVIDENCE.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"ok": report["ok"], "evidence": str(EVIDENCE), "checks": [
        {"name": c["name"], "passed": c["passed"]} for c in report["checks"]]}, indent=2))
    return report["ok"]


if __name__ == "__main__":
    raise SystemExit(0 if asyncio.run(run()) else 1)
