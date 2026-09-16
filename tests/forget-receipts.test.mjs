import test from "node:test";
import assert from "node:assert/strict";
import path from "node:path";
import { DatabaseSync } from "node:sqlite";
import { fixture } from "./helpers/harness.mjs";
import { seed } from "./helpers/synthetic.mjs";
import { Store } from "../src/storage.mjs";
import { saveReceipt, replay, RECEIPT_WINDOW } from "../src/receipts.mjs";

function sql(f, fn) {
  const db = new DatabaseSync(path.join(f.home, "memory.sqlite3"));
  try { return fn(db); } finally { db.close(); }
}
const count = (f) => sql(f, (db) => db.prepare("SELECT count(*) n FROM receipts").get().n);
const request = (r, key = "delete-original") => ({
  id: r.id, expected_version: 1, idempotency_key: key,
});
const clock = (time) => ({ LOCAL_MEMORY_TEST_NOW: new Date(time).toISOString() });

test("new-key delete retries retain original owner/project evidence and exact replay conflicts", (t) => {
  const f = fixture(t); f.init();
  const r = f.remember();
  const q = request(r);
  f.good("forget", q);
  const original = sql(f, (db) => db.prepare("SELECT * FROM receipts ORDER BY key").all());
  f.good("forget", request(r, "new-key"));
  f.good("forget", q);
  assert.equal(f.raw("forget", { ...q, expected_version: 2 }).error.code, "IDEMPOTENCY_CONFLICT");
  for (const scope of [{ skill: "other" }, { project: "prj-other" }, { project: null }]) {
    const denied = f.raw("forget", { ...request(r, "denied"), ...scope });
    assert.equal(denied.error.code, "NOT_FOUND");
    assert.equal(Object.hasOwn(denied.error, "current_version"), false);
  }
  assert.deepEqual(sql(f, (db) => db.prepare("SELECT * FROM receipts ORDER BY key").all()), original);
  assert.equal(f.raw("show", { id: r.id }).error.code, "NOT_FOUND");
});

test("owner retry includes day 30 boundary and fails closed after expiry or missing legacy evidence", (t) => {
  const f = fixture(t); f.init();
  const time = Date.parse("2026-09-16T12:00:00Z");
  const r = f.remember();
  f.good("forget", request(r), false, clock(time));
  f.good("forget", request(r, "boundary"), false, clock(time + RECEIPT_WINDOW));
  for (const idempotency_key of ["expired-new", "delete-original"])
    assert.equal(f.raw("forget", { ...request(r), idempotency_key }, false,
      clock(time + RECEIPT_WINDOW + 1)).error.code, "NOT_FOUND");
  f.good("forget", request(r, "management-expired"), true, clock(time + RECEIPT_WINDOW + 1));
  sql(f, (db) => db.prepare("DELETE FROM receipts WHERE json_extract(result,'$.deleted')=1").run());
  assert.equal(f.raw("forget", request(r, "legacy-new")).error.code, "NOT_FOUND");
  f.good("forget", request(r, "management-legacy"), true);
  assert.equal(f.good("recall", { keys: ["writing.hashtags"] }).context.records.length, 0);
});

test("pre-intent failures and changed keys/scopes retain exactly one unrenewed first reservation", (t) => {
  const f = fixture(t); f.init();
  const r = f.remember("Wide", { project: null });
  const originalTime = Date.now();
  for (let n = 0; n < 5; n++) {
    const q = { ...request(r, "attempt-" + n), project: n % 2 ? null : "prj-harbor" };
    assert.equal(f.raw("forget", q, false, {
      ...clock(originalTime + n * 1000), LOCAL_MEMORY_FAIL_POINT: "forget-receipt-durable",
    }).error.code, "STORAGE_UNAVAILABLE");
    assert.equal(count(f), 2);
    assert.equal(f.good("show", { id: r.id }).record.id, r.id);
  }
  const receipt = sql(f, (db) => db.prepare("SELECT * FROM receipts WHERE json_extract(result,'$.deleted')=1").get());
  assert.equal(receipt.created, originalTime);
  assert.equal(JSON.parse(receipt.key)[2], "attempt-0");
  f.good("forget", { ...request(r, "finish"), project: null });
  f.good("forget", request(r, "original-scope"));
  assert.equal(f.raw("forget", { ...request(r, "changed-scope"), project: null }).error.code, "NOT_FOUND");
  assert.deepEqual(sql(f, (db) => db.prepare("SELECT * FROM receipts WHERE json_extract(result,'$.deleted')=1").get()), receipt);
});

