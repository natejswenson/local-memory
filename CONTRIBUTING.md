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

CI runs `repository-policy` on every PR to main, including drafts, with no path
filters. It parses workflow YAML, validates policy JSON and generated hashes,
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

Eligible PRs use native auto-merge with squash merging. Successful checks may
complete the merge without another prompt. Keep unfinished PRs draft.
GitHub prevents merging drafts, but shipflow 0.6.0 tries to enable auto-merge on
drafts and can report a failed `auto-merge` job. Such a failure is a blocker for
this setup's completion, not an accepted CI result. Investigate the failed step.
The generated workflow has no `ready_for_review` trigger: after authorized
readiness, explicitly enable auto-merge with `gh pr merge --auto --squash NUMBER`,
or let a subsequent synchronize event enable it. Never mark ready merely to
hide a failure, and never use an admin bypass.

GitHub deletes merged short-lived branches once cleanup is activated. Refresh
local references with `git fetch --prune`. Main remains protected. Release mode
is `manual-gate`: merging adds a `release-pending` reminder, not a tag or release.
This repository has no release workflow; release infrastructure is future work.

## Maintainer activation (pending)

These files describe desired settings, not proof of live enforcement. Activation
is pending the maintainer's credential and approval of the concrete plan and
merge decisions. Do not run these mutations from CI.

1. Provision the repository Actions secret `SHIPFLOW_AUTOMERGE_PAT` using a
   suitable PAT or GitHub App installation credential with repository contents
   and pull-requests write access. Manage expiry/rotation outside source. Store
   only the secret name here; never put its value in a file, issue, or transcript.
   `GITHUB_TOKEN` suppresses the downstream closed-event reminder and is unsuitable.
2. Publish the setup PR as draft. Confirm `repository-policy` succeeds on its
   current head and inspect its producer. The payload binds it to GitHub Actions
   app ID 15368; recheck that observed producer before applying protection.
   Keep failed `auto-merge` jobs unresolved until their cause is fixed; missing
   credentials and draft refusal cannot be counted as a passing setup.
3. Run detection and review both the exact shipflow plan and supplemental JSON
   payloads. A new CLI version requires inspecting its changed template first:

   ```sh
   npx -y @natjswenson/shipflow@latest --version
   npx -y @natjswenson/shipflow@latest detect --repo . --main main
   npx -y @natjswenson/shipflow@latest plan --repo .
   npx -y @natjswenson/shipflow@latest apply --repo . --dry-run
   gh secret list --repo natejswenson/local-memory
   ```

   Shipflow 0.6.0 owns the main deletion ruleset, cleanup, generated workflow,
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
   npx -y @natjswenson/shipflow@latest plan --repo .
   npx -y @natjswenson/shipflow@latest apply --repo . --expect-state-hash HASH_FROM_FRESH_PLAN
   ```

   Inspect every applied, skipped, and error entry. Commit generated workflow
   bytes and `renderedTemplateHashes` together whenever rendering changes. The
   initial files are exact plan-rendered preview bytes, not a receipt of live apply.
   `devToMainMethod` is the CLI's legacy configuration key for the GitHub Flow
   main merge method; its value is squash and no dev branch is configured.
6. Only after protection and successful required CI are confirmed, enable native
   auto-merge and cleanup using the reviewed payload:

   ```sh
   gh api --method PATCH repos/natejswenson/local-memory \
     --input .github/repository-settings.json
   ```

7. Merge the reviewed setup only with explicit authority. Once the workflow is
   on main, perform validation with separately authorized merge steps.

## Live validation and audit

Record the PR number, exact head, check name, producer, and outcomes. A local
suite is not a hosted enforcement test.

- Inventory tags/releases before validation. Create a scoped validation PR in
  draft and observe it remains unmerged.
- Deliberately alter the recorded template hash on that validation branch.
  Observe `repository-policy` fail and GitHub report the PR blocked. Attempt an
  ordinary merge only if explicitly authorized; never use an administrative bypass.
- Restore the correct hash and observe the required check succeed on the restored
  head. Resolve automation failures. Obtain authority before making the PR
  ready or enabling its merge.
- Observe the authorized squash merge into main and remote branch deletion.
  Confirm tags/releases did not change and the reminder job succeeds after merge.

Audit shipflow and the supplemental settings independently:

```sh
npx -y @natjswenson/shipflow@latest plan --repo .
npx -y @natjswenson/shipflow@latest apply --repo . --dry-run
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
