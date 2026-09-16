import fs from "node:fs";
import { randomUUID } from "node:crypto";
import path from "node:path";
import os from "node:os";
import { spawnSync } from "node:child_process";
import { DatabaseSync } from "node:sqlite";
import { fileURLToPath } from "node:url";
import assert from "node:assert/strict";
import { performance } from "node:perf_hooks";
import { seed } from "../tests/helpers/synthetic.mjs";
const root = fileURLToPath(new URL("..", import.meta.url));
const temp = fs.mkdtempSync(path.join(os.tmpdir(), "memory-benchmark-")),
  home = path.join(temp, "store");
let seq = 0;
const call = (op, data = {}, manage = false) => {
  const cfg = fs.existsSync(path.join(home, "identity.json"))
    ? JSON.parse(fs.readFileSync(path.join(home, "identity.json")))
    : null;
  const req = {
    protocol: 1,
    op,
    request_id: "bench-" + ++seq,
    ...(manage
      ? {}
      : {
          caller: {
            skill_id: "ghostwriter",
            project_id: "prj-harbor",
            user_id: cfg.user_id,
            token: cfg.skills.ghostwriter.token,
          },
        }),
    ...data,
  };
  const start = performance.now();
  const p = spawnSync(
    process.execPath,
    [path.join(root, "bin/local-memory.mjs"), manage ? "manage" : "request"],
    {
      input: JSON.stringify(req),
      encoding: "utf8",
      env: { ...process.env, LOCAL_MEMORY_HOME: home },
      timeout: 5500,
    },
  );
  const result = JSON.parse(p.stdout);
  assert.equal(result.ok, true, JSON.stringify(result));
  return { result, ms: performance.now() - start };
};
try {
  call("init", {}, true);
  call(
    "register",
    { skill_id: "ghostwriter", keys: ["writing.hashtags"], capture: true },
    true,
  );
  call("project", { project_id: "prj-harbor", roots: [temp] }, true);
  seed(home, 10000);
  const metrics = {
    fixture: "10,000 synthetic live preference records; no user data",
    node: process.version,
    platform: process.platform,
    arch: process.arch,
    records: 10000,
    modes: {},
  };
  for (const mode of ["scan", "fts5"]) {
    const latencies = [];
    let exact = 0,
      lexical = 0;
    for (const n of [0, 19, 1234, 5678, 9999]) {
      const a = call("recall", {
        keys: ["bench.item_" + String(n).padStart(5, "0")],
        retrieval_mode: mode,
      });
      latencies.push(a.ms);
      exact += a.result.context.records.some(
        (r) => r.content === "Value synthetic marker " + n,
      )
        ? 1
        : 0;
      const b = call("recall", { query: "marker " + n, retrieval_mode: mode });
      latencies.push(b.ms);
      lexical += b.result.context.records.some(
        (r) => r.content === "Value synthetic marker " + n,
      )
        ? 1
        : 0;
    }
    latencies.sort((a, b) => a - b);
    metrics.modes[mode] = {
      exact_key_recall: exact / 5,
      lexical_recall: lexical / 5,
      samples: 10,
      p50_ms: Math.round(latencies[4]),
      p95_ms: Math.round(latencies[9]),
      maximum_context_bytes: 8192,
    };
    assert.equal(exact, 5);
    assert.equal(lexical, 5);
  }
  const ledger = new DatabaseSync(path.join(home, "deletions.sqlite3"));
  ledger.exec("BEGIN");
  for (let i = 0; i < 1000; i++)
    ledger
      .prepare("INSERT INTO intents(id,complete) VALUES (?,1)")
      .run(randomUUID());
  ledger.exec("COMMIT");
  ledger.close();
  const size = (p) => {
    try {
      return fs.statSync(path.join(home, p)).size;
    } catch {
      return 0;
    }
  };
  metrics.database_bytes = size("memory.sqlite3");
  metrics.wal_bytes = size("memory.sqlite3-wal");
  metrics.deletion_ledger_bytes_for_1000_ids = size("deletions.sqlite3");
  metrics.wal_admission = { soft_bytes: 33554432, hard_bytes: 67108864 };
  metrics.foreground_limit_ms = 4800;
  console.log(JSON.stringify(metrics, null, 2));
} finally {
  fs.rmSync(temp, { recursive: true, force: true });
}