for (const point of ["before-commit", "forget-receipt-durable", "journal-durable", "active-purged", "copies-purged", "journal-complete"])
  test("kill recovery preserves scoped retry at " + point, (t) => {
    const f = fixture(t); f.init(); const r = f.remember();
    assert.equal(f.raw("forget", request(r), false, { LOCAL_MEMORY_KILL_POINT: point }).ok, false);
    const preIntent = ["before-commit", "forget-receipt-durable"].includes(point);
    const recalled = f.good("recall", { keys: ["writing.hashtags"] });
    assert.equal(recalled.context.records.length, preIntent ? 1 : 0);
    f.good("forget", request(r, "after-kill-new"));
    f.good("forget", request(r, "another-retry"));
    assert.equal(count(f), 2);
  });

test("pending purge remains suppressed and resumes with owner new-key evidence", (t) => {
  const f = fixture(t); f.init(); const r = f.remember();
  const fault = { LOCAL_MEMORY_FAIL_POINT: "purge-copies" };
  assert.equal(f.raw("forget", request(r), false, fault).error.code, "PURGE_PENDING");
  assert.equal(f.raw("forget", request(r, "pending-retry"), false, fault).error.code, "PURGE_PENDING");
  assert.equal(f.raw("recall", { keys: ["writing.hashtags"] }, false, fault).error.code, "PURGE_PENDING");
  f.good("forget", request(r, "recovered"));
  assert.equal(count(f), 2);
});

test("receipt write failure rolls back and cannot create deletion intent", (t) => {
  const f = fixture(t); f.init(); const r = f.remember();
  sql(f, (db) => db.exec("CREATE TRIGGER reject_receipt BEFORE INSERT ON receipts BEGIN SELECT RAISE(ABORT,'receipt unavailable'); END"));
  assert.equal(f.raw("forget", request(r)).ok, false);
  assert.equal(f.good("show", { id: r.id }).record.id, r.id);
  const journal = new DatabaseSync(path.join(f.home, "deletions.sqlite3"));
  assert.equal(journal.prepare("SELECT count(*) n FROM intents").get().n, 0);
  journal.close();
});

test("management and a skill named management cannot borrow each other's delete authorization", (t) => {
  const f = fixture(t); f.init();
  f.good("register", { skill_id: "management", keys: ["writing.hashtags"], capture: true }, true);
  const r = f.remember();
  f.good("forget", request(r), true);
  assert.equal(f.raw("forget", { ...request(r, "pretend-owner"), skill: "management", project: null }).error.code, "NOT_FOUND");
  const own = f.remember("Own", { skill: "management", project: null });
  f.good("forget", { ...request(own, "own-delete"), skill: "management", project: null });
  f.good("forget", { ...request(own, "own-retry"), skill: "management", project: null });
  sql(f, (db) => db.exec("UPDATE receipts SET result=json_remove(result,'$._owner_retry') WHERE json_extract(result,'$.deleted')=1"));
  assert.equal(f.raw("forget", { ...request(own, "ambiguous-legacy"), skill: "management", project: null }).error.code, "NOT_FOUND");
});

test("mixed capture/delete churn counts first-delete receipts against ordinary admission", (t) => {
  const f = fixture(t); f.init();
  const original = { idempotency_key: "original-save", record: f.input() };
  const r = f.good("remember", original);
  sql(f, (db) => db.prepare("WITH RECURSIVE n(x) AS (VALUES(1) UNION ALL SELECT x+1 FROM n WHERE x<99996) INSERT INTO receipts SELECT 'full-'||x,'digest','{}',? FROM n").run(Date.now()));
  f.good("forget", request(r));
  const second = f.remember();
  f.good("forget", request(second, "delete-second"));
  assert.equal(count(f), 100000);
  assert.equal(f.raw("remember", { idempotency_key: "blocked", record: f.input() }).error.code, "CAPACITY");
  assert.equal(f.raw("remember", original).error.code, "GONE");
  f.good("forget", request(second, "repeat-at-capacity"));
  assert.equal(count(f), 100000);
});

