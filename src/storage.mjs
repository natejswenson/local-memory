import { DatabaseSync, backup } from "node:sqlite";
import fs from "node:fs";
import path from "node:path";
import os from "node:os";
import {
  check,
  fail,
  uuid,
  iso,
  now,
  digest,
  point,
  LIMITS,
} from "./validation.mjs";
export const SCHEMA = 1;
let lockDeadline = Infinity;
function busyBudget(db) {
  db.exec(
    "PRAGMA busy_timeout=" +
      Math.max(0, Math.min(2000, lockDeadline - Date.now())),
  );
}
export function location() {
  const p =
    process.env.LOCAL_MEMORY_HOME ||
    (process.platform === "darwin"
      ? path.join(os.homedir(), "Library/Application Support/local-memory")
      : path.join(
          process.env.XDG_DATA_HOME || path.join(os.homedir(), ".local/share"),
          "local-memory",
        ));
  check(path.isAbsolute(p), "STORAGE_UNAVAILABLE");
  check(process.platform !== "win32", "STORAGE_UNAVAILABLE");
  check(
    !/(?:^\/net\/|^\/Volumes\/|Dropbox|OneDrive|Google Drive|Mobile Documents|iCloud)/i.test(
      p,
    ),
    "STORAGE_UNAVAILABLE",
  );
  return path.resolve(p);
}
export function safe(p, directory = false) {
  const s = fs.lstatSync(p);
  check(
    !s.isSymbolicLink() && (directory ? s.isDirectory() : s.isFile()),
    "STORAGE_UNAVAILABLE",
  );
  check(
    s.uid === process.getuid() && (s.mode & 0o077) === 0,
    "STORAGE_UNAVAILABLE",
  );
  return s;
}
export function exists(p) {
  try {
    fs.lstatSync(p);
    return true;
  } catch (e) {
    if (e.code === "ENOENT") return false;
    throw e;
  }
}
function ancestors(p) {
  let a = path.dirname(p);
  while (a !== path.dirname(a)) {
    if (exists(a))
      check(!fs.lstatSync(a).isSymbolicLink(), "STORAGE_UNAVAILABLE");
    a = path.dirname(a);
  }
}
export function syncDir(p) {
  const f = fs.openSync(p, "r");
  try {
    fs.fsyncSync(f);
  } finally {
    fs.closeSync(f);
  }
}
export function atomic(p, data) {
  const temp = p + "." + uuid() + ".tmp";
  try {
    const f = fs.openSync(temp, "wx", 0o600);
    try {
      fs.writeFileSync(f, data);
      fs.fsyncSync(f);
    } finally {
      fs.closeSync(f);
    }
    fs.renameSync(temp, p);
    syncDir(path.dirname(p));
  } finally {
    fs.rmSync(temp, { force: true });
  }
}
export function json(p) {
  safe(p);
  try {
    return JSON.parse(fs.readFileSync(p, "utf8"));
  } catch {
    fail("CORRUPT");
  }
}
function version(db) {
  const node = process.versions.node.split(".").map(Number);
  check(
    node[0] * 1000000 + node[1] * 1000 + node[2] >= 25002001,
    "STORAGE_UNAVAILABLE",
  );
  const v = db
    .prepare("select sqlite_version() v")
    .get()
    .v.split(".")
    .map(Number);
  check(v[0] * 1000000 + v[1] * 1000 + v[2] >= 3051003, "STORAGE_UNAVAILABLE");
  return v.join(".");
}
function open(p) {
  if (exists(p)) safe(p);
  const d = new DatabaseSync(p, {
    timeout: Math.max(0, Math.min(2000, lockDeadline - Date.now())),
  });
  busyBudget(d);
  version(d);
  busyBudget(d);
  d.exec("PRAGMA synchronous=FULL; PRAGMA foreign_keys=ON;");
  return d;
}
export function integrity(db) {
  check(db.prepare("PRAGMA quick_check").get().quick_check === "ok", "CORRUPT");
}
export class Store {
  constructor(home) {
    lockDeadline = Date.now() + 2000;
    this.home = home;
    this.dbPath = path.join(home, "memory.sqlite3");
  }
  p(name) {
    return path.join(this.home, name);
  }
  acquire(create = false) {
    ancestors(this.home);
    if (create && !exists(this.home)) {
      fs.mkdirSync(this.home, { recursive: true, mode: 0o700 });
      syncDir(path.dirname(this.home));
    }
    safe(this.home, true);
    for (const name of [
      "memory.sqlite3",
      "memory.sqlite3-wal",
      "memory.sqlite3-shm",
      "maintenance.sqlite3",
      "maintenance.sqlite3-journal",
      "maintenance.sqlite3-wal",
      "maintenance.sqlite3-shm",
      "deletions.sqlite3",
      "deletions.sqlite3-journal",
    ])
      if (exists(this.p(name))) safe(this.p(name));
    if (!create) check(exists(this.p("maintenance.sqlite3")), "CORRUPT");
    this.lock = open(this.p("maintenance.sqlite3"));
    busyBudget(this.lock);
    this.lock.exec("BEGIN EXCLUSIVE");
    point("lock-acquired");
  }
  quarantine() {
    try {
      safe(this.p("quarantine"), true);
      for (const suffix of ["", "-wal", "-shm"]) {
        const from = this.dbPath + suffix,
          to = this.p("quarantine/corrupt.sqlite3" + suffix);
        if (exists(from) && !exists(to)) {
          safe(from);
          fs.copyFileSync(from, to, fs.constants.COPYFILE_EXCL);
          fs.chmodSync(to, 0o600);
          const f = fs.openSync(to, "r");
          fs.fsyncSync(f);
          fs.closeSync(f);
        }
      }
      syncDir(this.p("quarantine"));
    } catch {
      /* Originals are retained if evidence preservation is unavailable. */
    }
  }
  release() {
    try {
      this.db?.close();
    } finally {
      try {
        this.journal?.close();
      } finally {
        if (this.lock) {
          try {
            if (this.lock.isTransaction) this.lock.exec("ROLLBACK");
          } finally {
            this.lock.close();
          }
        }
      }
    }
  }
  initialize(backups) {
    check(!exists(this.p("identity.json")), "ALREADY_INITIALIZED");
    check(
      !exists(this.dbPath) && !exists(this.p("deletions.sqlite3")),
      "CORRUPT",
    );
    const identity = {
      schema: 1,
      user_id: "usr-" + uuid(),
      store_id: uuid(),
      receipt_key: uuid() + uuid(),
      backups,
      skills: {},
      projects: {},
      sources: {},
    };
    fs.mkdirSync(this.p("backups"), { mode: 0o700 });
    fs.mkdirSync(this.p("quarantine"), { mode: 0o700 });
    this.journal = open(this.p("deletions.sqlite3"));
    this.journal.exec(
      "CREATE TABLE identity (store_id TEXT NOT NULL); CREATE TABLE intents (seq INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT NOT NULL UNIQUE,complete INTEGER NOT NULL DEFAULT 0);",
    );
    this.journal
      .prepare("INSERT INTO identity VALUES (?)")
      .run(identity.store_id);
    this.db = open(this.dbPath);
    this.db.exec(`PRAGMA journal_mode=WAL; PRAGMA secure_delete=ON;
 CREATE TABLE metadata (name TEXT PRIMARY KEY,value TEXT NOT NULL);
 INSERT INTO metadata VALUES ('schema','1');
 CREATE TABLE records (id TEXT PRIMARY KEY,dedupe TEXT UNIQUE NOT NULL,body TEXT NOT NULL);
 CREATE TABLE receipts (key TEXT PRIMARY KEY,digest TEXT NOT NULL,result TEXT NOT NULL,created INTEGER NOT NULL);

 CREATE TABLE selections (token TEXT PRIMARY KEY,record_id TEXT,version INTEGER,recipients TEXT NOT NULL,owner TEXT NOT NULL,project TEXT,expires INTEGER NOT NULL);
 `);
    this.db
      .prepare("INSERT INTO metadata VALUES (?,?)")
      .run("store_id", identity.store_id);
    this.setupFts();
    atomic(this.p("identity.json"), JSON.stringify(identity));
    this.identity = identity;
    syncDir(this.home);
  }
  setupFts() {
    try {
      this.db.exec(
        'CREATE VIRTUAL TABLE IF NOT EXISTS records_fts USING fts5(id UNINDEXED, key, content, tokenize="unicode61");',
      );
      this.fts = true;
    } catch {
      this.fts = false;
    }
  }
  load({ allowOld = false, recovery = false } = {}) {
    this.identity = json(this.p("identity.json"));
    for (const key of ["skills", "projects", "sources"]) {
      check(
        this.identity[key] &&
          typeof this.identity[key] === "object" &&
          !Array.isArray(this.identity[key]),
        "CORRUPT",
      );
      Object.setPrototypeOf(this.identity[key], null);
    }
    check(this.identity.schema === 1, "CORRUPT");
    check(exists(this.p("deletions.sqlite3")), "CORRUPT");
    this.journal = open(this.p("deletions.sqlite3"));
    integrity(this.journal);
    check(
      this.journal.prepare("SELECT store_id FROM identity").get().store_id ===
        this.identity.store_id,
      "CORRUPT",
    );
    this.resumeRestore();
    if (recovery) return;
    check(exists(this.dbPath), "STORAGE_MISSING");
    this.openActive(allowOld);
  }
  openActive(allowOld = false) {
    this.db = open(this.dbPath);
    integrity(this.db);
    const schema = Number(
      this.db.prepare("SELECT value FROM metadata WHERE name='schema'").get()
        ?.value,
    );
    check(Number.isInteger(schema), "CORRUPT");
    if (schema > SCHEMA) fail("SCHEMA_TOO_NEW");
    if (schema < SCHEMA && !allowOld) fail("MIGRATION_REQUIRED");
    check(
      this.db.prepare("SELECT value FROM metadata WHERE name='store_id'").get()
        ?.value === this.identity.store_id,
      "CORRUPT",
    );
    this.schema = schema;
    this.db.exec("PRAGMA journal_mode=WAL; PRAGMA secure_delete=ON;");
    this.fts = !!this.db
      .prepare("SELECT 1 FROM sqlite_master WHERE name='records_fts'")
      .get();
  }
  saveIdentity() {
    atomic(this.p("identity.json"), JSON.stringify(this.identity));
  }
  all() {
    return this.db
      .prepare("SELECT body FROM records")
      .all()
      .map((r) => JSON.parse(r.body));
  }
  get(id) {
    const r = this.db.prepare("SELECT body FROM records WHERE id=?").get(id);
    return r ? JSON.parse(r.body) : null;
  }
  deleted(id) {
    return !!this.journal.prepare("SELECT 1 FROM intents WHERE id=?").get(id);
  }
  put(r) {
    // Exercise SQLite's real SQLITE_FULL rollback path without filling a host disk.
    if (
      process.env.NODE_ENV === "test" &&
      process.env.LOCAL_MEMORY_TESTING === "1" &&
      process.env.LOCAL_MEMORY_FAIL_POINT === "disk-full"
    ) {
      this.db.exec(
        "PRAGMA max_page_count=1; CREATE TABLE fault_disk_full(padding BLOB); INSERT INTO fault_disk_full VALUES (zeroblob(2097152));",
      );
    }
    this.db
      .prepare(
        "INSERT INTO records VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET body=excluded.body",
      )
      .run(r.id, r.dedupe_key, JSON.stringify(r));
    if (this.fts) {
      this.db.prepare("DELETE FROM records_fts WHERE id=?").run(r.id);
      this.db
        .prepare("INSERT INTO records_fts VALUES (?,?,?)")
        .run(r.id, r.key, r.content);
    }
  }
  transaction(fn) {
    busyBudget(this.db);
    this.db.exec("BEGIN IMMEDIATE");
    try {
      const result = fn();
      point("before-commit");
      this.db.exec("COMMIT");
      point("after-commit");
      return result;
    } catch (e) {
      if (this.db.isTransaction) this.db.exec("ROLLBACK");
      throw e;
    }
  }
  pruneBackups() {
    safe(this.p("backups"), true);
    for (const name of fs
      .readdirSync(this.p("backups"))
      .filter((n) => /^snapshot-[a-f0-9-]+\.json$/.test(n))) {
      const m = json(this.p("backups/" + name));
      check(
        m.file === name.replace(/\.json$/, ".sqlite3") &&
          Number.isFinite(Date.parse(m.created_at)),
        "CORRUPT",
      );
      if (now() - Date.parse(m.created_at) > 30 * 86400000) {
        if (exists(this.p("backups/" + m.file))) {
          safe(this.p("backups/" + m.file));
          fs.rmSync(this.p("backups/" + m.file));
        }
        fs.rmSync(this.p("backups/" + name));
        syncDir(this.p("backups"));
      }
    }
  }
  async snapshot(mandatory = false) {
    if (!mandatory && !this.identity.backups) return null;
    safe(this.p("backups"), true);
    for (const name of fs.readdirSync(this.p("backups"))) {
      if (
        name.endsWith(".tmp") ||
        (name.endsWith(".sqlite3") &&
          !exists(this.p("backups/" + name.replace(/\.sqlite3$/, ".json"))))
      ) {
        safe(this.p("backups/" + name));
        fs.rmSync(this.p("backups/" + name));
      }
    }
    const manifests = fs
      .readdirSync(this.p("backups"))
      .filter((n) => n.endsWith(".json"))
      .sort();
    for (const n of manifests) {
      const m = json(this.p("backups/" + n));
      check(
        m.file === n.replace(/\.json$/, ".sqlite3") &&
          Number.isFinite(Date.parse(m.created_at)),
        "CORRUPT",
      );
      if (now() - Date.parse(m.created_at) > 30 * 86400000) {
        fs.rmSync(this.p("backups/" + m.file));
        fs.rmSync(this.p("backups/" + n));
      }
    }
    const current = fs
      .readdirSync(this.p("backups"))
      .filter((n) => n.endsWith(".json"))
      .sort(
        (a, b) =>
          json(this.p("backups/" + a)).created_at.localeCompare(
            json(this.p("backups/" + b)).created_at,
          ) || a.localeCompare(b),
      );
    if (
      !mandatory &&
      current.some(
        (n) =>
          json(this.p("backups/" + n)).created_at.slice(0, 10) ===
          iso().slice(0, 10),
      )
    )
      return null;
    const id = "snapshot-" + uuid(),
      file = id + ".sqlite3",
      tmp = this.p("backups/" + file + ".tmp");
    point("backup-start");
    try {
      await backup(this.db, tmp);
      const d = open(tmp);
      try {
        integrity(d);
      } finally {
        d.close();
      }
      check(fs.statSync(tmp).size <= LIMITS.database, "CAPACITY");
      const manifest = {
        format: 1,
        store_id: this.identity.store_id,
        schema: this.schema ?? SCHEMA,
        created_at: iso(),
        sequence: this.sequence(),
        file,
        sha256: digest(fs.readFileSync(tmp)),
      };
      const f = fs.openSync(tmp, "r");
      fs.fsyncSync(f);
      fs.closeSync(f);
      point("backup-validated");
      while (current.length >= 3) {
        const n = current.shift(),
          m = json(this.p("backups/" + n));
        fs.rmSync(this.p("backups/" + m.file));
        fs.rmSync(this.p("backups/" + n));
      }
      fs.renameSync(tmp, this.p("backups/" + file));
      atomic(this.p("backups/" + id + ".json"), JSON.stringify(manifest));
      syncDir(this.p("backups"));
      return id;
    } finally {
      fs.rmSync(tmp, { force: true });
    }
  }
  sequence() {
    return this.journal
      .prepare("SELECT coalesce(max(seq),0) n FROM intents")
      .get().n;
  }
  intent(id) {
    this.journal
      .prepare("INSERT OR IGNORE INTO intents(id) VALUES (?)")
      .run(id);
    point("journal-durable");
  }
  replay(onDelete) {
    const pending = this.journal
      .prepare("SELECT seq,id FROM intents WHERE complete=0 ORDER BY seq")
      .all();
    if (!pending.length) return;
    this.transaction(() => {
      for (const { seq, id } of pending) {
        this.db.prepare("DELETE FROM records WHERE id=?").run(id);
        if (this.fts)
          this.db.prepare("DELETE FROM records_fts WHERE id=?").run(id);
        this.db.prepare("DELETE FROM selections WHERE record_id=?").run(id);
      }
      onDelete?.();
    });
    point("active-purged");
    try {
      point("purge-copies");
      for (const dir of ["backups", "quarantine"]) {
        safe(this.p(dir), true);
        for (const name of fs.readdirSync(this.p(dir))) {
          safe(this.p(dir + "/" + name));
          fs.rmSync(this.p(dir + "/" + name));
        }
        syncDir(this.p(dir));
      }
      point("copies-purged");
      this.journal.exec("BEGIN IMMEDIATE");
      for (const { seq } of pending)
        this.journal
          .prepare("UPDATE intents SET complete=1 WHERE seq=?")
          .run(seq);
      this.journal.exec("COMMIT");
      point("journal-complete");
    } catch {
      fail("PURGE_PENDING", { active_deleted: true });
    }
  }
  cleanup() {
    try {
      busyBudget(this.db);
      const r = this.db.prepare("PRAGMA wal_checkpoint(TRUNCATE)").get();
      if (r.busy) return "pending";
      busyBudget(this.db);
      this.db.exec("VACUUM");
      this.db.prepare("PRAGMA wal_checkpoint(TRUNCATE)").get();
      return "complete";
    } catch {
      return "pending";
    }
  }
  pressure() {
    let size = 0;
    try {
      size = fs.statSync(this.dbPath + "-wal").size;
    } catch {}
    if (size > LIMITS.walSoft) {
      this.db.prepare("PRAGMA wal_checkpoint(PASSIVE)").get();
      try {
        size = fs.statSync(this.dbPath + "-wal").size;
      } catch {
        size = 0;
      }
    }
    return { wal_bytes: size, maintenance_pressure: size > LIMITS.walSoft };
  }
  admission() {
    const p = this.pressure();
    check(p.wal_bytes < LIMITS.walHard, "CAPACITY");
    const pages =
      this.db.prepare("PRAGMA page_count").get().page_count *
      this.db.prepare("PRAGMA page_size").get().page_size;
    check(pages < LIMITS.database, "CAPACITY");
    check(
      this.db.prepare("SELECT count(*) n FROM records").get().n < LIMITS.live,
      "CAPACITY",
    );
  }
  async restore(name) {
    check(/^snapshot-[a-f0-9-]+$/.test(name));
    const m = json(this.p("backups/" + name + ".json"));
    check(
      m.format === 1 &&
        m.store_id === this.identity.store_id &&
        m.schema === SCHEMA &&
        m.sequence <= this.sequence() &&
        m.file === name + ".sqlite3",
      "CORRUPT",
    );
    const source = this.p("backups/" + m.file);
    safe(source);
    check(digest(fs.readFileSync(source)) === m.sha256, "CORRUPT");
    const candidate = this.p("restore.sqlite3");
    if (exists(candidate)) {
      safe(candidate);
      fs.rmSync(candidate);
    }
    const original = open(source);
    try {
      integrity(original);
      await backup(original, candidate);
    } finally {
      original.close();
    }
    point("restore-copied");
    const d = open(candidate);
    try {
      integrity(d);
      check(
        Number(
          d.prepare("SELECT value FROM metadata WHERE name='schema'").get()
            ?.value,
        ) === SCHEMA,
        "CORRUPT",
      );
      check(
        d.prepare("SELECT value FROM metadata WHERE name='store_id'").get()
          ?.value === this.identity.store_id,
        "CORRUPT",
      );
      d.exec("BEGIN IMMEDIATE");
      for (const { seq, id } of this.journal
        .prepare("SELECT seq,id FROM intents")
        .all()) {
        d.prepare("DELETE FROM records WHERE id=?").run(id);
        if (
          d
            .prepare("SELECT 1 FROM sqlite_master WHERE name='records_fts'")
            .get()
        )
          d.prepare("DELETE FROM records_fts WHERE id=?").run(id);
      }
      for (const row of d.prepare("SELECT id,body FROM records").all()) {
        const r = JSON.parse(row.body);
        if (r.share_with.length) {
          r.share_with = [];
          r.version++;
          r.updated_at = iso();
          d.prepare("UPDATE records SET body=? WHERE id=?").run(
            JSON.stringify(r),
            r.id,
          );
        }
      }
      d.exec(
        "DELETE FROM selections; DELETE FROM receipts; COMMIT; PRAGMA journal_mode=DELETE;",
      );
      integrity(d);
    } finally {
      d.close();
    }
    point("restore-reset");
    safe(this.p("quarantine"), true);
    for (const name of fs.readdirSync(this.p("quarantine"))) {
      safe(this.p("quarantine/" + name));
      fs.rmSync(this.p("quarantine/" + name));
    }
    syncDir(this.p("quarantine"));
    this.db?.close();
    this.db = null;
    const state = {
      candidate_hash: digest(fs.readFileSync(candidate)),
      prefix: "restore-" + uuid(),
    };
    atomic(this.p("restore-state.json"), JSON.stringify(state));
    this.resumeRestore();
    this.openActive();
    this.replay();
    return { restored: true, sharing_reset: true };
  }
  resumeRestore() {
    const statePath = this.p("restore-state.json");
    if (!exists(statePath)) return;
    const state = json(statePath),
      candidate = this.p("restore.sqlite3");
    check(
      /^[a-f0-9]{64}$/.test(state.candidate_hash) &&
        /^restore-[a-f0-9-]+$/.test(state.prefix),
      "CORRUPT",
    );
    if (exists(candidate)) {
      safe(candidate);
      check(
        digest(fs.readFileSync(candidate)) === state.candidate_hash,
        "CORRUPT",
      );
      for (const suffix of ["", "-wal", "-shm"]) {
        const old = this.dbPath + suffix;
        if (exists(old)) {
          safe(old);
          fs.renameSync(old, this.p("quarantine/" + state.prefix + suffix));
        }
      }
      syncDir(this.p("quarantine"));
      syncDir(this.home);
      point("restore-quarantined");
      fs.renameSync(candidate, this.dbPath);
      syncDir(this.home);
      point("restore-published");
    } else {
      safe(this.dbPath);
      check(
        digest(fs.readFileSync(this.dbPath)) === state.candidate_hash,
        "CORRUPT",
      );
    }
    fs.rmSync(statePath);
    syncDir(this.home);
  }
}
