import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { DatabaseSync } from "node:sqlite";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import { fixture } from "./helpers/harness.mjs";
const exe = fileURLToPath(new URL("../bin/local-memory.mjs", import.meta.url));
function sql(f, fn) {
  const d = new DatabaseSync(path.join(f.home, "memory.sqlite3"));
  try {
    return fn(d);
  } finally {
    d.close();
  }
}
function child(f, q, env = {}) {
  return new Promise((resolve, reject) => {
    const p = spawn(process.execPath, [exe, "request"], {
      env: {
        ...process.env,
        LOCAL_MEMORY_HOME: f.home,
        NODE_ENV: "test",
        LOCAL_MEMORY_TESTING: "1",
        ...env,
      },
    });
    let out = "";
    p.stdout.on("data", (b) => (out += b));
    p.on("error", reject);
    p.on("close", () => {
      try {
        resolve(JSON.parse(out));
      } catch (e) {
        reject(e);
      }
    });
    p.stdin.end(
      JSON.stringify({
        protocol: 1,
        request_id: "concurrent",
        caller: f.identity("ghostwriter", "prj-harbor"),
        ...q,
      }),
    );
  });
}
test("two writers serialize independent writes and stale expected versions conflict", async (t) => {
  const f = fixture(t);
  f.init();
  const r = f.remember();
  const changes = {
    content: "One hashtag",
    provenance: f.input("", "explicit_correction").provenance,
  };
  const result = await Promise.all(
    ["one", "two"].map((idempotency_key) =>
      child(f, {
        op: "update",
        id: r.id,
        expected_version: 1,
        idempotency_key,
        changes,
      }),
    ),
  );
  assert.equal(result.filter((x) => x.ok).length, 1);
  assert.equal(result.find((x) => !x.ok).error.code, "VERSION_CONFLICT");
  assert.equal(result.find((x) => !x.ok).error.current_version, 2);
  const independent = await Promise.all(
    ["project.acronym", "project.audience"].map((key) =>
      child(f, {
        op: "remember",
        idempotency_key: key,
        record: { ...f.input(key), key },
      }),
    ),
  );
  assert.equal(
    independent.every((x) => x.ok),
    true,
  );
});
test("lock contention has a bounded BUSY response", (t) => {
  const f = fixture(t);
  f.init();
  const lock = new DatabaseSync(path.join(f.home, "maintenance.sqlite3"));
  lock.exec("BEGIN EXCLUSIVE");
  try {
    const start = Date.now();
    const r = f.raw("recall", { keys: ["writing.hashtags"] });
    assert.equal(r.error.code, "BUSY");
    assert.ok(Date.now() - start < 4500);
  } finally {
    lock.exec("ROLLBACK");
    lock.close();
  }
});
for (const kill of ["before-commit", "after-commit"])
  test("lost acknowledgment atomicity at " + kill, (t) => {
    const f = fixture(t);
    f.init();
    const req = { idempotency_key: "lost", record: f.input() };
    assert.equal(
      f.raw("remember", req, false, { LOCAL_MEMORY_KILL_POINT: kill }).ok,
      false,
    );
    const r = f.good("remember", req);
    assert.equal(r.version, 1);
    assert.equal(f.good("list", {}, true).records.length, 1);
    sql(f, (d) => {
      assert.equal(d.prepare("SELECT count(*) n FROM receipts").get().n, 1);
      assert.ok(
        !d
          .prepare("SELECT result FROM receipts")
          .get()
          .result.includes("Avoid hashtags"),
      );
    });
  });
