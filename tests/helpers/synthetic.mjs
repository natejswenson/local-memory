import { DatabaseSync } from "node:sqlite";
import path from "node:path";
import fs from "node:fs";
import crypto from "node:crypto";
// Synthetic capacity fixtures only. This is not an import interface.
export function seed(home, count, { conflicts = false, mixed = false } = {}) {
  const db = new DatabaseSync(path.join(home, "memory.sqlite3"));
  const cfg = JSON.parse(fs.readFileSync(path.join(home, "identity.json")));
  const base = {
    type: "preference",
    user_id: cfg.user_id,
    project_id: "prj-harbor",
    owner_skill: "ghostwriter",
    share_with: [],
    provenance: {
      kind: "explicit_user",
      skill_version: "1.0.0",
      source_ref: "synthetic-fixture",
      observed_at: "2026-09-15T00:00:00Z",
    },
    created_at: "2026-09-15T00:00:00Z",
    updated_at: "2026-09-15T00:00:00Z",
    review_after: "2027-01-01T00:00:00Z",
    expires_at: null,
    version: 1,
    status: "active",
  };
  db.exec("BEGIN");
  for (let i = 0; i < count; i++) {
    const key = "bench.item_" + String(i).padStart(5, "0");
    for (let j = 0; j < (conflicts ? 2 : 1); j++) {
      const r = {
        ...base,
        id: crypto.randomUUID(),
        key,
        content: (j ? "Different " : "Value ") + "synthetic marker " + i,
        owner_skill: j ? "writing-peer" : "ghostwriter",
        share_with: j ? ["ghostwriter"] : [],
        dedupe_key: JSON.stringify([
          cfg.user_id,
          "prj-harbor",
          j ? "writing-peer" : "ghostwriter",
          "preference",
          key,
        ]),
      };
      if (mixed && i % 2 === 0 && j)
        r.provenance = { ...r.provenance, kind: "explicit_correction" };
      db.prepare("INSERT INTO records VALUES (?,?,?)").run(
        r.id,
        r.dedupe_key,
        JSON.stringify(r),
      );
      db.prepare("INSERT INTO records_fts VALUES (?,?,?)").run(
        r.id,
        r.key,
        r.content,
      );
    }
  }
  db.exec("COMMIT");
  db.close();
}
