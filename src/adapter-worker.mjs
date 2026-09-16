import { adapter } from "../adapters/client.mjs";
import { MemoryError } from "../src/validation.mjs";
process.umask(0o077);
process.stdin.setEncoding("utf8");
let input = "";
try {
  for await (const b of process.stdin) {
    input += b;
    if (Buffer.byteLength(input) > 16384)
      throw new MemoryError("INVALID_INPUT");
  }
  const r = await adapter(process.argv[2], process.argv[3], JSON.parse(input));
  console.log(JSON.stringify(r));
  process.exitCode = r.ok ? 0 : 3;
} catch (e) {
  const code =
    e instanceof MemoryError
      ? e.code
      : e instanceof SyntaxError
        ? "INVALID_INPUT"
        : /locked|busy/i.test(e.message)
          ? "BUSY"
          : "STORAGE_UNAVAILABLE";
  console.log(
    JSON.stringify({
      ok: false,
      error: {
        code,
        retryable: code === "BUSY",
        message: "Adapter did not confirm memory persistence.",
      },
    }),
  );
  process.exitCode = code === "INVALID_INPUT" ? 2 : 3;
}