test("review and expiry exclude records before foreground purge without renewing retention", (t) => {
  const f = fixture(t);
  f.init();
  const r = f.remember("No hashtags", {
    record: {
      ...f.input("No hashtags"),
      review_after: "2026-09-17T00:00:00Z",
      expires_at: "2026-09-18T00:00:00Z",
    },
  });
  assert.equal(
    f.good("recall", { keys: ["writing.hashtags"] }, false, {
      LOCAL_MEMORY_TEST_NOW: "2026-09-17T01:00:00Z",
    }).context.records.length,
    0,
  );
  assert.equal(
    f.good("show", { id: r.id }).record.review_after,
    "2026-09-17T00:00:00.000Z",
  );
  assert.equal(
    f.good("show", { id: r.id }, false, {
      LOCAL_MEMORY_TEST_NOW: "2026-09-18T01:00:00Z",
    }).record.expired,
    true,
  );
  f.good("maintain", {}, true, {
    LOCAL_MEMORY_TEST_NOW: "2026-09-18T01:00:00Z",
  });
  assert.equal(f.raw("show", { id: r.id }).error.code, "NOT_FOUND");
});
test("initialized database missing, permissions, symlinks, corruption, deletion journal absence fail distinctly", (t) => {
  const f = fixture(t);
  f.init();
  const db = path.join(f.home, "memory.sqlite3");
  fs.renameSync(db, db + ".hold");
  assert.equal(
    f.raw("recall", { keys: ["writing.hashtags"] }).error.code,
    "STORAGE_MISSING",
  );
  fs.renameSync(db + ".hold", db);
  fs.chmodSync(db, 0o644);
  assert.equal(
    f.raw("recall", { keys: ["writing.hashtags"] }).error.code,
    "STORAGE_UNAVAILABLE",
  );
  fs.chmodSync(db, 0o600);
  fs.renameSync(db, db + ".hold");
  fs.symlinkSync(db + ".hold", db);
  assert.equal(
    f.raw("recall", { keys: ["writing.hashtags"] }).error.code,
    "STORAGE_UNAVAILABLE",
  );
  fs.unlinkSync(db);
  fs.renameSync(db + ".hold", db);
  fs.renameSync(
    path.join(f.home, "deletions.sqlite3"),
    path.join(f.home, "journal.hold"),
  );
  assert.equal(
    f.raw("recall", { keys: ["writing.hashtags"] }).error.code,
    "CORRUPT",
  );
  fs.renameSync(
    path.join(f.home, "journal.hold"),
    path.join(f.home, "deletions.sqlite3"),
  );
  fs.writeFileSync(db, "not a SQLite database");
  assert.equal(
    f.raw("recall", { keys: ["writing.hashtags"] }).error.code,
    "CORRUPT",
  );
  assert.equal(fs.readFileSync(db, "utf8"), "not a SQLite database");
  assert.ok(fs.readdirSync(path.join(f.home, "quarantine")).length > 0);
});
test("old/new schema and failed mandatory backup/migration preserve the old state", (t) => {
  const f = fixture(t);
  f.init();
  sql(f, (d) => d.exec("UPDATE metadata SET value='2' WHERE name='schema'"));
  assert.equal(
    f.raw("recall", { keys: ["writing.hashtags"] }).error.code,
    "SCHEMA_TOO_NEW",
  );
  sql(f, (d) => d.exec("UPDATE metadata SET value='0' WHERE name='schema'"));
  assert.equal(
    f.raw("recall", { keys: ["writing.hashtags"] }).error.code,
    "MIGRATION_REQUIRED",
  );
  assert.equal(
    f.raw("migrate", {}, true, { LOCAL_MEMORY_FAIL_POINT: "backup-start" }).ok,
    false,
  );
  assert.equal(
    sql(
      f,
      (d) =>
        d.prepare("SELECT value FROM metadata WHERE name='schema'").get().value,
    ),
    "0",
  );
  assert.equal(
    f.raw("migrate", {}, true, { LOCAL_MEMORY_FAIL_POINT: "migration" }).ok,
    false,
  );
  assert.equal(
    sql(
      f,
      (d) =>
        d.prepare("SELECT value FROM metadata WHERE name='schema'").get().value,
    ),
    "0",
  );
  assert.equal(f.good("migrate", {}, true).schema, 1);
});
for (const kill of [
  "restore-copied",
  "restore-reset",
  "restore-quarantined",
  "restore-published",
])
  test("restore kill recovery cannot expose old sharing: " + kill, (t) => {
    const f = fixture(t);
    f.init();
    const select = f.good(
      "selection",
      {
        owner_skill: "ghostwriter",
        project_id: "prj-harbor",
        recipients: ["writing-peer"],
      },
      true,
    );
    const r = f.remember("", {
      record: { ...f.input(), share_with: ["writing-peer"] },
      selection_token: select.selection_token,
    });
    const snap = f.good("backup", {}, true);
    f.good("update", {
      id: r.id,
      expected_version: 1,
      idempotency_key: "revoke",
      changes: { share_with: [] },
    });
    assert.equal(
      f.raw("restore", { snapshot: snap.snapshot }, true, {
        LOCAL_MEMORY_KILL_POINT: kill,
      }).ok,
      false,
    );
    assert.equal(
      f.good("recall", { skill: "writing-peer", keys: ["writing.hashtags"] })
        .context.records.length,
      0,
    );
    assert.equal(
      f.good("recall", { keys: ["writing.hashtags"] }).context.records.length,
      1,
    );
  });
