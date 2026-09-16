import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { DatabaseSync } from "node:sqlite";
import { digest } from "../src/validation.mjs";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { fixture } from "./helpers/harness.mjs";
const exe = fileURLToPath(new URL("../bin/adapter.mjs", import.meta.url));
function setup(t) {
  const f = fixture(t);
  f.init();
  const source = path.join(f.dir, "voice.md");
  fs.writeFileSync(source, "# Synthetic voice\n");
  const run = (
    op,
    q,
    skill = "ghostwriter",
    env = {},
    cwd = path.join(f.dir, "project"),
  ) => {
    const r = spawnSync(process.execPath, [exe, skill, op], {
      cwd,
      input: JSON.stringify(q),
      encoding: "utf8",
      env: {
        ...process.env,
        LOCAL_MEMORY_HOME: f.home,
        NODE_ENV: "test",
        LOCAL_MEMORY_TESTING: "1",
        ...env,
      },
      timeout: 6500,
    });
    return r.stdout ? JSON.parse(r.stdout) : { ok: false, killed: true };
  };
  assert.equal(
    run("setup", { source_path: source, source_id: "voice" }).ok,
    true,
  );
  assert.equal(run("setup", {}, "writing-peer").ok, true);
  return { ...f, source, run };
}
test("source first: corrections, private defaults, revision freshness, suppression, rollback", (t) => {
  const f = setup(t);
  const first = f.run("request", {
    op: "capture",
    key: "writing.hashtags",
    content: "Avoid hashtags",
    durable: true,
  });
  assert.equal(first.memory, "synced");
  assert.match(fs.readFileSync(f.source, "utf8"), /Avoid hashtags/);
  assert.equal(
    f.run("request", { op: "recall", keys: ["writing.hashtags"] }).context
      .records[0].content,
    "Avoid hashtags",
  );
  assert.equal(
    f.run(
      "request",
      { op: "recall", keys: ["writing.hashtags"] },
      "writing-peer",
    ).context.records.length,
    0,
  );
  assert.equal(
    f.run("request", {
      op: "capture",
      key: "writing.hashtags",
      content: "At most one",
      durable: true,
    }).version,
    2,
  );
  fs.appendFileSync(f.source, "\nUse one relevant hashtag\n");
  assert.equal(
    f.run("request", { op: "recall", keys: ["writing.hashtags"] }).context
      .records.length,
    0,
  );
  assert.equal(f.run("request", { op: "reconcile", selected_keys: ["writing.hashtags"] }).error.code, "SOURCE_STALE");
  const reconciled = f.run("request", {
    op: "reconcile",
    selected_keys: ["writing.hashtags"],
    confirmed: true,
    content: "Use one relevant hashtag",
  });
  assert.equal(reconciled.memory, "synced");
  assert.equal(
    f.raw(
      "update",
      {
        id: reconciled.id,
        expected_version: reconciled.version,
        idempotency_key: "direct",
        changes: { content: "Memory only" },
      },
      true,
    ).error.code,
    "SOURCE_REQUIRED",
  );
  assert.equal(
    f.run("request", {
      op: "forget",
      id: reconciled.id,
      expected_version: reconciled.version,
    }).source_retained,
    true,
  );
  assert.equal(
    f.run("request", { op: "reconcile", selected_keys: ["writing.hashtags"] })
      .memory,
    "suppressed",
  );
  assert.equal(f.run("disable", {}).source_retained, true);
  assert.equal(
    f.run("request", { op: "recall", keys: ["writing.hashtags"] }).memory,
    "disabled",
  );
  assert.equal(f.run("enable", {}).ok, true);
  assert.equal(
    f.run("request", { op: "reconcile", selected_keys: ["writing.hashtags"] })
      .memory,
    "suppressed",
  );
  assert.match(fs.readFileSync(f.source, "utf8"), /At most one/);
});
test("recipient source freshness plus independently registered project isolation", (t) => {
  const f = setup(t);
  const r = f.run("request", {
    op: "capture",
    key: "writing.hashtags",
    content: "Avoid hashtags",
    durable: true,
  });
  const select = f.good(
    "selection",
    { id: r.id, expected_version: r.version, recipients: ["writing-peer"] },
    true,
  );
  const share = f.run("request", {
    op: "share",
    id: r.id,
    expected_version: r.version,
    recipients: ["writing-peer"],
    selection_token: select.selection_token,
  });
  assert.equal(share.ok, true, JSON.stringify(share));
  assert.equal(
    f.run(
      "request",
      { op: "recall", keys: ["writing.hashtags"] },
      "writing-peer",
    ).context.records.length,
    1,
  );
  assert.equal(
    f.run(
      "request",
      { op: "recall", keys: ["writing.hashtags"] },
      "writing-peer",
      {},
      path.join(f.dir, "elsewhere"),
    ).context.records.length,
    0,
  );
  fs.appendFileSync(f.source, "Changed source");
  assert.equal(
    f.run(
      "request",
      { op: "recall", keys: ["writing.hashtags"] },
      "writing-peer",
    ).context.records.length,
    0,
  );
  fs.renameSync(f.source, f.source + ".unavailable");
  assert.equal(
    f.run(
      "request",
      { op: "recall", keys: ["writing.hashtags"] },
      "writing-peer",
    ).context.records.length,
    0,
  );
});
test("source/mirror failures preserve authority and report pending sync", (t) => {
  const f = setup(t);
  let r = f.run(
    "request",
    {
      op: "capture",
      key: "writing.hashtags",
      content: "Failed source",
      durable: true,
    },
    "ghostwriter",
    { LOCAL_MEMORY_FAIL_POINT: "source-write" },
  );
  assert.equal(r.ok, false);
  assert.equal(
    f.good("recall", { keys: ["writing.hashtags"] }).context.records.length,
    0,
  );
  r = f.run(
    "request",
    {
      op: "capture",
      key: "writing.hashtags",
      content: "Saved source only",
      durable: true,
    },
    "ghostwriter",
    { LOCAL_MEMORY_FAIL_POINT: "before-commit" },
  );
  assert.equal(r.memory, "pending");
  assert.equal(r.source_saved, true);
  assert.match(fs.readFileSync(f.source, "utf8"), /Saved source only/);
  assert.equal(
    f.run("request", { op: "reconcile", selected_keys: ["writing.hashtags"] })
      .memory,
    "synced",
  );
});
test("lost mirror acknowledgment replays without adding a version; current instructions override recall", (t) => {
  const f = setup(t);
  const r = f.run(
    "request",
    {
      op: "capture",
      key: "writing.hashtags",
      content: "No tags",
      durable: true,
    },
    "ghostwriter",
    { LOCAL_MEMORY_KILL_POINT: "after-commit" },
  );
  assert.equal(r.memory, "pending");
  const replay = f.run("request", {
    op: "reconcile",
    selected_keys: ["writing.hashtags"],
  });
  assert.equal(replay.version, 1);
  assert.equal(
    f.run("request", {
      op: "recall",
      keys: ["writing.hashtags"],
      overridden_keys: ["writing.hashtags"],
    }).context.records.length,
    0,
  );
  const second = f.run(
    "request",
    {
      op: "capture",
      key: "writing.hashtags",
      content: "One tag",
      durable: true,
    },
    "ghostwriter",
    { LOCAL_MEMORY_KILL_POINT: "after-commit" },
  );
  assert.equal(second.memory, "pending");
  assert.equal(
    f.run("request", { op: "reconcile", selected_keys: ["writing.hashtags"] })
      .version,
    2,
  );
});
test("second adapter confirms broader records and rejects model-provided scope", (t) => {
  const f = setup(t);
  assert.equal(
    f.run(
      "request",
      {
        op: "capture",
        key: "project.acronym",
        content: "HBR means Harbor",
        type: "fact",
        durable: true,
      },
      "writing-peer",
    ).ok,
    false,
  );
  assert.equal(
    f.run(
      "request",
      {
        op: "capture",
        key: "project.acronym",
        content: "HBR means Harbor",
        type: "fact",
        durable: true,
        confirmed: true,
      },
      "writing-peer",
    ).ok,
    true,
  );
  assert.equal(
    f.run(
      "request",
      {
        op: "capture",
        key: "project.audience",
        content: "Developers",
        type: "project_context",
        durable: true,
        confirmed: true,
      },
      "writing-peer",
    ).ok,
    true,
  );
  assert.equal(
    f.run(
      "request",
      {
        op: "recall",
        keys: ["project.acronym"],
        caller: { skill_id: "ghostwriter" },
      },
      "writing-peer",
    ).ok,
    false,
  );
  assert.equal(
    f.run(
      "request",
      { op: "recall", keys: ["project.acronym"] },
      "writing-peer",
      {},
      f.dir,
    ).context.records.length,
    0,
  );
});

