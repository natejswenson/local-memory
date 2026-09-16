import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import os from "node:os";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
const root = fileURLToPath(new URL("..", import.meta.url));
test("packed executable discovery, separate data directory and uninstall persistence", (t) => {
  const temp = fs.mkdtempSync(path.join(os.tmpdir(), "memory-install-"));
  t.after(() => fs.rmSync(temp, { recursive: true, force: true }));
  const env = {
    ...process.env,
    npm_config_cache: path.join(temp, "cache"),
    LOCAL_MEMORY_HOME: path.join(temp, "data"),
  };
  const run = (file, args, opts = {}) => {
    const p = spawnSync(file, args, {
      cwd: root,
      env,
      encoding: "utf8",
      timeout: 10000,
      ...opts,
    });
    assert.equal(p.status, 0, p.stderr || p.stdout);
    return p.stdout;
  };
  const pack = JSON.parse(
    run("npm", [
      "pack",
      "--json",
      "--ignore-scripts",
      "--offline",
      "--pack-destination",
      temp,
    ]),
  )[0];
  const prefix = path.join(temp, "installation");
  run("npm", [
    "install",
    "--prefix",
    prefix,
    "--ignore-scripts",
    "--offline",
    path.join(temp, pack.filename),
  ]);
  const exe = path.join(prefix, "node_modules/.bin/local-memory");
  const init = JSON.parse(
    run(exe, ["manage"], {
      input: JSON.stringify({
        protocol: 1,
        op: "init",
        request_id: "installed",
      }),
    }),
  );
  assert.equal(init.initialized, true);
  run("npm", [
    "uninstall",
    "--prefix",
    prefix,
    "--ignore-scripts",
    "--offline",
    "@natejswenson/local-memory",
  ]);
  assert.ok(fs.existsSync(path.join(temp, "data/identity.json")));
  assert.ok(fs.existsSync(path.join(temp, "data/memory.sqlite3")));
});
