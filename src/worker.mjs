import { execute } from "./engine.mjs";
import { MemoryError, identifier } from "./validation.mjs";
process.stdin.setEncoding("utf8");
let input = "";
for await (const chunk of process.stdin) input += chunk;
let q;
try {
  q = JSON.parse(input);
  const response = await execute(q, {
    management: process.argv[2] === "manage",
  });
  console.log(
    JSON.stringify({ ok: true, request_id: q.request_id, ...response }),
  );
} catch (error) {
  let code = error.code || "STORAGE_UNAVAILABLE";
  if (error instanceof SyntaxError) code = "INVALID_INPUT";
  else if (!(error instanceof MemoryError)) {
    if (/locked|busy/i.test(error.message)) code = "BUSY";
    else if (
      /malformed|not a database|no such table|disk image/i.test(error.message)
    )
      code = "CORRUPT";
    else code = "STORAGE_UNAVAILABLE";
  }
  const invalid = ["INVALID_INPUT", "INVALID_REQUEST"].includes(code),
    unavailable = [
      "STORAGE_UNAVAILABLE",
      "STORAGE_MISSING",
      "CORRUPT",
      "BUSY",
      "PURGE_PENDING",
      "NOT_INITIALIZED",
      "SCHEMA_TOO_NEW",
      "MIGRATION_REQUIRED",
    ].includes(code);
  console.log(
    JSON.stringify({
      ok: false,
      request_id: identifier(q?.request_id) ? q.request_id : undefined,
      error: {
        code,
        retryable: code === "BUSY",
        message: code + "; no save was confirmed.",
        ...(error instanceof MemoryError ? error.extra : {}),
      },
    }),
  );
  process.exitCode = invalid ? 2 : unavailable ? 3 : 4;
}
