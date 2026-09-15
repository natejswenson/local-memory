# Completion policy

`completion.json` is operational input to issueflow's readiness guard. Its
`readyCanMerge: true` records the merge-capable code on main at
`9cef83cb2b4579a078fd662c6afaaf332d08af6a`, observed on 2026-09-15:

- [Merge automation](https://github.com/natejswenson/local-memory/blob/9cef83cb2b4579a078fd662c6afaaf332d08af6a/.github/workflows/main-automerge.yml)
  handles `ready_for_review` and invokes `gh pr merge --auto --squash` for ready
  same-repository PRs. PR #3 merged this code at 2026-09-15T18:30:32Z.
- [CI](https://github.com/natejswenson/local-memory/blob/9cef83cb2b4579a078fd662c6afaaf332d08af6a/.github/workflows/ci.yml)
  runs `repository-policy` on draft PRs to main, including synchronize events.
- [Contributor guidance](https://github.com/natejswenson/local-memory/blob/9cef83cb2b4579a078fd662c6afaaf332d08af6a/CONTRIBUTING.md)
  separates committed automation from its pending activation and describes the
  draft conditions for the optional `auto-merge` and `label-release-pending` jobs.

At that observation, repository auto-merge was disabled and PR #4 had no queued
auto-merge request. Those facts do not remove the ready-triggered merge code.
This policy neither changes automation nor activates repository settings.

## Draft endpoint and revalidation

The user selected `reviewed-pr` with `ready` and `merge` explicitly excluded for
PR #4. Keep it draft. The policy grants no authority. The installed guard rejects
an explicit ready exclusion, unknown automation, or merge-capable readiness
without concrete merge authority. Even with matching authority, it rejects the
ready-triggered merge because the ready operation lacks a server-enforced
expected-head precondition. Missing policy yields unknown; malformed policy
fails validation. A false value is an observation, never an automation switch.

Recheck the effective workflows, base, repository settings, hooks, rules,
protection, PR head/draft/auto-merge state and required check producers after
changes and before recording the reviewed endpoint. Policy or base drift needs
reviewed reconciliation. Required CI must pass on the current reviewed head;
local tests do not establish hosted CI or live enforcement. Do not use readiness
to trigger CI.

## Lookup and local tests

The consumer reads `.issueflow/completion.json` beneath `run.repo.path`, the
retained source repository root. A policy present only in an isolated lane is
insufficient. The controller's parent must safely materialize the exact committed,
reviewed policy at that source root before source-lookup verification, preserving
its branch, index and existing files. Reuse only an identical regular file; a
symlink or differing file requires drift resolution rather than overwrite.

`tests/completion-policy.test.mjs` imports the actual installed issueflow 0.17.0
`completionPolicy` and `assertReadyAuthority` via `ISSUEFLOW_COMPLETION_MODULE`.
The private verification recipe supplies its file URL and checks the reviewed
module digest. A missing/invalid import is setup failure. No consumer code or
dependency is vendored here. The tests use temporary repositories and synthetic
schema-5 run/lane objects; they do not save controller state, contact GitHub,
grant real permission or perform readiness/merge actions. The same tests run on
the frozen base and implementation: the missing base policy fails the first
true-value assertion, and the implementation must pass all seven tests.
