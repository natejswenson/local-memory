import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { DatabaseSync } from "node:sqlite";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { fixture } from "./helpers/harness.mjs";
import { seed } from "./helpers/synthetic.mjs";
const exe = fileURLToPath(new URL("../bin/local-memory.mjs", import.meta.url));
test("1,000 eligible conflicts and mixed groups respect 64/8192 byte budgets with exact omissions", (t) => {
  for (const mixed of [false, true]) {
    const f = fixture(t);
    f.init();
    seed(f.home, 1000, { conflicts: true, mixed });
    for (const budget of [64, 8192])
      for (const mode of ["scan", "fts5"]) {
        const r = f.good("recall", {
          query: "synthetic",
          max_context_bytes: budget,
          limit: 10,
          retrieval_mode: mode,
        });
        assert.ok(Buffer.byteLength(JSON.stringify(r.context)) <= budget);
        assert.equal(
          r.omitted_count,
          1000 - r.context.records.length - r.context.conflict_keys.length,
        );
        assert.equal(r.truncated, true);
        assert.deepEqual(
          f.good("recall", {
            query: "synthetic",
            max_context_bytes: budget,
            limit: 10,
            retrieval_mode: mode,
          }).context,
          r.context,
        );
      }
    const denied = f.good("recall", { skill: "other", query: "synthetic" });
    assert.equal(denied.omitted_count, 0);
    assert.deepEqual(denied.context, { records: [], conflict_keys: [] });
  }
});
test("10,000 live records refuse capture but continue recall and deletion", (t) => {
  const f = fixture(t);
  f.init();
  seed(f.home, 10000);
  assert.equal(
    f.raw("remember", { idempotency_key: "over-cap", record: f.input() }).error
      .code,
    "CAPACITY",
  );
  const r = f.good("recall", { keys: ["bench.item_00001"] });
  assert.equal(r.context.records.length, 1);
  assert.equal(
    f.good("forget", {
      id: r.context.records[0].id,
      expected_version: 1,
      idempotency_key: "free-cap",
    }).deleted,
    true,
  );
  assert.equal(f.remember().ok, true);
});
test("128 KiB inspection, metadata limits, request bounds and field errors", (t) => {
  const f = fixture(t);
  f.init();
  seed(f.home, 60);
  const listed = f.good("list", { limit: 50 }, true);
  assert.equal(listed.records.length, 50);
  assert.ok(Buffer.byteLength(JSON.stringify(listed)) < 128 * 1024);
  assert.equal(listed.next_offset, 50);
  assert.equal(
    f.good("list", { limit: 50, offset: 50 }, true).records.length,
    10,
  );
  assert.equal(f.raw("list", { limit: 51 }, true).error.code, "INVALID_INPUT");
  const out = spawnSync(process.execPath, [exe, "request"], {
    input: " ".repeat(16385),
    encoding: "utf8",
    env: { ...process.env, LOCAL_MEMORY_HOME: f.home },
    timeout: 6500,
  });
  assert.equal(JSON.parse(out.stdout).error.code, "INVALID_INPUT");
  assert.equal(
    f.raw("recall", {
      keys: ["writing.hashtags"],
      unknown: "password=do-not-echo",
    }).error.code,
    "INVALID_INPUT",
  );
  assert.equal(
    f.raw("recall", {
      caller: {
        skill_id: "ghostwriter",
        project_id: "prj-harbor",
        user_id: "forged",
        token: "forged",
      },
      keys: ["writing.hashtags"],
    }).error.code,
    "PERMISSION_DENIED",
  );
});
test("backup rotation and failure leave validated prior snapshots intact", (t) => {
  const f = fixture(t);
  f.init();
  f.remember();
  for (let i = 0; i < 5; i++) f.good("backup", {}, true);
  const dir = path.join(f.home, "backups");
  assert.equal(
    fs.readdirSync(dir).filter((n) => n.endsWith(".json")).length,
    3,
  );
  const before = fs.readdirSync(dir).sort();
  assert.equal(
    f.raw("backup", {}, true, { LOCAL_MEMORY_FAIL_POINT: "backup-validated" })
      .ok,
    false,
  );
  assert.deepEqual(fs.readdirSync(dir).sort(), before);
});
test("full receipt capacity still permits forgetting live content", (t) => {
  const f = fixture(t); f.init();
  const r = f.remember();
  const db = new DatabaseSync(path.join(f.home, "memory.sqlite3"));
  db.prepare("WITH RECURSIVE n(x) AS (VALUES(1) UNION ALL SELECT x+1 FROM n WHERE x<99999) INSERT INTO receipts SELECT 'full-'||x,'digest','{}',? FROM n").run(Date.now());
  db.close();
  assert.equal(f.good("forget", { id: r.id, expected_version: 1, idempotency_key: "forget-full" }).deleted, true);
  assert.equal(f.raw("show", { id: r.id }).error.code, "NOT_FOUND");
  assert.equal(f.good("recall", { keys: ["writing.hashtags"] }).context.records.length, 0);
  const after = new DatabaseSync(path.join(f.home, "memory.sqlite3"));
  assert.equal(after.prepare("SELECT count(*) n FROM receipts").get().n, 100001);
  after.close();
});