test("unavailable memory still leaves a verified source correction and pending sync", (t) => {
  const f = setup(t);
  const db = path.join(f.home, "memory.sqlite3");
  fs.renameSync(db, db + ".hold");
  try {
    const r = f.run("request", {
      op: "capture",
      key: "writing.hashtags",
      content: "Source remains usable",
      durable: true,
    });
    assert.equal(r.source_saved, true);
    assert.equal(r.memory, "pending");
    assert.equal(r.error.code, "STORAGE_MISSING");
    assert.match(fs.readFileSync(f.source, "utf8"), /Source remains usable/);
  } finally {
    fs.renameSync(db + ".hold", db);
  }
  assert.equal(
    f.run("request", { op: "reconcile", selected_keys: ["writing.hashtags"] })
      .memory,
    "synced",
  );
});

test("second adapter reuses the observed event timestamp when replaying a lost acknowledgment", (t) => {
  const f = setup(t);
  const q = {
    op: "capture",
    key: "project.acronym",
    type: "fact",
    content: "HBR means Harbor",
    durable: true,
    confirmed: true,
    source_event: "peer-stable-event",
  };
  assert.equal(
    f.run("request", q, "writing-peer", {
      LOCAL_MEMORY_KILL_POINT: "after-commit",
    }).ok,
    false,
  );
  const replay = f.run("request", q, "writing-peer");
  assert.equal(replay.ok, true, JSON.stringify(replay));
  assert.equal(replay.version, 1);
});