test("all 10,000 live IDs retain deletion receipts above full ordinary capacity", { timeout: 110000 }, (t) => {
  const f = fixture(t); f.init(); seed(f.home, 9999);
  const original = { idempotency_key: "preserved-original", record: f.input() };
  const saved = f.good("remember", original);
  // Exercise the production receipt/journal/purge primitives in one locked store.
  // Public subprocess cases above cover authentication, deadlines and recovery.
  const s = new Store(f.home); s.acquire(); s.load();
  const c = f.identity("ghostwriter", "prj-harbor");
  try {
    s.db.prepare("WITH RECURSIVE n(x) AS (VALUES(1) UNION ALL SELECT x+1 FROM n WHERE x<99999) INSERT INTO receipts SELECT 'full-'||x,'digest','{}',? FROM n").run(Date.now());
    const rows = s.all();
    const originalRequest = { protocol: 1, op: "remember", request_id: "retry",
      caller: c, ...original };
    const checkReplay = () => assert.equal(replay(originalRequest, s, c, () => true).id, saved.id);
    checkReplay();
    const started = performance.now();
    s.transaction(() => {
      for (const r of rows) {
        saveReceipt({ op: "forget", ...request(r, "delete-" + r.id) }, s, c, { id: r.id, deleted: true });
        if (r === rows[5000]) checkReplay();
      }
    });
    assert.equal(s.db.prepare("SELECT count(*) n FROM receipts").get().n, 110000);
    // Never evict original ordinary receipts, even at the full reserve bound.
    assert.equal(s.db.prepare("SELECT count(*) n FROM receipts WHERE key LIKE 'full-%' AND digest='digest' AND result='{}'").get().n, 99999);
    checkReplay();
    for (const r of rows) s.intent(r.id);
    s.replay();
    assert.equal(s.all().length, 0);
    assert.throws(checkReplay, { code: "GONE" });
    assert.equal(s.journal.prepare("SELECT count(*) n FROM intents WHERE complete=1").get().n, 10000);
    assert.equal(s.db.prepare("SELECT count(DISTINCT json_extract(result,'$.id')) n FROM receipts WHERE json_extract(result,'$.deleted')=1").get().n, 10000);
    assert.throws(() => s.transaction(() => saveReceipt({ op: "remember", idempotency_key: "blocked" }, s, c, {})), { code: "CAPACITY" });
    // An already-provisioned ID still reuses its reservation at 110,000.
    s.transaction(() => saveReceipt({ op: "forget", ...request(rows[0], "reserve-retry") }, s, c, { id: rows[0].id, deleted: true }));
    assert.equal(s.db.prepare("SELECT count(*) n FROM receipts").get().n, 110000);
    t.diagnostic("10,000 receipt reservations and journal purge: " + Math.round(performance.now() - started) + " ms");
  } finally { s.release(); }
  const id = sql(f, (db) => JSON.parse(db.prepare("SELECT result FROM receipts WHERE json_extract(result,'$.deleted')=1 LIMIT 1").get().result).id);
  const started = performance.now();
  f.good("forget", request({ id }, "public-full-retry"));
  const elapsed = performance.now() - started;
  assert.ok(elapsed < 5000, "Full-capacity public lookup must meet foreground deadline");
  t.diagnostic("110,000-receipt public owner retry: " + Math.round(elapsed) + " ms");
});

test("transaction rollback discards the transient deletion reservation index", (t) => {
  const f = fixture(t); f.init(); const r = f.remember();
  const s = new Store(f.home); s.acquire(); s.load();
  const c = f.identity("ghostwriter", "prj-harbor");
  try {
    assert.throws(() => s.transaction(() => {
      saveReceipt({ op: "forget", ...request(r) }, s, c, { id: r.id, deleted: true });
      throw new Error("synthetic rollback");
    }), /synthetic rollback/);
    assert.equal(s.db.prepare("SELECT count(*) n FROM receipts").get().n, 1);
    s.transaction(() => saveReceipt({ op: "forget", ...request(r, "after-rollback") }, s, c, { id: r.id, deleted: true }));
    assert.equal(s.db.prepare("SELECT count(*) n FROM receipts").get().n, 2);
  } finally { s.release(); }
  f.good("forget", request(r, "finish-after-rollback"));
  f.good("forget", request(r, "owner-retry"));
});
