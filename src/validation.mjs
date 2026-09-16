import crypto from "node:crypto";
export const LIMITS = Object.freeze({
  request: 16384,
  text: 2048,
  metadata: 2048,
  live: 10000,
  database: 100 * 1024 * 1024,
  walSoft: 32 * 1024 * 1024,
  walHard: 64 * 1024 * 1024,
  context: 8192,
  page: 128 * 1024,
});
export class MemoryError extends Error {
  constructor(code, extra = {}) {
    super(code);
    this.code = code;
    this.extra = extra;
  }
}
export function fail(code, extra) {
  throw new MemoryError(code, extra);
}
export function check(ok, code = "INVALID_INPUT", extra) {
  if (!ok) fail(code, extra);
}
export const bytes = (x) =>
  Buffer.byteLength(typeof x === "string" ? x : JSON.stringify(x));
export const canonical = (x) =>
  Array.isArray(x)
    ? x.map(canonical)
    : x && typeof x === "object"
      ? Object.fromEntries(
          Object.keys(x)
            .sort()
            .map((k) => [k, canonical(x[k])]),
        )
      : x;
export const stable = (x) => JSON.stringify(canonical(x));
export const digest = (x) =>
  crypto.createHash("sha256").update(x).digest("hex");
export const now = () =>
  process.env.NODE_ENV === "test" &&
  process.env.LOCAL_MEMORY_TESTING === "1" &&
  process.env.LOCAL_MEMORY_TEST_NOW
    ? Date.parse(process.env.LOCAL_MEMORY_TEST_NOW)
    : Date.now();
export const iso = () => new Date(now()).toISOString();
export const uuid = () => crypto.randomUUID();
export const identifier = (x) =>
  typeof x === "string" && /^[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,127}$/.test(x);
export const keyValid = (x) =>
  typeof x === "string" &&
  /^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$/.test(x) &&
  x.length <= 128;
export function fields(x, allowed, required = []) {
  check(x && typeof x === "object" && !Array.isArray(x));
  check(Object.keys(x).every((k) => allowed.includes(k)));
  check(required.every((k) => Object.hasOwn(x, k)));
}
export function secret(x) {
  check(
    !/(?:-----BEGIN [A-Z ]*PRIVATE KEY-----|\b(?:password|passwd|api[_ -]?key|access[_ -]?token|authorization|cookie|session(?:id|_id)?|csrf(?:token|_token)?)["']?\s*[:=]\s*["']?\S+|\bBearer\s+[a-z0-9._~+\/-]{8,}|\b(?:sk-[a-zA-Z0-9_-]{16,}|gh[pousr]_[a-zA-Z0-9]{20,}|AKIA[A-Z0-9]{16})|[a-z][a-z0-9+.-]*:\/\/[^\s:/]+:[^\s@]+@)/i.test(
      x,
    ),
    "SECRET_REJECTED",
  );
}
export function text(x) {
  check(typeof x === "string");
  x = x.replace(/\r\n?/g, "\n").normalize("NFC").trim();
  check(x.length > 0 && bytes(x) <= LIMITS.text);
  secret(x);
  return x;
}
export function provenance(p) {
  fields(
    p,
    ["kind", "skill_version", "source_ref", "observed_at"],
    ["kind", "skill_version", "source_ref", "observed_at"],
  );
  check(
    [
      "explicit_user",
      "explicit_correction",
      "confirmed_fact",
      "inferred",
    ].includes(p.kind),
  );
  check(identifier(p.skill_version) && identifier(p.source_ref));
  secret(p.skill_version);
  secret(p.source_ref);
  check(
    typeof p.observed_at === "string" &&
      Number.isFinite(Date.parse(p.observed_at)),
  );
  return { ...p, observed_at: new Date(p.observed_at).toISOString() };
}
export function point(name) {
  if (
    process.env.NODE_ENV === "test" &&
    process.env.LOCAL_MEMORY_TESTING === "1" &&
    process.env.LOCAL_MEMORY_FAIL_POINT === "foreground-timeout" &&
    name === "lock-acquired"
  )
    Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 6000);
  if (
    process.env.NODE_ENV === "test" &&
    process.env.LOCAL_MEMORY_TESTING === "1"
  ) {
    if (process.env.LOCAL_MEMORY_KILL_POINT === name)
      process.kill(process.pid, "SIGKILL");
    if (process.env.LOCAL_MEMORY_FAIL_POINT === name)
      fail("STORAGE_UNAVAILABLE");
  }
}
export const tokens = (x) =>
  x
    .normalize("NFC")
    .toLowerCase()
    .match(/[\p{L}\p{N}]+/gu) || [];
