import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import {
  Store,
  location,
  safe,
  json,
  atomic,
  SCHEMA,
  integrity,
  exists,
} from "./storage.mjs";
import {
  LIMITS,
  check,
  fail,
  fields,
  text,
  provenance,
  identifier,
  keyValid,
  iso,
  now,
  uuid,
  stable,
  bytes,
  tokens,
  digest,
  point,
} from "./validation.mjs";
const MUTATIONS = new Set(["remember", "update", "forget"]);
const COMMON = ["protocol", "op", "request_id", "caller", "idempotency_key"];
const OPTIONS = {
  init: ["backups"],
  status: [],
  register: ["skill_id", "keys", "capture"],
  project: ["project_id", "roots"],
  source: ["source_id", "owner_skill", "path"],
  selection: [
    "id",
    "expected_version",
    "recipients",
    "owner_skill",
    "project_id",
  ],
  remember: ["record", "selection_token"],
  update: ["id", "expected_version", "changes", "selection_token"],
  forget: ["id", "expected_version"],
  recall: [
    "keys",
    "query",
    "types",
    "limit",
    "max_context_bytes",
    "retrieval_mode",
  ],
  list: ["offset", "limit", "project_id", "owner_skill"],
  show: ["id"],
  export: ["project_id", "owner_skill", "offset", "limit", "format"],
  backup: [],
  restore: ["snapshot"],
  migrate: [],
  maintain: [],
};
const managementOnly = new Set([
  "init",
  "register",
  "project",
  "source",
  "selection",
  "backup",
  "restore",
  "migrate",
  "maintain",
  "export",
  "list",
]);
function validateRequest(q, management) {
  check(q && Object.hasOwn(OPTIONS, q.op));
  fields(q, [...COMMON, ...OPTIONS[q.op]], ["protocol", "op", "request_id"]);
  check(q.protocol === 1 && identifier(q.request_id));
  if (managementOnly.has(q.op)) check(management, "PERMISSION_DENIED");
  if (MUTATIONS.has(q.op)) check(identifier(q.idempotency_key));
  if (["update", "forget"].includes(q.op))
    check(
      typeof q.id === "string" &&
        /^[a-f0-9-]{36}$/i.test(q.id) &&
        Number.isSafeInteger(q.expected_version) &&
        q.expected_version > 0,
    );
  if (q.caller) {
    fields(
      q.caller,
      ["skill_id", "project_id", "user_id", "token"],
      ["skill_id", "project_id"],
    );
    check(identifier(q.caller.skill_id));
    check(q.caller.project_id === null || identifier(q.caller.project_id));
  }
}
function caller(q, s, management) {
  if (management)
    return {
      management: true,
      skill_id: q.caller?.skill_id ?? null,
      project_id: q.caller?.project_id ?? null,
    };
  check(q.caller, "PERMISSION_DENIED");
  const c = q.caller,
    registered = s.identity.skills[c.skill_id];
  check(
    registered &&
      c.token === registered.token &&
      c.user_id === s.identity.user_id,
    "PERMISSION_DENIED",
  );
  check(
    c.project_id === null || Object.hasOwn(s.identity.projects, c.project_id),
    "PERMISSION_DENIED",
  );
  return c;
}
function access(r, c, s, owner = false) {
  return (
    r &&
    !s.deleted(r.id) &&
    (c.management ||
      (r.user_id === s.identity.user_id &&
        (r.project_id === null || r.project_id === c.project_id) &&
        (r.owner_skill === c.skill_id ||
          (!owner && r.share_with.includes(c.skill_id)))))
  );
}
function owned(id, c, s) {
  check(typeof id === "string");
  const r = s.get(id);
  check(access(r, c, s, true), "NOT_FOUND");
  return r;
}
function sourceFresh(r, s) {
  if (!r.mirror) return true;
  const reg = s.identity.sources[r.mirror.source_id];
  if (!reg || reg.owner_skill !== r.owner_skill) return false;
  s.sourceRevisions ??= new Map();
  if (!s.sourceRevisions.has(r.mirror.source_id)) {
    let revision = null;
    try {
      const st = fs.lstatSync(reg.path);
      if (
        !st.isSymbolicLink() &&
        st.isFile() &&
        st.uid === process.getuid() &&
        st.size <= 1024 * 1024 &&
        fs.realpathSync(reg.path) === reg.path
      )
        revision = digest(fs.readFileSync(reg.path));
    } catch {}
    s.sourceRevisions.set(r.mirror.source_id, revision);
  }
  return s.sourceRevisions.get(r.mirror.source_id) === r.mirror.revision;
}
function active(r, s) {
  return (
    r.status === "active" &&
    (!r.review_after || Date.parse(r.review_after) > now()) &&
    (!r.expires_at || Date.parse(r.expires_at) > now()) &&
    sourceFresh(r, s)
  );
}
function record(input, c, s, old) {
  fields(
    input,
    [
      "type",
      "key",
      "content",
      "provenance",
      "share_with",
      "review_after",
      "expires_at",
      "status",
      "mirror",
    ],
    old ? [] : ["type", "key", "content", "provenance"],
  );
  const data = { ...old, ...input };
  check(["preference", "fact", "project_context"].includes(data.type));
  check(keyValid(data.key));
  const owner = old?.owner_skill || c.skill_id;
  check(
    owner && s.identity.skills[owner]?.keys.includes(data.key),
    "PERMISSION_DENIED",
  );
  data.content = text(data.content);
  data.provenance = provenance(data.provenance);
  if (old && old.provenance.kind !== "inferred")
    check(data.provenance.kind !== "inferred", "PERMISSION_DENIED");
  if (data.type !== "preference")
    check(
      ["confirmed_fact", "explicit_correction", "inferred"].includes(
        data.provenance.kind,
      ),
    );
  data.share_with = [...new Set(data.share_with || [])].sort();
  check(Array.isArray(input.share_with ?? []) && data.share_with.length <= 16);
  check(
    data.share_with.every(
      (x) => identifier(x) && s.identity.skills[x] && x !== owner,
    ),
  );
  data.status =
    data.status ||
    (data.provenance.kind === "inferred" ? "suggested" : "active");
  check(["active", "suggested", "conflicted"].includes(data.status));
  const days = (n) => new Date(now() + n * 86400000).toISOString();
  if (!old) {
    data.review_after ??= days(data.type === "preference" ? 180 : 30);
    data.expires_at ??= data.type === "preference" ? null : days(90);
  }
  if (data.provenance.kind === "inferred") {
    check(data.status === "suggested" && data.share_with.length === 0);
    data.expires_at = old?.expires_at || days(7);
    data.review_after = data.expires_at;
  }
  for (const f of ["review_after", "expires_at"]) {
    check(
      data[f] === null ||
        (typeof data[f] === "string" && Number.isFinite(Date.parse(data[f]))),
    );
    if (data[f]) data[f] = new Date(data[f]).toISOString();
  }
  check(data.review_after !== null);
  if (data.type !== "preference")
    check(
      data.expires_at !== null &&
        Date.parse(data.expires_at) <= now() + 90 * 86400000,
    );
  check(
    Date.parse(data.review_after) <=
      now() + (data.type === "preference" ? 180 : 30) * 86400000 ||
      data.provenance.kind === "inferred",
  );
  if (old) {
    for (const f of ["type", "key"])
      check(!Object.hasOwn(input, f) || input[f] === old[f]);
    if (old.provenance.kind !== "inferred")
      check(data.provenance.kind !== "inferred", "PERMISSION_DENIED");
    if (data.content !== old.content)
      check(
        data.provenance.kind === "explicit_correction",
        "PERMISSION_DENIED",
      );
  }
  if (data.mirror) {
    fields(
      data.mirror,
      ["source_id", "revision", "event"],
      ["source_id", "revision", "event"],
    );
    check(
      identifier(data.mirror.source_id) &&
        identifier(data.mirror.event) &&
        /^[a-f0-9]{64}$/.test(data.mirror.revision),
    );
    check(sourceFresh({ ...data, owner_skill: owner }, s), "SOURCE_STALE");
  }
  const meta = { ...data };
  delete meta.content;
  for (const x of [
    "id",
    "user_id",
    "owner_skill",
    "project_id",
    "created_at",
    "updated_at",
    "version",
    "dedupe_key",
  ])
    delete meta[x];
  check(bytes(meta) <= LIMITS.metadata);
  return data;
}
function consent(q, s, c, r, recipients) {
  if (!recipients.length) return;
  const sel = s.db
    .prepare("SELECT * FROM selections WHERE token=?")
    .get(q.selection_token ?? "");
  check(
    sel &&
      sel.expires > now() &&
      sel.owner === r.owner_skill &&
      sel.project === r.project_id &&
      sel.record_id ===
        (r.version === 1 && q.op === "remember" ? null : r.id) &&
      sel.version === (q.op === "remember" ? null : q.expected_version) &&
      sel.recipients === JSON.stringify(recipients),
    "PERMISSION_DENIED",
  );
}
function receiptKey(q, c) {
  return stable([
    c.management ? "management" : c.skill_id,
    c.project_id,
    q.idempotency_key,
  ]);
}
function payloadHash(q, s) {
  const payload = { ...q };
  delete payload.request_id;
  return crypto
    .createHmac("sha256", s.identity.receipt_key)
    .update(stable(payload))
    .digest("hex");
}
function replay(q, s, c) {
  const row = s.db
    .prepare("SELECT * FROM receipts WHERE key=?")
    .get(receiptKey(q, c));
  if (!row || now() - row.created > 30 * 86400000) return null;
  check(row.digest === payloadHash(q, s), "IDEMPOTENCY_CONFLICT");
  const r = JSON.parse(row.result);
  if (r.id && s.deleted(r.id)) {
    if (q.op === "forget")
      return { ...r, managed_backups: "purged", physical_cleanup: "pending" };
    fail("GONE");
  }
  if (r.id) check(access(s.get(r.id), c, s, true), "NOT_FOUND");
  return r;
}
function saveReceipt(q, s, c, result) {
  s.db
    .prepare("DELETE FROM receipts WHERE created<?")
    .run(now() - 30 * 86400000);
  check(
    s.db.prepare("SELECT count(*) n FROM receipts").get().n < 100000,
    "CAPACITY",
  );
  s.db
    .prepare("INSERT OR REPLACE INTO receipts VALUES (?,?,?,?)")
    .run(receiptKey(q, c), payloadHash(q, s), JSON.stringify(result), now());
}
function inspection(r, s) {
  return {
    ...r,
    stale: !!r.review_after && Date.parse(r.review_after) <= now(),
    expired: !!r.expires_at && Date.parse(r.expires_at) <= now(),
    source_fresh: sourceFresh(r, s),
  };
}
function recallOptions(q) {
  check(
    (Array.isArray(q.keys) && q.keys.length > 0 && !q.query) ||
      (typeof q.query === "string" && !q.keys),
  );
  if (q.keys) check(q.keys.length <= 64 && q.keys.every(keyValid));
  if (q.types)
    check(
      Array.isArray(q.types) &&
        q.types.length > 0 &&
        q.types.every((t) =>
          ["preference", "fact", "project_context"].includes(t),
        ),
    );
  const budget = q.max_context_bytes ?? 4096;
  check(
    Number.isInteger(budget) && budget >= 64 && budget <= 8192,
    "INVALID_REQUEST",
  );
  const limit = q.limit ?? 5;
  check(Number.isInteger(limit) && limit >= 1 && limit <= 10);
  check(
    q.retrieval_mode === undefined ||
      ["scan", "fts5"].includes(q.retrieval_mode),
  );
  let ts = [];
  if (q.query) {
    check(q.query.length <= 256);
    ts = tokens(q.query);
    check(ts.length > 0 && ts.length <= 16);
  }
  return { budget, limit, ts };
}
function recall(q, s, c) {
  const { budget, limit, ts } = recallOptions(q);
  const mode = s.fts && q.retrieval_mode !== "scan" ? "fts5" : "scan";
  const eligible = s
    .all()
    .filter(
      (r) =>
        access(r, c, s) &&
        active(r, s) &&
        (!q.types || q.types.includes(r.type)),
    );
  const groups = new Map();
  for (const r of eligible) {
    const k = r.type + "\0" + r.key;
    if (!groups.has(k)) groups.set(k, []);
    groups.get(k).push(r);
  }
  // FTS is candidate selection only. Scope and group expansion happen before resolution.
  let ftsIds = null;
  if (q.query && mode === "fts5") {
    const expression = ts
      .map((t) => '"' + t.replaceAll('"', '""') + '"')
      .join(" AND ");
    ftsIds = new Set(
      s.db
        .prepare("SELECT id FROM records_fts WHERE records_fts MATCH ?")
        .all(expression)
        .map((x) => x.id),
    );
  }
  let resolved = [],
    conflicts = [];
  for (const rs of groups.values()) {
    const matches = rs.filter((r) =>
      q.keys
        ? q.keys.includes(r.key)
        : r.key === q.query ||
          (ftsIds
            ? ftsIds.has(r.id)
            : ts.every((t) => tokens(r.key + " " + r.content).includes(t))),
    );
    if (!matches.length) continue;
    const score = Math.max(
      ...matches.map((r) =>
        q.keys?.includes(r.key) || r.key === q.query ? 1000 : ts.length,
      ),
    );
    const precedence = (r) =>
      (r.provenance.kind === "explicit_correction" ? 4 : 2) +
      (r.project_id === c.project_id && r.project_id !== null ? 1 : 0);
    const best = Math.max(...rs.map(precedence));
    const finalists = rs
      .filter((r) => precedence(r) === best)
      .sort(
        (a, b) =>
          b.updated_at.localeCompare(a.updated_at) || a.id.localeCompare(b.id),
      );
    if (new Set(finalists.map((r) => r.content)).size > 1) {
      conflicts.push(rs[0].key);
      continue;
    }
    const r = finalists[0];
    resolved.push({
      score,
      r,
      entry: {
        id: r.id,
        key: r.key,
        type: r.type,
        content: r.content,
        project_id: r.project_id,
        owner_skill: r.owner_skill,
        version: r.version,
        provenance: r.provenance,
        review_after: r.review_after,
        expires_at: r.expires_at,
        source_ids: finalists.slice(0, 16).map((x) => x.id),
      },
    });
  }
  resolved.sort(
    (a, b) =>
      b.score - a.score ||
      b.r.updated_at.localeCompare(a.r.updated_at) ||
      a.r.id.localeCompare(b.r.id),
  );
  conflicts = [...new Set(conflicts)].sort();
  const total = resolved.length + conflicts.length;
  const context = {
    records: resolved.slice(0, limit).map((x) => x.entry),
    conflict_keys: conflicts,
  };
  while (bytes(context) > budget && context.records.length)
    context.records.pop();
  while (bytes(context) > budget && context.conflict_keys.length)
    context.conflict_keys.pop();
  const omitted = total - context.records.length - context.conflict_keys.length;
  return {
    storage: "ready",
    retrieval_mode: mode,
    context,
    truncated: omitted > 0,
    omitted_count: omitted,
    ...s.pressure(),
  };
}
function page(q, s, c) {
  const limit = q.limit ?? 50,
    offset = q.offset ?? 0;
  check(
    Number.isInteger(limit) &&
      limit >= 1 &&
      limit <= 50 &&
      Number.isInteger(offset) &&
      offset >= 0,
  );
  if (q.project_id !== undefined)
    check(q.project_id === null || s.identity.projects[q.project_id]);
  if (q.owner_skill !== undefined) check(s.identity.skills[q.owner_skill]);
  const rs = s
    .all()
    .filter(
      (r) =>
        access(r, c, s) &&
        (q.project_id === undefined || r.project_id === q.project_id) &&
        (q.owner_skill === undefined || r.owner_skill === q.owner_skill),
    )
    .sort((a, b) => a.id.localeCompare(b.id));
  const records = [];
  for (const r of rs.slice(offset, offset + limit)) {
    const x = inspection(r, s);
    if (bytes([...records, x]) > LIMITS.page - 1024) break;
    records.push(x);
  }
  return {
    records,
    next_offset:
      offset + records.length < rs.length ? offset + records.length : null,
  };
}
export async function execute(q, { management = false } = {}) {
  validateRequest(q, management);
  if (q.op === "recall") recallOptions(q);
  const home = location(),
    s = new Store(home);
  const identity = path.join(home, "identity.json");
  if (!exists(identity) && q.op !== "init") {
    if (exists(home)) {
      safe(home, true);
      check(!exists(s.dbPath), "CORRUPT");
    }
    if (q.op === "recall")
      return {
        storage: "absent",
        context: { records: [], conflict_keys: [] },
        truncated: false,
        omitted_count: 0,
      };
    if (q.op === "status") return { storage: "absent", location: home };
    fail("NOT_INITIALIZED");
  }
  try {
    s.acquire(q.op === "init");
    if (q.op === "init") {
      check(typeof (q.backups ?? false) === "boolean");
      s.initialize(q.backups ?? false);
      return { initialized: true, user_id: s.identity.user_id, location: home };
    }
    s.load({ allowOld: q.op === "migrate", recovery: q.op === "restore" });
    if (q.op === "restore") return await s.restore(q.snapshot);
    s.replay();
    const c = caller(q, s, management);
    s.pruneBackups();
    if (q.op === "status")
      return {
        storage: "ready",
        location: home,
        user_id: s.identity.user_id,
        schema: s.schema,
        protocol: 1,
        live_records: c.management ? s.all().length : undefined,
        pending_purge: false,
        physical_cleanup: "pending",
        ...s.pressure(),
      };
    if (q.op === "register") {
      check(
        identifier(q.skill_id) &&
          Array.isArray(q.keys) &&
          q.keys.length <= 64 &&
          q.keys.every(keyValid) &&
          typeof q.capture === "boolean",
      );
      const prior = s.identity.skills[q.skill_id];
      check(prior || Object.keys(s.identity.skills).length < 32, "CAPACITY");
      s.identity.skills[q.skill_id] = {
        keys: [...new Set(q.keys)],
        capture: q.capture,
        token: prior?.token || uuid(),
      };
      s.saveIdentity();
      return { registered: true, skill_id: q.skill_id };
    }
    if (q.op === "project") {
      check(
        identifier(q.project_id) &&
          Array.isArray(q.roots) &&
          q.roots.length > 0 &&
          q.roots.length <= 16,
      );
      check(
        s.identity.projects[q.project_id] ||
          Object.keys(s.identity.projects).length < 256,
        "CAPACITY",
      );
      const roots = q.roots.map((p) => {
        check(typeof p === "string" && path.isAbsolute(p));
        check(fs.realpathSync(p) === path.resolve(p));
        check(fs.statSync(p).isDirectory());
        return path.resolve(p);
      });
      s.identity.projects[q.project_id] = { roots };
      s.saveIdentity();
      return { registered: true, project_id: q.project_id };
    }
    if (q.op === "source") {
      check(identifier(q.source_id) && s.identity.skills[q.owner_skill]);
      check(typeof q.path === "string" && path.isAbsolute(q.path));
      check(fs.realpathSync(q.path) === path.resolve(q.path));
      check(fs.statSync(q.path).isFile());
      check(
        s.identity.sources[q.source_id] ||
          Object.keys(s.identity.sources).length < 64,
        "CAPACITY",
      );
      s.identity.sources[q.source_id] = {
        owner_skill: q.owner_skill,
        path: path.resolve(q.path),
      };
      s.saveIdentity();
      return { registered: true, source_id: q.source_id };
    }
    if (q.op === "selection") {
      check(
        Array.isArray(q.recipients) &&
          q.recipients.length <= 16 &&
          q.recipients.every((x) => s.identity.skills[x]),
      );
      const r = q.id ? owned(q.id, c, s) : null;
      if (r)
        check(q.expected_version === r.version, "VERSION_CONFLICT", {
          current_version: r.version,
        });
      const owner = r?.owner_skill || q.owner_skill,
        project = r ? r.project_id : (q.project_id ?? null);
      check(s.identity.skills[owner]);
      check(project === null || s.identity.projects[project]);
      const token = uuid();
      s.db.prepare("DELETE FROM selections WHERE expires<=?").run(now());
      check(
        s.db.prepare("SELECT count(*) n FROM selections").get().n < 10000,
        "CAPACITY",
      );
      s.db
        .prepare("INSERT INTO selections VALUES (?,?,?,?,?,?,?)")
        .run(
          token,
          r?.id ?? null,
          r?.version ?? null,
          JSON.stringify([...new Set(q.recipients)].sort()),
          owner,
          project,
          now() + 5 * 60000,
        );
      return { selection_token: token, expires_in_seconds: 300 };
    }
    if (q.op === "recall") return recall(q, s, c);
    if (q.op === "show") {
      const r = s.get(q.id);
      check(access(r, c, s), "NOT_FOUND");
      return { record: inspection(r, s) };
    }
    if (q.op === "list") return page(q, s, c);
    if (q.op === "export") {
      check(q.project_id !== undefined || q.owner_skill !== undefined);
      check(q.format === undefined || ["json", "markdown"].includes(q.format));
      const p = page(q, s, c);
      const build = () => ({
        format: q.format ?? "json",
        ...p,
        deletion_sequence: s.sequence(),
        warning:
          "User exports are outside managed deletion and cannot be imported as backups.",
        ...(q.format === "markdown"
          ? {
              markdown: p.records
                .map((r) => "## " + r.key + "\n\n" + r.content + "\n")
                .join("\n"),
            }
          : {}),
      });
      let result = build();
      while (bytes(result) > LIMITS.page - 512 && p.records.length) {
        p.records.pop();
        p.next_offset = (q.offset ?? 0) + p.records.length;
        result = build();
      }
      return result;
    }
    if (q.op === "backup") return { snapshot: await s.snapshot(true) };
    if (q.op === "migrate") {
      if (s.schema === SCHEMA) return { schema: SCHEMA, migrated: false };
      check(s.schema === 0, "MIGRATION_REQUIRED");
      await s.snapshot(true);
      s.transaction(() => {
        point("migration");
        s.db
          .prepare("UPDATE metadata SET value=? WHERE name='schema'")
          .run(String(SCHEMA));
        integrity(s.db);
      });
      return { schema: SCHEMA, migrated: true };
    }
    if (q.op === "maintain") {
      for (const r of s.all())
        if (r.expires_at && Date.parse(r.expires_at) <= now()) s.intent(r.id);
      s.replay();
      return { physical_cleanup: s.cleanup(), deletion_sequence: s.sequence() };
    }
    if (MUTATIONS.has(q.op)) {
      const prior = replay(q, s, c);
      if (prior) return prior;
      if (q.op === "forget") {
        const r = s.get(q.id);
        if (s.deleted(q.id))
          return {
            id: q.id,
            deleted: true,
            managed_backups: "purged",
            physical_cleanup: "pending",
          };
        check(access(r, c, s, true), "NOT_FOUND");
        check(q.expected_version === r.version, "VERSION_CONFLICT", {
          current_version: r.version,
        });
        const result = {
          id: r.id,
          deleted: true,
          managed_backups: "purged",
          physical_cleanup: "pending",
        };
        s.intent(r.id);
        s.replay(() => saveReceipt(q, s, c, result));
        return { ...result, physical_cleanup: s.cleanup() };
      }
      check(
        c.management || s.identity.skills[c.skill_id].capture,
        "CAPTURE_DISABLED",
      );
      const old = q.op === "update" ? owned(q.id, c, s) : null;
      if (old) {
        check(q.expected_version === old.version, "VERSION_CONFLICT", {
          current_version: old.version,
        });
        if (old.mirror)
          check(
            !c.management &&
              q.changes?.mirror &&
              q.changes.mirror.source_id === old.mirror.source_id,
            "SOURCE_REQUIRED",
          );
      }
      const data = record(old ? q.changes : q.record, c, s, old);
      const r = old
        ? { ...data, version: old.version + 1, updated_at: iso() }
        : {
            ...data,
            id: uuid(),
            user_id: s.identity.user_id,
            project_id: c.project_id,
            owner_skill: c.skill_id,
            version: 1,
            created_at: iso(),
            updated_at: iso(),
            dedupe_key: stable([
              s.identity.user_id,
              c.project_id,
              c.skill_id,
              data.type,
              data.key,
            ]),
          };
      check(bytes({ ...r, content: undefined }) <= LIMITS.metadata);
      if (!old || stable(r.share_with) !== stable(old.share_with))
        consent(q, s, c, r, r.share_with);
      if (!old) {
        const dupe = s.db
          .prepare("SELECT body FROM records WHERE dedupe=?")
          .get(r.dedupe_key);
        if (dupe) {
          const existing = JSON.parse(dupe.body);
          const omit = (x) => {
            const y = { ...x };
            for (const f of [
              "id",
              "version",
              "created_at",
              "updated_at",
              "review_after",
              "expires_at",
            ])
              delete y[f];
            return y;
          };
          check(
            stable(omit(existing)) === stable(omit(r)) &&
              (!Object.hasOwn(q.record, "review_after") ||
                r.review_after === existing.review_after) &&
              (!Object.hasOwn(q.record, "expires_at") ||
                r.expires_at === existing.expires_at),
            "DUPLICATE_CONFLICT",
          );
          const result = {
            id: existing.id,
            version: existing.version,
            deduplicated: true,
          };
          s.transaction(() => saveReceipt(q, s, c, result));
          return result;
        }
        s.admission();
      } else {
        check(s.pressure().wal_bytes < LIMITS.walHard, "CAPACITY");
      }
      await s.snapshot();
      return s.transaction(() => {
        s.put(r);
        const result = { id: r.id, version: r.version, deduplicated: false };
        saveReceipt(q, s, c, result);
        check(
          s.db.prepare("PRAGMA page_count").get().page_count *
            s.db.prepare("PRAGMA page_size").get().page_size <=
            LIMITS.database,
          "CAPACITY",
        );
        if (q.selection_token)
          s.db
            .prepare("DELETE FROM selections WHERE token=?")
            .run(q.selection_token);
        return result;
      });
    }
    fail("INVALID_INPUT");
  } catch (e) {
    if (
      e.code === "CORRUPT" ||
      /malformed|not a database|disk image/i.test(e.message)
    )
      s.quarantine();
    throw e;
  } finally {
    s.release();
  }
}
