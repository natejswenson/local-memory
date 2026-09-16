#!/usr/bin/env node
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
process.umask(0o077);
// A separate process enforces the total foreground bound, including synchronous SQLite.
const child = spawn(
  process.execPath,
  [
    "--disable-warning=ExperimentalWarning",
    fileURLToPath(new URL("../src/adapter-worker.mjs", import.meta.url)),
    process.argv[2],
    process.argv[3],
  ],
  { stdio: ["pipe", "pipe", "pipe"], env: process.env, detached: true },
);
const killTree = () => {
  try { process.kill(-child.pid, "SIGKILL"); } catch (e) {
    if (e.code !== "ESRCH") throw e;
  }
};
let output = "",
  inputBytes = 0,
  finished = false;
const finish = (value, code) => {
  if (finished) return;
  finished = true;
  clearTimeout(timer);
  process.stdin.pause();
  console.log(value);
  process.exitCode = code;
};
const timer = setTimeout(() => {
  killTree();
  finish(
    JSON.stringify({
      ok: false,
      error: {
        code: "BUSY",
        retryable: true,
        message:
          "Adapter deadline reached; reconcile the selected source key before retrying.",
      },
    }),
    3,
  );
}, 4800);
child.stdout.setEncoding("utf8");
child.stdout.on("data", (b) => {
  output += b;
  if (Buffer.byteLength(output) > 300000) {
    killTree();
    finish(
      JSON.stringify({
        ok: false,
        error: {
          code: "STORAGE_UNAVAILABLE",
          retryable: false,
          message: "Bounded response unavailable.",
        },
      }),
      3,
    );
  }
});
child.stderr.on("data", () => {});
child.stdin.on("error", () => {});
process.stdin.on("data", (b) => {
  inputBytes += b.length;
  if (inputBytes > 16384) {
    killTree();
    finish(
      JSON.stringify({
        ok: false,
        error: {
          code: "INVALID_INPUT",
          retryable: false,
          message: "Request exceeds 16384 bytes.",
        },
      }),
      2,
    );
  } else child.stdin.write(b);
});
process.stdin.on("end", () => child.stdin.end());
child.on("error", () =>
  finish(
    JSON.stringify({
      ok: false,
      error: {
        code: "STORAGE_UNAVAILABLE",
        retryable: false,
        message: "Local runtime unavailable.",
      },
    }),
    3,
  ),
);
child.on("close", (code) => {
  if (!output.trim())
    finish(
      JSON.stringify({
        ok: false,
        error: {
          code: "STORAGE_UNAVAILABLE",
          retryable: false,
          message: "No save was confirmed; replay the same mutation key.",
        },
      }),
      3,
    );
  else finish(output.trim(), code ?? 3);
});

for (const signal of ["SIGTERM", "SIGINT"])
  process.on(signal, () => {
    killTree();
    process.exit(3);
  });
