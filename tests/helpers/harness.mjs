import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
const root = fileURLToPath(new URL("../..", import.meta.url));
export function fixture(t) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "memory-v1-"));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const home = path.join(dir, "store");
  let n = 0;
  const raw = (op, data = {}, manage = false, extra = {}) => {
    const q = {
      protocol: 1,
      op,
      request_id: "req-" + ++n,
      ...(manage
        ? {}
        : {
            caller: identity(
              data.skill ?? "ghostwriter",
              Object.hasOwn(data, "project") ? data.project : "prj-harbor",
            ),
          }),
      ...data,
    };
    delete q.skill;
    delete q.project;
    const child = spawnSync(
      process.execPath,
      [path.join(root, "bin/local-memory.mjs"), manage ? "manage" : "request"],
      {
        input: JSON.stringify(q),
        encoding: "utf8",
        env: {
          ...process.env,
          LOCAL_MEMORY_HOME: home,
          NODE_ENV: "test",
          LOCAL_MEMORY_TESTING: "1",
          ...extra,
        },
        timeout: 6500,
      },
    );
    assert.ok(
      child.stdout.trim(),
      "CLI must return a JSON response; " + child.stderr,
    );
    const response = JSON.parse(child.stdout);
    assert.equal(
      child.status,
      response.ok
        ? 0
        : ["INVALID_INPUT", "INVALID_REQUEST"].includes(response.error.code)
          ? 2
          : [
                "STORAGE_UNAVAILABLE",
                "STORAGE_MISSING",
                "CORRUPT",
                "BUSY",
                "PURGE_PENDING",
                "NOT_INITIALIZED",
                "SCHEMA_TOO_NEW",
                "MIGRATION_REQUIRED",
              ].includes(response.error.code)
            ? 3
            : 4,
    );
    return response;
  };
  const identity = (skill, project) => {
    if (!fs.existsSync(path.join(home, "identity.json")))
      return { skill_id: skill, project_id: project };
    const cfg = JSON.parse(fs.readFileSync(path.join(home, "identity.json")));
    return {
      skill_id: skill,
      project_id: project,
      user_id: cfg.user_id,
      token: cfg.skills[skill]?.token,
    };
  };
  const good = (op, data = {}, manage = false, extra = {}) => {
    const r = raw(op, data, manage, extra);
    assert.equal(r.ok, true, JSON.stringify(r));
    return r;
  };
  const init = () => {
    good("init", {}, true);
    for (const skill_id of ["ghostwriter", "writing-peer", "other"])
      good(
        "register",
        {
          skill_id,
          keys: ["writing.hashtags", "project.acronym", "project.audience"],
          capture: true,
        },
        true,
      );
    fs.mkdirSync(path.join(dir, "project"));
    good(
      "project",
      { project_id: "prj-harbor", roots: [path.join(dir, "project")] },
      true,
    );
    fs.mkdirSync(path.join(dir, "elsewhere"));
    good(
      "project",
      { project_id: "prj-other", roots: [path.join(dir, "elsewhere")] },
      true,
    );
  };
  const input = (content = "Avoid hashtags", kind = "explicit_user") => ({
    type: "preference",
    key: "writing.hashtags",
    content,
    provenance: {
      kind,
      skill_version: "1.0.0",
      source_ref: "event-synthetic",
      observed_at: "2026-09-15T10:00:00Z",
    },
  });
  const remember = (content = "Avoid hashtags", extra = {}) =>
    good("remember", {
      idempotency_key: "save-" + ++n,
      record: input(content),
      ...extra,
    });
  return { dir, home, raw, good, init, input, remember, identity };
}