test("restore applies current deletion ledger and rejects missing/corrupt manifests", (t) => {
  const f = fixture(t);
  f.init();
  const r = f.remember();
  const snap = f.good("backup", {}, true),
    backup = path.join(f.home, "backups");
  const saved = fs
    .readdirSync(backup)
    .map((n) => [n, fs.readFileSync(path.join(backup, n))]);
  f.good("forget", {
    id: r.id,
    expected_version: 1,
    idempotency_key: "forget",
  });
  for (const [n, b] of saved)
    fs.writeFileSync(path.join(backup, n), b, { mode: 0o600 });
  f.good("restore", { snapshot: snap.snapshot }, true);
  assert.equal(
    f.good("recall", { keys: ["writing.hashtags"] }).context.records.length,
    0,
  );
  fs.writeFileSync(path.join(backup, snap.snapshot + ".json"), "{}");
  assert.equal(
    f.raw("restore", { snapshot: snap.snapshot }, true).error.code,
    "CORRUPT",
  );
});
test("failed backup purge suppresses reads and retry finishes physical cleanup", (t) => {
  const f = fixture(t);
  f.init();
  const r = f.remember();
  f.good("backup", {}, true);
  const req = { id: r.id, expected_version: 1, idempotency_key: "forget" };
  const error = f.raw("forget", req, false, {
    LOCAL_MEMORY_FAIL_POINT: "purge-copies",
  });
  assert.equal(error.error.code, "PURGE_PENDING");
  assert.equal(error.error.active_deleted, true);
  assert.equal(
    f.raw("recall", { keys: ["writing.hashtags"] }, false, {
      LOCAL_MEMORY_FAIL_POINT: "purge-copies",
    }).error.code,
    "PURGE_PENDING",
  );
  assert.equal(f.good("forget", req).deleted, true);
  assert.equal(
    f.good("recall", { keys: ["writing.hashtags"] }).context.records.length,
    0,
  );
});
test("reader holding WAL prevents compaction but never logical deletion", (t) => {
  const f = fixture(t);
  f.init();
  const r = f.remember();
  const reader = new DatabaseSync(path.join(f.home, "memory.sqlite3"));
  reader.exec("BEGIN");
  reader.prepare("SELECT count(*) FROM records").get();
  try {
    const result = f.good("forget", {
      id: r.id,
      expected_version: 1,
      idempotency_key: "held",
    });
    assert.equal(result.physical_cleanup, "pending");
    assert.equal(
      f.good("recall", { keys: ["writing.hashtags"] }).context.records.length,
      0,
    );
  } finally {
    reader.exec("ROLLBACK");
    reader.close();
  }
  assert.equal(f.good("maintain", {}, true).physical_cleanup, "complete");
});
test("FTS unavailable discloses scan and retains exact-key semantics", (t) => {
  const f = fixture(t);
  f.init();
  f.remember();
  sql(f, (d) => d.exec("DROP TABLE records_fts"));
  const r = f.good("recall", { query: "hashtags" });
  assert.equal(r.retrieval_mode, "scan");
  assert.equal(r.context.records[0].content, "Avoid hashtags");
});

