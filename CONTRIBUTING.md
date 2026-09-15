# Contributing

## Branch, check, and merge

`main` is the default and only long-lived branch. Start feature and maintenance
work from current main and send every PR directly to main:

```sh
git switch main
git pull --ff-only
git switch -c feature/short-description
# Make and commit the change, then:
git push -u origin HEAD
gh pr create --draft --base main
```

CI runs `repository-policy` on every PR to main, including drafts, forks, and
edits that retarget a PR to main, with no path filters. It parses workflow YAML,
validates policy JSON and generated hashes,
and runs negative policy tests. Add application build/test checks when the
project exists. Keep this job name stable; it is the required status context.

Run the same tests locally using Python with PyYAML 6.0.3 installed:

```sh
python3 -B -m unittest discover -s tests -v
actionlint .github/workflows/ci.yml .github/workflows/main-automerge.yml
zizmor --no-progress .github/workflows/ci.yml .github/workflows/main-automerge.yml
```

After activation, main requires a PR and successful, up-to-date
`repository-policy` from GitHub Actions. Rules apply to administrators;
force pushes and deletion of main are prohibited. Zero mandatory approving
reviews accommodates the single-maintainer repository. Review changes before
making a PR eligible for merge. Missing or failing required checks block merge.

After activation, ready PRs from this repository use native auto-merge with
squash merging. Successful checks may complete the merge without another prompt.
Keep unfinished PRs draft: drafts intentionally skip the auto-merge job. The
`ready_for_review` event enables auto-merge when a same-repository PR becomes
ready. Opened, reopened, and synchronize events also admit ready same-repository
PRs. Never mark ready merely to hide a failure, and never use an admin bypass.

Fork PRs and PRs with a missing head repository skip both credential-using jobs.
Maintainers review fork PRs, then explicitly enable native auto-merge or merge
with their authorized credentials after required checks. For example, once
reviewed and authorized, enable it with:

```sh
gh pr merge --auto --squash NUMBER --repo natejswenson/local-memory
```

Same-repository origin does not guarantee secret availability: restricted
automation and Dependabot events may also lack the configured secret. An
unavailable explicitly named `SHIPFLOW_AUTOMERGE_PAT` produces a successful,
explicit skip before any `gh` command. It leaves automation inactive and does
not prove activation. A present but invalid credential or an API failure remains
an error to investigate.

GitHub deletes merged short-lived branches once cleanup is activated. Refresh
local references with `git fetch --prune`. Main remains protected. Release mode
is `manual-gate`: a same-repository merged PR can receive the optional
`release-pending` reminder when its credential is available. Maintainers may add
fork reminders manually. Neither job creates a tag or release; this repository
has no release workflow. Release infrastructure is future work.

## Maintainer generator source (unreleased)