test("review fixes: repeat setup, reconciliation provenance and renewal, peer correction", (t) => {
  const f = setup(t);
  const before = fs.readFileSync(path.join(f.home, "identity.json"), "utf8");
  assert.equal(f.run("setup", { source_id: "voice", source_path: f.source + ".other" }).error.code, "ALREADY_INITIALIZED");
  assert.equal(fs.readFileSync(path.join(f.home, "identity.json"), "utf8"), before);
  const first = f.run("request", { op: "capture", key: "writing.hashtags", content: "Avoid hashtags", durable: true });
  for (let i = 0; i < 2; i++) assert.equal(f.run("request", { op: "reconcile", selected_keys: ["writing.hashtags"] }).version, first.version);
  assert.equal(f.good("show", { id: first.id }).record.provenance.kind, "explicit_user");
  const future = { LOCAL_MEMORY_TEST_NOW: new Date(Date.now() + 181 * 86400000).toISOString() };
  const corrected = f.run("request", { op: "capture", key: "writing.hashtags", content: "One hashtag", durable: true, correction: true }, "ghostwriter", future);
  assert.equal(corrected.version, 2);
  assert.equal(f.run("request", { op: "recall", keys: ["writing.hashtags"] }, "ghostwriter", future).context.records[0].content, "One hashtag");
  const q = { op: "capture", key: "project.acronym", type: "fact", content: "HBR means Harbor", durable: true, confirmed: true, source_event: "first" };
  const peer = f.run("request", q, "writing-peer");
  const update = { ...q, content: "HBR means Harbor Bay", correction: true, id: peer.id, expected_version: peer.version, source_event: "second" };
  assert.equal(f.run("request", update, "writing-peer", future).version, 2);
  assert.equal(f.run("request", { op: "recall", keys: [q.key] }, "writing-peer", future).context.records[0].content, update.content);
  const pref = f.run("request", { ...q, key: "writing.hashtags", type: "preference", source_event: "preference" }, "writing-peer");
  const correction = { ...q, key: "writing.hashtags", type: "preference", correction: true, id: pref.id, expected_version: pref.version, source_event: "preference-correction" };
  assert.equal(f.run("request", correction, "writing-peer", future).version, 2);
  assert.equal(f.run("request", { op: "recall", keys: [correction.key] }, "writing-peer", future).context.records[0].id, pref.id);
  assert.equal(f.run("request", { ...update, source_event: "third" }, "writing-peer").error.code, "VERSION_CONFLICT");
});

