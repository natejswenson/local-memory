import crypto from "node:crypto";
import { check, fail, now, stable } from "./validation.mjs";

export const RECEIPT_WINDOW = 30 * 86400000;
export const ORDINARY_RECEIPTS = 100000;
export const TOTAL_RECEIPTS = 110000;

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
  return crypto.createHmac("sha256", s.identity.receipt_key)
    .update(stable(payload)).digest("hex");
}
function publicResult(row) {
  const { _owner_retry, ...result } = JSON.parse(row.result);
  return result;
}

// The bounded, content-free receipt table is scanned under the maintenance lock.
// No implicit schema/index migration or permanent owner tombstone is needed.
function deletionIndex(s) {
  const index = new Map();
  for (const row of s.db.prepare(
    "SELECT key,result,created FROM receipts WHERE created>=? AND json_extract(result,'$.deleted')=1",
  ).all(now() - RECEIPT_WINDOW)) {
    const id = JSON.parse(row.result).id;
    if (!index.has(id)) index.set(id, []);
    index.get(id).push(row);
  }
  return index;
}
export function deletionReceipt(s, id, c) {
  // Reuse only inside the current transaction; Store.transaction clears this
  // transient index on commit and rollback. It never changes the disk schema.
  const index = s.db.isTransaction
    ? (s.deletionReceiptCache ??= deletionIndex(s))
    : deletionIndex(s);
  return index.get(id)?.find((row) => {
    if (row.created < now() - RECEIPT_WINDOW) return false;
    if (!c) return true; // One outstanding reservation per live ID, in any scope.
    const scope = JSON.parse(row.key);
    const result = JSON.parse(row.result);
    // Old management receipts and a skill literally named "management" shared
    // a key namespace. Ambiguous legacy evidence cannot authorize owner retries.
    const owner = result._owner_retry === true ||
      (result._owner_retry === undefined && scope[0] !== "management");
    return owner && scope[0] === c.skill_id && scope[1] === c.project_id;
  });
}
export function replay(q, s, c, canAccess) {
  const row = s.db.prepare("SELECT * FROM receipts WHERE key=?")
    .get(receiptKey(q, c));
  if (!row || now() - row.created > RECEIPT_WINDOW) return null;
  check(row.digest === payloadHash(q, s), "IDEMPOTENCY_CONFLICT");
  const r = publicResult(row);
  if (r.id && s.deleted(r.id)) {
    if (q.op === "forget")
      return { ...r, managed_backups: "purged", physical_cleanup: "pending" };
    fail("GONE");
  }
  if (q.op === "forget") return null;
  if (r.id) check(canAccess(s.get(r.id)), "NOT_FOUND");
  return r;
}
export function saveReceipt(q, s, c, result) {
  s.db.prepare("DELETE FROM receipts WHERE created<?")
    .run(now() - RECEIPT_WINDOW);
  // Reuse the first reservation even when a pre-intent retry changes key/scope.
  // Its original digest, scope and deadline must never be overwritten/renewed.
  if (q.op === "forget" && deletionReceipt(s, result.id)) return;
  const count = s.db.prepare("SELECT count(*) n FROM receipts").get().n;
  check(count < (q.op === "forget" ? TOTAL_RECEIPTS : ORDINARY_RECEIPTS), "CAPACITY");
  const stored = q.op === "forget"
    ? { ...result, _owner_retry: !c.management }
    : result;
  const row = { key: receiptKey(q, c), result: JSON.stringify(stored), created: now() };
  s.db.prepare("INSERT INTO receipts VALUES (?,?,?,?)")
    .run(row.key, payloadHash(q, s), row.result, row.created);
  if (q.op === "forget" && s.deletionReceiptCache)
    s.deletionReceiptCache.set(result.id, [row]);
}