test("WAL pressure refuses captures at 64 MiB but permits recall and deletion", (t) => {
  const f = fixture(t);
  f.init();
  const r = f.remember();
  const writer = new DatabaseSync(path.join(f.home, "memory.sqlite3"));
  const reader = new DatabaseSync(path.join(f.home, "memory.sqlite3"));
  writer.exec(
    "PRAGMA wal_autocheckpoint=0; CREATE TABLE wal_fixture (padding BLOB)",
  );
  reader.exec("BEGIN");
  reader.prepare("SELECT count(*) FROM records").get();
  try {
    writer.exec("INSERT INTO wal_fixture VALUES (zeroblob(70*1024*1024))");
    const pressure = f.good("recall", { keys: ["writing.hashtags"] });
    assert.equal(pressure.maintenance_pressure, true);
    assert.ok(pressure.wal_bytes >= 64 * 1024 * 1024);
    assert.equal(
      f.raw("remember", {
        idempotency_key: "pressure",
        record: { ...f.input(), key: "project.acronym" },
      }).error.code,
      "CAPACITY",
    );
    assert.equal(
      f.good("forget", {
        id: r.id,
        expected_version: 1,
        idempotency_key: "pressure-delete",
      }).deleted,
      true,
    );
  } finally {
    reader.exec("ROLLBACK");
    reader.close();
    writer.close();
  }
});

test("unwritable managed backup directory keeps deletion pending until permissions recover", (t) => {
  const f = fixture(t);
  f.init();
  const r = f.remember();
  f.good("backup", {}, true);
  const dir = path.join(f.home, "backups");
  fs.chmodSync(dir, 0o500);
  try {
    const result = f.raw("forget", {
      id: r.id,
      expected_version: 1,
      idempotency_key: "unwritable",
    });
    assert.equal(result.error.code, "PURGE_PENDING");
    assert.equal(result.error.active_deleted, true);
  } finally {
    fs.chmodSync(dir, 0o700);
  }
  assert.equal(
    f.good("recall", { keys: ["writing.hashtags"] }).context.records.length,
    0,
  );
});

test("explicit restore can recover a missing initialized database using the current journal", (t) => {
  const f = fixture(t);
  f.init();
  f.remember();
  const backup = f.good("backup", {}, true);
  fs.renameSync(
    path.join(f.home, "memory.sqlite3"),
    path.join(f.home, "missing.hold"),
  );
  assert.equal(
    f.good("restore", { snapshot: backup.snapshot }, true).restored,
    true,
  );
  assert.equal(
    f.good("recall", { keys: ["writing.hashtags"] }).context.records.length,
    1,
  );
});

test("SQLite disk-full failure rolls back content/index/receipt and never acknowledges save", (t) => {
  const f = fixture(t);
  f.init();
  const req = {
    idempotency_key: "disk-full",
    record: f.input("Must not be saved"),
  };
  const failed = f.raw("remember", req, false, {
    LOCAL_MEMORY_FAIL_POINT: "disk-full",
  });
  assert.equal(failed.error.code, "STORAGE_UNAVAILABLE");
  assert.equal(
    f.good("recall", { keys: ["writing.hashtags"] }).context.records.length,
    0,
  );
  sql(f, (d) => {
    assert.equal(d.prepare("SELECT count(*) n FROM receipts").get().n, 0);
    assert.equal(
      d
        .prepare(
          "SELECT count(*) n FROM sqlite_master WHERE name='fault_disk_full'",
        )
        .get().n,
      0,
    );
  });
  assert.equal(f.good("remember", req).version, 1);
});
test("supervisor enforces the overall foreground deadline and releases killed locks", (t) => {
  const f = fixture(t);
  f.init();
  const start = Date.now();
  const failed = f.raw("recall", { keys: ["writing.hashtags"] }, false, {
    LOCAL_MEMORY_FAIL_POINT: "foreground-timeout",
  });
  assert.equal(failed.error.code, "BUSY");
  assert.ok(Date.now() - start < 5500);
  assert.equal(f.good("recall", { keys: ["writing.hashtags"] }).ok, true);
});