test("sharing revocation survives stale and unreadable sources", (t) => {
  const f = setup(t);
  const r = f.run("request", { op: "capture", key: "writing.hashtags", content: "Avoid hashtags", durable: true, correction: true });
  assert.equal(f.good("show", { id: r.id }).record.provenance.kind, "explicit_correction");
  const selection = f.good("selection", { id: r.id, expected_version: 1, recipients: ["writing-peer"] }, true);
  assert.equal(f.run("request", { op: "share", id: r.id, expected_version: 1, recipients: ["writing-peer"], selection_token: selection.selection_token }).version, 2);
  fs.renameSync(f.source, f.source + ".hold");
  for (const mirror of [null, false])
    assert.equal(f.raw("update", { id: r.id, expected_version: 2, idempotency_key: "detach-" + mirror, patch: { share_with: [], mirror } }, true).error.code, "SOURCE_REQUIRED");
  assert.equal(f.run("request", { op: "recall", keys: ["writing.hashtags"] }).context.records.length, 0);
  assert.equal(f.run("request", { op: "share", id: r.id, expected_version: 2, recipients: [], selection_token: "" }).version, 3);
  assert.equal(f.good("update", { id: r.id, expected_version: 3, idempotency_key: "management-revoke", patch: { share_with: [] } }, true).version, 4);
  fs.renameSync(f.source + ".hold", f.source);
  assert.equal(f.run("request", { op: "recall", keys: ["writing.hashtags"] }, "writing-peer").context.records.length, 0);
});

test("adapter deadline releases descendant engine locks", (t) => {
  const f = setup(t);
  const result = f.run("request", { op: "capture", key: "writing.hashtags", content: "Delayed write", durable: true }, "ghostwriter", { LOCAL_MEMORY_FAIL_POINT: "foreground-timeout" });
  assert.equal(result.ok, false);
  const started = Date.now();
  assert.equal(f.good("recall", { keys: ["writing.hashtags"] }).context.records.length, 0);
  assert.ok(Date.now() - started < 800);
});


test("adapter SQLite contention reports retryable BUSY within its deadline", (t) => {
  const f = setup(t);
  const db = new DatabaseSync(path.join(f.home, "adapter-ghostwriter.lock.sqlite3"));
  fs.chmodSync(path.join(f.home, "adapter-ghostwriter.lock.sqlite3"), 0o600);
  try {
    db.exec("BEGIN EXCLUSIVE");
    const start = Date.now();
    const r = f.run("request", { op: "recall", keys: ["writing.hashtags"] });
    assert.equal(r.error.code, "BUSY");
    assert.equal(r.error.retryable, true);
    assert.ok(Date.now() - start < 5000);
  } finally { db.exec("ROLLBACK"); db.close(); }
});

test("mirror identifiers reject secret-shaped values before persistence", (t) => {
  const f = setup(t);
  for (const field of ["event", "source_id"]) {
    const mirror = { source_id: "voice", event: "event-safe", revision: digest(fs.readFileSync(f.source)) };
    mirror[field] = "sk-abcdefghijklmnopqrstuv";
    const r = f.raw("remember", { idempotency_key: "secret-" + field, record: { ...f.input(), mirror } });
    assert.equal(r.error.code, "SECRET_REJECTED");
    assert.equal(JSON.stringify(r).includes(mirror[field]), false);
  }
  assert.equal(f.good("list", {}, true).records.length, 0);
});

for (const fault of ["LOCAL_MEMORY_KILL_POINT", "LOCAL_MEMORY_FAIL_POINT"])
  test("source commit boundary retains recoverable pending event: " + fault, (t) => {
    const f = setup(t);
    const r = f.run("request", { op: "capture", key: "writing.hashtags", content: "Avoid hashtags", durable: true },
      "ghostwriter", { [fault]: "source-committed" });
    assert.equal(r.ok, false);
    if (fault === "LOCAL_MEMORY_FAIL_POINT") {
      assert.equal(r.source_saved, true);
      assert.equal(r.memory, "pending");
    }
    assert.match(fs.readFileSync(f.source, "utf8"), /Avoid hashtags/);
    const recovered = f.run("request", { op: "reconcile", selected_keys: ["writing.hashtags"], confirmed: true, content: "Avoid hashtags" });
    assert.equal(recovered.memory, "synced");
    assert.equal(f.good("recall", { keys: ["writing.hashtags"] }).context.records[0].content, "Avoid hashtags");
  });