The workflow and its config receipt were generated from independently reviewed
**unreleased source** in [upstream draft PR #389](https://github.com/natejswenson/claude-skills/pull/389).
The source repository is `https://github.com/natejswenson/claude-skills.git`, pinned
to commit `4b0847110915e596619593408f22be2e8309c41b`. Its package directory is
`skills/shipflow/skills/shipflow`, package name `@natjswenson/shipflow`, and metadata
version `0.6.0`. This is not a corrected published 0.6.0 package. The package Git
tree is `39187f3ec4b98374d7cb1c0a7af7e41c10cc1f23`; the template
`templates/github-flow/main-automerge.yml.tmpl` has SHA-256
`5614b69a8e3ebd7a6a81a46409073a9f549acf2297a8fc19c731893bfc54b427`.

Use a new maintainer-owned tooling checkout. Run these commands from the consumer
checkout; `SHIPFLOW_SOURCE_ROOT` is a local tooling path outside this repository.

```sh
export SHIPFLOW_SOURCE_ROOT="$HOME/tooling/shipflow-4b084711"
git clone --no-checkout https://github.com/natejswenson/claude-skills.git "$SHIPFLOW_SOURCE_ROOT"
git -C "$SHIPFLOW_SOURCE_ROOT" fetch origin 4b0847110915e596619593408f22be2e8309c41b
git -C "$SHIPFLOW_SOURCE_ROOT" checkout --detach 4b0847110915e596619593408f22be2e8309c41b
test "$(git -C "$SHIPFLOW_SOURCE_ROOT" rev-parse HEAD)" = 4b0847110915e596619593408f22be2e8309c41b || exit 1
test -z "$(git -C "$SHIPFLOW_SOURCE_ROOT" status --porcelain)" || exit 1
node "$SHIPFLOW_SOURCE_ROOT/skills/shipflow/skills/shipflow/bin/shipflow.js" --version
```

Recheck HEAD and cleanliness before each use, and stop on a mismatch. Do not
substitute the currently published old package: its template can legitimately
plan a reverse update against this preview's receipt. Never apply that downgrade.
After a corrected package is published, inspect and pin its exact version and
prove matching rendered bytes/hash before replacing these commands. Upstream
publication is separate work.

The local preview uses the source's public pattern mapping and `computePlan`.
This read-only reproduction compares the generated bytes and coupled hash without
calling GitHub or applying settings (Node.js required):

```sh
node --input-type=module <<'JS'
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import assert from 'node:assert/strict';
import { pathToFileURL } from 'node:url';
const pkg = path.join(process.env.SHIPFLOW_SOURCE_ROOT, 'skills/shipflow/skills/shipflow');
const { computePlan } = await import(pathToFileURL(path.join(pkg, 'lib/plan.mjs')));
const { templates } = await import(pathToFileURL(path.join(pkg, 'lib/patterns/github-flow/index.mjs')));
const config = JSON.parse(fs.readFileSync('.github/shipflow.json'));
const sources = Object.fromEntries(templates(config).map(entry =>
  [entry.id, fs.readFileSync(entry.templateSourcePath, 'utf8')]));
// Omit on-disk state to request rendered content, not to assert live state.
const plan = computePlan({}, config, sources);
for (const entry of plan.creates.filter(item => item.id.startsWith('template:'))) {
  assert.equal(fs.readFileSync(entry.path, 'utf8'), entry.content);
  const digest = crypto.createHash('sha256').update(entry.content).digest('hex');
  assert.equal(digest, entry.renderedHash);
  assert.equal(config.renderedTemplateHashes[entry.path], entry.renderedHash);
  console.log(entry.path, entry.renderedHash);
}
JS
```

For future regeneration, first compare the current workflow hash with its
recorded receipt, then plan with the observed local template hash. Stop on
`handEditDetected`; never force unexplained drift. Stage only the exact returned
`content` and `renderedHash` together, and replan to confirm a template noop.
The preview is not a live-apply receipt. Keep every existing config key, including
`release.releaseCredential: SHIPFLOW_AUTOMERGE_PAT`. The no-runtime-fallback
behavior applies to this explicitly named secret: an unavailable value is not
replaced by `GITHUB_TOKEN`. Omitting the configuration instead retains upstream's
legacy `GITHUB_TOKEN` default. `devToMainMethod` is the legacy key for the GitHub
Flow main merge method; squash is configured, with no dev branch.

## Maintainer activation (pending)

These files describe desired settings, not proof of live enforcement. Activation
is pending the maintainer's credential and approval of the concrete plan and
merge decisions. Do not run these mutations from CI.

1. Provision the repository Actions secret `SHIPFLOW_AUTOMERGE_PAT` using a
   suitable PAT or GitHub App installation credential with repository contents
   and pull-requests write access. Manage expiry/rotation outside source. Store
   only the secret name here; never put its value in a file, issue, or transcript.
   `GITHUB_TOKEN` suppresses the downstream closed-event reminder and is unsuitable.
2. Keep the setup PR draft. Confirm `repository-policy` succeeds on its
   current head and inspect its producer. The payload binds it to GitHub Actions
   app ID 15368; recheck that observed producer before applying protection.
   On an open draft, `auto-merge` and `label-release-pending` intentionally skip.
   Only these optional jobs accept skipped conclusions; `repository-policy`
   must succeed. Every failed job remains a blocker. An empty-token shell skip
   succeeds without a command and does not establish credential readiness.
3. Run detection and review both the exact shipflow plan and supplemental JSON
   payloads using the immutable source verified above:

   ```sh
   node "$SHIPFLOW_SOURCE_ROOT/skills/shipflow/skills/shipflow/bin/shipflow.js" --version
   node "$SHIPFLOW_SOURCE_ROOT/skills/shipflow/skills/shipflow/bin/shipflow.js" detect --repo . --main main
   node "$SHIPFLOW_SOURCE_ROOT/skills/shipflow/skills/shipflow/bin/shipflow.js" plan --repo .
   node "$SHIPFLOW_SOURCE_ROOT/skills/shipflow/skills/shipflow/bin/shipflow.js" apply --repo . --dry-run
   gh secret list --repo natejswenson/local-memory
   ```

   This pinned source owns the main deletion ruleset, cleanup, generated workflow,
   and reminder label. It does not install required PR/check/force-push protection
   or enable the repository's native auto-merge setting. The separate classic
   protection payload fills that gap. Reassess ownership if fresh detection finds
   an external settings owner; do not overwrite competing policy.
4. After concrete approval, apply protection first and read it back:

   ```sh
   gh api --method PUT repos/natejswenson/local-memory/branches/main/protection \
     --input .github/main-protection.json
   gh api repos/natejswenson/local-memory/branches/main/protection
   ```

5. Re-plan after protection changes. Use the newly returned `stateHash`, never a
   saved preview hash. Run the following only after reviewing that fresh plan:

   ```sh
   node "$SHIPFLOW_SOURCE_ROOT/skills/shipflow/skills/shipflow/bin/shipflow.js" plan --repo .
   node "$SHIPFLOW_SOURCE_ROOT/skills/shipflow/skills/shipflow/bin/shipflow.js" apply --repo . --expect-state-hash HASH_FROM_FRESH_PLAN
   ```

   Inspect every applied, skipped, and error entry. Commit generated workflow
   bytes and `renderedTemplateHashes` together whenever rendering changes.
6. Only after protection and successful required CI are confirmed, enable native
   auto-merge and cleanup using the reviewed payload:

   ```sh
   gh api --method PATCH repos/natejswenson/local-memory \
     --input .github/repository-settings.json
   ```

7. Merge the reviewed setup only with explicit authority. Once the workflow is
   on main, perform validation with separately authorized merge steps.

## Maintainer live validation and audit (pending)

Record the PR number, exact head, check name, producer, and outcomes. A local
suite is not a hosted enforcement test.

- Record credential-name presence without reading values, and inventory tags/releases
  before validation. Create a scoped validation PR in draft and observe that it
  remains unmerged and both optional jobs skip.
- Deliberately alter the recorded template hash on that validation branch.
  Observe `repository-policy` fail and GitHub report the PR blocked. Attempt an
  ordinary merge only if explicitly authorized; never use an administrative bypass.
- Restore the correct hash and observe the required check succeed on the restored
  head. Resolve automation failures. Obtain authority before making the PR
  ready or enabling its merge. Observe the `ready_for_review` run and native
  auto-merge admission; verify pending as well as failing required checks block merge.
- Observe the authorized squash merge into main and remote branch deletion.
  Confirm tags/releases did not change and the same-repository reminder behaves
  as expected after merge. A skipped or credential-less reminder is not proof of
  activation; fork reminders follow the manual path above.

Audit shipflow and the supplemental settings independently:

```sh
node "$SHIPFLOW_SOURCE_ROOT/skills/shipflow/skills/shipflow/bin/shipflow.js" plan --repo .
node "$SHIPFLOW_SOURCE_ROOT/skills/shipflow/skills/shipflow/bin/shipflow.js" apply --repo . --dry-run
gh api repos/natejswenson/local-memory/branches/main/protection
gh api repos/natejswenson/local-memory/rules/branches/main
gh api repos/natejswenson/local-memory --jq \
  '{default_branch, allow_auto_merge, delete_branch_on_merge}'
```

Check exact main targeting, PR requirement, strict status checks with
`repository-policy`/Actions producer, administrator enforcement, disabled force
push/deletion, auto-merge, and cleanup against the committed JSON. A clean
shipflow plan alone does not audit supplemental settings; its ruleset
existence check is coarse. Explain pending entries and investigate any
`handEditDetected` instead of forcing over it. Before initial activation, the
expected pending entries are deletion protection, cleanup, and the reminder
label. The generated workflow should already match the committed config.
