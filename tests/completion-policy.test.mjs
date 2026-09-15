import assert from 'node:assert/strict';
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';

const moduleUrl = process.env.ISSUEFLOW_COMPLETION_MODULE;
assert.ok(moduleUrl, 'setup: ISSUEFLOW_COMPLETION_MODULE must name the installed consumer file URL');
assert.equal(new URL(moduleUrl).protocol, 'file:', 'setup: consumer must be a file URL');
let consumer;
try {
  consumer = await import(moduleUrl);
} catch (cause) {
  throw new Error('setup: cannot import the installed issueflow completion consumer', { cause });
}
const { completionPolicy, assertReadyAuthority } = consumer;
assert.equal(typeof completionPolicy, 'function', 'setup: missing completionPolicy export');
assert.equal(typeof assertReadyAuthority, 'function', 'setup: missing assertReadyAuthority export');

// In-memory fixtures only: no controller persistence or provider operations.
function fixture(repoPath) {
  return {
    run: {
      schema: 5,
      repo: { path: repoPath, owner: 'example', name: 'synthetic-memory' },
      completion: { endpoint: 'reviewed-pr', excluded: [], authorizations: [] },
    },
    lane: { pr: { number: 42 }, verification: { head: 'synthetic-reviewed-head' } },
  };
}

function temporaryRepo(t, readyCanMerge) {
  const repoPath = mkdtempSync(join(tmpdir(), 'completion-policy-'));
  t.after(() => rmSync(repoPath, { recursive: true, force: true }));
  if (readyCanMerge !== undefined) {
    mkdirSync(join(repoPath, '.issueflow'));
    writeFileSync(join(repoPath, '.issueflow/completion.json'), JSON.stringify({
      schema: 1, readyCanMerge, source: 'Synthetic test policy; no external authority.',
    }));
  }
  return fixture(repoPath);
}

const mergeAuthorityError = /ready can trigger merging; the concrete merge still needs user authority/;

test('actual repository policy declares merge-capable readiness and denies missing authority', () => {
  const { run, lane } = fixture(process.cwd());
  const policy = completionPolicy(run);
  assert.equal(policy.readyCanMerge, true);
  assert.equal(policy.schema, 1);
  assert.ok(policy.source.trim());
  assert.equal(policy.path, join(process.cwd(), '.issueflow/completion.json'));
  assert.throws(() => assertReadyAuthority(run, lane, { autoMerge: null }), mergeAuthorityError);
});

test('missing policy yields unknown and refuses readiness', (t) => {
  const { run, lane } = temporaryRepo(t);
  assert.equal(completionPolicy(run).readyCanMerge, 'unknown');
  assert.throws(() => assertReadyAuthority(run, lane, { autoMerge: null }),
    /repository readiness automation is unknown/);
});

test('queued auto-merge requires merge authority even with a false policy', (t) => {
  const { run, lane } = temporaryRepo(t, false);
  assert.equal(completionPolicy(run).readyCanMerge, false);
  assert.throws(() => assertReadyAuthority(run, lane, { autoMerge: { enabledAt: 'synthetic' } }),
    mergeAuthorityError);
});

test('matching synthetic merge authority cannot bypass the expected-head precondition', (t) => {
  const { run, lane } = temporaryRepo(t, true);
  run.completion.authorizations.push({
    source: 'Synthetic fixture only', action: 'merge', repo: 'example/synthetic-memory',
    pr: lane.pr.number, head: lane.verification.head,
  });
  assert.throws(() => assertReadyAuthority(run, lane, { autoMerge: null }),
    /ready-triggered merge has no server-enforced expected-head precondition/);
});

test('the requested draft endpoint excludes readiness for both false and true policies', (t) => {
  for (const readyCanMerge of [false, true]) {
    const { run, lane } = temporaryRepo(t, readyCanMerge);
    run.completion.excluded = ['ready', 'merge'];
    assert.equal(completionPolicy(run).readyCanMerge, readyCanMerge);
    assert.throws(() => assertReadyAuthority(run, lane, { autoMerge: null }),
      /lifting draft is excluded by the requested endpoint/);
  }
});

test('a string boolean is rejected as an invalid repository completion policy', (t) => {
  const { run, lane } = temporaryRepo(t, 'true');
  assert.throws(() => completionPolicy(run), /invalid repository completion policy/);
  assert.throws(() => assertReadyAuthority(run, lane, { autoMerge: null }),
    /invalid repository completion policy/);
});

test('false policy without exclusions or queued auto-merge allows ordinary guard evaluation', (t) => {
  const { run, lane } = temporaryRepo(t, false);
  assert.equal(completionPolicy(run).readyCanMerge, false);
  assert.doesNotThrow(() => assertReadyAuthority(run, lane, { autoMerge: null }));
});