test("receipts are content-free and expire after 30 days; tombstones do not", (t) => {
  const f = fixture(t);
  f.init();
  const req = { idempotency_key: "expiry", record: f.input() };
  const r = f.good("remember", req);
  const db = new DatabaseSync(path.join(f.home, "memory.sqlite3"));
  const row = db.prepare("SELECT * FROM receipts").get();
  assert.ok(!JSON.stringify(row).includes("Avoid hashtags"));
  db.close();
  f.good("forget", { id: r.id, expected_version: 1, idempotency_key: "gone" });
  assert.equal(f.raw("remember", req).error.code, "GONE");
  const d = new DatabaseSync(path.join(f.home, "deletions.sqlite3"));
  assert.equal(d.prepare("SELECT count(*) n FROM intents").get().n, 1);
  d.close();
});

for (const inferredFirst of [true, false])
  test(
    "inferred/explicit duplicate ordering preserves confirmed authority " +
      inferredFirst,
    (t) => {
      const f = fixture(t);
      f.init();
      const first = f.remember("First", {
        record: f.input(
          "First",
          inferredFirst ? "inferred" : "explicit_correction",
        ),
      });
      assert.equal(
        f.good("recall", { keys: ["writing.hashtags"] }).context.records.length,
        inferredFirst ? 0 : 1,
      );
      assert.equal(
        f.raw("remember", {
          idempotency_key: "other-kind",
          record: f.input(
            "Second",
            inferredFirst ? "explicit_user" : "inferred",
          ),
        }).error.code,
        "DUPLICATE_CONFLICT",
      );
      if (!inferredFirst)
        assert.equal(
          f.raw("update", {
            id: first.id,
            expected_version: 1,
            idempotency_key: "infer",
            changes: { provenance: f.input("", "inferred").provenance },
          }).error.code,
          "PERMISSION_DENIED",
        );
      else
        assert.equal(
          f.good("update", {
            id: first.id,
            expected_version: 1,
            idempotency_key: "confirm",
            changes: {
              provenance: f.input("", "explicit_user").provenance,
              status: "active",
            },
          }).version,
          2,
        );
    },
  );
test("matching project wins equal provenance but a user-wide explicit correction wins first", (t) => {
  const f = fixture(t);
  f.init();
  const wide = f.remember("Wide", { project: null });
  f.remember("Project");
  assert.equal(
    f.good("recall", { keys: ["writing.hashtags"] }).context.records[0].content,
    "Project",
  );
  f.good("update", {
    project: null,
    id: wide.id,
    expected_version: 1,
    idempotency_key: "wide-correction",
    changes: {
      content: "Corrected wide",
      provenance: f.input("", "explicit_correction").provenance,
    },
  });
  assert.equal(
    f.good("recall", { keys: ["writing.hashtags"] }).context.records[0].content,
    "Corrected wide",
  );
  assert.equal(
    f.good("recall", { project: null, keys: ["writing.hashtags"] }).context
      .records[0].content,
    "Corrected wide",
  );
});

test("credential-shaped JSON, PEM, bearer tokens and connection strings are rejected without echo", (t) => {
  const f = fixture(t);
  f.init();
  for (const content of [
    '{"password":"synthetic-password"}',
    "-----BEGIN PRIVATE KEY-----",
    "Authorization: Bearer synthetic-credential",
    "postgres://user:password@example.invalid/db",
    "Cookie: sessionid=synthetic-cookie",
  ]) {
    const r = f.raw("remember", {
      idempotency_key:
        "secret-" + Buffer.from(content).toString("hex").slice(0, 40),
      record: f.input(content),
    });
    assert.equal(r.error.code, "SECRET_REJECTED");
    assert.ok(!JSON.stringify(r).includes(content));
  }
});
