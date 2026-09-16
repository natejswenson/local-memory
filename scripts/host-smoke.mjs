import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
const root = fileURLToPath(new URL("..", import.meta.url));
const tmp = fs.mkdtempSync(
  path.join(fs.realpathSync(os.tmpdir()), "memory-host-smoke-"),
);
try {
  const env = { ...process.env, LOCAL_MEMORY_HOME: path.join(tmp, "store") };
  const call = (file, args, q) => {
    const p = spawnSync(process.execPath, [path.join(root, file), ...args], {
      cwd: tmp,
      env,
      input: JSON.stringify(q),
      encoding: "utf8",
      timeout: 5500,
    });
    assert.equal(p.status, 0, p.stdout);
    return JSON.parse(p.stdout);
  };
  const manage = (op, extra = {}) =>
    call("bin/local-memory.mjs", ["manage"], {
      protocol: 1,
      op,
      request_id: "host-smoke",
      ...extra,
    });
  manage("init");
  const source = path.join(tmp, "voice.md");
  fs.writeFileSync(source, "# Synthetic host voice\n");
  call("bin/adapter.mjs", ["ghostwriter", "setup"], {
    source_id: "synthetic-voice",
    source_path: source,
  });
  call("bin/adapter.mjs", ["ghostwriter", "request"], {
    op: "capture",
    key: "writing.hashtags",
    content: "Avoid hashtags in synthetic posts",
    durable: true,
  });
  const recall = call("bin/adapter.mjs", ["ghostwriter", "request"], {
    op: "recall",
    keys: ["writing.hashtags"],
  });
  assert.equal(
    recall.context.records[0].content,
    "Avoid hashtags in synthetic posts",
  );
  const record = recall.context.records[0];
  call("bin/adapter.mjs", ["ghostwriter", "request"], {
    op: "forget",
    id: record.id,
    expected_version: record.version,
  });
  assert.equal(
    call("bin/adapter.mjs", ["ghostwriter", "request"], {
      op: "recall",
      keys: ["writing.hashtags"],
    }).context.records.length,
    0,
  );
  console.log(
    JSON.stringify({
      host_smoke: "pass",
      synthetic: true,
      node: process.version,
      source_first: true,
      restart_recall: true,
      forget: true,
      cleanup: true,
    }),
  );
} finally {
  fs.rmSync(tmp, { recursive: true, force: true });
}
